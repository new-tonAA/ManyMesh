#!/usr/bin/env python3
"""Count analytic edge-versus-raster-sample events for frozen legal collapses."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


def load_pilot():
    path = Path(__file__).with_name("depth_candidate_pilot.py")
    spec = importlib.util.spec_from_file_location("edge_event_pilot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fit_first_harmonic(project, point, center):
    offsets = np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])
    basis = np.column_stack((np.ones(5), np.sin(offsets), np.cos(offsets),
                             np.sin(2 * offsets), np.cos(2 * offsets)))
    values = np.asarray([project(point[None, :], center + offset)[0, :2]
                         for offset in offsets])
    coeff = np.linalg.solve(basis, values)
    return coeff[:3]  # constant, sin(phi), cos(phi); higher harmonics are numerical residue.


def extrema(coeff, lo, hi):
    c, a, b = map(float, coeff)
    candidates = [lo, hi]
    root = math.atan2(a, b)
    for k in range(-3, 4):
        x = root + k * math.pi
        if lo <= x <= hi:
            candidates.append(x)
    return [c + a * math.sin(x) + b * math.cos(x) for x in candidates]


def event_angles_for_edge(project, a, b, start, end, size, scale, inv_basis, center,
                          sample_coordinates=None):
    lo_phi, hi_phi = start - center, end - center
    ca = fit_first_harmonic(project, a, center)
    cb = fit_first_harmonic(project, b, center)
    xy_min = np.asarray([min(min(extrema(ca[:, axis], lo_phi, hi_phi)),
                             min(extrema(cb[:, axis], lo_phi, hi_phi)))
                         for axis in range(2)])
    xy_max = np.asarray([max(max(extrema(ca[:, axis], lo_phi, hi_phi)),
                             max(extrema(cb[:, axis], lo_phi, hi_phi)))
                         for axis in range(2)])
    i0 = np.maximum(0, np.floor(xy_min * scale - 0.5).astype(int) - 1)
    i1 = np.minimum(size * scale - 1,
                    np.ceil(xy_max * scale - 0.5).astype(int) + 1)
    if np.any(i1 < i0):
        return []
    if sample_coordinates is None:
        gx, gy = np.meshgrid(np.arange(i0[0], i1[0] + 1),
                             np.arange(i0[1], i1[1] + 1))
        gx = gx.ravel()
        gy = gy.ravel()
    else:
        sample_coordinates = np.asarray(sample_coordinates, dtype=np.int64)
        keep = ((sample_coordinates[:, 0] >= i0[0]) &
                (sample_coordinates[:, 0] <= i1[0]) &
                (sample_coordinates[:, 1] >= i0[1]) &
                (sample_coordinates[:, 1] <= i1[1]))
        gx, gy = sample_coordinates[keep].T if np.any(keep) else ([], [])
        gx = np.asarray(gx, dtype=np.int64).reshape(-1)
        gy = np.asarray(gy, dtype=np.int64).reshape(-1)
    samples = np.column_stack(((np.asarray(gx) + 0.5) / scale,
                               (np.asarray(gy) + 0.5) / scale))
    fit_angles = center + np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])
    projected_a = np.asarray([project(a[None, :], angle)[0, :2] for angle in fit_angles])
    projected_b = np.asarray([project(b[None, :], angle)[0, :2] for angle in fit_angles])
    dx = projected_b[:, 0] - projected_a[:, 0]
    dy = projected_b[:, 1] - projected_a[:, 1]
    f = (dx[:, None] * (samples[None, :, 1] - projected_a[:, None, 1]) -
         dy[:, None] * (samples[None, :, 0] - projected_a[:, None, 0]))
    coefficients = inv_basis @ f
    angles = []
    for sample_index in range(samples.shape[0]):
        q = coefficients[:, sample_index]
        c0, c1, c2, c3, c4 = map(float, q)
        # Substitute tan(phi/2) into c0+c1*sin(phi)+c2*cos(phi)
        # +c3*sin(2phi)+c4*cos(2phi), clearing (1+t^2)^2.
        polynomial = np.asarray([
            c0 + c2 + c4,
            2 * c1 + 4 * c3,
            2 * c0 - 6 * c4,
            2 * c1 - 4 * c3,
            c0 - c2 + c4,
        ])
        scale_q = max(float(np.max(np.abs(polynomial))), 1e-30)
        last = 4
        while last > 0 and abs(polynomial[last]) < scale_q * 1e-12:
            last -= 1
        if last == 0:
            continue
        roots = np.roots((polynomial[:last + 1] / scale_q)[::-1])
        for root in roots:
            if abs(float(root.imag)) > 1e-8:
                continue
            angle = center + 2 * math.atan(float(root.real))
            if angle < start - 1e-9 or angle > end + 1e-9:
                continue
            pa = project(a[None, :], angle)[0, :2]
            pb = project(b[None, :], angle)[0, :2]
            d = pb - pa
            denom = float(np.dot(d, d))
            if denom <= 1e-20:
                continue
            t = float(np.dot(samples[sample_index] - pa, d) / denom)
            if -1e-7 <= t <= 1 + 1e-7:
                angles.append((angle, int(gx.ravel()[sample_index]),
                               int(gy.ravel()[sample_index])))
    return angles


def candidate_edges(positions, triangles, candidate):
    affected = np.asarray(candidate["affected"], dtype=np.int64)
    original = triangles[affected]
    post = original.copy()
    post[post == candidate["remove"]] = candidate["keep"]
    post_positions = positions.copy()
    post_positions[candidate["keep"]] = np.asarray(candidate["target"], dtype=np.float64)
    valid = ((post[:, 0] != post[:, 1]) & (post[:, 1] != post[:, 2]) &
             (post[:, 2] != post[:, 0]))
    edges = []
    for label, points, faces, face_valid in (
            ("source", positions, original, np.ones(len(original), dtype=bool)),
            ("collapsed", post_positions, post, valid)):
        for face in faces[face_valid]:
            for i in range(3):
                edges.append((label, points[face[i]], points[face[(i + 1) % 3]]))
    return edges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--ids", nargs="+", type=int, required=True)
    parser.add_argument("--start", type=float, default=2.13)
    parser.add_argument("--end", type=float, default=2.48)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start or args.scale < 1:
        parser.error("positive path extent and sample scale required")
    pilot = load_pilot()
    positions, triangles, candidates = pilot.load_capture(args.capture)
    center = 0.5 * (args.start + args.end)
    basis = np.column_stack((np.ones(5), np.sin(np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])),
                             np.cos(np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])),
                             np.sin(2 * np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4])),
                             np.cos(2 * np.asarray([-0.4, -0.2, 0.0, 0.2, 0.4]))))
    inv_basis = np.linalg.inv(basis)
    def project(points, angle):
        return pilot.project(points, pilot.camera(positions, angle, args.size))

    rows = []
    for cid in args.ids:
        if not 0 <= cid < len(candidates):
            parser.error(f"candidate ID out of range: {cid}")
        edge_events = []
        edges = candidate_edges(positions, triangles, candidates[cid])
        for label, a, b in edges:
            edge_events.extend((label, *event) for event in event_angles_for_edge(
                project, a, b, args.start, args.end, args.size, args.scale,
                inv_basis, center))
        source = [row for row in edge_events if row[0] == "source"]
        collapsed = [row for row in edge_events if row[0] == "collapsed"]
        unique = sorted(edge_events)
        unique_angles = sorted({round(row[1], 10) for row in unique})
        unique_sample_events = sorted({(round(row[1], 10), row[2], row[3])
                                       for row in unique})
        rows.append({
            "candidateId": cid,
            "affectedTriangleCount": len(candidates[cid]["affected"]),
            "edgeCount": len(edges),
            "sourceEdgeSampleEvents": len(source),
            "collapsedEdgeSampleEvents": len(collapsed),
            "uniqueEventAngles": len(unique_angles),
            "uniqueSampleAngleEvents": len(unique_sample_events),
            "uniqueEventAngleValues": unique_angles,
            "sampleCoordinates": sorted({(row[1], row[2]) for row in unique_sample_events}),
        })
        print(f"candidate={cid}: edges={len(edges)} sourceEvents={len(source)} "
              f"collapsedEvents={len(collapsed)} uniqueAngles={len(unique_angles)}",
              flush=True)

    output = {
        "scope": "analytic projected edge/sample-center crossing events on one camera segment",
        "limitations": [
            "counts changed-edge coverage events only",
            "does not include unchanged-triangle visibility/depth-order events",
            "does not integrate filtered loss",
            "candidate pool and camera path are frozen",
        ],
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "camera": {"start": args.start, "end": args.end, "size": args.size,
                   "scale": args.scale},
        "assets": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
