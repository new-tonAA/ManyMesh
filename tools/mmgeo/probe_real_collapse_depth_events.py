#!/usr/bin/env python3
"""Single legal Monkey collapse: filtered depth-event integral vs dense path sampling.

This CPU-only probe uses the frozen legal-candidate capture, an orthographic x-translation,
and three 1D filter samples. It measures neither full-image error nor an end-to-end speedup.
"""

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np


DEFAULT_CAPTURE = Path("out/filter-real-candidates/monkey.json")
DEFAULT_CANDIDATE = 5852
FILTER_OFFSETS = (-0.005, 0.0, 0.005)
FILTER_WEIGHTS = (0.25, 0.50, 0.25)
CAMERA_ANGLE = 2.13


def camera_frame(points, angle):
    points = np.asarray(points, dtype=np.float64)
    center = 0.5 * (points.min(axis=0) + points.max(axis=0))
    radius = max(float(np.linalg.norm(points - center, axis=1).max()), 1e-12)
    forward = np.asarray([math.sin(angle), 0.37, math.cos(angle)])
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    basis = np.stack((right, up, forward))
    return center, radius, basis


def camera_coordinates(points, frame):
    center, radius, basis = frame
    return ((np.asarray(points, dtype=np.float64) - center) / radius) @ basis.T


def triangle_depth_line(positions, triangle, sample_y, sample_x, path):
    p = [positions[int(index)] for index in triangle]
    intersections = []
    for a, b in ((p[0], p[1]), (p[1], p[2]), (p[2], p[0])):
        y0, y1 = float(a[1]), float(b[1])
        # Half-open crossing avoids counting a projected vertex twice.
        if (y0 <= sample_y < y1) or (y1 <= sample_y < y0):
            alpha = (sample_y - y0) / (y1 - y0)
            intersections.append(float(a[0] + alpha * (b[0] - a[0])))
    if len(intersections) < 2:
        return None

    matrix = np.asarray([[float(v[0]), float(v[1]), 1.0] for v in p], dtype=np.float64)
    if abs(float(np.linalg.det(matrix))) < 1e-12:
        return None
    a_x, a_y, c = np.linalg.solve(matrix, np.asarray([float(v[2]) for v in p]))
    lo = max(path[0], min(intersections) - sample_x)
    hi = min(path[1], max(intersections) - sample_x)
    if lo >= hi:
        return None
    return {"lo": lo, "hi": hi, "slope": float(a_x),
            "intercept": float(a_x * sample_x + a_y * sample_y + c)}


def mesh_lines(positions, triangles, sample_y, sample_x, path):
    result = []
    for face_id, triangle in enumerate(triangles):
        line = triangle_depth_line(positions, triangle, sample_y, sample_x, path)
        if line is not None:
            line["face"] = face_id
            result.append(line)
    return result


def mesh_lines_for_ids(positions, triangles_by_id, face_ids, sample_y, sample_x, path):
    result = []
    for face_id in face_ids:
        triangle = triangles_by_id[int(face_id)]
        if triangle is None:
            continue
        line = triangle_depth_line(positions, triangle, sample_y, sample_x, path)
        if line is not None:
            line["face"] = int(face_id)
            result.append(line)
    return result


def events_for_lines(lines, include_depth=True):
    events = {float(t) for line in lines for t in (line["lo"], line["hi"])}
    depth_events = set()
    if include_depth:
        ordered = sorted(lines, key=lambda line: line["lo"])
        active = []
        for line in ordered:
            active = [other for other in active if other["hi"] > line["lo"]]
            for other in active:
                if abs(line["slope"] - other["slope"]) < 1e-12:
                    continue
                crossing = ((other["intercept"] - line["intercept"]) /
                            (line["slope"] - other["slope"]))
                if max(line["lo"], other["lo"]) < crossing < min(line["hi"], other["hi"]):
                    depth_events.add(float(crossing))
            active.append(line)
    return events | depth_events, depth_events


def upper_envelope(lines, path):
    events, depth_events = events_for_lines(lines, include_depth=True)
    events.update((float(path[0]), float(path[1])))
    ordered = sorted(events)
    segments = []
    for lo, hi in zip(ordered, ordered[1:]):
        segments.append({"lo": lo, "hi": hi, "line": visible(lines, 0.5 * (lo + hi))})
    return segments, ordered, len(depth_events)


def envelope_line_at(segments, time):
    # The envelopes have few segments in this probe; linear search avoids another index structure.
    for segment in segments:
        if segment["lo"] < time < segment["hi"]:
            return segment["line"]
    return None


