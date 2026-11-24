"""Run a constrained placement-only control with NVIDIA's external renderer."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np

from preflight_appearance_meshes import audit, boundary, digest, load_obj


NVDIFFMODELING_REVISION = "9b2ba2eff83c7d90127f78c20773b06ddc3ae1db"
NVDIFFMODELING_SRC_SHA256 = "92a6f21a63bb608b834a83e8dfe579e35e48f05c8d52a9bb4380718a60904ffc"
NVDIFFRAST_VERSION = "0.4.0"
NVDIFFRAST_REVISION = "253ac4fcea7de5f396371124af597e6cc957bfae"
INITIALIZER = "meshoptimizer_lock_border.obj"
SIZE, SPP, BATCH, EPOCHS = 128, 2, 4, 16
TRAINING_MSAA = False
TRAINING_EDGE_ANTIALIAS = True
LEARNING_RATE = 0.001
MAX_DISPLACEMENT = 0.012
NORMAL_DOT_FRACTION = 0.2
DISPLACEMENT_WEIGHT = 0.1


def source_tree_digest(root):
    files = sorted((p.relative_to(root).as_posix(), p) for p in (root / "src").rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    sha = hashlib.sha256()
    for relative, path in files:
        sha.update(relative.encode("ascii") + b"\0" + bytes.fromhex(digest(path)))
    return sha.hexdigest()


def training_eyes():
    index = np.arange(16, dtype=np.float64)
    y = 1 - (2 * index + 1) / len(index)
    azimuth = 1.16 + index * np.pi * (3 - np.sqrt(5))
    radius = np.sqrt(1 - y * y)
    direction = np.stack((radius * np.cos(azimuth), y, radius * np.sin(azimuth)), axis=1)
    # Interleave directions in each minibatch and vary the sampled scale.
    cameras = direction[[(5 * i) % len(index) for i in range(len(index))]]
    near_first = np.arange(len(index)) % 2 == 0
    near = np.where(near_first, 3.3, 5.2)
    far = np.where(near_first, 5.2, 3.3)
    return np.concatenate((cameras * near[:, None], cameras * far[:, None]))


def welded_geometry(positions, triangles):
    points, inverse = np.unique(positions, axis=0, return_inverse=True)
    return points, inverse[triangles], inverse


def free_vertices(points, faces, edges):
    locked = {point for _, a, b in edges for point in (a, b)}
    return np.array([index for index in np.unique(faces) if tuple(points[index]) not in locked],
                    dtype=np.int64)


def face_normals(torch, positions, triangles):
    a, b, c = positions[triangles].unbind(1)
    return torch.linalg.cross(b - a, c - a, dim=1)


def flat_mesh(torch, mesh, loader, positions, triangles, appearance):
    normals = torch.nn.functional.normalize(face_normals(torch, positions, triangles), dim=1)
    geometry = mesh.Mesh(v_pos=positions, t_pos_idx=triangles, v_nrm=normals,
                         material=appearance, base=loader)
    return mesh.compute_tangents(geometry).eval()


def bounded_update(torch, before, attempted, start, valid):
    """Project to the displacement ball and backtrack before accepting a step."""
    offset = attempted - start
    length = torch.linalg.vector_norm(offset, dim=1, keepdim=True)
    end = start + offset * (MAX_DISPLACEMENT / length.clamp_min(1e-15)).clamp(max=1.)
    for attempt in range(7):
        candidate = before + (end - before) * (0.5 ** attempt)
        if valid(candidate):
            return candidate
    return before


def train(torch, dr, geometry, reference, initial, eyes, free):
    from src import mesh, obj, render, util

    ctx = dr.RasterizeCudaContext()
    device = torch.device("cuda", torch.cuda.current_device())
    origin, triangles, _ = initial
    positions = torch.as_tensor(origin, dtype=torch.float32, device=device)
    faces = torch.as_tensor(triangles, dtype=torch.int64, device=device)
    movable = torch.as_tensor(free, device=device)
    start = positions[movable]
    parameters = torch.nn.Parameter(start.clone())
    optimizer = torch.optim.Adam([parameters], lr=LEARNING_RATE)
    initial_normals = face_normals(torch, positions, faces)
    minimum_dot = NORMAL_DOT_FRACTION * (initial_normals ** 2).sum(dim=1)

    full_obj = obj.load_obj(str(geometry / "reference.obj"))
    low_obj = obj.load_obj(str(geometry / INITIALIZER))
    appearance = {**full_obj.material, "bsdf": "diffuse"}

    full_positions, full_triangles, _ = reference
    full = flat_mesh(torch, mesh, full_obj,
                     torch.as_tensor(full_positions, dtype=torch.float32, device=device),
                     torch.as_tensor(full_triangles, dtype=torch.int64, device=device), appearance)
    near = 0.05
    projection = util.projection(near * np.tan(np.deg2rad(20.)), n=near, f=25.)
    matrices = np.stack([projection @ util.lookAt(eye, np.zeros(3), np.array([0., 1., 0.]))
                         for eye in eyes])
    batches = [(matrices[i:i+BATCH], eyes[i:i+BATCH]) for i in range(0, len(eyes), BATCH)]

    def draw(geometry, camera):
        matrix, eye = camera
        return render.render_mesh(ctx, geometry, matrix, eye, eye, np.array([2., 2., 2.]),
                                  SIZE, spp=SPP, msaa=TRAINING_MSAA,
                                  antialias=TRAINING_EDGE_ANTIALIAS)

    def candidate():
        return flat_mesh(torch, mesh, low_obj, positions.index_copy(0, movable, parameters),
                         faces, appearance)

    def image_mse(geometry, target, camera):
        return torch.nn.functional.mse_loss(draw(geometry, camera), target)

    def evaluate():
        with torch.no_grad():
            low = candidate()
            return float(torch.stack([image_mse(low, target, camera)
                                      for target, camera in zip(targets, batches, strict=True)]).mean())

    def valid(proposed):
        new_normals = face_normals(torch, positions.index_copy(0, movable, proposed), faces)
        return bool(((new_normals * initial_normals).sum(dim=1) >= minimum_dot).all())

    torch.cuda.synchronize(device)
    torch.cuda.reset_peak_memory_stats(device)
    start_time = time.perf_counter()
    with torch.no_grad():
        targets = [draw(full, camera) for camera in batches]
    initial_mse = evaluate()
    if not np.isfinite(initial_mse):
        raise RuntimeError("Nonfinite image loss before training")
    losses = []
    first_gradient_norm = None
    for _ in range(EPOCHS):
        for camera, target in zip(batches, targets, strict=True):
            optimizer.zero_grad(set_to_none=True)
            mse = image_mse(candidate(), target, camera)
            objective = mse + DISPLACEMENT_WEIGHT * (parameters - start).square().mean()
            objective.backward()
            if parameters.grad is None or not torch.isfinite(parameters.grad).all():
                raise RuntimeError("Missing or nonfinite position gradient")
            if first_gradient_norm is None:
                first_gradient_norm = float(torch.linalg.vector_norm(parameters.grad))
            with torch.no_grad():
                before = parameters.clone()
                optimizer.step()
                parameters.copy_(bounded_update(torch, before, parameters, start, valid))
            losses.append(float(mse.detach()))
    final_mse = evaluate()
    if not np.isfinite(final_mse):
        raise RuntimeError("Nonfinite image loss after training")
    output = positions.index_copy(0, movable, parameters.detach()).cpu().numpy()
    torch.cuda.synchronize(device)
    stats = {"initial_image_mse": initial_mse, "final_image_mse": final_mse,
             "first_batch_position_gradient_norm": first_gradient_norm,
             "batch_image_mse": losses, "seconds": time.perf_counter() - start_time,
             "peak_torch_cuda_allocated_bytes": torch.cuda.max_memory_allocated(device),
             "peak_torch_cuda_reserved_bytes": torch.cuda.max_memory_reserved(device),
             "device": torch.cuda.get_device_name(device), "torch": torch.__version__,
             "torch_cuda": torch.version.cuda, "nvdiffrast": importlib.metadata.version("nvdiffrast")}
    return output, stats


def write_json(path, result):
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--geometry-dir", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true",
                        help="Verify inputs and emit the frozen protocol without loading CUDA")
    args = parser.parse_args()

    tree_sha = source_tree_digest(args.upstream)
    if tree_sha != NVDIFFMODELING_SRC_SHA256:
        parser.error("The external NVIDIA source tree differs from the protocol revision")
    manifest = json.loads(args.manifest.read_bytes())
    receipt = manifest["assets"][args.asset]["frozen_exports"]
    for name in ("reference.obj", INITIALIZER, "neutral.mtl"):
        if digest(args.geometry_dir / name) != receipt["obj_exports_sha256"][name]:
            parser.error(f"Frozen OBJ/MTL digest differs: {name}")
    reference = load_obj(args.geometry_dir / "reference.obj")
    initial = load_obj(args.geometry_dir / INITIALIZER)
    if len(reference[1]) != receipt["source_faces"] or len(initial[1]) != receipt["control_target_faces"]:
        parser.error("Unexpected source or initializer face count")
    reference_edges = boundary(*reference)
    initial_edges = boundary(*initial)
    if not audit(reference_edges, *initial)["boundary_preserved"]:
        parser.error("Initializer failed the source boundary check")
    low = welded_geometry(*initial)
    high = welded_geometry(*reference)
    free = free_vertices(*low[:2], initial_edges)
    if not len(free):
        parser.error("Initializer has no movable vertices")
    eyes = training_eyes()
    result = {"asset": args.asset, "manifest_sha256": digest(args.manifest),
              "script_sha256": digest(Path(__file__)), "nvdiffmodeling_revision": NVDIFFMODELING_REVISION,
              "nvdiffmodeling_src_sha256": tree_sha, "required_nvdiffrast": NVDIFFRAST_VERSION,
              "nvdiffrast_release_revision": NVDIFFRAST_REVISION,
              "scorer_sha256": digest(Path(__file__).with_name("bench_appearance_controls.py")),
              "preflight_script_sha256": digest(Path(__file__).with_name("preflight_appearance_meshes.py")),
              "inputs": {k: receipt["obj_exports_sha256"][k]
                         for k in ("reference.obj", INITIALIZER, "neutral.mtl")},
              "source_faces": len(reference[1]), "fitted_faces": len(initial[1]),
              "initializer_vertices": len(initial[0]), "welded_vertices": len(low[0]),
              "movable_welded_vertices": len(free), "initializer_boundary_edges": len(initial_edges),
              "training_eyes": eyes.tolist(), "resolution": SIZE, "supersample_axis": SPP,
              "training_rasterization": {
                  "render_resolution": SIZE * SPP,
                  "msaa": TRAINING_MSAA,
                  "nvdiffrast_edge_antialias": TRAINING_EDGE_ANTIALIAS,
                  "resolve": "2x2 box average after edge antialiasing",
              },
              "batch_size": BATCH, "epochs": EPOCHS, "learning_rate": LEARNING_RATE,
              "maximum_displacement": MAX_DISPLACEMENT, "min_normal_dot_fraction": NORMAL_DOT_FRACTION,
              "displacement_weight": DISPLACEMENT_WEIGHT}
    if args.prepare_only:
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out / "protocol.json", result)
        return

    import torch
    if not torch.cuda.is_available():
        parser.error("Training requires a CUDA-capable PyTorch installation and NVIDIA GPU")
    try:
        rasterizer_version = importlib.metadata.version("nvdiffrast")
    except importlib.metadata.PackageNotFoundError:
        rasterizer_version = None
    if rasterizer_version != NVDIFFRAST_VERSION:
        parser.error(f"Install nvdiffrast {NVDIFFRAST_VERSION} for this protocol")
    import nvdiffrast.torch as dr
    sys.path.insert(0, str(args.upstream.resolve()))
    fitted, stats = train(torch, dr, args.geometry_dir, high, low, eyes, free)
    fitted = fitted[low[2]].astype(np.float64)
    if not np.isfinite(fitted).all() or boundary(fitted, initial[1]) != initial_edges:
        raise RuntimeError("Fitted geometry failed the exact directed boundary check")
    result.update(stats)
    result["maximum_displacement_observed"] = float(np.linalg.norm(fitted - initial[0], axis=1).max())

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "fitted.obj"
    with path.open("w", encoding="ascii", newline="\n") as obj:
        np.savetxt(obj, fitted, fmt="v %.17g %.17g %.17g")
        np.savetxt(obj, initial[1] + 1, fmt="f %d %d %d")
    result["fitted_sha256"] = digest(path)
    write_json(args.out / "training.json", result)


if __name__ == "__main__":
    main()
