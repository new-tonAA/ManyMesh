"""Rasterize public meshes at two matched LODs for a tile-refinement pilot."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import fast_simplification
from numba import njit
import numpy as np
from PIL import Image
import trimesh

from tile_refinement import TILE_SIZE, tile_mean, tile_features, witness_tiles


@njit
def raster(vertices, triangles, light, size):
    depth = np.full((size, size), np.inf, np.float32)
    color = np.zeros((size, size), np.float32)
    for a, b, c in triangles:
        ax, ay, az = vertices[a]
        bx, by, bz = vertices[b]
        cx, cy, cz = vertices[c]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denominator) < 1e-8:
            continue
        for y in range(max(0, math.ceil(min(ay, by, cy) - 0.5)),
                       min(size, math.floor(max(ay, by, cy) - 0.5) + 1)):
            dy = y + 0.5 - cy
            for x in range(max(0, math.ceil(min(ax, bx, cx) - 0.5)),
                           min(size, math.floor(max(ax, bx, cx) - 0.5) + 1)):
                dx = x + 0.5 - cx
                u = ((by - cy) * dx + (cx - bx) * dy) / denominator
                v = ((cy - ay) * dx + (ax - cx) * dy) / denominator
                w = 1.0 - u - v
                z = u * az + v * bz + w * cz
                if min(u, v, w) >= -1e-7 and z < depth[y, x]:
                    depth[y, x] = z
                    color[y, x] = u * light[a] + v * light[b] + w * light[c]
    return color, depth


def vertex_normals(vertices, faces):
    points = vertices[faces]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    smooth = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(smooth, faces[:, corner], normals)
    smooth /= np.maximum(1e-10, np.linalg.norm(smooth, axis=1, keepdims=True))
    return smooth


def collapse_witnesses(vertices, faces, trace):
    replay_vertices, _, maps = fast_simplification.replay_simplification(
        vertices, faces, trace)
    normals = vertex_normals(vertices, faces)
    valid = maps >= 0
    points = vertices[valid]
    displacement = points - replay_vertices[maps[valid]]
    offset = np.abs(np.sum(displacement * normals[valid], axis=1))
    cell = np.clip(((points + 1.0) * 4).astype(np.int32), 0, 7)
    key = cell @ np.array([64, 8, 1])
    order = np.argsort(-offset, kind="stable")
    _, first = np.unique(key[order], return_index=True)
    best = order[np.sort(first)[:128]]
    return np.column_stack((points[best], offset[best])).astype(np.float32)


def capture(mesh, basis, size):
    vertices, faces, light = mesh
    projected = vertices @ basis
    projected[:, :2] = (projected[:, :2] * 0.45 + 0.5) * size
    return raster(projected, faces, light, size)


def view_basis(index, count):
    yaw = 2 * math.pi * index / count
    elevation = math.radians((-15, 20, 40)[index % 3])
    eye = np.array((math.sin(yaw) * math.cos(elevation),
                    math.sin(elevation), math.cos(yaw) * math.cos(elevation)))
    right = np.cross((0.0, 1.0, 0.0), eye)
    right /= np.linalg.norm(right)
    return np.stack((right, -np.cross(eye, right), -eye), axis=1).astype(np.float32)


def bicubic(color, size):
    image = Image.fromarray(np.rint(color * 255).astype(np.uint8))
    return np.asarray(image.resize((size, size), Image.Resampling.BICUBIC),
                      dtype=np.float32) / 255


def load_geometry(asset_path):
    mesh = trimesh.load_scene(asset_path, skip_materials=True).to_geometry()
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
    faces = np.asarray(mesh.faces, dtype=np.int32)
    if not 100 <= len(faces) <= 200_000:
        raise ValueError(f"Outside pilot triangle range: {asset_path}: {len(faces)}")
    vertices -= (vertices.min(axis=0) + vertices.max(axis=0)) * 0.5
    vertices /= np.linalg.norm(vertices, axis=1).max()
    return vertices, faces


def verify_asset(root, source):
    path = root / source["mesh"]
    for name, expected in source["buffers"].items():
        fingerprint = hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()
        if fingerprint != expected:
            raise ValueError(f"Asset buffer hash mismatch: {path}: {name}")
    return path


def make_pairs(asset_path, views, size):
    vertices, faces = load_geometry(asset_path)
    meshes = []
    light_direction = np.array((0.36, 0.80, 0.48), np.float32)
    for ratio in (1.0, 0.20, 0.45):
        pos, indices = vertices, faces
        if ratio == 0.20:
            pos, indices, trace = fast_simplification.simplify(
                vertices, faces, target_reduction=1-ratio, return_collapses=True)
            witnesses = collapse_witnesses(vertices, faces, trace)
        elif ratio < 1.0:
            pos, indices = fast_simplification.simplify(vertices, faces, target_reduction=1-ratio)
        pos = np.asarray(pos, dtype=np.float32)
        light = 0.20 + 0.75 * np.clip(vertex_normals(pos, indices) @ light_direction, 0.0, 1.0)
        meshes.append((pos, indices, light))
    reference_mesh, coarse, fine = meshes
    samples, coarse_error, fine_error = [], [], []
    for index in range(views):
        basis = view_basis(index, views)
        reference, _ = capture(reference_mesh, basis, 4 * size)
        reference = reference.reshape(size * 2, 2, size * 2, 2).mean(axis=(1, 3))
        color, depth = capture(coarse, basis, size)
        refined, _ = capture(fine, basis, size)
        features = tile_features(color, depth)
        samples.append(np.column_stack((features, witness_tiles(witnesses, basis, depth))))
        coarse_error.append(tile_mean((bicubic(color, 2 * size) - reference) ** 2, TILE_SIZE * 2))
        fine_error.append(tile_mean((bicubic(refined, 2 * size) - reference) ** 2, TILE_SIZE * 2))
        if index == 0:
            example = {"color": color, "depth": depth, "basis": basis, "witnesses": witnesses}
    return {"features": np.stack(samples), "coarse": np.stack(coarse_error),
            "fine": np.stack(fine_error), "triangles": np.array([len(m[1]) for m in meshes]),
            **example}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=12, choices=(6, 12, 24))
    parser.add_argument("--size", type=int, default=96)
    args = parser.parse_args()
    if not 32 <= args.size <= 192 or args.size % TILE_SIZE:
        parser.error("--size must be a multiple of the tile size in [32, 192]")
    assets = json.loads((args.assets / "sources.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    for source in assets:
        asset_path = verify_asset(args.assets, source)
        pairs = make_pairs(asset_path, args.views, args.size)
        np.savez_compressed(args.out / f"{source['name']}.npz", **pairs)
        print(source["name"], pairs["triangles"].tolist(), flush=True)
    manifest = {"sources": assets, "views": args.views, "size": args.size, "outputScale": 2}
    (args.out / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
