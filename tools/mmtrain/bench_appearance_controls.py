"""Score hash-pinned equal-face controls under native and 4x MSAA rasterization."""

import argparse
import importlib.metadata
import json
from pathlib import Path

import numpy as np

from bench_bevy_smaa import score
from bench_component_gpu import Offscreen, linear_gray_to_srgb, select_adapter
from bench_contour_priority_aa import bind_camera, upload
from cluster_decoder_surface_quality import surface_metrics
from preflight_appearance_meshes import audit, boundary, digest, load_obj


WIDTH, HEIGHT = 640, 360
DIRECTIONS = 12
DISTANCES = (3.3, 5.2)
ARMS = ("manymesh", "qem_preserve_border", "meshoptimizer_lock_border")
MODES = (("native", None), ("msaa4", "msaa4"))


def camera_eyes():
    for view in range(DIRECTIONS):
        y = 1 - (2 * view + 1) / DIRECTIONS
        angle = 0.37 + view * np.pi * (3 - np.sqrt(5))
        radius = np.sqrt(1 - y * y)
        direction = np.array([radius * np.cos(angle), y, radius * np.sin(angle)])
        for distance in DISTANCES:
            yield view, distance, distance * direction


def load_inputs(directory, receipt, fitted):
    geometries = {}
    for arm in ("reference", *ARMS):
        path = directory / f"{arm}.obj"
        if digest(path) != receipt["obj_exports_sha256"][path.name]:
            raise ValueError(f"Geometry hash differs from the frozen receipt: {path}")
        geometries[arm] = load_obj(path)
    source_boundary = boundary(*geometries["reference"])
    if len(geometries["reference"][1]) != receipt["source_faces"]:
        raise ValueError("The reference does not have the full source face count")
    if fitted:
        initial = geometries["meshoptimizer_lock_border"]
        positions, triangles = load_obj(fitted)
        if positions.shape != initial[0].shape or not np.array_equal(triangles, initial[1]):
            raise ValueError("The fitted mesh changed the initialization indices")
        if boundary(positions, triangles) != boundary(*initial):
            raise ValueError("The fitted mesh changed an open boundary of the initialization")
        geometries["fitted"] = positions, triangles
    for arm, geometry in geometries.items():
        if arm != "reference" and (len(geometry[1]) != receipt["control_target_faces"]
                                   or not audit(source_boundary, *geometry)["boundary_preserved"]):
            raise ValueError(f"Ineligible equal-face geometry: {arm}")
    return geometries


def measure(raster, high, meshes, eye):
    buffers = [bind_camera(raster, eye), bind_camera(high, eye)]
    _, high_image = high.run(meshes["reference"], "msaa4", 1, True)
    merged = high_image.reshape(HEIGHT, 2, WIDTH, 2).mean(axis=(1, 3))
    reference = linear_gray_to_srgb(merged)
    quality = {}
    for name, mesh in meshes.items():
        quality[name] = {}
        for label, mode in MODES:
            _, gray = raster.run(mesh, mode, 1, True)
            image = linear_gray_to_srgb(gray)
            row = score(reference, image)
            row["silhouette_xor_fraction"] = float(np.mean((gray > 0) != (merged > 0)))
            quality[name][label] = row
    for buffer in buffers:
        buffer.destroy()
    return quality


def summarize(views, meshes):
    result = {}
    for arm in meshes:
        result[arm] = {}
        for label, _ in MODES:
            rows = [view["quality"][arm][label] for view in views]
            values = {key: [row[key] for row in rows] for key in rows[0]}
            mean = {key: float(np.mean(values[key])) for key in values if key != "psnr_db"}
            worst = {key: float(min(values[key]) if key == "ssim" else max(values[key]))
                     for key in mean}
            psnr = [value for value in values["psnr_db"] if value is not None]
            mse = np.mean([0. if value is None else 10**(-value / 10.)
                           for value in values["psnr_db"]])
            mean["psnr_db"] = float(-10 * np.log10(mse)) if mse else None
            worst["psnr_db"] = min(psnr) if psnr else None
            result[arm][label] = {"mean": mean, "worst": worst}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--fitted", type=Path, help="Optional placement-only fit from meshoptimizer")
    parser.add_argument("--adapter", default="Iris(R) Xe")
    parser.add_argument("--backend", default="D3D12")
    parser.add_argument("--allow-software", action="store_true",
                        help="Allow timestamp-capable CPU adapters for quality-only scoring")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_bytes())
    receipt = manifest["assets"][args.asset]["frozen_exports"]
    geometries = load_inputs(args.geometry_dir, receipt, args.fitted)
    adapter = select_adapter(args.adapter, args.backend, args.allow_software)
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = Offscreen(device, WIDTH, HEIGHT, 1, False)
    high = Offscreen(device, WIDTH * 2, HEIGHT * 2, 1, False)
    meshes = {name: upload(device, *geometry) for name, geometry in geometries.items()}
    views = [{"view": view, "distance": distance, "eye": eye.tolist(),
              "quality": measure(raster, high, meshes, eye)}
             for view, distance, eye in camera_eyes()]
    reference = geometries["reference"]
    result = {
        "asset": args.asset, "manifest_sha256": digest(args.manifest),
        "source_sha256": receipt["source_sha256"],
        "fitted_sha256": digest(args.fitted) if args.fitted else None,
        "source_faces": len(reference[1]), "control_faces": receipt["control_target_faces"],
        "adapter": dict(adapter.info), "size": [WIDTH, HEIGHT],
        "packages": {name: importlib.metadata.version(name) for name in (
            "wgpu", "numpy", "scikit-image", "flip-evaluator")},
        "script_sha256": {name: digest(Path(__file__).with_name(name)) for name in (
            Path(__file__).name, "bench_component_gpu.py", "bench_contour_priority_aa.py",
            "bench_bevy_smaa.py", "cluster_decoder_surface_quality.py")},
        "reference": "full source at 2x resolution with 4x MSAA and linear box resolve",
        "surface": {arm: surface_metrics(reference, geometry, 20000, 20261124)
                    for arm, geometry in geometries.items() if arm != "reference"},
        "views": views, "summary": summarize(views, meshes),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
