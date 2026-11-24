#!/usr/bin/env python3
"""Measure deterministic sampled surface and normal error for a frozen cut."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_component_gpu import load_export  # noqa: E402


SAMPLE_COUNT = 4096
SAMPLE_SEED = 20261125
QUERY_BATCH = 256


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def nearest_surface(mesh: trimesh.Trimesh, points: np.ndarray):
    closest_parts, distance_parts, face_parts = [], [], []
    for start in range(0, len(points), QUERY_BATCH):
        closest, distances, face_ids = trimesh.proximity.closest_point_naive(
            mesh, points[start:start + QUERY_BATCH]
        )
        closest_parts.append(closest)
        distance_parts.append(distances)
        face_parts.append(face_ids)
    return (np.concatenate(closest_parts), np.concatenate(distance_parts),
            np.concatenate(face_parts))


def summarize_distances(values: np.ndarray, scale: float) -> dict[str, float]:
    normalized = values / scale
    return {
        "mean": float(normalized.mean()),
        "median": float(np.median(normalized)),
        "p95": float(np.percentile(normalized, 95)),
        "p99": float(np.percentile(normalized, 99)),
        "max_sampled": float(normalized.max()),
    }


def compare(source: trimesh.Trimesh, candidate: trimesh.Trimesh,
            seed: int, count: int, scale: float) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    rows = {}
    for name, origin, target in (
        ("source_to_cluster2", source, candidate),
        ("cluster2_to_source", candidate, source),
    ):
        points, source_faces = trimesh.sample.sample_surface(
            origin, count, seed=int(rng.integers(0, 2**32, dtype=np.uint32))
        )
        _, distances, target_faces = nearest_surface(target, points)
        dot = np.einsum(
            "ij,ij->i", origin.face_normals[source_faces],
            target.face_normals[target_faces]
        )
        angles = np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))
        rows[name] = {
            "sample_count": count,
            "distance_over_source_bbox_diagonal": summarize_distances(distances, scale),
            "normal_angle_degrees": {
                "mean": float(angles.mean()),
                "median": float(np.median(angles)),
                "p95": float(np.percentile(angles, 95)),
                "p99": float(np.percentile(angles, 99)),
            },
        }
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--meshes", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    stock_path = args.stock / "cluster-cuts.json"
    stock_bytes = stock_path.read_bytes()
    stock = json.loads(stock_bytes)
    if stock["manifest_sha256"] != sha256(manifest_bytes):
        raise ValueError("Stock cut manifest does not match the geometry manifest")
    if args.asset not in manifest["assets"] or args.asset not in stock["assets"]:
        raise ValueError(f"Asset is missing from a frozen manifest: {args.asset}")

    spec = manifest["assets"][args.asset]["exports"]["source"]
    source_path = args.meshes / args.asset / "source.ply"
    vertex_data, source_indices = load_export(source_path, spec)
    positions = vertex_data.reshape(-1, 6)[:, :3]
    welded_positions, vertex_map = np.unique(
        positions, axis=0, return_inverse=True
    )
    source_faces = vertex_map[source_indices.reshape(-1, 3)]

    cut_info = stock["assets"][args.asset]["cuts"]["cluster2"]
    cut_path = args.stock / args.asset / "cluster-depth2.npy"
    cut_bytes = cut_path.read_bytes()
    if sha256(cut_bytes) != cut_info["sha256"]:
        raise ValueError("Cluster cut bytes do not match the frozen stock manifest")
    cut_indices = np.load(cut_path, allow_pickle=False)
    if (cut_indices.dtype != np.uint32
            or cut_indices.shape != (3 * cut_info["count"],)
            or cut_indices.max() >= len(vertex_map)):
        raise ValueError("Cluster cut has an invalid dtype, count, or vertex index")
    cut_faces = vertex_map[cut_indices.reshape(-1, 3)]

    source = trimesh.Trimesh(vertices=welded_positions, faces=source_faces,
                             process=False)
    candidate = trimesh.Trimesh(vertices=welded_positions, faces=cut_faces,
                                process=False)
    scale = float(np.linalg.norm(source.bounds[1] - source.bounds[0]))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Source bounding-box diagonal is invalid")
    receipt = {
        "schema": 1,
        "asset": args.asset,
        "trimesh_version": trimesh.__version__,
        "manifest_sha256": sha256(manifest_bytes),
        "stock_manifest_sha256": sha256(stock_bytes),
        "source_mesh_sha256": spec["sha256"],
        "cluster2_indices_sha256": cut_info["sha256"],
        "analysis_script_sha256": sha256(Path(__file__).read_bytes()),
        "mesh_loader_sha256": sha256(
            Path(__file__).with_name("bench_component_gpu.py").read_bytes()
        ),
        "source_faces": len(source_faces),
        "cluster2_faces": len(cut_faces),
        "source_bbox_diagonal": scale,
        "sampling": {
            "distribution": "independent area-weighted surface samples",
            "samples_per_direction": SAMPLE_COUNT,
            "seed": SAMPLE_SEED,
            "nearest_point": "exact closest point to triangles via trimesh.closest_point_naive",
            "query_batch_size": QUERY_BATCH,
        },
        "directions": compare(source, candidate, SAMPLE_SEED, SAMPLE_COUNT, scale),
        "limitations": [
            "Single development asset; samples are not independent asset observations.",
            "Finite random samples do not bound worst-case Hausdorff distance.",
            "Does not evaluate attributes, rendered appearance, or self-intersections.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt["directions"], indent=2))


if __name__ == "__main__":
    main()
