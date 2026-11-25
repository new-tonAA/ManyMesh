"""Validate and summarize the post-hoc Poly Haven silhouette diagnostic."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json"
ARMS = ("manymesh", "qem_preserve_border", "meshoptimizer_lock_border")
MODES = ("native", "msaa4")
LABELS = {
    "manymesh": "ManyMesh",
    "qem_preserve_border": "Border-preserving QEM",
    "meshoptimizer_lock_border": "meshoptimizer LockBorder",
}
DECOMP_SEED = 20261126
PAIRED_SEED = 20261127
BOOTSTRAP_SAMPLES = 10000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def aa_error_decomposition(rows, arm):
    by_group = {}
    for row in rows:
        native = row["arms"][arm]["native"]
        aa = row["arms"][arm]["msaa4"]
        total = native["total_squared_error"]
        values = {
            "total_error_reduction": (total - aa["total_squared_error"]) / total,
            "xor_error_reduction": (native["xor_squared_error"]
                                    - aa["xor_squared_error"]) / total,
            "non_xor_error_reduction": (native["non_xor_squared_error"]
                                        - aa["non_xor_squared_error"]) / total,
        }
        by_group.setdefault(row["uncertainty_group"], []).append(values)

    groups = sorted(by_group)
    keys = ("total_error_reduction", "xor_error_reduction", "non_xor_error_reduction")
    group_values = {
        key: np.asarray([np.mean([asset[key] for asset in by_group[group]])
                         for group in groups], dtype=np.float64)
        for key in keys
    }
    if not np.allclose(
            group_values["total_error_reduction"],
            group_values["xor_error_reduction"] + group_values["non_xor_error_reduction"],
            rtol=0.0, atol=1e-12):
        raise ValueError(f"XOR and non-XOR reductions do not add to total for {arm}")
    rng = np.random.default_rng(DECOMP_SEED)
    indices = rng.integers(0, len(groups),
                           size=(BOOTSTRAP_SAMPLES, len(groups)))
    result = {"group_count": len(groups), "bootstrap_seed": DECOMP_SEED,
              "bootstrap_samples": BOOTSTRAP_SAMPLES, "metrics": {}}
    for key, values in group_values.items():
        means = values[indices].mean(axis=1)
        result["metrics"][key] = {
            "group_mean": float(values.mean()),
            "group_bootstrap_95_percentile_ci": [
                float(value) for value in np.quantile(means, [0.025, 0.975])],
        }
    return result


def paired_aa_contrasts(rows):
    by_group = {}
    for row in rows:
        group = row["uncertainty_group"]
        by_group.setdefault(group, {})
        for arm in ARMS:
            native = row["arms"][arm]["native"]
            aa = row["arms"][arm]["msaa4"]
            total = native["total_squared_error"]
            effect = {
                "total": (total - aa["total_squared_error"]) / total,
                "xor": (native["xor_squared_error"] - aa["xor_squared_error"]) / total,
                "non_xor": (native["non_xor_squared_error"]
                            - aa["non_xor_squared_error"]) / total,
            }
            by_group[group].setdefault(arm, []).append(effect)

    groups = sorted(by_group)
    metrics = ("total", "xor", "non_xor")
    effects = {arm: {metric: np.asarray([
        np.mean([asset[metric] for asset in by_group[group][arm]])
        for group in groups], dtype=np.float64) for metric in metrics}
        for arm in ARMS}
    for control in ("qem_preserve_border", "meshoptimizer_lock_border"):
        total_difference = effects[control]["total"] - effects["manymesh"]["total"]
        partition_difference = (
            effects[control]["xor"] - effects["manymesh"]["xor"]
            + effects[control]["non_xor"] - effects["manymesh"]["non_xor"])
        if not np.allclose(total_difference, partition_difference, rtol=0.0, atol=1e-12):
            raise ValueError(f"Paired XOR partitions do not sum to total for {control}")
    rng = np.random.default_rng(PAIRED_SEED)
    indices = rng.integers(0, len(groups), size=(BOOTSTRAP_SAMPLES, len(groups)))
    results = {}
    for control in ("qem_preserve_border", "meshoptimizer_lock_border"):
        results[control] = {}
        for metric in metrics:
            differences = effects[control][metric] - effects["manymesh"][metric]
            means = differences[indices].mean(axis=1)
            results[control][metric] = {
                "mean_difference": float(differences.mean()),
                "group_bootstrap_95_percentile_ci": [
                    float(value) for value in np.quantile(means, [0.025, 0.975])],
                "groups_positive": int(np.count_nonzero(differences > 0)),
                "group_count": len(groups),
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    receipt_path = args.receipt.resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    if receipt.get("status") != "complete" or len(receipt.get("assets", [])) != 21:
        raise ValueError("Expected a complete 21-model diagnostic receipt")
    if receipt["protocol"]["metrics_sha256"] != digest(METRICS_PATH):
        raise ValueError("Diagnostic receipt does not match the current quality metrics")

    metrics_by_asset = {row["asset"]: row for row in metrics["per_asset"]}
    parity = 0
    for asset in receipt["assets"]:
        metric_row = metrics_by_asset[asset["asset"]]
        views = metric_row["per_view_metrics"]
        if len(views) != 24:
            raise ValueError(f"Unexpected view count for {asset['asset']}")
        for index, view in enumerate(views):
            for arm in ARMS:
                for mode in MODES:
                    expected = view["quality"][arm][mode]["silhouette_xor_fraction"]
                    observed = asset["arms"][arm][mode]["views"][index]["xor_fraction"]
                    if expected != observed:
                        raise ValueError(
                            f"Mask replay mismatch: {asset['asset']} view {index} {arm}/{mode}")
                    parity += 1

    lines = [
        "# Post-hoc silhouette error attribution across 21 models",
        "",
        "Completed 2026-11-25. This is a diagnostic on the already-scored Poly Haven cohort, not independent confirmation or a new method result.",
        "",
        "## Measurement",
        "",
        "For each of the 21 frozen meshes, compare the candidate render with the full-source reference at the same 24 perspective view-distance pairs. The reference is rendered at 2x resolution with 4x MSAA and linear box resolve. Candidate renders use native sampling or 4x MSAA at 640 x 360. All geometry was rechecked against the frozen face-count and directed-boundary receipt before rendering.",
        "",
        "Define the contour-error region as the binary coverage XOR (`gray > 0`) between the candidate and resolved source reference. The reported error share is the sum of squared **linear grayscale** render differences inside this XOR region divided by total squared grayscale error. Pixel shares and error shares are pooled over all 24 views within each asset. We then average assets within each of the 16 pre-existing source-collection groups and bootstrap those groups 10,000 times (seed 20261125).",
        "",
        "This is a geometric attribution diagnostic, not a perceptual metric. The cohort had already been examined for quality, the rendering is flat grayscale and fixed-view, and the grouping does not make it independent confirmation.",
        "",
        "## Results",
        "",
        "No source group assigns more than half of total squared image error to silhouette-XOR pixels in any arm or sampling mode. For ManyMesh, the group-mean share is 31.0% (95% group-bootstrap CI 27.4%–34.8%) with native sampling, falling to 16.3% (13.7%–19.1%) with 4x MSAA. The median asset's XOR region covers 0.171% of native pixels and 0.084% with 4x MSAA. Thus contour disagreement is overrepresented in the error, but it is not the majority of image error under this protocol; MSAA reduces its contribution substantially.",
        "",
        "| Candidate | Native error share, group mean (95% CI) | 4x MSAA error share, group mean (95% CI) | Groups above 50%, native / 4x |",
        "|---|---:|---:|---:|",
    ]
    for arm in ARMS:
        native = receipt["summary"][arm]["native"]
        msaa = receipt["summary"][arm]["msaa4"]
        lines.append(
            f"| {LABELS[arm]} | {100*native['group_mean']:.2f}% "
            f"({100*native['group_bootstrap_95_percentile_ci'][0]:.2f}%–"
            f"{100*native['group_bootstrap_95_percentile_ci'][1]:.2f}%) | "
            f"{100*msaa['group_mean']:.2f}% "
            f"({100*msaa['group_bootstrap_95_percentile_ci'][0]:.2f}%–"
            f"{100*msaa['group_bootstrap_95_percentile_ci'][1]:.2f}%) | "
            f"{native['groups_above_half']} / {msaa['groups_above_half']} |")

    lines += [
        "",
        "The screen's matched-face image-quality result still favors QEM and meshoptimizer over ManyMesh. The energy decomposition below shows why contour share alone is insufficient: 4x MSAA removes 38.8% of ManyMesh's native total squared error, versus 58.0% for QEM and 67.1% for meshoptimizer. For ManyMesh, 20.7 percentage points of native total error are removed inside the XOR mask and 18.1 points outside it. The component intervals are descriptive, not multiplicity-corrected.",
        "",
        "### What 4x MSAA removes",
        "",
        "The table below decomposes each arm's change in pooled squared error after enabling 4x MSAA. Each component is normalized by that arm's native total error; positive values are reductions, negative values are increases. The XOR mask is computed separately for each mode, so this is a descriptive partition rather than a tracked-pixel causal attribution. Intervals resample the 16 source groups; the three related intervals are descriptive and are not multiplicity corrected.",
        "",
        "| Candidate | Total error removed | XOR-region error removed | Non-XOR error removed |",
        "|---|---:|---:|---:|",
    ]
    decomposition = {}
    for arm in ARMS:
        decomposition[arm] = aa_error_decomposition(receipt["assets"], arm)
        items = decomposition[arm]["metrics"]
        cells = []
        for metric in ("total_error_reduction", "xor_error_reduction",
                       "non_xor_error_reduction"):
            item = items[metric]
            cells.append(
                f"{100*item['group_mean']:.1f}% "
                f"({100*item['group_bootstrap_95_percentile_ci'][0]:.1f}%–"
                f"{100*item['group_bootstrap_95_percentile_ci'][1]:.1f}%)")
        lines.append(f"| {LABELS[arm]} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "### Paired AA gain relative to ManyMesh",
        "",
        "These differences compare the fraction of each arm's native total error removed by 4x MSAA, subtracting ManyMesh from the control within each source group. Positive values mean MSAA removes a larger fraction of that control's own native error. Intervals use paired resampling of the same 16 groups (10,000 samples, seed 20261127). They are post-hoc and not multiplicity-corrected across the six contrasts.",
        "",
        "| Control minus ManyMesh | Total error removed | XOR-region error removed | Non-XOR error removed | Groups with larger total reduction |",
        "|---|---:|---:|---:|---:|",
    ]
    paired = paired_aa_contrasts(receipt["assets"])
    for control in ("qem_preserve_border", "meshoptimizer_lock_border"):
        cells = []
        for metric in ("total", "xor", "non_xor"):
            item = paired[control][metric]
            ci = item["group_bootstrap_95_percentile_ci"]
            cells.append(f"{100*item['mean_difference']:+.1f} pp "
                         f"({100*ci[0]:+.1f} to {100*ci[1]:+.1f})")
        total_groups = paired[control]["total"]
        lines.append(f"| {LABELS[control]} | " + " | ".join(cells) +
                     f" | {total_groups['groups_positive']}/{total_groups['group_count']} |")

    lines += [
        "",
        "### Per-asset error share",
        "",
        "Each value is the pooled XOR-region share of squared error. These per-asset values expose the spread hidden by the group mean.",
        "",
        "| Asset | ManyMesh native | ManyMesh 4x MSAA | QEM 4x MSAA | meshoptimizer 4x MSAA |",
        "|---|---:|---:|---:|---:|",
    ]
    for asset in receipt["assets"]:
        a = asset["arms"]
        vals = [a[arm][mode]["pooled_xor_error_share"] for arm, mode in (
            ("manymesh", "native"), ("manymesh", "msaa4"),
            ("qem_preserve_border", "msaa4"),
            ("meshoptimizer_lock_border", "msaa4"))]
        lines.append(f"| {asset['asset']} | " + " | ".join(f"{100*x:.1f}%" for x in vals) + " |")

    lines += [
        "",
        "## Reproducibility and limits",
        "",
        f"The 3,024 candidate/view/mode XOR-area values exactly match the frozen per-view quality metrics. This verifies the rerendered coverage masks; the squared-error attribution itself is newly computed. Source metrics SHA-256: `{receipt['protocol']['metrics_sha256']}`. Diagnostic script SHA-256: `{receipt['protocol']['script_sha256']}`. Summary script SHA-256: `{digest(Path(__file__))}`. Receipt SHA-256: `{digest(receipt_path)}`.",
        "",
        "The historical single-view Monkey result reported 68.3% using a DAG cut as reference. This multi-model screen instead uses the original source reference, 24 views per asset, flat grayscale shading, and the explicitly defined XOR mask. The values are not directly interchangeable. The new diagnostic does not invalidate that individual measurement; it shows that it should not be presented as a general property.",
        "",
        "The [frozen cohort manifest](polyhaven_quality_cohort_20261124.json) lists the per-asset geometry-export paths. These derived exports and source meshes are not vendored; regenerate them from the licensed CC0 assets using the [topology screen](POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md) and [matched-face export protocol](POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md). The checked-in attribution receipt and [primary per-view metrics](polyhaven_quality_metrics_20261124.json) suffice to recompute the reported tables without rerendering. Replaying the renderer requires the regenerated geometry exports.",
        "",
        "No materials, shadows, temporal accumulation, mobile device, equal-frame-time comparison, or human preference were measured. The analysis does not establish how perceptual metrics such as LDR-FLIP or LPIPS partition error spatially.",
        "",
        "Reproduce from the repository root with the recorded Python dependencies:",
        "",
        "```powershell",
        "$env:PYTHONPATH = 'out/manymesh-research-pydeps-20261123;out/geometry-refinement-pilot/deps;out/geometry-refinement-pilot/deps/wgpu'",
        "python tools/mmtrain/analyze_polyhaven_silhouette_share.py `",
        "  --out tools/mmtrain/polyhaven_silhouette_attribution_20261125.json",
        "python tools/mmtrain/summarize_polyhaven_silhouette_share.py `",
        "  --receipt tools/mmtrain/polyhaven_silhouette_attribution_20261125.json `",
        "  --report tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md",
        "```",
        "",
        f"Mask-parity audit: {parity}/{21*24*len(ARMS)*len(MODES)} exact matches. The full machine-readable per-asset and per-view receipt is checked in at [polyhaven_silhouette_attribution_20261125.json](polyhaven_silhouette_attribution_20261125.json). Raw image buffers were not retained.",
        "",
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("wrote", args.report, "mask parity", parity)


if __name__ == "__main__":
    main()
