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

"""M4 allocation comparison for cuts that were exported offline.

`run.py` builds a DAG in every `mm_bench` invocation, which is practical for assets up to a few
hundred thousand triangles. For a 2M triangle scan it is not: one DAG build takes minutes, and
a sweep would take hours. `mmgeo --target-ratio-cut ... --screen-error-cut ...` builds the DAG
once and exports the selected meshes. This script renders those meshes directly (no DAG build
per camera), then trains the same reconstruction network on each allocation.

Usage:
    python tools/m4alloc/run_preselected.py \
        --uniform-mesh out/m4-dragon/lr-dag2/selected_ratio_0.252.ply \
        --distance-mesh out/m4-dragon/lr-dag2/selected_px_4.ply \
        --target-mesh out/m3/hr_mesh.ply \
        --out out/m4-dragon/run252 --views 8 --view-span 40 \
        --eye 2.220,-6.737,220.771 --target 2.220,-6.737,9.837
"""

import argparse
import glob
import json
import math
import os
import shutil
import statistics
import struct
import subprocess
import sys

BENCH = os.path.join("out", "cmake-release", "samples", "mm_bench.exe")
TRAIN = os.path.join("tools", "mmtrain", "train.py")


def read_ply_triangles(path):
    with open(path, "rb") as handle:
        header = b""
        while b"end_header" not in header:
            line = handle.readline()
            if not line:
                raise SystemExit(f"{path}: not a PLY file")
            header += line
    for line in header.decode("ascii", "ignore").splitlines():
        if line.startswith("element face"):
            return int(line.split()[2])
    raise SystemExit(f"{path}: no face element")


def vec(text):
    return [float(value) for value in text.split(",")]


def fmt(values):
    return ",".join(f"{value:.6f}" for value in values)


def orbit_eye(base_eye, target, view, views, span_degrees):
    if span_degrees >= 360.0:
        angle = 2.0 * math.pi * float(view) / float(max(views, 1))
    else:
        fraction = float(view) / float(max(views - 1, 1))
        angle = math.radians(-0.5 * span_degrees + span_degrees * fraction)
    offset = [base_eye[i] - target[i] for i in range(3)]
    c, s = math.cos(angle), math.sin(angle)
    return [target[0] + offset[0] * c - offset[2] * s,
            target[1] + offset[1],
            target[2] + offset[0] * s + offset[2] * c]


def render(bench, mesh, out_png, eye, target, size):
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    command = [bench, "--headless", "--window-size", size, "--fixed-timestep=0.0166667",
               "--out", out_png, "--eye", fmt(eye), "--target", fmt(target),
               "--warmup", "1", "--measure", "1", "--no-shadows", mesh]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:])
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"mm_bench failed: {' '.join(command)}")


def render_set(bench, mesh, out_dir, eyes, target, size, prefix):
    os.makedirs(out_dir, exist_ok=True)
    for index, eye in enumerate(eyes):
        path = os.path.join(out_dir, f"{prefix}_v{index:02d}.png")
        render(bench, mesh, path, eye, target, size)
    return [os.path.join(out_dir, f"{prefix}_v{index:02d}.png") for index in range(len(eyes))]


def train(data_dir, model, iterations, seed, out_prefix):
    command = [sys.executable, TRAIN, "--data", data_dir, "--model", model,
               "--scale", "1", "--iterations", str(iterations), "--seed", str(seed),
               "--no-error-map", "--val-views", "2", "--out", out_prefix]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:])
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"training failed: {' '.join(command)}")
    path = out_prefix if model == "bicubic" else out_prefix + ".json"
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uniform-mesh", required=True)
    parser.add_argument("--distance-mesh", required=True)
    parser.add_argument("--target-mesh", default="",
            help="full detail mesh; defaults to --uniform-mesh")
    parser.add_argument("--out", required=True)
    parser.add_argument("--eye", default="0,-0.02,3.25")
    parser.add_argument("--target", default="0,-0.016,0")
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--view-span", type=float, default=360.0)
    parser.add_argument("--size", default="640x360")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bench", default=BENCH)
    args = parser.parse_args()

    bench = os.path.abspath(args.bench)
    target_mesh = args.target_mesh or args.uniform_mesh
    base_triangles = read_ply_triangles(target_mesh)
    uniform_triangles = read_ply_triangles(args.uniform_mesh)
    distance_triangles = read_ply_triangles(args.distance_mesh)
    print(f"target {base_triangles}, uniform {uniform_triangles} "
          f"({100.0 * uniform_triangles / base_triangles:.2f}%), distance "
          f"{distance_triangles} ({100.0 * distance_triangles / base_triangles:.2f}%)")

    eyes = [orbit_eye(vec(args.eye), vec(args.target), view, args.views, args.view_span)
            for view in range(args.views)]
    os.makedirs(args.out, exist_ok=True)

    target_dir = os.path.join(args.out, "target")
    uniform_dir = os.path.join(args.out, "uniform")
    distance_dir = os.path.join(args.out, "distance")
    render_set(bench, target_mesh, target_dir, eyes, vec(args.target), args.size, "hr")
    render_set(bench, args.uniform_mesh, uniform_dir, eyes, vec(args.target), args.size, "lr")
    render_set(bench, args.distance_mesh, distance_dir, eyes, vec(args.target), args.size, "lr")
    for directory in (uniform_dir, distance_dir):
        for path in glob.glob(os.path.join(target_dir, "hr_v*.png")):
            shutil.copy2(path, os.path.join(directory, os.path.basename(path)))

    summary = {
        "baseTriangles": base_triangles,
        "uniform": {"triangles": uniform_triangles},
        "distance": {"triangles": distance_triangles},
    }
    for strategy, data_dir in (("uniform", uniform_dir), ("distance", distance_dir)):
        print(f"training tiny on {strategy}")
        tiny = train(data_dir, "tiny", args.iterations, args.seed,
                os.path.join(args.out, f"{strategy}_tiny"))
        bicubic = train(data_dir, "bicubic", args.iterations, args.seed,
                os.path.join(args.out, f"{strategy}_bicubic"))
        summary[strategy]["tiny"] = tiny["metrics"]
        summary[strategy]["bicubic"] = bicubic["metrics"]
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)

    print("\n=== summary ===")
    print(f"{'strategy':>9} {'tris':>9} {'ratio':>8} {'bicubic':>9} {'tiny':>9} {'delta':>8}")
    for strategy in ("uniform", "distance"):
        entry = summary[strategy]
        bicubic = entry["bicubic"]["psnr"]
        tiny = entry["tiny"]["psnr"]
        print(f"{strategy:>9} {entry['triangles']:>9} "
              f"{100.0 * entry['triangles'] / base_triangles:>7.2f}% "
              f"{bicubic:>9.2f} {tiny:>9.2f} {tiny - bicubic:>+8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
