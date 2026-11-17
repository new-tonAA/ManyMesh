#!/usr/bin/env python3
"""Real mesh silhouette pilot. Geometry capture only; not PBR or production timing.

Analytic scanline interval unions handle overlapping projected triangles. Fourier features
encode signed changes to union coverage, not sums of triangle coverage (which overcount).
The independent reference uses supersampled point coverage, Gaussian filtering and downsampling.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


def project(positions, angle, size):
    center = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    radius = max(np.linalg.norm(positions - center, axis=1).max(), 1e-10)
    forward = np.array([math.sin(angle), 0.25, math.cos(angle)])
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    p = (positions - center) / radius
    return np.column_stack((size * (.5 + .43 * (p @ right)),
                            size * (.5 + .43 * (p @ up))))


def intervals(projected, triangles, size, scale=1):
    """Exact horizontal intersections, then coverage union. No depth/shading model."""
    xy = projected[triangles]
    rows = []
    for y in range(size * scale):
        py = (y + .5) / scale
        active = xy[(xy[:, :, 1].min(axis=1) <= py) & (xy[:, :, 1].max(axis=1) > py)]
        intersections = np.full((len(active), 3), np.nan)
        for e in range(3):
            a, b = active[:, e], active[:, (e + 1) % 3]
            hit = ((a[:, 1] <= py) & (b[:, 1] > py)) | ((b[:, 1] <= py) & (a[:, 1] > py))
            intersections[hit, e] = a[hit, 0] + (py - a[hit, 1]) * (
                b[hit, 0] - a[hit, 0]) / (b[hit, 1] - a[hit, 1])
        valid = np.sum(np.isfinite(intersections), axis=1) >= 2
        hits = intersections[valid]
        segments = sorted(zip(np.nanmin(hits, axis=1), np.nanmax(hits, axis=1))) if len(hits) else []
        merged = []
        for left, right in segments:
            left, right = max(0., left), min(float(size), right)
            if right <= left:
                continue
            if merged and left <= merged[-1][1] + 1e-10:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        rows.append(merged)
    return rows


def kernel(sigma):
    radius = math.ceil(4 * sigma)
    k = np.exp(-.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return k / k.sum()


def filter_axis(image, weights, axis):
    radius = len(weights) // 2
    pad = [(0, 0)] * image.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(image, pad)
    result = np.zeros_like(image)
    for i, weight in enumerate(weights):
        window = [slice(None)] * image.ndim
        window[axis] = slice(i, i + image.shape[axis])
        result += weight * padded[tuple(window)]
    return result


def reference(rows, size, scale, sigma):
    image = np.zeros((size * scale, size * scale))
    for y, spans in enumerate(rows):
        for left, right in spans:
            # Exact horizontal subpixel area, not a center hit: tiny boundary motion must
            # remain measurable. Vertical sampling still needs a convergence check.
            lo = max(0, int(math.floor(left * scale)))
            hi = min(size * scale, int(math.ceil(right * scale)))
            cells = np.arange(lo, hi)
            image[y, lo:hi] += np.maximum(0., np.minimum(cells + 1., right * scale) -
                                          np.maximum(cells, left * scale))
    weights = kernel(sigma * scale)
    image = filter_axis(filter_axis(image, weights, 1), weights, 0)
    return image.reshape(size, scale, size, scale).mean(axis=(1, 3))


def features(rows, size, scale, sigma, count):
    # Global DFT frequencies avoid aliasing from a short implicit periodic domain. A cutoff
    # is explicit: small count omits high frequencies, so quality must be measured, not assumed.
    omega = 2 * np.pi * np.arange(count) / size
    result = np.zeros((len(rows), count), dtype=np.complex128)
    for y, spans in enumerate(rows):
        for left, right in spans:
            width, middle = right - left, .5 * (right + left)
            result[y] += width * np.sinc(omega * width / (2 * np.pi)) * np.exp(-1j * omega * middle)
    # Match vertical filtering and box-downsample. Horizontal box response is sinc(omega/2).
    result = filter_axis(result, kernel(sigma * scale), 0)
    result = result.reshape(size, scale, count).mean(axis=1)
    weights = np.sqrt(np.where(np.arange(count) == 0, 1., 2.) / size)
    return result * (weights * np.exp(-.5 * sigma * sigma * omega * omega) *
                     np.sinc(omega / (2 * np.pi)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--size', type=int, default=128)
    parser.add_argument('--scale', type=int, default=3)
    parser.add_argument('--candidates', type=int, default=16)
    args = parser.parse_args()
    if min(args.size, args.scale, args.candidates) < 1:
        parser.error('positive size, scale, candidates required')
    data = json.loads(args.capture.read_text())
    units = [u for u in data['units'] if u['triangles']]
    positions = np.concatenate([np.asarray(u['positions'], dtype=float) for u in units])
    triangles, candidates = [], []
    vertex_offset = face_offset = 0
    for u in units:
        tri = np.asarray(u['triangles'], dtype=np.int64)
        triangles.extend(tri + vertex_offset)
        for c in u['candidates']:
            candidates.append(dict(c, remove=c['remove'] + vertex_offset,
                                   keep=c['keep'] + vertex_offset,
                                   affected=[x + face_offset for x in c['affected']]))
        vertex_offset += len(u['positions'])
        face_offset += len(tri)
    triangles = np.asarray(triangles, dtype=np.int64)
    # Deterministic spread plus best original-priority candidate, not a cherry-picked oracle pool.
    order = sorted(range(len(candidates)), key=lambda i: (candidates[i]['priority'], i))
    selected = [order[i] for i in np.unique(np.linspace(0, len(order)-1,
                 min(args.candidates, len(order))).astype(int))] if order else []
    report = dict(scope='opaque silhouette only; orthographic; development assets',
                  captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                  size=args.size, scale=args.scale, sigma=.9, sourceTriangles=len(triangles),
                  legalCandidates=len(candidates), candidateSampling='uniform priority quantiles',
                  frames=[])
    sigma = .9
    for angle in (0.2, 1.7, 3.4):
        p = project(positions, angle, args.size)
        start = time.perf_counter()
        base_rows = intervals(p, triangles, args.size, args.scale)
        base = reference(base_rows, args.size, args.scale, sigma)
        counts = (8, 16, 32, 64)
        base_features = {k: features(base_rows, args.size, args.scale, sigma, k) for k in counts}
        frame = dict(angle=angle, setupSeconds=time.perf_counter()-start, candidates=[])
        for index in selected:
            c = candidates[index]
            # Keep projection frame identical; project target through the same normalized frame.
            center = (positions.min(axis=0) + positions.max(axis=0)) * .5
            radius = max(np.linalg.norm(positions-center, axis=1).max(), 1e-10)
            forward = np.array([math.sin(angle), .25, math.cos(angle)])
            forward /= np.linalg.norm(forward)
            right = np.cross(forward, [0, 1, 0]); right /= np.linalg.norm(right)
            up = np.cross(right, forward)
            changed_p = p.copy()
            q = (np.asarray(c['target'])-center)/radius
            changed_p[c['keep']] = args.size * np.array([.5+.43*q@right, .5+.43*q@up])
            changed_tri = triangles.copy()
            changed_tri[changed_tri == c['remove']] = c['keep']
            valid = ((changed_tri[:,0] != changed_tri[:,1]) &
                     (changed_tri[:,1] != changed_tri[:,2]) &
                     (changed_tri[:,2] != changed_tri[:,0]))
            changed_tri = changed_tri[valid]
            start = time.perf_counter()
            rows = intervals(changed_p, changed_tri, args.size, args.scale)
            extraction = time.perf_counter()-start
            start = time.perf_counter()
            image = reference(rows, args.size, args.scale, sigma)
            raster = time.perf_counter()-start
            actual = float(np.square(image-base).sum())
            predictions = []
            for k in counts:
                start = time.perf_counter()
                residual = features(rows, args.size, args.scale, sigma, k)-base_features[k]
                predictions.append(dict(frequencies=k, error=float(np.vdot(residual,residual).real),
                                        seconds=time.perf_counter()-start))
            frame['candidates'].append(dict(id=index, priority=c['priority'],
                triangles=len(changed_tri), actualError=actual, extractionSeconds=extraction,
                rasterSeconds=raster, predictions=predictions))
        report['frames'].append(frame)
        print(f'{args.capture.stem}: angle={angle}, candidates={len(selected)}', flush=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
