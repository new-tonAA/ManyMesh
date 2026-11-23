"""Fit a fixed mesh to source coverage using a local visible-edge derivative."""

import argparse
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.ndimage import map_coordinates
from scipy.sparse import coo_matrix, diags, eye
from scipy.sparse.linalg import factorized
from scipy.special import expit

from bench_contour_importance_qem import compare_images
from cluster_decoder_surface_quality import surface_metrics
from make_refinement_pairs import raster
from preflight_appearance_meshes import (
    audit, boundary, compact, digest, load_binary_ply, load_obj,
    meshopt_simplify_raw, normalize, source_frame,
)


SIZE = 128
SAMPLES = 3
ITERATIONS = 16
MAX_STEP = 0.002
MAX_DISPLACEMENT = 0.012
DEPTH_TOLERANCE = 0.04
OFFSETS = np.array((-1.5, -0.75, 0., 0.75, 1.5))
EDGE_WIDTH = 0.45


def fit_views():
    cameras = []
    for i in range(8):
        y = 1 - (2 * i + 1) / 8
        phi = i * np.pi * (3 - np.sqrt(5))
        eye_dir = np.array((np.sqrt(1 - y*y) * np.cos(phi), y,
                            np.sqrt(1 - y*y) * np.sin(phi)))
        right = np.cross((0, 1, 0), eye_dir)
        right /= np.linalg.norm(right)
        basis = np.stack((right, -np.cross(eye_dir, right), -eye_dir), axis=1)
        cameras.extend(basis * scale for scale in (1.0, 0.55))
    return cameras


def edge_incidence(faces):
    sides = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges, ids, count = np.unique(np.sort(sides, axis=1), axis=0,
                                  return_inverse=True, return_counts=True)
    if np.any(count > 2):
        raise ValueError("The initializer has nonmanifold edges")
    owners = np.tile(np.arange(len(faces)), 3)[np.argsort(ids, kind="stable")]
    start = np.cumsum(count) - count
    return edges, owners[start], owners[start + count - 1], count


def normals(points, faces):
    a, b, c = points[faces].transpose(1, 0, 2)
    return np.cross(b - a, c - a)


def render_coverage(points, faces, basis):
    screen = points @ basis
    screen[:, :2] = SIZE * (0.45 * screen[:, :2] + 0.5)
    raster_points = screen.astype(np.float32)
    raster_points[:, :2] *= SAMPLES
    _, depth = raster(raster_points, faces, np.ones(len(points), dtype=np.float32),
                      SIZE * SAMPLES)
    coverage = np.isfinite(depth).reshape(SIZE, SAMPLES, SIZE, SAMPLES).mean(axis=(1, 3))
    return coverage, depth, screen


def sample(image, xy):
    return map_coordinates(image, [xy[..., 1] - 0.5, xy[..., 0] - 0.5],
                           order=1, mode="constant", cval=0.0)


def strip_loss(displacement, current, target):
    """Coverage residual model for a small outward translation of a visible edge."""
    profile = expit((displacement[..., None] - OFFSETS) / EDGE_WIDTH)
    difference = current - target + profile - expit(-OFFSETS / EDGE_WIDTH)
    loss = np.mean(difference**2, axis=-1)
    derivative = np.mean(2 * difference * profile * (1 - profile) / EDGE_WIDTH, axis=-1)
    return loss, derivative


