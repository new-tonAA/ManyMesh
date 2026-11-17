#!/usr/bin/env python3
"""Combine seven-mesh build controls and five exact-budget visibility audits."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GROUPS = (2, 4, 8, 16, 32)
CORE_SUMMARY = ROOT / "out/targetbudget-repeat-control-20261116/summary.json"
HELDOUT_SUMMARY = ROOT / "out/targetbudget-heldout-20261116/builds_summary.json"
VISIBILITY_PATHS = {
    "pirate": ROOT / "out/targetbudget-frontier-pilot-20261116/visibility_audit.json",
    "monkey": ROOT / "out/targetbudget-crossasset-20261116/monkey_visibility_audit.json",
    "cloth": ROOT / "out/targetbudget-heldout-20261116/cloth_visibility.json",
    "material_sphere": ROOT / "out/targetbudget-heldout-20261116/material_sphere_visibility.json",
    "shapes": ROOT / "out/targetbudget-heldout-20261116/shapes_visibility.json",
}
OUTPUT_JSON = ROOT / "out/targetbudget-heldout-20261116/seven_asset_summary.json"
OUTPUT_MD = ROOT / "tools/mmgeo/TARGET_BUDGET_HELDOUT_FRONTIER_20261116.md"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    core = json.loads(CORE_SUMMARY.read_text(encoding="utf-8"))
    heldout = json.loads(HELDOUT_SUMMARY.read_text(encoding="utf-8"))
    visibility = {asset: json.loads(path.read_text(encoding="utf-8"))
            for asset, path in VISIBILITY_PATHS.items()}
    core_rows = {(row["asset"], row["groupSize"]): row for row in core["summaries"]}
    held_rows = {(row["asset"], row["groupSize"]): row
            for row in heldout["summaries"]}
    build_rows = []
    for asset in ("pirate", "monkey"):
        for group in GROUPS:
            row = core_rows[(asset, group)]
            build_rows.append({"asset": asset, "groupSize": group,
                "sourceTriangles": visibility[asset]["settings"]["sourceTriangles"],
                "buildMedianSeconds": row["dagBuildSeconds"]["median"],
                "buildMinSeconds": row["dagBuildSeconds"]["min"],
                "buildMaxSeconds": row["dagBuildSeconds"]["max"],
                "wallMedianSeconds": row["wallSeconds"]["median"],
                "screenErrorPx": row["screenErrorPx"][0],
                "selectedTriangles": row["selectedTriangles"][0],
                "visibilitySse": row["visibilityFilteredTotalSse"],
                "visibilityAudited": True})
    for asset in ("camera", "cloth", "material_sphere", "rounded_cube", "shapes"):
        audit = visibility.get(asset)
        audit_metrics = audit["meanViewMetrics"] if audit else {}
        audit_groups = set(audit_metrics)
        for group in GROUPS:
            row = held_rows[(asset, group)]
            label = f"g{group}"
            build_rows.append({"asset": asset, "groupSize": group,
                "sourceTriangles": row["baseTriangles"],
                "buildMedianSeconds": row["dagBuildMedianSeconds"],
                "buildMinSeconds": row["dagBuildMinSeconds"],
                "buildMaxSeconds": row["dagBuildMaxSeconds"],
                "wallMedianSeconds": row["wallMedianSeconds"],
                "screenErrorPx": row["worstSelectedScreenErrorPx"],
                "selectedTriangles": row["selectedTriangles"],
                "visibilitySse": audit_metrics[label]["filteredTotalSse"]
                        if label in audit_groups else None,
                "visibilityAudited": label in audit_groups})

    asset_summaries = []
    for asset in ("pirate", "monkey", "camera", "cloth", "material_sphere",
            "rounded_cube", "shapes"):
        rows = [row for row in build_rows if row["asset"] == asset]
        fastest = min(rows, key=lambda row: row["buildMedianSeconds"])
        audited = [row for row in rows if row["visibilityAudited"]]
        best = min(audited, key=lambda row: row["visibilitySse"]) if audited else None
        triangle_counts = sorted({row["selectedTriangles"] for row in rows})
        improvement = None
        cost_ratio = None
        if best and fastest["visibilityAudited"]:
            improvement = 1.0 - best["visibilitySse"] / fastest["visibilitySse"]
            cost_ratio = best["buildMedianSeconds"] / fastest["buildMedianSeconds"]
        asset_summaries.append({
            "asset": asset,
            "sourceTriangles": rows[0]["sourceTriangles"],
            "selectedTriangleRange": [min(triangle_counts), max(triangle_counts)],
            "fastestGroup": fastest["groupSize"],
            "fastestBuildSeconds": fastest["buildMedianSeconds"],
            "fastestVisibilitySse": fastest["visibilitySse"],
            "bestAuditedQualityGroup": best["groupSize"] if best else None,
            "bestAuditedQualityBuildSeconds": best["buildMedianSeconds"] if best else None,
            "bestAuditedVisibilitySse": best["visibilitySse"] if best else None,
            "qualityReductionFromFastest": improvement,
            "bestBuildCostMultipleOfFastest": cost_ratio,
            "groups": [row for row in rows],
        })

    quality_assets = [item for item in asset_summaries
            if item["bestAuditedQualityGroup"] is not None]
    machine = {
        "scope": "seven repository meshes; five exact-face-budget visibility comparisons; 105 repeated builds total across core and held-out sets",
        "reportScript": {"path": str(Path(__file__).relative_to(ROOT)),
                "sha256": sha256(Path(__file__))},
        "buildInputs": {
            "coreSummary": {"path": str(CORE_SUMMARY.relative_to(ROOT)),
                    "sha256": sha256(CORE_SUMMARY)},
            "heldoutSummary": {"path": str(HELDOUT_SUMMARY.relative_to(ROOT)),
                    "sha256": sha256(HELDOUT_SUMMARY)},
        },
        "visibilityInputs": {asset: {"path": str(path.relative_to(ROOT)),
                "sha256": sha256(path), "settings": visibility[asset]["settings"],
                "sourceHash": visibility[asset]["hashes"]["sourceObj"],
                "graphHashes": visibility[asset]["hashes"]["graphs"]}
                for asset, path in VISIBILITY_PATHS.items()},
        "buildRows": build_rows,
        "assetSummaries": asset_summaries,
    }
    OUTPUT_JSON.write_text(json.dumps(machine, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Held-Out Target-Budget Frontier Study (2026-11-16)",
        "",
        "## Scope",
        "",
        "This extension adds five repository meshes to the two-asset Pirate/Monkey control: camera, cloth, material_sphere, rounded_cube and shapes. All builds use a 55% target and the same group-size grid (2, 4, 8, 16, 32); each setting is built three times in randomized per-repeat order. The three repeated graph files, cut files, triangle counts and screen-error values were checked for determinism.",
        "",
        "Visibility quality is audited only where candidate cuts have exactly the same triangle count. The CPU diagnostic is geometry-only filtered coverage plus normalized first-hit-depth SSE, averaged over 16 evenly spaced azimuths, one elevation, 256x256, 2x supersampling, Gaussian sigma 0.9. Pirate and Monkey reuse the earlier exact-budget audits. Among the five added meshes, cloth and material_sphere match exactly across all group sizes; shapes uses groups 2, 8, 16 and 32 at 40,550 triangles, while g4 is excluded because it has 40,551. Camera (320–350 triangles) and rounded_cube (552–660) are build-only: their cuts have materially different budgets and are not ranked by image error.",
        "",
        "## Per-asset result",
        "",
        "| Asset | Fastest group (median DAG build) | Best exact-budget raster group | Raster SSE at fastest | Raster SSE at best | Best quality vs fastest |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in quality_assets:
        quality_text = ("same group" if item["qualityReductionFromFastest"] == 0 else
                f"{100 * item['qualityReductionFromFastest']:.1f}% lower SSE at "
                f"{item['bestBuildCostMultipleOfFastest']:.2f}x build cost")
        lines.append(f"| {item['asset']} | g{item['fastestGroup']} ({item['fastestBuildSeconds']:.2f}s) | "
                f"g{item['bestAuditedQualityGroup']} | {item['fastestVisibilitySse']:.6f} | "
                f"{item['bestAuditedVisibilitySse']:.6f} | {quality_text} |")
    lines += [
        "",
        "| Build-only asset | Triangle range across groups | Fastest group / median DAG build |",
        "|---|---:|---|",
    ]
    for item in asset_summaries:
        if item["bestAuditedQualityGroup"] is None:
            lines.append(f"| {item['asset']} | {item['selectedTriangleRange'][0]}-{item['selectedTriangleRange'][1]} | "
                    f"g{item['fastestGroup']} / {item['fastestBuildSeconds']:.2f}s |")

    lines += ["", "## Detailed build and quality table", ""]
    for asset in ("pirate", "monkey", "cloth", "material_sphere", "shapes",
            "camera", "rounded_cube"):
        rows = [row for row in build_rows if row["asset"] == asset]
        lines += [f"### {asset}", "",
            "| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |",
            "|---:|---:|---:|---:|---:|"]
        for row in rows:
            metric = f"{row['visibilitySse']:.8f}" if row["visibilityAudited"] else "not audited"
            lines.append(f"| {row['groupSize']} | {row['buildMedianSeconds']:.2f} "
                    f"[{row['buildMinSeconds']:.2f}, {row['buildMaxSeconds']:.2f}] | "
                    f"{row['selectedTriangles']:,} | {row['screenErrorPx']:.4f} | {metric} |")
        lines.append("")

    lines += [
        "## What the result supports",
        "",
        "Among five exact-budget audited assets, the fastest group-2 setting also gives the lowest raster SSE for Pirate and cloth. The best group is different for the other three: Monkey g8, material_sphere g32, shapes g16. On the latter two, group 2 is fastest but has respectively 39.3% and 96.9% higher raster SSE than the best measured group, at about 2.64x and 3.28x the build time for those best settings. These are finite-grid observations, not a universal policy. The results make a single fixed `--dag-group` choice implausible as a global quality/cost optimum for this sample.",
        "",
        "The sphere-error proxy disagrees with the image-space diagnostic on several assets: Pirate's sphere-error minimum is g8 while its raster minimum is g2; Monkey's proxy minimum is g2 while raster minimum is g8; material_sphere's proxy minimum is g2 while raster minimum is g32; shapes' proxy minimum is g2 while raster minimum is g16. This is a metric-validation result, not a new quality metric. The visibility score remains an uncalibrated geometry-only proxy.",
        "",
        "## Research status and next gate",
        "",
        "This is not SIGGRAPH-ready evidence. It establishes a repeatable asset-dependent sweep on five exact-budget meshes and adds two build-only assets, but uses only seven repository models, a small group grid, one fixed 55% target, one CPU raster proxy, one camera elevation and no materials/textures/normals/PBR or user study. HLOD ASAP already simplifies neighboring cluster boundaries crack-free; DAG2 already uses shared-child split-and-reinsert; scene-level adaptive simplification-rate allocation is also prior art. No novelty claim follows from per-asset tuning.",
        "",
        "Next, compute the exact best joint schedule over the measured finite group/retry configurations at matched total wall time and peak memory, then compare a marginal full-cut quality-gain-per-build-second scheduler against that upper bound on held-out meshes not used to choose thresholds. If the finite-grid oracle shows no substantial gain over the best fixed schedule, stop this direction. If it does, the candidate method still needs a distinct cut-frontier mechanism and gate-matched HLOD ASAP/DAG2/cluster-LOD comparisons, plus appearance-aware rendering and broader evaluation.",
        "",
        "## Reproduction and artifacts",
        "",
        "The 75 new builds are in `out/targetbudget-heldout-20261116/builds.json`; their timing/hash aggregation is `builds_summary.json`. Re-run them with `python -I tools/mmgeo/benchmark_target_budget_heldout.py` only after changing its output root, because it refuses to overwrite captured runs. The exact-budget audit manifest (including commands and excluded groups) is `visibility_manifest.json`; the aggregate JSON is `seven_asset_summary.json`. Build inputs and all audit graphs/cuts/raster scripts are SHA-256-bound in the JSON manifests. No C++ changed and no software tests were run.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(OUTPUT_MD), "summary": str(OUTPUT_JSON),
            "qualityAssets": [item["asset"] for item in quality_assets],
            "buildAssets": [item["asset"] for item in asset_summaries]}, indent=2))


if __name__ == "__main__":
    main()
