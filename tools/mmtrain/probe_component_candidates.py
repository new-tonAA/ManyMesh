"""Select equal-count options per source component using cached raster views."""

import argparse
import json
from pathlib import Path
import time

import fast_simplification
import numpy as np
from PIL import Image
import trimesh

from make_refinement_pairs import collapse_mapping, load_geometry, verify_asset
from probe_contour_relocation import (
    FIT_PHASES, FIT_VIEWS, METRICS, TEST_PHASES, TEST_VIEWS, auxiliary_errors,
    measure, render, targets,
)
from probe_filter_aware_cuts import FILTERS, merge_meshes, shaded
from probe_qem_candidate_pool import POOL, qem


CUBIC, RADIUS = FILTERS["bicubic"]
RECIPES = {"qem": (7.0, (1, 1, 1)), **{name: (agg, axis) for name, agg, axis in POOL}}


def triangle_keys(triangles, vertices):
    return np.sort(triangles, axis=1) @ np.array((1, vertices, vertices ** 2), dtype=np.int64)


def source_components(vertices, faces, simplified_faces, mapping, vertex_count):
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    labels = trimesh.graph.connected_component_labels(mesh.edges, node_count=len(vertices))
    source_labels = labels[faces[:, 0]]
    remapped = mapping[faces]
    valid = np.all((remapped >= 0) & (remapped < vertex_count), axis=1)
    keys = triangle_keys(remapped[valid], vertex_count)
    output_keys = triangle_keys(simplified_faces, vertex_count)
    valid_labels = source_labels[valid]
    order = np.lexsort((valid_labels, keys))
    sorted_keys = keys[order]
    before = np.searchsorted(sorted_keys, output_keys)
    after = np.searchsorted(sorted_keys, output_keys, side="right")
    if np.any(before == after):
        raise ValueError("Missing source ownership for an output triangle")
    sorted_labels = valid_labels[order]
    owners = sorted_labels[before]
    if np.any(owners != sorted_labels[after - 1]):
        raise ValueError("Ambiguous source ownership for an output triangle")
    # Every output vertex must belong to a single source component.
    lo = np.full(vertex_count, len(vertices), dtype=np.int64)
    hi = np.full(vertex_count, -1, dtype=np.int64)
    np.minimum.at(lo, simplified_faces.ravel(), np.repeat(owners, 3))
    np.maximum.at(hi, simplified_faces.ravel(), np.repeat(owners, 3))
    if np.any((hi >= 0) & (lo != hi)):
        raise ValueError("Output triangles join separate source components")
    return source_labels, owners


def compact_indices(faces):
    used, inverse = np.unique(faces, return_inverse=True)
    return used, inverse.reshape(-1, 3)


def submesh(mesh, faces):
    vertices, _, light = mesh
    used, triangles = compact_indices(faces)
    return vertices[used], triangles, light[used]


def reduce_to_budget(vertices, faces, budget, recipe, trace=False):
    positions, indices, *history = qem(vertices, faces, budget, *RECIPES[recipe], return_trace=trace)
    if len(indices) == budget - 1 and budget + 1 < len(faces):
        positions, indices, *history = qem(
            vertices, faces, budget + 1, *RECIPES[recipe], return_trace=trace)
    if len(indices) == budget and np.all(np.isfinite(positions)):
        return shaded(positions, indices), history
    return None, []


def build_options(vertices, faces, baseline, mapping):
    positions, reduced, _ = baseline
    source_labels, output_labels = source_components(
        vertices, faces, reduced, mapping, len(positions))
    source_counts = np.bincount(source_labels, minlength=len(vertices))
    output_counts = np.bincount(output_labels, minlength=len(vertices))
    eligible = ((source_counts >= 128) & (output_counts >= 8)
                & (output_counts < source_counts))
    labels = np.flatnonzero(eligible)
    labels = labels[np.argsort(-source_counts[labels], kind="stable")][:4]
    parts, retained = [], []
    for label in labels:
        used, triangles = compact_indices(faces[source_labels == label])
        part = submesh(baseline, reduced[output_labels == label])
        options = {"originalPart": part}
        for recipe in RECIPES:
            candidate, _ = reduce_to_budget(vertices[used], triangles, len(part[1]), recipe)
            if candidate is not None:
                options[recipe] = candidate
        if len(options) > 1:
            parts.append(options)
            retained.append(label)
    fixed = submesh(baseline, reduced[~np.isin(output_labels, retained)])
    return fixed, parts


