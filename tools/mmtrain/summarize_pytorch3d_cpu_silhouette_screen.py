"""Aggregate the frozen per-asset CPU silhouette-fit receipts."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    assets = {}
    for name in ("BarramundiFish", "Corset"):
        directory = args.run_dir / name
        protocol_path = directory / "protocol.json"
        training_path = directory / "training.json"
        diagnostic_path = directory / "training-diagnostics.json"
        quality_path = directory / "quality.json"
        protocol = read(protocol_path)
        training = read(training_path)
        diagnostic = read(diagnostic_path)
        quality = read(quality_path)
        deltas = {}
        for mode in ("native", "msaa4"):
            candidate = quality["summary"]["fitted"][mode]["mean"]
            baseline = quality["summary"]["meshoptimizer_lock_border"][mode]["mean"]
            deltas[mode] = {
                key: candidate[key] - baseline[key]
                for key in ("psnr_db", "ssim", "flip", "silhouette_xor_fraction")
            }
        assets[name] = {
            "reference_faces": training["reference_faces"],
            "candidate_faces": training["fit_faces"],
            "inputs_sha256": training["inputs"],
            "source_script_sha256": training["script_sha256"],
            "source_manifest_sha256": training["manifest_sha256"],
            "optimizer_protocol_sha256": training["optimizer_protocol_sha256"],
            "fitted_sha256": training["fitted_sha256"],
            "fit_seconds": training["fit_seconds"],
            "target_preprocess_seconds": diagnostic["target_preprocess_seconds"],
            "fit_plus_target_preprocess_seconds": (
                training["fit_seconds"] + diagnostic["target_preprocess_seconds"]
            ),
            "peak_rss_bytes": training["peak_rss_bytes"],
            "first_gradient_norm": training["first_gradient_norm"],
            "maximum_displacement_observed": training["maximum_displacement_observed"],
            "fit_boundary_audit": training["fit_boundary_audit"],
            "training_coverage_mse": {
                "initial": diagnostic["initial_mean_mse"],
                "fitted": diagnostic["fitted_mean_mse"],
            },
            "quality": {
                "adapter": quality["adapter"],
                "packages": quality["packages"],
                "summary": quality["summary"],
                "fit_minus_meshoptimizer": deltas,
                "views": quality["views"],
                "scorer_script_sha256": quality["script_sha256"],
            },
            "raw_receipt_sha256": {
                "protocol": sha256(protocol_path),
                "training": sha256(training_path),
                "training_diagnostics": sha256(diagnostic_path),
                "quality": sha256(quality_path),
            },
            "preparation_protocol_sha256": protocol["script_sha256"],
        }

    result = {
        "status": "failed development gate; close this CPU silhouette-fit configuration",
        "source_revision": "8930619a4aeab2699060d3ed394575cd4ee79c39",
        "protocol": "PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_PROTOCOL_20261127.md",
        "corrected_run": True,
        "invalidated_attempt": "The first attempt used candidate face indices on source positions for target rasterization; all outputs from that attempt are excluded.",
        "raw_run_directory": "out/pytorch3d-cpu-silhouette-screen-corrected-20261127/",
        "assets_are_reused_development_data": True,
        "cross_asset_generalization_claim": False,
        "scoring_scope": "24 reserved camera-distance pairs per asset; WGPU Vulkan llvmpipe software adapter",
        "metrics": {
            "psnr_db": "higher is better",
            "ssim": "higher is better",
            "flip": "lower is better",
            "silhouette_xor_fraction": "lower is better",
        },
        "decision": (
            "The required mean LDR-FLIP improvement is absent on BarramundiFish "
            "under native sampling and absent on both assets under 4x MSAA. "
            "Do not advance this configuration to the reserved 30-model pool."
        ),
        "assets": assets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
