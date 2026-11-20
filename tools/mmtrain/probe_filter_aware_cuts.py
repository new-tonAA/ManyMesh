"""Compare fixed upscalers on budgeted cuts of disconnected mesh components."""

import argparse
import json
from pathlib import Path
import time

import fast_simplification
import numpy as np
from PIL import Image
from scipy.ndimage import maximum_filter
import trimesh

from make_refinement_pairs import capture, load_geometry, vertex_normals, verify_asset, view_basis


FILTERS = {
    "nearest": (Image.Resampling.NEAREST, 0),
    "bilinear": (Image.Resampling.BILINEAR, 1),
    "bicubic": (Image.Resampling.BICUBIC, 2),
    "lanczos": (Image.Resampling.LANCZOS, 3),
}
BUDGET_FRACTIONS = (0.25, 0.50, 0.75)


def shaded(vertices, faces):
    vertices = vertices.astype(np.float32)
    light = 0.20 + 0.75 * np.clip(vertex_normals(vertices, faces)
                                @ np.array([0.36, 0.80, 0.48], np.float32), 0, 1)
    return vertices, faces, light


def part_mesh(vertices, faces, ratio):
    used, remapped = np.unique(faces, return_inverse=True)
    positions = vertices[used]
    triangles = remapped.reshape(-1, 3)
    if ratio < 1 and len(triangles) >= 32:
        positions, triangles = fast_simplification.simplify(
            positions, triangles, target_count=max(8, round(len(triangles) * ratio)))
        if not len(triangles):
            raise ValueError("Decimation removed an entire part")
    return shaded(positions, triangles)


def separate_parts(vertices, faces):
    edges = trimesh.Trimesh(vertices=vertices, faces=faces, process=False).edges
    labels = trimesh.graph.connected_component_labels(edges, node_count=len(vertices))
    ownership = labels[faces[:, 0]]
    if not np.all(labels[faces] == ownership[:, None]):
        raise ValueError("A triangle spans multiple component labels")
    counts = np.bincount(ownership)
    largest = np.argsort(-counts, kind="stable")
    largest = largest[counts[largest] >= 128][:6]
    fixed_faces = faces[~np.isin(ownership, largest)]
    pairs = []
    for label in largest:
        local = faces[ownership == label]
        coarse = part_mesh(vertices, local, 0.20)
        fine = part_mesh(vertices, local, 0.45)
        if len(fine[1]) <= len(coarse[1]):
            fixed_faces = np.concatenate((fixed_faces, local))
        else:
            pairs.append((coarse, fine))
    return part_mesh(vertices, fixed_faces, 0.20), pairs


def merge_meshes(parts):
    offset = 0
    triangles = []
    for vertices, faces, _ in parts:
        triangles.append(faces + offset)
        offset += len(vertices)
    return (np.concatenate([part[0] for part in parts]), np.concatenate(triangles),
            np.concatenate([part[2] for part in parts]))


def compose(fixed, layers, mask):
    color, depth = (image.copy() for image in fixed)
    for index, alternatives in enumerate(layers):
        next_color, next_depth = alternatives[(mask >> index) & 1]
        front = next_depth < depth
        np.copyto(color, next_color, where=front)
        np.copyto(depth, next_depth, where=front)
    return color, depth


def live_footprints(fixed, layers):
    # A different part with a nearer fragment in both states blocks this action.
    guaranteed_depths = [np.maximum(low[1], high[1]) for low, high in layers]
    footprints = []
    for index, (low, high) in enumerate(layers):
        blocker = fixed[1].copy()
        for other, guaranteed in enumerate(guaranteed_depths):
            if other != index:
                np.minimum(blocker, guaranteed, out=blocker)
        changed = (low[0] != high[0]) | (low[1] != high[1])
        potentially_front = np.minimum(low[1], high[1]) <= blocker
        footprints.append(changed & potentially_front)
    return footprints


