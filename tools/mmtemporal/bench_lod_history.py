"""Replay paired native raster captures to measure history at mesh cut transitions."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from temporal import (depth_path, load, load_depth, psnr, read_camera_list,
                      reproject_with_depth, upscale)


def changed_depth(a, b, tolerance):
    covered_a, covered_b = a > 0, b > 0
    changed = (covered_a ^ covered_b) | (
        covered_a & covered_b & (np.abs(a - b) > tolerance * np.maximum(a, b)))
    padded = np.pad(changed, 1)
    height, width = a.shape
    return np.logical_or.reduce([padded[y:y+height, x:x+width]
                                 for y in range(3) for x in range(3)])


def replay(captures, cameras, switch_every, depth_tolerance, change_tolerance):
    policies = ("single", "keep", "reset", "depth_mask")
    history = {}
    residuals = {}
    previous_depth = previous_camera = previous_cut = None
    rows = []
    for i, camera in enumerate(cameras["cameras"]):
        view, subframe = divmod(i, cameras["jitter"])
        if subframe == 0:
            history.clear()
            residuals.clear()
            previous_depth = previous_camera = previous_cut = None
        stem = f"v{view:02d}_j{subframe:02d}"
        first, second = [p / f"hr_{stem}.png" for p in captures]
        reference_bytes = first.read_bytes()
        if reference_bytes != second.read_bytes():
            raise ValueError(f"Reference mismatch at {stem}")
        reference = load(first)
        cut = (subframe // switch_every) % 2
        switched = previous_cut is not None and previous_cut != cut
        source = captures[cut]
        current = load(source / f"lr_{stem}.png")
        depth = load_depth(depth_path(source / "depth", i, cameras["jitter"]))
        if ((reference.shape[0], reference.shape[1]) != (current.shape[0] * 4, current.shape[1] * 4)
                or current.shape[:2] != depth.shape
                or current.shape[:2] != (camera["height"], camera["width"])):
            raise ValueError(f"Native 4x scale, depth, or camera mismatch at {stem}")
        mask = None
        if switched:
            old_depth = load_depth(depth_path(captures[previous_cut] / "depth", i, cameras["jitter"]))
            mask = changed_depth(depth, old_depth, change_tolerance)
        row = {"view": view, "subframe": subframe, "cut": cut, "switched": switched,
               "depthMaskFraction": float(mask.mean()) if mask is not None else None,
               "referenceSha256": hashlib.sha256(reference_bytes).hexdigest()}
        for name in policies:
            accumulated = current
            if name != "single" and name in history and (name != "reset" or not switched):
                warped, accept, _ = reproject_with_depth(history[name], previous_depth, depth,
                    previous_camera, camera, depth_tolerance, "taps")
                if name == "depth_mask" and mask is not None:
                    accept &= ~mask
                accumulated = np.where(accept[..., None], 0.5 * (current + warped), current)
            output = upscale(accumulated, (reference.shape[1], reference.shape[0]))
            residual = output - reference
            row[name] = {"psnr": psnr(reference, output),
                         "residualChangeMse": float(np.mean((residual - residuals[name]) ** 2))
                         if name in residuals else None}
            residuals[name] = residual
            history[name] = accumulated
        previous_depth, previous_camera, previous_cut = depth, camera, cut
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path, nargs=2)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--switch-every", type=int, default=2)
    parser.add_argument("--depth-tolerance", type=float, default=0.05)
    parser.add_argument("--change-tolerance", type=float, default=0.002)
    args = parser.parse_args()
    camera_paths = [p / "cameras.txt" for p in args.captures]
    camera_bytes = camera_paths[0].read_bytes()
    if camera_bytes != camera_paths[1].read_bytes():
        parser.error("the two camera lists must match exactly")
    cameras = read_camera_list(camera_paths[0])
    if not 1 <= args.switch_every < cameras["jitter"]:
        parser.error("switch interval must fall within each camera sequence")
    if not 0 < args.change_tolerance <= args.depth_tolerance < 1:
        parser.error("depth tolerances must be positive and below one")
    rows = replay(args.captures, cameras, args.switch_every, args.depth_tolerance,
                  args.change_tolerance)
    result = {"captures": [str(p) for p in args.captures],
              "cameraSha256": hashlib.sha256(camera_bytes).hexdigest(),
              "switchEvery": args.switch_every, "depthTolerance": args.depth_tolerance,
              "changeTolerance": args.change_tolerance, "frames": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} frames, {sum(r['switched'] for r in rows)} cut switches. Wrote {args.out}")


if __name__ == "__main__":
    main()