def resize(frame):
    height, width = frame.shape
    return np.asarray(Image.fromarray(frame).resize((width * 2, height * 2), CUBIC))


def insert(back, layer, index):
    color, depth, owner = back
    changed_color, changed_depth = layer
    front = (changed_depth < depth) | ((changed_depth == depth) & (index < owner))
    return np.where(front, changed_color, color), np.where(front, changed_depth, depth), front


def background(fixed, layers, selected, skip):
    color, depth = (buffer.copy() for buffer in fixed)
    owner = np.full(depth.shape, -1, dtype=np.int8)
    for index, name in enumerate(selected):
        if index != skip:
            color, depth, changed = insert((color, depth, owner), layers[index][name], index)
            owner[changed] = index
    return color, depth, owner


def crop_loss(candidate, current, filtered, target, baseline):
    ys, xs = np.nonzero(candidate != current)
    if not len(ys):
        return baseline, 0
    height, width = current.shape
    left, right = max(0, xs.min() - RADIUS), min(width, xs.max() + 1 + RADIUS)
    top, bottom = max(0, ys.min() - RADIUS), min(height, ys.max() + 1 + RADIUS)
    x0, x1 = max(0, left - RADIUS), min(width, right + RADIUS)
    y0, y1 = max(0, top - RADIUS), min(height, bottom + RADIUS)
    patch = resize(candidate[y0:y1, x0:x1])
    local = patch[2 * (top - y0):2 * (bottom - y0), 2 * (left - x0):2 * (right - x0)]
    out = np.s_[2 * top:2 * bottom, 2 * left:2 * right]
    reference = target[out]
    before = np.square(filtered[out] - reference, dtype=np.float64).sum()
    after = np.square(local - reference, dtype=np.float64).sum()
    return baseline + (after - before) / target.size, (x1 - x0) * (y1 - y0)


def score_options(packets, selected, index, names, audit):
    scores = {name: np.zeros(len(METRICS)) for name in names}
    count = area = total = 0
    crop_time = direct_time = maximum_error = 0.0
    for reference, fixed, layers in packets:
        _, _, target, coverage, thin, native = reference
        back = background(fixed, layers, selected, index)
        current, current_depth, _ = insert(back, layers[index][selected[index]], index)
        filtered = resize(current)
        base_loss = np.mean(np.square(filtered - target, dtype=np.float64))
        for name in names:
            if name == selected[index]:
                color, depth, color_loss = current, current_depth, base_loss
            else:
                color, depth, _ = insert(back, layers[index][name], index)
                start = time.perf_counter()
                color_loss, footprint = crop_loss(color, current, filtered, target, base_loss)
                crop_time += time.perf_counter() - start
                if audit:
                    start = time.perf_counter()
                    direct = np.mean(np.square(resize(color) - target, dtype=np.float64))
                    direct_time += time.perf_counter() - start
                    maximum_error = max(maximum_error, abs(color_loss - direct))
                count += 1
                area += footprint
                total += color.size
            scores[name] += [color_loss, *auxiliary_errors(color, depth, coverage, thin, native)]
    if maximum_error > 1e-12:
        raise ValueError(f"Local filtering changed MSE by {maximum_error}")
    score = {name: values / len(packets) for name, values in scores.items()}
    return score, (count, area, total, crop_time, direct_time, maximum_error)


