#!/usr/bin/env python3
"""Compare vectorized edge/sample roots with the existing per-edge analytic solver."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("local_events", type=Path)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--angle-tolerance", type=float, default=1e-7)
    args = parser.parse_args()

    pilot = load("batched_verify_pilot", "depth_candidate_pilot.py")
    edge_probe = load("batched_verify_edge", "probe_projected_edge_sample_events.py")
    batch_probe = load("batched_verify_batch", "probe_batched_edge_event_roots.py")
    positions, triangles, candidates = pilot.load_capture(args.capture)
    report = json.loads(args.local_events.read_text(encoding="utf-8"))
    camera = report["camera"]
    row = next(item for item in report["assets"]
               if item["candidateId"] == args.candidate_id)
    samples = np.asarray(row.get("supportSampleCoordinates", row["sampleCoordinates"]),
                         dtype=np.int64)
    edges = edge_probe.candidate_edges(positions, triangles, candidates[args.candidate_id])
    center = 0.5 * (float(camera["start"]) + float(camera["end"]))
    offsets = np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])
    basis = np.column_stack((np.ones(5), np.sin(offsets), np.cos(offsets),
                             np.sin(2 * offsets), np.cos(2 * offsets)))
    inv_basis = np.linalg.inv(basis)

    def project(points, angle):
        return pilot.project(points, pilot.camera(positions, angle, int(camera["size"])))

    old = set()
    edge_points = []
    for edge_index, (_, a, b) in enumerate(edges):
        edge_points.append((a, b))
        for angle, sx, sy in edge_probe.event_angles_for_edge(
                project, a, b, float(camera["start"]), float(camera["end"]),
                int(camera["size"]), int(camera["scale"]), inv_basis, center,
                sample_coordinates=samples):
            old.add((edge_index, sx, sy, round(float(angle), 10)))

    new = set((edge_index, sx, sy, round(angle, 10))
              for edge_index, angle, sx, sy in batch_probe.edge_event_pairs(
                  pilot, positions, edge_points, samples, float(camera["start"]),
                  float(camera["end"]), int(camera["size"]), int(camera["scale"])))

    def unmatched(source, target):
        by_key = {}
        for edge, sx, sy, angle in target:
            by_key.setdefault((edge, sx, sy), []).append(angle)
        for angles in by_key.values():
            angles.sort()
        result = []
        used = {}
        for edge, sx, sy, angle in sorted(source):
            key = (edge, sx, sy)
            choices = by_key.get(key, [])
            index = used.get(key, 0)
            if index >= len(choices):
                result.append((edge, sx, sy, angle, None))
                continue
            other = choices[index]
            used[key] = index + 1
            if abs(angle - other) > args.angle_tolerance:
                result.append((edge, sx, sy, angle, other))
        return result

    old_missing = unmatched(old, new)
    new_missing = unmatched(new, old)
    print(json.dumps({
        "candidateId": args.candidate_id,
        "candidateEdgeRecords": len(edges),
        "supportSampleCount": len(samples),
        "referenceEventCount": len(old),
        "batchedEventCount": len(new),
        "referenceNotMatchedByBatch": len(old_missing),
        "batchNotMatchedByReference": len(new_missing),
        "referenceExamples": old_missing[:8],
        "batchExamples": new_missing[:8],
        "angleTolerance": args.angle_tolerance,
    }, indent=2))


if __name__ == "__main__":
    main()
