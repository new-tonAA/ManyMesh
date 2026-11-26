"""Recompute aggregate coverage loss on the 32 fit views, not held-out views."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np

from fit_pytorch3d_cpu_silhouette import (
    BLUR_RADIUS,
    RESOLUTION,
    SIGMA,
    SUPERSAMPLE,
    hard_coverage,
    make_rasterizer,
    soft_coverage,
    training_eyes,
)
from preflight_appearance_meshes import digest, load_obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--optimizer-protocol", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--fitted", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_bytes())
    receipt = manifest["assets"][args.asset]["frozen_exports"]
    reference_path = args.geometry_dir / "reference.obj"
    initial_path = args.geometry_dir / "meshoptimizer_lock_border.obj"
    for path in (reference_path, initial_path):
        if digest(path) != receipt["obj_exports_sha256"][path.name]:
            parser.error(f"Frozen geometry hash differs: {path}")
    fitted_receipt = json.loads((args.fitted.parent / "training.json").read_bytes())
    if digest(args.fitted) != fitted_receipt["fitted_sha256"]:
        parser.error("Fitted geometry hash differs from its training receipt")

    reference_points, reference_faces = load_obj(reference_path)
    initial_points, faces = load_obj(initial_path)
    fitted_points, fitted_faces = load_obj(args.fitted)
    if not np.array_equal(faces, fitted_faces):
        parser.error("Fitted geometry changed the fixed triangle indices")
    initial_unique, inverse = np.unique(initial_points, axis=0, return_inverse=True)
    fitted_unique = np.zeros_like(initial_unique)
    counts = np.bincount(inverse, minlength=len(initial_unique))
    np.add.at(fitted_unique, inverse, fitted_points)
    fitted_unique /= counts[:, None]
    welded_faces = inverse[faces]

    import torch
    import torch.nn.functional as functional

    if torch.__version__ != "2.4.1+cpu" or torch.cuda.is_available():
        parser.error("This protocol requires torch 2.4.1+cpu and no CUDA device")
    if importlib.metadata.version("pytorch3d") != "0.7.8":
        parser.error("This protocol requires PyTorch3D 0.7.8")
    torch.set_num_threads(2)
    evaluation_start = time.perf_counter()
    target_preprocess_seconds = 0.0
    ref = torch.as_tensor(reference_points, dtype=torch.float32)
    initial = torch.as_tensor(initial_unique, dtype=torch.float32)
    fitted = torch.as_tensor(fitted_unique, dtype=torch.float32)
    triangles = torch.as_tensor(welded_faces, dtype=torch.int64)
    reference_triangles = torch.as_tensor(reference_faces, dtype=torch.int64)
    per_view = []
    for index, eye in enumerate(training_eyes(args.optimizer_protocol)):
        target_start = time.perf_counter()
        target_rasterizer = make_rasterizer(torch, eye, RESOLUTION * SUPERSAMPLE, 0.0)
        fit_rasterizer = make_rasterizer(torch, eye, RESOLUTION * SUPERSAMPLE, BLUR_RADIUS)
        target = functional.avg_pool2d(
            hard_coverage(torch, target_rasterizer, ref, reference_triangles),
            kernel_size=SUPERSAMPLE)
        target_preprocess_seconds += time.perf_counter() - target_start
        initial_mask = functional.avg_pool2d(
            soft_coverage(torch, fit_rasterizer, initial, triangles), kernel_size=SUPERSAMPLE)
        fitted_mask = functional.avg_pool2d(
            soft_coverage(torch, fit_rasterizer, fitted, triangles), kernel_size=SUPERSAMPLE)
        per_view.append({
            "view": index,
            "initial_mse": float(functional.mse_loss(initial_mask, target)),
            "fitted_mse": float(functional.mse_loss(fitted_mask, target)),
        })

    result = {
        "asset": args.asset,
        "split": "same 32 training eyes used for fitting; not held-out evaluation",
        "manifest_sha256": digest(args.manifest),
        "optimizer_protocol_sha256": digest(args.optimizer_protocol),
        "fit_script_sha256": fitted_receipt["script_sha256"],
        "fitted_sha256": digest(args.fitted),
        "evaluator_sha256": digest(Path(__file__)),
        "torch": torch.__version__, "pytorch3d": importlib.metadata.version("pytorch3d"),
        "resolution": RESOLUTION, "supersample": SUPERSAMPLE,
        "blur_radius": BLUR_RADIUS, "sigma": SIGMA,
        "target_preprocess_seconds": target_preprocess_seconds,
        "diagnostic_total_seconds": time.perf_counter() - evaluation_start,
        "initial_mean_mse": float(np.mean([row["initial_mse"] for row in per_view])),
        "fitted_mean_mse": float(np.mean([row["fitted_mse"] for row in per_view])),
        "per_view": per_view,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
