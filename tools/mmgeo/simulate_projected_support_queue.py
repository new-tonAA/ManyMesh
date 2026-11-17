#!/usr/bin/env python3
"""Replay a small fixed candidate pool under oracle, support, and stale-key queues.

This is an offline experiment. It uses the archived initial legal candidate set, rejects
topologically conflicting candidates after each accepted collapse, and does not regenerate
new local candidates. The renderer and finite image filter match depth_candidate_pilot.py.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load_depth():
    path = Path(__file__).with_name("depth_candidate_pilot.py")
    spec = importlib.util.spec_from_file_location("queue_depth_pilot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


depth = load_depth()


def overlaps(a, b):
    return (a is not None and b is not None and a[0] < b[2] and b[0] < a[2] and
            a[1] < b[3] and b[1] < a[3])


def valid_faces(faces):
    return ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) &
            (faces[:, 2] != faces[:, 0]))


def scene_images(world, faces, transforms, size, scale):
    images = []
    valid = valid_faces(faces)
    for transform in transforms:
        projected = depth.project(world, transform)
        image, _ = depth.raster(projected, faces, valid, (0, 0, size, size), scale)
        images.append((projected, image))
    return images


def candidate_supports(world, faces, candidates, ids, transforms, size, halo):
    result = {cid: [] for cid in ids}
    for transform in transforms:
        projected = depth.project(world, transform)
        for cid in ids:
            result[cid].append(depth.support(projected, faces, candidates[cid], transform,
                                             size, halo))
    return result


def score_candidate(world, faces, candidates, cid, transforms, current_images,
                    current_filtered_images, reference_filtered,
                    size, scale, sigma, halo):
    candidate = candidates[cid]
    total_delta = 0.0
    start = time.perf_counter()
    for view, transform in enumerate(transforms):
        projected, current_raw = current_images[view]
        rect = depth.support(projected, faces, candidate, transform, size, halo)
        if rect is None:
            continue
        proposed_positions, proposed_faces, proposed_valid = depth.edited_geometry(
            projected, faces, candidate, transform)
        delta, _ = depth.patch_residual(proposed_positions, proposed_faces,
                                        proposed_valid, rect, scale, sigma, current_raw)
        x0, y0, x1, y1 = rect
        residual = (current_filtered_images[view][y0:y1, x0:x1] -
                    reference_filtered[view][y0:y1, x0:x1])
        total_delta += float(2.0 * np.sum(residual * delta) + np.sum(delta * delta))
    return total_delta, time.perf_counter() - start


def total_error(current_images, reference_filtered, sigma, scale):
    return sum(float(np.square(depth.filtered(raw, sigma, scale) - ref).sum())
               for (_, raw), ref in zip(current_images, reference_filtered))


def run_policy(name, initial_world, initial_faces, candidates, ids, transforms,
               reference_filtered, size, scale, sigma, halo, steps):
    world = initial_world.copy()
    faces = initial_faces.copy()
    current_images = scene_images(world, faces, transforms, size, scale)
    current_filtered_images = [depth.filtered(raw, sigma, scale) for _, raw in current_images]
    index_start = time.perf_counter()
    supports = candidate_supports(world, faces, candidates, ids, transforms, size, halo)
    index_build_seconds = time.perf_counter() - index_start
    active = set(ids)
    cache = {}
    score_seconds = 0.0
    evaluations = 0
    for cid in sorted(active):
        cache[cid], elapsed = score_candidate(world, faces, candidates, cid, transforms,
                                              current_images, current_filtered_images,
                                              reference_filtered,
                                              size, scale, sigma, halo)
        score_seconds += elapsed
        evaluations += 1
    audit_seconds = 0.0
    audit_evaluations = 0
    query_seconds = 0.0
    rerender_seconds = 0.0
    records = []
    for step in range(steps):
        if not active:
            break
        oracle_scores = {}
        if name == "fullOracle" and step:
            for cid in sorted(active):
                cache[cid], elapsed = score_candidate(
                    world, faces, candidates, cid, transforms, current_images,
                    current_filtered_images, reference_filtered, size, scale, sigma, halo)
                score_seconds += elapsed
                evaluations += 1

        if name == "fullOracle":
            oracle_scores = {cid: cache[cid] for cid in active}
        elif step == 0:
            oracle_scores = {cid: cache[cid] for cid in active}
        else:
            audit_start = time.perf_counter()
            for cid in sorted(active):
                oracle_scores[cid], _ = score_candidate(
                    world, faces, candidates, cid, transforms, current_images,
                    current_filtered_images, reference_filtered, size, scale, sigma, halo)
            audit_seconds += time.perf_counter() - audit_start
            audit_evaluations += len(active)

        exact_before = total_error(current_images, reference_filtered, sigma, scale)
        if name == "fullOracle":
            # cache has just been fully refreshed in this state.
            pass
        selected = min(active, key=lambda cid: (cache[cid], cid))
        true_selected = oracle_scores[selected]
        oracle_cost = min(oracle_scores.values())

        event_support = supports[selected]
        event_vertices = set(initial_faces[np.asarray(candidates[selected]["affected"], dtype=int)]
                             .reshape(-1).tolist())
        conflicting = {cid for cid in active if cid != selected and event_vertices &
                       set(initial_faces[np.asarray(candidates[cid]["affected"], dtype=int)]
                           .reshape(-1).tolist())}
        surviving = active - conflicting - {selected}

        world[candidates[selected]["keep"]] = np.asarray(candidates[selected]["target"], dtype=float)
        faces[faces == candidates[selected]["remove"]] = candidates[selected]["keep"]
        render_start = time.perf_counter()
        current_images = scene_images(world, faces, transforms, size, scale)
        current_filtered_images = [depth.filtered(raw, sigma, scale) for _, raw in current_images]
        rerender_seconds += time.perf_counter() - render_start
        exact_after = total_error(current_images, reference_filtered, sigma, scale)

        if name == "screenSupport":
            query_start = time.perf_counter()
            dirty = {cid for cid in surviving if any(
                overlaps(a, b) for a, b in zip(supports[cid], event_support))}
            query_seconds += time.perf_counter() - query_start
            for cid in sorted(dirty):
                cache[cid], elapsed = score_candidate(
                    world, faces, candidates, cid, transforms, current_images,
                    current_filtered_images, reference_filtered, size, scale, sigma, halo)
                score_seconds += elapsed
                evaluations += 1
        else:
            dirty = set()
        active = surviving
        cache = {cid: cache[cid] for cid in active}
        records.append(dict(
            step=step,
            selectedCandidate=selected,
            selectedCachedDelta=true_selected,
            exactMinimumDelta=oracle_cost,
            selectionRegret=true_selected - oracle_cost,
            invalidatedByTopology=len(conflicting),
            invalidatedByScreen=len(dirty),
            activeAfter=len(active),
            errorBefore=exact_before,
            errorAfter=exact_after,
            measuredDelta=exact_after - exact_before,
        ))
    return dict(policy=name, initialCandidates=len(ids), scoreEvaluations=evaluations,
                scoreEvaluationSeconds=score_seconds, finalError=(records[-1]["errorAfter"]
                                                                  if records else 0.0),
                supportIndexBuildSeconds=index_build_seconds,
                invalidationQuerySeconds=query_seconds,
                oracleAuditEvaluations=audit_evaluations,
                oracleAuditSeconds=audit_seconds,
                stateRerenderSeconds=rerender_seconds,
                steps=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, nargs="+", default=[0, 3])
    parser.add_argument("--angles", type=float, nargs="+",
                        help="optional camera angles; defaults to the archived narrow arc")
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--candidates", type=int, default=48)
    parser.add_argument("--seed", type=int,
                        help="sample a reproducible uniform subset from the full legal capture")
    parser.add_argument("--report-union", action="store_true",
                        help="sample from the union of candidate IDs listed across report frames")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--sigma", type=float, default=.9)
    parser.add_argument("--halo", type=int, default=6)
    args = parser.parse_args()
    if min(args.steps, args.candidates, args.size, args.scale) < 1 or args.halo < 0:
        parser.error("steps, candidates, size, and scale must be positive; halo nonnegative")

    world, faces, candidates = depth.load_capture(args.capture)
    report = json.loads(args.report.read_text())
    if args.report_union:
        pool_ids = sorted({int(row["id"])
                           for frame in report["frames"]
                           for row in frame["candidates"]})
        if len(pool_ids) < args.candidates:
            raise ValueError("report union has fewer candidates than requested")
        ids = np.random.default_rng(args.seed if args.seed is not None else 0).choice(
            pool_ids, size=args.candidates, replace=False).astype(int).tolist()
    elif args.seed is None:
        frame0_ids = [int(row["id"]) for row in report["frames"][0]["candidates"]]
        ids = frame0_ids[:args.candidates]
    else:
        ids = np.random.default_rng(args.seed).choice(
            len(candidates), size=args.candidates, replace=False).astype(int).tolist()
    if len(ids) != args.candidates:
        raise ValueError("report has fewer candidates than requested")
    if any(cid < 0 or cid >= len(candidates) for cid in ids):
        raise ValueError("candidate id outside capture")
    angles = (np.asarray(args.angles, dtype=float) if args.angles is not None
              else np.linspace(2.13, 2.48, 6))
    if max(args.views) >= len(angles):
        parser.error("each view index must address a supplied camera angle")
    transforms = [depth.camera(world, float(angles[index]), args.size) for index in args.views]
    initial = scene_images(world, faces, transforms, args.size, args.scale)
    reference_filtered = [depth.filtered(raw, args.sigma, args.scale) for _, raw in initial]
    policies = [run_policy(name, world, faces, candidates, ids, transforms,
                           reference_filtered, args.size, args.scale, args.sigma,
                           args.halo, args.steps)
                for name in ("fullOracle", "screenSupport", "topologyLazy")]
    result = dict(
        scope=("fixed initial legal candidate subset; accepted candidates invalidate all candidates "
               "sharing affected vertices; no candidate regeneration; sampled views only"),
        settings=dict(views=args.views, size=args.size, scale=args.scale,
                      sigma=args.sigma, halo=args.halo, requestedSteps=args.steps,
                      angles=angles.tolist(), seed=args.seed, candidateIds=ids),
        inputs={
            "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
            "reportSha256": hashlib.sha256(args.report.read_bytes()).hexdigest(),
            "rendererSha256": hashlib.sha256(Path(depth.__file__).read_bytes()).hexdigest(),
            "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        policies=policies,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"asset": args.capture.stem,
                      "policies": [{"policy": p["policy"],
                                    "scoreEvaluations": p["scoreEvaluations"],
                                    "scoreEvaluationSeconds": p["scoreEvaluationSeconds"],
                      "supportIndexBuildSeconds": p["supportIndexBuildSeconds"],
                      "invalidationQuerySeconds": p["invalidationQuerySeconds"],
                      "oracleAuditEvaluations": p["oracleAuditEvaluations"],
                                    "finalError": p["finalError"],
                                    "steps": p["steps"]} for p in policies]}, indent=2))


if __name__ == "__main__":
    main()