def view_gradient(screen, coverage, depth, target, basis, face_normals, incidence):
    edge, first, second, counts = incidence
    signs = face_normals @ basis[:, 2]
    visible_candidates = (counts == 1) | (signs[first] * signs[second] < 0)
    edge = edge[visible_candidates]
    p, q = screen[edge].transpose(1, 0, 2)
    length = np.linalg.norm(q[:, :2] - p[:, :2], axis=1)
    valid = length > 1e-6
    edge, p, q, length = edge[valid], p[valid], q[valid], length[valid]
    if not len(edge):
        return np.zeros((len(screen), 3)), 0
    side = (q[:, :2] - p[:, :2])[:, [1, 0]] * (-1, 1) / length[:, None]
    n = np.ceil(length).astype(int)
    t = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 0.5) / np.repeat(n, n)
    n_ids = np.repeat(np.arange(len(edge)), n)
    center = p[n_ids] + t[:, None] * (q[n_ids] - p[n_ids])
    side = side[n_ids]
    left = sample(coverage, center[:, :2] - 1.25 * side)
    right = sample(coverage, center[:, :2] + 1.25 * side)
    supported = np.abs(left - right) >= 0.7
    outward = side * np.where(left > right, 1, -1)[:, None]
    inside = np.clip(np.floor(SAMPLES * (center[:, :2] - outward)).astype(int),
                     0, SIZE * SAMPLES - 1)
    supported &= np.abs(depth[inside[:, 1], inside[:, 0]] - center[:, 2]) <= DEPTH_TOLERANCE
    t, n_ids, center, outward = t[supported], n_ids[supported], center[supported], outward[supported]
    gradient = np.zeros((len(screen), 3))
    if not len(t):
        return gradient, 0
    xy = center[:, None, :2] + outward[:, None, :] * OFFSETS[None, :, None]
    _, slope = strip_loss(np.zeros(len(t)), sample(coverage, xy), sample(target, xy))
    pixel_gradient = slope[:, None] * outward
    world_gradient = (pixel_gradient @ basis[:, :2].T) * (0.45 * SIZE)
    weights = length[n_ids] / n[n_ids]
    world_gradient *= weights[:, None] / weights.sum()
    np.add.at(gradient, edge[n_ids, 0], world_gradient * (1 - t[:, None]))
    np.add.at(gradient, edge[n_ids, 1], world_gradient * t[:, None])
    return gradient, len(t)


