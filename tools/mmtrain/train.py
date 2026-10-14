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

"""Trains and compares reconstruction networks for ManyMesh.

ManyMesh renders coarse geometry at a low resolution and asks a network to put the picture
back. Two questions matter:

  1. Is the *Geometry Error Map* - the per cluster error the geometry stage already computes -
     worth feeding to the network? That is `--no-error-map`, run both ways.
  2. How does a purpose-built tiny network compare with published lightweight super
     resolution architectures, and with plain bicubic upsampling?

The data is a set of views rendered twice from the same cameras: once from the full detail
mesh (`hr_vNN.png`) and once from the decimated one (`lr_vNN.png`), plus the error map the
geometry stage projected for that view (`err/vNN/error_map.pgm`). See tools/mmgeo and
samples/mm_bench for how to produce them.

Architectures:
  bicubic   no network at all; the upsampled coarse render, as a floor to compare against
  tiny      ours: a few 3x3 convolutions predicting a residual over the upsampled render
  espcn     Shi et al., "Real-Time Single Image and Video Super-Resolution Using an Efficient
            Sub-Pixel Convolutional Neural Network", CVPR 2016
  fsrcnn    Dong et al., "Accelerating the Super-Resolution Convolutional Neural Network",
            ECCV 2016
  unet      a small encoder-decoder, to check that capacity is not what limits the others

espcn and fsrcnn do their upsampling inside the network, so they take the low resolution
image directly. tiny and unet take a bicubically pre-upsampled image and predict a residual,
which is the cheaper and more common arrangement for same-resolution restoration.

Usage:
    train.py --data out/m3 --model tiny --scale 2 [--iterations N] [--no-error-map]
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

MODELS = ("bicubic", "tiny", "espcn", "fsrcnn", "unet")
POST_UPSAMPLE = ("espcn", "fsrcnn")


def read_pgm(path):
    with open(path, "rb") as handle:
        data = handle.read()
    parts = data.split(b"\n", 3)
    width, height = (int(value) for value in parts[1].split())
    pixels = data[len(parts[0]) + len(parts[1]) + len(parts[2]) + 3:]
    return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width)


def resize(array, size):
    """Bicubic resize. `array` is float [0,1] with 1 or 3 channels."""
    if array.shape[:2] == (size[1], size[0]):
        return array
    if array.ndim == 3:
        image = Image.fromarray(np.clip(array * 255.0, 0, 255).round().astype(np.uint8))
    else:
        image = Image.fromarray(np.clip(array * 255.0, 0, 255).round().astype(np.uint8), "L")
    return np.asarray(image.resize(size, Image.BICUBIC)).astype(np.float32) / 255.0


def load_dataset(data_dir, with_error_map):
    views = []
    lr_paths = sorted(glob.glob(os.path.join(data_dir, "lr_v*.png")))
    if not lr_paths:
        raise SystemExit(f"no lr_v*.png under {data_dir}")

    for lr_path in lr_paths:
        index = os.path.basename(lr_path)[:-4].split("_v")[1]
        hr_path = os.path.join(data_dir, f"hr_v{index}.png")
        if not os.path.exists(hr_path):
            raise SystemExit(f"missing {hr_path}")

        lr_image = Image.open(lr_path)
        if lr_image.mode != "RGB":
            lr_image = lr_image.convert("RGB")
        lr = np.asarray(lr_image).astype(np.float32) / 255.0

        hr_image = Image.open(hr_path)
        if hr_image.mode != "RGB":
            hr_image = hr_image.convert("RGB")
        hr = np.asarray(hr_image).astype(np.float32) / 255.0

        if lr.shape != hr.shape:
            raise SystemExit(f"{lr_path} and {hr_path} differ in size")

        error = None
        if with_error_map:
            error = read_pgm(os.path.join(data_dir, "err", f"v{index}", "error_map.pgm"))
            if error.shape != lr.shape[:2]:
                raise SystemExit(f"error map for view {index} does not match the render size")
            error = error.astype(np.float32) / 255.0

        views.append({"lr": lr, "hr": hr, "error": error})

    return views


class Tiny(nn.Module):
    """Ours: a few convolutions predicting a residual over the upsampled coarse render."""

    def __init__(self, in_channels, channels=32):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(in_channels, channels, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(channels, 3, 3, padding=1),
        )

    def forward(self, x):
        return x[:, :3] + self.body(x)


class ESPCN(nn.Module):
    """Shi et al., CVPR 2016. Two feature layers then a sub-pixel shuffle."""

    def __init__(self, in_channels, scale, channels=64):
        super().__init__()
        self.scale = scale
        self.body = nn.Sequential(
            nn.Conv2d(in_channels, channels, 5, padding=2), nn.Tanh(),
            nn.Conv2d(channels, 32, 3, padding=1), nn.Tanh(),
            nn.Conv2d(32, 3 * scale * scale, 3, padding=1),
        )
        self.shuffle = nn.PixelShuffle(scale)

    def forward(self, x):
        return self.shuffle(self.body(x))


class FSRCNN(nn.Module):
    """Dong et al., ECCV 2016. Shrinking, mapping, expanding, then deconvolution."""

    def __init__(self, in_channels, scale, d=56, s=12, m=4):
        super().__init__()
        layers = [nn.Conv2d(in_channels, d, 5, padding=2), nn.PReLU(d)]   # feature extraction
        layers += [nn.Conv2d(d, s, 1), nn.PReLU(s)]                       # shrinking
        for _ in range(m):
            layers += [nn.Conv2d(s, s, 3, padding=1), nn.PReLU(s)]        # mapping
        layers += [nn.Conv2d(s, d, 1), nn.PReLU(d)]                       # expanding
        if scale == 1:
            layers += [nn.Conv2d(d, 3, 3, padding=1)]
        else:
            layers += [nn.ConvTranspose2d(d, 3, 9, stride=scale, padding=4,
                                          output_padding=scale - 1)]
        self.body = nn.Sequential(*layers)

    def forward(self, x):
        return self.body(x)


class SmallUNet(nn.Module):
    """A small encoder-decoder, as a capacity check rather than a real proposal."""

    def __init__(self, in_channels, channels=32):
        super().__init__()
        def block(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.ReLU(inplace=True),
                                 nn.Conv2d(o, o, 3, padding=1), nn.ReLU(inplace=True))

        self.down1 = block(in_channels, channels)
        self.down2 = block(channels, channels * 2)
        self.middle = block(channels * 2, channels * 2)
        self.up2 = nn.ConvTranspose2d(channels * 2, channels, 2, stride=2)
        self.up1 = block(channels * 2, channels)
        self.head = nn.Conv2d(channels, 3, 3, padding=1)
        self.pool = nn.MaxPool2d(2)

    def forward(self, x):
        residual = x[:, :3]
        d1 = self.down1(x)
        d2 = self.down2(self.pool(d1))
        m = self.middle(d2)
        u2 = self.up2(m)
        u1 = self.up1(torch.cat([u2, d1], dim=1))
        return residual + self.head(u1)


def build_model(name, in_channels, scale, channels):
    if name == "tiny":
        return Tiny(in_channels, channels)
    if name == "espcn":
        return ESPCN(in_channels, scale, channels * 2)
    if name == "fsrcnn":
        return FSRCNN(in_channels, scale)
    if name == "unet":
        return SmallUNet(in_channels, channels)
    raise SystemExit(f"unknown model {name}")


def psnr(reference, candidate):
    mse = float(np.mean((reference - candidate) ** 2))
    return float("inf") if mse == 0.0 else 10.0 * np.log10(1.0 / mse)


def ssim(reference, candidate):
    from skimage.metrics import structural_similarity

    return float(structural_similarity(reference, candidate, channel_axis=2, data_range=1.0))


@torch.no_grad()
def evaluate(model, views, scale, post_upsample):
    """Full frame metrics on the held out views."""
    from skimage.metrics import structural_similarity

    rows = []
    for view in views:
        inputs = prepare_input(view, scale, post_upsample)
        if model is None:
            output = prepare_input({**view, "error": None}, scale, post_upsample)
        else:
            tensor = torch.from_numpy(inputs.transpose(2, 0, 1))[None]
            output = model(tensor)[0].clamp(0.0, 1.0).numpy().transpose(1, 2, 0)

        rows.append({
            "psnr": psnr(view["hr"], output),
            "ssim": float(structural_similarity(view["hr"], output, channel_axis=2, data_range=1.0)),
        })
    return {
        "psnr": float(np.median([row["psnr"] for row in rows])),
        "ssim": float(np.median([row["ssim"] for row in rows])),
        "per_view_psnr": [row["psnr"] for row in rows],
    }


def prepare_input(view, scale, post_upsample):
    """Builds the network input: the coarse observation, plus the error map when enabled.

    `scale` > 1 means the observation is reduced by that factor first. Networks that upsample
    internally take it at the reduced size; the others get it bicubically restored so they can
    predict a residual over it.
    """
    hr_height, hr_width = view["hr"].shape[:2]
    if scale == 1:
        base = view["lr"]
    else:
        small = resize(view["lr"], (hr_width // scale, hr_height // scale))
        base = small if post_upsample else resize(small, (hr_width, hr_height))

    if view["error"] is None:
        return base

    error = view["error"]
    if base.shape[:2] != error.shape[:2]:
        # The network's input resolution decides what the error map has to be resampled to.
        error = resize(error, (base.shape[1], base.shape[0]))
    return np.concatenate([base, error[..., None]], axis=2)


def sample_batch(train_views, patch, batch, scale, post_upsample, in_channels, rng):
    hr_h, hr_w = train_views[0]["hr"].shape[:2]

    # Networks that upsample internally see the observation at its reduced size; the others
    # see it already restored, so their input crop is the full patch.
    reduced = post_upsample and scale > 1
    low = patch // scale if reduced else patch

    batch_x = np.empty((batch, low, low, in_channels), dtype=np.float32)
    batch_y = np.empty((batch, patch, patch, 3), dtype=np.float32)

    for b in range(batch):
        view = train_views[rng.integers(len(train_views))]
        top = rng.integers(0, hr_h - patch + 1)
        left = rng.integers(0, hr_w - patch + 1)
        batch_y[b] = view["hr"][top:top + patch, left:left + patch]

        source = prepare_input(view, scale, post_upsample)
        low_top, low_left = (top // scale, left // scale) if reduced else (top, left)
        batch_x[b] = source[low_top:low_top + low, low_left:low_left + low]

    return batch_x, batch_y


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default="out/m3")
    parser.add_argument("--model", default="tiny", choices=MODELS)
    parser.add_argument("--scale", type=int, default=2,
            help="observation is reduced by this factor; 1 means compared at equal resolution")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--patch", type=int, default=64, help="in the high resolution frame")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--channels", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-views", type=int, default=4)
    parser.add_argument("--no-error-map", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    with_error_map = not args.no_error_map
    views = load_dataset(args.data, with_error_map)
    if len(views) <= args.val_views:
        raise SystemExit("not enough views to hold any out for validation")
    train_views = views[:len(views) - args.val_views]
    val_views = views[len(views) - args.val_views:]

    post_upsample = args.model in POST_UPSAMPLE
    in_channels = 3 + (1 if with_error_map else 0)

    label = f"{args.model} x{args.scale}" + ("" if with_error_map else " (no error map)")
    print(f"--- {label} ---")
    print(f"{len(train_views)} train / {len(val_views)} val views, "
          f"{in_channels} input channels")

    if args.model == "bicubic":
        metrics = evaluate(None, val_views, args.scale, post_upsample)
        print(f"  PSNR {metrics['psnr']:.2f} dB   SSIM {metrics['ssim']:.4f}")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump({"model": args.model, "scale": args.scale, "metrics": metrics},
                          handle, indent=2)
        return 0

    model = build_model(args.model, in_channels, args.scale, args.channels)
    print(f"  {sum(p.numel() for p in model.parameters())} parameters")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.L1Loss()

    best = None
    for iteration in range(1, args.iterations + 1):
        batch_x, batch_y = sample_batch(train_views, args.patch, args.batch, args.scale,
                post_upsample, in_channels, rng)
        x = torch.from_numpy(batch_x.transpose(0, 3, 1, 2))
        y = torch.from_numpy(batch_y.transpose(0, 3, 1, 2))

        loss = loss_fn(model(x), y)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if iteration % max(1, args.iterations // 5) == 0 or iteration == args.iterations:
            metrics = evaluate(model, val_views, args.scale, post_upsample)
            marker = ""
            if best is None or metrics["psnr"] > best["psnr"]:
                best = metrics
                marker = "  <- best"
            print(f"  iter {iteration:5d}  loss {loss.item():.5f}  "
                  f"PSNR {metrics['psnr']:6.2f} dB  SSIM {metrics['ssim']:.4f}{marker}")

    print(f"  final: PSNR {best['psnr']:.2f} dB   SSIM {best['ssim']:.4f}"
          f"   (per view {[round(v, 1) for v in best['per_view_psnr']]})")

    if args.out:
        torch.save(model.state_dict(), args.out + ".pt")
        with open(args.out + ".json", "w", encoding="utf-8") as handle:
            json.dump({"model": args.model, "scale": args.scale, "metrics": best,
                       "parameters": sum(p.numel() for p in model.parameters()),
                       "with_error_map": with_error_map}, handle, indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