def groups_for_filter(footprints, radius):
    groups = []
    for index, footprint in enumerate(footprints):
        if radius:
            footprint = maximum_filter(footprint, size=2 * radius + 1, mode="constant")
        mask = 1 << index
        separated = []
        for old_mask, old_footprint in groups:
            if np.any(footprint & old_footprint):
                mask |= old_mask
                footprint = footprint | old_footprint
            else:
                separated.append((old_mask, old_footprint))
        groups = separated + [(mask, footprint)]
    return [mask for mask, _ in groups]


def loss(color, target, filter_mode):
    output = np.asarray(Image.fromarray(color).resize(target.shape[::-1], filter_mode))
    return float(np.mean(np.square(output - target, dtype=np.float64)))


def feasible_masks(group, increments, cap):
    options = [(0, 0)]
    for index, increment in enumerate(increments):
        bit = 1 << index
        if group & bit:
            options += [(mask | bit, cost + increment) for mask, cost in options
                        if cost + increment <= cap]
    return np.array(options).T


def budget_frontier(blocks, maximum):
    frontier = [(0, 0.0, 0)]
    largest_frontier = 1
    for _, masks, costs, marginal in blocks:
        candidates = {}
        block_options = [(int(mask), faces, delta)
                         for mask, faces, delta in zip(masks, costs, marginal)]
        for old_faces, old_loss, old_mask in frontier:
            for mask, faces, delta in block_options:
                total = old_faces + faces
                if total <= maximum:
                    choice = (old_loss + delta, old_mask | mask)
                    if choice < candidates.get(total, (np.inf, 0)):
                        candidates[total] = choice
        frontier = []
        best = np.inf
        for faces, (delta, mask) in sorted(candidates.items()):
            if delta < best:
                frontier.append((faces, delta, mask))
                best = delta
        largest_frontier = max(largest_frontier, len(frontier))
    return frontier, largest_frontier


def score_view(fixed, layers, target, states, increments, limits):
    start = time.perf_counter()
    color_by_mask = {mask: compose(fixed, layers, mask)[0] for mask in states}
    direct = {
        name: np.array([loss(color_by_mask[mask], target, mode) for mask in states])
        for name, (mode, _) in FILTERS.items()
    }
    direct_ms = 1000 * (time.perf_counter() - start)

    start = time.perf_counter()
    footprints = live_footprints(fixed, layers)
    composites = {0: compose(fixed, layers, 0)[0]}
    tables, evaluations, block_sizes = {}, {}, {}
    solutions, frontier_sizes = {}, {}
    for name, (mode, radius) in FILTERS.items():
        groups = groups_for_filter(footprints, radius)
        base = loss(composites[0], target, mode)
        evaluations[name] = 1
        block_sizes[name] = [mask.bit_count() for mask in groups]
        blocks = []
        for group in groups:
            masks, costs = feasible_masks(group, increments, limits[-1])
            marginal = np.zeros(len(masks))
            for index, subset in enumerate(masks):
                if subset:
                    if subset not in composites:
                        composites[subset] = compose(fixed, layers, subset)[0]
                    marginal[index] = loss(composites[subset], target, mode) - base
                    evaluations[name] += 1
            blocks.append((group, masks, costs, marginal))
        tables[name] = (base, blocks)
        frontier, frontier_sizes[name] = budget_frontier(blocks, limits[-1])
        solutions[name] = [next(mask for faces, _, mask in reversed(frontier) if faces <= cap)
                           for cap in limits]
    accelerated_ms = 1000 * (time.perf_counter() - start)
    accelerated = {}
    for name, (base, blocks) in tables.items():
        combined = np.full(len(states), base)
        for group, masks, _, marginal in blocks:
            combined += marginal[np.searchsorted(masks, states & group)]
        accelerated[name] = combined
    discrepancy = max(np.max(np.abs(direct[name] - accelerated[name])) for name in FILTERS)
    if discrepancy > 1e-12:
        raise ValueError(f"Grouped filter loss differs from direct rendering by {discrepancy}")
    return direct, solutions, {
        "directMs": direct_ms, "groupedMs": accelerated_ms,
        "directEvaluations": len(states) * len(FILTERS), "filterEvaluations": evaluations,
        "blockSizes": block_sizes, "maxFrontierSizes": frontier_sizes,
        "largestAbsoluteError": float(discrepancy)}


