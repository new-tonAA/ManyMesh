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

"""M4 first slice: does *where* the triangles go still matter after reconstruction?

The geometry stage can spend a fixed triangle budget in more than one way:

  uniform   selectLodGraphAtRatio: every part of the model loses the same fraction.
  distance  selectLodGraph: a fixed screen-space error threshold, so near geometry stays
            detailed and far geometry gets coarser.

Both produce the same number of drawn triangles. This script renders the same views from both
allocations, trains the *same* tiny reconstruction network on each (same seed, same iteration
budget), and reports PSNR/SSIM before and after reconstruction. If the ranking changes once the
network is in the loop, then geometry allocation and reconstruction are coupled - the premise
of the joint optimization stage. If it does not, the allocation is a pure geometry decision and
M4 has to look elsewhere.

The script deliberately runs one camera per mm_bench invocation so that the printed
`selectedTriangles` belongs to that view; a multi-view run reports only the last cut.

Usage:
    python tools/m4alloc/run.py --mesh assets/models/monkey/monkey.obj \
        --out out/m4-monkey --ratios 0.35 --views 8 --iterations 2000
"""

import argparse
import glob
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys

BENCH = os.path.join("out", "cmake-release", "samples", "mm_bench.exe")
TRAIN = os.path.join("tools", "mmtrain", "train.py")
CUT_RE = re.compile(r"dag: selectedTriangles=(\d+) ratio=([0-9.]+)")


def vec(text):
    return [float(value) for value in text.split(",")]


def fmt(values):
    return ",".join(f"{value:.6f}" for value in values)


def orbit_eye(base_eye, target, view, views):
    """The same azimuthal orbit mm_bench uses for --views."""
    angle = 2.0 * math.pi * float(view) / float(max(views, 1))
    offset = [base_eye[i] - target[i] for i in range(3)]
    c, s = math.cos(angle), math.sin(angle)
    return [target[0] + offset[0] * c - offset[2] * s,
            target[1] + offset[1],
            target[2] + offset[0] * s + offset[2] * c]


def run_bench(mesh, out_png, eye, target, extra, size):
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    command = [BENCH, "--headless", "--window-size", size, "--fixed-timestep=0.0166667",
               "--out", out_png, "--eye", fmt(eye), "--target", fmt(target),
               "--warmup", "2", "--measure", "4", "--no-shadows"] + extra + [mesh]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:])
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"mm_bench failed ({result.returncode}): {' '.join(command)}")
    match = CUT_RE.search(result.stdout)
    if match is None:
        sys.stderr.write(result.stdout[-4000:])
        raise SystemExit(f"no cut statistics in mm_bench output: {' '.join(command)}")
    return int(match.group(1)), float(match.group(2))


def calibrate_distance(mesh, eye, target, wanted_ratio, size, out_dir):
    """Finds the screen-error threshold whose cut matches the wanted triangle ratio."""
    low, high = 0.01, 100.0
    best = None
    # A screen-error threshold is monotone: larger threshold -> fewer triangles. Sixteen
    # bisections put the ratio well inside the two percent tolerance.
    for _ in range(16):
        middle = math.sqrt(low * high)
        probe = os.path.join(out_dir, "_calibrate.png")
        triangles, ratio = run_bench(mesh, probe, eye, target,
                ["--dag", "--distance-lod", f"--screen-error={middle:.6f}"], size)
        if best is None or abs(ratio - wanted_ratio) < abs(best[1] - wanted_ratio):
            best = (middle, ratio, triangles)
        if ratio > wanted_ratio:
            low = middle
        else:
            high = middle
    return best


def render_set(mesh, out_dir, eyes, target, extra, size):
    counts = []
    for index, eye in enumerate(eyes):
        path = os.path.join(out_dir, f"lr_v{index:02d}.png")
        triangles, ratio = run_bench(mesh, path, eye, target, extra, size)
        counts.append((triangles, ratio))
        print(f"    view {index:02d}: {triangles} triangles ({100.0 * ratio:.2f}%)")
    return counts


def copy_targets(source_dir, destination_dir):
    os.makedirs(destination_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(source_dir, "hr_v*.png"))):
        shutil.copy2(path, os.path.join(destination_dir, os.path.basename(path)))


