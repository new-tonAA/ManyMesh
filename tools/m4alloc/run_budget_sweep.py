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

"""Measures how much geometry budget a reconstructor replaces.

M4's allocation experiments showed that *where* triangles go barely changes the picture. The
useful question is how many triangles are needed at all: at a fixed PSNR, how far to the left
does the curve move when a network is in the loop? This script renders pre-selected meshes at
several budgets against the same full-detail target, trains the same tiny network on each, and
prints a PSNR-vs-triangles table. The horizontal gap between the two curves is the budget the
reconstructor buys.

Reusing an existing target set (for example the 16-view dragon targets in `out/m3`) avoids
re-rendering a multi-million triangle mesh for every sweep:

    python tools/m4alloc/run_budget_sweep.py \
        --meshes cut7.ply,cut10.ply,cut14.ply,cut19.ply \
        --target-mesh out/m3/hr_mesh.ply --target-dir out/m3 \
        --camera-list out/m3/views.txt --target 2.220,-6.737,9.837 \
        --out out/m4-dragon/budget --views 8 --shadows
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

from run_preselected import orbit_eye, read_ply_triangles, train, vec


def parse_camera_list(path, views):
    eyes = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                eye = [float(value) for value in parts[1].split(",")]
                eyes.append(eye)
    if len(eyes) < views:
        raise SystemExit(f"{path}: {len(eyes)} cameras, need {views}")
    return eyes[:views]


def render(bench, mesh, out_png, eye, target, size, shadows):
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    command = [bench, "--headless", "--window-size", size, "--fixed-timestep=0.0166667",
               "--out", out_png, "--eye", ",".join(f"{v:.6f}" for v in eye),
               "--target", ",".join(f"{v:.6f}" for v in target),
               "--warmup", "1", "--measure", "1",
               "--shadows" if shadows else "--no-shadows", mesh]
    print(f"  render {os.path.basename(out_png)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:])
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(f"mm_bench failed: {' '.join(command)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--meshes", required=True,
            help="comma separated pre-selected meshes, one per budget")
    parser.add_argument("--target-mesh", default="", help="full detail target mesh")
    parser.add_argument("--target-dir", default="",
            help="directory with existing hr_vNN.png targets; skips target rendering")
    parser.add_argument("--camera-list", default="",
            help="file with '<index> x,y,z' lines, used instead of the orbit")
    parser.add_argument("--out", required=True)
    parser.add_argument("--eye", default="0,-0.02,3.25")
    parser.add_argument("--target", default="0,-0.016,0")
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--view-span", type=float, default=360.0)
    parser.add_argument("--size", default="640x360")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--shadows", action="store_true",
            help="render with sun shadows, as the out/m3 targets were")
    parser.add_argument("--render-only", action="store_true",
            help="render the pairs and stop; useful before assembling a cross-budget set")
    parser.add_argument("--bench", default=os.path.join("out", "cmake-release", "samples",
                                                        "mm_bench.exe"))
    args = parser.parse_args()

    meshes = [value for value in args.meshes.split(",") if value]
    if not args.target_dir and not args.target_mesh:
        raise SystemExit("provide --target-mesh or --target-dir")
    base_triangles = read_ply_triangles(args.target_mesh or
            os.path.join(args.target_dir, "hr_mesh.ply"))
    if args.camera_list:
        eyes = parse_camera_list(args.camera_list, args.views)
    else:
        eyes = [orbit_eye(vec(args.eye), vec(args.target), view, args.views, args.view_span)
                for view in range(args.views)]
    target_view = vec(args.target)
    bench = os.path.abspath(args.bench)
    os.makedirs(args.out, exist_ok=True)

    target_dir = os.path.join(args.out, "target")
    os.makedirs(target_dir, exist_ok=True)
    if args.target_dir:
        for index in range(args.views):
            source = os.path.join(args.target_dir, f"hr_v{index:02d}.png")
            if not os.path.exists(source):
                raise SystemExit(f"missing {source}")
            shutil.copy2(source, os.path.join(target_dir, f"hr_v{index:02d}.png"))
    else:
        for index, eye in enumerate(eyes):
            render(bench, args.target_mesh, os.path.join(target_dir, f"hr_v{index:02d}.png"),
                    eye, target_view, args.size, args.shadows)

    summary_path = os.path.join(args.out, "summary.json")
    summary = []
    for mesh in meshes:
        triangles = read_ply_triangles(mesh)
        print(f"\n=== {mesh}: {triangles} triangles "
              f"({100.0 * triangles / base_triangles:.2f}% of target) ===")
        budget_dir = os.path.join(args.out, f"budget_{triangles}")
        for index, eye in enumerate(eyes):
            render(bench, mesh, os.path.join(budget_dir, f"lr_v{index:02d}.png"),
                    eye, target_view, args.size, args.shadows)
        for path in glob.glob(os.path.join(target_dir, "hr_v*.png")):
            shutil.copy2(path, os.path.join(budget_dir, os.path.basename(path)))
        entry = {
            "mesh": mesh,
            "triangles": triangles,
            "ratio": triangles / base_triangles,
        }
        if not args.render_only:
            tiny = train(budget_dir, "tiny", args.iterations, args.seed,
                    os.path.join(budget_dir, "tiny"))
            bicubic = train(budget_dir, "bicubic", args.iterations, args.seed,
                    os.path.join(budget_dir, "bicubic"))
            entry["tiny"] = tiny["metrics"]
            entry["bicubic"] = bicubic["metrics"]
        summary.append(entry)
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump({"baseTriangles": base_triangles, "entries": summary}, handle, indent=2)

    print("\n=== budget sweep ===")
    if args.render_only:
        print(f"{'tris':>9} {'ratio':>8}")
        for entry in sorted(summary, key=lambda item: item["triangles"]):
            print(f"{entry['triangles']:>9} {100.0 * entry['ratio']:>7.2f}%")
        return 0
    print(f"{'tris':>9} {'ratio':>8} {'bicubic':>9} {'tiny':>9} {'delta':>8}")
    for entry in sorted(summary, key=lambda item: item["triangles"]):
        bicubic = entry["bicubic"]["psnr"]
        tiny = entry["tiny"]["psnr"]
        print(f"{entry['triangles']:>9} {100.0 * entry['ratio']:>7.2f}% "
              f"{bicubic:>9.2f} {tiny:>9.2f} {tiny - bicubic:>+8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
