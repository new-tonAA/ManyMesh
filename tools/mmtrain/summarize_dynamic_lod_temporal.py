"""Summarize paired temporal image-difference diagnostics over assets."""

import argparse
import json
from pathlib import Path

import numpy as np


METRICS = (
    "foregroundSupportMae",
    "foregroundSupportRmse",
    "foregroundPairMaeP95",
    "meanForegroundPairMaeAtSwitch",
    "meanForegroundPairMaeWithoutSwitch",
    "lodSwitchTransitions",
)


def summarize(inputs, bootstrap_count=20000, seed=20261122):
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in inputs]
    data = runs[0]
    assets = list(data["assets"])
    for run in runs[1:]:
        if list(run["assets"]) != assets or run["size"] != data["size"]:
            raise ValueError("Input runs must have identical assets and resolution")
        if run.get("inputHashes") != data.get("inputHashes"):
            raise ValueError("Input runs must identify the same renderer and mesh inputs")
        for asset in assets:
            if run["assets"][asset]["calibratedRanker"] != data["assets"][asset]["calibratedRanker"]:
                raise ValueError(f"Profile choice changed between runs for {asset}")
    per_asset = {}
    ranker_counts = {}
    for asset in assets:
        ranker = data["assets"][asset]["calibratedRanker"]
        ranker_counts[ranker] = ranker_counts.get(ranker, 0) + 1
    for asset in assets:
        paths = [path for run in runs
                 for path in run["assets"][asset]["temporalDifferenceQuality"]]
        row = {}
        for metric in METRICS:
            baseline = [p["area-hysteresis"][metric] for p in paths]
            candidate = [p["calibrated-hysteresis"][metric] for p in paths]
            row[metric] = float(np.mean(candidate) - np.mean(baseline))
        per_asset[asset] = row

    rng = np.random.default_rng(seed)
    summary = {}
    for metric in METRICS:
        values = np.asarray([per_asset[asset][metric] for asset in assets], dtype=np.float64)
        samples = rng.choice(values, size=(bootstrap_count, len(values)), replace=True).mean(axis=1)
        baseline_means = []
        candidate_means = []
        for asset in assets:
            paths = [path for run in runs
                     for path in run["assets"][asset]["temporalDifferenceQuality"]]
            baseline_means.append(float(np.mean([p["area-hysteresis"][metric] for p in paths])))
            candidate_means.append(float(np.mean([p["calibrated-hysteresis"][metric] for p in paths])))
        summary[metric] = {
            "baselineMean": float(np.mean(baseline_means)),
            "candidateMean": float(np.mean(candidate_means)),
            "meanDelta": float(values.mean()),
            "ci95": [float(value) for value in np.quantile(samples, (0.025, 0.975))],
            "assetsImproved": int(np.count_nonzero(values < 0)),
            "assetsRegressed": int(np.count_nonzero(values > 0)),
        }
    return {
        "resolution": data["size"],
        "framesPerPath": data["framesPerPath"],
        "paths": [path for run in runs for path in run["testPaths"]],
        "profileObjective": data.get("profileObjective", "color-sse"),
        "selectedRankers": ranker_counts,
        "receipts": [Path(path).as_posix() for path in inputs],
        "inputHashes": data.get("inputHashes"),
        "assetCount": len(assets),
        "perAssetPairedDeltas": per_asset,
        "summary": summary,
        "scope": "Temporal finite-difference diagnostic; not CGVQM or a perceptual flicker score",
    }


