"""Independently audit a downloaded CPU projective-RGB workflow artifact."""

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))
ASSETS = {
    "e6f986bd960e31bbc7a0b1d957f0fdf1be25b22de547fd2a3761615d521eb041":
        ("GlassHurricaneCandleHolder", 4126, 2062),
    "8bd3e8f5ae3dfffe0e7ccbc89f3941aa7c1122a7e8756ddac4c7293df7608c09":
        ("MaterialsVariantsShoe", 22700, 11350),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, name):
    require(math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-11),
            f"{name} differs: receipt={actual!r}, recomputed={expected!r}")


def digest(path):
    import hashlib

    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path,
                        help="Directory containing result.json, result.geometry.npz, and geometry.obj")
    args = parser.parse_args()

    result_path = args.artifact_dir / "result.json"
    geometry_path = args.artifact_dir / "result.geometry.npz"
    source_path = args.artifact_dir / "geometry.obj"
    for path in (result_path, geometry_path, source_path):
        require(path.is_file(), f"Artifact is missing {path.name}")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    require(result["status"] == "completed", "Fit receipt is not marked completed")
    require(result["source_sha256"] in ASSETS, "Source hash is outside the frozen two-asset screen")
    asset_name, expected_source_faces, expected_target_faces = ASSETS[result["source_sha256"]]
    require(result["source_sha256"] == digest(source_path), "Source OBJ hash mismatch")
    require(result["geometry_sha256"] == digest(geometry_path), "Geometry archive hash mismatch")
    require(result["script_sha256"] == digest(Path(__file__).with_name("fit_projective_rgb_cpu.py")),
            "Fit script differs from the hash recorded by the run")

    from audit_target_budget_visibility import load_obj
    from bench_upstream_clusterlod import compact
    from cluster_decoder_surface_quality import surface_metrics
    from fit_projective_rgb_cpu import camera_sets
    from preflight_appearance_meshes import audit, boundary
    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame

    raw_positions, raw_faces = load_obj(source_path)
    center, radius = source_frame(raw_positions)
    reference = compact(normalize(raw_positions, center, radius), raw_faces)
    require(len(raw_faces) == expected_source_faces, "Source is not the expected frozen asset")
    require(len(raw_faces) == result["source_faces"], "Source face count mismatch")
    target = len(raw_faces) - 2 * round(len(raw_faces) / 4)
    require(target == expected_target_faces, "Unexpected target face budget for this asset")
    require(target == result["target_faces"], "Target face budget mismatch")

    with np.load(geometry_path, allow_pickle=False) as geometry:
        source = (geometry["source_positions"], geometry["source_faces"])
        meshoptimizer = (geometry["meshoptimizer_positions"], geometry["meshoptimizer_faces"])
        fitted = (geometry["fitted_positions"], geometry["fitted_faces"])
    require(np.array_equal(source[0], reference[0]) and np.array_equal(source[1], reference[1]),
            "Geometry archive source differs from the extracted source OBJ")
    require(meshoptimizer[1].shape == fitted[1].shape
            and np.array_equal(meshoptimizer[1], fitted[1]),
            "Fit changed the fixed triangle topology")
    require(len(meshoptimizer[1]) == target and len(fitted[1]) == target,
            "Candidate face count differs from the frozen budget")

    source_boundary = boundary(*source)
    init_audit = audit(source_boundary, *meshoptimizer)
    fit_audit = audit(source_boundary, *fitted)
    require(init_audit["boundary_preserved"] and fit_audit["boundary_preserved"],
            "A mesh failed the source boundary audit")
    edges, _, _, incidence = _edge_incidence(meshoptimizer[1])
    boundary_vertices = np.unique(edges[incidence == 1])
    require(np.array_equal(meshoptimizer[0][boundary_vertices], fitted[0][boundary_vertices]),
            "Open-boundary vertices moved during fitting")

    displacement = np.linalg.norm(fitted[0] - meshoptimizer[0], axis=1)
    close(result["max_displacement"], displacement.max(), "maximum displacement")
    require(displacement.max() <= 0.012 + 1e-9, "Displacement limit exceeded")
    initial_normals = _face_normals(meshoptimizer[0], meshoptimizer[1])
    fitted_normals = _face_normals(fitted[0], fitted[1])
    dot = np.einsum("ij,ij->i", initial_normals, fitted_normals)
    normal_floor = 0.2 * np.einsum("ij,ij->i", initial_normals, initial_normals)
    require(np.all(dot >= normal_floor), "A face violates the normal-orientation constraint")

    heldout = result["heldout"]
    rows = heldout["views"]
    require(len(rows) == 24 and [row["view"] for row in rows] == list(range(24)),
            "Expected all 24 ordered reserved-view records")
    expected_training, expected_heldout = camera_sets()
    recorded_training = np.asarray(result["training"]["camera_bases"], dtype=np.float64)
    require(recorded_training.shape == (16, 3, 3)
            and np.allclose(recorded_training, expected_training, rtol=0, atol=1e-12),
            "Training camera bases differ from the frozen generator")
    recorded_heldout = np.asarray([row["basis"] for row in rows], dtype=np.float64)
    require(recorded_heldout.shape == (24, 3, 3)
            and np.allclose(recorded_heldout, expected_heldout, rtol=0, atol=1e-12),
            "Reserved camera bases differ from the frozen generator")
    means = {}
    for arm in ("meshoptimizer", "fitted"):
        values = [row["arms"][arm] for row in rows]
        for key in ("mse", "psnr_db", "ssim", "flip"):
            require(all(math.isfinite(float(value[key])) for value in values),
                    f"Nonfinite {key} in {arm} view scores")
        pooled_mse = float(np.mean([value["mse"] for value in values]))
        means[arm] = {
            "pooled_mse": pooled_mse,
            "pooled_psnr_db": -10 * math.log10(pooled_mse) if pooled_mse else None,
            "mean_ssim": float(np.mean([value["ssim"] for value in values])),
            "mean_flip": float(np.mean([value["flip"] for value in values])),
        }
        for key, value in means[arm].items():
            close(heldout["means"][arm][key], value, f"{arm} {key}")

    surface = {name: surface_metrics(reference, mesh, 20000, 20261125)
               for name, mesh in (("source", reference),
                                  ("meshoptimizer", meshoptimizer), ("fitted", fitted))}
    for name, metrics in surface.items():
        for key, value in metrics.items():
            close(result["surface"][name][key], value, f"{name} surface {key}")

    accepted = result["training"]["accepted_steps"] > 0
    passes = (accepted
              and means["fitted"]["mean_flip"] < means["meshoptimizer"]["mean_flip"]
              and means["fitted"]["pooled_psnr_db"] >= means["meshoptimizer"]["pooled_psnr_db"] - 0.1
              and means["fitted"]["mean_ssim"] >= means["meshoptimizer"]["mean_ssim"] - 0.001)
    expected_decision = ("advance to a separately frozen multi-asset study" if passes
                         else "close this CPU full-image fit configuration")
    require(result["decision"] == expected_decision, "Recorded decision disagrees with the frozen gate")

    print(json.dumps({"asset": asset_name, "audit": "passed",
                      "source_faces": len(raw_faces), "target_faces": target,
                      "initial_topology": init_audit, "fitted_topology": fit_audit,
                      "means": means, "decision": expected_decision,
                      "geometry_sha256": result["geometry_sha256"]}, indent=2))


def _edge_incidence(faces):
    sides = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges, ids, counts = np.unique(np.sort(sides, axis=1), axis=0,
                                   return_inverse=True, return_counts=True)
    owners = np.tile(np.arange(len(faces)), 3)[np.argsort(ids, kind="stable")]
    starts = np.cumsum(counts) - counts
    return edges, owners[starts], owners[starts + counts - 1], counts


def _face_normals(points, faces):
    a, b, c = points[faces].transpose(1, 0, 2)
    return np.cross(b - a, c - a)


if __name__ == "__main__":
    main()
