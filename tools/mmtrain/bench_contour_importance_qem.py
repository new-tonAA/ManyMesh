"""Compare a 64-view contour priority against the same unweighted QEM queue."""

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from preflight_appearance_meshes import audit, boundary, compact, digest, load_obj
from preflight_appearance_meshes import normalize, source_frame
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics, view_basis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmgeo"))
from progressive_geometry_baseline import ProgressiveQEM


def contour_importance(points, faces, count=64):
    """Count views where a vertex touches any apparent contour edge."""
    views = np.arange(count, dtype=float)
    y = 1 - (2 * views + 1) / count
    azimuth = views * np.pi * (3 - np.sqrt(5))
    radius = np.sqrt(1 - y * y)
    directions = np.column_stack((radius * np.cos(azimuth), y,
                                  radius * np.sin(azimuth)))
    edge_faces = {}
    for i, (a, b, c) in enumerate(faces):
        for u, v in ((a, b), (b, c), (c, a)):
            edge_faces.setdefault((min(u, v), max(u, v)), []).append(i)
    shared = [(edge, owners) for edge, owners in edge_faces.items() if len(owners) == 2]
    endpoints = np.array([edge for edge, _ in shared], dtype=int).reshape(-1, 2)
    incidents = np.array([owners for _, owners in shared], dtype=int).reshape(-1, 2)
    a, b, c = points[faces].transpose(1, 0, 2)
    normals = np.cross(b - a, c - a)
    hits = np.zeros(len(points), dtype=int)
    for direction in directions:
        signs = np.sign(normals @ direction)
        contour = signs[incidents[:, 0]] * signs[incidents[:, 1]] < 0
        hits[np.unique(endpoints[contour])] += 1
    return hits.astype(float) / count


class ContourPriorityQEM(ProgressiveQEM):
    def __init__(self, points, faces, importance):
        self.importance = importance.copy()
        super().__init__(points, faces)

    def placement_costs(self, u, v):
        factor = 1 + max(self.importance[u], self.importance[v])
        for cost, index, point in super().placement_costs(u, v):
            yield cost * factor, index, point

    def accept(self, entry):
        _, keep, remove, _, _, _, _ = entry
        self.importance[keep] = max(self.importance[keep], self.importance[remove])
        super().accept(entry)


def compare_images(source, variants):
    rows = []
    yaw = np.deg2rad(13)
    rotation = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0],
                         [-np.sin(yaw), 0, np.cos(yaw)]])
    for scale in (1.0, 0.55):
        for view in range(12):
            camera = rotation @ view_basis(view, 12)
            reference, reference_coverage = render(source[0] * scale, source[1], camera, 192, 2)
            row = {"view": view, "screen_scale": scale}
            for name, (points, faces) in variants.items():
                image, coverage = render(points * scale, faces, camera, 192, 2)
                row[name] = image_metrics(reference, image, reference_coverage, coverage, 67.0)
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.source) != args.sha256:
        parser.error("Input OBJ SHA-256 differs from the frozen source")
    raw, faces = load_obj(args.source)
    center, radius = source_frame(raw)
    points, remap = np.unique(normalize(raw, center, radius), axis=0, return_inverse=True)
    faces = remap[faces]
    reference_edges = boundary(points, faces)
    target = len(faces) - 2 * round(len(faces) / 4)
    start = time.perf_counter()
    importance = contour_importance(points, faces)
    preparation_seconds = time.perf_counter() - start
    result = {
        "source_sha256": args.sha256, "source_faces": len(faces), "target_faces": target,
        "script_sha256": digest(Path(__file__)),
        "qem_script_sha256": digest(Path(sys.modules["progressive_geometry_baseline"].__file__)),
        "precompute_seconds": preparation_seconds, "fitting_views": 64, "lambda": 1,
        "nonzero_importance_vertices": int(np.count_nonzero(importance)),
        "arms": {},
    }
    variants = {}
    for name, create in (
        ("qem", lambda: ProgressiveQEM(points, faces)),
        ("contour_priority", lambda: ContourPriorityQEM(points, faces, importance)),
    ):
        start = time.perf_counter()
        solver = create()
        solver.advance(target)
        geometry = compact(solver.p, solver.f[solver.alive])
        row = audit(reference_edges, *geometry)
        row.update(seconds=time.perf_counter() - start, collapses=len(solver.actions))
        result["arms"][name] = row
        variants[name] = geometry
        print(name, row, flush=True)

    if all(row["faces"] == target and row["boundary_preserved"]
           for row in result["arms"].values()):
        result["views"] = compare_images((points, faces), variants)
    else:
        result["views"] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
