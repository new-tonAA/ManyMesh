"""Measure fixed-cut mesh rendering as instanced scene size grows."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import wgpu

from bench_component_gpu import select_adapter
from bench_mixed_scenes import (
    SceneRaster,
    SceneReference,
    gpu_mesh,
    load_asset_buffers,
    run_view,
    sha,
)


ASSETS = ("Avocado", "BarramundiFish", "CesiumMilkTruck", "Lantern", "WaterBottle")
COUNTS = (1_000, 4_000, 10_000)
EYE = (0.0, 0.0, 20.0)
WIDTH, HEIGHT = 1280, 720
SETTINGS = (
    ("source-native", "source", None),
    ("source-msaa4", "source", "msaa4"),
    ("cluster2-msaa4", "cluster2", "msaa4"),
)


def grid_transforms(count):
    # Keep the scene's world-space footprint fixed across counts. This makes
    # per-instance projected size shrink with density, as in a packed scene.
    columns = math.ceil(math.sqrt(count * 18.0 / 13.0))
    rows = math.ceil(count / columns)
    xs = np.linspace(-9.0, 9.0, columns, dtype=np.float32)
    ys = np.linspace(-6.5, 6.5, rows, dtype=np.float32)
    pitch_x = 18.0 / max(columns - 1, 1)
    pitch_y = 13.0 / max(rows - 1, 1)
    scale = 0.72 * min(pitch_x, pitch_y)
    records = {asset: [] for asset in ASSETS}
    for index in range(count):
        row, column = divmod(index, columns)
        angle = (index * 0.6180339887498949 % 1.0) * (2.0 * math.pi)
        asset = ASSETS[index % len(ASSETS)]
        records[asset].append((xs[column], ys[row], 0.0, scale,
                               math.cos(angle), math.sin(angle)))
    return {asset: np.asarray(records[asset], dtype=np.float32)
            for asset in ASSETS}, columns, rows, scale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--meshes", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--shader-root", type=Path, required=True)
    parser.add_argument("--source-lists", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--captures", type=Path)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--batches", type=int, default=2)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    stock_bytes = (args.stock / "cluster-cuts.json").read_bytes()
    stock = json.loads(stock_bytes)
    if stock["manifest_sha256"] != sha(manifest_bytes):
        raise ValueError("Stock cluster cuts do not match the geometry manifest")
    if not set(ASSETS) <= manifest["assets"].keys():
        raise ValueError("The frozen geometry manifest is missing a selected asset")
    sources = {row["name"]: row for path in args.source_lists
               for row in json.loads(path.read_bytes())}
    if not set(ASSETS) <= sources.keys():
        raise ValueError("Missing source provenance for selected assets")

    buffers = None
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SceneRaster(device, WIDTH, HEIGHT, args.shader_root)
    reference = SceneReference(device, 2 * WIDTH, 2 * HEIGHT, 1, False)
    buffers = load_asset_buffers(device, args.meshes, manifest, args.stock, stock)
    retries = []
    scripts = ("bench_instance_scale.py", "bench_mixed_scenes.py",
               "bench_component_gpu.py", "bench_bevy_smaa.py",
               "bench_silhouette_guide_fusion.py",
               "bench_sparse_silhouette_guide.py", "gray_flip.py")
    report = {
        "protocol": "five fixed licensed Khronos meshes; identical fixed-footprint layouts; source versus stock cluster depth 2; both 4x MSAA",
        "size": [WIDTH, HEIGHT],
        "reference_size": [2 * WIDTH, 2 * HEIGHT],
        "reference": "full source, 4x MSAA at 2x resolution, linear-light 2x box downsample",
        "camera_eye": EYE,
        "frames_per_batch": args.frames,
        "batches": args.batches,
        "adapter": dict(adapter.info),
        "wgpu": wgpu.__version__,
        "assets": {name: {"provenance": sources[name],
                          "geometry": manifest["assets"][name]["exports"],
                          "stock": stock["assets"][name]}
                   for name in ASSETS},
        "manifest_sha256": sha(manifest_bytes),
        "stock_manifest_sha256": sha(stock_bytes),
        "stock_commit": stock["upstream_commit"],
        "stock_binary_sha256": stock["demo_sha256"],
        "scripts": {name: sha(Path(__file__).with_name(name).read_bytes())
                    for name in scripts},
        "timestamp_retries": retries,
        "workloads": {},
    }

    for count in COUNTS:
        groups, columns, rows, scale = grid_transforms(count)
        transform_buffers = {
            name: device.create_buffer_with_data(
                data=values, usage=wgpu.BufferUsage.VERTEX)
            for name, values in groups.items()
        }
        plans = {
            kind: [(*buffers[name][kind], transform_buffers[name], len(groups[name]))
                   for name in ASSETS]
            for kind in ("source", "cluster2")
        }
        source_triangles = sum(draw[2] // 3 * draw[4] for draw in plans["source"])
        coarse_triangles = sum(draw[2] // 3 * draw[4] for draw in plans["cluster2"])
        captures = args.captures / str(count) if args.captures is not None else None
        if captures is not None:
            captures.mkdir(parents=True, exist_ok=True)
        result = run_view(
            raster, reference, plans, EYE, args.frames, args.batches,
            f"instances-{count}", retries, captures, settings=SETTINGS)
        timings = {
            name: {
                "gpu_ms_p50": float(np.median(values["gpu_ms"])),
                "gpu_ms_p95": float(np.percentile(values["gpu_ms"], 95)),
                "samples": len(values["gpu_ms"]),
                "gpu_ms_samples": [float(value) for value in values["gpu_ms"]],
            }
            for name, values in result["modes"].items()
        }
        report["workloads"][str(count)] = {
            "asset_order": list(ASSETS),
            "instance_transform_sha256": {
                name: sha(values.tobytes()) for name, values in groups.items()
            },
            "grid": {"columns": columns, "rows": rows, "scale": scale,
                     "world_bounds_xy": [-9.0, -6.5, 9.0, 6.5]},
            "indexed_draws": len(ASSETS),
            "instance_count": count,
            "triangles": {"source": source_triangles, "cluster2": coarse_triangles},
            "source_reference_sha256": result["reference_srgb_sha256"],
            "coverage_pixels": result["coverage_pixels"],
            "cross_asset_overlap_pixels": result["cross_asset_overlap_pixels"],
            "gpu_timing": timings,
            "quality_vs_full_source_reference": {
                name: row["quality"] for name, row in result["modes"].items()
            },
            "silhouette_xor_fraction": {
                name: row["silhouette_xor_fraction"] for name, row in result["modes"].items()
            },
            "candidate_image_sha256": {
                name: row["image_sha256"] for name, row in result["modes"].items()
            },
        }
        for buffer in transform_buffers.values():
            buffer.destroy()
        print(count, source_triangles, coarse_triangles, timings, flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
