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


def read_camera_list(path):
    """Reads the exact per-frame cameras mm_bench wrote with --camera-out.

    Deriving the camera path here instead would let the pan/translation maths drift from the
    renderer, and a one-pixel disagreement silently shows up as ghosting rather than an error.
    """
    with open(path, "r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    header = lines[0].split()
    if header[:2] != ["manymesh-cameras", "1"]:
        raise SystemExit(f"{path} is not a version 1 manymesh camera list")
    views, jitter, count = 1, 1, 0
    index = 1
    while index < len(lines):
        parts = lines[index].split()
        if parts[0] == "views":
            views = int(parts[1])
        elif parts[0] == "jitter":
            jitter = int(parts[1])
        elif parts[0] == "count":
            count = int(parts[1])
            index += 1
            break
        else:
            raise SystemExit(f"unknown camera list field '{parts[0]}'")
        index += 1
    cameras = []
    for line in lines[index:]:
        parts = line.split()
        cameras.append({
            "eye": np.array([float(value) for value in parts[1:4]]),
            "target": np.array([float(value) for value in parts[4:7]]),
            "fov": float(parts[7]),
            "width": int(parts[8]),
            "height": int(parts[9]),
        })
    if len(cameras) != count:
        raise SystemExit(f"{path}: expected {count} cameras, found {len(cameras)}")
    return {"views": views, "jitter": jitter, "cameras": cameras}


def load_depth(path):
    with open(path, "rb") as handle:
        if handle.readline().strip() != b"MMDEPTH1":
            raise SystemExit(f"{path} is not a mmdepth file")
        width, height = (int(value) for value in handle.readline().split())
        pixels = np.frombuffer(handle.read(width * height * 4), dtype="<f4")
    if pixels.size != width * height:
        raise SystemExit(f"{path}: truncated depth image")
    return pixels.reshape(height, width).astype(np.float64)


def depth_path(directory, capture, jitter):
    name = (f"depth_v{capture // jitter:02d}_j{capture % jitter:02d}.depth"
            if jitter > 1 else f"depth_v{capture:02d}.depth")
    return os.path.join(directory, name)


def bilinear(image, x, y, inside):
    """Samples an HxW or HxWxC float image with bilinear filtering."""
    height, width = image.shape[:2]
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    fx = x - x0
    fy = y - y0
    x0c = np.clip(x0, 0, width - 2)
    y0c = np.clip(y0, 0, height - 2)
    if image.ndim == 2:
        p00 = image[y0c, x0c]
        p10 = image[y0c, x0c + 1]
        p01 = image[y0c + 1, x0c]
        p11 = image[y0c + 1, x0c + 1]
        return ((p00 * (1 - fx) * (1 - fy)) + (p10 * fx * (1 - fy))
                + (p01 * (1 - fx) * fy) + (p11 * fx * fy))
    return ((image[y0c, x0c] * (1 - fx)[..., None] * (1 - fy)[..., None])
            + (image[y0c, x0c + 1] * fx[..., None] * (1 - fy)[..., None])
            + (image[y0c + 1, x0c] * (1 - fx)[..., None] * fy[..., None])
            + (image[y0c + 1, x0c + 1] * fx[..., None] * fy[..., None]))


def reproject_with_depth(history, depth_prev, depth_now, camera_prev, camera_now,
        tolerance):
    """Warps history into the current view using the current frame's depth.

    With translation there is no depth-independent homography: a pixel's previous location is
    its world position projected through the previous camera. That needs the depth of the
    frame being reconstructed (which mmdepth rasterizes from the same coarse mesh), plus the
    previous frame's depth for an occlusion test - the previous camera may have seen a nearer
    surface at the warped location, which is exactly a disocclusion.
    """
    width = depth_now.shape[1]
    height = depth_now.shape[0]
    right_n, up_n, forward_n = camera_basis(camera_now["eye"], camera_now["target"])
    right_p, up_p, forward_p = camera_basis(camera_prev["eye"], camera_prev["target"])

    f = (height * 0.5) / math.tan(0.5 * camera_now["fov"])
    xs = (np.arange(width) + 0.5 - width * 0.5) / f
    ys = (height * 0.5 - np.arange(height) - 0.5) / f
    u, v = np.meshgrid(xs, ys)

    direction = (forward_n[None, None, :] + u[..., None] * right_n[None, None, :]
                 + v[..., None] * up_n[None, None, :])
    world = camera_now["eye"][None, None, :] + direction * depth_now[..., None]

    delta = world - camera_prev["eye"][None, None, :]
    z_prev = delta @ forward_p
    valid = (depth_now > 0.0) & (z_prev > 1e-4)
    safe_z = np.where(z_prev > 1e-4, z_prev, 1.0)
    u_prev = (delta @ right_p) / safe_z
    v_prev = (delta @ up_p) / safe_z
    x_prev = u_prev * f + width * 0.5 - 0.5
    y_prev = height * 0.5 - v_prev * f - 0.5

    inside = (valid & (x_prev >= 0) & (y_prev >= 0)
              & (x_prev < width - 1) & (y_prev < height - 1))
    sampled = bilinear(history, x_prev, y_prev, inside)
    sampled_depth = bilinear(depth_prev, x_prev, y_prev, inside)

    # A depth mismatch means the history pixel belongs to a surface the previous camera saw in
    # front of (or behind) the point we are reconstructing: an occlusion boundary, not noise.
    depth_ok = np.abs(sampled_depth - z_prev) <= tolerance * np.maximum(np.abs(z_prev), 1e-4)
    accept = inside & depth_ok
    return sampled, accept, z_prev


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
    parser.add_argument("--cameras", default="",
            help="camera list written by mm_bench --camera-out; required for translation")
    parser.add_argument("--depth-dir", default="",
            help="directory of mmdepth files; enables depth-based reprojection and occlusion "
                 "rejection")
    parser.add_argument("--depth-tolerance", type=float, default=0.05,
            help="relative depth mismatch at which history is rejected as disoccluded")
    parser.add_argument("--no-reproject", action="store_true",
            help="blend history without alignment; the negative control that shows ghosting")
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

    camera_list = read_camera_list(args.cameras) if args.cameras else None
    if camera_list is not None:
        per_view = camera_list["jitter"] > 1
        if len(camera_list["cameras"]) != len(lr_paths):
            raise SystemExit(f"{args.cameras}: {len(camera_list['cameras'])} cameras but "
                             f"{len(lr_paths)} rendered frames")
    if args.depth_dir and camera_list is None:
        raise SystemExit("--depth-dir needs --cameras: depth reprojection needs the exact "
                         "cameras the renderer used")
    depth_prev = None
    camera_prev = None

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

        if camera_list is not None:
            # The renderer wrote the exact camera for this capture, so there is no separate
            # camera model here to drift out of sync with it.
            camera_now = camera_list["cameras"][index]
            view_eye = camera_now["eye"]
            target = camera_now["target"]
            frame_fov_y = math.radians(camera_now["fov"])
            view_index, sub_index = divmod(index, max(camera_list["jitter"], 1)) if per_view \
                    else (index, 0)
            frames_per_view = camera_list["jitter"]
        else:
            # The camera model has to match mm_bench: the eye orbits the base target by the
            # view's azimuth, and within a view the pan turns the view direction about that eye.
            camera_now = None
            frame_fov_y = fov_y
            frames_per_view = args.frames
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

        depth_now = load_depth(depth_path(args.depth_dir, index, frames_per_view)) \
                if args.depth_dir else None

        # A per-view layout holds several independent sequences, so history must not cross
        # from the end of one into the start of the next.
        if per_view and index % frames_per_view == 0:
            history = None
            depth_prev = None
            camera_prev = None

        accumulated = lr
        warped = None
        inside = None
        if history is not None and args.no_reproject:
            warped = history
            accept = np.ones(lr.shape[:2], dtype=bool)
            accumulated = (1.0 - args.blend) * lr + args.blend * warped
            rejected_fraction = 0.0
        elif history is not None:
            if depth_now is not None and depth_prev is not None and camera_prev is not None:
                warped, accept, _ = reproject_with_depth(history, depth_prev, depth_now,
                        camera_prev, camera_now, args.depth_tolerance)
            else:
                if camera_list is not None and np.linalg.norm(view_eye - camera_prev["eye"]) > 1e-6:
                    raise SystemExit("camera translation needs --depth-dir; a rotation-only "
                                     "homography would produce ghosting")
                warped, inside = reproject(history, width, height, frame_fov_y, basis_prev,
                        basis_now)
                accept = inside
            if args.reject > 0.0:
                # Reject history where it disagrees strongly with what was just rendered. In a
                # full pipeline that is the proxy for a disocclusion or a shading change, which
                # the motion vectors alone cannot express. Note that with depth we already have
                # a geometric disocclusion test; the colour test is kept for A/B only.
                accept = accept & (np.abs(warped - lr).max(axis=2) <= args.reject)
            accumulated = np.where(accept[..., None],
                   (1.0 - args.blend) * lr + args.blend * warped, lr)
            # Report rejection where history could exist at all. Counting the background as
            # "rejected" made a 2% disocclusion rate look like 80%.
            covered = depth_now > 0.0 if depth_now is not None \
                    else np.ones(accept.shape, dtype=bool)
            rejected_fraction = 1.0 - float(accept[covered].mean()) if covered.any() else 0.0

        single_all.append(psnr(hr, upscale(lr, target_size)))
        blend_all.append(psnr(hr, upscale(accumulated, target_size)))
        print(f"  frame {index:2d}  coarse {single_all[-1]:6.2f} dB   "
              f"accumulated {blend_all[-1]:6.2f} dB")

        if warped is not None and rejected_fraction > 0.0:
            print(f"  frame {index:2d}  rejected {100.0 * rejected_fraction:.1f}% of the history")
        if args.export and warped is not None:
            # The training set is laid out the way tools/mmtrain expects: two "sub frames" per
            # view, the current observation and the reprojected history, so --stack 2 feeds
            # both to the network. Rejected history falls back to the current frame, which is
            # what a runtime would do when it has no valid history for that pixel.
            def save(array, path):
                Image.fromarray(np.clip(array * 255.0, 0, 255).round().astype(np.uint8)).save(path)

            history_for_network = np.where(accept[..., None], warped, lr)
            save(upscale(lr, target_size), os.path.join(args.export, f"lr_v{exported:02d}_j00.png"))
            save(upscale(history_for_network, target_size),
                    os.path.join(args.export, f"lr_v{exported:02d}_j01.png"))
            save(hr, os.path.join(args.export, f"hr_v{exported:02d}.png"))
            exported += 1

        history = accumulated
        basis_prev = basis_now
        camera_prev = camera_now
        depth_prev = depth_now

    print()
    if args.export:
        print(f"exported {exported} training triplets to {args.export}")
    print(f"median over {len(single_all)} frames: coarse {np.median(single_all):.2f} dB   "
          f"accumulated {np.median(blend_all):.2f} dB   "
          f"gain {np.median(blend_all) - np.median(single_all):+.2f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
