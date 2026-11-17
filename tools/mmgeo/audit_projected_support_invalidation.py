#!/usr/bin/env python3
"""Compare projected support overlap with archived filtered candidate interactions.

This is an offline selectivity preflight for a screen-space candidate invalidation index.
The input pool contains sampled initial-state Corner candidates, not a full simplification
trajectory. Axis-aligned supports are conservative and can overestimate affected pixels.
"""
import argparse
import hashlib
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
import sys

import numpy as np


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


depth = load("support_depth_pilot", "depth_candidate_pilot.py")
interaction = load("support_interaction_audit", "audit_real_candidate_interactions.py")


def rectangles_overlap(a, b):
    if a is None or b is None:
        return False
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def frame_rectangles(vertices, faces, candidates, frame, size, halo):
    angle = float(np.linspace(2.13, 2.48, 6)[frame["frame_id"]])
    transform = depth.camera(vertices, angle, size)
    projected = depth.project(vertices, transform)
    result = {}
    for cid in frame["candidateIds"]:
        result[cid] = depth.support(projected, faces, candidates[cid], transform,
                                    size, halo)
    return result


def support_fragments(projected, faces, candidate, transform, size, halo):
    """Conservative per-face old/new screen supports, with the filter halo."""
    affected = np.asarray(candidate["affected"], dtype=np.int64)
    if not len(affected):
        return []
    old = projected[faces[affected], :2]
    new = old.copy()
    target = depth.project(np.asarray([candidate["target"]]), transform)[0, :2]
    replaced = ((faces[affected] == candidate["remove"]) |
                (faces[affected] == candidate["keep"]))
    new[replaced] = target
    lo = np.floor(np.minimum(old.min(axis=1), new.min(axis=1))).astype(np.int64)
    hi = np.ceil(np.maximum(old.max(axis=1), new.max(axis=1))).astype(np.int64)
    boxes = []
    for low, high in zip(lo, hi):
        if high[0] <= 0 or high[1] <= 0 or low[0] >= size or low[1] >= size:
            continue
        x0, y0 = max(0, int(low[0]) - halo), max(0, int(low[1]) - halo)
        x1, y1 = min(size, int(high[0]) + halo), min(size, int(high[1]) + halo)
        if x0 < x1 and y0 < y1:
            boxes.append((x0, y0, x1, y1))
    return boxes


def fragmented_overlap(a, b):
    return any(rectangles_overlap(x, y) for x in a for y in b)