def markdown(report):
    width, height = report["resolution"]
    lines = [
        "# Dynamic LOD temporal image-difference screen",
        "",
        "Updated 2026-11-22. This is a temporal signal diagnostic, **not a perceptual video-quality result**.",
        "",
        "## Protocol",
        "",
        f"- {report['assetCount']} Khronos glTF assets; 16 tiled instances per frame; {width}x{height};",
        f"  {report['framesPerPath']} frames on each of camera paths {', '.join(map(str, report['paths']))}.",
        "- Compare the leave-one-asset-out calibrated ranker plus hysteresis against area ranking plus hysteresis",
        "  on two separately captured path pairs. The per-asset policy is fixed before scoring held-out paths;",
        "  both methods use the same face budget.",
        f"- Profile training objective: `{report['profileObjective']}`.",
        f"- Selected rankers: {', '.join(f'{name} ({count})' for name, count in sorted(report['selectedRankers'].items()))}.",
        "- For each sequence, compose the actual candidate image from captured low-detail and full-detail instance renders.",
        "  Measure adjacent-frame image derivatives for candidate and full-detail reference, then subtract those derivatives.",
        "- Foreground support is the union of candidate/reference non-black pixels over adjacent frames. Report mean and p95",
        "  absolute derivative error, normalized by 255. Lower is better. Average paths within asset, then bootstrap assets.",
        "- The custom finite-difference diagnostic is sensitive to camera motion and silhouette displacement. It is not motion-compensated,",
        "  perceptually calibrated, or validated against human ratings. Do not call it a standardized flicker score.",
        f"- The motion-reference manifest SHA-256 is `{report['inputHashes']['motionReferenceSha256']}`; source and component mesh SHA-256 values are in the raw receipts.",
        "",
        "## Paired results",
        "",
        "Positive deltas mean the calibrated policy has greater temporal error than area ranking. The CI bootstraps 13 assets.",
        "",
        "| Metric | Area mean | Calibrated mean | Paired delta [95% asset-bootstrap CI] | Assets improved / regressed |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "foregroundSupportMae": "Foreground temporal-difference MAE",
        "foregroundSupportRmse": "Foreground temporal-difference RMSE",
        "foregroundPairMaeP95": "95th percentile per-pair foreground MAE",
        "meanForegroundPairMaeAtSwitch": "Mean foreground MAE on LOD-switch pairs",
        "meanForegroundPairMaeWithoutSwitch": "Mean foreground MAE without LOD switches",
        "lodSwitchTransitions": "Transitions with at least one instance LOD switch",
    }
    for key, label in labels.items():
        row = report["summary"][key]
        lines.append(f"| {label} | {row['baselineMean']:.6f} | {row['candidateMean']:.6f} | "
                     f"{row['meanDelta']:+.6f} [{row['ci95'][0]:+.6f}, {row['ci95'][1]:+.6f}] | "
                     f"{row['assetsImproved']} / {row['assetsRegressed']} |")
    lines.extend([
        "",
        "## Interpretation and limits",
        "",
        ("Every asset selected the area ranker, so candidate and control sequences are identical and all temporal deltas "
         "are zero. The silhouette-XOR objective did not change the selected policy." 
         if report["selectedRankers"] == {"area": report["assetCount"]} else
         "This screen supplements the existing framewise PSNR, SSIM, and silhouette results and checks whether the "
         "chosen policy changes temporal image differences on these synthetic paths."),
        "The custom pixelwise derivative does not account for optical flow or human temporal sensitivity. The broader",
        "shared-profile formulation already lacks a reliable PSNR gain and reduces silhouette IoU on this reused development corpus; these results do not reopen it as",
        "a contribution candidate or establish temporal stability.",
        "",
        "CGVQM, a full-reference computer-graphics video metric with spatial and temporal modeling, remains the required",
        "perceptual follow-up. CGVQM code/weights were not present locally during this screen. No CGVQM score, user preference,",
        "authored-material result, or mobile result is claimed.",
        "See the [temporal quality protocol](../mmmetrics/TEMPORAL_QUALITY_PROTOCOL.md) and [shared-profile screen](DYNAMIC_LOD_LOAO_13ASSET_20261122.md).",
        "",
        "Raw receipts:",
        *[f"- `{path}`" for path in report["receipts"]],
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--alternate", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-markdown", type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.initial, args.alternate]
    report = summarize(inputs)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out_markdown.write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
