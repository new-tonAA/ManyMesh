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

"""End-to-end timing and quality for the geometry-budget pipeline.

Compares three per-frame pipelines at 640x360:

  full     render the full-detail mesh
  low      render the low-budget cut
  low+cnn  render the low-budget cut, run the reconstruction network

Render time is the median GPU frame time reported by mm_bench over repeated runs. Inference
time is the median CPU time of the tiny network over the held-out views. The total is a serial
sum, which is the conservative number: a real pipeline can overlap the next render with the
current inference, and on a device the network would likely run on the GPU/NPU.

Usage:
    python tools/m4alloc/e2e.py \
        --model out/m4-dragon/cross/cross16_tiny.pt \
        --budgets 499277:out/m4-dragon/cross16-val/budget_499277:out/m4-dragon/lr-dag2/selected.ply \
        --full-mesh out/m3/hr_mesh.ply --eye 213.1540,-6.7370,9.8370 \
        --target 2.220,-6.737,9.837 --out out/m4-dragon/e2e
"""

import argparse
import importlib.util
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time

import numpy as np
import torch
from PIL import Image
from skimage.metrics import structural_similarity

BENCH = os.path.join("out", "cmake-release", "samples", "mm_bench.exe")
TRAIN_SCRIPT = os.path.join("tools", "mmtrain", "train.py")
GPU_RE = re.compile(r"GPU\s+median\s+([0-9.]+)\s*ms")
CPU_RE = re.compile(r"CPU\s+median\s+([0-9.]+)\s*ms")


