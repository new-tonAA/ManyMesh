#!/usr/bin/env python3
"""Vectorized analytic raster-sample crossings for a batch of projected mesh edges."""
import math

import numpy as np


def harmonic_extrema(coefficients, lo, hi):
    """Exact extrema of c + a*sin(phi) + b*cos(phi) over [lo, hi]."""
    c, a, b = (coefficients[..., i] for i in range(3))
    values = [c + a * math.sin(lo) + b * math.cos(lo),
              c + a * math.sin(hi) + b * math.cos(hi)]
    root = np.arctan2(a, b)
    for k in range(-2, 3):
        x = root + k * math.pi
        valid = (x >= lo) & (x <= hi)
        values.append(np.where(valid, c + a * np.sin(x) + b * np.cos(x), np.nan))
    stack = np.stack(values, axis=0)
    return np.nanmin(stack, axis=0), np.nanmax(stack, axis=0)


def batched_companion_roots(polynomials):
    """Roots for ascending polynomial coefficient rows with degree <= 4."""
    count = len(polynomials)
    roots = np.full((count, 4), np.nan + 1j * np.nan, dtype=np.complex128)
    if not count:
        return roots
    scale = np.maximum(np.max(np.abs(polynomials), axis=1), 1e-30)
    normalized = polynomials / scale[:, None]
    degree = np.full(count, 4, dtype=np.int8)
    for d in (3, 2, 1):
        trim = (degree == d + 1) & (np.abs(normalized[:, d + 1]) < 1e-12)
        degree[trim] = d
    degree[np.max(np.abs(normalized[:, :2]), axis=1) < 1e-30] = 0

    linear = np.flatnonzero(degree == 1)
    roots[linear, 0] = -normalized[linear, 0] / normalized[linear, 1]
    for d in (2, 3, 4):
        indices = np.flatnonzero(degree == d)
        if not len(indices):
            continue
        q = normalized[indices, :d + 1]
        companion = np.zeros((len(indices), d, d), dtype=np.float64)
        companion[:, 0, :] = -q[:, d - 1::-1] / q[:, d, None]
        if d > 1:
            companion[:, 1:, :-1] = np.eye(d - 1, dtype=np.float64)[None, :, :]
        roots[indices, :d] = np.linalg.eigvals(companion)
    return roots


def edge_event_pairs(pilot, camera_positions, edge_points, sample_coordinates,
                     start, end, size, scale):
    """Return (edge index, angle, sample x, sample y) events for all supplied edges."""
    edge_points = np.asarray(edge_points, dtype=np.float64)
    samples_xy = np.asarray(sample_coordinates, dtype=np.int64)
    if not len(edge_points) or not len(samples_xy):
        return []
    center = 0.5 * (start + end)
    offsets = np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4], dtype=np.float64)
    basis = np.column_stack((np.ones(5), np.sin(offsets), np.cos(offsets),
                             np.sin(2 * offsets), np.cos(2 * offsets)))
    inv_basis = np.linalg.inv(basis)
    flat_points = edge_points.reshape(-1, 3)
    projected_samples = []
    for offset in offsets:
        transform = pilot.camera(camera_positions, center + float(offset), size)
        projected_samples.append(pilot.project(flat_points, transform)[:, :2])
    projected = np.asarray(projected_samples).reshape(5, len(edge_points), 2, 2)
    coefficients = np.einsum("ij,jeka->ieka", inv_basis, projected)
    phi_lo, phi_hi = start - center, end - center
    min_a, max_a = harmonic_extrema(
        coefficients[:3, :, 0, :].transpose(1, 2, 0), phi_lo, phi_hi)
    min_b, max_b = harmonic_extrema(
        coefficients[:3, :, 1, :].transpose(1, 2, 0), phi_lo, phi_hi)
    xy_min = np.minimum(min_a, min_b)
    xy_max = np.maximum(max_a, max_b)
    i0 = np.maximum(0, np.floor(xy_min * scale - 0.5).astype(np.int64) - 1)
    i1 = np.minimum(size * scale - 1,
                    np.ceil(xy_max * scale - 0.5).astype(np.int64) + 1)

    sx = samples_xy[:, 0]
    sy = samples_xy[:, 1]
    events = []
    # Bound the pair workspace so larger models do not create large temporary arrays.
    edge_chunk = max(1, min(len(edge_points), 200_000 // max(1, len(samples_xy))))
    sample_xy = np.column_stack(((sx + 0.5) / scale, (sy + 0.5) / scale))
    for edge_start in range(0, len(edge_points), edge_chunk):
        edge_end = min(len(edge_points), edge_start + edge_chunk)
        candidate_mask = (
            (i0[edge_start:edge_end, 0, None] <= sx[None, :]) &
            (i1[edge_start:edge_end, 0, None] >= sx[None, :]) &
            (i0[edge_start:edge_end, 1, None] <= sy[None, :]) &
            (i1[edge_start:edge_end, 1, None] >= sy[None, :]) &
            (i1[edge_start:edge_end, 0, None] >= i0[edge_start:edge_end, 0, None]) &
            (i1[edge_start:edge_end, 1, None] >= i0[edge_start:edge_end, 1, None]))
        local_edges, sample_ids = np.nonzero(candidate_mask)
        if not len(local_edges):
            continue
        edge_ids = local_edges + edge_start
        a = projected[:, edge_ids, 0, :]
        b = projected[:, edge_ids, 1, :]
        d = b - a
        f = (d[:, :, 0] * (sample_xy[sample_ids, 1][None, :] - a[:, :, 1]) -
             d[:, :, 1] * (sample_xy[sample_ids, 0][None, :] - a[:, :, 0]))
        q = inv_basis @ f
        c0, c1, c2, c3, c4 = q
        polynomials = np.column_stack((c0 + c2 + c4,
                                       2 * c1 + 4 * c3,
                                       2 * c0 - 6 * c4,
                                       2 * c1 - 4 * c3,
                                       c0 - c2 + c4))
        roots = batched_companion_roots(polynomials)
        for pair_index in range(len(edge_ids)):
            for root in roots[pair_index]:
                if not np.isfinite(root.real) or abs(float(root.imag)) > 1e-8:
                    continue
                angle = center + 2 * math.atan(float(root.real))
                if angle < start - 1e-9 or angle > end + 1e-9:
                    continue
                phi = angle - center
                pa_coeff = coefficients[:3, edge_ids[pair_index], 0, :]
                pb_coeff = coefficients[:3, edge_ids[pair_index], 1, :]
                # Evaluate endpoint sin/cos coefficients, rather than refitting each root.
                pa = pa_coeff[0] + pa_coeff[1] * math.sin(phi) + pa_coeff[2] * math.cos(phi)
                pb = pb_coeff[0] + pb_coeff[1] * math.sin(phi) + pb_coeff[2] * math.cos(phi)
                direction = pb - pa
                denom = float(np.dot(direction, direction))
                if denom <= 1e-20:
                    continue
                sample = sample_xy[sample_ids[pair_index]]
                t = float(np.dot(sample - pa, direction) / denom)
                if -1e-7 <= t <= 1 + 1e-7:
                    events.append((int(edge_ids[pair_index]), float(angle),
                                   int(sx[sample_ids[pair_index]]),
                                   int(sy[sample_ids[pair_index]])))
    return events
