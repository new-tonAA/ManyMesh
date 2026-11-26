#!/usr/bin/env python3
"""Screen CPU image fitting on a face-matched ManyMesh DAG cut."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import tempfile
import time
import resource

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def face_key(points):
    return tuple(sorted(tuple(float(component) for component in point)
                        for point in np.asarray(points, dtype=np.float32)))


def read_labeled_cut(candidate_dir, source_obj_positions, source_obj_faces):
    import sys
    sys.path.insert(0, str(ROOT / "tools/mmgeo"))
    sys.path.insert(0, str(ROOT / "tools/mmtrain"))
    from audit_mixed_group_cut_geometry import read_mmb
    from bench_stream_rate_distortion_pilot import load_binary_xyz_ply
    from cluster_decoder import Mesh, topology

    graph_path = candidate_dir / "lod_graph.mmb"
    graph_json_path = candidate_dir / "lod_graph.json"
    full_json_path = candidate_dir / "full/lod_graph.json"
    full_ply_path = candidate_dir / "full/selected.ply"
    candidate_ply_path = candidate_dir / "selected.ply"
    graph_json = json.loads(graph_json_path.read_text(encoding="utf-8"))
    full_json = json.loads(full_json_path.read_text(encoding="utf-8"))
    node_count = int(graph_json["nodes"])
    graph = read_mmb(graph_path, range(node_count))
    full_positions, full_faces = load_binary_xyz_ply(full_ply_path)

    from scipy.spatial import cKDTree
    distance, full_to_source = cKDTree(source_obj_positions).query(full_positions, k=1)
    if (float(distance.max()) > 1e-5 or len(np.unique(full_to_source)) != len(source_obj_positions)
            or len(full_positions) != len(source_obj_positions)):
        raise ValueError("The full-detail mapping PLY does not bijectively match the source OBJ")
    source_face_set = {tuple(sorted(map(int, face))) for face in source_obj_faces}
    mapped_face_set = {
        tuple(sorted(map(int, full_to_source[face]))) for face in full_faces
    }
    if len(source_face_set) != len(source_obj_faces) or mapped_face_set != source_face_set:
        raise ValueError("The full-detail mapping PLY topology differs from the source OBJ")
    source_mapping_record = {
        "source_vertices": int(len(source_obj_positions)),
        "full_detail_vertices": int(len(full_positions)),
        "bijection": True,
        "max_coordinate_delta": float(distance.max()),
        "source_faces": int(len(source_obj_faces)),
        "full_detail_faces": int(len(full_faces)),
        "face_index_sets_equal_after_vertex_map": True,
    }

    # `source.obj` vertex order is not the order used by the mmgeo importer.
    # The full selected PLY preserves MMLG leaf triangle order, which gives an
    # unambiguous source-index to full-PLY-index map.
    source_to_full = {}
    face_cursor = 0
    for node_id in full_json["selectedNodes"]:
        node_faces = np.asarray(graph["nodes"][int(node_id)]["indices"],
                                dtype=np.int64).reshape(-1, 3)
        ply_faces = full_faces[face_cursor:face_cursor + len(node_faces)]
        if len(ply_faces) != len(node_faces):
            raise ValueError("Full-detail PLY is shorter than the MMLG leaf faces")
        for global_face, ply_face in zip(node_faces, ply_faces, strict=True):
            for global_id, ply_id in zip(global_face, ply_face, strict=True):
                global_id, ply_id = int(global_id), int(ply_id)
                previous = source_to_full.setdefault(global_id, ply_id)
                if previous != ply_id:
                    raise ValueError(f"Inconsistent full-detail vertex mapping for {global_id}")
        face_cursor += len(node_faces)
    if face_cursor != len(full_faces):
        raise ValueError("Full-detail MMLG and PLY face counts differ")
    source_count = int(graph["sourceCount"])
    if len(source_to_full) != source_count:
        raise ValueError("Full-detail cut did not map every MMLG source vertex")

    global_positions = {
        vertex: full_positions[ply_vertex]
        for vertex, ply_vertex in source_to_full.items()
    }
    for index, generated in enumerate(graph["generated"]):
        global_positions[source_count + index] = np.asarray(generated[0], dtype=np.float32)

    candidate_positions, candidate_faces = load_binary_xyz_ply(candidate_ply_path)
    candidate_face_lookup = {}
    for face_id, face in enumerate(candidate_faces):
        key = face_key(candidate_positions[face])
        if key in candidate_face_lookup:
            raise ValueError("Candidate PLY has duplicate geometric faces")
        candidate_face_lookup[key] = face_id

    selected_nodes = sorted(map(int, graph_json["selectedNodes"]))
    face_clusters = np.full(len(candidate_faces), -1, dtype=np.int64)
    node_face_counts = {}
    source_faces = 0
    for cluster_id, node_id in enumerate(selected_nodes):
        node_faces = np.asarray(graph["nodes"][node_id]["indices"],
                                dtype=np.int64).reshape(-1, 3)
        node_face_counts[str(node_id)] = int(len(node_faces))
        source_faces += len(node_faces)
        for face in node_faces:
            try:
                key = face_key([global_positions[int(vertex)] for vertex in face])
            except KeyError as error:
                raise ValueError(f"MMLG references unmapped position {error.args[0]}") from error
            face_id = candidate_face_lookup.get(key)
            if face_id is None or face_clusters[face_id] >= 0:
                raise ValueError("Selected MMLG face did not map one-to-one to the candidate PLY")
            face_clusters[face_id] = cluster_id
    if source_faces != len(candidate_faces) or np.any(face_clusters < 0):
        raise ValueError("The selected MMLG nodes and candidate PLY do not match exactly")

    mesh = Mesh(candidate_positions, candidate_faces, face_clusters).checked()
    locked, cluster_boundary, _ = topology(mesh)
    return (candidate_positions, candidate_faces, face_clusters, locked,
            {"node_count": len(selected_nodes), "node_ids": selected_nodes,
             "node_face_counts": node_face_counts,
             "mmlg_faces": source_faces, "ply_faces": int(len(candidate_faces)),
             "candidate_vertices": int(len(candidate_positions)),
             "cluster_boundary_directed_edges": len(cluster_boundary),
             "cluster_locked_vertices": int(np.count_nonzero(locked)),
             "source_vertices_mapped": len(source_to_full),
             "source_vertex_count": source_count,
             "source_to_full_detail_audit": source_mapping_record})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import drjit as dr
    import mitsuba as mi
    mi.set_variant("llvm_ad_rgb")
    dr.set_thread_count(2)

    import sys
    sys.path.insert(0, str(ROOT / "tools/mmgeo"))
    sys.path.insert(0, str(ROOT / "tools/mmtrain"))
    from audit_target_budget_visibility import load_obj
    from bench_upstream_clusterlod import compact
    from cluster_decoder import Mesh, topology
    from cluster_decoder_surface_quality import surface_metrics
    from compare_qem_meshopt_validation_70pct import meshopt_simplify_raw
    from fit_projective_rgb_cpu import (ITERATIONS, MAX_DISPLACEMENT, MAX_STEP,
                                        SCORE_SPP, SEED, SIZE, TRAIN_SPP,
                                        camera_sets, fit, score)
    from preflight_appearance_meshes import audit, boundary
    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame

    if digest(args.source_obj) != args.source_sha256:
        parser.error("Source OBJ hash differs from the frozen Thingi10K input")
    source_obj_positions, source_obj_faces = load_obj(args.source_obj)
    positions, faces, face_clusters, cluster_locked, cluster_record = read_labeled_cut(
        args.candidate_dir, source_obj_positions, source_obj_faces)
    center, radius = source_frame(source_obj_positions)
    source = compact(normalize(source_obj_positions, center, radius), source_obj_faces)
    initial_manymesh = (normalize(positions, center, radius), faces)
    cluster_mesh = Mesh(initial_manymesh[0], faces, face_clusters).checked()
    cluster_locked, cluster_boundary, _ = topology(cluster_mesh)
    reference_edges = boundary(*source)
    target_faces = len(faces)
    initial_audit = audit(reference_edges, *initial_manymesh)
    if initial_audit["faces"] != target_faces or not initial_audit["boundary_preserved"]:
        raise ValueError(f"ManyMesh cut failed the source-boundary gate: {initial_audit}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    meshopt_positions, meshopt_faces, simplify_record = meshopt_simplify_raw(
        source[0], source[1], target_faces, args.out.parent)
    simplify_seconds = time.perf_counter() - start
    meshopt_audit = audit(reference_edges, meshopt_positions, meshopt_faces)
    if meshopt_audit["faces"] != target_faces or not meshopt_audit["boundary_preserved"]:
        raise ValueError(f"Exact-face meshoptimizer control is ineligible: {meshopt_audit}")

    training_views, heldout_views = camera_sets()
    mi.set_variant("llvm_ad_rgb")
    traces = {}
    fitted = {}
    fit_seconds = {}
    with tempfile.TemporaryDirectory(prefix="mm-cluster-projective-") as temporary:
        work = Path(temporary)
        for name, initial, lock_mask in (
                ("manymesh_cluster_locked", initial_manymesh[0], cluster_locked),
                ("manymesh_unclustered_fit", initial_manymesh[0], None),
                ("meshoptimizer_fit", meshopt_positions, None)):
            fit_start = time.perf_counter()
            (work / name).mkdir()
            fitted[name], traces[name] = fit(
                mi, dr, source, initial, faces if name.startswith("manymesh") else meshopt_faces,
                training_views, work / name, locked_vertices=lock_mask)
            fit_seconds[name] = time.perf_counter() - fit_start

        variants = {
            "source": source,
            "manymesh_raw": initial_manymesh,
            "manymesh_cluster_locked": (fitted["manymesh_cluster_locked"], faces),
            "manymesh_unclustered_fit": (fitted["manymesh_unclustered_fit"], faces),
            "meshoptimizer_raw": (meshopt_positions, meshopt_faces),
            "meshoptimizer_fit": (fitted["meshoptimizer_fit"], meshopt_faces),
        }
        scored = score(mi, variants, heldout_views, work / "score")

    fit_audits = {name: audit(reference_edges, *mesh)
                  for name, mesh in variants.items() if name != "source"}
    cluster_fit = fitted["manymesh_cluster_locked"]
    exact_locked = np.array_equal(cluster_fit[cluster_locked],
                                  initial_manymesh[0][cluster_locked])
    max_displacement = float(np.linalg.norm(cluster_fit - initial_manymesh[0], axis=1).max())
    points0 = initial_manymesh[0][faces]
    points1 = cluster_fit[faces]
    normals0 = np.cross(points0[:, 1] - points0[:, 0], points0[:, 2] - points0[:, 0])
    normals1 = np.cross(points1[:, 1] - points1[:, 0], points1[:, 2] - points1[:, 0])
    normal_dot_min = float(np.min(np.sum(normals0 * normals1, axis=1) /
                                  np.maximum(np.sum(normals0 * normals0, axis=1), 1e-30)))
    means = scored["means"]
    gate = (
        sum(row["halvings"] is not None for row in traces["manymesh_cluster_locked"]) > 0
        and exact_locked
        and max_displacement <= MAX_DISPLACEMENT + 1e-9
        and normal_dot_min >= 0.20 - 1e-6
        and all(record["faces"] == target_faces and record["boundary_preserved"]
                for record in fit_audits.values())
        and means["manymesh_cluster_locked"]["mean_flip"]
            < means["meshoptimizer_raw"]["mean_flip"]
        and means["manymesh_cluster_locked"]["mean_flip"]
            < means["meshoptimizer_fit"]["mean_flip"]
        and means["manymesh_cluster_locked"]["pooled_psnr_db"]
            >= means["meshoptimizer_fit"]["pooled_psnr_db"] - 0.10
        and means["manymesh_cluster_locked"]["mean_ssim"]
            >= means["meshoptimizer_fit"]["mean_ssim"] - 0.001)

    geometry_path = args.out.with_suffix(".geometry.npz")
    with geometry_path.open("wb") as stream:
        np.savez_compressed(
            stream, source_positions=source[0], source_faces=source[1],
            manymesh_positions=initial_manymesh[0], manymesh_faces=faces,
            face_clusters=face_clusters, cluster_locked_vertices=cluster_locked,
            manymesh_cluster_fit=fitted["manymesh_cluster_locked"],
            manymesh_unclustered_fit=fitted["manymesh_unclustered_fit"],
            meshoptimizer_positions=meshopt_positions, meshoptimizer_faces=meshopt_faces,
            meshoptimizer_fit=fitted["meshoptimizer_fit"])
    geometry_buffer_bytes = {}
    for name, vertex_positions, triangle_indices in (
            ("manymesh", initial_manymesh[0], faces),
            ("meshoptimizer", meshopt_positions, meshopt_faces)):
        position_bytes = int(np.asarray(vertex_positions, dtype=np.float32).nbytes)
        index_bytes = int(np.asarray(triangle_indices, dtype=np.uint32).nbytes)
        geometry_buffer_bytes[name] = {
            "vertices": int(len(vertex_positions)), "faces": int(len(triangle_indices)),
            "position_float32_bytes": position_bytes,
            "triangle_uint32_bytes": index_bytes,
            "position_and_index_bytes": position_bytes + index_bytes,
            "excludes_normals_uvs_materials_and_container_headers": True,
        }
    result = {
        "status": "completed",
        "scope": "single reused Thingi10K train asset; selected-cut feasibility only",
        "asset_id": 84736,
        "license": "Creative Commons Attribution",
        "source_obj_sha256": args.source_sha256,
        "source_obj_vertices": int(len(source_obj_positions)),
        "source_obj_faces": int(len(source_obj_faces)),
        "full_detail_mapping_ply_sha256": digest(args.candidate_dir / "full/selected.ply"),
        "candidate_ply_sha256": digest(args.candidate_dir / "selected.ply"),
        "mmlg_sha256": digest(args.candidate_dir / "lod_graph.mmb"),
        "candidate_graph_json_sha256": digest(args.candidate_dir / "lod_graph.json"),
        "full_graph_json_sha256": digest(args.candidate_dir / "full/lod_graph.json"),
        "script_sha256": digest(Path(__file__)),
        "fit_implementation_sha256": digest(ROOT / "tools/mmtrain/fit_projective_rgb_cpu.py"),
        "geometry_sha256": digest(geometry_path),
        "geometry_archive_bytes": int(geometry_path.stat().st_size),
        "geometry_buffer_bytes": geometry_buffer_bytes,
        "target_faces": target_faces,
        "cluster_reconstruction": cluster_record,
        "cluster_boundaries": {"directed_edges": len(cluster_boundary),
                               "locked_vertices": int(cluster_locked.sum()),
                               "locked_vertices_unchanged": exact_locked},
        "meshoptimizer_simplifier": {key: value for key, value in simplify_record.items()
                                      if key not in {"positions", "vertices", "indices"}},
        "meshoptimizer_simplification_seconds": simplify_seconds,
        "audits": fit_audits,
        "max_cluster_fit_displacement": max_displacement,
        "minimum_face_normal_dot": normal_dot_min,
        "training": {"loss": "unweighted full-frame linear-RGB MSE",
                     "integrator": "Mitsuba direct_projective",
                     "variant": mi.variant(), "resolution": [SIZE, SIZE],
                     "spp": TRAIN_SPP, "iterations_max": ITERATIONS,
                     "max_step": MAX_STEP, "max_displacement": MAX_DISPLACEMENT,
                     "camera_count": len(training_views), "fit_seconds": fit_seconds,
                     "traces": traces},
        "heldout": {"view_count": len(heldout_views), "resolution": [SIZE, SIZE],
                    "spp": SCORE_SPP, "means_and_per_view": scored},
        "surface": {name: surface_metrics(source, mesh, 20000, SEED)
                    for name, mesh in variants.items()},
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
        "package_versions": {name: importlib.metadata.version(name) for name in (
            "mitsuba", "drjit", "numpy", "scipy", "scikit-image", "flip-evaluator")},
        "platform": platform.platform(), "python": platform.python_version(),
        "decision": ("advance to a separately frozen multi-asset study" if gate
                     else "close this single-cut CPU fitting configuration"),
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"asset_id": 84736, "decision": result["decision"],
                      "cluster_locked_fit": means["manymesh_cluster_locked"],
                      "meshoptimizer_raw": means["meshoptimizer_raw"],
                      "meshoptimizer_fit": means["meshoptimizer_fit"],
                      "locked_vertices_unchanged": exact_locked,
                      "fit_seconds": fit_seconds}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
