#!/usr/bin/env python3
"""Combine paired CGVQM dynamic-LOD screens across camera paths."""

import argparse
import json
from pathlib import Path

import numpy as np


def bootstrap_mean(values, seed=20261122, count=20000):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(count, len(values)), replace=True).mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95": [float(x) for x in np.quantile(samples, (0.025, 0.975))],
        "assetsAboveZero": int(np.count_nonzero(values > 0)),
        "assetsBelowZero": int(np.count_nonzero(values < 0)),
        "assetCount": int(len(values)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summaries", nargs="+", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-markdown", type=Path, required=True)
    args = parser.parse_args()

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.summaries]
    if len(reports) < 2:
        parser.error("provide at least two camera-path summaries")
    common = ("metric", "benchmarkSha256", "resolution", "frameCount", "fps",
              "profileObjective", "patchPool", "patchScale", "cpuThreads")
    for key in common:
        if any(report.get(key) != reports[0].get(key) for report in reports[1:]):
            parser.error(f"summary configurations differ at {key}")

    path_ids = [report["path"] for report in reports]
    if len(path_ids) != len(set(path_ids)):
        parser.error("camera path IDs must be unique")
    by_path = {report["path"]: {row["asset"]: row for row in report["assets"]}
               for report in reports}
    asset_names = set(next(iter(by_path.values())))
    if any(set(rows) != asset_names for rows in by_path.values()):
        parser.error("all paths must contain exactly the same assets")

    combined_assets = []
    for asset in sorted(asset_names):
        rows = [by_path[path][asset] for path in path_ids]
        if any(row["ranker"] != rows[0]["ranker"] for row in rows[1:]):
            parser.error(f"selected ranker differs across paths for {asset}")
        area = float(np.mean([row["areaScore"] for row in rows]))
        selected = float(np.mean([row["selectedScore"] for row in rows]))
        combined_assets.append({
            "asset": asset,
            "ranker": rows[0]["ranker"],
            "meanAreaScore": area,
            "meanSelectedScore": selected,
            "meanDeltaSelectedMinusArea": selected - area,
            "pathDeltas": {str(path): by_path[path][asset]["deltaSelectedMinusArea"]
                           for path in path_ids},
        })

    deltas = [row["meanDeltaSelectedMinusArea"] for row in combined_assets]
    summary = {
        "metric": reports[0]["metric"],
        "benchmark": reports[0]["benchmark"],
        "benchmarkSha256": reports[0]["benchmarkSha256"],
        "paths": path_ids,
        "resolution": reports[0]["resolution"],
        "frameCountPerPath": reports[0]["frameCount"],
        "fps": reports[0]["fps"],
        "renderer": reports[0]["renderer"],
        "profileObjective": reports[0]["profileObjective"],
        "patchPool": reports[0]["patchPool"],
        "patchScale": reports[0]["patchScale"],
        "cpuThreads": reports[0]["cpuThreads"],
        "scoreDirection": "higher_is_better",
        "aggregation": "average paths within each asset, then bootstrap assets",
        "pairedAssetBootstrap": bootstrap_mean(deltas),
        "assets": combined_assets,
        "sourceSummaries": [str(path) for path in args.summaries],
        "interpretation": "Development screen on reused assets; not independent confirmation or a SIGGRAPH result.",
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    ci = summary["pairedAssetBootstrap"]["ci95"]
    width, height = summary["resolution"]
    lines = [
        f"# {summary['metric']} dynamic LOD sequence screen",
        "",
        "This is a research screen on reused development assets, not an independent confirmation or a SIGGRAPH result.",
        "",
        "## Protocol",
        "",
        f"- {len(combined_assets)} Khronos glTF assets; camera paths {', '.join(map(str, path_ids))}; "
        f"{width}x{height}; {summary['frameCountPerPath']} frames per path at {summary['fps']} fps.",
        "- Both policies use the same per-asset face budget. The cross-validated direction/scale ranker was fit without the held-out asset.",
        f"- LOD profile objective: `{summary['profileObjective']}`. Quality score: `{summary['metric']}`, "
        f"{summary['patchPool']} patch pooling, scale {summary['patchScale']}; CPU inference with {summary['cpuThreads']} threads.",
        "- Upstream model and calibration weights with an OpenCV FFmpeg video adapter; videos are lossless FFV1 grayscale renders. "
        "Decoded dimensions, frame rate, frame count, and exact pixels were verified.",
        "- Scores are paired within asset. Path deltas are averaged within each asset before the 95% percentile bootstrap, "
        "so the bootstrap unit is 13 assets rather than 26 asset-path pairs.",
        "- Reused development assets and isolated flat-shaded rendering; no authored materials, user ratings, or mobile devices.",
        "",
        "## Results",
        "",
        "Higher CGVQM scores indicate higher predicted quality. Positive deltas favor the selected ranker.",
        "",
        "| Asset | Selected ranker | Mean area score | Mean selected score | Mean delta | Path deltas |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in combined_assets:
        path_text = ", ".join(f"{path}: {delta:+.4f}" for path, delta in row["pathDeltas"].items())
        lines.append(f"| {row['asset']} | {row['ranker']} | {row['meanAreaScore']:.4f} | "
                     f"{row['meanSelectedScore']:.4f} | {row['meanDeltaSelectedMinusArea']:+.4f} | {path_text} |")
    boot = summary["pairedAssetBootstrap"]
    lines.extend([
        "",
        f"Mean within-asset delta: **{boot['mean']:+.4f}** (asset-bootstrap 95% CI "
        f"[{ci[0]:+.4f}, {ci[1]:+.4f}]); {boot['assetsAboveZero']} assets favor the selected ranker "
        f"and {boot['assetsBelowZero']} favor area.",
        "",
        "## Limits",
        "",
        "CGVQM-5 is a published graphics video metric, not a universal or ISO-standard score. OpenCV FFmpeg decoding "
        "differs from the paper's PyAV input path, so absolute scores are not a canonical reproduction. Paired "
        "comparisons share the same decoder and settings. These reused assets, synthetic renderer, and two paths "
        "do not establish general temporal perceptual quality. The profile remains closed unless a distinct novelty "
        "claim and repeatable quality-cost gain emerge on fresh licensed assets. No user preference or mobile claim is measured.",
        "",
        f"Raw JSON receipt: `{args.out_json.as_posix()}`. Source path summaries: "
        + ", ".join(f"`{path.as_posix()}`" for path in args.summaries) + ".",
        "",
        "References: [CGVQM paper](https://doi.org/10.1111/cgf.70221), "
        "[official implementation](https://github.com/IntelLabs/cgvqm).",
        "",
    ])
    args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out_markdown.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_markdown}")


if __name__ == "__main__":
    main()
