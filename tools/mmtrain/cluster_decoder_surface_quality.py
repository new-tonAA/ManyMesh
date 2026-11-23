"""Sampled bidirectional surface metrics for the frozen rank-8 quality screen.

These point-cloud estimates complement, and do not replace, exact surface
distances or the rendered-image metrics in cluster_decoder_quality.py.
"""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import sys

import numpy as np
import scipy
from scipy.spatial import cKDTree

from cluster_decoder import Mesh, Model, decode
from fit_cluster_decoder import load_pair
from cluster_decoder_quality import validation_variants

METRICS = ("chamfer_l1_mean", "chamfer_l2_squared_mean",
           "bidirectional_distance_p95", "bidirectional_distance_max_sampled",
           "normal_consistency_absdot")


def summarize(records, bootstrap_count=10000, seed=20261121):
    """Summarize assets as the independent units; views/samples are not trials."""
    result = {}
    for split in ("train", "validation"):
        rows = [row for row in records if row["split"] == split and
                row["methods"].get("rank8_fixed") is not None]
        section = {"paired_assets": len(rows), "methods": {}, "rank8_minus_qem": {}}
        for method in ("qem", "rank8_fixed"):
            section["methods"][method] = {
                metric: float(np.mean([row["methods"][method][metric] for row in rows]))
                for metric in METRICS
            } if rows else {}
        for offset, metric in enumerate(METRICS):
            delta = np.asarray([
                row["methods"]["rank8_fixed"][metric] - row["methods"]["qem"][metric]
                for row in rows
            ], dtype=np.float64)
            if not len(delta):
                section["rank8_minus_qem"][metric] = None
                continue
            rng = np.random.default_rng(seed + offset + (0 if split == "train" else 100))
            boot = np.empty(bootstrap_count, dtype=np.float64)
            for index in range(bootstrap_count):
                boot[index] = rng.choice(delta, size=len(delta), replace=True).mean()
            section["rank8_minus_qem"][metric] = {
                "mean": float(delta.mean()),
                "bootstrap_95_percentile_ci": [float(x) for x in np.quantile(boot, (.025, .975))],
                "assets_with_positive_delta": int(np.count_nonzero(delta > 0)),
                "assets_with_negative_delta": int(np.count_nonzero(delta < 0)),
                "positive_is_better": metric == "normal_consistency_absdot",
            }
        result[split] = section
    return result


def sample_surface(positions, triangles, count, seed):
    """Draw area-uniform points and face normals with deterministic sampling."""
    positions = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if positions.ndim != 2 or positions.shape[1] != 3 or not len(positions):
        raise ValueError("Positions must be a non-empty Nx3 array")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles):
        raise ValueError("Triangles must be a non-empty Mx3 array")
    if not np.isfinite(positions).all() or triangles.min() < 0 or triangles.max() >= len(positions):
        raise ValueError("Invalid surface geometry")
    face_points = positions[triangles]
    cross = np.cross(face_points[:, 1] - face_points[:, 0],
                     face_points[:, 2] - face_points[:, 0])
    twice_area = np.linalg.norm(cross, axis=1)
    if not np.isfinite(twice_area).all() or np.any(twice_area <= 1e-18):
        raise ValueError("Surface contains degenerate triangles")
    rng = np.random.default_rng(seed)
    face_ids = rng.choice(len(triangles), size=count, p=twice_area / twice_area.sum())
    uv = rng.random((count, 2))
    root = np.sqrt(uv[:, 0])
    bary = np.column_stack((1 - root, root * (1 - uv[:, 1]), root * uv[:, 1]))
    points = np.einsum("ni,nij->nj", bary, face_points[face_ids])
    normals = cross[face_ids] / twice_area[face_ids, None]
    return points, normals


