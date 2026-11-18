#!/usr/bin/env python3
"""Filter projected edge events by whether they change the raw coverage residual."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


def load_module(name, filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def coverage_at(pilot, positions, triangles, valid, angle, sample, size, scale):
    projected = pilot.project(positions, pilot.camera(positions, angle, size))
    face = projected[triangles][:, :, :2]
    a = face[:, 0]
    ab = face[:, 1] - a
    ac = face[:, 2] - a
    q = np.asarray(sample, dtype=np.float64)[None, :] - a
    det = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    safe = np.abs(det) > 1e-14
    denom = np.where(safe, det, 1.0)
    u = (q[:, 0] * ac[:, 1] - q[:, 1] * ac[:, 0]) / denom
    v = (ab[:, 0] * q[:, 1] - ab[:, 1] * q[:, 0]) / denom
    inside = safe & valid & (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10)
    return bool(np.any(inside))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--ids", nargs="+", type=int, required=True)
    parser.add_argument("--start", type=float, default=2.13)
    parser.add_argument("--end", type=float, default=2.48)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start or args.scale < 1:
        parser.error("positive path extent and sample scale required")

    pilot = load_module("visible_event_pilot", "depth_candidate_pilot.py")
    event_probe = load_module("visible_event_roots", "probe_projected_edge_sample_events.py")
    positions, triangles, candidates = pilot.load_capture(args.capture)
    center = 0.5 * (args.start + args.end)
    offsets = np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])
    basis = np.column_stack((np.ones(5), np.sin(offsets), np.cos(offsets),
                             np.sin(2 * offsets), np.cos(2 * offsets)))
    inv_basis = np.linalg.inv(basis)

    rows = []
    for cid in args.ids:
        if not 0 <= cid < len(candidates):
            parser.error(f"candidate ID out of range: {cid}")
        candidate = candidates[cid]
        edges = event_probe.candidate_edges(positions, triangles, candidate)
        events = []
        def project(points, angle):
            return pilot.project(points, pilot.camera(positions, angle, args.size))
        for _, a, b in edges:
            events.extend(event_probe.event_angles_for_edge(
                project, a, b, args.start, args.end, args.size, args.scale,
                inv_basis, center))
        by_sample = {}
        for angle, sx, sy in events:
            key = (sx, sy)
            by_sample.setdefault(key, set()).add(round(float(angle), 10))

        post_positions = positions.copy()
        post_positions[candidate["keep"]] = np.asarray(candidate["target"], dtype=np.float64)
        post_triangles = triangles.copy()
        post_triangles[post_triangles == candidate["remove"]] = candidate["keep"]
        post_valid = ((post_triangles[:, 0] != post_triangles[:, 1]) &
                      (post_triangles[:, 1] != post_triangles[:, 2]) &
                      (post_triangles[:, 2] != post_triangles[:, 0]))
        source_valid = np.ones(len(triangles), dtype=bool)
        affected = np.asarray(candidate["affected"], dtype=np.int64)
        local_source_triangles = triangles[affected]
        local_post_triangles = post_triangles[affected]
        local_post_valid = post_valid[affected]
        start_transform = pilot.camera(positions, args.start + 1e-7, args.size)
        start_projected = pilot.project(positions, start_transform)
        post_start_projected = pilot.project(post_positions, start_transform)
        full_rect = (0, 0, args.size, args.size)
        start_source, _ = pilot.raster(
            start_projected, local_source_triangles,
            np.ones(len(local_source_triangles), dtype=bool), full_rect, args.scale)
        start_collapsed, _ = pilot.raster(
            post_start_projected, local_post_triangles, local_post_valid,
            full_rect, args.scale)
        start_mismatch_yx = np.argwhere(start_source[:, :, 0] != start_collapsed[:, :, 0])
        start_mismatch_samples = {(int(x), int(y)) for y, x in start_mismatch_yx}

        total_events = 0
        ambiguous = 0
        residual_changes = 0
        source_changes = 0
        collapsed_changes = 0
        transitions = []
        for (sx, sy), angle_set in by_sample.items():
            ordered = sorted(angle_set)
            sample = ((sx + 0.5) / args.scale, (sy + 0.5) / args.scale)
            for i, angle in enumerate(ordered):
                left_gap = angle - (ordered[i - 1] if i else args.start)
                right_gap = (ordered[i + 1] if i + 1 < len(ordered) else args.end) - angle
                epsilon = min(1e-6, 0.2 * left_gap, 0.2 * right_gap)
                if epsilon < 1e-9:
                    ambiguous += 1
                    continue
                total_events += 1
                states = []
                for side in (-1, 1):
                    theta = angle + side * epsilon
                    src = coverage_at(pilot, positions, triangles, source_valid, theta,
                                      sample, args.size, args.scale)
                    dst = coverage_at(pilot, post_positions, post_triangles, post_valid, theta,
                                      sample, args.size, args.scale)
                    states.append((src, dst, src != dst))
                source_changes += int(states[0][0] != states[1][0])
                collapsed_changes += int(states[0][1] != states[1][1])
                changed = states[0][2] != states[1][2]
                residual_changes += int(changed)
                if changed:
                    before = int(states[0][0]) - int(states[0][1])
                    after = int(states[1][0]) - int(states[1][1])
                    transitions.append({
                        "angle": angle,
                        "sampleX": sx,
                        "sampleY": sy,
                        "before": before,
                        "after": after,
                        "delta": after - before,
                    })

        edge_event_samples = sorted(by_sample)
        support_samples = sorted(set(edge_event_samples) | start_mismatch_samples)
        rows.append({
            "candidateId": cid,
            "edgeRecords": len(edges),
            "rawEdgeSampleEventRecords": len(events),
            "uniqueSampleEventCandidates": sum(len(v) for v in by_sample.values()),
            "testedUniqueSampleEvents": total_events,
            "ambiguousNearCoincidentEvents": ambiguous,
            "sourceCoverageChanges": source_changes,
            "collapsedCoverageChanges": collapsed_changes,
            "visibleResidualCoverageChanges": residual_changes,
            "visibleResidualChangeFraction": residual_changes / max(total_events, 1),
            "edgeEventSampleCoordinates": edge_event_samples,
            "startMismatchSampleCoordinates": sorted(start_mismatch_samples),
            "sampleCoordinates": edge_event_samples,
            "supportSampleCoordinates": support_samples,
            "residualTransitions": transitions,
        })
        print(f"candidate={cid}: raw={len(events)} tested={total_events} "
              f"residualChanges={residual_changes} fraction="
              f"{residual_changes / max(total_events, 1):.4g} "
              f"supportSamples={len(support_samples)}", flush=True)

    output = {
        "scope": "candidate edge events tested against full-mesh raw coverage on both sides",
        "limitations": [
            "coverage channel only; no depth-order event or filtered-loss integration",
            "events are candidate-local edge/sample crossings, not a complete event set",
            "no wall-time comparison with exact patch redraw",
        ],
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "camera": {"start": args.start, "end": args.end, "size": args.size,
                   "scale": args.scale},
        "assets": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