def fit(initial, faces, source):
    incidence = edge_incidence(faces)
    edges, _, _, counts = incidence
    free = np.ones(len(initial), dtype=bool)
    free[np.unique(edges[counts == 1])] = False
    if not free.any():
        return initial.copy(), []
    i, j = np.concatenate((edges, edges[:, ::-1])).T
    adjacency = coo_matrix((np.ones(len(i)), (i, j)), shape=(len(initial), len(initial))).tocsc()
    laplacian = diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    solve = factorized((eye(len(initial), format="csc") + 4 * laplacian)[free, :][:, free].tocsc())
    reference_normals = normals(initial, faces)
    initial_area_squared = np.einsum("ij,ij->i", reference_normals, reference_normals)
    cameras = fit_views()
    targets = [render_coverage(*source, basis)[0] for basis in cameras]
    vertices = initial.copy()
    history = []

    def training_error(points):
        return float(np.mean([np.mean((render_coverage(points, faces, basis)[0] - target)**2)
                              for basis, target in zip(cameras, targets, strict=True)]))

    for _ in range(ITERATIONS):
        gradient = np.zeros_like(vertices)
        view_errors, supports = [], []
        face_normals = normals(vertices, faces)
        for basis, target in zip(cameras, targets, strict=True):
            coverage, depth, screen = render_coverage(vertices, faces, basis)
            partial, count = view_gradient(screen, coverage, depth, target, basis,
                                           face_normals, incidence)
            gradient += partial
            supports.append(count)
            view_errors.append(np.mean((coverage - target)**2))
        before = float(np.mean(view_errors))
        step = np.zeros_like(vertices)
        step[free] = -solve(gradient[free])
        longest = np.linalg.norm(step, axis=1).max()
        row = {"before": before, "after": before, "visible_samples_by_view": supports,
               "gradient_norm": float(np.linalg.norm(gradient[free])), "step": None}
        history.append(row)
        if not np.isfinite(longest):
            raise ValueError("Nonfinite contour update")
        if longest == 0:
            break
        step *= MAX_STEP / longest
        for attempt in range(7):
            delta = vertices + step * (0.5**attempt) - initial
            length = np.linalg.norm(delta, axis=1)
            delta *= np.minimum(1., MAX_DISPLACEMENT / np.maximum(length, 1e-30))[:, None]
            candidate = initial + delta
            orientation = np.einsum("ij,ij->i", normals(candidate, faces), reference_normals)
            if np.any(orientation < 0.20 * initial_area_squared):
                continue
            after = training_error(candidate)
            if after < before - 1e-12:
                vertices = candidate
                row.update(after=after, step=attempt)
                break
        if row["step"] is None:
            break
    return vertices, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--cut", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fitted-out", type=Path,
                        help="Save the audited fitted mesh for reuse in the render harness")
    args = parser.parse_args()
    earlier = json.loads(args.preflight.read_text(encoding="utf-8"))
    prep = json.loads(args.prepared.with_suffix(".json").read_text(encoding="utf-8"))
    if (digest(args.source) != earlier["source_sha256"]
            or prep["source_sha256"] != earlier["source_sha256"]
            or digest(args.prepared) != prep["geometry_sha256"]):
        parser.error("Source and prepared mesh hashes must match the earlier receipts")
    cut_sha = digest(args.cut)
    if not any(row["candidate_ply_sha256"] == cut_sha for row in earlier["cuts"]):
        parser.error("The ManyMesh cut hash is absent from the earlier receipt")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    raw, faces = load_obj(args.source)
    center, radius = source_frame(raw)
    points = normalize(raw, center, radius)
    with np.load(args.prepared, allow_pickle=False) as packed:
        source = (packed["source_vertices"], packed["source_triangles"])
        qem = (packed["qem_vertices"], packed["qem_triangles"])
    if not np.array_equal(source[0][source[1]], points[faces]):
        parser.error("Prepared reference differs from the original source")
    ref_edges = boundary(*source)
    target = prep["target_faces"]
    meshopt_points, meshopt_faces, _ = meshopt_simplify_raw(points, faces, target, args.out.parent)
    cut_points, cut_faces = load_binary_ply(args.cut)
    variants = {
        "qem": qem,
        "manymesh": compact(normalize(cut_points, center, radius), cut_faces),
        "meshoptimizer": (meshopt_points, meshopt_faces),
    }
    audit_rows = {name: audit(ref_edges, *mesh) for name, mesh in variants.items()}
    if not all(row["faces"] == target and row["boundary_preserved"]
               for row in audit_rows.values()):
        raise ValueError(f"Ineligible fixed-face controls: {audit_rows}")
    start = time.perf_counter()
    fitted, history = fit(meshopt_points, meshopt_faces, source)
    seconds = time.perf_counter() - start
    audit_rows["fitted"] = audit(ref_edges, fitted, meshopt_faces)
    if audit_rows["fitted"]["boundary_preserved"]:
        variants["fitted"] = (fitted, meshopt_faces)
    report = {
        "source_sha256": digest(args.source), "packed_sha256": digest(args.prepared),
        "cut_sha256": cut_sha, "script_sha256": digest(Path(__file__)),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__, "scipy_version": scipy.__version__,
        "faces": target, "audits": audit_rows, "seconds": seconds,
        "max_displacement": float(np.linalg.norm(fitted - meshopt_points, axis=1).max()),
        "surface": {name: surface_metrics(source, mesh, 20000, 20261124)
                    for name, mesh in variants.items()},
        "iterations": history, "views": compare_images(source, variants),
    }
    if args.fitted_out is not None and "fitted" in variants:
        args.fitted_out.parent.mkdir(parents=True, exist_ok=True)
        with args.fitted_out.open("wb") as stream:
            np.savez_compressed(stream, positions=fitted, triangles=meshopt_faces)
        report["fitted_sha256"] = digest(args.fitted_out)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
