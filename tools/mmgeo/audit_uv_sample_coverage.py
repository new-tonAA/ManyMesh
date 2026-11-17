#!/usr/bin/env python3
"""Check that source-UV samples are found again by the UV-bin hit query."""

import argparse
import bisect
import hashlib
import importlib.util
import json
import random
from pathlib import Path
from collections import Counter


def load_uv_module():
    path = Path(__file__).with_name("measure_lod_uv_transport.py")
    spec = importlib.util.spec_from_file_location("measure_lod_uv_transport", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    uv = load_uv_module()
    mesh = uv.prepare(args.source)
    target_mesh = uv.prepare(args.target)
    uv.build_uv_bins(mesh, args.grid_resolution)
    uv.build_uv_bins(target_mesh, args.grid_resolution)
    faces = mesh["faces"]
    cumulative, total = [], 0.0
    for face in faces:
        total += face["uv_area"]
        cumulative.append(total)
    rng = random.Random(args.seed)
    missing, target_miss, empty, wrong_cell = [], 0, 0, 0
    source_counts, target_counts = Counter(), Counter()
    cardinality = Counter()
    source_branch_coverage = []
    for sample_id in range(args.samples):
        face_id = min(bisect.bisect_left(cumulative, rng.random() * total), len(faces) - 1)
        face = faces[face_id]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1.0:
            r1, r2 = 1.0 - r1, 1.0 - r2
        bary = (1.0 - r1 - r2, r1, r2)
        point = uv.add_weighted(face["uv"], bary)
        world = uv.add_weighted(face["p"], bary)
        matches = uv.surface_matches(mesh, point, world)
        target_matches = uv.surface_matches(target_mesh, point, world)
        source_counts[len(matches)] += 1
        target_counts[len(target_matches)] += 1
        cardinality["source_gt_target" if len(matches) > len(target_matches) else
                    "source_lt_target" if len(matches) < len(target_matches) else "equal"] += 1
        source_branch_coverage.append(min(len(matches), len(target_matches)) / len(matches)
                                      if matches else 0.0)
        if not matches:
            empty += 1
        if not target_matches:
            target_miss += 1
        if not any(item[1] is face for item in matches):
            missing.append({"sample": sample_id, "face": face_id, "uv": point,
                            "uv_area": face["uv_area"], "candidate_count": len(matches),
                            "barycentric": bary, "uv_triangle": face["uv"]})
            cell = mesh["uv_cell"](point)
            if face_id not in mesh["uv_bins"].get(cell, ()):
                wrong_cell += 1
    report = {"samples": args.samples, "seed": args.seed,
              "source": str(args.source), "target": str(args.target),
              "missing_sample_face": len(missing), "target_hit_misses": target_miss,
              "empty_source_hit_sets": empty, "missing_from_uv_cell": wrong_cell,
              "source_hit_count_histogram": dict(sorted(source_counts.items())),
              "target_hit_count_histogram": dict(sorted(target_counts.items())),
              "cardinality_relation": dict(cardinality),
              "mean_cardinality_only_uniform_branch_coverage_estimate":
                  sum(source_branch_coverage) / len(source_branch_coverage),
              "interpretation_limit": "hit-set cardinality only; min(source,target)/source assumes equal branch weights and is not actual greedy matching or path-weighted reuse",
              "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
              "target_sha256": hashlib.sha256(args.target.read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
