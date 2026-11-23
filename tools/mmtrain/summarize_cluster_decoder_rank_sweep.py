#!/usr/bin/env python3
"""Summarize fixed-topology and local-refinement decoder rank screens."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path("out/cluster-decoder-fit")
QUALITY_ROOT = Path("out/cluster-decoder-quality")
RANKS = (8, 16, 30)
METRICS = ("psnr_db", "ssim", "flip", "lpips_squeeze",
           "silhouette_xor_fraction", "coverage_mae")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metric_delta(comparison, name):
    row = comparison["metrics"][name]["paired_delta"]
    return {
        "mean_delta": row["mean_delta"],
        "bootstrap_95_percent": row["bootstrap_95_percent"],
        "negative_assets": row["negative"],
        "positive_assets": row["positive"],
        "paired_assets": row["assets"],
    }


def make_rank_record(rank):
    name = f"rank{rank}"
    fit_path = ROOT / name / "report.json"
    quality_path = QUALITY_ROOT / name / "report.json"
    summary_path = QUALITY_ROOT / name / "summary.json"
    fit, quality, summary = map(read_json, (fit_path, quality_path, summary_path))
    validation = summary["splits"]["validation"]
    records = [row for row in quality["records"]
               if row["split"] == "validation"
               and row["preparation_status"] == "prepared"]
    result = {
        "rank": rank,
        "model_file_bytes": {},
        "model_sha256": {},
        "train_decode": {},
        "validation_decode": {},
        "validation_mean_sidecar_bytes": {},
        "validation_metrics_vs_qem": {},
        "artifact_sha256": {
            "fit_report": sha256(fit_path),
            "quality_report": sha256(quality_path),
            "quality_summary": sha256(summary_path),
        },
    }
    for mode in ("fixed", "refine"):
        model_path = ROOT / name / mode / "model.npz"
        fit_rows = fit["modes"][mode]["records"]
        result["model_file_bytes"][mode] = model_path.stat().st_size
        result["model_sha256"][mode] = sha256(model_path)
        result["train_decode"][mode] = {
            "decoded": sum(row["status"] == "decoded" for row in fit_rows),
            "attempted": len(fit_rows),
        }
        result["validation_decode"][mode] = {
            "decoded": sum(row["decode_status"].get(mode) == "decoded"
                            for row in records),
            "prepared": len(records),
            "failures": [
                {"file_id": row["file_id"], "reason": row["decode_status"].get(mode)}
                for row in records if row["decode_status"].get(mode) != "decoded"
            ],
        }
        sidecars = [
            QUALITY_ROOT / name / f"validation-{row['file_id']}"
            / f"{row['file_id']}-{mode}.sidecar"
            for row in records
        ]
        if not all(path.exists() for path in sidecars):
            raise FileNotFoundError(f"Missing validation sidecar for rank {rank} {mode}")
        result["validation_mean_sidecar_bytes"][mode] = (
            sum(path.stat().st_size for path in sidecars) / len(sidecars)
        )
        comparison = validation["comparisons"].get(f"{mode}_vs_base")
        result["validation_metrics_vs_qem"][mode] = {
            "paired_assets": comparison["paired_assets"] if comparison else 0,
            "same_triangle_count": comparison["same_triangle_count"] if comparison else None,
            "metrics": ({metric: metric_delta(comparison, metric) for metric in METRICS}
                        if comparison else {}),
        }
    return result


def fmt_delta(row, digits=3):
    if not row:
        return "n/a"
    lo, hi = row["bootstrap_95_percent"]
    return (f"{row['mean_delta']:+.{digits}f} "
            f"[{lo:+.{digits}f}, {hi:+.{digits}f}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    records = [make_rank_record(rank) for rank in RANKS]
    train_manifest = Path("out/cluster-decoder-pairs/train-pruned/manifest.json")
    validation_manifest = Path("out/cluster-decoder-pairs/validation/manifest.json")
    script_names = (
        "tools/mmtrain/cluster_decoder.py",
        "tools/mmtrain/fit_cluster_decoder.py",
        "tools/mmtrain/cluster_decoder_quality.py",
        "tools/mmmetrics/summarize_decoder_quality.py",
    )
    receipt = {
        "scope": "Exploratory rank sweep; no test split was loaded",
        "configuration": {
            "ranks": list(RANKS),
            "ridge": 1e-5,
            "refinement_fraction": 0.1,
            "training_manifest_sha256": sha256(train_manifest),
            "validation_manifest_sha256": sha256(validation_manifest),
            "script_sha256": {name: sha256(name) for name in script_names},
        },
        "protocol": {
            "train_attempted": 16,
            "train_prepared": 9,
            "validation_attempted": 8,
            "validation_prepared": 5,
            "views_per_asset": 12,
            "resolution": [256, 256],
            "box_samples_per_pixel": 4,
            "quality_metrics": METRICS,
            "uncertainty_unit": "asset",
        },
        "ranks": records,
    }

    lines = [
        "# Cluster Decoder Rank Sweep",
        "",
        "Date: 2026-11-22. This development screen tests whether the negative",
        "rank-8 result was caused by too little shared-basis capacity. It varies only",
        "the rank of the existing shared polynomial linear-subspace decoder. This is",
        "not a neural decoder, a new algorithm, or a publication result.",
        "",
        "## Protocol",
        "",
        "- Train-only basis fitting uses the same 9 prepared assets from the 16-asset",
        "  training split, ridge `1e-5`, and either fixed-topology displacement or",
        "  10%-face budgeted centroid refinement. Ranks 8, 16, and the maximum allowed",
        "  rank 30 are compared. Three training QEM outputs failed preparation.",
        "- Validation has 5 prepared assets out of 8; three QEM bases failed strict",
        "  preparation. No failed asset was repaired, dropped silently, or replaced.",
        "  No test manifest or test geometry was loaded.",
        "- Quality uses 12 orthographic views at 256 x 256, four raster samples per",
        "  pixel, flat grayscale shading, PSNR, SSIM, LDR-FLIP, calibrated SqueezeNet",
        "  LPIPS, silhouette XOR, and coverage MAE. Intervals resample assets, not views.",
        "- The fixed decoder is compared with its QEM base at identical face count.",
        "  Refinement adds faces and is not an equal-face comparison. Sidecar bytes",
        "  exclude the separately reported shared model file.",
        "",
        "## Validation results",
        "",
        "Deltas are decoder minus the same per-asset QEM base. Negative PSNR/SSIM",
        "and positive FLIP/LPIPS/silhouette/coverage deltas are worse. Intervals are",
        "95% paired asset-bootstrap intervals from 2,000 resamples (seed",
        "`20261121`).",
        "",
        "| Rank | Shared fixed/refine model bytes | Fixed decoded | Fixed sidecar mean B | Fixed PSNR dB | Fixed SSIM | Fixed FLIP | Fixed LPIPS | Refine decoded | Refine sidecar mean B |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in records:
        fixed = row["validation_metrics_vs_qem"]["fixed"]["metrics"]
        lines.append(
            f"| {row['rank']} | {row['model_file_bytes']['fixed']} / "
            f"{row['model_file_bytes']['refine']} | "
            f"{row['validation_decode']['fixed']['decoded']}/5 | "
            f"{row['validation_mean_sidecar_bytes']['fixed']:.0f} | "
            f"{fmt_delta(fixed.get('psnr_db'))} | "
            f"{fmt_delta(fixed.get('ssim'), 5)} | "
            f"{fmt_delta(fixed.get('flip'), 5)} | "
            f"{fmt_delta(fixed.get('lpips_squeeze'), 5)} | "
            f"{row['validation_decode']['refine']['decoded']}/5 | "
            f"{row['validation_mean_sidecar_bytes']['refine']:.0f} |"
        )
    lines.extend([
        "",
        "### Fixed-topology metric details",
        "",
        "| Rank | Paired validation assets | PSNR delta dB | SSIM delta | FLIP delta | LPIPS delta | Silhouette XOR delta | Coverage MAE delta |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in records:
        comparison = row["validation_metrics_vs_qem"]["fixed"]
        metrics = comparison["metrics"]
        lines.append(
            f"| {row['rank']} | {comparison['paired_assets']}/5 | "
            + " | ".join([
                fmt_delta(metrics.get("psnr_db")),
                fmt_delta(metrics.get("ssim"), 5),
                fmt_delta(metrics.get("flip"), 5),
                fmt_delta(metrics.get("lpips_squeeze"), 5),
                fmt_delta(metrics.get("silhouette_xor_fraction"), 5),
                fmt_delta(metrics.get("coverage_mae"), 5),
            ]) + " |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "Increasing rank did not rescue the fixed decoder. Every rank is worse than",
        "QEM on every reported fixed-topology metric over its valid paired assets.",
        "Ranks 8 and 16 share the same four valid pairs; rank 16 has larger deltas in",
        "the wrong direction and larger shared weights and sidecars. Rank 30 decodes",
        "only three validation meshes, so its smaller paired set cannot be compared",
        "directly with the four-asset estimates. It is still worse on all metrics and",
        "has two fixed-decoder validation failures. Refinement decodes on 3/5",
        "validation assets at ranks 8 and 16 and 2/5 at rank 30; it does not",
        "provide an equal-face result.",
        "",
        "Decision: close the tested polynomial ranks 8, 16, and 30. This does not",
        "rule out other learned decoders, but the current linear residual target and",
        "basis do not translate lower pointwise fitting error into better rendered",
        "quality. Do not use the test split to tune this family. A future method needs",
        "a new mechanism and a fresh licensed confirmation set.",
        "",
        "## Reproduction",
        "",
        "Use the pinned local dependencies described in the [rank-8 protocol](CLUSTER_DECODER_QUALITY_20261121.md).",
        "Run each rank independently from the same frozen training pairs:",
        "",
        "```powershell",
        "$env:PYTHONPATH = (Resolve-Path 'out/image-quality-deps').Path + ';' + (Resolve-Path 'out/geometry-refinement-pilot/deps').Path",
        "$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')",
        "$env:OPENBLAS_NUM_THREADS = '1'",
        "foreach ($rank in 8,16,30) {",
        "  $fit = \"out/cluster-decoder-fit/rank$rank\"",
        "  $quality = \"out/cluster-decoder-quality/rank$rank\"",
        "  python tools/mmtrain/fit_cluster_decoder.py out/cluster-decoder-pairs/train-pruned/manifest.json --out $fit --rank $rank",
        "  python tools/mmtrain/cluster_decoder_quality.py --pairs out/cluster-decoder-pairs/train-pruned/manifest.json --pairs out/cluster-decoder-pairs/validation/manifest.json --fit $fit --out $quality --views 12 --size 256 --samples 2",
        "  python tools/mmmetrics/summarize_decoder_quality.py \"$quality/report.json\" --out \"$quality/summary.json\"",
        "}",
        "python tools/mmtrain/summarize_cluster_decoder_rank_sweep.py --report-out tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md --json-out tools/mmtrain/cluster_decoder_rank_sweep_20261122.json",
        "```",
        "",
        "The [machine-readable receipt](cluster_decoder_rank_sweep_20261122.json) binds",
        "the manifests, model artifacts, quality reports, and source hashes. Full per-view",
        "renders and summaries remain under the ignored `out/cluster-decoder-*` folders.",
        "",
    ])

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    args.json_out.write_text(json.dumps(receipt, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    print(f"wrote {args.report_out} and {args.json_out}")


if __name__ == "__main__":
    main()
