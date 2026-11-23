"""Measure geometric boundary deviation when exact boundary-edge sets differ."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))

from audit_target_budget_visibility import load_binary_ply, load_obj
from bench_upstream_clusterlod import boundary, compact


def source_frame(positions):
    center = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    radius = np.linalg.norm(positions - center, axis=1).max()
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Source mesh has invalid scale")
    return center, radius


def normalize(positions, center, radius):
    return ((positions - center) / radius).astype(np.float32).astype(np.float64)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unpack_segments(boundary_edges):
    if not boundary_edges:
        return np.empty((0, 3)), np.empty((0, 3))
    starts = np.asarray([edge[1] for edge in boundary_edges], dtype=np.float64)
    ends = np.asarray([edge[2] for edge in boundary_edges], dtype=np.float64)
    return starts, ends


def sample_segments(starts, ends, max_step):
    samples = []
    lengths = np.linalg.norm(ends - starts, axis=1)
    for start, end, length in zip(starts, ends, lengths):
        count = max(1, int(np.ceil(length / max_step)))
        t = np.linspace(0.0, 1.0, count + 1)[:, None]
        samples.append(start + t * (end - start))
    return np.concatenate(samples, axis=0), lengths


def directed_curve_distance(points, starts, ends, chunk=256):
    if not len(points) or not len(starts):
        raise ValueError("Cannot measure an empty boundary curve")
    vectors = ends - starts
    squared_lengths = np.sum(vectors * vectors, axis=1)
    squared_lengths = np.maximum(squared_lengths, np.finfo(np.float64).tiny)
    nearest = []
    for offset in range(0, len(points), chunk):
        block = points[offset:offset + chunk]
        relative = block[:, None, :] - starts[None, :, :]
        parameter = np.clip(
            np.sum(relative * vectors[None, :, :], axis=2)
            / squared_lengths[None, :], 0.0, 1.0)
        residual = relative - parameter[:, :, None] * vectors[None, :, :]
        nearest.extend(np.sqrt(np.min(np.sum(residual * residual, axis=2), axis=1)))
    distances = np.asarray(nearest)
    return {
        "mean": float(np.mean(distances)),
        "p95": float(np.quantile(distances, 0.95)),
        "max_sampled": float(np.max(distances)),
    }


def measure(reference_edges, candidate_edges, step):
    ref_start, ref_end = unpack_segments(reference_edges)
    out_start, out_end = unpack_segments(candidate_edges)
    ref_vertices = np.unique(np.vstack([ref_start, ref_end]), axis=0)
    out_vertices = np.unique(np.vstack([out_start, out_end]), axis=0)
    exact_shared_vertices = len(
        {tuple(point) for point in ref_vertices}
        & {tuple(point) for point in out_vertices})
    vertex_pair_distance = np.linalg.norm(
        ref_vertices[:, None, :] - out_vertices[None, :, :], axis=2)
    nearest_candidate_vertex = np.argmin(vertex_pair_distance, axis=1)
    nearest_vertex_distance = vertex_pair_distance[
        np.arange(len(ref_vertices)), nearest_candidate_vertex]
    one_to_one_vertex_map = (
        len(ref_vertices) == len(out_vertices)
        and len(np.unique(nearest_candidate_vertex)) == len(ref_vertices))
    approximate_directed_edge_matches = None
    approximate_reversed_edge_matches = None
    if one_to_one_vertex_map:
        ref_index = {tuple(point): i for i, point in enumerate(ref_vertices)}
        out_index = {tuple(point): i for i, point in enumerate(out_vertices)}
        ref_to_out_index = {
            i: int(nearest_candidate_vertex[i]) for i in range(len(ref_vertices))}
        candidate_directed_edges = {
            (edge[0], out_index[edge[1]], out_index[edge[2]])
            for edge in candidate_edges
        }
        approximate_directed_edge_matches = 0
        approximate_reversed_edge_matches = 0
        for cluster, start, end in reference_edges:
            i = ref_to_out_index[ref_index[start]]
            j = ref_to_out_index[ref_index[end]]
            approximate_directed_edge_matches += (cluster, i, j) in candidate_directed_edges
            approximate_reversed_edge_matches += (cluster, j, i) in candidate_directed_edges
    ref_samples, ref_lengths = sample_segments(ref_start, ref_end, step)
    out_samples, out_lengths = sample_segments(out_start, out_end, step)
    ref_to_candidate = directed_curve_distance(ref_samples, out_start, out_end)
    candidate_to_ref = directed_curve_distance(out_samples, ref_start, ref_end)
    return {
        "reference_edge_count": len(ref_start),
        "candidate_edge_count": len(out_start),
        "reference_unique_boundary_vertices": len(ref_vertices),
        "candidate_unique_boundary_vertices": len(out_vertices),
        "exact_shared_boundary_vertices": exact_shared_vertices,
        "nearest_vertex_map_is_one_to_one": one_to_one_vertex_map,
        "max_nearest_boundary_vertex_distance": float(np.max(nearest_vertex_distance)),
        "approximate_directed_edge_matches": approximate_directed_edge_matches,
        "approximate_reversed_edge_matches": approximate_reversed_edge_matches,
        "reference_total_length": float(ref_lengths.sum()),
        "candidate_total_length": float(out_lengths.sum()),
        "relative_length_error": float(
            abs(out_lengths.sum() - ref_lengths.sum()) / max(ref_lengths.sum(), 1e-15)),
        "reference_to_candidate": ref_to_candidate,
        "candidate_to_reference": candidate_to_ref,
        "symmetric_hausdorff_sampled": max(
            ref_to_candidate["max_sampled"], candidate_to_ref["max_sampled"]),
        "sample_spacing": step,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--cut-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ratios", type=float, nargs="+", default=[0.3, 0.5, 0.7])
    parser.add_argument("--step-relative", type=float, default=1e-4,
                        help="Maximum boundary sampling interval as a fraction of source AABB diagonal")
    args = parser.parse_args()

    source_positions, source_faces = load_obj(args.source_obj)
    center, radius = source_frame(source_positions)
    frame_positions = normalize(source_positions, center, radius)
    reference = compact(frame_positions, source_faces)
    reference_edges = boundary(*reference)
    extent = np.linalg.norm(source_positions.max(axis=0) - source_positions.min(axis=0))
    step = extent * args.step_relative / radius

    report = {
        "source_path": str(args.source_obj),
        "source_sha256": digest(args.source_obj),
        "script_sha256": digest(Path(__file__)),
        "sampling": {
            "method": "uniform samples on every boundary segment, maximum spacing relative to source AABB diagonal",
            "step_relative": args.step_relative,
            "normalized_step": step,
            "source_aabb_diagonal": float(extent),
        },
        "source_boundary_edges": len(reference_edges),
        "cuts": [],
    }
    for ratio in args.ratios:
        path = args.cut_dir / f"selected_ratio_{ratio:g}.ply"
        positions, faces = load_binary_ply(path)
        candidate = compact(normalize(positions, center, radius), faces)
        candidate_edges = boundary(*candidate)
        result = measure(reference_edges, candidate_edges, step)
        result.update({
            "requested_ratio": ratio,
            "cut_path": str(path),
            "cut_sha256": digest(path),
            "cut_faces": len(candidate[1]),
            "exact_directed_edge_set_preserved": candidate_edges == reference_edges,
        })
        report["cuts"].append(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"receipt: {args.out}")


if __name__ == "__main__":
    main()
