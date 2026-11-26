#!/usr/bin/env python3
"""Jointly fit one shared MMLG position field across several legal DAG cuts."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time

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


def face_key(points):
    return tuple(sorted(tuple(float(c) for c in p)
                        for p in np.asarray(points, dtype=np.float32)))


def read_global_cut(candidate_dir, source_positions, source_faces):
    """Return a legal exported cut indexed by the shared MMLG position IDs."""
    from audit_mixed_group_cut_geometry import read_mmb
    from bench_stream_rate_distortion_pilot import load_binary_xyz_ply
    from fit_cluster_dag_projective_cpu import read_labeled_cut

    result = read_labeled_cut(candidate_dir, source_positions, source_faces)
    candidate_positions, candidate_faces, clusters, local_locked, record = result
    graph_json = json.loads((candidate_dir / "lod_graph.json").read_text(encoding="utf-8"))
    full_json = json.loads((candidate_dir / "full/lod_graph.json").read_text(encoding="utf-8"))
    graph = read_mmb(candidate_dir / "lod_graph.mmb", range(int(graph_json["nodes"])))
    full_positions, full_faces = load_binary_xyz_ply(candidate_dir / "full/selected.ply")

    from scipy.spatial import cKDTree
    distance, full_to_source = cKDTree(source_positions).query(full_positions, k=1)
    if (len(full_positions) != len(source_positions) or
            len(np.unique(full_to_source)) != len(source_positions) or
            float(distance.max()) > 1e-5):
        raise ValueError("Full-detail PLY does not bijectively map to source OBJ vertices")

    source_to_mmlg = {}
    mmlg_to_full_ply = {}
    cursor = 0
    for node_id in full_json["selectedNodes"]:
        node_faces = np.asarray(graph["nodes"][int(node_id)]["indices"],
                                dtype=np.int64).reshape(-1, 3)
        ply_faces = full_faces[cursor:cursor + len(node_faces)]
        if len(ply_faces) != len(node_faces):
            raise ValueError("Full-detail faces do not align with MMLG leaf order")
        for graph_face, ply_face in zip(node_faces, ply_faces, strict=True):
            for global_id, ply_id in zip(graph_face, ply_face, strict=True):
                previous = source_to_mmlg.setdefault(int(global_id), int(full_to_source[ply_id]))
                if previous != int(full_to_source[ply_id]):
                    raise ValueError("Inconsistent source vertex mapping in full-detail leaves")
                full_previous = mmlg_to_full_ply.setdefault(int(global_id), int(ply_id))
                if full_previous != int(ply_id):
                    raise ValueError("Inconsistent full-detail position mapping in MMLG leaves")
        cursor += len(node_faces)
    if cursor != len(full_faces) or len(source_to_mmlg) != int(graph["sourceCount"]):
        raise ValueError("Full-detail MMLG source mapping is incomplete")

    mmlg_positions = {
        global_id: np.asarray(full_positions[mmlg_to_full_ply[global_id]], dtype=np.float32)
        for global_id in source_to_mmlg
    }
    source_count = int(graph["sourceCount"])
    for generated_index, generated in enumerate(graph["generated"]):
        mmlg_positions[source_count + generated_index] = np.asarray(
            generated[0], dtype=np.float32)

    candidate_lookup = {}
    for face_id, face in enumerate(candidate_faces):
        key = face_key(candidate_positions[face])
        if key in candidate_lookup:
            raise ValueError("Candidate PLY contains duplicate geometric faces")
        candidate_lookup[key] = face_id

    candidate_to_global = np.full(len(candidate_positions), -1, dtype=np.int64)
    face_owner = np.full(len(candidate_faces), -1, dtype=np.int64)
    selected_nodes = sorted(map(int, graph_json["selectedNodes"]))
    for cluster_id, node_id in enumerate(selected_nodes):
        node_faces = np.asarray(graph["nodes"][node_id]["indices"],
                                dtype=np.int64).reshape(-1, 3)
        for graph_face in node_faces:
            try:
                key = face_key([mmlg_positions[int(vertex)] for vertex in graph_face])
            except KeyError as error:
                raise ValueError(f"Selected MMLG node has unmapped vertex {error.args[0]}") from error
            face_id = candidate_lookup.get(key)
            if face_id is None or face_owner[face_id] >= 0:
                raise ValueError("Selected MMLG faces do not map one-to-one to candidate PLY")
            face_owner[face_id] = cluster_id
            ply_face = candidate_faces[face_id]
            for global_id in graph_face:
                point_key = tuple(float(c) for c in mmlg_positions[int(global_id)])
                matches = [int(index) for index in ply_face
                           if tuple(float(c) for c in candidate_positions[index]) == point_key]
                if len(matches) != 1:
                    raise ValueError("Cannot uniquely map candidate vertex to its MMLG ID")
                ply_id = matches[0]
                if candidate_to_global[ply_id] not in (-1, int(global_id)):
                    raise ValueError("Candidate vertex aliases different MMLG position IDs")
                candidate_to_global[ply_id] = int(global_id)
    if (np.any(face_owner < 0) or np.any(candidate_to_global < 0) or
            len(candidate_faces) != int(sum(len(graph["nodes"][n]["indices"]) // 3
                                             for n in selected_nodes))):
        raise ValueError("The selected MMLG cut and candidate PLY are not a complete bijection")

    # The existing label mapper's lock mask is based on the same cluster labels.
    if len(local_locked) != len(candidate_positions):
        raise ValueError("Existing cluster-boundary audit returned an invalid mask")
    return {
        "positions": candidate_positions.astype(np.float64),
        "faces": candidate_faces.astype(np.int64),
        "clusters": clusters.astype(np.int64),
        "local_locked": local_locked.astype(bool),
        "global_ids": candidate_to_global,
        "selected_nodes": selected_nodes,
        "node_count": len(selected_nodes),
        "candidate_vertices": len(candidate_positions),
        "face_count": len(candidate_faces),
        "requested_ratio": float(graph_json["targetRatio"]),
        "cluster_boundary_vertices": int(local_locked.sum()),
        "mapping_record": record,
        "mmlg_sha256": digest(candidate_dir / "lod_graph.mmb"),
        "graph_json_sha256": digest(candidate_dir / "lod_graph.json"),
        "candidate_ply_sha256": digest(candidate_dir / "selected.ply"),
        "full_ply_sha256": digest(candidate_dir / "full/selected.ply"),
    }


def fit_joint(mi, dr, source, union_initial, cuts, training_views, work_dir):
    """Optimize one global position vector against all cuts and training views."""
    from scipy.sparse import coo_matrix, diags, eye
    from scipy.sparse.linalg import factorized
    from fit_projective_rgb_cpu import (ITERATIONS, MAX_DISPLACEMENT, MAX_STEP,
                                        SEED, SIZE, TRAIN_SPP, _face_normals,
                                        scene_for, sensor_for)

    work_dir.mkdir(parents=True, exist_ok=True)
    edges = []
    locked = np.zeros(len(union_initial), dtype=bool)
    for cut in cuts:
        local_faces = cut["faces"]
        union_ids = cut["union_ids"]
        local_edges = np.concatenate((local_faces[:, [0, 1]], local_faces[:, [1, 2]],
                                      local_faces[:, [2, 0]]), axis=0)
        edges.append(union_ids[local_edges])
        locked[union_ids[cut["local_locked"]]] = True
        cut["initial_normals"] = _face_normals(union_initial[union_ids], local_faces)
        cut["normal_floor"] = 0.20 * np.einsum(
            "ij,ij->i", cut["initial_normals"], cut["initial_normals"])

    edges = np.unique(np.sort(np.concatenate(edges), axis=1), axis=0)
    a, b = np.concatenate((edges, edges[:, ::-1]), axis=0).T
    adjacency = coo_matrix((np.ones(len(a)), (a, b)),
                           shape=(len(union_initial), len(union_initial))).tocsc()
    laplacian = diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    free = ~locked
    if not free.any():
        raise ValueError("No movable vertices remain after locking all cut boundaries")
    solve = factorized((eye(len(union_initial), format="csc") +
                        4 * laplacian)[free, :][:, free].tocsc())

    target_scene = scene_for(mi, work_dir / "source.ply", *source, differentiable=False)
    sensors = [sensor_for(mi, basis) for basis in training_views]
    references = [dr.detach(mi.render(target_scene, sensor=sensor, seed=SEED + i))
                  for i, sensor in enumerate(sensors)]
    for index, cut in enumerate(cuts):
        scene = scene_for(mi, work_dir / f"manymesh_{index}.ply",
                          union_initial[cut["union_ids"]], cut["faces"],
                          differentiable=True)
        params = mi.traverse(scene)
        params.keep(["shape.vertex_positions"])
        cut["scene"] = scene
        cut["params"] = params

    def loss_and_gradient(points, with_gradient):
        gradient = np.zeros_like(points)
        losses = []
        for cut in cuts:
            local_points = points[cut["union_ids"]]
            parameter = mi.Float(local_points.astype(np.float32).ravel())
            key = "shape.vertex_positions"
            for index, (sensor, reference) in enumerate(zip(sensors, references, strict=True)):
                if with_gradient:
                    dr.enable_grad(parameter)
                cut["params"][key] = parameter
                cut["params"].update()
                image = mi.render(cut["scene"], cut["params"], sensor=sensor,
                                  seed=SEED + index)
                loss = dr.mean(dr.square(image.array - reference.array))
                losses.append(float(loss[0]))
                if with_gradient:
                    dr.backward(loss)
                    local_gradient = dr.grad(parameter).numpy().reshape(-1, 3)
                    np.add.at(gradient, cut["union_ids"], local_gradient)
                    parameter = dr.detach(parameter)
        denominator = len(cuts) * len(sensors)
        return float(np.mean(losses)), gradient / denominator

    initial = union_initial.copy()
    vertices = initial.copy()
    history = []
    for iteration in range(ITERATIONS):
        before, gradient = loss_and_gradient(vertices, True)
        step = np.zeros_like(vertices)
        step[free] = -solve(gradient[free])
        longest = float(np.linalg.norm(step, axis=1).max())
        row = {"iteration": iteration, "before": before, "after": before,
               "gradient_norm": float(np.linalg.norm(gradient[free])), "halvings": None}
        history.append(row)
        if not np.isfinite(longest):
            raise ValueError("Joint projective RGB gradient was nonfinite")
        if longest == 0:
            break
        step *= MAX_STEP / longest
        for attempt in range(7):
            offset = vertices - initial + step * (0.5 ** attempt)
            length = np.linalg.norm(offset, axis=1, keepdims=True)
            offset *= np.minimum(1., MAX_DISPLACEMENT / np.maximum(length, 1e-30))
            candidate = initial + offset
            valid = True
            for cut in cuts:
                normals = _face_normals(candidate[cut["union_ids"]], cut["faces"])
                orientation = np.einsum("ij,ij->i", normals, cut["initial_normals"])
                if np.any(orientation < cut["normal_floor"]):
                    valid = False
                    break
            if not valid:
                continue
            after, _ = loss_and_gradient(candidate, False)
            if after < before - 1e-12:
                vertices = candidate
                row.update(after=after, halvings=attempt)
                break
    return vertices, history, locked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--cut-dir", type=Path, action="append", required=True,
                        help="Repeat for each selected DAG cut, in coarse-to-fine order")
    parser.add_argument("--mmgeo", type=Path,
                        help="Pinned mmgeo executable used to build the DAG cuts")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import drjit as dr
    import mitsuba as mi
    mi.set_variant("llvm_ad_rgb")
    dr.set_thread_count(2)

    from audit_target_budget_visibility import load_obj
    from bench_upstream_clusterlod import compact
    from cluster_decoder import Mesh, topology
    from cluster_decoder_surface_quality import surface_metrics
    from compare_qem_meshopt_validation_70pct import meshopt_simplify_raw, qem_simplify
    from fit_projective_rgb_cpu import (MAX_DISPLACEMENT, SEED, camera_sets, fit,
                                        score)
    from preflight_appearance_meshes import audit, boundary
    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame

    if digest(args.source_obj) != args.source_sha256:
        parser.error("Source OBJ hash differs from the frozen asset")
    raw_source_positions, raw_source_faces = load_obj(args.source_obj)
    center, radius = source_frame(raw_source_positions)
    normalized_source = normalize(raw_source_positions, center, radius)
    source = compact(normalized_source, raw_source_faces)
    source_boundary = boundary(*source)

    raw_cuts = [read_global_cut(path, raw_source_positions, raw_source_faces)
                for path in args.cut_dir]
    graph_hashes = {cut["mmlg_sha256"] for cut in raw_cuts}
    if len(graph_hashes) != 1:
        raise ValueError("The three cut exports do not share one byte-identical MMLG graph")
    global_ids = np.unique(np.concatenate([cut["global_ids"] for cut in raw_cuts]))
    id_to_union = {int(global_id): index for index, global_id in enumerate(global_ids)}
    global_raw_positions = {}
    cuts = []
    for raw_cut in raw_cuts:
        local_global_ids = raw_cut["global_ids"]
        for global_id, position in zip(local_global_ids, raw_cut["positions"], strict=True):
            previous = global_raw_positions.setdefault(int(global_id), position)
            if not np.array_equal(previous.astype(np.float32), position.astype(np.float32)):
                raise ValueError("A shared MMLG vertex has different exported positions across cuts")
        union_ids = np.asarray([id_to_union[int(value)] for value in local_global_ids],
                               dtype=np.int64)
        local_positions = normalize(raw_cut["positions"], center, radius)
        raw_cut["local_locked"] = topology(Mesh(
            local_positions, raw_cut["faces"], raw_cut["clusters"]).checked())[0]
        raw_cut["union_ids"] = union_ids
        raw_cut["positions_normalized"] = local_positions
        initial_audit = audit(source_boundary, local_positions, raw_cut["faces"])
        raw_cut["initial_audit"] = initial_audit
        if initial_audit["faces"] != raw_cut["face_count"] or not initial_audit["boundary_preserved"]:
            raise ValueError(f"ManyMesh {raw_cut['face_count']}-face cut is ineligible: {initial_audit}")
        cuts.append(raw_cut)

    union_initial = np.empty((len(global_ids), 3), dtype=np.float64)
    for global_id, index in id_to_union.items():
        if global_id not in global_raw_positions:
            raise ValueError(f"Unmapped global MMLG vertex {global_id}")
        union_initial[index] = normalize(global_raw_positions[global_id], center, radius)
    for cut in cuts:
        if not np.array_equal(union_initial[cut["union_ids"]], cut["positions_normalized"]):
            raise ValueError("MMLG global union does not exactly reproduce an exported cut")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    training_views, heldout_views = camera_sets()
    controls = []
    simplify_seconds = {}
    for cut in cuts:
        start = time.perf_counter()
        initial, faces, record = meshopt_simplify_raw(
            source[0], source[1], cut["face_count"], args.out.parent)
        elapsed = time.perf_counter() - start
        meshopt_audit = audit(source_boundary, initial, faces)
        if (meshopt_audit["faces"] == cut["face_count"] and
                meshopt_audit["boundary_preserved"]):
            controls.append({"name": "meshoptimizer", "positions": initial,
                             "faces": faces, "record": record,
                             "audit": meshopt_audit, "rejected_controls": []})
            simplify_seconds[str(cut["face_count"])] = elapsed
            continue

        rejected = [{"name": "meshoptimizer", "audit": meshopt_audit,
                     "reason": "failed frozen topology/boundary eligibility before image scoring"}]
        start = time.perf_counter()
        fallback = qem_simplify(source[0], source[1], cut["face_count"])
        elapsed = time.perf_counter() - start
        qem_audit = audit(source_boundary, fallback.positions, fallback.triangles)
        if (qem_audit["faces"] != cut["face_count"] or
                not qem_audit["boundary_preserved"]):
            raise ValueError(f"No eligible exact-face baseline at {cut['face_count']} faces: "
                             f"meshoptimizer={meshopt_audit}, QEM={qem_audit}")
        controls.append({"name": "qem", "positions": fallback.positions,
                         "faces": fallback.triangles,
                         "record": {"method": "fast-simplification QEM",
                                    "target_faces": cut["face_count"]},
                         "audit": qem_audit, "rejected_controls": rejected})
        simplify_seconds[str(cut["face_count"])] = elapsed

    with tempfile.TemporaryDirectory(prefix="mm-cluster-multicut-") as temporary:
        work = Path(temporary)
        fit_start = time.perf_counter()
        joint_positions, joint_trace, global_locked = fit_joint(
            mi, dr, source, union_initial, cuts, training_views, work / "joint")
        joint_seconds = time.perf_counter() - fit_start

        control_fitted, control_traces, control_fit_seconds = [], [], {}
        for index, control in enumerate(controls):
            start = time.perf_counter()
            (work / f"{control['name']}_{index}").mkdir()
            fitted, trace = fit(mi, dr, source, control["positions"], control["faces"],
                                training_views, work / f"{control['name']}_{index}")
            control_fitted.append(fitted)
            control_traces.append(trace)
            control_fit_seconds[str(len(control["faces"]))] = time.perf_counter() - start

        scored = []
        audits = []
        surface = []
        for index, (cut, control, fitted_control) in enumerate(
                zip(cuts, controls, control_fitted, strict=True)):
            manymesh_fit = joint_positions[cut["union_ids"]]
            raw_key = f"{control['name']}_raw"
            fit_key = f"{control['name']}_fit"
            variants = {
                "source": source,
                "manymesh_raw": (cut["positions_normalized"], cut["faces"]),
                "manymesh_joint_fit": (manymesh_fit, cut["faces"]),
                raw_key: (control["positions"], control["faces"]),
                fit_key: (fitted_control, control["faces"]),
            }
            scored.append(score(mi, variants, heldout_views, work / f"score_{index}"))
            cut_audits = {name: audit(source_boundary, *geometry)
                          for name, geometry in variants.items() if name != "source"}
            audits.append(cut_audits)
            surface.append({name: surface_metrics(source, geometry, 20000, SEED)
                            for name, geometry in variants.items() if name != "source"})

    means = []
    gate = sum(row["halvings"] is not None for row in joint_trace) > 0
    max_displacement = float(np.linalg.norm(joint_positions - union_initial, axis=1).max())
    gate = gate and max_displacement <= MAX_DISPLACEMENT + 1e-9
    normal_mins = []
    lock_preserved = np.array_equal(joint_positions[global_locked], union_initial[global_locked])
    gate = gate and lock_preserved
    for index, (cut, control, fitted_control) in enumerate(
            zip(cuts, controls, control_fitted, strict=True)):
        cut_means = scored[index]["means"]
        means.append(cut_means)
        fitted = joint_positions[cut["union_ids"]]
        before = __import__("fit_projective_rgb_cpu")._face_normals(
            cut["positions_normalized"], cut["faces"])
        after = __import__("fit_projective_rgb_cpu")._face_normals(fitted, cut["faces"])
        ratio = np.sum(before * after, axis=1) / np.maximum(
            np.sum(before * before, axis=1), 1e-30)
        minimum = float(ratio.min())
        normal_mins.append(minimum)
        eligible = all(value["faces"] == cut["face_count"] and value["boundary_preserved"]
                       for value in audits[index].values())
        one_pass = sum(row["halvings"] is not None for row in joint_trace) > 0
        raw_key = f"{control['name']}_raw"
        fit_key = f"{control['name']}_fit"
        this_gate = (
            one_pass and eligible and lock_preserved and
            max_displacement <= MAX_DISPLACEMENT + 1e-9 and minimum >= 0.20 - 1e-6 and
            cut_means["manymesh_joint_fit"]["mean_flip"]
                < cut_means[raw_key]["mean_flip"] and
            cut_means["manymesh_joint_fit"]["mean_flip"]
                < cut_means[fit_key]["mean_flip"] and
            cut_means["manymesh_joint_fit"]["pooled_psnr_db"]
                >= cut_means[fit_key]["pooled_psnr_db"] - 0.10 and
            cut_means["manymesh_joint_fit"]["mean_ssim"]
                >= cut_means[fit_key]["mean_ssim"] - 0.001)
        gate = gate and this_gate

    geometry_path = args.out.with_suffix(".geometry.npz")
    arrays = {"source_positions": source[0], "source_faces": source[1],
              "global_ids": global_ids, "union_initial_positions": union_initial,
              "joint_positions": joint_positions, "global_locked": global_locked}
    for index, (cut, control, fitted_control) in enumerate(
            zip(cuts, controls, control_fitted, strict=True)):
        key = f"cut_{int(cut['face_count']):05d}"
        arrays[f"{key}_faces"] = cut["union_ids"][cut["faces"]]
        arrays[f"{key}_union_ids"] = cut["union_ids"]
        arrays[f"{key}_clusters"] = cut["clusters"]
        arrays[f"{key}_local_locked"] = cut["local_locked"]
        arrays[f"{key}_baseline_positions"] = control["positions"]
        arrays[f"{key}_baseline_faces"] = control["faces"]
        arrays[f"{key}_baseline_fit"] = fitted_control
    with geometry_path.open("wb") as stream:
        np.savez_compressed(stream, **arrays)

    cut_results = []
    for index, cut in enumerate(cuts):
        cut_results.append({
            "requested_ratio": cut["requested_ratio"],
            "face_count": cut["face_count"], "vertex_count": cut["candidate_vertices"],
            "node_count": cut["node_count"], "selected_nodes": cut["selected_nodes"],
            "cluster_boundary_vertices": cut["cluster_boundary_vertices"],
            "retention": cut["face_count"] / len(raw_source_faces),
            "candidate_ply_sha256": cut["candidate_ply_sha256"],
            "graph_json_sha256": cut["graph_json_sha256"],
            "initial_audit": cut["initial_audit"], "audits": audits[index],
            "means_and_per_view": scored[index], "surface": surface[index],
            "geometry_buffer_bytes": {
                "manymesh_position_float32_bytes": int(cut["candidate_vertices"] * 3 * 4),
                "manymesh_triangle_uint32_bytes": int(cut["face_count"] * 3 * 4),
                "baseline_position_float32_bytes": int(len(controls[index]["positions"]) * 3 * 4),
                "baseline_triangle_uint32_bytes": int(cut["face_count"] * 3 * 4),
                "excludes_attributes_and_container_headers": True,
            },
            "baseline": {"name": controls[index]["name"],
                         "simplifier": {key: value for key, value in
                                        controls[index]["record"].items()
                                        if key not in {"positions", "vertices", "indices"}},
                         "raw_audit": controls[index]["audit"],
                         "rejected_controls": controls[index]["rejected_controls"],
                         "simplification_seconds": simplify_seconds[str(cut["face_count"])],
                         "fit_seconds": control_fit_seconds[str(cut["face_count"])],
                         "fit_trace": control_traces[index]},
        })
    result = {
        "status": "completed",
        "scope": "single reused train asset; shared-position three-cut feasibility screen",
        "source_sha256": args.source_sha256,
        "source_faces": int(len(raw_source_faces)),
        "command": sys.argv,
        "script_sha256": digest(Path(__file__)),
        "shared_fit_implementation_sha256": digest(ROOT / "tools/mmtrain/fit_projective_rgb_cpu.py"),
        "protocol_sha256": digest(ROOT / "tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_PROTOCOL_20261127.md"),
        "mmgeo_sha256": digest(args.mmgeo) if args.mmgeo else None,
        "geometry_sha256": digest(geometry_path),
        "geometry_archive_bytes": int(geometry_path.stat().st_size),
        "mmlg_sha256": next(iter(graph_hashes)),
        "cuts": cut_results,
        "joint_fit": {"trace": joint_trace, "seconds": joint_seconds,
                      "unique_mmlg_vertices": int(len(global_ids)),
                      "boundary_locked_vertices": int(global_locked.sum()),
                      "boundary_locked_vertices_unchanged": bool(lock_preserved),
                      "maximum_displacement": max_displacement,
                      "minimum_face_normal_dot_by_cut": normal_mins},
        "training": {"loss": "equal mean full-frame linear-RGB MSE over all cuts and views",
                     "integrator": "Mitsuba direct_projective", "variant": mi.variant(),
                     "resolution": [96, 96], "spp": 4, "camera_count": len(training_views),
                     "iterations_max": 8, "max_step": 0.002,
                     "max_displacement": MAX_DISPLACEMENT,
                     "baseline_fit_seconds": control_fit_seconds},
        "heldout": {"view_count": len(heldout_views), "resolution": [96, 96], "spp": 16},
        "package_versions": {name: importlib.metadata.version(name) for name in
                              ("mitsuba", "drjit", "numpy", "scipy", "scikit-image", "flip-evaluator")},
        "platform": platform.platform(), "python": platform.python_version(),
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
        "decision": ("advance to a separately frozen multi-asset study" if gate
                     else "close this shared-position three-cut configuration"),
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"decision": result["decision"], "mmlg_sha256": result["mmlg_sha256"],
                      "joint_fit_seconds": joint_seconds,
                      "boundary_locked_vertices": int(global_locked.sum()),
                      "maximum_displacement": max_displacement,
                      "minimum_face_normal_dot_by_cut": normal_mins,
                      "cuts": [{"faces": cut["face_count"],
                                "cluster_fit": cut["means_and_per_view"]["means"]["manymesh_joint_fit"],
                                "baseline": cut["baseline"]["name"],
                                "baseline_fit": cut["means_and_per_view"]["means"][
                                    f"{cut['baseline']['name']}_fit"]}
                               for cut in cut_results]}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
