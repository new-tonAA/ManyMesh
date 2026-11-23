"""Build a compact, hash-linked summary of the exploratory Khronos quality screen."""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUPPORT_FILES = (
    "tools/mmgeo/audit_target_budget_visibility.py",
    "tools/mmtrain/audit_cut_boundary_geometry.py",
    "tools/mmtrain/bench_upstream_clusterlod.py",
    "tools/mmtrain/cluster_decoder.py",
    "tools/mmtrain/cluster_decoder_meshopt_baseline.py",
    "tools/mmtrain/cluster_decoder_pilot.py",
    "tools/mmtrain/cluster_decoder_quality.py",
    "tools/mmtrain/cluster_decoder_surface_quality.py",
    "tools/mmtrain/compare_qem_meshopt_validation_70pct.py",
    "tools/mmtrain/direct_cluster_control.py",
    "tools/mmtrain/fit_cluster_decoder.py",
    "tools/mmtrain/fused_tile_features.py",
    "tools/mmtrain/make_refinement_pairs.py",
    "tools/mmtrain/score_mmgeo_obj_diagnostic_controls.py",
    "tools/mmtrain/tile_refinement.py",
    "tools/mmtrain/extract_static_gltf_geometry.py",
    "tools/mmtrain/adapt_position_ply.py",
    "tools/mmtrain/KHRONOS_QUALITY_SCREEN_PROTOCOL_20261123.md",
    "tools/mmtrain/khronos_quality_screen_protocol_20261123.json",
    "tools/mmtrain/khronos_quality_screen_environment_20261123.json",
    "tools/mmtrain/current_mmgeo_source_patch_20261123.zip",
    "third_party/meshoptimizer/js/meshopt_simplifier.js",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    raw_receipts = []
    provenance = None
    for strict_path in sorted(args.screen_root.glob("*/scored-v1/receipt.json")):
        asset_dir = strict_path.parents[1]
        name = asset_dir.name
        ulp_path = asset_dir / "scored-one-ulp-diagnostic" / "receipt.json"
        if not ulp_path.is_file():
            raise FileNotFoundError(f"Missing one-ULP diagnostic receipt: {ulp_path}")
        strict = json.loads(strict_path.read_text(encoding="utf-8"))
        ulp = json.loads(ulp_path.read_text(encoding="utf-8"))
        if strict["source_sha256"] != ulp["source_sha256"]:
            raise ValueError(f"Source hash differs between runs for {name}")
        this_provenance = {
            "parent_revision": strict["source_revision"],
            "python_version": strict["python_version"],
            "numpy_version": strict["numpy_version"],
            "fast_simplification_version": strict["fast_simplification_version"],
            "scikit_image_version": strict["scikit_image_version"],
            "node_version": strict["node_version"],
            "mmgeo_binary_sha256": strict["mmgeo_sha256"],
            "mmgeo_main_sha256": strict["mmgeo_main_sha256"],
            "strict_scoring_script_sha256": strict["script_sha256"],
            "one_ulp_scoring_script_sha256": ulp["script_sha256"],
        }
        if provenance is None:
            provenance = this_provenance
        elif provenance != this_provenance:
            raise ValueError(f"Executable or script provenance differs for {name}")
        raw_receipts.extend((
            {"path": str(strict_path), "sha256": digest(strict_path), "rule": "exact directed edge set"},
            {"path": str(ulp_path), "sha256": digest(ulp_path), "rule": "retrospective one-float32-ULP curve match"},
        ))
        for strict_cut, cut in zip(strict["cuts"], ulp["cuts"], strict=True):
            controls = {}
            for method, control in sorted(cut.get("controls", {}).items()):
                controls[method] = {
                    "eligible": bool(control.get("eligible")),
                    "faces": control.get("faces"),
                    "metrics": control.get("metrics", {}).get("image"),
                    "candidate_minus_control": control.get("candidate_minus_control"),
                }
            rows.append({
                "asset": name,
                "source_sha256": ulp["source_sha256"],
                "requested_ratio": cut["requested_ratio"],
                "actual_faces": cut["actual_faces"],
                "actual_ratio": cut["actual_ratio"],
                "eligible_exact_edges": bool(strict_cut["candidate_eligible"]),
                "eligible_one_ulp": bool(cut["candidate_eligible"]),
                "topology_error": cut["candidate"].get("topology_error"),
                "candidate_metrics": cut["candidate"].get("image"),
                "boundary_audit": cut.get("candidate_boundary_curve_audit"),
                "controls": controls,
            })

    if not rows:
        raise ValueError(f"No strict screen receipts found under {args.screen_root}")

    report = {
        "label": "exploratory development-pool screen; not held-out confirmation",
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "summary_script_sha256": digest(__file__),
        "python_version": platform.python_version(),
        "scoring_environment": {
            key: provenance[key]
            for key in ("python_version", "numpy_version", "fast_simplification_version",
                        "scikit_image_version", "node_version")
        },
        "strict_protocol_sha256": digest(args.screen_root / "protocol.json"),
        "adapter_script_sha256": digest(args.screen_root / "adapt_position_ply.py"),
        "environment_receipt": {
            "path": "tools/mmtrain/khronos_quality_screen_environment_20261123.json",
            "sha256": digest(ROOT / "tools/mmtrain/khronos_quality_screen_environment_20261123.json"),
        },
        "mmgeo_source_patch": {
            "patch_path": "tools/mmtrain/current_mmgeo_source_patch_20261123.diff",
            "patch_sha256": digest(ROOT / "tools/mmtrain/current_mmgeo_source_patch_20261123.diff"),
            "archive_path": "tools/mmtrain/current_mmgeo_source_patch_20261123.zip",
            "archive_sha256": digest(ROOT / "tools/mmtrain/current_mmgeo_source_patch_20261123.zip"),
        },
        "support_files": [
            {"path": path, "sha256": digest(ROOT / path)} for path in SUPPORT_FILES
        ],
        "run_provenance": provenance,
        "candidate_eligibility_rule": {
            "initial": "manifold/orientation pass and exact directed boundary edge set",
            "follow_up": "manifold/orientation pass and one-to-one oriented boundary-vertex mapping within 1 float32 epsilon after normalized-coordinate conversion",
            "follow_up_status": "chosen retrospectively after inspecting the separate Monkey export-precision diagnostic; not preregistered",
        },
        "comparison_protocol": {
            "reference": "original full-resolution static geometry extracted from source GLB/OBJ",
            "views": 8,
            "resolution": "192x192",
            "sampling": "4 CPU software samples per pixel; not hardware MSAA",
            "metrics": ["LDR-FLIP", "PSNR", "SSIM", "silhouette XOR", "coverage MAE", "sampled Chamfer", "sampled p95 distance", "sampled normal consistency"],
            "controls": ["fast-simplification QEM", "meshoptimizer whole-mesh LockBorder"],
            "target_face_ratios": [0.3, 0.5, 0.7],
        },
        "raw_receipts": raw_receipts,
        "cuts": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"summary: {args.out}")
    print(f"cuts: {len(rows)}; one-ULP eligible: {sum(row['eligible_one_ulp'] for row in rows)}")


if __name__ == "__main__":
    main()