def overlay_events(segments, local_lines, path):
    events = {float(path[0]), float(path[1])}
    depth_event_records = 0
    events.update(segment["lo"] for segment in segments)
    events.update(segment["hi"] for segment in segments)
    events.update(line[t] for line in local_lines for t in ("lo", "hi"))

    # Local front-surface changes.
    for i, a in enumerate(local_lines):
        for b in local_lines[i + 1:]:
            if abs(a["slope"] - b["slope"]) < 1e-12:
                continue
            crossing = (b["intercept"] - a["intercept"]) / (a["slope"] - b["slope"])
            if max(a["lo"], b["lo"]) < crossing < min(a["hi"], b["hi"]):
                events.add(float(crossing))
                depth_event_records += 1

    # A local triangle can replace the cached common front surface only where their depths cross.
    for segment in segments:
        common = segment["line"]
        if common is None:
            continue
        for local in local_lines:
            lo = max(segment["lo"], local["lo"])
            hi = min(segment["hi"], local["hi"])
            if lo >= hi or abs(local["slope"] - common["slope"]) < 1e-12:
                continue
            crossing = ((common["intercept"] - local["intercept"]) /
                        (local["slope"] - common["slope"]))
            if lo < crossing < hi:
                events.add(float(crossing))
                depth_event_records += 1
    return sorted(events), depth_event_records


def visible_with_envelope(segments, local_lines, time):
    best = envelope_line_at(segments, time)
    best_depth = (best["slope"] * time + best["intercept"]
                  if best is not None else -float("inf"))
    for local in local_lines:
        if local["lo"] < time < local["hi"]:
            depth = local["slope"] * time + local["intercept"]
            if depth > best_depth:
                best, best_depth = local, depth
    return best


def exact_envelope_overlay(sample_cache, path):
    events = {float(path[0]), float(path[1])}
    local_depth_events = 0
    for common_envelope, src_local, dst_local, _weight in sample_cache:
        source_events, source_depth_records = overlay_events(common_envelope, src_local, path)
        target_events, target_depth_records = overlay_events(common_envelope, dst_local, path)
        events.update(source_events)
        events.update(target_events)
        local_depth_events += source_depth_records + target_depth_records

    ordered = sorted(events)
    energy = 0.0
    for lo, hi in zip(ordered, ordered[1:]):
        mid = 0.5 * (lo + hi)
        coverage = 0.0
        depth_slope = 0.0
        depth_intercept = 0.0
        for common, src_local, dst_local, weight in sample_cache:
            src = visible_with_envelope(common, src_local, mid)
            dst = visible_with_envelope(common, dst_local, mid)
            coverage += weight * (int(src is not None) - int(dst is not None))
            if src is not None:
                depth_slope += weight * src["slope"]
                depth_intercept += weight * src["intercept"]
            if dst is not None:
                depth_slope -= weight * dst["slope"]
                depth_intercept -= weight * dst["intercept"]
        energy += ((hi - lo) * coverage * coverage +
                   integrate_square_line(depth_slope, depth_intercept, lo, hi))
    return max(0.0, energy), len(ordered), local_depth_events


def visible(lines, time):
    active = [line for line in lines if line["lo"] < time < line["hi"]]
    return (max(active, key=lambda line: line["slope"] * time + line["intercept"])
            if active else None)


def integrate_square_line(slope, intercept, lo, hi):
    return (slope * slope * (hi ** 3 - lo ** 3) / 3.0 +
            slope * intercept * (hi ** 2 - lo ** 2) + intercept * intercept * (hi - lo))


def exact_integral(sample_lines, path, include_depth=True):
    all_events = {float(path[0]), float(path[1])}
    depth_event_count = 0
    for source, candidate, _weight in sample_lines:
        for mesh in (source, candidate):
            events, depth_events = events_for_lines(mesh, include_depth)
            all_events.update(events)
            depth_event_count += len(depth_events)
    events = sorted(all_events)
    integral = 0.0
    for lo, hi in zip(events, events[1:]):
        mid = 0.5 * (lo + hi)
        cov_residual = 0.0
        depth_slope = 0.0
        depth_intercept = 0.0
        for source, candidate, weight in sample_lines:
            src, dst = visible(source, mid), visible(candidate, mid)
            cov_residual += weight * (int(src is not None) - int(dst is not None))
            if src is not None:
                depth_slope += weight * src["slope"]
                depth_intercept += weight * src["intercept"]
            if dst is not None:
                depth_slope -= weight * dst["slope"]
                depth_intercept -= weight * dst["intercept"]
        integral += ((hi - lo) * cov_residual * cov_residual +
                     integrate_square_line(depth_slope, depth_intercept, lo, hi))
    return max(0.0, integral), events, depth_event_count


