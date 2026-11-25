"""Fit fixed-topology mesh positions to CPU-rendered neutral-material RGB images."""

import argparse
import importlib.metadata
import json
import os
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


SIZE = 96
TRAIN_SPP = 4
SCORE_SPP = 16
ITERATIONS = 8
MAX_STEP = 0.002
MAX_DISPLACEMENT = 0.012
SEED = 20261125


def write_ply(path, positions, faces):
    with path.open("w", encoding="ascii", newline="\n") as mesh:
        mesh.write(f"ply\nformat ascii 1.0\nelement vertex {len(positions)}\n"
                   "property float x\nproperty float y\nproperty float z\n"
                   f"element face {len(faces)}\nproperty list uchar int vertex_indices\n"
                   "end_header\n")
        np.savetxt(mesh, positions, fmt="%.9g")
        np.savetxt(mesh, faces, fmt="3 %d %d %d")


def scene_for(mi, path, positions, faces, differentiable):
    write_ply(path, positions, faces)
    samples = TRAIN_SPP if differentiable else SCORE_SPP
    return mi.load_dict({
        "type": "scene",
        "integrator": {"type": "direct_projective",
                       "sppp": TRAIN_SPP if differentiable else 0,
                       "sppc": TRAIN_SPP if differentiable else 0,
                       "sppi": 0},
        "background": {"type": "constant", "radiance": {"type": "rgb",
                                                              "value": [0.025, 0.025, 0.025]}},
        "key_light": {"type": "directional", "direction": [0.35, -0.8, -0.45],
                      "irradiance": {"type": "rgb", "value": [2.5, 2.5, 2.5]}},
        "shape": {"type": "ply", "filename": str(path),
                  "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb",
                                                                  "value": [0.62, 0.62, 0.62]}}},
        "sensor": {"type": "perspective",
                   "film": {"type": "hdrfilm", "width": SIZE, "height": SIZE,
                            "pixel_format": "rgb", "sample_border": True,
                            "rfilter": {"type": "box"}},
                   "sampler": {"type": "independent", "sample_count": samples}},
    })


def sensor_for(mi, basis, samples=TRAIN_SPP):
    scale = np.linalg.norm(basis[:, 0])
    distance = 3.2
    transform = mi.ScalarTransform4f().look_at(
        origin=(-distance * basis[:, 2] / scale**2).tolist(), target=[0., 0., 0.],
        up=(-basis[:, 1] / scale).tolist())
    return mi.load_dict({
        "type": "perspective", "to_world": transform, "fov_axis": "x",
        "fov": float(np.degrees(2 * np.arctan(1 / (.9 * distance)))),
        "film": {"type": "hdrfilm", "width": SIZE, "height": SIZE,
                 "pixel_format": "rgb", "sample_border": True,
                 "rfilter": {"type": "box"}},
        "sampler": {"type": "independent", "sample_count": samples},
    })


def camera_sets():
    from fit_visible_contours import fit_views
    from make_refinement_pairs import view_basis

    training = fit_views()
    yaw = np.deg2rad(13)
    rotation = np.array([[np.cos(yaw), 0., np.sin(yaw)], [0., 1., 0.],
                         [-np.sin(yaw), 0., np.cos(yaw)]])
    heldout = [rotation @ view_basis(index, 12) * scale
               for scale in (1., 0.55) for index in range(12)]
    return training, heldout


