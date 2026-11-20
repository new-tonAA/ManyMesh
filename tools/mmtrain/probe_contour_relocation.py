"""Fit bounded vertex offsets to supersampled contours at a fixed QEM triangle count."""

import argparse
import json
from pathlib import Path
import time

import fast_simplification
import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr

from make_refinement_pairs import load_geometry, raster, vertex_normals, verify_asset, view_basis
from probe_filter_aware_cuts import FILTERS, loss, shaded


FIT_VIEWS = range(0, 12, 2)
TEST_VIEWS = range(1, 12, 2)
FIT_PHASES = ((0.0, 0.0), (0.25, -0.25), (-0.25, 0.25))
TEST_PHASES = ((0.0, 0.0), (0.31, 0.19), (-0.33, 0.21))
METRICS = ("bicubicMse", "coverageMse", "boundaryMiss", "nativeMse")


def project(vertices, basis, size, phase):
    projected = vertices @ basis
    projected[:, :2] = (projected[:, :2] * 0.45 + 0.5) * size + phase
    return projected


def render(mesh, basis, size, phase, scale):
    vertices, faces, light = mesh
    projected = project(vertices, basis, size, phase)
    projected[:, :2] *= scale
    return raster(projected, faces, light, size * scale)


def block_mean(data):
    side = data.shape[0] // 2
    return data.reshape(side, 2, side, 2).mean(axis=(1, 3)).astype(np.float32)


def sample(image, xy, order):
    # The coordinates describe points in pixel units, with centers at half integers.
    return map_coordinates(image, xy.T[::-1] - 0.5, order=order, mode="nearest")


def edge_incidence(faces):
    boundaries = np.column_stack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    flat = np.sort(boundaries.reshape(-1, 2), axis=1)
    edges, membership, count = np.unique(flat, axis=0, return_inverse=True, return_counts=True)
    return edges, membership, count


def measurements(source, coarse, normals, edges, membership, count, size):
    vertices, faces, _ = coarse
    points = vertices[faces]
    face_normal = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    all_indices, all_coefficients, all_rhs = [], [], []
    for view in FIT_VIEWS:
        basis = view_basis(view, 12)
        front = face_normal @ basis[:, 2] < 0
        front_count = np.bincount(membership, np.repeat(front, 3), minlength=len(edges))
        candidates = edges[(count == 1) | ((front_count > 0) & (front_count < count))]
        projected = project(vertices, basis, size, (0, 0))
        a, b = projected[candidates[:, 0]], projected[candidates[:, 1]]
        tangent = b[:, :2] - a[:, :2]
        length = np.linalg.norm(tangent, axis=1)
        rows = np.repeat(np.arange(len(a)), np.clip(np.ceil(length).astype(int), 1, 8))
        if not len(rows):
            continue
        samples_per_edge = np.bincount(rows, minlength=len(a))
        starts = np.cumsum(samples_per_edge) - samples_per_edge
        u = (np.arange(len(rows)) - starts[rows] + 0.5) / samples_per_edge[rows]
        point = a[rows] + u[:, None] * (b[rows] - a[rows])
        perp = tangent[rows][:, (1, 0)] * np.array([1, -1])
        perp /= np.maximum(length[rows, None], 1e-6)
        _, depth = render(coarse, basis, size, (0, 0), 4)
        left = sample(depth, 4 * (point[:, :2] - 0.65 * perp), order=0)
        right = sample(depth, 4 * (point[:, :2] + 0.65 * perp), order=0)
        silhouetted = np.isfinite(left) ^ np.isfinite(right)
        near = np.abs(point[:, 2] - np.minimum(left, right)) < 0.04
        keep = silhouetted & near & (length[rows] >= 0.35)
        point, u, indices = point[keep], u[keep], candidates[rows[keep]]
        _, reference = render(source, basis, size, (0, 0), 4)
        covered = np.isfinite(reference)
        sdf = distance_transform_edt(~covered) - distance_transform_edt(covered)
        dy, dx = np.gradient(sdf)
        xy = point[:, :2] * 4
        distance = sample(sdf, xy, order=1) / 4
        gradient = np.column_stack((sample(dx, xy, 1), sample(dy, xy, 1)))
        usable = (np.abs(distance) <= 2.0) & (np.linalg.norm(gradient, axis=1) >= 0.5)
        indices, u, distance = indices[usable], u[usable], distance[usable]
        world_direction = gradient[usable] @ basis[:, :2].T
        coefficients = np.sum(normals[indices] * world_direction[:, None, :], axis=2)
        coefficients *= np.column_stack((1 - u, u))
        all_indices.append(indices)
        all_coefficients.append(coefficients)
        all_rhs.append(-distance)
    if not all_rhs:
        return np.zeros(len(vertices)), 0
    rhs = np.concatenate(all_rhs)
    if not len(rhs):
        return np.zeros(len(vertices)), 0
    columns = np.concatenate(all_indices)
    coefficients = np.concatenate(all_coefficients)
    rows = np.repeat(np.arange(len(rhs)), 2)
    design = coo_matrix((coefficients.ravel(), (rows, columns.ravel())),
                        shape=(len(rhs), len(vertices))).tocsr()
    offsets = lsqr(design, rhs, damp=0.8, atol=1e-5, btol=1e-5, iter_lim=50)[0]
    return np.clip(offsets, -0.9, 0.9), len(rhs)


