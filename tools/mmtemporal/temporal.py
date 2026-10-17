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
    parser.add_argument("--frames", type=int, default=12,
            help="sub frames per view when the data is a per-view sequence set")
    parser.add_argument("--views", type=int, default=1)
    parser.add_argument("--fov-y", type=float, default=45.0)
    parser.add_argument("--eye", default="2.220,-6.737,220.771")
    parser.add_argument("--target", default="2.220,-6.737,9.837")
    parser.add_argument("--blend", type=float, default=0.5,
            help="weight of the history in the blend")
    parser.add_argument("--reject", type=float, default=0.0,
            help="drop history whose colour differs from the current frame by more than this; "
                 "0 disables rejection")
    parser.add_argument("--export", default="",
            help="also write (current, reprojected history, target) as a training set")
    args = parser.parse_args()

    eye = [float(v) for v in args.eye.split(",")]
    target0 = np.array([float(v) for v in args.target.split(",")])
    fov_y = math.radians(args.fov_y)

    lr_paths = sorted(glob.glob(os.path.join(args.data, "lr_v*.png")))
    if not lr_paths:
        lr_paths = sorted(glob.glob(os.path.join(args.data, "lr_v*_j*.png")))
    if not lr_paths:
        raise SystemExit(f"no lr_v*.png under {args.data}")
    per_view = "_j" in os.path.basename(lr_paths[0])

    history = None
    basis_prev = None
    single_all, blend_all = [], []
    exported = 0
    if args.export:
        os.makedirs(args.export, exist_ok=True)

    for index, path in enumerate(lr_paths):
        name = os.path.splitext(os.path.basename(path))[0].split("_")[1]  # v00
        # A per-view layout renders the target per sub frame as well, since each frame of the
        # pan is taken from its own camera.
        sub_for_name = index % args.frames
        hr_path = os.path.join(args.data, f"hr_{name}_j{sub_for_name:02d}.png"
                if per_view else f"hr_{name}.png")
        if not os.path.exists(hr_path):
            raise SystemExit(f"missing {hr_path}")

        # The camera model has to match mm_bench: the eye orbits the base target by the
        # view's azimuth, and within a view the pan turns the view direction about that eye.
        if per_view:
            view_index, sub_index = divmod(index, args.frames)
            azimuth = 2.0 * math.pi * view_index / max(args.views, 1)
            view_eye = target0 + rot_y(np.array(eye) - target0, azimuth)
            t = sub_index / max(args.frames - 1, 1)
            angle = (t - 0.5) * math.radians(args.pan)
            target = view_eye + rot_y(target0 - view_eye, angle)
        else:
            view_eye = np.array(eye)
            t = index / max(len(lr_paths) - 1, 1)
            angle = (t - 0.5) * math.radians(args.pan)
            target = view_eye + rot_y(target0 - view_eye, angle)
        basis_now = camera_basis(view_eye, target)

        lr = load(path)
        height, width = lr.shape[:2]
        hr = load(hr_path)
        target_size = (hr.shape[1], hr.shape[0])

        # A per-view layout holds several independent sequences, so history must not cross
        # from the end of one into the start of the next.
        if per_view and index % args.frames == 0:
            history = None

        accumulated = lr
        warped = None
        inside = None
        if history is not None:
            warped, inside = reproject(history, width, height, fov_y, basis_prev, basis_now)
            accept = inside
            if args.reject > 0.0:
                # Reject history where it disagrees strongly with what was just rendered. In a
                # full pipeline that is the proxy for a disocclusion or a shading change, which
                # the motion vectors alone cannot express.
                accept = inside & (np.abs(warped - lr).max(axis=2) <= args.reject)
            accumulated = np.where(accept[..., None],
                   (1.0 - args.blend) * lr + args.blend * warped, lr)
            rejected_fraction = 1.0 - float(accept.mean())

        single_all.append(psnr(hr, upscale(lr, target_size)))
        blend_all.append(psnr(hr, upscale(accumulated, target_size)))
        print(f"  frame {index:2d}  coarse {single_all[-1]:6.2f} dB   "
              f"accumulated {blend_all[-1]:6.2f} dB")

        if warped is not None and args.reject > 0.0:
            print(f"  frame {index:2d}  rejected {100.0 * rejected_fraction:.1f}% of the history")
        if args.export and warped is not None:
            # The training set is laid out the way tools/mmtrain expects: two "sub frames" per
            # view, the current observation and the reprojected history, so --stack 2 feeds
            # both to the network.
            def save(array, path):
                Image.fromarray(np.clip(array * 255.0, 0, 255).round().astype(np.uint8)).save(path)

            save(upscale(lr, target_size), os.path.join(args.export, f"lr_v{exported:02d}_j00.png"))
            save(upscale(warped, target_size), os.path.join(args.export, f"lr_v{exported:02d}_j01.png"))
            save(hr, os.path.join(args.export, f"hr_v{exported:02d}.png"))
            exported += 1

        history = accumulated
        basis_prev = basis_now

    print()
    if args.export:
        print(f"exported {exported} training triplets to {args.export}")
    print(f"median over {len(single_all)} frames: coarse {np.median(single_all):.2f} dB   "
          f"accumulated {np.median(blend_all):.2f} dB   "
          f"gain {np.median(blend_all) - np.median(single_all):+.2f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
