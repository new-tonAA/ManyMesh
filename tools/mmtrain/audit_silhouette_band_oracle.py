"""Measure how much image error a perfect correction near the coarse outline can remove."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion
import wgpu

from bench_bevy_smaa import score
from bench_component_gpu import Offscreen, linear_gray_to_srgb, load_export, select_adapter


RADII = (1, 2, 4)
CONTROLS = ("source-native", "source-msaa4", "source-smaa",
            "source-linear", "source-cubic", "qem-msaa4", "qem-smaa")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.benchmark.read_text(encoding="utf-8"))
    if baseline["manifest_sha256"] != digest(args.manifest.read_bytes()):
        raise ValueError("The silhouette screen must use the same geometry as the AA baseline")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    width, height = baseline["size"]
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"]:
        raise ValueError("The silhouette screen must use the AA baseline GPU and driver")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = Offscreen(device, width, height, 4, False)
    high = Offscreen(device, 2*width, 2*height, 4, False)
    report = {"benchmark_sha256": digest(args.benchmark.read_bytes()),
              "code_sha256": digest(Path(__file__).read_bytes()),
              "band_radii_pixels": RADII, "assets": {}}
    for asset, rows in baseline["assets"].items():
        meshes = {}
        for name in ("source", "parts"):
            key = manifest["assets"][asset]["exports"][name]
            positions, indices = load_export(args.meshes / asset / f"{name}.ply", key)
            meshes[name] = (device.create_buffer_with_data(data=positions, usage=wgpu.BufferUsage.VERTEX),
                            device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                            len(indices))
        _, coarse = raster.run(meshes["parts"], "msaa4", 1, True)
        if digest(coarse.tobytes()) != rows["parts-msaa4"]["image_sha256"]:
            raise ValueError(f"The coarse capture differs from the benchmark for {asset}")
        _, up = high.run(meshes["source"], "msaa4", 1, True)
        ref = linear_gray_to_srgb(up.reshape(height, 2, width, 2).mean(axis=(1, 3)))
        candidate = linear_gray_to_srgb(coarse)
        foreground = coarse > 0  # All shaded primitives have positive intensity.
        initial_sse = np.sum((candidate.astype(np.float64) - ref)**2)
        if initial_sse == 0:
            raise ValueError("The reduced mesh unexpectedly reproduces the reference")
        candidate_ms = float(np.median(rows["parts-msaa4"]["gpu_ms"]))
        eligible = [k for k in CONTROLS if np.median(rows[k]["gpu_ms"]) <= candidate_ms]
        controls = {k: rows[k]["quality"] for k in eligible}
        result = {"part_msaa4_gpu_ms": candidate_ms, "existing_quality": rows["parts-msaa4"]["quality"],
                  "eligible_without_correction_cost": controls,
                  "source_smaa_quality": rows["source-smaa"]["quality"], "bands": {}}
        for radius in RADII:
            mask = (binary_dilation(foreground, iterations=radius)
                    & ~binary_erosion(foreground, iterations=radius))
            corrected = np.where(mask, ref, candidate)
            saved = np.sum((candidate[mask].astype(np.float64) - ref[mask])**2)
            result["bands"][str(radius)] = {"pixel_fraction": float(mask.mean()),
                                            "sse_fraction_removed": float(saved/initial_sse),
                                            "perfect_copy_quality": score(ref, corrected)}
        report["assets"][asset] = result
        print(asset, len(eligible), [round(result["bands"][str(r)]["sse_fraction_removed"], 4)
                                     for r in RADII], flush=True)
        for v, i, _ in meshes.values():
            v.destroy()
            i.destroy()
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
