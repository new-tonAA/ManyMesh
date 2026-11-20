"""Audit frozen equal-count meshes on held-out perspective camera paths."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import trimesh
from trimesh.exchange.ply import export_ply

from make_refinement_pairs import load_geometry, raster, verify_asset, vertex_normals
from probe_component_candidates import prepare_anchors, resize
from probe_contour_relocation import FIT_PHASES, FIT_VIEWS, block_mean, measure, targets
from probe_filter_aware_cuts import merge_meshes, shaded

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmtemporal"))
from temporal import camera_basis, reproject_with_depth


PATHS = (
    (-168, -131, 15, 5, 3.0, 3.1),
    (-35, 27, 8, 13, 3.2, 3.1),
    (66, 102, -12, 23, 3.35, 3.0),
)
FOV = 40.0
POLICIES = ("qem", "whole", "parts")


def cameras(path, frames):
    azimuth0, azimuth1, elevation0, elevation1, radius0, radius1 = path
    for t in np.linspace(0, 1, frames):
        azimuth = math.radians(azimuth0 + (azimuth1 - azimuth0) * t)
        elevation = math.radians(elevation0 + (elevation1 - elevation0) * t)
        radius = radius0 + (radius1 - radius0) * t
        direction = np.array([math.sin(azimuth) * math.cos(elevation),
                              math.sin(elevation), math.cos(azimuth) * math.cos(elevation)])
        target = np.array([0.09 * (t - 0.5), 0.07 * math.sin(math.pi * t), 0.0])
        yield {"eye": target + radius * direction, "target": target, "fov": FOV}


def perspective(mesh, camera, size):
    vertices, faces, light = mesh
    right, up, forward = camera_basis(camera["eye"], camera["target"])
    projected = (vertices - camera["eye"]) @ np.stack((right, -up, forward), axis=1)
    if np.any(projected[:, 2] <= 0.05):
        raise ValueError("Camera path crosses the near plane")
    focal = 0.5 * size / math.tan(0.5 * math.radians(camera["fov"]))
    projected[:, :2] = projected[:, :2] / projected[:, 2, None] * focal + 0.5 * size
    return raster(projected.astype(np.float32), faces, light, size, True)


def output_depth(depth):
    side = depth.shape[0] // 2
    samples = depth.reshape(side, 2, side, 2)
    lo, hi = samples.min(axis=(1, 3)), samples.max(axis=(1, 3))
    one_surface = np.isfinite(hi) & (hi <= 1.01 * lo)
    safe_samples = np.where(one_surface[:, None, :, None], samples, 1.0)
    centered = 1.0 / (1.0 / safe_samples).mean(axis=(1, 3))
    return np.where(one_surface, centered, 0.0)


def measure_motion(source, meshes, size, frames):
    results = []
    for path_index, path in enumerate(PATHS):
        previous = None
        for step, camera in enumerate(cameras(path, frames)):
            reference, depth = perspective(source, camera, 4 * size)
            target = block_mean(reference)
            alpha = block_mean(np.isfinite(depth))
            center_depth = output_depth(depth)
            colors, coverage = [], []
            for name in POLICIES:
                low, coarse_depth = perspective(meshes[name], camera, size)
                colors.append(resize(low) - target)
                mask = np.isfinite(coarse_depth)
                coverage.append(np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1) - alpha)
            colors = np.stack(colors, axis=2)
            coverage = np.stack(coverage, axis=2)
            row = {"path": path_index, "frame": step,
                   "colorMse": np.square(colors, dtype=np.float64).mean(axis=(0, 1)).tolist(),
                   "coverageMse": np.square(coverage, dtype=np.float64).mean(axis=(0, 1)).tolist()}
            if previous:
                old_color, old_coverage, old_depth, old_camera = previous
                warped, accept, _ = reproject_with_depth(
                    old_color, old_depth, center_depth, old_camera, camera, 0.01, "taps")
                row["validSurfacePixels"] = int(np.count_nonzero(accept))
                row["referenceSurfacePixels"] = int(np.count_nonzero(center_depth))
                row["warpedColorChangeSse"] = np.square(
                    (colors - warped)[accept], dtype=np.float64).sum(axis=0).tolist()
                # This screen-space measure includes the boundary that the depth warp excludes.
                row["coverageChangeMse"] = np.square(
                    coverage - old_coverage, dtype=np.float64).mean(axis=(0, 1)).tolist()
            previous = colors, coverage, center_depth, camera
            results.append(row)
    return results


def export_mesh(mesh, path):
    vertices, faces, _ = mesh
    data = trimesh.Trimesh(vertices=vertices, faces=faces,
                          vertex_normals=vertex_normals(vertices, faces), process=False)
    binary = export_ply(data, vertex_normal=True)
    path.write_bytes(binary)
    return {"faces": len(faces), "vertices": len(vertices),
            "sha256": hashlib.sha256(binary).hexdigest()}


def experiment(asset_path, whole, selected, size, fit_size, frames, mesh_directory):
    vertices, indices = load_geometry(asset_path)
    source = shaded(vertices, indices)
    qem, global_choice, _, fixed, options = prepare_anchors(vertices, indices, whole, True)
    if [list(p) for p in options] != selected["partOptions"] or whole["selected"] != selected["wholeChoice"]:
        raise ValueError("Replayed mesh option pool differs from the frozen fit")
    parts = merge_meshes([fixed, *(p[n] for p, n in zip(options, selected["choices"], strict=True))])
    meshes = {"qem": qem, "whole": global_choice, "parts": parts}
    fit = targets(source, fit_size, FIT_VIEWS, FIT_PHASES)
    for name, mesh in meshes.items():
        if (len(mesh[1]) != selected["faces"]
                or not np.allclose(measure(mesh, fit_size, fit), selected["fit"][name],
                                   rtol=0, atol=1e-12)):
            raise ValueError(f"Replayed {name} mesh differs from the frozen fit")
    del fit
    exports = {}
    if mesh_directory is not None:
        mesh_directory.mkdir(parents=True, exist_ok=True)
        for name, mesh in {"source": source, **meshes}.items():
            exports[name] = export_mesh(mesh, mesh_directory / f"{name}.ply")
    return {"faces": selected["faces"], "exports": exports,
            "frames": measure_motion(source, meshes, size, frames)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_roots", type=Path, nargs="+")
    parser.add_argument("--whole-reference", type=Path, required=True)
    parser.add_argument("--component-reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mesh-out", type=Path)
    parser.add_argument("--size", type=int, choices=(64, 96, 128), default=96)
    parser.add_argument("--frames", type=int, choices=(8, 12, 24), default=12)
    args = parser.parse_args()
    whole = json.loads(args.whole_reference.read_text(encoding="utf-8"))
    component = json.loads(args.component_reference.read_text(encoding="utf-8"))
    if component["anchor"] != "selected" or component["size"] != whole["size"]:
        parser.error("Expected a matched pair of whole and selected-anchor reports")
    assets = {}
    for root in args.asset_roots:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for source in sources:
            name = source["name"]
            frozen = component["assets"].get(name)
            comparator = whole["assets"].get(name)
            if (name in assets or frozen is None or comparator is None
                    or source != frozen["source"] or source != comparator["source"]):
                parser.error(f"Unmatched or duplicate asset {name}")
            directory = args.mesh_out / name if args.mesh_out else None
            assets[name] = experiment(verify_asset(root, source), comparator, frozen, args.size,
                                      component["size"], args.frames, directory)
            print(f"{name}: {assets[name]['faces']} triangles, {len(assets[name]['frames'])} frames",
                  flush=True)
    metadata = {"size": args.size, "outputScale": 2, "fov": FOV, "paths": PATHS,
                "framesPerPath": args.frames, "policies": POLICIES, "assets": assets}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