def load_train_module():
    spec = importlib.util.spec_from_file_location("mmtrain", TRAIN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rgb(path):
    image = Image.open(path)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.asarray(image).astype(np.float32) / 255.0


def psnr(reference, candidate):
    mse = float(np.mean((reference - candidate) ** 2))
    return float("inf") if mse == 0.0 else 10.0 * math.log10(1.0 / mse)


def render_samples(bench, mesh, eye, target, size, shadows, out_dir, repeats):
    os.makedirs(out_dir, exist_ok=True)
    gpu, cpu = [], []
    for index in range(repeats):
        path = os.path.join(out_dir, f"timing_{index}.png")
        command = [bench, "--headless", "--window-size", size,
                   "--fixed-timestep=0.0166667", "--out", path,
                   "--eye", eye, "--target", target,
                   "--warmup", "10", "--measure", "60",
                   "--shadows" if shadows else "--no-shadows", mesh]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout[-3000:])
            sys.stderr.write(result.stderr[-3000:])
            raise SystemExit(f"mm_bench failed: {' '.join(command)}")
        gpu_match = GPU_RE.search(result.stdout)
        cpu_match = CPU_RE.search(result.stdout)
        if gpu_match:
            gpu.append(float(gpu_match.group(1)))
        if cpu_match:
            cpu.append(float(cpu_match.group(1)))
    return (statistics.median(gpu) if gpu else float("nan"),
            statistics.median(cpu) if cpu else float("nan"))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="tiny checkpoint")
    parser.add_argument("--budgets", required=True, action="append",
            help="triangles:val_dir:mesh; repeat for several budgets")
    parser.add_argument("--full-mesh", required=True)
    parser.add_argument("--eye", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--size", default="640x360")
    parser.add_argument("--out", default="out/m4-dragon/e2e")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=1,
            help="PyTorch CPU threads; 1 is the conservative single-core number")
    parser.add_argument("--shadows", action="store_true")
    parser.add_argument("--bench", default=BENCH)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    train_module = load_train_module()
    model = train_module.Tiny(3)
    model.load_state_dict(torch.load(args.model, map_location="cpu"))
    model.eval()
    parameters = sum(p.numel() for p in model.parameters())
    os.makedirs(args.out, exist_ok=True)

    bench = os.path.abspath(args.bench)
    full_gpu, full_cpu = render_samples(bench, args.full_mesh, args.eye, args.target,
            args.size, args.shadows, os.path.join(args.out, "full"), args.repeats)
    print(f"full render: GPU {full_gpu:.3f} ms, CPU {full_cpu:.3f} ms")

    rows = []
    for spec in args.budgets:
        parts = spec.split(":")
        if len(parts) != 3:
            raise SystemExit(f"bad --budgets entry '{spec}'; expected triangles:val_dir:mesh")
        triangles, val_dir, mesh = int(parts[0]), parts[1], parts[2]
        low_gpu, low_cpu = render_samples(bench, mesh, args.eye, args.target, args.size,
                args.shadows, os.path.join(args.out, f"low_{triangles}"), args.repeats)

        lr_paths = sorted([path for path in os.listdir(val_dir) if path.startswith("lr_")])
        coarse_psnr, cnn_psnr, coarse_ssim, cnn_ssim = [], [], [], []
        inference_ms = []
        for lr_name in lr_paths:
            hr_name = lr_name.replace("lr_", "hr_", 1)
            lr = load_rgb(os.path.join(val_dir, lr_name))
            hr = load_rgb(os.path.join(val_dir, hr_name))
            tensor = torch.from_numpy(lr.transpose(2, 0, 1))[None]
            with torch.no_grad():
                for _ in range(5):
                    model(tensor)
                timings = []
                for _ in range(30):
                    before = time.perf_counter()
                    output_tensor = model(tensor)[0].clamp(0.0, 1.0)
                    timings.append((time.perf_counter() - before) * 1000.0)
            output = output_tensor.numpy().transpose(1, 2, 0)
            inference_ms.extend(timings)
            coarse_psnr.append(psnr(hr, lr))
            cnn_psnr.append(psnr(hr, output))
            coarse_ssim.append(float(structural_similarity(hr, lr, channel_axis=2,
                    data_range=1.0)))
            cnn_ssim.append(float(structural_similarity(hr, output, channel_axis=2,
                    data_range=1.0)))

        inference = statistics.median(inference_ms)
        total = low_gpu + inference
        rows.append({
            "triangles": triangles,
            "lowGpuMs": low_gpu,
            "lowCpuMs": low_cpu,
            "fullGpuMs": full_gpu,
            "fullCpuMs": full_cpu,
            "inferenceMs": inference,
            "totalMs": total,
            "speedup": full_gpu / total if total > 0 else float("nan"),
            "coarsePsnr": statistics.median(coarse_psnr),
            "cnnPsnr": statistics.median(cnn_psnr),
            "coarseSsim": statistics.median(coarse_ssim),
            "cnnSsim": statistics.median(cnn_ssim),
        })
        print(f"{triangles}: render GPU {low_gpu:.3f} ms, inference {inference:.3f} ms, "
              f"total {total:.3f} ms, speedup {rows[-1]['speedup']:.2f}x, "
              f"PSNR {rows[-1]['coarsePsnr']:.2f} -> {rows[-1]['cnnPsnr']:.2f}")

    summary = {
        "model": args.model,
        "parameters": parameters,
        "float32KiB": parameters * 4 / 1024.0,
        "int8KiB": parameters / 1024.0,
        "size": args.size,
        "threads": args.threads,
        "rows": rows,
    }
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print("\n=== end to end ===")
    print(f"model {parameters} params ({summary['float32KiB']:.1f} KiB fp32, "
          f"{summary['int8KiB']:.1f} KiB int8), {args.threads} CPU thread(s)")
    print(f"{'tris':>9} {'lowGPU':>8} {'infer':>8} {'total':>8} {'speedup':>8} "
          f"{'coarse':>8} {'cnn':>8}")
    for row in rows:
        print(f"{row['triangles']:>9} {row['lowGpuMs']:>8.3f} {row['inferenceMs']:>8.3f} "
              f"{row['totalMs']:>8.3f} {row['speedup']:>7.2f}x {row['coarsePsnr']:>8.2f} "
              f"{row['cnnPsnr']:>8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