def experiment(asset, size, whole_row, audit, anchor_on_selected):
    start = time.perf_counter()
    vertices, faces = load_geometry(asset)
    source = shaded(vertices, faces)
    target = max(8, round(len(faces) * 0.2))
    positions, faces_qem, trace = fast_simplification.simplify(
        vertices, faces, target_count=target, return_collapses=True)
    base = shaded(positions, faces_qem)
    budget = len(base[1])
    if budget != whole_row["faces"]:
        raise ValueError("Unmatched whole-mesh budget")
    whole_recipe = whole_row["selected"]
    whole, history = base, [trace]
    if whole_recipe != "qem":
        whole, history = reduce_to_budget(vertices, faces, budget, whole_recipe, anchor_on_selected)
    if whole is None:
        raise ValueError("Cannot reproduce selected whole-mesh recipe")
    anchor = whole if anchor_on_selected else base
    if anchor_on_selected:
        warp = RECIPES[whole_recipe][1]
        map_vertices = vertices * np.asarray(warp)
        trace = history[0]
    else:
        map_vertices = vertices
    mapping = collapse_mapping(map_vertices, faces, trace, anchor[1])
    fixed_mesh, options = build_options(vertices, faces, anchor, mapping)
    fit = targets(source, size, FIT_VIEWS, FIT_PHASES)
    original = measure(base, size, fit)
    whole_fit = measure(whole, size, fit)
    if not np.array_equal(whole_fit, whole_row["fit"][whole_recipe]):
        raise ValueError("Whole-mesh comparator has different fit losses")
    selected = ["originalPart"] * len(options)
    packets = []
    for reference in fit:
        basis, phase = reference[:2]
        fixed = render(fixed_mesh, basis, size, phase, 1)
        layers = [{name: render(mesh, basis, size, phase, 1) for name, mesh in choices.items()}
                  for choices in options]
        direct = render(anchor, basis, size, phase, 1)
        if any(not np.array_equal(a, b) for a, b in zip(direct, background(fixed, layers, selected, -1))):
            raise ValueError("Repartitioning changed the baseline raster")
        packets.append((reference, fixed, layers))

    statistics = np.zeros(6)
    initial = whole_fit if anchor_on_selected else original
    current = initial
    for _ in range(2):
        previous = selected.copy()
        for index, choices in enumerate(options):
            scores, counters = score_options(packets, selected, index, choices, audit)
            statistics[:5] += counters[:5]
            statistics[5] = max(statistics[5], counters[5])
            qualified = [name for name, values in scores.items()
                         if values[0] < current[0] - 1e-12
                         and np.all(values[1:3] <= initial[1:3] + 1e-12)]
            if qualified:
                selected[index] = min(qualified, key=lambda name: scores[name][0])
                current = scores[selected[index]]
        if selected == previous:
            break
    result = merge_meshes([fixed_mesh, *(part[name] for part, name in zip(options, selected))])
    if len(result[1]) != budget or not np.allclose(measure(result, size, fit), current, atol=1e-12, rtol=0):
        raise ValueError("Selected assembled mesh disagrees with cached fit")
    fit_ms = 1000 * (time.perf_counter() - start - statistics[4])
    test = {}
    del packets
    for test_size in (size, size + 32):
        refs = targets(source, test_size, TEST_VIEWS, TEST_PHASES)
        measured = {name: measure(mesh, test_size, refs).tolist()
                    for name, mesh in (("qem", base), ("whole", whole), ("parts", result))}
        if measured["whole"] != whole_row["test"][str(test_size)]["losses"][whole_recipe]:
            raise ValueError("Whole-mesh comparator has different held-out losses")
        test[str(test_size)] = measured
    return {"faces": budget, "partOptions": [list(part) for part in options], "choices": selected,
            "wholeChoice": whole_recipe, "fit": {"qem": original.tolist(), "whole": whole_fit.tolist(),
                                                 "parts": current.tolist()},
            "test": test, "offlineFitMs": fit_ms, "filterQueries": int(statistics[0]),
            "croppedPixels": int(statistics[1]), "fullPixels": int(statistics[2]),
            "cropMs": statistics[3] * 1000, "directMs": statistics[4] * 1000,
            "auditMaxMseError": statistics[5] if audit else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_roots", type=Path, nargs="+")
    parser.add_argument("--whole-reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--anchor", choices=("qem", "selected"), default="selected")
    args = parser.parse_args()
    whole = json.loads(args.whole_reference.read_text(encoding="utf-8"))
    size = whole["size"]
    if size not in (64, 96, 128) or tuple(whole["metrics"]) != METRICS:
        parser.error("Expected a matching whole-mesh candidate report")
    results = {}
    for root in args.asset_roots:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for source in sources:
            name = source["name"]
            comparator = whole["assets"].get(name)
            if name in results or comparator is None or comparator["source"] != source:
                parser.error(f"Unmatched or duplicate asset {name}")
            row = experiment(
                verify_asset(root, source), size, comparator, args.audit, args.anchor == "selected")
            results[name] = {**row, "source": source}
            test = row["test"][str(size)]
            gain = 100 * (1 - test["parts"][0] / test["whole"][0])
            print(f"{name}: {len(row['choices'])} parts, {row['choices']}, "
                  f"{gain:+.2f}% vs selected whole mesh", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {"size": size, "metrics": METRICS, "audited": args.audit,
              "anchor": args.anchor, "assets": results}
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
