"""Geometry-only edit support preflight for parallel, two-sided any-hit rays.

Normal-cone/silhouette logic and conservative envelopes are established tools.
This tests their composition over archived collapses; it is not a new algorithm
claim, hardware benchmark, or a robust floating-point visibility certificate.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import depth_candidate_pilot as raster
from proxy_visibility_cost_gate import require_hash


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary_chain(faces):
    coefficients = defaultdict(int)
    for tri in faces:
        for u, v in zip(tri, np.roll(tri, -1)):
            a, b = sorted((int(u), int(v)))
            coefficients[a, b] += 1 if u < v else -1
    return {edge: value for edge, value in coefficients.items() if value}


def oriented_patch(faces):
    """Find consistent patch orientation; reject nonmanifold/nonorientable patches."""
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    incidence = defaultdict(list)
    for index, tri in enumerate(faces):
        if len(set(tri)) != 3:
            return None
        for u, v in zip(tri, np.roll(tri, -1)):
            incidence[tuple(sorted((int(u), int(v))))].append((index, 1 if u < v else -1))
    adjacency = [[] for _ in faces]
    for entries in incidence.values():
        if len(entries) > 2:
            return None
        if len(entries) == 2:
            (i, si), (j, sj) = entries
            adjacency[i].append((j, -si * sj))
            adjacency[j].append((i, -si * sj))
    signs = np.zeros(len(faces), dtype=np.int64)
    for start in range(len(faces)):
        if signs[start]:
            continue
        signs[start] = 1
        stack = [start]
        while stack:
            i = stack.pop()
            for j, relative in adjacency[i]:
                needed = int(signs[i]) * relative
                if signs[j] and signs[j] != needed:
                    return None
                if not signs[j]:
                    signs[j] = needed
                    stack.append(j)
    result = faces.copy()
    result[signs < 0] = result[signs < 0][:, [0, 2, 1]]
    return result


def edit_geometry(positions, faces, keep, remove, target):
    """Four-point hull per affected face, plus a checked oriented-chain condition."""
    triangles = np.asarray(positions)[faces]
    hulls = np.concatenate((triangles, np.broadcast_to(target, (len(triangles), 1, 3))), axis=1)
    old = oriented_patch(faces)
    if old is None:
        return dict(hulls=hulls, normals=np.empty((0, 3)), chainValid=False)
    new = old.copy()
    new[new == remove] = keep
    new = new[(new[:, 0] != new[:, 1]) & (new[:, 1] != new[:, 2]) & (new[:, 2] != new[:, 0])]
    old_boundary, new_boundary = boundary_chain(old), boundary_chain(new)
    valid = old_boundary == new_boundary and not any(
        keep in edge or remove in edge for edge in old_boundary)
    new_xyz = positions[new].copy()
    new_xyz[new == keep] = target
    xyz = np.concatenate((positions[old], new_xyz))
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 1e-15):
        valid = False
    normals = normals / np.maximum(lengths[:, None], 1e-300)
    return dict(hulls=hulls, normals=normals, chainValid=bool(valid))


def direction_invariant(edit, direction):
    if not edit["chainValid"] or not len(edit["normals"]):
        return False
    dots = edit["normals"] @ np.asarray(direction)
    # Refuse grazing configurations. This is not a proved rounding-error bound.
    return bool(np.all(dots > 1e-10) or np.all(dots < -1e-10))


def box_mask(lower, upper, size=128, scale=3):
    """Union of projected boxes, sampled at the same subpixel centers as raster."""
    lower = np.asarray(lower, dtype=float).reshape(-1, 2)
    upper = np.asarray(upper, dtype=float).reshape(-1, 2)
    if lower.shape != upper.shape or not np.isfinite([lower, upper]).all():
        raise ValueError("matching finite bounds required")
    if np.any(lower > upper):
        raise ValueError("inverted box")
    extent = size * scale
    left = np.ceil(lower * scale - .5 - 1e-7).astype(np.int64)
    right = np.floor(upper * scale - .5 + 1e-7).astype(np.int64) + 1
    left, right = np.clip(left, 0, extent), np.clip(right, 0, extent)
    active = np.all(right > left, axis=1)
    x0, y0 = left[active].T
    x1, y1 = right[active].T
    difference = np.zeros((extent + 1, extent + 1), dtype=np.int64)
    for x, y, sign in ((x0, y0, 1), (x1, y0, -1), (x0, y1, -1), (x1, y1, 1)):
        np.add.at(difference, (y, x), sign)
    return difference.cumsum(0).cumsum(1)[:-1, :-1] > 0


def hull_mask(hulls, transform):
    if not len(hulls):
        return np.zeros((384, 384), bool)
    projected = raster.project(hulls.reshape(-1, 3), transform).reshape(*hulls.shape[:2], 3)
    return box_mask(projected[:, :, :2].min(1), projected[:, :, :2].max(1))


def replay(source, manifest):
    """Replay frozen actions without invoking QEM or changing their ordering."""
    snapshots = {ratio: [] for ratio in manifest["artifacts"]}
    all_edits = {ratio: [] for ratio in snapshots}
    records = {record["unit"]: record for record in manifest["units"]}
    applied = 0
    initial_parts = []
    for unit_index, unit in enumerate(source["units"]):
        if not unit["triangles"]:
            continue
        raw = np.asarray(unit["positions"], float)
        center = (raw.min(0) + raw.max(0)) * .5
        radius = max(float(np.linalg.norm(raw - center, axis=1).max()), 1e-12)
        record = records[unit_index]
        if radius != record["normalizationRadius"]:
            raise ValueError("normalization differs from archived run")
        p = (raw - center) / radius
        initial_parts.append(p.copy() * radius + center)
        f = np.asarray(unit["triangles"], dtype=np.int64).copy()
        alive = np.ones(len(f), bool)
        incident = [set() for _ in p]
        for fi, tri in enumerate(f):
            for vertex in tri:
                incident[vertex].add(fi)
        edits = []
        cursor = 0
        for level in record["levels"]:
            ratio = str(level["ratio"])
            while cursor < level["applied"]:
                action = record["actions"][cursor]
                keep, remove = action["keep"], action["remove"]
                if not np.array_equal(p[keep], action["oldKeep"]) or not np.array_equal(
                        p[remove], action["oldRemove"]):
                    raise ValueError("old endpoint does not match action")
                target = np.asarray(action["target"], float)
                affected = sorted(incident[keep] | incident[remove])
                # Work in normalized local coordinates, then restore frozen world units.
                edit = edit_geometry(p, f[affected], keep, remove, target)
                edit["hulls"] = edit["hulls"] * radius + center
                edits.append(edit)
                for fi in affected:
                    for vertex in f[fi]:
                        incident[vertex].discard(fi)
                    f[fi][f[fi] == remove] = keep
                    if len(set(f[fi])) < 3:
                        alive[fi] = False
                    else:
                        for vertex in f[fi]:
                            incident[vertex].add(fi)
                p[keep] = target
                if int(alive.sum()) != action["faces"]:
                    raise ValueError("action face count differs")
                cursor += 1
                applied += 1
            if int(alive.sum()) != level["actual"]:
                raise ValueError("snapshot face count differs")
            snapshots[ratio].append((p.copy() * radius + center, f[alive].copy()))
            all_edits[ratio].extend(edits)
    joined = {}
    for ratio, parts in snapshots.items():
        offsets = np.cumsum([0] + [len(ps) for ps, _ in parts[:-1]])
        joined[ratio] = (np.concatenate([ps for ps, _ in parts]),
                         np.concatenate([fs + offset for (_, fs), offset in zip(parts, offsets)]))
    return joined, all_edits, applied, np.concatenate(initial_parts)


def unmatched_triangles(positions, faces, coarse_positions, coarse_faces):
    """Exact coordinate sets; orientation and duplicate multiplicity irrelevant to any-hit."""
    old = positions[faces]
    new = coarse_positions[coarse_faces]
    def key(triangle):
        return tuple(sorted(tuple(map(float, point)) for point in triangle))
    old_keys = [key(t) for t in old]
    new_keys = [key(t) for t in new]
    old_set, new_set = set(old_keys), set(new_keys)
    different = [t for k, t in zip(old_keys, old) if k not in new_set]
    different.extend(t for k, t in zip(new_keys, new) if k not in old_set)
    return np.asarray(different, float).reshape(-1, 3, 3), len(old_set & new_set)


def mask_stats(mask, fine, mismatch, cohort):
    return dict(samples=int(mask.size), fallbackSamples=int(mask.sum()),
                fallbackInsideSourceRectangle=int(np.count_nonzero(mask & cohort)),
                fallbackOnFineHits=int(np.count_nonzero(mask & fine)),
                fallbackOnFineMisses=int(np.count_nonzero(mask & ~fine)),
                missedDisagreements=int(np.count_nonzero(mismatch & ~mask)))


def run_asset(root, asset, output_dir):
    started = time.perf_counter()
    directory = root / "out/progressive-baseline" / asset
    capture = root / "out/filter-real-candidates" / (asset + ".json")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation_path = directory / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    require_hash(capture, manifest["captureSha256"])
    require_hash(manifest_path, evaluation["manifestSha256"])
    require_hash(raster.__file__, evaluation["rasterSha256"])
    source = json.loads(capture.read_text(encoding="utf-8"))
    meshes, edits, actions, roundtrip_source = replay(source, manifest)
    rows, hulls, endpoints = {}, {}, {}
    fine, faces, _ = raster.load_capture(capture)
    for ratio, (ps, fs) in meshes.items():
        artifact = manifest["artifacts"][ratio]
        path = root / Path(artifact["path"].replace("\\", "/"))
        require_hash(path, artifact["sha256"])
        with np.load(path, allow_pickle=False) as data:
            if not (np.array_equal(ps, data["positions"]) and np.array_equal(fs, data["triangles"])):
                raise ValueError("replay did not reproduce exact snapshot")
        hulls[ratio] = np.concatenate([edit["hulls"] for edit in edits[ratio]])
        # Avoid making unchanged faces look edited solely due to affine roundoff.
        # Its coverage is checked against the original capture at every view below.
        endpoints[ratio], common = unmatched_triangles(roundtrip_source, faces, ps, fs)
        rows[ratio] = dict(actualTriangles=len(fs), edits=len(edits[ratio]),
            invalidChains=sum(not edit["chainValid"] for edit in edits[ratio]),
            historyHulls=len(hulls[ratio]), unmatchedEndpointTriangles=len(endpoints[ratio]),
            exactCommonTriangles=common, artifact=dict(path=str(path), sha256=digest(path)), views=[])
    archives = defaultdict(list)
    for vi, angle in enumerate(np.linspace(0, 2 * np.pi, 12, endpoint=False)):
        transform = raster.camera(fine, float(angle), 128)
        projected = raster.project(fine, transform)
        raw, _ = raster.raster(projected, faces, np.ones(len(faces), bool), (0, 0, 128, 128), 3)
        cover = raw[..., 0].astype(bool)
        roundtrip_raw, _ = raster.raster(raster.project(roundtrip_source, transform), faces,
                                         np.ones(len(faces), bool), (0, 0, 128, 128), 3)
        if not np.array_equal(roundtrip_raw[..., 0].astype(bool), cover):
            raise ValueError("normalization roundtrip changed finite coverage")
        cohort = box_mask([projected[:, :2].min(0)], [projected[:, :2].max(0)])
        if np.any(cover & ~cohort):
            raise ValueError("source screen rectangle lost a fine hit")
        archives["fine"].append(cover)
        archives["source_rectangle"].append(cohort)
        for ratio, (ps, fs) in meshes.items():
            candidate, _ = raster.raster(raster.project(ps, transform), fs,
                                         np.ones(len(fs), bool), (0, 0, 128, 128), 3)
            coarse = candidate[..., 0].astype(bool)
            mismatch = cover != coarse
            if int(mismatch.sum()) != evaluation["levels"][ratio]["views"][vi]["rawCoverageChanged"]:
                raise ValueError("fresh coverage differs from archived evaluation")
            invariant = [direction_invariant(edit, transform[2][2]) for edit in edits[ratio]]
            selected = [edit["hulls"] for edit, safe in zip(edits[ratio], invariant) if not safe]
            uncertain = np.concatenate(selected) if selected else np.empty((0, 4, 3))
            masks = dict(historyBoxes=hull_mask(hulls[ratio], transform),
                         coneFilteredBoxes=hull_mask(uncertain, transform),
                         endpointBoxes=hull_mask(endpoints[ratio], transform))
            if np.any(masks["coneFilteredBoxes"] & ~masks["historyBoxes"]):
                raise ValueError("filtered support is not a subset of its baseline")
            stats = {name: mask_stats(mask, cover, mismatch, cohort) for name, mask in masks.items()}
            if any(row["missedDisagreements"] for row in stats.values()):
                raise ValueError(f"finite-grid support false negative: {asset} {ratio} {vi} {stats}")
            rows[ratio]["views"].append(dict(index=vi, angle=float(angle),
                disagreements=int(mismatch.sum()), fineHits=int(cover.sum()),
                sourceRectangleSamples=int(cohort.sum()), invariantEdits=sum(invariant), masks=stats))
            archives["coarse_" + ratio].append(coarse)
            for name, mask in masks.items():
                archives[name + "_" + ratio].append(mask)
        print(asset, "view", vi, "three supports checked", flush=True)
    mask_path = output_dir / (asset + "-masks.npz")
    np.savez_compressed(mask_path, **{key: np.asarray(value) for key, value in archives.items()})
    for row in rows.values():
        row["totals"] = {name: {key: sum(view["masks"][name][key] for view in row["views"])
                                        for key in row["views"][0]["masks"][name]}
                         for name in ("historyBoxes", "coneFilteredBoxes", "endpointBoxes")}
        row["fineHits"] = sum(view["fineHits"] for view in row["views"])
        row["sourceRectangleSamples"] = sum(view["sourceRectangleSamples"] for view in row["views"])
        row["disagreements"] = sum(view["disagreements"] for view in row["views"])
    return dict(asset=asset, sourceTriangles=len(faces), replayedActions=actions,
        capture=dict(path=str(capture), sha256=digest(capture)),
        manifest=dict(path=str(manifest_path), sha256=digest(manifest_path)),
        archivedEvaluation=dict(path=str(evaluation_path), sha256=digest(evaluation_path)),
        maskArtifact=dict(path=str(mask_path), sha256=digest(mask_path)),
        normalizationRoundtripCoverageVerified=True,
        sourceVerticesWithRoundtripChange=int(np.any(fine != roundtrip_source, axis=1).sum()),
        levels=rows, pythonSeconds=time.perf_counter() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    assets = [run_asset(args.root, asset, args.out) for asset in ("torus", "monkey", "pirate")]
    report = dict(schema=1, scope="parallel-ray finite coverage support; no shading/first-hit guarantee",
        scriptSha256=digest(__file__), rasterSha256=digest(raster.__file__),
        helperSha256=digest(Path(__file__).with_name("proxy_visibility_cost_gate.py")),
        caveats=["normal cones/envelopes are prior art; no standalone novelty claim",
                 "finite-grid no-false-negative checks are not robust real-arithmetic certification",
                 "endpoint matching uses roundtrip source coordinates; all 36 source coverages rechecked",
                 "screen-space boxes are rebuilt for each fixed view; no runtime hierarchy implemented",
                 "fallback fraction is not conditional fine-query cost or end-to-end speedup",
                 "source rectangle is a screen-cohort control, not a measured BVH traversal",
                 "static binary two-sided coverage only; no attributes, lighting, transparency, or materials",
                 "three reused development assets; no unseen asset or continuous-camera result"], assets=assets)
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("wrote", args.out / "report.json", flush=True)


if __name__ == "__main__":
    main()
