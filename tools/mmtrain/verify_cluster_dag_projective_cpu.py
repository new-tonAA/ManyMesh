#!/usr/bin/env python3
"""Independently audit a saved cluster-DAG projective-fit preflight."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def image_means(scored):
    views = scored["views"]
    require(len(views) == 24, f"Expected 24 held-out views, found {len(views)}")
    arms = tuple(scored["means"])
    recomputed = {}
    for arm in arms:
        rows = [view["arms"][arm] for view in views]
        mse = float(np.mean([row["mse"] for row in rows]))
        recomputed[arm] = {
            "pooled_mse": mse,
            "pooled_psnr_db": -10.0 * float(np.log10(mse)),
            "mean_ssim": float(np.mean([row["ssim"] for row in rows])),
            "mean_flip": float(np.mean([row["flip"] for row in rows])),
        }
        for key, actual in recomputed[arm].items():
            expected = float(scored["means"][arm][key])
            require(abs(actual - expected) <= max(1e-12, abs(expected) * 1e-10),
                    f"Stored {arm}.{key} does not match the raw view rows")
    return recomputed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()

    from audit_target_budget_visibility import load_obj
    from bench_upstream_clusterlod import compact
    from cluster_decoder import Mesh, topology
    from fit_projective_rgb_cpu import _face_normals
    from preflight_appearance_meshes import audit, boundary
    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame

    result = json.loads(args.result.read_text(encoding="utf-8"))
    require(digest(args.source_obj) == args.source_sha256 == result["source_obj_sha256"],
            "Source OBJ hash mismatch")
    require(digest(args.geometry) == result["geometry_sha256"],
            "Geometry archive hash mismatch")
    require(args.geometry.stat().st_size == result["geometry_archive_bytes"],
            "Geometry archive size mismatch")
    require(result["script_sha256"] == digest(ROOT / "tools/mmtrain/fit_cluster_dag_projective_cpu.py"),
            "Fit script hash mismatch")
    require(result["fit_implementation_sha256"] ==
            digest(ROOT / "tools/mmtrain/fit_projective_rgb_cpu.py"),
            "Fit implementation hash mismatch")

    source_positions, source_faces = load_obj(args.source_obj)
    center, radius = source_frame(source_positions)
    source = compact(normalize(source_positions, center, radius), source_faces)
    source_boundary = boundary(*source)
    with np.load(args.geometry, allow_pickle=False) as data:
        arrays = {name: data[name].copy() for name in data.files}
    required = {
        "source_positions", "source_faces", "manymesh_positions", "manymesh_faces",
        "face_clusters", "cluster_locked_vertices", "manymesh_cluster_fit",
        "manymesh_unclustered_fit", "meshoptimizer_positions", "meshoptimizer_faces",
        "meshoptimizer_fit",
    }
    require(required <= arrays.keys(), "Geometry archive is missing required arrays")
    require(np.array_equal(arrays["source_faces"], source[1]),
            "Stored source topology differs from the pinned source OBJ")
    require(np.allclose(arrays["source_positions"], source[0], rtol=0, atol=1e-7),
            "Stored source positions differ from the pinned source OBJ")

    many_faces = arrays["manymesh_faces"]
    cluster_ids = arrays["face_clusters"]
    many_raw = arrays["manymesh_positions"]
    many_fit = arrays["manymesh_cluster_fit"]
    locked = arrays["cluster_locked_vertices"].astype(bool)
    require(many_raw.shape == many_fit.shape and locked.shape == (len(many_raw),),
            "ManyMesh fitted geometry or lock-mask shape mismatch")
    require(len(many_faces) == int(result["target_faces"]) == 5290,
            "Unexpected ManyMesh face count")
    require(len(arrays["meshoptimizer_faces"]) == 5290,
            "Meshoptimizer control does not match the face budget")
    require(np.array_equal(many_fit[locked], many_raw[locked]),
            "A cluster-locked vertex moved")

    cluster_mesh = Mesh(many_fit, many_faces, cluster_ids).checked()
    recomputed_lock, cluster_boundary, _ = topology(cluster_mesh)
    require(np.array_equal(recomputed_lock, locked), "Cluster lock mask is not reproducible")
    require(len(cluster_boundary) == result["cluster_boundaries"]["directed_edges"],
            "Cluster boundary count mismatch")
    maximum_displacement = float(np.linalg.norm(many_fit - many_raw, axis=1).max())
    require(abs(maximum_displacement - result["max_cluster_fit_displacement"]) < 1e-9,
            "Maximum displacement does not match the geometry archive")
    original_normals = _face_normals(many_raw, many_faces)
    fitted_normals = _face_normals(many_fit, many_faces)
    normal_ratio = float(np.min(np.sum(original_normals * fitted_normals, axis=1) /
                                np.maximum(np.sum(original_normals * original_normals, axis=1),
                                           1e-30)))
    require(abs(normal_ratio - result["minimum_face_normal_dot"]) < 1e-7,
            "Normal-orientation minimum does not match the geometry archive")

    audits = {}
    buffer_sources = {}
    for name, positions, faces in (
            ("manymesh_raw", many_raw, many_faces),
            ("manymesh_cluster_locked", many_fit, many_faces),
            ("manymesh_unclustered_fit", arrays["manymesh_unclustered_fit"], many_faces),
            ("meshoptimizer_raw", arrays["meshoptimizer_positions"],
             arrays["meshoptimizer_faces"]),
            ("meshoptimizer_fit", arrays["meshoptimizer_fit"],
             arrays["meshoptimizer_faces"])):
        audits[name] = audit(source_boundary, positions, faces)
        if name in {"manymesh_raw", "meshoptimizer_raw"}:
            buffer_sources[name] = (positions, faces)
        require(audits[name]["faces"] == 5290 and audits[name]["boundary_preserved"],
                f"{name} failed its face-count or source-boundary audit")
        if name.endswith("_fit") or name == "manymesh_cluster_locked":
            initial = (many_raw if name.startswith("manymesh")
                       else arrays["meshoptimizer_positions"])
            candidate_normals = _face_normals(positions, faces)
            reference_normals = _face_normals(initial, faces)
            ratio = np.sum(reference_normals * candidate_normals, axis=1) / np.maximum(
                np.sum(reference_normals * reference_normals, axis=1), 1e-30)
            require(float(ratio.min()) >= 0.20 - 1e-6,
                    f"{name} violated the fitted face-normal floor")

    means = image_means(result["heldout"]["means_and_per_view"])
    require(len(result["heldout"]["means_and_per_view"]["views"]) == 24,
            "Held-out rows missing")
    for name, raw_name in (("manymesh", "manymesh_raw"),
                           ("meshoptimizer", "meshoptimizer_raw")):
        positions, faces = buffer_sources[raw_name]
        position_bytes = int(np.asarray(positions, dtype=np.float32).nbytes)
        index_bytes = int(np.asarray(faces, dtype=np.uint32).nbytes)
        stored = result["geometry_buffer_bytes"][name]
        require(stored["vertices"] == len(positions) and stored["faces"] == len(faces)
                and stored["position_float32_bytes"] == position_bytes
                and stored["triangle_uint32_bytes"] == index_bytes
                and stored["position_and_index_bytes"] == position_bytes + index_bytes,
                f"{name} raw position/index byte accounting mismatch")
    accepted_steps = sum(row["halvings"] is not None
                         for row in result["training"]["traces"]["manymesh_cluster_locked"])
    gate = (
        accepted_steps > 0 and np.array_equal(many_fit[locked], many_raw[locked])
        and maximum_displacement <= 0.012 + 1e-9 and normal_ratio >= 0.20 - 1e-6
        and all(row["faces"] == 5290 and row["boundary_preserved"]
                for row in audits.values())
        and means["manymesh_cluster_locked"]["mean_flip"]
            < means["meshoptimizer_raw"]["mean_flip"]
        and means["manymesh_cluster_locked"]["mean_flip"]
            < means["meshoptimizer_fit"]["mean_flip"]
        and means["manymesh_cluster_locked"]["pooled_psnr_db"]
            >= means["meshoptimizer_fit"]["pooled_psnr_db"] - 0.10
        and means["manymesh_cluster_locked"]["mean_ssim"]
            >= means["meshoptimizer_fit"]["mean_ssim"] - 0.001)
    expected_decision = ("advance to a separately frozen multi-asset study" if gate
                         else "close this single-cut CPU fitting configuration")
    require(result["decision"] == expected_decision,
            "Recorded decision does not follow the frozen gate")
    print(json.dumps({
        "status": "passed",
        "heldout_views": 24,
        "face_count": 5290,
        "cluster_count": int(len(np.unique(cluster_ids))),
        "locked_vertices": int(locked.sum()),
        "locked_vertices_unchanged": True,
        "maximum_displacement": maximum_displacement,
        "minimum_normal_dot_ratio": normal_ratio,
        "audits": audits,
        "heldout_means": means,
        "frozen_decision": result["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