def summarize_frame(vertices, faces, candidates, rows, frame, size, halo,
                    interaction_epsilon, rank_floor_abs, rank_floor_rel):
    rect_by_id = frame_rectangles(vertices, faces, candidates, frame, size, halo)
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate IDs must be unique within a frame")
    if any(cid < 0 or cid >= len(candidates) for cid in ids):
        raise ValueError("candidate ID is outside the captured pool")
    n = len(ids)
    rects = [rect_by_id[cid] for cid in ids]
    projected = depth.project(vertices, depth.camera(
        vertices, float(np.linspace(2.13, 2.48, 6)[frame["frame_id"]]), size))
    transform = depth.camera(vertices, float(np.linspace(2.13, 2.48, 6)[frame["frame_id"]]), size)
    fragments = [support_fragments(projected, faces, candidates[cid], transform,
                                  size, halo) for cid in ids]

    residuals = np.stack([row["residual"] for row in rows])
    gram = residuals @ residuals.T
    energy = np.diag(gram)
    compatible = np.zeros((n, n), dtype=bool)
    screen_overlap = np.zeros((n, n), dtype=bool)
    whole_bbox_overlap = np.zeros((n, n), dtype=bool)
    vertex_sets = [set(faces[np.asarray(candidates[cid]["affected"], dtype=int)]
                       .reshape(-1).tolist()) for cid in ids]
    for i in range(n):
        for j in range(i + 1, n):
            compatible[i, j] = compatible[j, i] = not bool(vertex_sets[i] & vertex_sets[j])
            overlap = fragmented_overlap(fragments[i], fragments[j])
            screen_overlap[i, j] = screen_overlap[j, i] = overlap
            broad_overlap = rectangles_overlap(rects[i], rects[j])
            whole_bbox_overlap[i, j] = whole_bbox_overlap[j, i] = broad_overlap

    compatible_pairs = 0
    bbox_pairs = 0
    fragmented_pairs = 0
    nonzero_cross_pairs = 0
    nonzero_cross_misses = 0
    strong_pairs = 0
    strong_pair_misses = 0
    max_missed_relative = 0.0
    all_pair_false_positive = 0
    exact_cross_epsilon = 1e-14
    pair_count = n * (n - 1) // 2
    for i in range(n):
        for j in range(i + 1, n):
            if not compatible[i, j]:
                continue
            compatible_pairs += 1
            overlap = bool(screen_overlap[i, j])
            bbox_pairs += int(whole_bbox_overlap[i, j])
            fragmented_pairs += int(overlap)
            cross = float(gram[i, j])
            has_cross = abs(cross) > exact_cross_epsilon
            nonzero_cross_pairs += int(has_cross)
            nonzero_cross_misses += int(has_cross and not overlap)
            relative = abs(2.0 * cross) / max(float(energy[i] + energy[j]), 1e-30)
            strong = relative >= interaction_epsilon
            strong_pairs += int(strong)
            strong_pair_misses += int(strong and not overlap)
            if has_cross and not overlap:
                max_missed_relative = max(max_missed_relative, relative)
            all_pair_false_positive += int(overlap and not has_cross)

    reversals = 0
    reversals_above_floor = 0
    reversals_support_missed = 0
    triplets = 0
    for k in range(n):
        admissible = np.flatnonzero(compatible[k])
        for pos, i in enumerate(admissible):
            for j in admissible[pos + 1:]:
                triplets += 1
                standalone = float(energy[i] - energy[j])
                joint = float((energy[i] + energy[k] + 2 * gram[i, k]) -
                              (energy[j] + energy[k] + 2 * gram[j, k]))
                if standalone * joint >= 0:
                    continue
                reversals += 1
                total = max(float(energy[i] + energy[j] + 2 * energy[k]), 1e-30)
                above_floor = (abs(standalone) > rank_floor_abs + rank_floor_rel * total and
                               abs(joint) > rank_floor_abs + rank_floor_rel * total)
                reversals_above_floor += int(above_floor)
                if not (screen_overlap[i, k] or screen_overlap[j, k]):
                    reversals_support_missed += 1

    topology_dirty = np.count_nonzero(~compatible, axis=1)
    screen_dirty = np.count_nonzero(screen_overlap, axis=1)
    union_dirty = np.count_nonzero((~compatible) | screen_overlap, axis=1)
    screen_only = np.count_nonzero(screen_overlap & compatible, axis=1)
    return dict(
        frame=frame["frame_id"],
        candidates=n,
        supportMissing=sum(rect is None for rect in rects),
        compatiblePairs=compatible_pairs,
        allPairs=pair_count,
        bboxOverlappingCompatiblePairs=bbox_pairs,
        bboxOverlapFractionOfCompatible=bbox_pairs / max(compatible_pairs, 1),
        fragmentedSupportOverlappingCompatiblePairs=fragmented_pairs,
        fragmentedSupportOverlapFractionOfCompatible=fragmented_pairs / max(compatible_pairs, 1),
        filteredCrossPairsAboveAbs1e14=nonzero_cross_pairs,
        filteredCrossPairMisses=nonzero_cross_misses,
        filteredCrossRecall=(nonzero_cross_pairs - nonzero_cross_misses) /
                            max(nonzero_cross_pairs, 1),
        strongCrossPairs=strong_pairs,
        strongCrossPairMisses=strong_pair_misses,
        strongCrossRecall=(strong_pairs - strong_pair_misses) / max(strong_pairs, 1),
        bboxOverlapsWithoutCrossAboveAbs1e14=all_pair_false_positive,
        maxMissedCrossRelative=max_missed_relative,
        rankingTriplets=triplets,
        rankingReversals=reversals,
        rankingReversalsAboveFloor=reversals_above_floor,
        rankingReversalsWithoutContextSupportOverlap=reversals_support_missed,
        meanTopologyDirty=float(np.mean(topology_dirty)),
        meanScreenOverlapDirty=float(np.mean(screen_dirty)),
        meanUnionDirty=float(np.mean(union_dirty)),
        meanNonlocalScreenInvalidations=float(np.mean(screen_only)),
        medianNonlocalScreenInvalidations=float(np.median(screen_only)),
        p95NonlocalScreenInvalidations=float(np.percentile(screen_only, 95)),
        meanUnionDirtyFraction=float(np.mean(union_dirty) / max(n, 1)),
    )