def experiment(path, size, views):
    vertices, faces = load_geometry(path)
    reference_mesh = shaded(vertices, faces)
    fixed_mesh, pairs = separate_parts(vertices, faces)
    if len(pairs) < 2:
        return {"originalFaces": len(faces), "actions": len(pairs)}
    base = len(fixed_mesh[1]) + sum(len(low[1]) for low, _ in pairs)
    increments = np.array([len(high[1]) - len(low[1]) for low, high in pairs])
    limits = [base + int(fraction * increments.sum()) for fraction in BUDGET_FRACTIONS]
    states, costs = feasible_masks((1 << len(pairs)) - 1, increments, limits[-1] - base)
    costs = base + costs
    if len(states) < 2:
        return {"originalFaces": len(faces), "actions": len(pairs), "feasibleCuts": len(states)}
    rows = []
    indices = {mask: index for index, mask in enumerate(states)}
    for index in range(views):
        basis = view_basis(index, views)
        source, _ = capture(reference_mesh, basis, 4 * size)
        target = source.reshape(2 * size, 2, 2 * size, 2).mean(axis=(1, 3))
        fixed = capture(fixed_mesh, basis, size)
        layers = [tuple(capture(mesh, basis, size) for mesh in pair) for pair in pairs]

        # Check depth and radiance against rasterization of the assembled geometry.
        for mask in (0, int(states[-1])):
            cut = merge_meshes([fixed_mesh, *(pair[(mask >> i) & 1] for i, pair in enumerate(pairs))])
            assembled = capture(cut, basis, size)
            merged = compose(fixed, layers, mask)
            if any(not np.array_equal(a, b) for a, b in zip(assembled, merged)):
                raise ValueError(f"Depth composition changed the assembled cut at view {index}")

        losses, solutions, timing = score_view(
            fixed, layers, target, states, increments, [cap - base for cap in limits])
        budgets = []
        for position, limit in enumerate(limits):
            legal = np.flatnonzero(costs <= limit)
            ranked = {name: indices[masks[position]] for name, masks in solutions.items()}
            for name, selected in ranked.items():
                measured = losses[name]
                if costs[selected] > limit or measured[selected] > measured[legal].min() + 1e-12:
                    raise ValueError(f"Frontier missed exhaustive optimum at view {index}: {name}")
            nearest = ranked["nearest"]
            budgets.append({"triangleCap": limit, "numCutsAtCap": len(legal), "filters": {
                name: {"optimalMask": int(states[best]), "triangles": int(costs[best]),
                       "mse": float(losses[name][best]),
                       "nearestMaskTriangles": int(costs[nearest]),
                       "nearestMaskMse": float(losses[name][nearest])}
                for name, best in ranked.items()
            }})
        rows.append({"view": index, **timing, "budgets": budgets, "cutMse": {
            name: values.tolist() for name, values in losses.items()}})
    return {"originalFaces": len(faces), "actions": len(pairs), "baseFaces": base,
            "upgradeFaceCosts": increments.tolist(), "masks": states.tolist(),
            "triangleCounts": costs.tolist(), "views": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_roots", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=(64, 96, 128), default=96)
    parser.add_argument("--views", type=int, choices=(6, 12), default=12)
    args = parser.parse_args()
    results = {}
    for root in args.asset_roots:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for source in sources:
            name = source["name"]
            if name in results:
                parser.error(f"Duplicate asset name: {name}")
            result = experiment(verify_asset(root, source), args.size, args.views)
            results[name] = {**result, "source": source}
            print(name, result["actions"], len(result.get("masks", [])), flush=True)
    report = {"size": args.size, "views": args.views, "budgetFractions": BUDGET_FRACTIONS,
              "assets": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
