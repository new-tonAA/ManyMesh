#!/usr/bin/env python3
"""Audit target-budget mesh cuts against the fixed-camera CPU coverage/depth raster oracle."""

import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "tools/mmgeo/audit_target_budget_visibility.py"
HELPER_SPEC = importlib.util.spec_from_file_location("target_visibility", HELPERS)
target_visibility = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(target_visibility)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--cut", action="append", required=True, metavar="LABEL=PLY")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--sigma", type=float, default=0.9)
    parser.add_argument("--views", type=int, default=16)
    parser.add_argument("--triangle-budget", type=int,
            help="allow cuts with different triangle counts, provided each stays within this cap")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.size <= 0 or args.scale <= 0 or args.sigma <= 0 or args.views <= 0:
        raise ValueError("size, scale, sigma, and views must be positive")
    if args.triangle_budget is not None and args.triangle_budget <= 0:
        raise ValueError("triangle budget must be positive")

    labels, ply_paths, groups = [], {}, {}
    target_triangles = None
    triangle_counts = {}
    for item in args.cut:
        if "=" not in item:
            raise ValueError(f"--cut expects LABEL=PLY, got {item!r}")
        label, path_text = item.split("=", 1)
        if not label or label in groups:
            raise ValueError(f"empty or duplicate cut label: {label!r}")
        path = Path(path_text)
        points, faces = target_visibility.load_binary_ply(path)
        triangle_counts[label] = len(faces)
        if target_triangles is None:
            target_triangles = len(faces)
        if args.triangle_budget is None and len(faces) != target_triangles:
            raise ValueError(f"cut {label} has {len(faces)} triangles, expected {target_triangles}")
        if args.triangle_budget is not None and len(faces) > args.triangle_budget:
            raise ValueError(f"cut {label} has {len(faces)} triangles, above budget {args.triangle_budget}")
        labels.append(label)
        ply_paths[label] = path
        groups[label] = (points, faces)

    reference_points, reference_faces = target_visibility.load_obj(args.mesh)
    raster_path = ROOT / "tools/mmgeo/depth_candidate_pilot.py"
    spec = importlib.util.spec_from_file_location("depth_candidate_pilot", raster_path)
    raster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(raster)

    angles = np.linspace(0.0, 2.0 * math.pi, args.views, endpoint=False)
    view_rows = {label: [] for label in labels}
    for view_id, angle in enumerate(angles):
        transform = raster.camera(reference_points, float(angle), args.size)
        projected_reference = raster.project(reference_points, transform)
        full_rect = (0, 0, args.size, args.size)
        high_reference, _ = raster.raster(projected_reference, reference_faces,
                np.ones(len(reference_faces), dtype=bool), full_rect, args.scale)
        filtered_reference = raster.filtered(high_reference, args.sigma, args.scale)
        for label in labels:
            points, faces = groups[label]
            projected = raster.project(points, transform)
            high_candidate, _ = raster.raster(projected, faces,
                    np.ones(len(faces), dtype=bool), full_rect, args.scale)
            filtered_candidate = raster.filtered(high_candidate, args.sigma, args.scale)
            values = raster.metrics(filtered_candidate - filtered_reference)
            mismatch = np.count_nonzero(high_candidate[..., 0] != high_reference[..., 0])
            sample_count = high_reference.shape[0] * high_reference.shape[1]
            view_rows[label].append({
                "view": view_id,
                "azimuthRadians": float(angle),
                "filteredCoverageSse": values["coverage"],
                "filteredDepthSse": values["depth"],
                "filteredTotalSse": values["total"],
                "rawCoverageMismatchFraction": mismatch / sample_count,
            })
        print(f"{args.asset}: view {view_id + 1}/{args.views}", flush=True)

    summary = {}
    for label in labels:
        rows = view_rows[label]
        means = {key: float(np.mean([row[key] for row in rows])) for key in (
                "filteredCoverageSse", "filteredDepthSse", "filteredTotalSse",
                "rawCoverageMismatchFraction")}
        means["filteredTotalRmsePerOutputPixel"] = math.sqrt(
                means["filteredTotalSse"] / (args.size * args.size))
        means["worstViewTotalSse"] = max(row["filteredTotalSse"] for row in rows)
        summary[label] = means

    graph_hashes = {}
    for label, path in ply_paths.items():
        graph_path = path.parent / "lod_graph.json"
        if graph_path.exists():
            graph_hashes[label] = target_visibility.sha256(graph_path)
    hashes = {
        "sourceObj": target_visibility.sha256(args.mesh),
        "rasterOracle": target_visibility.sha256(raster_path),
        "helperParser": target_visibility.sha256(HELPERS),
        "analysisScript": target_visibility.sha256(Path(__file__)),
        "lodGraphSource": target_visibility.sha256(ROOT / "libs/manymesh/src/LodGraph.cpp"),
        "mmgeoSource": target_visibility.sha256(ROOT / "tools/mmgeo/src/main.cpp"),
        "mmgeoExecutable": target_visibility.sha256(ROOT / "out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe"),
        "graphs": graph_hashes,
        "cuts": {label: target_visibility.sha256(path) for label, path in ply_paths.items()},
    }
    result = {
        "scope": "single-asset full-orbit CPU orthographic raster diagnostic; binary coverage and normalized first-hit depth only; no PBR",
        "warnings": [
            "The raster uses the repository's two-sided supersampled CPU visibility oracle and normalized orthographic camera, not the mmgeo perspective screen-error camera.",
            "This is a diagnostic control on one asset; it is not a generalization or SIGGRAPH-quality evaluation.",
        ],
        "asset": args.asset,
        "settings": {"size": args.size, "scale": args.scale, "sigma": args.sigma,
                "views": args.views, "sourceTriangles": len(reference_faces),
                "candidateTriangles": target_triangles if args.triangle_budget is None else triangle_counts,
                "triangleBudget": args.triangle_budget},
        "meanViewMetrics": summary,
        "rankByFilteredTotalSse": sorted(labels,
                key=lambda label: summary[label]["filteredTotalSse"]),
        "viewsByCut": view_rows,
        "hashes": hashes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"meanViewMetrics": summary,
            "rankByFilteredTotalSse": result["rankByFilteredTotalSse"],
            "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
