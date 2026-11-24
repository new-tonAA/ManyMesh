#!/usr/bin/env python3
"""Audit the 16 primary Poly Haven comparisons with simultaneous intervals."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
METRICS = ("psnr_db", "ssim", "flip", "silhouette_xor_fraction")
LOWER_IS_BETTER = {"flip", "silhouette_xor_fraction"}
MODES = ("native", "msaa4")
CONTROLS = ("qem_preserve_border", "meshoptimizer_lock_border")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tools/mmtrain/polyhaven_multiplicity_audit_20261125.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md")
    parser.add_argument("--samples", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=20261125)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    if source.get("status") != "complete" or source.get("assets") != 21:
        raise ValueError("Expected the completed 21-model quality screen")
    rows = source["per_asset"]
    groups = sorted({row["uncertainty_group"] for row in rows})
    if len(groups) != 16:
        raise ValueError(f"Expected 16 source groups, found {len(groups)}")

    endpoints = []
    columns = []
    for mode in MODES:
        for control in CONTROLS:
            for metric in METRICS:
                values = []
                for group in groups:
                    group_rows = [row for row in rows if row["uncertainty_group"] == group]
                    deltas = [row["delta_manymesh_minus_control"][mode][control][metric]
                              for row in group_rows]
                    delta = float(np.mean(deltas))
                    # Positive means ManyMesh is better for every plotted endpoint.
                    improvement = -delta if metric in LOWER_IS_BETTER else delta
                    values.append(improvement)
                column = np.asarray(values, dtype=np.float64)
                published = source["paired_group_deltas_manymesh_minus_control"][mode][control][metric]["group_mean_delta"]
                direction = -1.0 if metric in LOWER_IS_BETTER else 1.0
                if not np.isclose(column.mean(), direction * published, atol=1e-12, rtol=1e-12):
                    raise ValueError(f"Group reconstruction differs from published mean: {mode}/{control}/{metric}")
                columns.append(column)
                endpoints.append({"mode": mode, "control": control, "metric": metric})

    # Resample whole source groups once per replicate, shared across all endpoints.
    matrix = np.column_stack(columns)
    means = matrix.mean(axis=0)
    standard_errors = matrix.std(axis=0, ddof=1) / np.sqrt(matrix.shape[0])
    if np.any(standard_errors == 0):
        raise ValueError("A primary endpoint has zero between-group standard error")
    rng = np.random.default_rng(args.seed)
    indices = rng.integers(0, matrix.shape[0], size=(args.samples, matrix.shape[0]))
    bootstrap_means = matrix[indices].mean(axis=1)
    bootstrap_t = (bootstrap_means - means) / standard_errors
    max_t = np.max(np.abs(bootstrap_t), axis=1)
    critical = float(np.quantile(max_t, 0.95, method="linear"))
    results = []
    for index, endpoint in enumerate(endpoints):
        unadjusted = np.quantile(bootstrap_means[:, index], [0.025, 0.975], method="linear")
        simultaneous = [float(means[index] - critical * standard_errors[index]),
                        float(means[index] + critical * standard_errors[index])]
        results.append({
            **endpoint,
            "manymesh_improvement_mean": float(means[index]),
            "unadjusted_bootstrap_95_ci": [float(x) for x in unadjusted],
            "simultaneous_max_t_95_ci": simultaneous,
            "groups": int(matrix.shape[0]),
        })

    all_simultaneous_below_zero = all(row["simultaneous_max_t_95_ci"][1] < 0 for row in results)
    output = {
        "schema": 1,
        "status": "complete",
        "analysis_role": "post-hoc multiplicity robustness audit; no method or asset selection",
        "source_metrics_path": args.input.relative_to(ROOT).as_posix(),
        "source_metrics_sha256": sha256(args.input),
        "assets": len(rows),
        "groups": len(groups),
        "endpoints": len(results),
        "endpoint_family": "four predeclared image metrics x two controls x two sampling modes",
        "posthoc_lpips_included": False,
        "bootstrap": {
            "method": "centered cluster bootstrap max-|t| simultaneous confidence intervals",
            "resampling_unit": "connected source-collection group",
            "shared_resamples_across_endpoints": True,
            "samples": args.samples,
            "seed": args.seed,
            "familywise_confidence": 0.95,
            "max_t_critical_value": critical,
            "direction": "positive improvement favors ManyMesh",
        },
        "all_simultaneous_intervals_below_zero": all_simultaneous_below_zero,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    lines = [
        "# Poly Haven multiplicity robustness audit",
        "",
        "Completed 2026-11-25. This is a post-hoc statistical audit of the",
        "already-published 21-model screen. It neither selects a method nor",
        "changes the frozen asset cohort. Positive effects favor ManyMesh.",
        "",
        "## Method",
        "",
        "The family contains the 16 original endpoints: four image metrics",
        "(PSNR, SSIM, LDR-FLIP, and silhouette XOR), two matched-face controls,",
        "and two sampling modes. Views are averaged within asset, assets within",
        "connected source group, then whole groups are resampled. A shared set",
        f"of {args.samples:,} bootstrap draws preserves dependence across endpoints.",
        "The centered bootstrap max-|t| critical value gives two-sided",
        "familywise 95% simultaneous intervals. The bootstrap is an uncertainty",
        "model over this selected cohort, not random sampling of all possible meshes.",
        "",
        "LPIPS is excluded because it was added post hoc in a separate supplement.",
        "Its interval remains descriptive and does not affect the primary family.",
        "",
        "## Results",
        "",
        f"The max-|t| critical value is {critical:.4f}. All simultaneous upper bounds below zero: **{all_simultaneous_below_zero}**.",
        "",
        "| Mode | Control | Metric | ManyMesh improvement | Individual 95% CI | Simultaneous 95% CI |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in results:
        lo, hi = row["unadjusted_bootstrap_95_ci"]
        slo, shi = row["simultaneous_max_t_95_ci"]
        lines.append(
            f"| {row['mode']} | {row['control']} | {row['metric']} | {row['manymesh_improvement_mean']:+.6g} "
            f"| [{lo:+.6g}, {hi:+.6g}] | [{slo:+.6g}, {shi:+.6g}] |")
    lines += [
        "",
        "## Limits",
        "",
        "This does not turn the fixed-view Iris Xe comparison into an equal-time,",
        "mobile, temporal, or user-preference result. The candidate cohort was",
        "conditioned on static topology and exact-face boundary eligibility.",
        "The bootstrap intervals quantify source-group variation in these 21",
        "assets; they do not prove generalization to the wider mesh population.",
        "",
        "The machine-readable receipt preserves the input hash, seed, endpoint",
        "definitions, group means, and simultaneous intervals. See the [JSON receipt]",
        "(polyhaven_multiplicity_audit_20261125.json) and [analysis script]",
        "(audit_polyhaven_multiplicity.py). Reproduce with:",
        "",
        "```powershell",
        "python tools/mmtrain/audit_polyhaven_multiplicity.py",
        "```",
        "",
        f"Input SHA-256: `{output['source_metrics_sha256']}`.",
        "",
    ]
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("assets", len(rows), "groups", len(groups), "endpoints", len(results))
    print("max-t critical", critical)
    print("all simultaneous intervals below zero", all_simultaneous_below_zero)
    for row in results:
        lo, hi = row["simultaneous_max_t_95_ci"]
        print(row["mode"], row["control"], row["metric"],
              f"{row['manymesh_improvement_mean']:+.6g}",
              f"[{lo:+.6g}, {hi:+.6g}]")


if __name__ == "__main__":
    main()
