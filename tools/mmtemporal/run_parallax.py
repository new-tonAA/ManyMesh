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

"""Builds a translation sequence and measures temporal reprojection with real occlusion.

The existing pan sequence has no parallax, so history rejects are unnecessary and the
color-rejection experiment could not say anything about disocclusion. This script renders a
lateral camera translation instead, asks mmdepth for the exact depth of every coarse frame, and
drives temporal.py with it. It then exports (current, reprojected history, target) triplets and
trains the same tiny network with and without history, so the learned result is comparable to
the pan experiment.

Usage:
    python tools/mmtemporal/run_parallax.py --lr-mesh out/parallax/lr_mesh.ply \
        --hr-mesh assets/models/monkey/monkey.obj --out out/parallax
"""

import argparse
import json
import os
import subprocess
import sys

BENCH = os.path.join("out", "cmake-release", "samples", "mm_bench.exe")
MMDEPTH = os.path.join("out", "cmake-release", "tools", "mmdepth", "mmdepth.exe")
TEMPORAL = os.path.join("tools", "mmtemporal", "temporal.py")
TRAIN = os.path.join("tools", "mmtrain", "train.py")


def run(command, label):
    print(f"--- {label} ---")
    print(" ".join(command))
    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed ({result.returncode})")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lr-mesh", required=True, help="coarse mesh that is actually rendered")
    parser.add_argument("--hr-mesh", required=True, help="full detail mesh used as target")
    parser.add_argument("--out", default="out/parallax")
    parser.add_argument("--views", type=int, default=4)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--translate", type=float, default=0.20,
            help="total lateral translation per sequence, in world units")
    parser.add_argument("--eye", default="0,-0.016,3.25")
    parser.add_argument("--target", default="0,-0.016,0")
    parser.add_argument("--lr-size", default="320x180")
    parser.add_argument("--hr-size", default="640x360")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--bench", default=BENCH, help="mm_bench executable")
    parser.add_argument("--mmdepth", default=MMDEPTH, help="mmdepth executable")
    args = parser.parse_args()

    # Windows CreateProcess does not resolve a relative executable path containing forward
    # slashes, so normalise the tool paths once.
    args.bench = os.path.abspath(args.bench)
    args.mmdepth = os.path.abspath(args.mmdepth)
    os.makedirs(args.out, exist_ok=True)
    cameras = os.path.join(args.out, "cameras.txt")
    depth_dir = os.path.join(args.out, "depth")
    os.makedirs(depth_dir, exist_ok=True)

    common = ["--views", str(args.views), "--frames", str(args.frames),
              "--translate", str(args.translate), "--eye", args.eye, "--target", args.target,
              "--warmup", "2", "--measure", "4", "--no-shadows"]
    run([args.bench, "--headless", "--window-size", args.lr_size,
         "--fixed-timestep=0.0166667", "--out", os.path.join(args.out, "lr.png"),
         "--camera-out", cameras] + common + [args.lr_mesh], "coarse sequence")
    run([args.bench, "--headless", "--window-size", args.hr_size,
         "--fixed-timestep=0.0166667", "--out", os.path.join(args.out, "hr.png")]
        + common + [args.hr_mesh], "full detail targets")
    run([args.mmdepth, args.lr_mesh, "--cameras", cameras, "--out", depth_dir, "--quiet"],
            "coarse depth")

    export = os.path.join(args.out, "temporal_train")
    temporal = [sys.executable, TEMPORAL, "--data", args.out, "--cameras", cameras,
                "--depth-dir", depth_dir, "--frames", str(args.frames), "--views",
                str(args.views), "--blend", "0.5"]
    run(temporal + ["--export", export], "reprojected history")
    # The negative control only needs the PSNR; exporting here would overwrite the aligned
    # triplets with unaligned ones.
    run(temporal + ["--no-reproject"], "unaligned history (negative control)")

    if args.skip_train:
        return 0

    single = os.path.join(args.out, "tiny_single")
    stacked = os.path.join(args.out, "tiny_stacked")
    run([sys.executable, TRAIN, "--data", export, "--model", "tiny", "--scale", "1",
         "--stack", "1", "--iterations", str(args.iterations), "--seed", "0",
         "--no-error-map", "--val-views", "2", "--out", single], "tiny, current frame only")
    run([sys.executable, TRAIN, "--data", export, "--model", "tiny", "--scale", "1",
         "--stack", "2", "--iterations", str(args.iterations), "--seed", "0",
         "--no-error-map", "--val-views", "2", "--out", stacked],
        "tiny, current + reprojected history")

    summary = {}
    for name, path in (("single", single + ".json"), ("stacked", stacked + ".json")):
        with open(path, "r", encoding="utf-8") as handle:
            summary[name] = json.load(handle)["metrics"]
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print("\n=== learned temporal ===")
    for name in ("single", "stacked"):
        metrics = summary[name]
        print(f"{name:>8}: PSNR {metrics['psnr']:.2f} dB  SSIM {metrics['ssim']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
