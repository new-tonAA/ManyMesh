"""Benchmark exact RGB Tiny cropping on native low-resolution raster captures."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import time

import numpy as np
import torch

from local_reconstruction import infer, local_prediction, uniform_prediction
from train import Tiny, TinyUpsample, load_rgb, psnr, resize


def timed(function, repeats):
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = function()
        times.append(1000 * (time.perf_counter() - start))
    return result, times


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--model", choices=("tiny", "tiny_up"), default="tiny")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.threads < 1 or args.repeats < 1:
        parser.error("positive thread and repeat counts required")
    torch.set_num_threads(args.threads)
    weights = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    channels = weights["body.0.weight"].shape[0]
    model = Tiny(3, channels) if args.model == "tiny" else TinyUpsample(3, 2, channels)
    model.load_state_dict(weights)
    model.eval()
    rows = []
    previous = None
    for high_path in sorted(args.capture.glob("hr_v??.png")):
        low_path = high_path.with_name(high_path.name.replace("hr_", "lr_"))
        if not low_path.exists():
            low_path = low_path.with_stem(low_path.stem + "_j00")
        high, low = load_rgb(high_path), load_rgb(low_path)
        height, width = high.shape[:2]
        if (height, width) != tuple(2 * n for n in low.shape[:2]):
            raise ValueError(f"Expected a native 2x raster pair: {low_path}")

        base, resize_ms = timed(lambda: resize(low, (width, height)), args.repeats)
        internal_upsample = args.model == "tiny_up"
        observation = low if internal_upsample else base
        predictor = model.body if internal_upsample else model

        def restore(prediction):
            if not internal_upsample:
                return prediction
            image = torch.from_numpy(low).permute(2, 0, 1).unsqueeze(0)
            large = torch.nn.functional.interpolate(
                image, scale_factor=2, mode="bicubic", align_corners=False)
            residual = torch.from_numpy(prediction).permute(2, 0, 1).unsqueeze(0)
            return (large + model.shuffle(residual))[0].permute(1, 2, 0).numpy()

        color = observation[0, 0].copy()
        signature = tuple(color), observation.shape
        background_ms = 0.0
        if signature != previous:
            background, times = timed(
                lambda: uniform_prediction(predictor, observation.shape, color), 1)
            background_ms = times[0]
            previous = signature
        flat_input = np.broadcast_to(color, observation.shape)

        # Warm the kernels for both input shapes. The timed calls include both the
        # input comparison and output assembly for the cropped path.
        full = infer(model, observation)

        def local():
            prediction, area = local_prediction(predictor, observation, flat_input, background)
            return restore(prediction), area

        local()
        (crop, area), local_ms = timed(local, args.repeats)
        _, full_ms = timed(lambda: infer(model, observation), args.repeats)
        maximum = float(np.max(np.abs(full - crop)))
        if maximum > 1e-5:
            raise ValueError(f"Cropped inference changed {low_path} by {maximum}")
        full_pixels = observation.shape[0] * observation.shape[1]
        rows.append({"low": str(low_path), "high": str(high_path),
                     "fullPixels": full_pixels, "cropPixels": int(area),
                     "maxDifference": maximum, "resizeMs": resize_ms,
                     "fullMs": full_ms, "localMs": local_ms, "backgroundSetupMs": background_ms,
                     "bicubicPsnr": psnr(high, base), "tinyPsnr": psnr(high, np.clip(full, 0, 1))})
        print(f"{low_path.name}: {area/full_pixels:.1%} crop; "
              f"{median(full_ms):.2f} -> {median(local_ms):.2f} ms", flush=True)
    if not rows:
        parser.error("capture requires hr_vNN.png raster pairs")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {"checkpointSha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              "model": args.model, "threads": args.threads, "rows": rows}
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
