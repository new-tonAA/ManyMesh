#!/usr/bin/env python3
"""Evaluate two frozen collapse candidates at unseen angles on an existing camera segment."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load_pilot():
    path = Path(__file__).with_name("depth_candidate_pilot.py")
    spec = importlib.util.spec_from_file_location("adaptive_holdout_pilot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def evaluate(pilot, positions, triangles, candidates, candidate_id, angle, size, scale, sigma):
    transform = pilot.camera(positions, angle, size)
    projected = pilot.project(positions, transform)
    full = (0, 0, size, size)
    valid = np.ones(len(triangles), dtype=bool)
    base_raw, _ = pilot.raster(projected, triangles, valid, full, scale)
    candidate = candidates[candidate_id]
    rect = pilot.support(projected, triangles, candidate, transform, size,
                         int(np.ceil(4 * sigma)) + 2)
    if rect is None:
        return dict(id=candidate_id, rect=None, coverage=0.0, depth=0.0, total=0.0)
    changed, edited_triangles, alive = pilot.edited_geometry(
        projected, triangles, candidate, transform)
    residual, seconds = pilot.patch_residual(changed, edited_triangles, alive, rect,
                                              scale, sigma, base_raw)
    result = pilot.metrics(residual)
    return dict(id=candidate_id, rect=rect, **result, seconds=seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("--ids", nargs=2, type=int, required=True,
                        help="adaptive winner and uniform-sampling winner")
    parser.add_argument("--segments", type=int, default=15,
                        help="number of equal path segments; evaluates their midpoints")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--sigma", type=float, default=.9)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.segments < 1:
        parser.error("--segments must be positive")

    pilot = load_pilot()
    positions, triangles, candidates = pilot.load_capture(args.capture)
    source_report = json.loads(args.candidate_report.read_text(encoding="utf-8"))
    pool_ids = {int(row["id"]) for row in source_report["frames"][0]["candidates"]}
    original = json.loads(Path("out/camera-rank-stability/monkey-pool0-16.json").read_text(
        encoding="utf-8"))
    source_angles = np.asarray([float(view["angle"]) for view in original["views"]])
    if any(cid < 0 or cid >= len(candidates) or cid not in pool_ids for cid in args.ids):
        parser.error("candidate ID outside frozen candidate report")
    heldout = ((source_angles[:-1] + source_angles[1:]) * .5).tolist()
    if args.segments != len(heldout):
        heldout = np.linspace(float(source_angles[0]), float(source_angles[-1]),
                              args.segments + 2)[1:-1].tolist()

    output = {
        "scope": "two-candidate held-out raster evaluation on interstitial camera angles",
        "warning": "does not evaluate the full candidate pool or certify a continuous path",
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "candidateReportSha256": hashlib.sha256(args.candidate_report.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "finitePathReportSha256": hashlib.sha256(Path(
            "out/camera-rank-stability/monkey-pool0-16.json").read_bytes()).hexdigest(),
        "size": args.size,
        "scale": args.scale,
        "sigma": args.sigma,
        "candidateIds": args.ids,
        "heldoutAngles": heldout,
        "views": [],
    }
    start = time.perf_counter()
    for angle in heldout:
        rows = [evaluate(pilot, positions, triangles, candidates, cid, angle, args.size,
                         args.scale, args.sigma) for cid in args.ids]
        output["views"].append(dict(angle=angle, candidates=rows))
        print(f"angle={angle:.6f}: " + ", ".join(
            f"{row['id']}={row['total']:.9g}" for row in rows), flush=True)
    means = {str(cid): float(np.mean([v["candidates"][i]["total"]
                                      for v in output["views"]]))
             for i, cid in enumerate(args.ids)}
    output["summary"] = {
        "meanHeldoutLoss": means,
        "heldoutWinner": min(args.ids, key=lambda cid: means[str(cid)]),
        "winnerMatchesAdaptive": min(args.ids, key=lambda cid: means[str(cid)]) == args.ids[0],
        "winnerMatchesUniform": min(args.ids, key=lambda cid: means[str(cid)]) == args.ids[1],
        "wallSeconds": time.perf_counter() - start,
        "note": "CPU raster timing is diagnostic only; no speed claim.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"held-out winner={output['summary']['heldoutWinner']}; "
          f"means={means}; wrote {args.out}")


if __name__ == "__main__":
    main()
