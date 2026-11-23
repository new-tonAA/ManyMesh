#!/usr/bin/env python3
"""Compare exact shared-envelope events against dense local depth redraw samples.

This is a 1D software raster surrogate: at each midpoint on an orthographic translation path,
source and candidate local triangles are depth-tested against the same cached common-scene
envelope. It is a stronger baseline than rebuilding all triangle lines per candidate, but it is
not a 2D/GPU renderer benchmark.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from probe_real_collapse_depth_events import (
    DEFAULT_CAPTURE,
    FILTER_OFFSETS,
    FILTER_WEIGHTS,
    camera_coordinates,
    camera_frame,
    exact_envelope_overlay,
    mesh_lines,
    mesh_lines_for_ids,
    upper_envelope,
    visible_with_envelope,
)
from probe_shared_depth_envelope_batch import candidate_geometry, choose_local_candidates


def dense_midpoint_energy(sample_cache, path, steps):
    lo, hi = map(float, path)
    dt = (hi - lo) / steps
    energy = 0.0
    for step in range(steps):
        t = lo + (step + 0.5) * dt
        coverage = 0.0
        depth = 0.0
        for common, source_local, candidate_local, weight in sample_cache:
            source = visible_with_envelope(common, source_local, t)
            candidate = visible_with_envelope(common, candidate_local, t)
            coverage += weight * (int(source is not None) - int(candidate is not None))
            if source is not None:
                depth += weight * (source["slope"] * t + source["intercept"])
            if candidate is not None:
                depth -= weight * (candidate["slope"] * t + candidate["intercept"])
        energy += (coverage * coverage + depth * depth) * dt
    return energy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--seed-candidate", type=int, default=44000)
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--steps", type=int, nargs="+", default=[128, 512, 2048, 8192])
    parser.add_argument("--out", type=Path,
                        default=Path("out/shared-envelope-dense-redraw-20261119.json"))
    args = parser.parse_args()
    if any(step <= 0 for step in args.steps):
        parser.error("all --steps values must be positive")

    data = json.loads(args.capture.read_text(encoding="utf-8"))
    unit = data["units"][0]
    raw_positions = unit["positions"]
    triangles = [list(map(int, face)) for face in unit["triangles"]]
    candidates = unit["candidates"]
    candidate_ids = choose_local_candidates(
        candidates, triangles, args.seed_candidate, args.candidate_limit)
    frame = camera_frame(raw_positions, args.angle)
    positions = camera_coordinates(raw_positions, frame).tolist()

    batch_local_faces = set()
    batch_vertices = set()
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        _post, _faces, _valid, local = candidate_geometry(positions, triangles, candidate)
        batch_local_faces.update(local)
        batch_vertices.update(map(int, (candidate["remove"], candidate["keep"])))
    for face_id in tuple(batch_local_faces):
        batch_vertices.update(triangles[face_id])

    xs = [positions[v][0] for v in batch_vertices]
    ys = [positions[v][1] for v in batch_vertices]
    sample_center_x = 0.5 * (min(xs) + max(xs))
    sample_y = 0.5 * (min(ys) + max(ys))
    radius = max(0.02, 0.75 * (max(xs) - min(xs)))
    path = (-radius, radius)
    common_face_ids = [i for i in range(len(triangles)) if i not in batch_local_faces]

    sample_sources = []
    common_envelopes = []
    common_setup_seconds = 0.0
    for offset in FILTER_OFFSETS:
        sample_x = sample_center_x + offset
        started = time.perf_counter()
        source_lines = mesh_lines(positions, triangles, sample_y, sample_x, path)
        common_setup_seconds += time.perf_counter() - started
        source_by_face = {line["face"]: line for line in source_lines}
        common_lines = [source_by_face[i] for i in common_face_ids if i in source_by_face]
        union_source_lines = [source_by_face[i] for i in batch_local_faces
                              if i in source_by_face]
        started = time.perf_counter()
        envelope, _events, _depth_events = upper_envelope(common_lines, path)
        common_setup_seconds += time.perf_counter() - started
        sample_sources.append((sample_x, source_by_face, union_source_lines))
        common_envelopes.append(envelope)

    step_totals = {step: {"seconds": 0.0, "absoluteErrorSum": 0.0,
                          "maxRelativeError": 0.0} for step in args.steps}
    candidate_rows = []
    exact_total_seconds = 0.0
    local_setup_seconds = 0.0
    nonzero_count = 0
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        post_positions, faces_by_id, valid_faces, local_faces = candidate_geometry(
            positions, triangles, candidate)
        local_set = set(local_faces)
        unchanged_union_ids = batch_local_faces - local_set
        sample_cache = []
        local_started = time.perf_counter()
        for sample_index, (sample_x, source_by_face, union_source_lines) in enumerate(sample_sources):
            unchanged_union_lines = [source_by_face[i] for i in unchanged_union_ids
                                     if i in source_by_face]
            candidate_local = mesh_lines_for_ids(
                post_positions, faces_by_id, local_faces, sample_y, sample_x, path)
            sample_cache.append((common_envelopes[sample_index], union_source_lines,
                                 unchanged_union_lines + candidate_local,
                                 FILTER_WEIGHTS[sample_index]))
        local_setup_seconds += time.perf_counter() - local_started

        exact_started = time.perf_counter()
        exact_energy, _event_count, _depth_count = exact_envelope_overlay(sample_cache, path)
        exact_seconds = time.perf_counter() - exact_started
        exact_total_seconds += exact_seconds
        if exact_energy > 1e-12:
            nonzero_count += 1

        per_candidate = {"candidateId": candidate_id, "exactEnergy": exact_energy,
                         "exactSeconds": exact_seconds, "dense": []}
        for step in args.steps:
            started = time.perf_counter()
            dense_energy = dense_midpoint_energy(sample_cache, path, step)
            elapsed = time.perf_counter() - started
            abs_error = abs(dense_energy - exact_energy)
            relative_error = abs_error / max(abs(exact_energy), 1e-12)
            aggregate = step_totals[step]
            aggregate["seconds"] += elapsed
            aggregate["absoluteErrorSum"] += abs_error
            aggregate["maxRelativeError"] = max(aggregate["maxRelativeError"], relative_error)
            per_candidate["dense"].append({
                "steps": step, "energy": dense_energy, "seconds": elapsed,
                "absoluteError": abs_error, "relativeError": relative_error,
            })
        candidate_rows.append(per_candidate)

    output = {
        "scope": "1D orthographic scanline; cached common envelope; local face depth redraw at path midpoints",
        "warning": "software raster surrogate only; not a 2D/GPU renderer or production local-redraw benchmark",
        "captureSha256": __import__("hashlib").sha256(args.capture.read_bytes()).hexdigest(),
        "seedCandidate": args.seed_candidate,
        "cameraAngle": args.angle,
        "candidateIds": candidate_ids,
        "candidateCount": len(candidate_ids),
        "nonzeroExactCandidates": nonzero_count,
        "sourceTriangles": len(triangles),
        "batchLocalFaceUnion": len(batch_local_faces),
        "filterSampleCount": len(FILTER_OFFSETS),
        "sampleCenter": [sample_center_x, sample_y],
        "path": path,
        "sharedCommonSetupSeconds": common_setup_seconds,
        "candidateLocalSetupSeconds": local_setup_seconds,
        "exactCandidateEventSeconds": exact_total_seconds,
        "denseTotals": {str(step): values for step, values in step_totals.items()},
        "candidateResults": candidate_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidateCount": output["candidateCount"],
        "nonzeroExactCandidates": nonzero_count,
        "sharedCommonSetupSeconds": common_setup_seconds,
        "candidateLocalSetupSeconds": local_setup_seconds,
        "exactCandidateEventSeconds": exact_total_seconds,
        "denseTotals": output["denseTotals"],
        "maxDenseRelativeError": max(v["maxRelativeError"] for v in step_totals.values()),
    }, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