def fit(mi, dr, source, initial, faces, training_views, work_dir):
    from scipy.sparse import coo_matrix, diags, eye
    from scipy.sparse.linalg import factorized
    from fit_visible_contours import edge_incidence, normals

    edges, _, _, counts = edge_incidence(faces)
    free = np.ones(len(initial), dtype=bool)
    free[np.unique(edges[counts == 1])] = False
    if not free.any():
        raise ValueError("No movable vertices remain after locking open boundaries")
    a, b = np.concatenate((edges, edges[:, ::-1])).T
    adjacency = coo_matrix((np.ones(len(a)), (a, b)),
                           shape=(len(initial), len(initial))).tocsc()
    laplacian = diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    solve = factorized((eye(len(initial), format="csc") + 4 * laplacian)[free, :][:, free].tocsc())
    initial_normals = normals(initial, faces)
    min_dot = 0.2 * np.einsum("ij,ij->i", initial_normals, initial_normals)

    target = scene_for(mi, work_dir / "source.ply", *source, differentiable=False)
    scene = scene_for(mi, work_dir / "candidate.ply", initial, faces, differentiable=True)
    sensors = [sensor_for(mi, basis) for basis in training_views]
    references = [dr.detach(mi.render(target, sensor=sensor, seed=SEED + index))
                  for index, sensor in enumerate(sensors)]
    params = mi.traverse(scene)
    key = "shape.vertex_positions"
    params.keep([key])
    vertices = initial.copy()
    history = []

    def loss_at(points, with_gradient):
        gradient = np.zeros_like(points)
        losses = []
        parameter = mi.Float(points.astype(np.float32).ravel())
        for index, (sensor, reference) in enumerate(zip(sensors, references, strict=True)):
            if with_gradient:
                dr.enable_grad(parameter)
            params[key] = parameter
            params.update()
            image = mi.render(scene, params if with_gradient else None,
                              sensor=sensor, seed=SEED + index)
            loss = dr.mean(dr.square(image.array - reference.array))
            losses.append(float(loss[0]))
            if with_gradient:
                dr.backward(loss)
                gradient += dr.grad(parameter).numpy().reshape(-1, 3)
                parameter = dr.detach(parameter)
        return float(np.mean(losses)), gradient / len(sensors)

    for iteration in range(ITERATIONS):
        before, gradient = loss_at(vertices, True)
        step = np.zeros_like(vertices)
        step[free] = -solve(gradient[free])
        longest = float(np.linalg.norm(step, axis=1).max())
        row = {"iteration": iteration, "before": before, "after": before,
               "gradient_norm": float(np.linalg.norm(gradient[free])), "halvings": None}
        history.append(row)
        if not np.isfinite(longest):
            raise ValueError("The projective RGB gradient was nonfinite")
        if longest == 0:
            break
        step *= MAX_STEP / longest
        for attempt in range(7):
            offset = vertices - initial + step * (0.5 ** attempt)
            length = np.linalg.norm(offset, axis=1, keepdims=True)
            offset *= np.minimum(1., MAX_DISPLACEMENT / np.maximum(length, 1e-30))
            candidate = initial + offset
            orientation = np.einsum("ij,ij->i", normals(candidate, faces), initial_normals)
            if np.any(orientation < min_dot):
                continue
            after, _ = loss_at(candidate, False)
            if after < before - 1e-12:
                vertices = candidate
                row.update(after=after, halvings=attempt)
                break
        if row["halvings"] is None:
            break
    return vertices, history


def linear_to_srgb(image):
    image = np.clip(np.asarray(image, dtype=np.float64), 0., 1.)
    return np.where(image <= 0.0031308, 12.92 * image,
                    1.055 * image ** (1 / 2.4) - 0.055).astype(np.float32)


