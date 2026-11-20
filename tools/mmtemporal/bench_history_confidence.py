"""Measure causal history gates and hindsight tile-selection bounds."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from temporal import (depth_path, load, load_depth, project_history, read_camera_list,
                      sample_valid_history, upscale)

TILE_SIDES = (1, 4, 8, 16)


def tile_sums(values, side):
    rows = np.arange(0, values.shape[0], side)
    cols = np.arange(0, values.shape[1], side)
    return np.add.reduceat(np.add.reduceat(values, rows, axis=0), cols, axis=1)


def replay(root, color_threshold):
    cameras = read_camera_list(root / "cameras.txt")
    count = cameras["jitter"]
    histories = {}
    past_residuals = {}
    rows = []
    policies = ("current", "fixed", "support", "color", "support_color")
    for index, camera in enumerate(cameras["cameras"]):
        view, frame = divmod(index, count)
        stem = f"v{view:02d}_j{frame:02d}" if count > 1 else f"v{view:02d}"
        current = load(root / f"lr_{stem}.png")
        target = load(root / f"hr_{stem}.png")
        depth = load_depth(depth_path(root / "depth", index, count))
        height, width = depth.shape
        scale = target.shape[1] // width
        if (current.shape[:2] != (height, width)
                or (height, width) != (camera["height"], camera["width"])
                or scale < 2 or target.shape[:2] != (height * scale, width * scale)):
            raise ValueError(f"Expected matching color/depth and integer-scale native pair: {stem}")
        if frame == 0:
            histories.clear()
            past_residuals.clear()
        else:
            start = time.perf_counter()
            x, y, z = project_history(depth, previous_camera, camera)
            valid = ((depth > 0) & (z > 1e-4) & (x >= 0) & (y >= 0)
                     & (x < width - 1) & (y < height - 1))
            projection_ms = 1000 * (time.perf_counter() - start)
        row = {"view": view, "frame": frame}
        pixel_errors = {}
        for name in policies:
            start = time.perf_counter()
            accumulated = current
            fraction = 0.0
            if name in histories:
                warped, support = sample_valid_history(
                    histories[name], previous_depth, x, y, z, 0.05)
                gain = 0.5 * (valid & (support >= 0.5))
                if name in ("support", "support_color"):
                    gain *= np.clip(2.0 * support - 1.0, 0, 1)
                if name in ("color", "support_color"):
                    gain *= np.max(np.abs(warped - current), axis=2) <= color_threshold
                gain = gain[..., None]
                accumulated = (1.0 - gain) * current + gain * warped
            working_ms = 1000 * (time.perf_counter() - start)
            if name in histories:
                working_ms += projection_ms
                fraction = float(np.count_nonzero(gain) / gain.size)
            if name != "current":
                histories[name] = accumulated
            start = time.perf_counter()
            result = upscale(accumulated, (target.shape[1], target.shape[0]))
            working_ms += 1000 * (time.perf_counter() - start)
            residual = result - target
            mse = float(np.mean(residual ** 2))
            row[name] = {"mse": mse, "wallMs": working_ms, "historyFraction": fraction,
                         "residualChangeMse": float(np.mean((residual - past_residuals[name]) ** 2))
                         if name in past_residuals else None}
            past_residuals[name] = residual
            if name in ("current", "fixed"):
                pixel_errors[name] = np.sum(residual ** 2, axis=2)

        # The oracle can select only between the finished current and fixed outputs.
        # Its decisions are independent per tile and never feed back into either history.
        row["tileOracle"] = {}
        for side in TILE_SIDES:
            single = tile_sums(pixel_errors["current"], side * scale)
            fixed = tile_sums(pixel_errors["fixed"], side * scale)
            row["tileOracle"][str(side)] = {
                "mse": float(np.minimum(single, fixed).sum() / target.size),
                "historyTileFraction": float((fixed < single).mean()),
            }
        rows.append(row)
        previous_camera, previous_depth = camera, depth
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--color-threshold", type=int, default=12,
                        help="maximum RGB-channel difference in 8-bit code values")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.color_threshold <= 255:
        parser.error("--color-threshold must be in [1, 255]")
    frames = replay(args.capture, args.color_threshold / 255.0)
    result = {"capture": str(args.capture), "colorThreshold": args.color_threshold,
              "depthTolerance": 0.05, "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(frames)} frames. Wrote {args.out}")


if __name__ == "__main__":
    main()
