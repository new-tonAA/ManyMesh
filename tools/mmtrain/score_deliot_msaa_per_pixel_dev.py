"""Score the frozen D3D12 per-pixel-fit captures in the existing WSL venv."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform

import flip_evaluator
import numpy as np
import scipy
import skimage
from scipy.spatial import cKDTree
from skimage.metrics import structural_similarity


SAMPLES_PER_DIRECTION = 20000
SURFACE_SEED = 20261127


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score_pair(reference, image):
    ref = reference.astype(np.float32) / 255.0
    img = image.astype(np.float32) / 255.0
    mse = float(np.mean((ref - img) ** 2, dtype=np.float64))
    _, flip, _ = flip_evaluator.evaluate(ref, img, "LDR", inputsRGB=True,
                                        applyMagma=False,
                                        parameters={"ppd": 67.0})
    ref_gray = ref[..., 0]
    img_gray = img[..., 0]
    return {
        "mse": mse,
        "psnr_db": None if mse == 0 else float(-10.0 * np.log10(mse)),
        "ssim": float(structural_similarity(
            ref_gray, img_gray, data_range=1.0, gaussian_weights=True,
            sigma=1.5, use_sample_covariance=False)),
        "flip": float(flip),
        "silhouette_xor_fraction": float(np.mean((ref_gray > 0) != (img_gray > 0))),
    }


def sample_surface(positions, faces, count, seed):
    tri = positions[faces].astype(np.float64)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    twice_area = np.linalg.norm(cross, axis=1)
    if np.any(twice_area <= 1e-18) or not np.isfinite(twice_area).all():
        raise ValueError("Cannot sample a surface containing degenerate triangles")
    rng = np.random.default_rng(seed)
    face_ids = rng.choice(len(faces), size=count, p=twice_area / twice_area.sum())
    uv = rng.random((count, 2))
    root = np.sqrt(uv[:, 0])
    bary = np.column_stack((1 - root, root * (1 - uv[:, 1]), root * uv[:, 1]))
    points = np.einsum("ni,nij->nj", bary, tri[face_ids])
    normals = cross[face_ids] / twice_area[face_ids, None]
    return points, normals


def surface_metrics(reference, candidate, seed):
    ref_points, ref_normals = sample_surface(*reference, SAMPLES_PER_DIRECTION, seed)
    cand_points, cand_normals = sample_surface(*candidate, SAMPLES_PER_DIRECTION,
                                                seed ^ 0x9E3779B9)
    ref_tree, cand_tree = cKDTree(ref_points), cKDTree(cand_points)
    d_ref, i_cand = cand_tree.query(ref_points, k=1, workers=1)
    d_cand, i_ref = ref_tree.query(cand_points, k=1, workers=1)
    dot_ref = np.abs(np.einsum("ij,ij->i", ref_normals, cand_normals[i_cand]))
    dot_cand = np.abs(np.einsum("ij,ij->i", cand_normals, ref_normals[i_ref]))
    distances = np.concatenate((d_ref, d_cand))
    return {
        "samples_per_direction": SAMPLES_PER_DIRECTION,
        "chamfer_l1_mean": float((d_ref.mean() + d_cand.mean()) * 0.5),
        "chamfer_l2_squared_mean": float(((d_ref ** 2).mean() +
                                           (d_cand ** 2).mean()) * 0.5),
        "bidirectional_distance_p95": float(np.quantile(distances, 0.95)),
        "bidirectional_distance_max_sampled": float(distances.max()),
        "normal_consistency_absdot": float((dot_ref.mean() + dot_cand.mean()) * 0.5),
    }


def summarize(rows):
    output = {}
    for arm in ("manymesh", "meshoptimizer"):
        for variant in ("raw", "fit"):
            selected = [row["arms"][arm][variant] for row in rows]
            mse = float(np.mean([x["mse"] for x in selected]))
            output[f"{arm}_{variant}"] = {
                "pooled_mse": mse,
                "pooled_psnr_db": None if mse == 0 else float(-10.0 * np.log10(mse)),
                "mean_flip": float(np.mean([x["flip"] for x in selected])),
                "worst_flip": float(np.max([x["flip"] for x in selected])),
                "mean_ssim": float(np.mean([x["ssim"] for x in selected])),
                "worst_ssim": float(np.min([x["ssim"] for x in selected])),
                "mean_silhouette_xor_fraction": float(np.mean(
                    [x["silhouette_xor_fraction"] for x in selected])),
                "worst_silhouette_xor_fraction": float(np.max(
                    [x["silhouette_xor_fraction"] for x in selected])),
            }
    many, control = output["manymesh_fit"], output["meshoptimizer_fit"]
    output["fitted_manymesh_minus_fitted_meshoptimizer"] = {
        "pooled_psnr_db": many["pooled_psnr_db"] - control["pooled_psnr_db"],
        "mean_flip": many["mean_flip"] - control["mean_flip"],
        "mean_ssim": many["mean_ssim"] - control["mean_ssim"],
        "mean_silhouette_xor_fraction": (
            many["mean_silhouette_xor_fraction"] - control["mean_silhouette_xor_fraction"]),
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-receipt", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.raw_receipt.read_text(encoding="utf-8"))
    if digest(args.captures) != raw["capture_archive_sha256"]:
        raise ValueError("Capture archive hash does not match the hardware receipt")
    if digest(args.geometry) != raw["geometry_archive_sha256"]:
        raise ValueError("Geometry archive hash does not match the hardware receipt")
    captures = np.load(args.captures, allow_pickle=False)
    geometry = np.load(args.geometry, allow_pickle=False)
    rows = []
    for view in raw["image_rows"]["validation"]:
        row = {"view": view["view"], "screen_scale": view["screen_scale"],
               "arms": {}}
        reference = captures[view["reference_capture"]]
        if hashlib.sha256(reference.tobytes()).hexdigest() != view["reference_sha256"]:
            raise ValueError(f"Reference hash mismatch on view {view['view']}")
        for arm in ("manymesh", "meshoptimizer"):
            row["arms"][arm] = {}
            for variant in ("raw", "fit"):
                item = view["arms"][arm][variant]
                image = captures[item["capture"]]
                if hashlib.sha256(image.tobytes()).hexdigest() != item["image_sha256"]:
                    raise ValueError(f"Image hash mismatch: {item['capture']}")
                metrics = score_pair(reference, image)
                metrics["capture"] = item["capture"]
                row["arms"][arm][variant] = metrics
        rows.append(row)
    summary = summarize(rows)

    source = (geometry["source_positions"].astype(np.float64),
              geometry["source_faces"].astype(np.int64))
    surface = {}
    for arm in ("manymesh", "meshoptimizer"):
        faces = geometry[f"{arm}_faces"].astype(np.int64)
        surface[arm] = {}
        for variant in ("raw", "fit"):
            points = geometry[f"{arm}_{variant}_positions"].astype(np.float64)
            surface[arm][variant] = surface_metrics(
                source, (points, faces), SURFACE_SEED)

    fits = {arm: raw["arms"][arm]["fit"] for arm in ("manymesh", "meshoptimizer")}
    structural = all(
        fit["locked_vertices_unchanged"] and fit["degenerate_faces"] == 0
        and fit["minimum_face_normal_dot_ratio"] >= 0.20
        and fit["maximum_displacement"] <= 0.012
        for fit in fits.values())
    structural = structural and all(
        len(geometry[f"{arm}_faces"]) == 5290
        and len(geometry[f"{arm}_raw_positions"]) == len(geometry[f"{arm}_fit_positions"])
        for arm in ("manymesh", "meshoptimizer"))
    updates_accepted = all(
        len(fit["trace"]) == 4
        and all(step["accepted_halving"] is not None for step in fit["trace"])
        for fit in fits.values())
    train_improvement = all(
        fit["trace"][-1]["train_mse_after"] < fit["trace"][0]["train_mse_before"]
        for fit in fits.values())
    delta = summary["fitted_manymesh_minus_fitted_meshoptimizer"]
    pass_gate = bool(
        structural and updates_accepted and train_improvement
        and delta["mean_flip"] < 0.0
        and delta["pooled_psnr_db"] > 0.0
        and delta["mean_ssim"] >= -0.001)
    report = {
        "status": "pass" if pass_gate else "fail",
        "decision": {
            "advance_fixed_topology_configuration": pass_gate,
            "structural_constraints_pass": structural,
            "all_four_optimizer_updates_accepted": updates_accepted,
            "both_training_losses_improve": train_improvement,
            "fitted_manymesh_beats_fitted_meshoptimizer_on_flip_and_psnr": bool(
                delta["mean_flip"] < 0.0 and delta["pooled_psnr_db"] > 0.0),
            "ssim_margin_pass": bool(delta["mean_ssim"] >= -0.001),
            "thresholds": {"mean_flip_delta_max": 0.0, "pooled_psnr_delta_min_db": 0.0,
                           "mean_ssim_delta_min": -0.001},
        },
        "scope": raw["scope"], "raw_receipt_sha256": digest(args.raw_receipt),
        "capture_archive_sha256": digest(args.captures),
        "geometry_archive_sha256": digest(args.geometry),
        "script_sha256": digest(__file__),
        "runtime": {"platform": platform.platform(),
                    "python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__, "scikit_image": skimage.__version__,
                    "flip_evaluator": importlib.metadata.version("flip-evaluator")},
        "summary": summary, "per_view": rows,
        "sampled_surface_metrics": surface,
        "diagnostic_views_are_correlated_and_previously_scored": True,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "decision": report["decision"],
                      "summary": summary}, separators=(",", ":"), allow_nan=False),
          flush=True)


if __name__ == "__main__":
    main()