def full_pool_invalidation(vertices, faces, candidates, sampled_ids, frame_id,
                           size, halo):
    """Query every captured candidate using per-face supports and a tile index."""
    angle = float(np.linspace(2.13, 2.48, 6)[frame_id])
    transform = depth.camera(vertices, angle, size)
    projected = depth.project(vertices, transform)
    tile_size = 8
    fragments = []
    vertex_to_candidates = [[] for _ in range(len(vertices))]
    tile_to_candidates = defaultdict(list)

    for cid, candidate in enumerate(candidates):
        affected = np.asarray(candidate["affected"], dtype=np.int64)
        boxes = support_fragments(projected, faces, candidate, transform, size, halo)
        fragments.append(boxes)
        occupied_tiles = set()
        for x0, y0, x1, y1 in boxes:
            for ty in range(y0 // tile_size, (y1 - 1) // tile_size + 1):
                for tx in range(x0 // tile_size, (x1 - 1) // tile_size + 1):
                    occupied_tiles.add((tx, ty))
        for tile in occupied_tiles:
            tile_to_candidates[tile].append(cid)
        touched = (np.unique(faces[affected].reshape(-1)) if len(affected)
                   else np.empty(0, dtype=np.int64))
        for vertex in touched:
            vertex_to_candidates[int(vertex)].append(cid)

    # Check that each fragment lies inside the established conservative whole support.
    for cid in sampled_ids:
        expected = depth.support(projected, faces, candidates[cid], transform, size, halo)
        if expected is None and fragments[cid]:
            raise ValueError(f"fragment extends beyond whole support at frame {frame_id}, candidate {cid}")
        if expected is not None:
            x0, y0, x1, y1 = expected
            if any(a < x0 or b < y0 or c > x1 or d > y1
                   for a, b, c, d in fragments[cid]):
                raise ValueError(f"fragment extends beyond whole support at frame {frame_id}, candidate {cid}")

    records = []
    for cid in sampled_ids:
        query_tiles = set()
        for x0, y0, x1, y1 in fragments[cid]:
            for ty in range(y0 // tile_size, (y1 - 1) // tile_size + 1):
                for tx in range(x0 // tile_size, (x1 - 1) // tile_size + 1):
                    query_tiles.add((tx, ty))
        broad_ids = set()
        for tile in query_tiles:
            broad_ids.update(tile_to_candidates.get(tile, ()))
        screen_ids = {other for other in broad_ids if other != cid and
                      fragmented_overlap(fragments[cid], fragments[other])}
        topology_ids = set()
        affected = np.asarray(candidates[cid]["affected"], dtype=np.int64)
        touched = (np.unique(faces[affected].reshape(-1)) if len(affected)
                   else np.empty(0, dtype=np.int64))
        for vertex in touched:
            topology_ids.update(vertex_to_candidates[int(vertex)])
        screen_ids.discard(cid)
        topology_ids.discard(cid)
        union = screen_ids | topology_ids
        records.append(dict(
            eventCandidate=cid,
            topologyDirty=len(topology_ids),
            screenSupportDirty=len(screen_ids),
            nonlocalScreenAdded=len(screen_ids - topology_ids),
            tileBroadPhaseCandidates=len(broad_ids),
            unionDirty=len(union),
            topologyDirtyFraction=len(topology_ids) / max(len(candidates) - 1, 1),
            screenSupportDirtyFraction=len(screen_ids) / max(len(candidates) - 1, 1),
            unionDirtyFraction=len(union) / max(len(candidates) - 1, 1),
        ))
    return dict(candidatePoolSize=len(candidates), sampledEvents=len(sampled_ids),
                frame=frame_id,
                meanTopologyDirty=float(np.mean([r["topologyDirty"] for r in records])),
                meanScreenSupportDirty=float(np.mean([r["screenSupportDirty"] for r in records])),
                meanNonlocalScreenAdded=float(np.mean([r["nonlocalScreenAdded"] for r in records])),
                meanTileBroadPhaseCandidates=float(np.mean([r["tileBroadPhaseCandidates"] for r in records])),
                meanUnionDirty=float(np.mean([r["unionDirty"] for r in records])),
                meanTopologyDirtyFraction=float(np.mean([r["topologyDirtyFraction"] for r in records])),
                meanScreenSupportDirtyFraction=float(np.mean([r["screenSupportDirtyFraction"] for r in records])),
                meanUnionDirtyFraction=float(np.mean([r["unionDirtyFraction"] for r in records])),
                p95UnionDirtyFraction=float(np.percentile([r["unionDirtyFraction"] for r in records], 95)),
                perEvent=records)


def analyze(capture_path, report_path, export_path, size=128, halo=6,
            interaction_epsilon=.1, rank_floor_abs=1e-12, rank_floor_rel=1e-6,
            include_full_pool=False):
    vertices, faces, candidates = depth.load_capture(capture_path)
    report = json.loads(report_path.read_text())
    settings, export_manifest, export_hash, delta_rows = interaction.read_export(export_path)
    if hashlib.sha256(capture_path.read_bytes()).hexdigest() != export_manifest["captureSha256"]:
        raise ValueError("capture hash differs from exported candidate deltas")
    if hashlib.sha256(report_path.read_bytes()).hexdigest() != export_manifest["reportSha256"]:
        raise ValueError("candidate report hash differs from exported candidate deltas")
    by_frame = {}
    for row in delta_rows:
        by_frame.setdefault(row["frame"], []).append(row)
    results = []
    for frame_data in report["frames"]:
        frame_id = int(frame_data["frame"])
        rows = by_frame.get(frame_id, [])
        ids = [int(row["id"]) for row in rows]
        if len(rows) != len(frame_data["candidates"]):
            raise ValueError("delta/report candidate counts differ")
        if set(ids) != {int(row["id"]) for row in frame_data["candidates"]}:
            raise ValueError("delta/report candidate IDs differ")
        frame = dict(frame_id=frame_id, candidateIds=ids)
        result = summarize_frame(vertices, faces, candidates, rows, frame, size, halo,
                                 interaction_epsilon, rank_floor_abs, rank_floor_rel)
        if include_full_pool:
            result["fullPoolInvalidation"] = full_pool_invalidation(
                vertices, faces, candidates, ids, frame_id, size, halo)
        results.append(result)
    return dict(
        scope=("sampled initial-state candidates only; six fixed views per asset; conservative "
               "axis-aligned projected supports with filter halo; exactness applies only to the "
               "archived linear-filter deltas"),
        asset=capture_path.stem,
        settings=dict(width=settings[0], height=settings[1], scale=settings[2],
                      sigma=settings[3],supportHaloPixels=halo,
                      interactionEpsilon=interaction_epsilon,
                      crossTermAbsoluteFloor=1e-14,
                      rankFloorAbsolute=rank_floor_abs,rankFloorRelative=rank_floor_rel),
        hashes={
            "captureSha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            "reportSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "deltaSha256": export_hash,
            "captureLoaderSha256": hashlib.sha256(Path(depth.__file__).read_bytes()).hexdigest(),
            "interactionLoaderSha256": hashlib.sha256(Path(interaction.__file__).read_bytes()).hexdigest(),
            "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        frames=results,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--halo", type=int, default=6)
    parser.add_argument("--interaction-epsilon", type=float, default=.1)
    parser.add_argument("--full-pool-support", action="store_true",
                        help="also count conservative support invalidations over every captured candidate")
    args = parser.parse_args()
    if args.size <= 0 or args.halo < 0 or args.interaction_epsilon < 0:
        parser.error("size must be positive; halo and interaction epsilon must be nonnegative")
    result = analyze(args.capture, args.report, args.export, args.size, args.halo,
                     args.interaction_epsilon, include_full_pool=args.full_pool_support)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    fields = ("compatiblePairs", "bboxOverlappingCompatiblePairs",
              "fragmentedSupportOverlappingCompatiblePairs",
              "filteredCrossPairsAboveAbs1e14", "filteredCrossPairMisses",
              "strongCrossPairs", "strongCrossPairMisses",
              "rankingReversalsAboveFloor", "rankingReversalsWithoutContextSupportOverlap",
              "meanTopologyDirty", "meanNonlocalScreenInvalidations", "meanUnionDirtyFraction")
    summaries = []
    for row in result["frames"]:
        summary = {"frame": row["frame"], **{key: row[key] for key in fields}}
        if args.full_pool_support:
            full = row["fullPoolInvalidation"]
            summary["fullPoolSize"] = full["candidatePoolSize"]
            summary["fullPoolMeanUnionDirtyFraction"] = full["meanUnionDirtyFraction"]
            summary["fullPoolP95UnionDirtyFraction"] = full["p95UnionDirtyFraction"]
            summary["fullPoolMeanNonlocalAdded"] = full["meanNonlocalScreenAdded"]
        summaries.append(summary)
    print(json.dumps({"asset": result["asset"], "frames": summaries}, indent=2))


if __name__ == "__main__":
    main()
