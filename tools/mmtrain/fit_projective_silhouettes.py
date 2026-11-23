"""Fit positions using Mitsuba's CPU projective derivative of silhouette coverage."""

import argparse
import json
import os
from pathlib import Path
import tempfile

import numpy as np


SIZE = 128
SAMPLES = 64
MAX_STEP = 0.002
MAX_DISPLACEMENT = 0.012
ITERATIONS = 16


def scene_for(mi, path, positions, faces):
    with path.open("w", encoding="ascii", newline="\n") as mesh:
        mesh.write(f"ply\nformat ascii 1.0\nelement vertex {len(positions)}\n"
                   "property float x\nproperty float y\nproperty float z\n"
                   f"element face {len(faces)}\nproperty list uchar int vertex_indices\n"
                   "end_header\n")
        np.savetxt(mesh, positions, fmt="%.9g")
        np.savetxt(mesh, faces, fmt="3 %d %d %d")
    return mi.load_dict({
        "type": "scene",
        "integrator": {"type": "direct_projective", "sppp": SAMPLES, "sppc": 0, "sppi": 0},
        "background": {"type": "constant", "radiance": 1.0},
        "shape": {"type": "ply", "filename": str(path),
                  "bsdf": {"type": "diffuse", "reflectance": 0.0}},
    })


def sensor_for(mi, basis):
    scale = np.linalg.norm(basis[:, 0])
    distance = 3.2
    transform = mi.ScalarTransform4f().look_at(
        origin=(-distance * basis[:, 2] / scale**2).tolist(), target=[0., 0., 0.],
        up=(-basis[:, 1] / scale).tolist())
    return mi.load_dict({
        "type": "perspective", "to_world": transform, "fov_axis": "x",
        "fov": float(np.degrees(2 * np.arctan(1 / (.9 * distance)))),
        "film": {"type": "hdrfilm", "width": SIZE, "height": SIZE, "pixel_format": "rgb",
                 "sample_border": True, "rfilter": {"type": "box"}},
        "sampler": {"type": "independent", "sample_count": SAMPLES},
    })


