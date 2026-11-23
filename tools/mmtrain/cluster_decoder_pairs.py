"""Prepare geometry-only QEM/reference residuals without opening test assets.

Nearest-surface labels use a centroid tree with a conservative triangle-radius
search, followed by exact point/triangle projections. Candidate work is capped;
an exhausted cap rejects an asset rather than approximating its labels silently.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.spatial import cKDTree

from cluster_decoder import Mesh, features, topology
from cluster_decoder_pilot import partition_faces, peak_process_bytes, read_stl


def closest_on_triangles(point, triangles):
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    norm2 = np.einsum("ij,ij->i", normal, normal)
    if np.any(norm2 <= 0) or not np.isfinite(norm2).all():
        raise ValueError("Degenerate reference triangle")
    projection = point - (np.sum((point - a) * normal, axis=1) / norm2)[:, None] * normal
    ap = projection - a
    d00 = np.sum(ab * ab, axis=1)
    d01 = np.sum(ab * ac, axis=1)
    d11 = np.sum(ac * ac, axis=1)
    d20 = np.sum(ap * ab, axis=1)
    d21 = np.sum(ap * ac, axis=1)
    # |ab x ac|^2 avoids cancellation in d00*d11-d01*d01 for narrow triangles.
    u = (d11 * d20 - d01 * d21) / norm2
    v = (d00 * d21 - d01 * d20) / norm2
    inside = (u >= 0) & (v >= 0) & (u + v <= 1)
    candidates = [projection]
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        t = np.sum((point - start) * edge, axis=1) / np.sum(edge * edge, axis=1)
        candidates.append(start + np.clip(t, 0, 1)[:, None] * edge)
    candidates = np.stack(candidates, axis=1)
    distances = np.sum((candidates - point) ** 2, axis=2)
    distances[~inside, 0] = np.inf
    best = np.argmin(distances, axis=1)
    return candidates[np.arange(len(triangles)), best], distances[np.arange(len(triangles)), best]


def nearest_surface(points, triangles, max_candidates=20_000_000, stats=None):
    points = np.asarray(points, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise ValueError("Invalid query/reference shape")
    if not np.isfinite(points).all() or not np.isfinite(triangles).all() or not len(triangles):
        raise ValueError("Empty or nonfinite reference/query")
    centers = triangles.mean(axis=1)
    radii = np.linalg.norm(triangles - centers[:, None], axis=2).max(axis=1)
    radius = radii.max()
    tree = cKDTree(centers)
    _, seeds = tree.query(points)
    targets = np.empty_like(points)
    work, bound_checks = 0, 0
    for i, (point, seed) in enumerate(zip(points, seeds)):
        _, distance = closest_on_triangles(point, triangles[int(seed):int(seed)+1])
        # Every point on a triangle lies within its vertex-bounding centroid ball.
        # Thus any triangle closer than the incumbent has its centroid within d+R.
        search = np.nextafter(np.sqrt(distance[0]) + radius, np.inf) + 1e-12
        ids = np.asarray(tree.query_ball_point(point, search), dtype=np.int64)
        bound_checks += len(ids)
        if bound_checks > max_candidates * 4:
            raise ValueError(f"Nearest-surface radius-check cap exceeded: {max_candidates * 4}")
        # A single long triangle can make the global radius loose. Apply each
        # candidate's tighter ball before the more expensive triangle projection.
        distance_to_center = np.linalg.norm(centers[ids] - point, axis=1)
        ids = ids[distance_to_center <= np.sqrt(distance[0]) + radii[ids] + 1e-12]
        work += len(ids) + 1
        if work > max_candidates:
            raise ValueError(f"Nearest-surface candidate cap exceeded: {max_candidates}")
        closest, squared = closest_on_triangles(point, triangles[ids])
        targets[i] = closest[np.argmin(squared)]
    if stats is not None:
        stats.update({"radius_bound_checks": bound_checks})
    return targets, work


def prepare_geometry(source_pos, source_faces, positions, faces, cluster_faces,
                     max_candidates, source_topology_positions=None,
                     source_to_unit_scale=1., started=None, base_method="provided"):
    """Build residual labels for a supplied coarse mesh against a high-detail source."""
    start = time.perf_counter() if started is None else started
    source_pos = np.asarray(source_pos, dtype=np.float64)
    source_faces = np.asarray(source_faces, dtype=np.int64)
    positions = np.asarray(positions, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if source_topology_positions is None:
        source_topology_positions = source_pos
    source_topology_positions = np.asarray(source_topology_positions, dtype=np.float64)
    source = Mesh(source_topology_positions, source_faces,
                  np.zeros(len(source_faces), dtype=np.int64)).checked()
    coarse = Mesh(positions, faces, np.zeros(len(faces), dtype=np.int64)).checked()
    if topology(coarse)[1] != topology(source)[1]:
        raise ValueError("Coarse mesh changed source boundary positions or edges")
    groups = partition_faces(faces, cluster_faces)
    coarse = Mesh(positions, faces, groups).checked()
    locked = topology(coarse)[0]
    free = np.flatnonzero(~locked)
    owner = np.full(len(positions), -1, dtype=np.int64)
    for face, cluster in zip(faces, groups):
        owner[face] = cluster  # Any shared vertex is locked and excluded below.
    queries = np.concatenate((positions[free], positions[faces].mean(axis=1)))
    query_groups = np.concatenate((owner[free], groups))
    stats = {}
    targets, work = nearest_surface(queries, source_pos[source_faces], max_candidates, stats)
    basis = np.empty((len(queries), 10), dtype=np.float64)
    offsets = np.empty_like(queries)
    for cluster in range(int(groups.max()) + 1):
        ids = np.unique(faces[groups == cluster])
        local = positions[ids]
        center = (local.min(axis=0) + local.max(axis=0)) * 0.5
        radius = np.linalg.norm(local - center, axis=1).max()
        mask = query_groups == cluster
        basis[mask] = features((queries[mask] - center) / radius)
        offsets[mask] = (targets[mask] - queries[mask]) / radius
    arrays = {"positions": positions, "triangles": faces, "face_clusters": groups,
              "source_positions": source_pos, "source_triangles": source_faces,
              "queries": queries, "targets": targets, "features": basis,
              "offsets": offsets, "query_clusters": query_groups, "free_vertices": free}
    report = {"source_faces": len(source_faces), "coarse_faces": len(faces),
              "clusters": int(groups.max()) + 1, "free_vertices": len(free),
              "queries": len(queries), "closest_triangle_evaluations": work, **stats,
              "prepare_seconds": time.perf_counter() - start,
              "source_to_unit_scale": float(source_to_unit_scale),
              "base_method": base_method,
              "vertex_mse": float(np.mean(np.sum((queries[:len(free)]-targets[:len(free)])**2,
                                                  axis=1))) if len(free) else None,
              "centroid_mse": float(np.mean(np.sum((queries[len(free):]-targets[len(free):])**2,
                                                    axis=1)))}
    return arrays, report


def prepare(path, retention, cluster_faces, max_candidates):
    import fast_simplification

    start = time.perf_counter()
    source_pos, source_faces = read_stl(path)
    origin = (source_pos.min(axis=0) + source_pos.max(axis=0)) * 0.5
    scale = np.linalg.norm(source_pos - origin, axis=1).max()
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid reference scale")
    source_pos = (source_pos - origin) / scale
    positions, faces = fast_simplification.simplify(
        source_pos, source_faces.astype(np.int32), target_count=max(4, int(len(source_faces)*retention)),
        preserve_border=True)
    used, inverse = np.unique(faces, return_inverse=True)
    positions, faces = positions[used], inverse.reshape(-1, 3)
    return prepare_geometry(source_pos, source_faces, positions, faces, cluster_faces,
                            max_candidates, source_to_unit_scale=scale, started=start,
                            base_method="fast_simplification_qem")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation"), default="train")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--retention", type=float, default=.3)
    parser.add_argument("--cluster-faces", type=int, default=128)
    parser.add_argument("--max-candidates", type=int, default=20_000_000)
    parser.add_argument("--max-input-mib", type=float, default=24)
    args = parser.parse_args()
    if (not 0 < args.retention < 1 or min(args.limit, args.cluster_faces, args.max_candidates) < 1
            or not np.isfinite(args.max_input_mib) or args.max_input_mib <= 0):
        parser.error("Invalid preparation budget")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sources = [row for row in manifest["files"] if row["split"] == args.split][:args.limit]
    if not sources:
        raise ValueError("No assets in the requested development split")
    records = []
    for row in sources:
        path = args.manifest.parent / row["path"]
        result = {"source": row}
        try:
            if path.stat().st_size > args.max_input_mib * 1024**2:
                raise ValueError("Input exceeds byte cap")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Input hash mismatch")
            arrays, metrics = prepare(path, args.retention, args.cluster_faces, args.max_candidates)
            if metrics["source_faces"] != row["faces"]:
                raise ValueError("Source face count mismatch")
            target = args.out / f"{row['file_id']}.npz"
            np.savez(target, **arrays)
            result.update({"status": "prepared", "file": target.name,
                           "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), **metrics})
        except ValueError as error:
            result.update({"status": "rejected", "reason": str(error)})
        result["process_peak_bytes"] = peak_process_bytes()
        records.append(result)
        print(f"{args.split} {row['file_id']}: {result['status']} "
              f"{result.get('reason', result.get('queries'))}", flush=True)
        report = {"scope": "Geometry residual preparation; no quality/generalization result",
                  "configuration": vars(args) | {"manifest": str(args.manifest), "out": str(args.out)},
                  "records": records}
        (args.out / "manifest.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
