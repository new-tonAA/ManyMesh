"""Compute the frozen image-quality metrics for local Iris Xe MSAA captures."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import flip_evaluator
from skimage.metrics import structural_similarity


def score(reference, image):
    ref = reference.astype(np.float32) / 255.
    rgb = image.astype(np.float32) / 255.
    mse = float(np.mean((ref - rgb) ** 2, dtype=np.float64))
    _, flip, _ = flip_evaluator.evaluate(np.repeat(ref[..., None], 3, axis=-1),
                                         np.repeat(rgb[..., None], 3, axis=-1), "LDR",
                                         inputsRGB=True, applyMagma=False,
                                         parameters={"ppd": 67.})
    return {"psnr_db": None if mse == 0 else -10 * float(np.log10(mse)),
            "ssim": float(structural_similarity(
                ref, rgb, data_range=1., gaussian_weights=True, sigma=1.5,
                use_sample_covariance=False)),
            "flip": float(flip)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(rows):
    output = {}
    for arm in ("joint_fit", "fitted_control"):
        samples = [row[arm] for row in rows]
        mse = float(np.mean([item["mse"] for item in samples]))
        output[arm] = {
            "pooled_mse": mse,
            "pooled_psnr_db": None if mse == 0 else float(-10 * np.log10(mse)),
            "mean_flip": float(np.mean([item["flip"] for item in samples])),
            "worst_flip": float(np.max([item["flip"] for item in samples])),
            "mean_ssim": float(np.mean([item["ssim"] for item in samples])),
            "worst_ssim": float(np.min([item["ssim"] for item in samples])),
            "mean_silhouette_xor_fraction": float(np.mean(
                [item["silhouette_xor_fraction"] for item in samples])),
            "worst_silhouette_xor_fraction": float(np.max(
                [item["silhouette_xor_fraction"] for item in samples])),
        }
    candidate, control = output["joint_fit"], output["fitted_control"]
    output["joint_minus_control"] = {
        "pooled_psnr_db": candidate["pooled_psnr_db"] - control["pooled_psnr_db"],
        "mean_flip": candidate["mean_flip"] - control["mean_flip"],
        "mean_ssim": candidate["mean_ssim"] - control["mean_ssim"],
        "mean_silhouette_xor_fraction": (
            candidate["mean_silhouette_xor_fraction"]
            - control["mean_silhouette_xor_fraction"]),
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--raw-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    raw = json.loads(args.raw_receipt.read_text(encoding="utf-8"))
    if digest(args.captures) != raw["capture_archive_sha256"]:
        raise ValueError("Capture archive hash does not match the hardware receipt")
    archive = np.load(args.captures, allow_pickle=False)
    results = []
    output_budgets = []
    shared_reference_hashes = None
    for budget in raw["budgets"]:
        rows = []
        for view in budget["views"]:
            reference_key = view["reference_capture"]
            reference = archive[reference_key]
            reference_hash = hashlib.sha256(reference.tobytes()).hexdigest()
            if reference_hash != budget["image_sha256"]["reference"][view["view"]]:
                raise ValueError(f"Reference image hash mismatch: {reference_key}")
            row = {"view": view["view"], "screen_scale": view["screen_scale"]}
            row["arms"] = {}
            for arm in ("joint_fit", "fitted_control"):
                row["arms"][arm] = {}
                for mode in ("native", "msaa4"):
                    metadata = view["arms"][arm][mode]
                    image = archive[metadata["capture"]]
                    image_hash = hashlib.sha256(image.tobytes()).hexdigest()
                    if image_hash != metadata["image_sha256"]:
                        raise ValueError(f"Candidate image hash mismatch: {metadata['capture']}")
                    metrics = score(reference, image)
                    metrics["mse"] = float(np.mean(
                        ((reference.astype(np.float64) - image) / 255.) ** 2))
                    metrics["silhouette_xor_fraction"] = metadata["silhouette_xor_fraction"]
                    metrics["image_sha256"] = image_hash
                    row["arms"][arm][mode] = metrics
            rows.append(row)
        current_hashes = budget["image_sha256"]["reference"]
        if shared_reference_hashes is None:
            shared_reference_hashes = current_hashes
        elif current_hashes != shared_reference_hashes:
            raise ValueError("Source reference changed across face budgets")
        summaries = {mode: summarize([
            {arm: row["arms"][arm][mode] for arm in ("joint_fit", "fitted_control")}
            for row in rows]) for mode in ("native", "msaa4")}
        output_budgets.append({"face_count": budget["face_count"],
                               "control": budget["control"], "views": rows,
                               "summary": summaries})
        results.append({"face_count": budget["face_count"],
                        "msaa4_delta": summaries["msaa4"]["joint_minus_control"]})

    reversals = sum(result["msaa4_delta"]["mean_flip"] < 0
                    and result["msaa4_delta"]["pooled_psnr_db"] > 0
                    for result in results)
    decision = ("ranking_reversed_on_at_least_two_budgets" if reversals >= 2
                else "prior_negative_ranking_not_reversed")
    report = {
        "status": "completed", "decision": decision, "budgets_reversed": reversals,
        "hardware_receipt_sha256": digest(args.raw_receipt),
        "capture_archive_sha256": digest(args.captures),
        "metric_script_sha256": digest(Path(__file__)),
        "metric_backend": "WSL2 CPU; hardware image captures were produced on Iris Xe D3D12",
        "flip_evaluator_version": importlib.metadata.version("flip-evaluator"),
        "numpy_version": importlib.metadata.version("numpy"),
        "scikit_image_version": importlib.metadata.version("scikit-image"),
        "metrics": "sRGB PSNR pooled over pixels and views; gaussian SSIM; LDR-FLIP at 67 ppd; coverage-mask XOR",
        "correlated_views_are_not_independent_samples": True,
        "budgets": output_budgets,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"decision": decision, "budgets_reversed": reversals,
                      "msaa4_delta": results}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
