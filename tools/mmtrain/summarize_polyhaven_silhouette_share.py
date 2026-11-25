"""Validate and summarize the post-hoc Poly Haven silhouette diagnostic."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json"
ARMS = ("manymesh", "qem_preserve_border", "meshoptimizer_lock_border")
MODES = ("native", "msaa4")
LABELS = {
    "manymesh": "ManyMesh",
    "qem_preserve_border": "Border-preserving QEM",
    "meshoptimizer_lock_border": "meshoptimizer LockBorder",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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

    raw_by_asset = {}
    for row in metrics["per_asset"]:
        raw_by_asset[row["asset"]] = json.loads(
            (ROOT / row["raw_receipt"]).read_text(encoding="utf-8"))
    parity = 0
    for asset in receipt["assets"]:
        raw = raw_by_asset[asset["asset"]]
        if len(raw["views"]) != 24:
            raise ValueError(f"Unexpected view count for {asset['asset']}")
        for index, view in enumerate(raw["views"]):
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
        "The screen's matched-face image-quality result still favors QEM and meshoptimizer over ManyMesh. The lower control shares with MSAA do not mean their total image error is lower because of the attribution alone; see the primary quality metrics for total-error comparisons.",
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
        f"The 3,024 candidate/view/mode XOR-area values exactly match the frozen per-view quality metrics. This verifies the rerendered coverage masks; the squared-error attribution itself is newly computed. Source metrics SHA-256: `{receipt['protocol']['metrics_sha256']}`. Diagnostic script SHA-256: `{receipt['protocol']['script_sha256']}`. Receipt SHA-256: `{digest(receipt_path)}`.",
        "",
        "The historical single-view Monkey result reported 68.3% using a DAG cut as reference. This multi-model screen instead uses the original source reference, 24 views per asset, flat grayscale shading, and the explicitly defined XOR mask. The values are not directly interchangeable. The new diagnostic does not invalidate that individual measurement; it shows that it should not be presented as a general property.",
        "",
        "No materials, shadows, temporal accumulation, mobile device, equal-frame-time comparison, or human preference were measured. The analysis does not establish how perceptual metrics such as LDR-FLIP or LPIPS partition error spatially.",
        "",
        "Reproduce from the repository root with the recorded Python dependencies:",
        "",
        "```powershell",
        "$env:PYTHONPATH = 'out/manymesh-research-pydeps-20261123;out/geometry-refinement-pilot/deps;out/geometry-refinement-pilot/deps/wgpu'",
        "python tools/mmtrain/analyze_polyhaven_silhouette_share.py `",
        "  --out out/polyhaven-silhouette-share-3arms-20261125/receipt.json",
        "python tools/mmtrain/summarize_polyhaven_silhouette_share.py `",
        "  --receipt out/polyhaven-silhouette-share-3arms-20261125/receipt.json `",
        "  --report tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md",
        "```",
        "",
        f"Mask-parity audit: {parity}/{21*24*len(ARMS)*len(MODES)} exact matches. Raw image buffers were not retained; the machine-readable attribution receipt is in the ignored local `out/` directory.",
        "",
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("wrote", args.report, "mask parity", parity)


if __name__ == "__main__":
    main()
