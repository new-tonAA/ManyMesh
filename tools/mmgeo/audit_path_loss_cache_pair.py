#!/usr/bin/env python3
"""Audit a cached and uncached path-loss run pair and recompute held-out metrics."""

import argparse
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from probe_dynamic_path_simplification import heldout_raster_quality


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def total_cpu(report, policy):
    row = report[policy]
    return sum(float(row.get(key, 0.0)) for key in
               ("queueSetupSeconds", "viewSetupSeconds", "runCpuSeconds"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True,
                        help="uncached path-loss report")
    parser.add_argument("--cached", type=Path, required=True,
                        help="axis-row-cache path-loss report")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    capture = load(args.capture)
    baseline = load(args.baseline)
    cached = load(args.cached)
    capture_hash = sha256(args.capture)
    if baseline["captureSha256"] != capture_hash or cached["captureSha256"] != capture_hash:
        parser.error("capture hash does not match both path-loss reports")
    if baseline["axisRowCache"] or not cached["axisRowCache"]:
        parser.error("expected an uncached baseline and a cached candidate")

    for key in ("unitIndex", "targetFaces", "pool", "fitViewCount", "normalWeight",
                "integrateAlongPan", "stripWidth", "optimization"):
        if baseline.get(key) != cached.get(key):
            parser.error(f"reports do not match on {key}")
    if baseline["qem"] != cached["qem"]:
        # Timing can differ between serial runs even when the deterministic edits match.
        for key in ("initialFaces", "finalFaces"):
            if baseline["qem"].get(key) != cached["qem"].get(key):
                parser.error("QEM baselines have different face counts")
        for a, b in zip(baseline["qem"]["steps"], cached["qem"]["steps"], strict=True):
            if (a["edge"], a["target"], a["faces"]) != (b["edge"], b["target"], b["faces"]):
                parser.error("QEM baselines have different edit sequences")

    base_steps = baseline["path"]["steps"]
    cache_steps = cached["path"]["steps"]
    if len(base_steps) != len(cache_steps):
        parser.error("path runs have different edit counts")
    for a, b in zip(base_steps, cache_steps, strict=True):
        if (a["edge"], a["target"], a["faces"]) != (b["edge"], b["target"], b["faces"]):
            parser.error("path runs chose different edits")

    max_score_delta = max(
        (abs(float(x) - float(y))
         for a, b in zip(base_steps, cache_steps, strict=True)
         for x, y in zip(a["perViewScore"], b["perViewScore"], strict=True)),
        default=0.0)
    config = cached["optimization"]
    quality_args = SimpleNamespace(
        quality_size=96,
        quality_scale=3,
        quality_steps=4,
        normal_weight=float(cached["normalWeight"]),
        angle=float(config["angle"]),
        pan_angle=float(config["panAngle"]),
        radius=float(config["radius"]),
        size=int(config["size"]))
    view_offsets = ((24, 37), (75, -29), (155, 15), (190, 47), (275, -43), (330, 21))
    heldout_views = [
        (f"orbit{i}", quality_args.angle + math.radians(azimuth),
         quality_args.pan_angle + pan)
        for i, (azimuth, pan) in enumerate(view_offsets, 1)]
    quality = heldout_raster_quality(
        capture["units"][int(cached["unitIndex"])], cache_steps,
        cached["qem"]["steps"], quality_args, views=heldout_views)
    means = {
        metric: sum(row["path"][metric] - row["qem"][metric]
                    for row in quality["views"]) / len(quality["views"])
        for metric in ("coverageMse", "depthMse", "flatNormalSquaredDistance")}
    quality["view_pair_delta_means"] = means

    qem_total = total_cpu(cached, "qem")
    baseline_total = total_cpu(baseline, "path")
    cached_total = total_cpu(cached, "path")
    output = {
        "schema": "manymesh-path-loss-cache-pair-v1",
        "scope": "Single-run 4% Monkey development check; CPU flat-geometry raster proxy, not production rendering.",
        "inputs": {
            "capture": {"path": str(args.capture), "sha256": capture_hash},
            "uncached_report": {"path": str(args.baseline), "sha256": sha256(args.baseline)},
            "cached_report": {"path": str(args.cached), "sha256": sha256(args.cached)},
            "code": {name: sha256(Path(name)) for name in (
                "tools/mmgeo/audit_path_loss_cache_pair.py",
                "tools/mmgeo/probe_global_path_qem.py",
                "tools/mmgeo/probe_dynamic_path_simplification.py")}},
        "setup": {
            "initial_faces": cached["path"]["initialFaces"],
            "final_faces": cached["path"]["finalFaces"],
            "edits": len(cache_steps),
            "views": 6,
            "view_size": quality["size"],
            "supersampling": quality["scale"],
            "pan_samples": quality["steps"],
            "normal_weight": cached["normalWeight"]},
        "same_face_count_and_edit_sequence": True,
        "max_abs_fit_score_difference": max_score_delta,
        "final_fit_view_audit_max_pixel_difference": {
            "cached": max(row["maxPixelDifference"]
                          for row in cached["path"]["finalViewAudit"]),
            "uncached": max(row["maxPixelDifference"]
                            for row in baseline["path"]["finalViewAudit"])},
        "cpu_seconds_single_run": {
            "qem_total": qem_total,
            "path_uncached_total": baseline_total,
            "path_cached_total": cached_total,
            "cache_speedup_vs_uncached": baseline_total / cached_total,
            "cached_path_over_qem": cached_total / qem_total,
            "path_scorer_uncached": baseline["path"]["runCpuSeconds"],
            "path_scorer_cached": cached["path"]["runCpuSeconds"]},
        "cache_peak_lines_per_view_source_and_current": cached["path"]["perViewAxisRowCachePeakLines"],
        "heldout_quality": quality,
        "limitations": [
            "One asset and one serial run per condition; timings are not a statistical comparison.",
            "The cache is faster than this path-loss implementation but remains slower than QEM.",
            "The six held-out views show no coverage gain and negligible average depth/normal differences.",
            "This geometry-only CPU proxy does not measure materials, hardware rendering, temporal behavior, or perception."],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "cpu_seconds": output["cpu_seconds_single_run"],
                      "heldout_delta_means": means}, indent=2))


if __name__ == "__main__":
    main()
