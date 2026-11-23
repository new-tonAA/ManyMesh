#!/usr/bin/env python3
"""Record a strict welded-edge topology screen for a triangle-only OBJ."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    positions: list[list[float]] = []
    faces: list[list[int]] = []
    with path.open("r", encoding="ascii") as stream:
        for line_number, raw in enumerate(stream, 1):
            parts = raw.split()
            if not parts or parts[0].startswith("#"):
                continue
            if parts[0] == "v":
                if len(parts) != 4:
                    raise ValueError(f"Expected xyz vertex at line {line_number}")
                positions.append([float(value) for value in parts[1:]])
            elif parts[0] == "f":
                if len(parts) != 4:
                    raise ValueError(f"Expected a triangle at line {line_number}")
                indices = [int(token.split("/", 1)[0]) for token in parts[1:]]
                if any(index <= 0 for index in indices):
                    raise ValueError(f"Only positive vertex indices are supported at line {line_number}")
                faces.append([index - 1 for index in indices])
    points = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("OBJ must contain positions and triangle faces")
    if not len(points) or not len(triangles) or triangles.max() >= len(points):
        raise ValueError("OBJ is empty or has an out-of-range index")
    if not np.isfinite(points).all():
        raise ValueError("OBJ positions contain non-finite values")
    return points, triangles


def components(triangles: np.ndarray, vertex_count: int) -> int:
    parent = np.arange(vertex_count, dtype=np.int64)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = int(parent[value])
        return value

    for a, b, c in triangles:
        root = find(int(a))
        for vertex in (int(b), int(c)):
            other = find(vertex)
            if root != other:
                parent[other] = root
    return len({find(int(vertex)) for vertex in np.unique(triangles)})


def audit(path: Path) -> dict[str, object]:
    positions, triangles = read_obj(path)
    exported_vertices = len(positions)
    used = np.unique(triangles)
    unused_vertices = len(positions) - len(used)
    if unused_vertices:
        remap = np.full(len(positions), -1, dtype=np.int64)
        remap[used] = np.arange(len(used), dtype=np.int64)
        positions = positions[used]
        triangles = remap[triangles]

    canonical, inverse = np.unique(positions, axis=0, return_inverse=True)
    welded_faces = inverse[triangles]
    sorted_faces = np.sort(welded_faces, axis=1)
    duplicate_faces = len(sorted_faces) - len(np.unique(sorted_faces, axis=0))
    points = positions[triangles]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    degenerate_faces = int(np.count_nonzero(np.linalg.norm(normals, axis=1) == 0))
    edge_directions: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face in welded_faces:
        for start, end in zip(face, np.roll(face, -1)):
            start, end = int(start), int(end)
            edge = (min(start, end), max(start, end))
            edge_directions.setdefault(edge, []).append((start, end))
    edge_histogram: dict[str, int] = {}
    for incidences in edge_directions.values():
        key = str(len(incidences))
        edge_histogram[key] = edge_histogram.get(key, 0) + 1
    nonmanifold_edges = sum(len(directions) > 2 for directions in edge_directions.values())
    inconsistent_edges = sum(
        len(directions) == 2 and directions[0] == directions[1]
        for directions in edge_directions.values()
    )
    boundary_edges = sum(len(directions) == 1 for directions in edge_directions.values())
    errors = []
    if degenerate_faces:
        errors.append(f"{degenerate_faces} degenerate faces")
    if duplicate_faces:
        errors.append(f"{duplicate_faces} duplicate geometric faces")
    if nonmanifold_edges:
        errors.append(f"{nonmanifold_edges} nonmanifold edges")
    if inconsistent_edges:
        errors.append(f"{inconsistent_edges} inconsistently oriented edges")
    return {
        "schema": 1,
        "input_path": str(path),
        "input_sha256": sha256(path),
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "exported_vertices": exported_vertices,
        "used_vertices": len(positions),
        "unused_exported_vertices": unused_vertices,
        "welded_vertices": len(canonical),
        "triangles": len(triangles),
        "connected_components_by_exact_welded_vertex": components(welded_faces, len(canonical)),
        "boundary_edges": boundary_edges,
        "duplicate_geometric_triangles": duplicate_faces,
        "degenerate_triangles": degenerate_faces,
        "nonmanifold_edges": nonmanifold_edges,
        "inconsistently_oriented_edges": inconsistent_edges,
        "minimum_double_area": float(np.linalg.norm(normals, axis=1).min()),
        "edge_incidence_histogram": edge_histogram,
        "topology_status": "pass" if not errors else "fail",
        "topology_errors": errors,
        "scope": "exact-coordinate welding; static geometry only; does not check semantic correctness, silhouettes, visual quality, or near-coincident seams",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in receipt.items()
                      if key not in {"scope", "input_path", "audit_script_sha256"}}, indent=2))


if __name__ == "__main__":
    main()
