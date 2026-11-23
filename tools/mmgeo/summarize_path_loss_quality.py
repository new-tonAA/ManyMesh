#!/usr/bin/env python3
"""Score matched path-loss and QEM renders with the project image metric panel."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys

import numpy as np
from PIL import Image

METRICS = ("psnr_db", "foreground_psnr_db", "ssim", "flip")
HIGHER_IS_BETTER = {"psnr_db", "foreground_psnr_db", "ssim"}


class MetricPanel:
    def __init__(self, ppd):
        import flip_evaluator
        import scipy
        import skimage
        from skimage.metrics import structural_similarity

        self.flip, self.ssim, self.ppd = flip_evaluator, structural_similarity, ppd
        self.settings = {"input": "8-bit sRGB, RGB in [0,1]",
                         "ssim": "Gaussian sigma=1.5, population covariance, K1=.01 K2=.03",
                         "flip": "official NVIDIA LDR-FLIP", "flip_ppd": ppd,
                         "lpips_squeeze": "not measured; pretrained SqueezeNet weights are not in the local writable cache",
                         "python": platform.python_version(),
                         "packages": {"numpy": np.__version__, "scipy": scipy.__version__,
                                      "flip-evaluator": version("flip-evaluator"),
                                      "scikit-image": skimage.__version__}}

    def __call__(self, reference, candidate, foreground):
        difference = reference.astype(np.float64) - candidate.astype(np.float64)
        mse = float(np.mean(difference ** 2))
        foreground_mse = float(np.mean(difference[foreground] ** 2))
        _, flip_mean, _ = self.flip.evaluate(
            reference.astype(np.float32), candidate.astype(np.float32), "LDR",
            inputsRGB=True, applyMagma=False, parameters={"ppd": float(self.ppd)})
        ssim = self.ssim(reference, candidate, data_range=1.0, channel_axis=2,
                         gaussian_weights=True, sigma=1.5, use_sample_covariance=False)
        return {"mse": mse, "foreground_mse": foreground_mse,
                "psnr_db": None if mse == 0 else float(-10 * np.log10(mse)),
                "foreground_psnr_db": None if foreground_mse == 0 else float(
                    -10 * np.log10(foreground_mse)),
                "ssim": float(ssim), "flip": float(flip_mean), "lpips_squeeze": None}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def asset_metric_rows(root, record, metric):
    reference_images = record["renders"]["source"]["images"]
    rows = {"path": [], "qem": []}
    for index, ref_record in enumerate(reference_images):
        reference = image(root / ref_record["path"])
        foreground = np.any(reference > (2.0 / 255.0), axis=2)
        if not np.any(foreground):
            raise ValueError(f"empty foreground mask for {record['asset']} view {index}")
        for method in rows:
            candidate_record = record["renders"][method]["images"][index]
            candidate = image(root / candidate_record["path"])
            rows[method].append(metric(reference, candidate, foreground))
    return rows


def summarize_asset(rows):
    result = {}
    for method, values in rows.items():
        result[method] = {}
        for name in METRICS:
            if name in ("psnr_db", "foreground_psnr_db"):
                error_name = "mse" if name == "psnr_db" else "foreground_mse"
                errors = np.asarray([row[error_name] for row in values], dtype=float)
                mean_error = float(np.mean(errors))
                result[method][name] = (None if mean_error == 0 else
                                        float(-10 * np.log10(mean_error)))
                continue
            series = np.asarray([row[name] for row in values if row[name] is not None], dtype=float)
            result[method][name] = float(np.mean(series)) if len(series) else None
    return result


def bootstrap(values, seed=20261122, iterations=20000):
    values = np.asarray(values, dtype=float)
    generator = np.random.default_rng(seed)
    samples = generator.integers(0, len(values), size=(iterations, len(values)))
    means = values[samples].mean(axis=1)
    return [float(x) for x in np.quantile(means, [0.025, 0.975])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renders", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ppd", type=float, default=67.0)
    args = parser.parse_args()
    receipt_path = args.renders / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    metric = MetricPanel(ppd=args.ppd)
    asset_rows = []
    for record in receipt["records"]:
        per_view = asset_metric_rows(args.renders, record, metric)
        asset_rows.append({"asset": record["asset"], "source_faces": record["source_faces"],
                           "final_faces": record["face_budget"],
                           "per_view": per_view,
                           "asset_mean": summarize_asset(per_view)})
        print(f"scored {record['asset']}: {len(per_view['path'])} paired views", flush=True)

    paired = {}
    for name in METRICS:
        differences = []
        for row in asset_rows:
            path_value = row["asset_mean"]["path"][name]
            qem_value = row["asset_mean"]["qem"][name]
            if path_value is not None and qem_value is not None:
                differences.append(path_value - qem_value)
        paired[name] = {"path_minus_qem_mean": float(np.mean(differences)),
                        "asset_bootstrap_95pct_ci": bootstrap(differences),
                        "assets": len(differences),
                        "positive_favors": "path" if name in HIGHER_IS_BETTER else "qem"}
    result = {"scope": "four-asset development screen; matched faces; shared-default-material Filament renders",
              "render_receipt_sha256": sha256(receipt_path),
              "scorer_script_sha256": sha256(Path(__file__).resolve()),
              "metrics": metric.settings,
              "aggregation": "PSNR from mean per-view MSE; other views averaged within asset; paired bootstrap over assets only",
              "views_per_asset": receipt["views_per_asset"],
              "resolution": receipt["image_size"],
              "asset_rows": asset_rows,
              "paired_path_minus_qem": paired}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