def surface_metrics(reference, candidate, sample_count=20000, seed=0):
    """Return sampled symmetric Chamfer, tail distance, and normal agreement."""
    if not isinstance(sample_count, int) or sample_count < 100:
        raise ValueError("sample_count must be an integer of at least 100")
    if (np.array_equal(reference[0], candidate[0]) and
            np.array_equal(reference[1], candidate[1])):
        return {
            "samples_per_direction": sample_count,
            "chamfer_l1_mean": 0.,
            "chamfer_l2_squared_mean": 0.,
            "bidirectional_distance_p95": 0.,
            "bidirectional_distance_max_sampled": 0.,
            "normal_consistency_absdot": 1.,
        }
    ref_points, ref_normals = sample_surface(*reference, sample_count, seed)
    cand_points, cand_normals = sample_surface(*candidate, sample_count, seed ^ 0x9E3779B9)
    ref_tree, cand_tree = cKDTree(ref_points), cKDTree(cand_points)
    d_ref, i_cand = cand_tree.query(ref_points, k=1, workers=1)
    d_cand, i_ref = ref_tree.query(cand_points, k=1, workers=1)
    normal_ref = np.abs(np.einsum("ij,ij->i", ref_normals, cand_normals[i_cand]))
    normal_cand = np.abs(np.einsum("ij,ij->i", cand_normals, ref_normals[i_ref]))
    both = np.concatenate((d_ref, d_cand))
    return {
        "samples_per_direction": sample_count,
        "chamfer_l1_mean": float((d_ref.mean() + d_cand.mean()) * 0.5),
        "chamfer_l2_squared_mean": float(((d_ref ** 2).mean() + (d_cand ** 2).mean()) * 0.5),
        "bidirectional_distance_p95": float(np.quantile(both, 0.95)),
        "bidirectional_distance_max_sampled": float(both.max()),
        "normal_consistency_absdot": float((normal_ref.mean() + normal_cand.mean()) * 0.5),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True,
                        help="Directory containing the frozen image-quality report")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20000)
    args = parser.parse_args()
    if args.samples < 100 or args.samples > 1_000_000:
        parser.error("--samples must be between 100 and 1000000")
    args.out.mkdir(parents=True, exist_ok=True)
    quality_path = args.quality / "report.json"
    image_quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality_rows = {(r["split"], r["file_id"]): r for r in image_quality["records"]}
    fit_path = args.fit / "report.json"
    fit = json.loads(fit_path.read_text(encoding="utf-8"))
    fit_fixed = {r["file_id"]: r for r in fit["modes"]["fixed"]["records"]}
    report = {
        "scope": "Sampled surface-distance diagnostic for frozen rank-8 linear control; no final test assets",
        "method": "Area-uniform triangle samples; symmetric nearest-point-cloud Chamfer estimates, not exact point-to-triangle distance",
        "normal_convention": "Absolute dot of nearest sampled face normals; ignores winding sign",
        "sample_count_per_direction": args.samples,
        "seed_policy": "Per asset, fixed seed from file_id; reference and candidate use separate deterministic streams",
        "distance_units": "Source meshes normalized to unit bounding radius",
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pair_manifest_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.pairs
        },
        "fit_report_sha256": hashlib.sha256(fit_path.read_bytes()).hexdigest(),
        "fixed_model_sha256": hashlib.sha256((args.fit / "fixed" / "model.npz").read_bytes()).hexdigest(),
        "input_quality_report_sha256": hashlib.sha256(quality_path.read_bytes()).hexdigest(),
        "records": [],
    }
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(r["source"]["split"] not in ("train", "validation") for r in manifest["records"]):
            raise ValueError("Final test geometry is not accepted by this diagnostic")
        for row in manifest["records"]:
            source = row["source"]
            split, file_id = source["split"], source["file_id"]
            result = {"split": split, "file_id": file_id,
                      "source_sha256": source["sha256"],
                      "preparation_status": row["status"], "methods": {}}
            quality_row = quality_rows[(split, file_id)]
            if row["status"] != "prepared":
                result["reason"] = row["reason"]
                report["records"].append(result)
                continue
            pair = load_pair(manifest_path.parent, row)
            ref = (pair["source_positions"], pair["source_triangles"])
            result["methods"]["qem"] = surface_metrics(
                ref, (pair["positions"], pair["triangles"]), args.samples, file_id)
            if split == "train":
                item = fit_fixed[file_id]
                result["decoder_status"] = item["status"]
                if item["status"] == "decoded":
                    decoded_path = args.fit / "fixed" / f"{file_id}-decoded.npz"
                    with np.load(decoded_path, allow_pickle=False) as decoded:
                        geom = (decoded["positions"], decoded["triangles"])
                else:
                    geom = None
            else:
                status = quality_row.get("decode_status", {}).get("fixed")
                result["decoder_status"] = status or "not decoded"
                geom = None
                if status == "decoded":
                    model_path = args.fit / "fixed" / "model.npz"
                    with np.load(model_path, allow_pickle=False) as archive:
                        model = Model(archive["weights"], float(archive["max_offset"]))
                    sidecar = args.quality / f"validation-{file_id}" / f"{file_id}-fixed.sidecar"
                    candidate, _ = decode(Mesh(pair["positions"], pair["triangles"],
                                                pair["face_clusters"]), model, sidecar,
                                          len(pair["triangles"]))
                    geom = (candidate.positions, candidate.triangles)
            if geom is not None:
                result["methods"]["rank8_fixed"] = surface_metrics(ref, geom, args.samples, file_id)
            else:
                result["methods"]["rank8_fixed"] = None
            report["records"].append(result)
            print(f"{split} {file_id}: {result['decoder_status']}", flush=True)
            (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["paired_summary"] = summarize(report["records"])
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
