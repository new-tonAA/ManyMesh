#!/usr/bin/env python3
"""Small 2D tile screen for exact shared-envelope events vs dense local redraw.

The image is only 8x8 pixels with 2x2 spatial samples. Common unchanged geometry is rasterized
analytically into per-ray depth envelopes once; each collapse then redraws its local faces against
that common envelope. This bounded-memory CPU probe is not a production renderer benchmark.
"""

import argparse
import bisect
import hashlib
import json
import time
from pathlib import Path

from probe_real_collapse_depth_events import (
    DEFAULT_CAPTURE,
    camera_coordinates,
    camera_frame,
    exact_envelope_overlay,
    mesh_lines,
    mesh_lines_for_ids,
    integrate_square_line,
    overlay_events,
    upper_envelope,
)
from probe_shared_depth_envelope_batch import candidate_geometry, choose_local_candidates


def dense_visible(common, starts, local, t):
    index = bisect.bisect_right(starts, t) - 1
    best = None
    if 0 <= index < len(common):
        segment = common[index]
        if segment["lo"] < t < segment["hi"]:
            best = segment["line"]
    best_depth = (best["slope"] * t + best["intercept"]
                  if best is not None else -float("inf"))
    for line in local:
        if line["lo"] < t < line["hi"]:
            depth = line["slope"] * t + line["intercept"]
            if depth > best_depth:
                best, best_depth = line, depth
    return best


def dense_image_energy(pixel_cache, path, steps):
    lo, hi = map(float, path)
    dt = (hi - lo) / steps
    total = 0.0
    for step in range(steps):
        t = lo + (step + 0.5) * dt
        image_energy = 0.0
        for samples in pixel_cache:
            coverage = 0.0
            depth = 0.0
            for common, starts, source_local, candidate_local, weight in samples:
                source = dense_visible(common, starts, source_local, t)
                candidate = dense_visible(common, starts, candidate_local, t)
                coverage += weight * (int(source is not None) - int(candidate is not None))
                if source is not None:
                    depth += weight * (source["slope"] * t + source["intercept"])
                if candidate is not None:
                    depth -= weight * (candidate["slope"] * t + candidate["intercept"])
            image_energy += coverage * coverage + depth * depth
        total += image_energy * dt
    return total


