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

"""Measures tiny-network inference cost across CPU thread counts and input sizes.

The end-to-end render is only a few milliseconds once the geometry budget is low. The network
is the expensive half: at 640x360 the 32-channel 3x3 stack does billions of multiply-adds per
frame. This script isolates that cost so the deployment question is concrete.

Usage:
    python tools/m4alloc/bench_infer.py --model out/.../tiny.pt \
        --image out/.../lr_v00.png --threads 1,2,4,8 --sizes 640x360,320x180
"""

import argparse
import importlib.util
import statistics
import time

import numpy as np
import torch
from PIL import Image

TRAIN_SCRIPT = "tools/mmtrain/train.py"


def load_train_module():
    spec = importlib.util.spec_from_file_location("mmtrain", TRAIN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--arch", choices=("tiny", "tiny_up"), default="tiny")
    parser.add_argument("--scale", type=int, default=1,
            help="upsampling factor for tiny_up")
    parser.add_argument("--image", required=True)
    parser.add_argument("--threads", default="1,2,4,8")
    parser.add_argument("--sizes", default="640x360,320x180")
    parser.add_argument("--runs", type=int, default=30)
    args = parser.parse_args()

    train_module = load_train_module()
    image = Image.open(args.image).convert("RGB")
    rows = []
    for size in args.sizes.split(","):
        width, height = (int(value) for value in size.split("x"))
        resized = image.resize((width, height), Image.BICUBIC)
        array = np.asarray(resized).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array.transpose(2, 0, 1))[None]
        for threads in (int(value) for value in args.threads.split(",")):
            torch.set_num_threads(threads)
            if args.arch == "tiny_up":
                model = train_module.TinyUpsample(3, args.scale)
            else:
                model = train_module.Tiny(3)
            model.load_state_dict(torch.load(args.model, map_location="cpu"))
            model.eval()
            with torch.no_grad():
                for _ in range(5):
                    model(tensor)
                timings = []
                for _ in range(args.runs):
                    before = time.perf_counter()
                    model(tensor)
                    timings.append((time.perf_counter() - before) * 1000.0)
            median = statistics.median(timings)
            rows.append((size, threads, median))
            print(f"{size:>9} {threads:>2} thread(s): {median:8.3f} ms")
    print()
    print(f"{'size':>9} {'threads':>8} {'ms':>9}")
    for size, threads, median in rows:
        print(f"{size:>9} {threads:>8} {median:9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
