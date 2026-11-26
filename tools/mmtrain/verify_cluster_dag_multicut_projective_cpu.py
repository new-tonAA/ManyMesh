#!/usr/bin/env python3
"""Independently audit a multi-cut cluster-DAG fit receipt and geometry."""

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


def means_from_views(scored):
    views = scored["views"]
    require(len(views) == 24, f"Expected 24 reserved views, got {len(views)}")
    names = tuple(scored["means"])
    result = {}
    for name in names:
        rows = [view["arms"][name] for view in views]
        mse = float(np.mean([row["mse"] for row in rows]))
        values = {
            "pooled_mse": mse,
            "pooled_psnr_db": -10.0 * float(np.log10(mse)),
            "mean_ssim": float(np.mean([row["ssim"] for row in rows])),
            "mean_flip": float(np.mean([row["flip"] for row in rows])),
        }
        for key, actual in values.items():
            expected = float(scored["means"][name][key])
            require(abs(actual - expected) <= max(1e-12, abs(expected) * 1e-10),
                    f"Stored {name}.{key} differs from its per-view rows")
        result[name] = values
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--mmgeo", type=Path, required=True)
    args = parser.parse_args()

    from audit_target_budget_visibility import load_obj
    from cluster_decoder import Mesh, topology
    from fit_projective_rgb_cpu import _face_normals
    from preflight_appearance_meshes import audit, boundary

    result = json.loads(args.result.read_text(encoding="utf-8"))
    require(digest(args.source_obj) == args.source_sha256 == result["source_sha256"],
            "Source OBJ SHA-256 mismatch")
    require(digest(args.geometry) == result["geometry_sha256"],
            "Geometry archive SHA-256 mismatch")
    require(args.geometry.stat().st_size == result["geometry_archive_bytes"],
            "Geometry archive byte count mismatch")
    require(result["script_sha256"] == digest(ROOT / "tools/mmtrain/fit_cluster_dag_multicut_projective_cpu.py"),
            "Fit script hash mismatch")
    require(result["shared_fit_implementation_sha256"] ==
            digest(ROOT / "tools/mmtrain/fit_projective_rgb_cpu.py"),
            "Shared fit implementation hash mismatch")
    require(result["protocol_sha256"] == digest(args.protocol), "Protocol hash mismatch")
    require(result["mmgeo_sha256"] == digest(args.mmgeo), "mmgeo binary hash mismatch")

    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame
    raw_source, source_faces = load_obj(args.source_obj)
    center, radius = source_frame(raw_source)
    source_positions = normalize(raw_source, center, radius)
    used, inverse = np.unique(source_faces, return_inverse=True)
    source = (source_positions[used], inverse.reshape(-1, 3))
    source_boundary = boundary(*source)
    require(len(source_faces) == result["source_faces"], "Source face count mismatch")

    with np.load(args.geometry, allow_pickle=False) as data:
        arrays = {name: data[name].copy() for name in data.files}
    require(np.array_equal(arrays["source_faces"], source[1]),
            "Archived source topology differs from original OBJ")
    require(np.allclose(arrays["source_positions"], source[0], rtol=0, atol=1e-7),
            "Archived source positions differ from original OBJ")
    global_ids = arrays["global_ids"]
    require(global_ids.ndim == 1 and len(np.unique(global_ids)) == len(global_ids),
            "Global MMLG IDs are not unique")
    initial = arrays["union_initial_positions"]
    fitted = arrays["joint_positions"]
    global_locked = arrays["global_locked"].astype(bool)
    require(initial.shape == fitted.shape == (len(global_ids), 3),
            "Shared position array shape mismatch")

    recomputed_global_locks = np.zeros(len(global_ids), dtype=bool)
    means, audits, normal_mins = [], [], []
    for cut in result["cuts"]:
        faces_count = int(cut["face_count"])
        key = f"cut_{faces_count:05d}"
        union_ids = arrays[f"{key}_union_ids"].astype(np.int64)
        clusters = arrays[f"{key}_clusters"].astype(np.int64)
        local_locked = arrays[f"{key}_local_locked"].astype(bool)
        global_faces = arrays[f"{key}_faces"].astype(np.int64)
        require(len(union_ids) == len(local_locked), f"Cut {faces_count}: lock mask shape mismatch")
        require(global_faces.shape == (faces_count, 3), f"Cut {faces_count}: face count mismatch")
        require(np.all(union_ids >= 0) and np.all(union_ids < len(global_ids)),
                f"Cut {faces_count}: union ID out of range")
        require(np.all(global_faces >= 0) and np.all(global_faces < len(global_ids)),
                f"Cut {faces_count}: triangle index out of range")
        recomputed_global_locks[union_ids[local_locked]] = True

        union_to_local = np.full(len(global_ids), -1, dtype=np.int64)
        union_to_local[union_ids] = np.arange(len(union_ids))
        local_faces = union_to_local[global_faces]
        require(np.all(local_faces >= 0), f"Cut {faces_count}: face references absent local vertex")
        local_positions0 = initial[union_ids]
        local_positions1 = fitted[union_ids]
        mesh = Mesh(local_positions0, local_faces, clusters).checked()
        expected_lock, _, _ = topology(mesh)
        require(np.array_equal(expected_lock, local_locked),
                f"Cut {faces_count}: saved cluster lock mask is not reproducible")
        require(np.array_equal(local_positions1[local_locked], local_positions0[local_locked]),
                f"Cut {faces_count}: locked cluster vertex moved")

        control_name = cut["baseline"]["name"]
        control_positions = arrays[f"{key}_baseline_positions"]
        control_faces = arrays[f"{key}_baseline_faces"].astype(np.int64)
        control_fit = arrays[f"{key}_baseline_fit"]
        require(len(control_faces) == faces_count, f"Cut {faces_count}: baseline count mismatch")
        variants = {
            "manymesh_raw": (local_positions0, local_faces),
            "manymesh_joint_fit": (local_positions1, local_faces),
            f"{control_name}_raw": (control_positions, control_faces),
            f"{control_name}_fit": (control_fit, control_faces),
        }
        current_audits = {name: audit(source_boundary, *geometry)
                           for name, geometry in variants.items()}
        require(current_audits == cut["audits"],
                f"Cut {faces_count}: raw topology audit differs from stored receipt")
        require(all(row["faces"] == faces_count and row["boundary_preserved"]
                    for row in current_audits.values()),
                f"Cut {faces_count}: topology or source boundary failed")

        normals0 = _face_normals(local_positions0, local_faces)
        normals1 = _face_normals(local_positions1, local_faces)
        ratios = np.sum(normals0 * normals1, axis=1) / np.maximum(
            np.sum(normals0 * normals0, axis=1), 1e-30)
        normal_min = float(ratios.min())
        normal_mins.append(normal_min)
        means_cut = means_from_views(cut["means_and_per_view"])
        means.append(means_cut)

        ratio = cut["retention"]
        require(abs(ratio - faces_count / len(source_faces)) < 1e-12,
                f"Cut {faces_count}: actual retention mismatch")
        byte_record = cut["geometry_buffer_bytes"]
        require(byte_record["manymesh_position_float32_bytes"] ==
                int(cut["vertex_count"] * 3 * 4), f"Cut {faces_count}: vertex byte count mismatch")
        for field in ("manymesh_triangle_uint32_bytes", "baseline_triangle_uint32_bytes"):
            require(byte_record[field] == faces_count * 3 * 4,
                    f"Cut {faces_count}: index byte count mismatch")
        require(byte_record["baseline_position_float32_bytes"] ==
                int(len(control_positions) * 3 * 4),
                f"Cut {faces_count}: baseline vertex byte count mismatch")

    require(np.array_equal(global_locked, recomputed_global_locks),
            "Global lock mask is not the union of cut-boundary lock masks")
    max_displacement = float(np.linalg.norm(fitted - initial, axis=1).max())
    require(abs(max_displacement - result["joint_fit"]["maximum_displacement"]) < 1e-9,
            "Maximum displacement mismatch")
    require(np.array_equal(fitted[global_locked], initial[global_locked]),
            "A globally locked MMLG vertex moved")
    require(np.allclose(normal_mins,
                        result["joint_fit"]["minimum_face_normal_dot_by_cut"],
                        rtol=0, atol=1e-7), "Per-cut normal floor mismatch")

    accepted = sum(row["halvings"] is not None for row in result["joint_fit"]["trace"])
    maxdisp = max_displacement <= 0.012 + 1e-9
    topology_ok = all(all(item["faces"] == int(cut["face_count"]) and
                          item["boundary_preserved"] for item in cut["audits"].values())
                      for cut in result["cuts"])
    gate = accepted > 0 and maxdisp and topology_ok and np.array_equal(
        fitted[global_locked], initial[global_locked])
    for cut, metrics, normal_min in zip(result["cuts"], means, normal_mins, strict=True):
        control = cut["baseline"]["name"]
        raw, optimized = metrics[f"{control}_raw"], metrics[f"{control}_fit"]
        candidate = metrics["manymesh_joint_fit"]
        gate = gate and normal_min >= 0.20 - 1e-6
        gate = gate and candidate["mean_flip"] < raw["mean_flip"]
        gate = gate and candidate["mean_flip"] < optimized["mean_flip"]
        gate = gate and candidate["pooled_psnr_db"] >= optimized["pooled_psnr_db"] - 0.10
        gate = gate and candidate["mean_ssim"] >= optimized["mean_ssim"] - 0.001
    expected_decision = ("advance to a separately frozen multi-asset study" if gate
                         else "close this shared-position three-cut configuration")
    require(result["decision"] == expected_decision,
            "Recorded decision does not follow the frozen gate")

    print(json.dumps({
        "status": "passed", "cuts": [
            {"faces": int(cut["face_count"]), "baseline": cut["baseline"]["name"],
             "candidate_psnr_db": means[i]["manymesh_joint_fit"]["pooled_psnr_db"],
             "baseline_psnr_db": means[i][f"{cut['baseline']['name']}_fit"]["pooled_psnr_db"],
             "candidate_flip": means[i]["manymesh_joint_fit"]["mean_flip"],
             "baseline_flip": means[i][f"{cut['baseline']['name']}_fit"]["mean_flip"],
             "boundary_preserved": True, "normal_dot_min": normal_mins[i]}
            for i, cut in enumerate(result["cuts"])],
        "locked_vertices": int(global_locked.sum()),
        "locked_vertices_unchanged": True,
        "maximum_displacement": max_displacement,
        "frozen_decision": result["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