def exact_cached_source_events(pixel_samples, source_events, path):
    """Exact overlay that reuses source-side events across candidate collapses."""
    events = {float(path[0]), float(path[1])}
    for index, (common, _starts, _source_local, candidate_local, _weight) in enumerate(pixel_samples):
        events.update(source_events[index])
        target, _depth_count = overlay_events(common, candidate_local, path)
        events.update(target)
    ordered = sorted(events)
    energy = 0.0
    for lo, hi in zip(ordered, ordered[1:]):
        mid = 0.5 * (lo + hi)
        coverage = 0.0
        depth_slope = 0.0
        depth_intercept = 0.0
        for common, _starts, source_local, candidate_local, weight in pixel_samples:
            source = dense_visible(common, _starts, source_local, mid)
            candidate = dense_visible(common, _starts, candidate_local, mid)
            coverage += weight * (int(source is not None) - int(candidate is not None))
            if source is not None:
                depth_slope += weight * source["slope"]
                depth_intercept += weight * source["intercept"]
            if candidate is not None:
                depth_slope -= weight * candidate["slope"]
                depth_intercept -= weight * candidate["intercept"]
        energy += ((hi - lo) * coverage * coverage +
                   integrate_square_line(depth_slope, depth_intercept, lo, hi))
    return max(0.0, energy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--seed-candidate", type=int, default=44000)
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--grid", type=int, default=8,
                        help="pixels per tile side; keep small to bound setup work")
    parser.add_argument("--subpixels", type=int, default=2,
                        help="regular samples per pixel side")
    parser.add_argument("--steps", type=int, nargs="+", default=[128, 512, 2048])
    parser.add_argument("--out", type=Path,
                        default=Path("out/shared-envelope-2d-tile-20261119.json"))
    args = parser.parse_args()
    if args.grid <= 0 or args.subpixels <= 0 or any(step <= 0 for step in args.steps):
        parser.error("grid, subpixels, and path steps must be positive")

    data = json.loads(args.capture.read_text(encoding="utf-8"))
    unit = data["units"][0]
    raw_positions = unit["positions"]
    triangles = [list(map(int, face)) for face in unit["triangles"]]
    candidates = unit["candidates"]
    candidate_ids = choose_local_candidates(
        candidates, triangles, args.seed_candidate, args.candidate_limit)
    frame = camera_frame(raw_positions, args.angle)
    positions = camera_coordinates(raw_positions, frame).tolist()

    batch_local_faces = set()
    batch_vertices = set()
    target_points = []
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        target_points.append(candidate["target"])
        _post, _faces, _valid, local = candidate_geometry(positions, triangles, candidate)
        batch_local_faces.update(local)
        batch_vertices.update(map(int, (candidate["remove"], candidate["keep"])))
    for face_id in tuple(batch_local_faces):
        batch_vertices.update(triangles[face_id])

    bounds_points = [positions[v] for v in batch_vertices] + target_points
    xs = [point[0] for point in bounds_points]
    ys = [point[1] for point in bounds_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    path_radius = max(0.02, 0.75 * (max_x - min_x))
    path = (-path_radius, path_radius)
    # Cover the full locally affected footprint swept by the camera path, with a small margin.
    x_lo, x_hi = min_x - path_radius, max_x + path_radius
    y_pad = max((max_y - min_y) * 0.1, path_radius / args.grid)
    y_lo, y_hi = min_y - y_pad, max_y + y_pad
    common_face_ids = [i for i in range(len(triangles)) if i not in batch_local_faces]
    pixel_step_x = (x_hi - x_lo) / args.grid
    pixel_step_y = (y_hi - y_lo) / args.grid

    # Each entry is one output pixel with a regular subpixel reconstruction filter.
    pixel_rays = []
    for py in range(args.grid):
        for px in range(args.grid):
            taps = []
            for sy in range(args.subpixels):
                for sx in range(args.subpixels):
                    fx = (sx + 0.5) / args.subpixels - 0.5
                    fy = (sy + 0.5) / args.subpixels - 0.5
                    sample_x = x_lo + (px + 0.5 + fx) * pixel_step_x
                    sample_y = y_lo + (py + 0.5 + fy) * pixel_step_y
                    taps.append((sample_x, sample_y, 1.0 / (args.subpixels ** 2)))
            pixel_rays.append(taps)

    setup_start = time.perf_counter()
    ray_cache = []
    line_visits = 0
    for taps in pixel_rays:
        cached_taps = []
        for sample_x, sample_y, weight in taps:
            source_lines = mesh_lines(positions, triangles, sample_y, sample_x, path)
            line_visits += len(triangles)
            source_by_face = {line["face"]: line for line in source_lines}
            common_lines = [source_by_face[i] for i in common_face_ids if i in source_by_face]
            union_source = [source_by_face[i] for i in batch_local_faces if i in source_by_face]
            common, _events, _depth = upper_envelope(common_lines, path)
            starts = [segment["lo"] for segment in common]
            cached_taps.append((sample_x, sample_y, weight, common, starts,
                                union_source, source_by_face))
        ray_cache.append(cached_taps)
    common_setup_seconds = time.perf_counter() - setup_start

    source_events_start = time.perf_counter()
    source_event_cache = []
    for taps in ray_cache:
        source_event_cache.append([
            overlay_events(tap[3], tap[5], path)[0] for tap in taps
        ])
    shared_source_event_seconds = time.perf_counter() - source_events_start

    exact_seconds = 0.0
    legacy_audit_seconds = 0.0
    legacy_audit_difference = None
    local_setup_seconds = 0.0
    dense_totals = {step: {"seconds": 0.0, "absoluteErrorSum": 0.0,
                           "maxRelativeError": 0.0} for step in args.steps}
    candidate_rows = []
    nonzero_pixels = 0
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        post_positions, faces_by_id, _valid, local_faces = candidate_geometry(
            positions, triangles, candidate)
        unchanged_union = batch_local_faces - set(local_faces)
        local_start = time.perf_counter()
        candidate_pixel_cache = []
        for taps in ray_cache:
            pixel_samples = []
            for sample_x, sample_y, weight, common, starts, source_union, source_by_face in taps:
                unchanged_source = [source_by_face[i] for i in unchanged_union
                                    if i in source_by_face]
                candidate_lines = mesh_lines_for_ids(
                    post_positions, faces_by_id, local_faces, sample_y, sample_x, path)
                source_local = source_union
                candidate_local = unchanged_source + candidate_lines
                pixel_samples.append((common, starts, source_local, candidate_local, weight))
            candidate_pixel_cache.append(pixel_samples)
        local_setup_seconds += time.perf_counter() - local_start

        exact_start = time.perf_counter()
        exact_image_energy = 0.0
        for pixel_index, samples in enumerate(candidate_pixel_cache):
            exact_image_energy += exact_cached_source_events(
                samples, source_event_cache[pixel_index], path)
        exact_seconds += time.perf_counter() - exact_start
        if candidate_id == candidate_ids[0]:
            legacy_start = time.perf_counter()
            legacy_energy = 0.0
            for samples in candidate_pixel_cache:
                exact_cache = [(common, source_local, candidate_local, weight)
                               for common, _starts, source_local, candidate_local, weight in samples]
                pixel_energy, _events, _depth_events = exact_envelope_overlay(exact_cache, path)
                legacy_energy += pixel_energy
            legacy_audit_seconds = time.perf_counter() - legacy_start
            legacy_audit_difference = abs(legacy_energy - exact_image_energy)
        if exact_image_energy > 1e-12:
            nonzero_pixels += 1

        row = {"candidateId": candidate_id, "exactImageEnergy": exact_image_energy,
               "dense": []}
        for step in args.steps:
            started = time.perf_counter()
            dense_energy = dense_image_energy(candidate_pixel_cache, path, step)
            elapsed = time.perf_counter() - started
            abs_error = abs(dense_energy - exact_image_energy)
            rel_error = abs_error / max(abs(exact_image_energy), 1e-12)
            aggregate = dense_totals[step]
            aggregate["seconds"] += elapsed
            aggregate["absoluteErrorSum"] += abs_error
            aggregate["maxRelativeError"] = max(aggregate["maxRelativeError"], rel_error)
            row["dense"].append({"steps": step, "energy": dense_energy,
                                 "seconds": elapsed, "absoluteError": abs_error,
                                 "relativeError": rel_error})
        candidate_rows.append(row)

    output = {
        "scope": "small 2D orthographic tile; regular subpixel taps; shared common depth envelopes",
        "warning": "CPU software visibility screen, not a production 2D/GPU renderer benchmark",
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seedCandidate": args.seed_candidate,
        "cameraAngle": args.angle,
        "grid": [args.grid, args.grid],
        "subpixelsPerSide": args.subpixels,
        "candidateIds": candidate_ids,
        "candidateCount": len(candidate_ids),
        "candidatesWithNonzeroTileLoss": nonzero_pixels,
        "sourceTriangles": len(triangles),
        "batchLocalFaceUnion": len(batch_local_faces),
        "path": path,
        "tileBounds": [x_lo, x_hi, y_lo, y_hi],
        "rays": len(ray_cache) * (args.subpixels ** 2),
        "commonTriangleScanVisits": line_visits,
        "commonSetupSeconds": common_setup_seconds,
        "sharedSourceEventSeconds": shared_source_event_seconds,
        "candidateLocalSetupSeconds": local_setup_seconds,
        "exactEventSeconds": exact_seconds,
        "legacyExactAuditSeconds": legacy_audit_seconds,
        "legacyExactAuditDifference": legacy_audit_difference,
        "denseTotals": {str(step): values for step, values in dense_totals.items()},
        "candidateResults": candidate_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "candidateCount", "candidatesWithNonzeroTileLoss", "rays",
        "commonTriangleScanVisits", "commonSetupSeconds", "candidateLocalSetupSeconds",
        "sharedSourceEventSeconds", "exactEventSeconds", "legacyExactAuditSeconds",
        "legacyExactAuditDifference", "denseTotals")}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