def score(mi, variants, heldout_views, work_dir):
    import flip_evaluator
    from skimage.metrics import structural_similarity

    work_dir.mkdir(parents=True, exist_ok=True)
    scenes = {
        name: scene_for(mi, work_dir / f"{name}.ply", *mesh, differentiable=False)
        for name, mesh in variants.items()
    }
    rows = []
    for view_index, basis in enumerate(heldout_views):
        sensor = sensor_for(mi, basis, SCORE_SPP)
        reference = linear_to_srgb(mi.render(scenes["source"], sensor=sensor,
                                             seed=SEED + 1000 + view_index).numpy())
        row = {"view": view_index, "basis": np.asarray(basis).tolist(),
               "screen_scale": float(np.linalg.norm(basis[:, 0])),
               "arms": {}}
        for name in ("meshoptimizer", "fitted"):
            candidate = linear_to_srgb(mi.render(scenes[name], sensor=sensor,
                                                 seed=SEED + 1000 + view_index).numpy())
            difference = reference.astype(np.float64) - candidate.astype(np.float64)
            mse = float(np.mean(difference ** 2))
            _, flip, _ = flip_evaluator.evaluate(
                reference, candidate, "LDR", inputsRGB=True, applyMagma=False,
                parameters={"ppd": 67.})
            row["arms"][name] = {
                "mse": mse,
                "psnr_db": None if mse == 0 else float(-10 * np.log10(mse)),
                "ssim": float(structural_similarity(
                    reference, candidate, data_range=1., channel_axis=2,
                    gaussian_weights=True, sigma=1.5, use_sample_covariance=False)),
                "flip": float(flip),
            }
        rows.append(row)
    means = {}
    for name in ("meshoptimizer", "fitted"):
        mse = float(np.mean([row["arms"][name]["mse"] for row in rows]))
        means[name] = {
            "pooled_mse": mse,
            "pooled_psnr_db": None if mse == 0 else float(-10 * np.log10(mse)),
            "mean_ssim": float(np.mean([row["arms"][name]["ssim"] for row in rows])),
            "mean_flip": float(np.mean([row["arms"][name]["flip"] for row in rows])),
        }
    return {"views": rows, "means": means}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import drjit as dr
    import mitsuba as mi

    mi.set_variant("llvm_ad_rgb")
    dr.set_thread_count(2)
    from cluster_decoder_surface_quality import surface_metrics
    from audit_target_budget_visibility import load_obj
    from bench_upstream_clusterlod import compact
    from compare_qem_meshopt_validation_70pct import meshopt_simplify_raw
    from preflight_appearance_meshes import audit, boundary, digest
    from score_mmgeo_obj_diagnostic_controls import normalize, source_frame

    if digest(args.source) != args.sha256:
        parser.error("The source OBJ hash differs from the pinned asset hash")
    raw_positions, raw_faces = load_obj(args.source)
    center, radius = source_frame(raw_positions)
    positions = normalize(raw_positions, center, radius)
    source = compact(positions, raw_faces)
    reference_edges = boundary(*source)
    target_faces = len(raw_faces) - 2 * round(len(raw_faces) / 4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    simplify_start = time.perf_counter()
    initial, faces, simplify_report = meshopt_simplify_raw(
        positions, raw_faces, target_faces, args.out.parent)
    simplify_seconds = time.perf_counter() - simplify_start
    init_audit = audit(reference_edges, initial, faces)
    if init_audit["faces"] != target_faces or not init_audit["boundary_preserved"]:
        raise ValueError(f"The exact-face initializer failed eligibility: {init_audit}")

    training_views, heldout_views = camera_sets()
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mm-projective-rgb-") as temporary:
        fitted, history = fit(mi, dr, source, initial, faces, training_views,
                              Path(temporary))
        fit_seconds = time.perf_counter() - start
        fit_audit = audit(reference_edges, fitted, faces)
        if not fit_audit["boundary_preserved"]:
            raise ValueError(f"The fitted mesh failed the boundary gate: {fit_audit}")
        variants = {"source": source, "meshoptimizer": (initial, faces),
                    "fitted": (fitted, faces)}
        scored = score(mi, variants, heldout_views, Path(temporary) / "score")
    max_displacement = float(np.linalg.norm(fitted - initial, axis=1).max())
    geometry_path = args.out.with_suffix(".geometry.npz")
    with geometry_path.open("wb") as geometry_file:
        np.savez_compressed(geometry_file, source_positions=source[0],
                            source_faces=source[1],
                            meshoptimizer_positions=initial,
                            meshoptimizer_faces=faces,
                            fitted_positions=fitted, fitted_faces=faces)
    result = {
        "status": "completed",
        "scope": "two reused development assets; not an asset-held-out test",
        "source_sha256": args.sha256,
        "script_sha256": digest(Path(__file__)),
        "geometry_sha256": digest(geometry_path),
        "source_faces": len(raw_faces), "target_faces": target_faces,
        "retention": target_faces / len(raw_faces),
        "simplifier": simplify_report,
        "meshoptimizer_build_seconds": simplify_seconds,
        "initial_audit": init_audit, "fitted_audit": fit_audit,
        "boundary_vertices_locked": True,
        "max_displacement": max_displacement,
        "training": {"loss": "unweighted linear-RGB MSE across the full image",
                     "integrator": "Mitsuba 3.9.0 direct_projective",
                     "variant": mi.variant(), "drjit": dr.__version__,
                     "resolution": [SIZE, SIZE], "spp_continuous": TRAIN_SPP,
                     "spp_primary_visibility": TRAIN_SPP,
                     "camera_bases": [np.asarray(basis).tolist() for basis in training_views],
                     "spp_indirect_visibility": 0, "iterations": history,
                     "accepted_steps": sum(row["halvings"] is not None for row in history),
                     "wall_seconds": fit_seconds},
        "heldout": {"camera_count": len(heldout_views), "resolution": [SIZE, SIZE],
                    "spp": SCORE_SPP, "color_metrics": "linear radiance converted to sRGB",
                    **scored},
        "surface": {name: surface_metrics(source, mesh, 20000, SEED)
                    for name, mesh in variants.items()},
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
        "package_versions": {name: importlib.metadata.version(name) for name in (
            "mitsuba", "drjit", "numpy", "scipy", "scikit-image", "flip-evaluator")},
        "platform": platform.platform(), "python": platform.python_version(),
    }
    result["decision"] = (
        "advance to a separately frozen multi-asset study"
        if (result["training"]["accepted_steps"] > 0
            and scored["means"]["fitted"]["mean_flip"]
            < scored["means"]["meshoptimizer"]["mean_flip"]
            and scored["means"]["fitted"]["pooled_psnr_db"]
            >= scored["means"]["meshoptimizer"]["pooled_psnr_db"] - 0.1
            and scored["means"]["fitted"]["mean_ssim"]
            >= scored["means"]["meshoptimizer"]["mean_ssim"] - 0.001)
        else "close this CPU full-image fit configuration")
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"asset": args.source.name, "decision": result["decision"],
                      "training_accepted_steps": result["training"]["accepted_steps"],
                      "heldout_means": scored["means"],
                      "source_sha256": args.sha256, "script_sha256": result["script_sha256"]},
                     separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
