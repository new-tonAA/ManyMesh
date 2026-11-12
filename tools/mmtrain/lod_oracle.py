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

"""Capture and score a single-step, equal-triangle LOD intervention experiment."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command, log):
    with log.open("w", encoding="utf-8") as output:
        try:
            subprocess.run([str(value) for value in command], stdout=output,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"Failed to run {command[0]}; see {log}") from error


def cameras(mesh, count, arc_degrees=360.0, start_degrees=0.0):
    low = [math.inf] * 3
    high = [-math.inf] * 3
    with mesh.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("v "):
                for axis, value in enumerate(map(float, line.split()[1:4])):
                    low[axis] = min(low[axis], value)
                    high[axis] = max(high[axis], value)
    center = [(a + b) / 2 for a, b in zip(low, high)]
    radius = math.dist(low, high) / 2
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError(f"Invalid OBJ bounds: {mesh}")
    for i in range(count):
        if arc_degrees == 360.0:
            angle = math.radians(start_degrees) + (i + 0.25) * math.tau / count
            distance = radius * (3.1 + 0.55 * math.sin(angle))
        else:
            t = i / max(count - 1, 1)
            angle = math.radians(start_degrees + arc_degrees * t)
            distance = radius * (3.4 - 0.6 * t)
        eye = [center[0] + distance * math.sin(angle),
               center[1] + 0.28 * distance,
               center[2] + distance * math.cos(angle)]
        yield ",".join(map(str, eye)), ",".join(map(str, center))


def export_geometry(args):
    args.out.mkdir(parents=True, exist_ok=False)
    provenance = {
        "mmgeo_sha256": digest(args.mmgeo),
        "width": args.height * 16 // 9,
        "height": args.height,
        "target_ratio": args.ratio,
        "max_swaps": args.swaps,
        "max_composites": args.composites,
        "arc_degrees": args.arc_degrees,
        "start_degrees": args.start_degrees,
        "views": [],
    }
    for asset_index, mesh in enumerate(args.mesh):
        graph_hash = None
        asset_hash = digest(mesh)
        for view, (eye, target) in enumerate(
                cameras(mesh, args.views, args.arc_degrees, args.start_degrees)):
            name = f"{asset_index:02}_{mesh.stem}_v{view:02}"
            path = args.out / name
            path.mkdir()
            run([args.mmgeo.resolve(), mesh.resolve(), "--out", path, "--mode", "dag",
                 "--target-ratio", args.ratio, "--oracle-swaps", args.swaps,
                 "--oracle-composites", args.composites,
                 "--eye", eye, "--look-at", target, "--screen-height", args.height,
                 "--dump-obj", "0", "--dump-format", "obj",
                 "--write-json", "1" if args.composites else "0"],
                path / "mmgeo.log")
            current_hash = digest(path / "lod_graph.mmb")
            if graph_hash is not None and graph_hash != current_hash:
                raise RuntimeError(f"LOD hierarchy changed between views: {path}")
            graph_hash = current_hash
            with (path / "oracle.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            counts = {row["stem"]: int(row["triangles"]) for row in rows}
            if (counts["oracle_reference"] <= counts["oracle_baseline"]
                    or any(count != counts["oracle_baseline"] for stem, count in counts.items()
                           if stem != "oracle_reference")):
                raise RuntimeError(f"Invalid triangle counts in {path / 'oracle.csv'}")
            for stem, triangles in counts.items():
                obj = path / f"{stem}.obj"
                with obj.open() as stream:
                    if sum(line.startswith("f ") for line in stream) != triangles:
                        raise RuntimeError(f"Unexpected exported triangle count: {obj}")
            provenance["views"].append({
                "directory": name, "asset": mesh.name, "asset_sha256": asset_hash,
                "graph_sha256": graph_hash, "eye": eye, "target": target,
            })
            print(f"{name}: {len(rows) - 2} equal-triangle swaps", flush=True)
    (args.out / "geometry.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")


def render_capture(root, renderer):
    provenance = json.loads((root / "geometry.json").read_text(encoding="utf-8"))
    provenance["mm_bench_sha256"] = digest(renderer)
    size = f"{provenance['width']}x{provenance['height']}"
    capture_path = root / "capture.json"
    capture_path.unlink(missing_ok=True)
    for view in provenance["views"]:
        path = root / view["directory"]
        camera_hash = None
        with (path / "oracle.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            stem = row["stem"]
            png = path / f"{stem}.png"
            camera_path = path / f"{stem}_camera.txt"
            png.unlink(missing_ok=True)
            camera_path.unlink(missing_ok=True)
            run([renderer.resolve(), "--headless", "--window-size", size,
                 "--warmup", "3", "--measure", "3", "--no-shadows",
                 "--eye", view["eye"], "--target", view["target"], "--out", png,
                 "--camera-out", camera_path, path / f"{stem}.obj"], path / f"{stem}.log")
            if not png.is_file():
                raise RuntimeError(f"Renderer did not write {png}")
            current_camera_hash = digest(camera_path)
            if camera_hash is not None and camera_hash != current_camera_hash:
                raise RuntimeError(f"Render camera changed within {path}")
            camera_hash = current_camera_hash
        view["camera_sha256"] = camera_hash
        print(f"{path.name}: rendered {len(rows)} cuts", flush=True)
    capture_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")


def score(args):
    import numpy as np
    from PIL import Image

    if args.checkpoint:
        import torch
        from train import Tiny

        torch.set_num_threads(2)
        model = Tiny(3)
        model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
        model.eval()

        @torch.inference_mode()
        def reconstruct(image):
            tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)
            return model(tensor)[0].permute(1, 2, 0).numpy()
    else:
        def reconstruct(image):
            return image

    def load(path):
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.float32) / 255

    def mse(image, reference):
        return float(np.mean(np.square(image - reference), dtype=np.float64))

    def psnr(error):
        return -10 * math.log10(max(error, 1e-12))

    provenance = json.loads((args.capture / "capture.json").read_text(encoding="utf-8"))
    result = {"checkpoint_sha256": digest(args.checkpoint) if args.checkpoint else None,
              "strengths": args.strengths, "capture": provenance, "views": []}
    for view in provenance["views"]:
        path = args.capture / view["directory"]
        reference = load(path / "oracle_reference.png")
        if reference.shape != (provenance["height"], provenance["width"], 3):
            raise ValueError(f"Reference size differs from capture metadata: {path}")
        background = reference[0, 0]
        corners = ((0, 0), (0, -1), (-1, 0), (-1, -1))
        if not all(np.array_equal(reference[y, x], background) for y, x in corners):
            raise ValueError(f"Reference must have a flat background at the corners: {path}")
        ref_mask = np.any(reference != background, axis=2)
        if not 0 < ref_mask.mean() < 1:
            raise ValueError(f"Reference is empty or fully covers the viewport: {path}")
        with (path / "oracle.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))[1:]
        for row in rows:
            image = load(path / f"{row['stem']}.png")
            if image.shape != reference.shape:
                raise ValueError(f"Size mismatch in {path}: {row['stem']}")
            mask = np.any(image != background, axis=2)
            union = mask | ref_mask
            prediction = reconstruct(image)
            rebuilt_image = np.clip(prediction, 0, 1)
            row["raw_mse"] = mse(image, reference)
            row["reconstructed_mse"] = mse(rebuilt_image, reference)
            if args.strengths:
                row["mse_by_strength"] = {
                    str(strength): (row["raw_mse"] if strength == 0
                                    else row["reconstructed_mse"] if strength == 1
                                    else mse(np.clip(image + strength * (prediction - image),
                                                     0, 1), reference))
                    for strength in args.strengths
                }
            row["raw_mse_on_foreground_union"] = mse(image[union], reference[union])
            row["reconstructed_mse_on_foreground_union"] = mse(
                rebuilt_image[union], reference[union])
            row["silhouette_xor_over_union"] = float(
                np.count_nonzero(mask ^ ref_mask) / np.count_nonzero(union))
        baseline = rows[0]
        geometric = max(rows, key=lambda row: float(row["geometric_score"] or 0))
        raw = min(rows, key=lambda row: row["raw_mse"])
        rebuilt = min(rows, key=lambda row: row["reconstructed_mse"])
        rebuilt_gain = psnr(rebuilt["reconstructed_mse"]) - psnr(baseline["reconstructed_mse"])
        rank_gain = psnr(rebuilt["reconstructed_mse"]) - psnr(raw["reconstructed_mse"])
        result["views"].append({
            "directory": view["directory"], "candidates": rows,
            "geometric_choice": geometric["stem"], "raw_oracle": raw["stem"],
            "reconstructed_oracle": rebuilt["stem"],
            "raw_oracle_gain_db": psnr(raw["raw_mse"]) - psnr(baseline["raw_mse"]),
            "reconstructed_oracle_gain_db": rebuilt_gain,
            "reconstructed_oracle_vs_raw_choice_db": rank_gain,
            "reconstructed_geometric_gain_db": psnr(geometric["reconstructed_mse"])
            - psnr(baseline["reconstructed_mse"]),
        })
        print(f"{path.name}: {len(rows) - 1} swaps, reconstructed oracle {rebuilt_gain:+.4f} dB,"
              f" vs raw oracle choice {rank_gain:+.4f} dB", flush=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("capture")
    collect.add_argument("--mmgeo", type=Path, required=True)
    collect.add_argument("--mm-bench", type=Path, help="Omit to export geometry only")
    collect.add_argument("--out", type=Path, required=True)
    collect.add_argument("--mesh", type=Path, nargs="+", required=True, help="OBJ assets")
    collect.add_argument("--ratio", type=float, default=0.60)
    collect.add_argument("--views", type=int, default=4)
    collect.add_argument("--arc-degrees", type=float, default=360.0)
    collect.add_argument("--start-degrees", type=float, default=0.0)
    collect.add_argument("--height", type=int, default=180)
    collect.add_argument("--swaps", type=int, default=16)
    collect.add_argument("--composites", type=int, default=0)
    render = commands.add_parser("render")
    render.add_argument("--capture", type=Path, required=True)
    render.add_argument("--mm-bench", type=Path, required=True)
    evaluate = commands.add_parser("score")
    evaluate.add_argument("--capture", type=Path, required=True)
    evaluate.add_argument("--out", type=Path, required=True)
    evaluate.add_argument("--checkpoint", type=Path, help="Frozen RGB Tiny scale=1 weights")
    evaluate.add_argument("--strengths", nargs="+", type=float, default=[],
                          help="Evaluate these reconstruction residual strengths as well")
    args = parser.parse_args()
    if args.command == "capture":
        if not (0 < args.ratio < 1 and args.views >= 1 and args.height >= 64
                and 0 <= args.swaps <= 256 and 0 <= args.composites <= 256
                and args.swaps + args.composites > 0 and 0 < args.arc_degrees <= 360
                and math.isfinite(args.start_degrees)):
            parser.error("capture requires 0 < ratio < 1, views >= 1, height >= 64, swaps 1–256")
        export_geometry(args)
        if args.mm_bench:
            render_capture(args.out, args.mm_bench)
    elif args.command == "render":
        render_capture(args.capture, args.mm_bench)
    else:
        if args.strengths and (not args.checkpoint
                or any(not math.isfinite(s) or s < 0 for s in args.strengths)):
            parser.error("--strengths requires a checkpoint and finite nonnegative values")
        score(args)


if __name__ == "__main__":
    main()