def event_aligned_gauss(sample_lines, events):
    """Directly evaluate the piecewise residual at two Gauss nodes per event interval."""
    total = 0.0
    inv_sqrt_three = 1.0 / math.sqrt(3.0)
    for lo, hi in zip(events, events[1:]):
        half = 0.5 * (hi - lo)
        mid = 0.5 * (hi + lo)
        for time in (mid - half * inv_sqrt_three, mid + half * inv_sqrt_three):
            coverage, depth = 0.0, 0.0
            for source, candidate, weight in sample_lines:
                src, dst = visible(source, time), visible(candidate, time)
                coverage += weight * (int(src is not None) - int(dst is not None))
                if src is not None:
                    depth += weight * (src["slope"] * time + src["intercept"])
                if dst is not None:
                    depth -= weight * (dst["slope"] * time + dst["intercept"])
            total += half * (coverage * coverage + depth * depth)
    return total


def dense_integral(sample_lines, path, steps=250_000):
    dt = (path[1] - path[0]) / steps
    times = path[0] + (np.arange(steps, dtype=np.float64) + 0.5) * dt
    filtered_coverage = np.zeros(steps, dtype=np.float64)
    filtered_depth = np.zeros(steps, dtype=np.float64)
    for source, candidate, weight in sample_lines:
        values = []
        for mesh in (source, candidate):
            coverage = np.zeros(steps, dtype=np.float64)
            depth = np.zeros(steps, dtype=np.float64)
            for line in mesh:
                active = (times > line["lo"]) & (times < line["hi"])
                z = line["slope"] * times + line["intercept"]
                update = active & ((coverage == 0.0) | (z > depth))
                coverage[active] = 1.0
                depth[update] = z[update]
            values.append((coverage, depth))
        filtered_coverage += weight * (values[0][0] - values[1][0])
        filtered_depth += weight * (values[0][1] - values[1][1])
    return dt * float(np.sum(filtered_coverage ** 2 + filtered_depth ** 2))


