"""Aggregate the frozen Poly Haven screen by asset and source-collection group."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
METRICS = ("flip", "psnr_db", "ssim", "silhouette_xor_fraction")
ARMS = ("qem_preserve_border", "meshoptimizer_lock_border")
MODES = ("native", "msaa4")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--geometry-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261124)
    args = parser.parse_args()

    manifest_path, receipt_path = args.manifest.resolve(), args.receipt.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    geometry_receipt_path = args.geometry_receipt.resolve()
    geometry_receipt = json.loads(geometry_receipt_path.read_text(encoding="utf-8"))
    manifest_hash = digest(manifest_path)
    if receipt.get("status") != "complete" or receipt.get("manifest_sha256") != manifest_hash:
        raise ValueError("The raw scoring receipt is incomplete or uses another manifest")

    receipt_by_asset = {row["asset"]: row for row in receipt["assets"]}
    rows = []
    raw_receipts = {}
    for slug, specification in manifest["assets"].items():
        run = receipt_by_asset.get(slug)
        if not run or run.get("status") != "scored":
            raise ValueError(f"Missing completed score for {slug}")
        raw_path = ROOT / run["raw_receipt"]
        if digest(raw_path) != run["raw_sha256"]:
            raise ValueError(f"Raw result hash mismatch for {slug}")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if raw.get("manifest_sha256") != manifest_hash or len(raw["views"]) != 24:
            raise ValueError(f"View count or manifest mismatch for {slug}")
        deltas = {}
        for mode in MODES:
            deltas[mode] = {}
            for arm in ARMS:
                deltas[mode][arm] = {
                    metric: (None if raw["summary"]["manymesh"][mode]["mean"][metric] is None
                             or raw["summary"][arm][mode]["mean"][metric] is None
                             else raw["summary"]["manymesh"][mode]["mean"][metric]
                             - raw["summary"][arm][mode]["mean"][metric])
                    for metric in METRICS
                }
        rows.append({
            "asset": slug,
            "class": specification["class"],
            "uncertainty_group": specification["uncertainty_group"],
            "source_sha256": specification["source_sha256"],
            "source_faces": raw["source_faces"],
            "control_faces": raw["control_faces"],
            "retention": specification["retention"],
            "raw_receipt": run["raw_receipt"],
            "raw_sha256": run["raw_sha256"],
            "summary": raw["summary"],
            "surface": raw["surface"],
            "per_view_metrics": raw["views"],
            "delta_manymesh_minus_control": deltas,
        })
        raw_receipts[slug] = {"path": run["raw_receipt"], "sha256": run["raw_sha256"]}

    groups = sorted({row["uncertainty_group"] for row in rows})
    rng = np.random.default_rng(args.seed)
    paired = {}
    for mode in MODES:
        paired[mode] = {}
        for arm in ARMS:
            paired[mode][arm] = {}
            for metric in METRICS:
                by_group = []
                for group in groups:
                    values = [row["delta_manymesh_minus_control"][mode][arm][metric]
                              for row in rows if row["uncertainty_group"] == group]
                    finite = [value for value in values if value is not None]
                    if finite:
                        by_group.append(float(np.mean(finite)))
                values = np.asarray(by_group, dtype=np.float64)
                samples = rng.integers(0, len(values), size=(args.bootstrap_samples, len(values)))
                means = values[samples].mean(axis=1)
                paired[mode][arm][metric] = {
                    "group_mean_delta": float(values.mean()),
                    "percentile_95_ci": [float(np.quantile(means, 0.025)),
                                          float(np.quantile(means, 0.975))],
                    "groups": int(len(values)),
                    "groups_won_by_manymesh": int(np.count_nonzero(values < 0)
                        if metric in ("flip", "silhouette_xor_fraction")
                        else np.count_nonzero(values > 0)),
                    "groups_tied": int(np.count_nonzero(values == 0)),
                }

    adapters = {json.dumps(row.get("adapter", {}), sort_keys=True) for row in receipt["assets"]}
    packages = {json.dumps(row.get("packages", {}), sort_keys=True) for row in receipt["assets"]}
    result = {
        "schema": 1,
        "status": "complete",
        "quality_scored": True,
        "manifest_sha256": manifest_hash,
        "runner_receipt_sha256": digest(receipt_path),
        "summary_script_sha256": digest(Path(__file__)),
        "scorer_sha256": receipt["scorer_sha256"],
        "geometry_build": {
            "mmgeo_sha256": geometry_receipt["mmgeo_sha256"],
            "source_revision_pin": geometry_receipt["source_revision_pin"],
            "source_screen_sha256": geometry_receipt["source_screen_sha256"],
            "clean_rebuild_verified": False,
            "rebuild_limit": "The Poly Haven and Khronos receipts pin the same mmgeo binary hash but record different main.cpp SHA-256 values. The archived patch reconstructs only the Khronos value, leaving source provenance unresolved. The compiler environment is recorded, but the exact build command is missing, so this is not a verified clean-source rebuild.",
        },
        "hardware_adapter_records": sorted(adapters),
        "package_records": sorted(packages),
        "assets": len(rows),
        "classes": sorted({row["class"] for row in rows}),
        "uncertainty_groups": len(groups),
        "view_distance_pairs_per_asset": 24,
        "bootstrap": {"unit": "connected source-collection group", "samples": args.bootstrap_samples,
                      "seed": args.seed, "interval": "paired percentile 95% interval"},
        "protocol_limitations": [
            "Coverage MAE was listed in the pre-score plan, but the pinned scorer emits silhouette XOR rather than coverage MAE; coverage MAE is unavailable and was not inferred.",
            "The scorer did not measure GPU frame time, LPIPS, temporal stability, mobile hardware, or human preference.",
            "The render comparison uses a fixed desktop image-quality protocol; it is not equal-frame-time evidence.",
            "The Poly Haven and Khronos receipts pin the same mmgeo binary hash but record different main.cpp hashes; the source identity conflict is unresolved. The compiler environment is recorded, but no exact build command or clean rebuild is available.",
        ],
        "paired_group_deltas_manymesh_minus_control": paired,
        "raw_receipts": raw_receipts,
        "per_asset": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    if args.markdown:
        lines = [
            "# Poly Haven matched-face image-quality screen",
            "",
            "Completed 2026-11-24. This is a fixed-view desktop geometry-quality",
            "screen, not a SIGGRAPH contribution or mobile-performance result.",
            "All 21 models were selected by source topology and exact-face/boundary",
            "eligibility before any image quality was scored. No model was used for",
            "training or parameter tuning. The 21 unique source meshes form 16",
            "collection groups for uncertainty estimates.",
            "",
            "## Protocol",
            "",
            "- 21 CC0 Poly Haven models in six classes, each at an exact common face",
            "  count near 50% retention. ManyMesh, border-preserving QEM, and",
            "  meshoptimizer LockBorder all preserve the source directed boundary and",
            "  pass the recorded triangle/edge topology audit.",
            "- Iris Xe, D3D12, 640x360 offscreen rasterization. The reference is the",
            "  original source at 2x resolution with 4x MSAA and a linear box resolve.",
            "  Each model uses 12 fixed perspective directions at two distances",
            "  (24 view-distance pairs). Candidate renders use native sampling and",
            "  4x MSAA.",
            "- Reported image metrics are LDR-FLIP (67 pixels/degree), pooled-MSE",
            "  PSNR, SSIM, and binary silhouette XOR. Sampled bidirectional surface",
            "  distance and normal consistency are also recorded.",
            "- Paired uncertainty resamples the 16 connected source-collection groups",
            "  10,000 times. All individual model results are listed below and in the",
            "  machine-readable receipt.",
            "",
            "## Result",
            "",
            "**Across the cohort, group-mean ManyMesh quality was worse than both",
            "deterministic controls on all four image metrics in both sampling",
            "modes.** The paired 95% group-bootstrap intervals exclude zero for every",
            "metric. Four of 16 metric/control/mode comparisons show one group win",
            "against QEM; the other 12 show none. ManyMesh had no wins against",
            "meshoptimizer. This closes this fixed 50% ManyMesh configuration as a",
            "quality-improving method on this eligible cohort.",
            "",
            "Delta is ManyMesh minus the named control. Lower FLIP and silhouette XOR",
            "are better; higher PSNR and SSIM are better. Therefore positive FLIP/XOR",
            "and negative PSNR/SSIM deltas favor the control.",
            "",
            "| Candidate mode | Control | Metric | Mean paired delta | 95% group-bootstrap CI | ManyMesh wins / 16 groups |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for mode in MODES:
            for arm in ARMS:
                for metric in METRICS:
                    stat = paired[mode][arm][metric]
                    low, high = stat["percentile_95_ci"]
                    lines.append(
                        f"| {mode} | {arm} | {metric} | {stat['group_mean_delta']:+.6f} "
                        f"| [{low:+.6f}, {high:+.6f}] | {stat['groups_won_by_manymesh']}/16 |")
        lines += [
            "",
            "## Per-model image deltas",
            "",
            "Each cell is the mean LDR-FLIP delta (ManyMesh minus control) across the",
            "model's 24 view-distance pairs; lower is better.",
            "",
            "| Asset | Class | Faces | Native vs QEM | 4x MSAA vs QEM | Native vs meshoptimizer | 4x MSAA vs meshoptimizer |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            d = row["delta_manymesh_minus_control"]
            lines.append(
                f"| {row['asset']} | {row['class']} | {row['control_faces']:,} "
                f"| {d['native']['qem_preserve_border']['flip']:+.6f} "
                f"| {d['msaa4']['qem_preserve_border']['flip']:+.6f} "
                f"| {d['native']['meshoptimizer_lock_border']['flip']:+.6f} "
                f"| {d['msaa4']['meshoptimizer_lock_border']['flip']:+.6f} |")
        lines += [
            "",
            "## Limits and reproducibility",
            "",
            "The cohort is conditioned on passing the static source topology and",
            "matched-face boundary gates; it does not represent every mesh. The",
            "renderer and views are fixed and desktop-only. This is not an equal-time",
            "comparison. The pinned scorer did not emit the predeclared coverage-MAE",
            "field, so it is unavailable; it was not reconstructed from other metrics.",
            "LPIPS, temporal behavior, GPU frame time, mobile-device performance, and",
            "human preference were not measured.",
            "The Poly Haven geometry receipts use the same mmgeo executable hash as",
            "the Khronos receipt, but their recorded main.cpp SHA-256 values differ.",
            "The archived patch reconstructs the Khronos value, not the Poly Haven",
            "value. Source identity remains unresolved. The compiler environment is",
            "recorded, but no exact build command or clean source rebuild is available.",
            "See the [source-provenance audit](mmgeo_source_provenance_audit_20261124.json)",
            "and [audit script](audit_mmgeo_main_source_provenance.py).",
            "",
            "The [frozen cohort](polyhaven_quality_cohort_20261124.json), complete",
            "[per-view metrics and geometry metrics](polyhaven_quality_metrics_20261124.json),",
            "and [runner receipt](polyhaven_quality_screen_20261124.json) preserve the",
            "protocol, hashes, commands, all per-asset measurements, and raw receipt",
            "hashes. Raw renderer receipts remain local under",
            "`out/polyhaven-quality-screen-20261124/`.",
            "The source geometry screen and fixed-face eligibility reports are",
            "[here](POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md) and",
            "[here](POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md).",
            "The fixed image-scoring stage was replayed from the same geometry",
            "exports on the same Iris Xe/D3D12 setup. All 21 score receipts matched",
            "byte-for-byte and the paired bootstrap values matched. This verifies",
            "the scoring stage only; it does not resolve the geometry-source",
            "identity conflict. See the [replay audit](POLYHAVEN_SCORE_REPLAY_AUDIT_20261124.md).",
            "",
        ]
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("summarized", len(rows), "assets in", len(groups), "source groups")
    for mode in MODES:
        print(mode)
        for arm in ARMS:
            print(" ", arm)
            for metric in METRICS:
                print("   ", metric, paired[mode][arm][metric])


if __name__ == "__main__":
    main()