def targets(source, size, views, phases):
    references = []
    for view in views:
        basis = view_basis(view, 12)
        for phase in phases:
            rgb, depth = render(source, basis, size, phase, 4)
            coverage = np.isfinite(depth)
            thin = distance_transform_edt(coverage) <= 4.0
            feature = block_mean(coverage & thin)
            color = block_mean(rgb)
            references.append((basis, phase, color, block_mean(coverage), feature, block_mean(color)))
    return references


def auxiliary_errors(low, depth, coverage, thin, native):
    mask = np.isfinite(depth)
    expanded = np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1)
    return [np.mean((expanded - coverage) ** 2), np.mean(thin * ~expanded),
            np.mean((low - native) ** 2)]


def measure(mesh, size, references):
    cubic = FILTERS["bicubic"][0]
    sums = np.zeros(len(METRICS))
    for basis, phase, color, coverage, thin, native in references:
        low, depth = render(mesh, basis, size, phase, 1)
        sums += [loss(low, color, cubic), *auxiliary_errors(low, depth, coverage, thin, native)]
    return sums / len(references)


def valid_relocation(vertices, faces, original_normals):
    points = vertices[faces]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    squared = np.sum(original_normals ** 2, axis=1)
    dot = np.sum(normals * original_normals, axis=1)
    return (np.all(dot >= 0.2 * squared)
            and np.all(np.linalg.norm(normals, axis=1)[squared == 0] <= 1e-10))


def experiment(asset_path, size):
    start = time.perf_counter()
    vertices, faces = load_geometry(asset_path)
    source = shaded(vertices, faces)
    coarse_pos, coarse_indices = fast_simplification.simplify(
        vertices, faces, target_count=round(len(faces) * 0.2))
    if not len(coarse_indices):
        raise ValueError(f"No triangles in coarse mesh: {asset_path}")
    coarse = shaded(coarse_pos, coarse_indices)
    coarse_pos = coarse[0]
    normal = vertex_normals(coarse_pos, coarse_indices)
    edges, membership, count = edge_incidence(coarse_indices)
    offsets, samples = measurements(source, coarse, normal, edges, membership, count, size)
    points = coarse_pos[coarse_indices]
    before_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    fit = targets(source, size, FIT_VIEWS, FIT_PHASES)
    before = measure(coarse, size, fit)
    experiments = []
    for scale in (0.25, 0.5, 1.0):
        moved = coarse_pos + (offsets * scale / (0.45 * size))[:, None] * normal
        candidate = shaded(moved, coarse_indices)
        if valid_relocation(candidate[0], coarse_indices, before_normals):
            experiments.append((scale, candidate, measure(candidate, size, fit)))

    # Choose from exact-count candidates by fit-set raster error and enforce a coverage guard.
    allowed = [(factor, candidate, fitted) for factor, candidate, fitted in experiments
               if fitted[1] <= before[1] and fitted[2] <= before[2]]
    factor, candidate, fitted = min([(0.0, coarse, before), *allowed], key=lambda row: row[2][0])
    fit_ms = 1000 * (time.perf_counter() - start)
    tests = {}
    for test_size in (size, size + 32):
        references = targets(source, test_size, TEST_VIEWS, TEST_PHASES)
        tests[str(test_size)] = {
            "before": measure(coarse, test_size, references).tolist(),
            "after": measure(candidate, test_size, references).tolist(),
        }
    return {"fitScale": factor, "fitSamples": samples, "sourceFaces": len(faces),
            "faces": len(coarse_indices), "fitMs": fit_ms,
            "fitBefore": before.tolist(), "fitAfter": fitted.tolist(),
            "validCandidateScales": [entry[0] for entry in experiments], "test": tests}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_roots", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--size", type=int, choices=(64, 96, 128), default=96)
    args = parser.parse_args()
    results = {}
    for root in args.asset_roots:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for source in sources:
            name = source["name"]
            if name in results:
                parser.error(f"Duplicate asset name: {name}")
            result = experiment(verify_asset(root, source), args.size)
            results[name] = {**result, "source": source}
            row = result["test"][str(args.size)]
            gain = 1 - row["after"][0] / row["before"][0]
            print(f"{name}: {result['faces']} faces, {result['fitSamples']} samples, "
                  f"scale {result['fitScale']}, test MSE reduction {100 * gain:.2f}%", flush=True)
    report = {"size": args.size, "metrics": METRICS, "fitViews": list(FIT_VIEWS),
              "testViews": list(TEST_VIEWS), "assets": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