def run(capture, candidate_id, steps, camera_angle=CAMERA_ANGLE):
    payload = json.loads(capture.read_text(encoding="utf-8"))
    unit = payload["units"][0]
    candidate = unit["candidates"][candidate_id]
    positions = [list(map(float, p)) for p in unit["positions"]]
    triangles = [list(map(int, f)) for f in unit["triangles"]]
    remove, keep = int(candidate["remove"]), int(candidate["keep"])
    target = list(map(float, candidate["target"]))
    frame = camera_frame(positions, camera_angle)
    positions = camera_coordinates(positions, frame).tolist()
    target = camera_coordinates([target], frame)[0].tolist()
    candidate_positions = [p[:] for p in positions]
    candidate_positions[keep] = target
    candidate_triangles = []
    candidate_face_by_id = []
    removed_faces = 0
    for face in triangles:
        changed = [keep if vertex == remove else vertex for vertex in face]
        if len(set(changed)) < 3:
            removed_faces += 1
            candidate_face_by_id.append(None)
        else:
            candidate_triangles.append(changed)
            candidate_face_by_id.append(changed)

    local_face_ids = [face_id for face_id, face in enumerate(triangles)
                      if remove in face or keep in face]
    local_face_set = set(local_face_ids)
    common_face_ids = [face_id for face_id in range(len(triangles))
                       if face_id not in local_face_set]

    incident = [face for face in triangles if remove in face or keep in face]
    incident_vertices = sorted({vertex for face in incident for vertex in face})
    xs = [positions[vertex][0] for vertex in incident_vertices]
    ys = [positions[vertex][1] for vertex in incident_vertices]
    sample_x = 0.5 * (min(xs) + max(xs))
    sample_y = 0.5 * (min(ys) + max(ys))
    radius = max(0.02, 0.75 * (max(xs) - min(xs)))
    path = (-radius, radius)

    sample_lines = []
    cached_sample_lines = []
    envelope_cache = []
    per_sample = []
    naive_started = time.perf_counter()
    for offset, weight in zip(FILTER_OFFSETS, FILTER_WEIGHTS):
        sx = sample_x + offset
        src = mesh_lines(positions, triangles, sample_y, sx, path)
        dst = mesh_lines(candidate_positions, candidate_triangles, sample_y, sx, path)
        per_sample.append({"sampleX": sx, "sourceLineCount": len(src),
                           "candidateLineCount": len(dst)})
        sample_lines.append((src, dst, weight))
    naive_line_setup_seconds = time.perf_counter() - naive_started

    cached_started = time.perf_counter()
    common_envelope_seconds = 0.0
    for offset, weight in zip(FILTER_OFFSETS, FILTER_WEIGHTS):
        sx = sample_x + offset
        common = mesh_lines_for_ids(positions, triangles, common_face_ids,
                                    sample_y, sx, path)
        src_local = mesh_lines_for_ids(positions, triangles, local_face_ids,
                                       sample_y, sx, path)
        dst_local = mesh_lines_for_ids(candidate_positions, candidate_face_by_id,
                                       local_face_ids, sample_y, sx, path)
        cached_sample_lines.append((common + src_local, common + dst_local, weight))
        envelope_started = time.perf_counter()
        common_envelope, common_events, common_depth_events = upper_envelope(common, path)
        common_envelope_seconds += time.perf_counter() - envelope_started
        envelope_cache.append((common_envelope, src_local, dst_local, weight))
    cached_line_setup_seconds = time.perf_counter() - cached_started

    full_solve_started = time.perf_counter()
    exact, events, depth_event_count = exact_integral(sample_lines, path, True)
    full_event_solve_seconds = time.perf_counter() - full_solve_started
    cached_solve_started = time.perf_counter()
    cached_exact, cached_events, cached_depth_events = exact_integral(
        cached_sample_lines, path, True)
    cached_event_solve_seconds = time.perf_counter() - cached_solve_started
    shared_overlay_started = time.perf_counter()
    envelope_exact, envelope_event_count, envelope_depth_events = exact_envelope_overlay(
        envelope_cache, path)
    shared_overlay_seconds = time.perf_counter() - shared_overlay_started
    event_gauss = event_aligned_gauss(sample_lines, events)
    coverage_only, _, _ = exact_integral(sample_lines, path, False)
    dense = dense_integral(sample_lines, path, steps)
    return {
        "candidateId": candidate_id,
        "cameraAngle": camera_angle,
        "remove": remove,
        "keep": keep,
        "target": target,
        "sourceTriangles": len(triangles),
        "candidateTriangles": len(candidate_triangles),
        "removedDegenerateFaces": removed_faces,
        "incidentFaceCount": len(incident),
        "sampleCenter": [sample_x, sample_y],
        "path": path,
        "filterOffsets": FILTER_OFFSETS,
        "filterWeights": FILTER_WEIGHTS,
        "perSampleLineCounts": per_sample,
        "unionEventCount": len(events),
        "depthEventCount": depth_event_count,
        "exactFilteredPathEnergy": exact,
        "cachedCommonGeometryEnergy": cached_exact,
        "cacheRelativeDifference": abs(exact - cached_exact) / max(abs(exact), 1e-12),
        "cachedUnionEventCount": len(cached_events),
        "cachedDepthEventCount": cached_depth_events,
        "sharedEnvelopeEnergy": envelope_exact,
        "sharedEnvelopeRelativeDifference":
            abs(exact - envelope_exact) / max(abs(exact), 1e-12),
        "sharedEnvelopeEventCount": envelope_event_count,
        "sharedEnvelopeDepthEventRecords": envelope_depth_events,
        "meanCommonEnvelopeSegments": float(np.mean([
            len(cache[0]) for cache in envelope_cache])),
        "localFaceCount": len(local_face_ids),
        "commonFaceCount": len(common_face_ids),
        "naiveTriangleLineVisits": 2 * len(triangles) * len(FILTER_OFFSETS),
        "cachedTriangleLineVisits": (len(common_face_ids) + 2 * len(local_face_ids)) *
                                     len(FILTER_OFFSETS),
        "naiveLineSetupSeconds": naive_line_setup_seconds,
        "cachedLineSetupSeconds": cached_line_setup_seconds,
        "lineSetupSpeedup": naive_line_setup_seconds /
                            max(cached_line_setup_seconds, 1e-12),
        "commonEnvelopeBuildSeconds": common_envelope_seconds,
        "fullEventSolveSeconds": full_event_solve_seconds,
        "cachedDuplicateEventSolveSeconds": cached_event_solve_seconds,
        "sharedEnvelopeOverlaySeconds": shared_overlay_seconds,
        "fullSetupPlusSolveSeconds": naive_line_setup_seconds + full_event_solve_seconds,
        "sharedSetupPlusOverlaySeconds": cached_line_setup_seconds + shared_overlay_seconds,
        "sharedTotalSpeedup": (naive_line_setup_seconds + full_event_solve_seconds) /
                              max(cached_line_setup_seconds + shared_overlay_seconds, 1e-12),
        "eventAlignedTwoPointGaussEnergy": event_gauss,
        "eventGaussRelativeDifference": abs(exact - event_gauss) / max(abs(exact), 1e-12),
        "denseMidpointPathEnergy": dense,
        "relativeDifference": abs(exact - dense) / max(abs(exact), 1e-12),
        "coverageEventsOnlyEnergy": coverage_only,
        "coverageOnlyRelativeDifference": abs(coverage_only - dense) / max(abs(dense), 1e-12),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--candidate", type=int, default=DEFAULT_CANDIDATE)
    parser.add_argument("--steps", type=int, default=250_000)
    parser.add_argument("--angle", type=float, default=CAMERA_ANGLE)
    parser.add_argument("--out", type=Path,
                        default=Path("out/real-collapse-depth-events-20261119.json"))
    args = parser.parse_args()
    result = run(args.capture, args.candidate, args.steps, args.angle)
    result["inputSha256"] = __import__("hashlib").sha256(args.capture.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
