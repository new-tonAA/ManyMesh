#!/usr/bin/env python3

# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Image quality metrics for ManyMesh.

Compares rendered frames and reports PSNR, SSIM, and optionally LPIPS. Nine- tenths of the
point of ManyMesh is trading geometry for image quality, so this is the tool that says how
much quality a given reduction actually cost.

Nothing in Filament provides these metrics: its own comparators (tools/diffimg,
libs/imagediff) are absolute difference and tolerance based. PSNR and SSIM come from skimage;
LPIPS is optional because it needs the `lpips` package and a set of weights.

Usage:
    compare.py <reference> <candidate> [<candidate> ...] [options]

Options:
    --labels a,b,c      Names for the candidates, for the table (default: file names)
    --json <path>       Also write the results as JSON
    --diff <path>       Write a difference image for the first candidate
    --gain N            Brightness factor applied to the difference image (default: 4)
    --lpips             Also compute LPIPS (needs `pip install lpips`)

Sweep mode, for a set of views rendered from the same cameras:

    compare.py --sweep --reference-prefix A --candidate-prefix B --views 6

The files are paired as <prefix>_v00.png, <prefix>_v01.png, ... and the output reports the
distribution across views rather than one number. That matters: measured on the Stanford
dragon, the same mesh at the same level of detail varies by 7.7 dB PSNR between views, so a
single view can be off by more than 3 dB from the median.
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


def load(path):
    """Loads an image as float RGB in [0, 1]."""
    image = Image.open(path)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.asarray(image).astype(np.float64) / 255.0


def peak_signal_noise_ratio(reference, candidate):
    mse = float(np.mean((reference - candidate) ** 2))
    if mse == 0.0:
        return float("inf")
    return 10.0 * np.log10(1.0 / mse)


def structural_similarity(reference, candidate):
    from skimage.metrics import structural_similarity as ssim_metric

    # A single global SSIM hides local damage, which is exactly what a simplification artefact
    # looks like: a small region going wrong while the rest is untouched. Average the windowed
    # map instead of using the scalar summary.
    _, full = ssim_metric(reference, candidate, channel_axis=2, data_range=1.0, full=True)
    return float(full.mean())


def lpips_score(reference, candidate, model):
    import torch

    def to_tensor(image):
        tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0).float()
        return tensor * 2.0 - 1.0  # LPIPS expects [-1, 1]

    with torch.no_grad():
        return float(model(to_tensor(reference), to_tensor(candidate)).item())


def difference_image(reference, candidate, gain):
    delta = np.abs(reference - candidate).max(axis=2)
    return np.clip(delta * gain, 0.0, 1.0)


def metric_row(reference, candidate):
    difference = np.abs(reference - candidate)
    return {
        "psnr_db": peak_signal_noise_ratio(reference, candidate),
        "ssim": structural_similarity(reference, candidate),
        "max_abs_diff": float(difference.max()),
        "mean_abs_diff": float(difference.mean()),
        "pixels_over_1_255_percent": float((difference.max(axis=2) > 1.0 / 255.0).mean() * 100.0),
    }


def summarise(rows, label):
    psnr_values = [row["psnr_db"] for row in rows]
    ssim_values = [row["ssim"] for row in rows]
    return {
        "label": label,
        "views": len(rows),
        "psnr_median": float(np.median(psnr_values)),
        "psnr_min": float(np.min(psnr_values)),
        "psnr_max": float(np.max(psnr_values)),
        "ssim_median": float(np.median(ssim_values)),
        "ssim_min": float(np.min(ssim_values)),
        "per_view": rows,
    }


def run_sweep(args):
    header = (f"{'label':<18} {'views':>5} {'PSNR med':>9} {'PSNR min':>9} {'PSNR max':>9} "
              f"{'SSIM med':>9} {'SSIM min':>9}")
    print(header)
    print("-" * len(header))

    report = []
    for label, prefix in zip(args.labels.split(",") if args.labels else [],
                             args.candidate_prefix):
        rows = []
        for view in range(args.views):
            reference = load(f"{args.reference_prefix}_v{view:02d}.png")
            candidate = load(f"{prefix}_v{view:02d}.png")
            rows.append(metric_row(reference, candidate))
        summary = summarise(rows, label or prefix)
        report.append(summary)
        print(f"{summary['label']:<18} {summary['views']:>5} "
              f"{summary['psnr_median']:>9.2f} {summary['psnr_min']:>9.2f} "
              f"{summary['psnr_max']:>9.2f} {summary['ssim_median']:>9.5f} "
              f"{summary['ssim_min']:>9.5f}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"reference_prefix": args.reference_prefix, "results": report},
                      handle, indent=2)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", nargs="?")
    parser.add_argument("candidates", nargs="*")
    parser.add_argument("--sweep", action="store_true",
            help="pair up per-view renders instead of comparing single images")
    parser.add_argument("--reference-prefix", default="")
    parser.add_argument("--candidate-prefix", action="append", default=[])
    parser.add_argument("--views", type=int, default=1)
    parser.add_argument("--labels", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--diff", default="")
    parser.add_argument("--gain", type=float, default=4.0)
    parser.add_argument("--lpips", action="store_true")
    args = parser.parse_args()

    labels = args.labels.split(",") if args.labels else []

    if args.sweep:
        return run_sweep(args)

    if not args.reference or not args.candidates:
        parser.error("give a reference and at least one candidate, or use --sweep")

    reference = load(args.reference)

    model = None
    if args.lpips:
        try:
            import lpips

            model = lpips.LPIPS(net="alex", verbose=False)
            model.eval()
        except ImportError:
            print("LPIPS requested but the `lpips` package is missing. "
                  "Run `pip install lpips`.", file=sys.stderr)
            return 1

    results = []
    for index, path in enumerate(args.candidates):
        candidate = load(path)
        if candidate.shape != reference.shape:
            print(f"{path}: size mismatch "
                  f"{candidate.shape[1]}x{candidate.shape[0]} versus "
                  f"{reference.shape[1]}x{reference.shape[0]}", file=sys.stderr)
            return 1

        difference = np.abs(reference - candidate)
        entry = {
            "candidate": path,
            "label": labels[index] if index < len(labels) else os.path.basename(path),
            "psnr_db": peak_signal_noise_ratio(reference, candidate),
            "ssim": structural_similarity(reference, candidate),
            "max_abs_diff": float(difference.max()),
            "mean_abs_diff": float(difference.mean()),
            "pixels_over_1_255_percent": float((difference.max(axis=2) > 1.0 / 255.0).mean() * 100.0),
        }
        if model is not None:
            entry["lpips"] = lpips_score(reference, candidate, model)
        results.append(entry)

        if index == 0 and args.diff:
            Image.fromarray((difference_image(reference, candidate, args.gain) * 255.0)
                            .astype(np.uint8)).save(args.diff)

    header = f"{'label':<22} {'PSNR (dB)':>10} {'SSIM':>9} {'max diff':>9} {'mean diff':>10} {'>1/255':>8}"
    if model is not None:
        header += f" {'LPIPS':>8}"
    print(f"reference: {args.reference}")
    print(header)
    print("-" * len(header))
    for entry in results:
        row = (f"{entry['label']:<22} "
               f"{entry['psnr_db']:>10.2f} "
               f"{entry['ssim']:>9.5f} "
               f"{entry['max_abs_diff']:>9.4f} "
               f"{entry['mean_abs_diff']:>10.6f} "
               f"{entry['pixels_over_1_255_percent']:>7.3f}%")
        if model is not None:
            row += f" {entry['lpips']:>8.4f}"
        print(row)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"reference": args.reference, "results": results}, handle, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
