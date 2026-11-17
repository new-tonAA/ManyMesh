#!/usr/bin/env python3
"""Compare saved target-budget cuts with a CPU orthographic coverage/depth raster oracle.

This is a geometry-only, multi-view diagnostic. It is not a shaded image-quality benchmark.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "out/targetbudget-frontier-pilot-20261116"
ASSETS = (2, 4, 8, 16, 32)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_obj(path):
    positions, triangles = [], []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                positions.append(tuple(float(value) for value in parts[1:4]))
            elif parts[0] == "f" and len(parts) >= 4:
                face = []
                for token in parts[1:]:
                    index = int(token.split("/", 1)[0])
                    face.append(index - 1 if index > 0 else len(positions) + index)
                for corner in range(1, len(face) - 1):
                    triangles.append((face[0], face[corner], face[corner + 1]))
    points = np.asarray(positions, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    if not len(points) or not len(faces) or not np.isfinite(points).all():
        raise ValueError(f"invalid or empty OBJ: {path}")
    if faces.min() < 0 or faces.max() >= len(points):
        raise ValueError(f"OBJ face index out of range: {path}")
    return points, faces


def load_binary_ply(path):
    with path.open("rb") as stream:
        header = []
        while True:
            line = stream.readline()
            if not line:
                raise ValueError(f"unterminated PLY header: {path}")
            header.append(line.decode("ascii").strip())
            if header[-1] == "end_header":
                break
        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"expected binary little-endian PLY: {path}")
        vertex_count = next(int(line.split()[2]) for line in header
                if line.startswith("element vertex "))
        face_count = next(int(line.split()[2]) for line in header
                if line.startswith("element face "))
        vertex_properties = []
        in_vertex = False
        for line in header:
            if line.startswith("element "):
                in_vertex = line.startswith("element vertex ")
            elif in_vertex and line.startswith("property "):
                parts = line.split()
                if parts[1] == "list":
                    raise ValueError("list-valued vertex properties are unsupported")
                vertex_properties.append((parts[2], parts[1]))
        expected = [("x", "float"), ("y", "float"), ("z", "float"),
                ("nx", "float"), ("ny", "float"), ("nz", "float"),
                ("s", "float"), ("t", "float")]
        if vertex_properties != expected:
            raise ValueError(f"unexpected PLY vertex schema: {vertex_properties}")
        raw_vertices = stream.read(vertex_count * 32)
        if len(raw_vertices) != vertex_count * 32:
            raise ValueError(f"truncated PLY vertex data: {path}")
        points = np.frombuffer(raw_vertices, dtype="<f4").reshape(vertex_count, 8)[:, :3]
        faces = np.empty((face_count, 3), dtype=np.int64)
        for face_id in range(face_count):
            raw_count = stream.read(1)
            if len(raw_count) != 1 or raw_count[0] != 3:
                raise ValueError(f"non-triangle or truncated face in {path}")
            raw_face = stream.read(20)
            if len(raw_face) != 20:
                raise ValueError(f"truncated PLY face data: {path}")
            a, b, c, _material, _submesh = struct.unpack("<iiiII", raw_face)
            faces[face_id] = (a, b, c)
    if faces.size and (faces.min() < 0 or faces.max() >= vertex_count):
        raise ValueError(f"PLY face index out of range: {path}")
    return points.astype(np.float64), faces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=256,
            help="orthographic image width and height before supersampling")
    parser.add_argument("--scale", type=int, default=2,
            help="supersampling scale before filtering/downsampling")
    parser.add_argument("--sigma", type=float, default=0.9,
            help="Gaussian filter sigma in output-pixel units")
    parser.add_argument("--views", type=int, default=16)
    parser.add_argument("--output", type=Path,
            default=ROOT / "out/targetbudget-frontier-pilot-20261116/visibility_audit.json")
    args = parser.parse_args()
    if args.size <= 0 or args.scale <= 0 or args.views <= 0 or args.sigma <= 0:
        raise ValueError("size, scale, views, and sigma must be positive")

    reference_path = ROOT / "third_party/meshoptimizer/demo/pirate.obj"
    reference_points, reference_faces = load_obj(reference_path)
    if len(reference_faces) != 5010:
        raise ValueError(f"unexpected source triangle count: {len(reference_faces)}")

    module_path = ROOT / "tools/mmgeo/depth_candidate_pilot.py"
    spec = importlib.util.spec_from_file_location("depth_candidate_pilot", module_path)
    raster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(raster)

    groups = {}
    ply_paths = {}
    for group in ASSETS:
        ply_path = PILOT / f"pirate-g{group}" / "selected_ratio_0.55.ply"
        points, faces = load_binary_ply(ply_path)
        if len(faces) != 2756:
            raise ValueError(f"group {group} has {len(faces)} triangles, expected 2756")
        groups[group] = (points, faces)
        ply_paths[group] = ply_path

    angles = np.linspace(0.0, 2.0 * math.pi, args.views, endpoint=False)
    view_rows = {group: [] for group in ASSETS}
    for view_id, angle in enumerate(angles):
        transform = raster.camera(reference_points, float(angle), args.size)
        projected_reference = raster.project(reference_points, transform)
        full_rect = (0, 0, args.size, args.size)
        high_reference, _ = raster.raster(projected_reference, reference_faces,
                np.ones(len(reference_faces), dtype=bool), full_rect, args.scale)
        filtered_reference = raster.filtered(high_reference, args.sigma, args.scale)
        for group in ASSETS:
            points, faces = groups[group]
            projected = raster.project(points, transform)
            high_candidate, _ = raster.raster(projected, faces,
                    np.ones(len(faces), dtype=bool), full_rect, args.scale)
            filtered_candidate = raster.filtered(high_candidate, args.sigma, args.scale)
            delta = filtered_candidate - filtered_reference
            values = raster.metrics(delta)
            raw_coverage_mismatch = np.count_nonzero(
                    high_candidate[..., 0] != high_reference[..., 0])
            sample_count = high_reference.shape[0] * high_reference.shape[1]
            view_rows[group].append({
                "view": view_id,
                "azimuthRadians": float(angle),
                "filteredCoverageSse": values["coverage"],
                "filteredDepthSse": values["depth"],
                "filteredTotalSse": values["total"],
                "rawCoverageMismatchFraction": raw_coverage_mismatch / sample_count,
            })
        print(f"view {view_id + 1}/{args.views} rasterized", flush=True)

    summary = {}
    for group in ASSETS:
        rows = view_rows[group]
        means = {key: float(np.mean([row[key] for row in rows])) for key in (
                "filteredCoverageSse", "filteredDepthSse", "filteredTotalSse",
                "rawCoverageMismatchFraction")}
        means["filteredTotalRmsePerOutputPixel"] = math.sqrt(
                means["filteredTotalSse"] / (args.size * args.size))
        means["worstViewTotalSse"] = max(row["filteredTotalSse"] for row in rows)
        summary[str(group)] = means

    hashes = {
        "sourceObj": sha256(reference_path),
        "rasterOracle": sha256(module_path),
        "analysisScript": sha256(Path(__file__)),
        "lodGraphSource": sha256(ROOT / "libs/manymesh/src/LodGraph.cpp"),
        "mmgeoSource": sha256(ROOT / "tools/mmgeo/src/main.cpp"),
        "mmgeoExecutable": sha256(ROOT / "out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe"),
        "graphs": {str(group): sha256(PILOT / f"pirate-g{group}" / "lod_graph.json")
                for group in ASSETS},
        "cuts": {str(group): sha256(path) for group, path in ply_paths.items()},
    }
    ordered = sorted(ASSETS, key=lambda group: summary[str(group)]["filteredTotalSse"])
    result = {
        "scope": "single-asset full-orbit CPU orthographic raster diagnostic; binary coverage and normalized first-hit depth only; no PBR",
        "warnings": [
            "The raster uses the repository's two-sided supersampled CPU visibility oracle and normalized orthographic camera, not the mmgeo perspective screen-error camera.",
            "This is one Pirate mesh and one resolution/filter setting; it is not a generalization or SIGGRAPH-quality evaluation.",
        ],
        "settings": {"size": args.size, "scale": args.scale, "sigma": args.sigma,
                "views": args.views, "sourceTriangles": len(reference_faces),
                "candidateTriangles": 2756},
        "meanViewMetrics": summary,
        "rankByFilteredTotalSse": ordered,
        "viewsByGroup": {str(group): view_rows[group] for group in ASSETS},
        "hashes": hashes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"meanViewMetrics": summary,
            "rankByFilteredTotalSse": ordered, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
