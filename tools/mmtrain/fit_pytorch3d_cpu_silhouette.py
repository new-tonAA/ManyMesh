"""Fit fixed-topology mesh positions against CPU PyTorch3D soft coverage."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import time

import numpy as np

from preflight_appearance_meshes import audit, boundary, digest, load_obj


INITIALIZER = "meshoptimizer_lock_border.obj"
RESOLUTION = 128
SUPERSAMPLE = 2
EPOCHS = 16
BATCH_SIZE = 4
LEARNING_RATE = 0.001
MAX_DISPLACEMENT = 0.012
MIN_NORMAL_DOT_FRACTION = 0.2
DISPLACEMENT_WEIGHT = 0.1
SIGMA = 1.0 / (RESOLUTION * SUPERSAMPLE)
BLUR_RADIUS = (4.0 * SIGMA) ** 2


def welded_geometry(points, triangles):
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    return unique, inverse[triangles], inverse


def training_eyes(protocol_path):
    protocol = json.loads(protocol_path.read_bytes())
    eyes = np.asarray(protocol["protocol"]["training_eyes"], dtype=np.float32)
    if eyes.shape != (32, 3):
        raise ValueError(f"Expected 32 frozen training eyes; got {eyes.shape}")
    return eyes


def face_normals(torch, positions, triangles):
    a, b, c = positions[triangles].unbind(1)
    return torch.linalg.cross(b - a, c - a, dim=1)


def make_rasterizer(torch, eyes, image_size, blur_radius):
    from pytorch3d.renderer import FoVPerspectiveCameras, MeshRasterizer, RasterizationSettings
    from pytorch3d.renderer import look_at_view_transform

    eye = torch.as_tensor(eyes, dtype=torch.float32).reshape(1, 3)
    at = torch.zeros_like(eye)
    up = torch.tensor([[0.0, 1.0, 0.0]])
    rotation, translation = look_at_view_transform(eye=eye, at=at, up=up, device="cpu")
    cameras = FoVPerspectiveCameras(R=rotation, T=translation, fov=40.0,
                                    znear=0.05, zfar=25.0, device="cpu")
    settings = RasterizationSettings(
        image_size=image_size, blur_radius=blur_radius, faces_per_pixel=1,
        cull_backfaces=False,
    )
    return MeshRasterizer(cameras=cameras, raster_settings=settings)


def mesh(torch, positions, faces):
    from pytorch3d.structures import Meshes
    return Meshes(verts=[positions], faces=[faces])


def hard_coverage(torch, rasterizer, positions, faces):
    with torch.no_grad():
        fragments = rasterizer(mesh(torch, positions, faces))
        return (fragments.pix_to_face >= 0).any(dim=-1).to(dtype=torch.float32).unsqueeze(1)


def soft_coverage(torch, rasterizer, positions, faces):
    fragments = rasterizer(mesh(torch, positions, faces))
    valid = fragments.pix_to_face >= 0
    signed_distance = torch.sign(fragments.dists) * torch.sqrt(
        torch.abs(fragments.dists).clamp_min(1e-20)
    )
    alpha = torch.sigmoid(-signed_distance / SIGMA)
    alpha = torch.where(valid, alpha, torch.zeros_like(alpha))
    return alpha.amax(dim=-1, keepdim=False).unsqueeze(1)


def fit(torch, reference, reference_faces, initial, faces, eyes, free):
    import torch.nn.functional as functional

    torch.set_num_threads(2)
    start = torch.as_tensor(initial, dtype=torch.float32)
    triangles = torch.as_tensor(faces, dtype=torch.int64)
    reference_tensor = torch.as_tensor(reference, dtype=torch.float32)
    reference_triangles = torch.as_tensor(reference_faces, dtype=torch.int64)
    target_rasterizers = [make_rasterizer(torch, eye, RESOLUTION * SUPERSAMPLE, 0.0)
                          for eye in eyes]
    fit_rasterizers = [make_rasterizer(torch, eye, RESOLUTION * SUPERSAMPLE, BLUR_RADIUS)
                       for eye in eyes]
    targets = [functional.avg_pool2d(hard_coverage(torch, rasterizer,
                                                   reference_tensor, reference_triangles),
                                     kernel_size=SUPERSAMPLE)
               for rasterizer in target_rasterizers]

    movable = torch.as_tensor(free, dtype=torch.int64)
    parameters = torch.nn.Parameter(start[movable].clone())
    optimizer = torch.optim.Adam([parameters], lr=LEARNING_RATE)
    normal0 = face_normals(torch, start, triangles)
    min_dot = MIN_NORMAL_DOT_FRACTION * (normal0 ** 2).sum(dim=1)
    history = []
    first_gradient_norm = None
    begin = time.perf_counter()

    def current_positions():
        return start.index_copy(0, movable, parameters)

    for epoch in range(EPOCHS):
        for first in range(0, len(eyes), BATCH_SIZE):
            batch_indices = range(first, min(first + BATCH_SIZE, len(eyes)))
            optimizer.zero_grad(set_to_none=True)
            candidate = current_positions()
            losses = []
            for view in batch_indices:
                coverage = soft_coverage(torch, fit_rasterizers[view], candidate, triangles)
                coverage = functional.avg_pool2d(coverage, kernel_size=SUPERSAMPLE)
                losses.append(functional.mse_loss(coverage, targets[view]))
            image_loss = torch.stack(losses).mean()
            objective = image_loss + DISPLACEMENT_WEIGHT * (parameters - start[movable]).square().mean()
            objective.backward()
            if parameters.grad is None or not torch.isfinite(parameters.grad).all():
                raise RuntimeError("Missing or nonfinite CPU vertex gradient")
            if first_gradient_norm is None:
                first_gradient_norm = float(torch.linalg.vector_norm(parameters.grad))
                if first_gradient_norm <= 0:
                    raise RuntimeError("Training views produced no silhouette gradient")

            before = parameters.detach().clone()
            optimizer.step()
            with torch.no_grad():
                offset = parameters - start[movable]
                length = torch.linalg.vector_norm(offset, dim=1, keepdim=True)
                parameters.copy_(start[movable] + offset *
                                 (MAX_DISPLACEMENT / length.clamp_min(1e-15)).clamp(max=1.0))
                valid = False
                for attempt in range(8):
                    candidate = current_positions()
                    normals = face_normals(torch, candidate, triangles)
                    if bool(((normals * normal0).sum(dim=1) >= min_dot).all()):
                        valid = True
                        break
                    factor = 0.5 ** (attempt + 1)
                    parameters.copy_(start[movable] + (parameters - start[movable]) * factor)
                if not valid:
                    parameters.copy_(before)
            history.append({"epoch": epoch, "batch_start": first,
                            "image_mse": float(image_loss.detach()),
                            "objective": float(objective.detach()),
                            "gradient_norm": float(torch.linalg.vector_norm(parameters.grad)),
                            "normal_bound_accepted": valid})

    seconds = time.perf_counter() - begin
    with torch.no_grad():
        fitted = current_positions().cpu().numpy().astype(np.float64)
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    stats = {"fit_seconds": seconds, "peak_rss_bytes": int(rss_kib * 1024),
             "first_gradient_norm": first_gradient_norm, "history": history,
             "torch": torch.__version__, "torch_cuda_available": torch.cuda.is_available(),
             "pytorch3d": importlib.metadata.version("pytorch3d"),
             "supersampled_resolution": RESOLUTION * SUPERSAMPLE,
             "blur_radius": BLUR_RADIUS, "sigma": SIGMA}
    return fitted, stats


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--optimizer-protocol", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_bytes())
    receipt = manifest["assets"][args.asset]["frozen_exports"]
    for name in ("reference.obj", INITIALIZER, "qem_preserve_border.obj",
                 "meshoptimizer_lock_border.obj", "manymesh.obj", "neutral.mtl"):
        if digest(args.geometry_dir / name) != receipt["obj_exports_sha256"][name]:
            parser.error(f"Frozen input hash differs: {name}")

    reference_points, reference_faces = load_obj(args.geometry_dir / "reference.obj")
    original_points, initial_faces = load_obj(args.geometry_dir / INITIALIZER)
    if len(reference_faces) != receipt["source_faces"]:
        parser.error("Reference face count differs from the frozen full-source receipt")
    points, faces, inverse = welded_geometry(original_points, initial_faces)
    source_edges = boundary(reference_points, reference_faces)
    init_boundary = boundary(points, faces)
    init_audit = audit(source_edges, points, faces)
    if not init_audit["boundary_preserved"] or len(faces) != receipt["control_target_faces"]:
        parser.error("Initializer failed its frozen boundary or face-count gate")
    boundary_points = {point for _, a, b in init_boundary for point in (a, b)}
    free = np.array([i for i in np.unique(faces) if tuple(points[i]) not in boundary_points],
                    dtype=np.int64)
    if not len(free):
        parser.error("Initializer has no movable interior vertices")

    eyes = training_eyes(args.optimizer_protocol)
    result = {
        "asset": args.asset,
        "protocol": "CPU PyTorch3D soft-coverage placement screen; not the CUDA adapter",
        "manifest_sha256": digest(args.manifest),
        "optimizer_protocol_sha256": digest(args.optimizer_protocol),
        "script_sha256": digest(Path(__file__)),
        "inputs": {name: receipt["obj_exports_sha256"][name] for name in
                   ("reference.obj", INITIALIZER, "qem_preserve_border.obj",
                    "meshoptimizer_lock_border.obj", "manymesh.obj", "neutral.mtl")},
        "reference_faces": len(reference_faces), "fit_faces": len(faces),
        "initial_boundary_audit": init_audit, "welded_vertices": len(points),
        "movable_vertices": len(free), "training_eyes": eyes.tolist(),
        "resolution": RESOLUTION, "supersample": SUPERSAMPLE,
        "epochs": EPOCHS, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE,
        "max_displacement": MAX_DISPLACEMENT,
        "min_normal_dot_fraction": MIN_NORMAL_DOT_FRACTION,
        "displacement_weight": DISPLACEMENT_WEIGHT,
    }
    if args.prepare_only:
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out / "protocol.json", result)
        return

    import torch
    if torch.__version__ != "2.4.1+cpu" or torch.cuda.is_available():
        parser.error("This protocol requires torch 2.4.1+cpu and no CUDA device")
    if importlib.metadata.version("pytorch3d") != "0.7.8":
        parser.error("This protocol requires PyTorch3D 0.7.8")
    fitted, stats = fit(torch, reference_points, reference_faces, points, faces, eyes, free)
    expanded = fitted[inverse]
    fit_audit = audit(source_edges, expanded, initial_faces)
    if not fit_audit["boundary_preserved"]:
        raise RuntimeError(f"Fitted geometry failed boundary audit: {fit_audit}")
    displacement = np.linalg.norm(expanded - original_points, axis=1)
    if float(displacement.max()) > MAX_DISPLACEMENT + 1e-6:
        raise RuntimeError("Fitted geometry exceeded the displacement bound")
    result.update(stats)
    result["fit_boundary_audit"] = fit_audit
    result["maximum_displacement_observed"] = float(displacement.max())
    args.out.mkdir(parents=True, exist_ok=True)
    fitted_obj = args.out / "fitted.obj"
    with fitted_obj.open("w", encoding="ascii", newline="\n") as output:
        np.savetxt(output, expanded, fmt="v %.17g %.17g %.17g")
        np.savetxt(output, initial_faces + 1, fmt="f %d %d %d")
    result["fitted_sha256"] = digest(fitted_obj)
    write_json(args.out / "training.json", result)


if __name__ == "__main__":
    main()
