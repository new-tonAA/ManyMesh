#!/usr/bin/env python3
#
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

"""Make paired visual audit sheets from rendered LOD replay reports.

For each asset, include the best and worst PSNR changes across every supplied
trajectory, including no-ops. Selection is deterministic; the JSON records every
source frame and the policy choice. Error panels show absolute RGB error at 8x.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lod_oracle import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--captures", type=Path, nargs="+", required=True)
    parser.add_argument("--policy", default="proxy1_surface_causal")
    parser.add_argument("--exposure", type=float, default=1.0,
                        help="Fixed display multiplier applied equally to all RGB panels")
    parser.add_argument("--crop", action="store_true", help="Crop all panels to their shared foreground bounds")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not np.isfinite(args.exposure) or args.exposure <= 0:
        parser.error("--exposure must be positive and finite")
    captures = {digest(root / "geometry.json"): root for root in args.captures}
    assets = {}
    for report in json.loads(args.report.read_text(encoding="utf-8")):
        root = captures[report["capture_sha256"]]
        meta = json.loads((root / "geometry.json").read_text(encoding="utf-8"))
        views = [v for v in meta["views"] if v["asset_sha256"] == report["asset_sha256"]]
        policy = report["strategies"][args.policy]
        for view, stem, gain, outline, triangles in zip(
                views, policy["chosen"], policy["psnr_gain_db_by_frame"],
                policy["silhouette_delta_by_frame"], report["triangle_counts"], strict=True):
            assets.setdefault(report["asset_sha256"], []).append({
                "asset": report["asset"], "frame": str(root / view["directory"]),
                "stem": stem, "psnr_gain_db": gain, "silhouette_delta": outline,
                "triangles": triangles,
            })
    args.out.mkdir(parents=True, exist_ok=True)
    selected = []
    for asset, frames in assets.items():
        extrema = [min(frames, key=lambda r: r["psnr_gain_db"]),
                   max(frames, key=lambda r: r["psnr_gain_db"])]
        panels = []
        for row in extrema:
            path = Path(row["frame"])
            images = [Image.open(path / f"{stem}.png").convert("RGB") for stem in
                      ("oracle_reference", "oracle_baseline", row["stem"])]
            ref = np.asarray(images[0], dtype=float)
            for image in images[1:3]:
                error = np.abs(np.asarray(image, dtype=float) - ref) * 8
                images.append(Image.fromarray(np.clip(error, 0, 255).astype("uint8")))
            if args.crop:
                occupied = np.any(np.stack([np.asarray(im) for im in images[:3]]) > 2, axis=(0, 3))
                y, x = np.nonzero(occupied)
                if len(x):
                    box = (max(0, int(x.min()) - 8), max(0, int(y.min()) - 8),
                           min(images[0].width, int(x.max()) + 9),
                           min(images[0].height, int(y.max()) + 9))
                    images = [im.crop(box) for im in images]
            images[:3] = [Image.fromarray(np.clip(np.asarray(im, dtype=float) * args.exposure,
                                                0, 255).astype("uint8")) for im in images[:3]]
            if args.crop:
                images = [im.resize((im.width * 2, im.height * 2), Image.Resampling.NEAREST)
                          for im in images]
            width, height = max(320, images[0].width), images[0].height
            panel = Image.new("RGB", (width * 5, height + 64), "#20242b")
            draw = ImageDraw.Draw(panel)
            draw.text((8, 4), f"{row['asset']} | {path.parent.name}/{path.name} | "
                      f"{row['triangles']} triangles | gain {row['psnr_gain_db']:+.4f} dB | "
                      f"outline delta {row['silhouette_delta']:+.6f}", fill="white")
            for i, (image, label) in enumerate(zip(images, (
                    "Full detail", "Baseline", row["stem"], "Baseline error x8", "Selected error x8"))):
                panel.paste(image, (width * i, 64))
                draw.text((width * i + 8, 40), label, fill="white")
            panels.append(panel)
        sheet = Image.new("RGB", (max(p.width for p in panels), sum(p.height for p in panels)))
        sheet.paste(panels[0], (0, 0))
        sheet.paste(panels[1], (0, panels[0].height))
        filename = f"{Path(frames[0]['asset']).stem}-{asset[:8]}.png"
        sheet.save(args.out / filename)
        selected.append({"sheet": filename, "worst": extrema[0], "best": extrema[1]})
    (args.out / "frames.json").write_text(json.dumps({
        "policy": args.policy, "exposure": args.exposure, "crop": args.crop,
        "report_sha256": digest(args.report), "assets": selected,
    }, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(selected)} paired audit sheets to {args.out}")


if __name__ == "__main__":
    main()