def fit(mi, dr, source, initial, faces):
    from scipy.sparse import coo_matrix, diags, eye
    from scipy.sparse.linalg import factorized
    from fit_visible_contours import edge_incidence, fit_views, normals

    edges, _, _, counts = edge_incidence(faces)
    free = np.ones(len(initial), dtype=bool)
    free[np.unique(edges[counts == 1])] = False
    if not free.any():
        raise ValueError("No movable vertices")
    a, b = np.concatenate((edges, edges[:, ::-1])).T
    neighbors = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(initial), len(initial))).tocsc()
    laplacian = diags(np.asarray(neighbors.sum(axis=1)).ravel()) - neighbors
    solve = factorized((eye(len(initial), format="csc") + 4 * laplacian)[free, :][:, free].tocsc())
    normal0 = normals(initial, faces)
    min_dot = .2 * np.einsum("ij,ij->i", normal0, normal0)

    with tempfile.TemporaryDirectory() as directory:
        target = scene_for(mi, Path(directory) / "target.ply", *source)
        scene = scene_for(mi, Path(directory) / "fit.ply", initial, faces)
    sensors = [sensor_for(mi, basis) for basis in fit_views()]
    refs = [dr.detach(mi.render(target, sensor=sensor, seed=i + 20261124))
            for i, sensor in enumerate(sensors)]
    params = mi.traverse(scene)
    key = "shape.vertex_positions"
    params.keep([key])
    vertices = initial.copy()
    history = []

    def loss_at(points, with_gradient):
        grad = np.zeros_like(points)
        losses = []
        parameter = mi.Float(points.astype(np.float32).ravel())
        for i, (sensor, target_img) in enumerate(zip(sensors, refs, strict=True)):
            if with_gradient:
                dr.enable_grad(parameter)
            params[key] = parameter
            params.update()
            image = mi.render(scene, params if with_gradient else None, sensor=sensor,
                              seed=i + 20261124)
            loss = dr.mean(dr.square(image - target_img))
            losses.append(float(loss[0]))
            if with_gradient:
                dr.backward(loss)
                grad += dr.grad(parameter).numpy().reshape(-1, 3)
                parameter = dr.detach(parameter)
        return float(np.mean(losses)), grad / len(sensors)

    for _ in range(ITERATIONS):
        before, grad = loss_at(vertices, True)
        step = np.zeros_like(vertices)
        step[free] = -solve(grad[free])
        longest = np.linalg.norm(step, axis=1).max()
        if not np.isfinite(longest):
            raise ValueError("The projective gradient produced a nonfinite update")
        row = {"before": before, "after": before, "gradient_norm": float(np.linalg.norm(grad[free])),
               "halvings": None}
        history.append(row)
        if longest == 0:
            break
        step *= MAX_STEP / longest
        for attempt in range(7):
            offset = vertices - initial + step * (0.5**attempt)
            length = np.linalg.norm(offset, axis=1, keepdims=True)
            offset *= np.minimum(1., MAX_DISPLACEMENT / np.maximum(length, 1e-30))
            candidate = initial + offset
            orientation = np.einsum("ij,ij->i", normals(candidate, faces), normal0)
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
    from bench_contour_importance_qem import compare_images
    from preflight_appearance_meshes import (
        audit, boundary, compact, digest, load_obj, meshopt_simplify_raw, normalize, source_frame,
    )
    if digest(args.source) != args.sha256:
        parser.error("The input geometry SHA-256 differs from its frozen manifest")
    points, faces = load_obj(args.source)
    center, radius = source_frame(points)
    points = normalize(points, center, radius)
    source = compact(points, faces)
    edges = boundary(*source)
    target = len(faces) - 2 * round(len(faces) / 4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    low, indices, _ = meshopt_simplify_raw(points, faces, target, args.out.parent)
    audit_init = audit(edges, low, indices)
    if not audit_init["boundary_preserved"] or audit_init["faces"] != target:
        raise ValueError(f"Initializer is ineligible: {audit_init}")
    fitted, history = fit(mi, dr, source, low, indices)
    if history[0]["gradient_norm"] <= 0 or history[0]["before"] <= 0:
        raise ValueError("The first view batch did not produce a nonzero silhouette gradient")
    audit_fit = audit(edges, fitted, indices)
    variants = {"meshoptimizer": (low, indices)}
    if audit_fit["boundary_preserved"]:
        variants["fitted"] = (fitted, indices)
    scores = compare_images(source, variants)
    result = {
        "source_sha256": args.sha256, "script_sha256": digest(Path(__file__)),
        "mitsuba": mi.__version__, "drjit": dr.__version__, "variant": mi.variant(),
        "reference_faces": len(faces), "initial": audit_init, "fitted": audit_fit,
        "history": history, "views": scores,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: result[k] for k in ("source_sha256", "script_sha256", "mitsuba", "drjit",
                                     "variant", "reference_faces", "initial", "fitted")}
    summary["accepted_steps"] = sum(row["halvings"] is not None for row in history)
    summary["first_training_mse"] = history[0]["before"]
    summary["last_training_mse"] = history[-1]["after"]
    summary["gradient_norm"] = history[0]["gradient_norm"]
    summary["receipt_sha256"] = digest(args.out)
    summary["means"] = {arm: {key: float(np.mean([view[arm][key] for view in scores]))
                              for key in ("mse", "flip", "ssim", "silhouette_xor_fraction")}
                        for arm in variants}
    payload = json.dumps(summary, separators=(",", ":"))
    print(payload, flush=True)
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::notice file=tools/mmtrain/fit_projective_silhouettes.py,line=1,"
              f"title=Projective silhouette receipt::{payload}", flush=True)


if __name__ == "__main__":
    main()
