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

"""Reprojects a history frame for a pure camera rotation, and blends it in.

Temporal accumulation needs the previous frame aligned with the current one. When the camera
only *rotates* about its own centre there is no parallax, so a pixel's motion depends on the
rotation alone and not on how far away the surface is. The correspondence is then exact, and
can be computed without any depth buffer - which is the point of using a pan here.

`tools/mmgeo` can project the geometry it already has, but writing depth for every frame of
every sequence only to reproject a rotation would be wasted work.

The sequence rendered by `samples/mm_bench --pan D` is a pan of D degrees spread over the
capture count, so frame i and i-1 differ by a known rotation.

Usage:
    temporal.py --data out/m3pan --pan 3 --frames 12 --fov-y 45 --blend 0.5

Prints, per frame, the PSNR against the full detail target of: the coarse frame alone, and the
accumulated frame. Accumulation here is a plain exponential blend, the simplest form of what a
trained temporal model learns to do.
"""

import argparse
import glob
import math
import os

import numpy as np
from PIL import Image


def load(path):
    image = Image.open(path)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.asarray(image).astype(np.float64) / 255.0


def upscale(image, size):
    pil = Image.fromarray(np.clip(image * 255.0, 0, 255).round().astype(np.uint8))
    return np.asarray(pil.resize(size, Image.BICUBIC)).astype(np.float64) / 255.0


def camera_basis(eye, target, up_hint=(0.0, 1.0, 0.0)):
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.asarray(up_hint, dtype=np.float64))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return right, up, forward


def rot_y(vector, angle):
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = vector
    return np.array([x * c - z * s, y, x * s + z * c])


def reproject(history, width, height, fov_y, basis_prev, basis_now):
    """Warps `history` (rendered with basis_prev) into the view described by basis_now."""
    right_p, up_p, forward_p = basis_prev
    right_n, up_n, forward_n = basis_now

    f = (height * 0.5) / math.tan(0.5 * fov_y)

    xs = (np.arange(width) + 0.5 - width * 0.5) / f
    ys = (height * 0.5 - np.arange(height) - 0.5) / f
    u, v = np.meshgrid(xs, ys)

    # Ray through each pixel of the current frame, in world space (a pure rotation, so the eye
    # is shared and only the basis differs).
    direction = (forward_n[None, None, :]
                 + u[..., None] * right_n[None, None, :]
                 + v[..., None] * up_n[None, None, :])

    depth = direction @ forward_p
    u_prev = (direction @ right_p) / depth
    v_prev = (direction @ up_p) / depth

    x_prev = u_prev * f + width * 0.5 - 0.5
    y_prev = height * 0.5 - v_prev * f - 0.5

    # Bilinear sample.
    x0 = np.floor(x_prev).astype(np.int32)
    y0 = np.floor(y_prev).astype(np.int32)
    fx = x_prev - x0
    fy = y_prev - y0

    inside = (x0 >= 0) & (y0 >= 0) & (x0 + 1 < width) & (y0 + 1 < height)
    x0c = np.clip(x0, 0, width - 2)
    y0c = np.clip(y0, 0, height - 2)

    p00 = history[y0c, x0c]
    p10 = history[y0c, x0c + 1]
    p01 = history[y0c + 1, x0c]
    p11 = history[y0c + 1, x0c + 1]
    sampled = ((p00 * (1 - fx)[..., None] * (1 - fy)[..., None])
               + (p10 * fx[..., None] * (1 - fy)[..., None])
               + (p01 * (1 - fx)[..., None] * fy[..., None])
               + (p11 * fx[..., None] * fy[..., None]))
    return sampled, inside


def psnr(reference, candidate):
    mse = float(np.mean((reference - candidate) ** 2))
    return float("inf") if mse == 0.0 else 10.0 * math.log10(1.0 / mse)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="out/m3pan")
    parser.add_argument("--pan", type=float, default=3.0, help="total pan in degrees")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--fov-y", type=float, default=45.0)
    parser.add_argument("--eye", default="2.220,-6.737,220.771")
    parser.add_argument("--target", default="2.220,-6.737,9.837")
    parser.add_argument("--blend", type=float, default=0.5,
            help="weight of the history in the blend")
    args = parser.parse_args()

    eye = [float(v) for v in args.eye.split(",")]
    target0 = np.array([float(v) for v in args.target.split(",")])
    fov_y = math.radians(args.fov_y)

    lr_paths = sorted(glob.glob(os.path.join(args.data, "lr_v*.png")))
    if not lr_paths:
        raise SystemExit(f"no lr_v*.png under {args.data}")

    history = None
    basis_prev = None
    single_all, blend_all = [], []

    for index, path in enumerate(lr_paths):
        name = os.path.basename(path)[:-4].split("_v")[1]
        hr_path = os.path.join(args.data, f"hr_v{name}.png")
        if not os.path.exists(hr_path):
            raise SystemExit(f"missing {hr_path}")

        # The pan is spread evenly across the sequence, the same way mm_bench does it.
        t = index / max(len(lr_paths) - 1, 1)
        angle = (t - 0.5) * math.radians(args.pan)
        target = eye + rot_y(target0 - np.array(eye), angle)
        basis_now = camera_basis(eye, target)

        lr = load(path)
        height, width = lr.shape[:2]
        hr = load(hr_path)
        target_size = (hr.shape[1], hr.shape[0])

        accumulated = lr
        if history is not None:
            warped, inside = reproject(history, width, height, fov_y, basis_prev, basis_now)
            accumulated = np.where(inside[..., None],
                   (1.0 - args.blend) * lr + args.blend * warped, lr)

        single_all.append(psnr(hr, upscale(lr, target_size)))
        blend_all.append(psnr(hr, upscale(accumulated, target_size)))
        print(f"  frame {index:2d}  coarse {single_all[-1]:6.2f} dB   "
              f"accumulated {blend_all[-1]:6.2f} dB")

        history = accumulated
        basis_prev = basis_now

    print()
    print(f"median over {len(single_all)} frames: coarse {np.median(single_all):.2f} dB   "
          f"accumulated {np.median(blend_all):.2f} dB   "
          f"gain {np.median(blend_all) - np.median(single_all):+.2f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