def train(data_dir, model, iterations, seed, out_prefix):
    command = [sys.executable, TRAIN, "--data", data_dir, "--model", model,
               "--scale", "1", "--iterations", str(iterations), "--seed", str(seed),
               "--no-error-map", "--val-views", "2", "--out", out_prefix]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:])
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"training failed: {' '.join(command)}")
    # The no-network baseline writes its JSON straight to --out, while trained models append
    # their own extensions.
    metrics_path = out_prefix if model == "bicubic" else out_prefix + ".json"
    with open(metrics_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mesh", default=os.path.join("assets", "models", "monkey",
                                                       "monkey.obj"))
    parser.add_argument("--out", default="out/m4-monkey")
    parser.add_argument("--eye", default="0,-0.02,3.25")
    parser.add_argument("--target", default="0,-0.016,0")
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--size", default="640x360")
    parser.add_argument("--ratios", default="0.35",
            help="comma separated retained triangle ratios to compare")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--bench", default=BENCH, help="mm_bench executable")
    args = parser.parse_args()

    global BENCH
    # Windows CreateProcess does not resolve a relative executable path containing forward
    # slashes, so normalise it once.
    BENCH = os.path.abspath(args.bench)

    ratios = [float(value) for value in args.ratios.split(",")]
    base_eye = vec(args.eye)
    target = vec(args.target)
    eyes = [orbit_eye(base_eye, target, view, args.views) for view in range(args.views)]
    os.makedirs(args.out, exist_ok=True)

    summary_path = os.path.join(args.out, "summary.json")
    summary = {}
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary = json.load(handle)

    # The full-detail target is shared by every strategy. Render it once per view.
    target_dir = os.path.join(args.out, "hr")
    if not args.skip_render:
        print("full detail target")
        os.makedirs(target_dir, exist_ok=True)
        for index, eye in enumerate(eyes):
            path = os.path.join(target_dir, f"hr_v{index:02d}.png")
            triangles, ratio = run_bench(args.mesh, path, eye, target,
                    ["--dag", "--savings=0", "--ignore-ceiling"], args.size)
            print(f"    view {index:02d}: {triangles} triangles ({100.0 * ratio:.2f}%)")

    for wanted in ratios:
        key = f"{wanted:.2f}"
        entry = summary.setdefault(key, {})
        uniform_dir = os.path.join(args.out, f"r{key}", "uniform")
        distance_dir = os.path.join(args.out, f"r{key}", "distance")

        if not args.skip_render:
            print(f"\nratio {wanted:.2f}: uniform allocation")
            os.makedirs(uniform_dir, exist_ok=True)
            uniform_counts = render_set(args.mesh, uniform_dir, eyes, target,
                    ["--dag", f"--savings={1.0 - wanted:.6f}", "--ignore-ceiling"], args.size)
            copy_targets(target_dir, uniform_dir)
            uniform_ratio = statistics.median(ratio for _, ratio in uniform_counts)

            print(f"ratio {wanted:.2f}: distance allocation (calibrated to "
                  f"{100.0 * uniform_ratio:.2f}%)")
            os.makedirs(distance_dir, exist_ok=True)
            threshold, probe_ratio, probe_triangles = calibrate_distance(
                    args.mesh, eyes[0], target, uniform_ratio, args.size, distance_dir)
            print(f"    screen error {threshold:.4f}px -> {probe_triangles} triangles "
                  f"({100.0 * probe_ratio:.2f}%) on the calibration view")
            distance_counts = render_set(args.mesh, distance_dir, eyes, target,
                    ["--dag", "--distance-lod", f"--screen-error={threshold:.6f}"], args.size)
            copy_targets(target_dir, distance_dir)

            entry["uniform"] = {
                "target": wanted,
                "ratio": uniform_ratio,
                "triangles": [count for count, _ in uniform_counts],
            }
            entry["distance"] = {
                "target": wanted,
                "ratio": statistics.median(ratio for _, ratio in distance_counts),
                "triangles": [count for count, _ in distance_counts],
                "screenErrorPx": threshold,
            }
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)

        if args.skip_train:
            continue

        for strategy, data_dir in (("uniform", uniform_dir), ("distance", distance_dir)):
            print(f"ratio {wanted:.2f}: training tiny on {strategy}")
            prefix = os.path.join(args.out, f"r{key}", f"{strategy}_tiny")
            metrics = train(data_dir, "tiny", args.iterations, args.seed, prefix)
            bicubic_prefix = os.path.join(args.out, f"r{key}", f"{strategy}_bicubic")
            bicubic = train(data_dir, "bicubic", args.iterations, args.seed, bicubic_prefix)
            entry.setdefault(strategy, {})
            entry[strategy]["tiny"] = metrics["metrics"]
            entry[strategy]["bicubic"] = bicubic["metrics"]
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)

    print("\n=== summary ===")
    print(f"{'ratio':>6} {'strategy':>9} {'tris':>9} {'bicubic':>9} {'tiny':>9} {'delta':>8}")
    for key in sorted(summary):
        for strategy in ("uniform", "distance"):
            entry = summary[key].get(strategy, {})
            if not entry or "tiny" not in entry:
                continue
            triangles = int(statistics.median(entry["triangles"]))
            bicubic = entry["bicubic"]["psnr"]
            tiny = entry["tiny"]["psnr"]
            print(f"{key:>6} {strategy:>9} {triangles:>9} {bicubic:>9.2f} "
                  f"{tiny:>9.2f} {tiny - bicubic:>+8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
