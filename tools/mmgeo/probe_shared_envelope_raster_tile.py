#!/usr/bin/env python3
"""Compare exact path events with the existing CPU patch rasterizer on an aligned 2D tile.

The source/common depth buffer is rendered once per path sample. Each legal collapse redraws
only the faces in the shared local batch against that common buffer. The exact side integrates
the same filtered coverage/depth objective over an orthographic image-plane pan.
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster
from probe_real_collapse_depth_events import (
    exact_envelope_overlay,
    mesh_lines,
    mesh_lines_for_ids,
    overlay_events,
    upper_envelope,
    visible_with_envelope,
)
from probe_shared_envelope_2d_tile import exact_cached_source_events
from probe_shared_depth_envelope_batch import candidate_geometry, choose_local_candidates


def composite(layers):
    depth = None
    for image in layers:
        layer_depth = np.where(image[..., 0] > 0, image[..., 1], -np.inf)
        depth = layer_depth if depth is None else np.maximum(depth, layer_depth)
    coverage = np.isfinite(depth)
    return np.stack((coverage.astype(float), np.where(coverage, depth, 0.0)), axis=-1)


def downsample_box(image, width, height, scale):
    return image.reshape(height, scale, width, scale, 2).mean(axis=(1, 3))


def triangle_line_records(positions, triangles_by_id, face_ids, sample_y):
    """Compute projected depth-plane coefficients once per triangle and scanline."""
    records = []
    for face_id in face_ids:
        triangle = triangles_by_id[int(face_id)]
        if triangle is None:
            continue
        p = [positions[int(index)] for index in triangle]
        intersections = []
        for a, b in ((p[0], p[1]), (p[1], p[2]), (p[2], p[0])):
            y0, y1 = float(a[1]), float(b[1])
            if (y0 <= sample_y < y1) or (y1 <= sample_y < y0):
                alpha = (sample_y - y0) / (y1 - y0)
                intersections.append(float(a[0] + alpha * (b[0] - a[0])))
        if len(intersections) < 2:
            continue
        matrix = np.asarray([[float(v[0]), float(v[1]), 1.0] for v in p])
        if abs(float(np.linalg.det(matrix))) < 1e-12:
            continue
        slope, y_slope, intercept = np.linalg.solve(
            matrix, np.asarray([float(v[2]) for v in p]))
        records.append((int(face_id), min(intersections), max(intersections),
                        float(slope), float(y_slope * sample_y + intercept)))
    return records


def instantiate_lines(records, sample_x, path):
    lines = []
    for face, left, right, slope, base_intercept in records:
        lo = max(float(path[0]), left - sample_x)
        hi = min(float(path[1]), right - sample_x)
        if lo < hi:
            lines.append({"face": face, "lo": lo, "hi": hi, "slope": slope,
                          "intercept": slope * sample_x + base_intercept})
    return lines


def triangle_path_coefficients(positions, triangles_by_id, face_ids):
    """Cache barycentric and depth-plane coefficients for arbitrary 2D pan rays."""
    records = []
    for face_id in face_ids:
        triangle = triangles_by_id[int(face_id)]
        if triangle is None:
            continue
        p = [positions[int(index)] for index in triangle]
        matrix = np.asarray([[float(v[0]), float(v[1]), 1.0] for v in p])
        if abs(float(np.linalg.det(matrix))) < 1e-12:
            continue
        inverse = np.linalg.inv(matrix)
        barycentric = inverse.T
        depth_plane = np.linalg.solve(matrix, np.asarray([float(v[2]) for v in p]))
        xy = np.asarray([[float(v[0]), float(v[1])] for v in p])
        bounds = (float(xy[:, 0].min()), float(xy[:, 1].min()),
                  float(xy[:, 0].max()), float(xy[:, 1].max()))
        records.append((int(face_id), barycentric, depth_plane, bounds))
    return records


def build_path_triangle_grid(records, cell_size=8.0):
    grid = {}
    for index, (_face, _barycentric, _depth_plane, bounds) in enumerate(records):
        x0, y0, x1, y1 = bounds
        for gx in range(math.floor(x0 / cell_size), math.floor(x1 / cell_size) + 1):
            for gy in range(math.floor(y0 / cell_size), math.floor(y1 / cell_size) + 1):
                grid.setdefault((gx, gy), []).append(index)
    return grid


def instantiate_path_lines(records, sample_x, sample_y, direction, path, grid=None,
                           cell_size=8.0):
    lines = []
    dx, dy = direction
    if grid is None:
        record_indices = range(len(records))
    else:
        t0, t1 = map(float, path)
        x0, x1 = sorted((sample_x + dx * t0, sample_x + dx * t1))
        y0, y1 = sorted((sample_y + dy * t0, sample_y + dy * t1))
        indices = set()
        for gx in range(math.floor(x0 / cell_size), math.floor(x1 / cell_size) + 1):
            for gy in range(math.floor(y0 / cell_size), math.floor(y1 / cell_size) + 1):
                indices.update(grid.get((gx, gy), ()))
        record_indices = sorted(indices)
    tested = 0
    for record_index in record_indices:
        face_id, barycentric, depth_plane, _bounds = records[record_index]
        tested += 1
        lo, hi = map(float, path)
        valid = True
        for affine in barycentric:
            value = float(affine[0] * sample_x + affine[1] * sample_y + affine[2])
            slope = float(affine[0] * dx + affine[1] * dy)
            if abs(slope) < 1e-14:
                if value < -1e-12:
                    valid = False
                    break
                continue
            crossing = -value / slope
            if slope > 0.0:
                lo = max(lo, crossing)
            else:
                hi = min(hi, crossing)
            if lo >= hi:
                valid = False
                break
        if not valid or lo >= hi:
            continue
        z_slope = float(depth_plane[0] * dx + depth_plane[1] * dy)
        z_intercept = float(depth_plane[0] * sample_x +
                            depth_plane[1] * sample_y + depth_plane[2])
        lines.append({"face": face_id, "lo": lo, "hi": hi,
                      "slope": z_slope, "intercept": z_intercept})
    return lines, tested


def raster_local_path(positions, triangles, union_faces, candidate_data, rect, scale,
                      path, direction, steps, loss_cell_width=0, loss_cell_height=0):
    """Dense local redraw with one common depth render and candidate patch overlays per sample."""
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    full_valid = np.ones(len(triangles), dtype=bool)
    common_triangles = triangles[union_faces["common"]]
    source_triangles = triangles[union_faces["local"]]
    common_valid = np.ones(len(common_triangles), dtype=bool)
    source_valid = np.ones(len(source_triangles), dtype=bool)
    candidate_valid = [np.ones(len(item["patchTriangles"]), dtype=bool)
                       for item in candidate_data]
    source_time = 0.0
    patch_time = 0.0
    candidate_energy = np.zeros(len(candidate_data), dtype=float)
    dt = (path[1] - path[0]) / steps
    for step in range(steps):
        t = path[0] + (step + 0.5) * dt
        camera_positions = positions.copy()
        camera_positions[:, 0] -= direction[0] * t
        camera_positions[:, 1] -= direction[1] * t
        common_start = time.perf_counter()
        common_image, _ = raster.raster(camera_positions, common_triangles,
                                        common_valid, rect, scale)
        source_union_image, _ = raster.raster(camera_positions, source_triangles,
                                              source_valid, rect, scale)
        source_image = composite((common_image, source_union_image))
        source_time += time.perf_counter() - common_start
        source_pixels = downsample_box(source_image, width, height, scale)

        for index, item in enumerate(candidate_data):
            patch_start = time.perf_counter()
            changed = item["positions"].copy()
            changed[:, 0] -= direction[0] * t
            changed[:, 1] -= direction[1] * t
            local_image, _ = raster.raster(changed, item["patchTriangles"],
                                           candidate_valid[index], rect, scale)
            candidate_image = composite((common_image, local_image))
            candidate_pixels = downsample_box(candidate_image, width, height, scale)
            patch_time += time.perf_counter() - patch_start
            delta = candidate_pixels - source_pixels
            candidate_energy[index] += float(np.square(delta).sum()) * dt
            if loss_cell_width:
                cell_energies = item.setdefault("rasterCellEnergy", {})
                for cell_y, y0 in enumerate(range(0, height, loss_cell_height)):
                    for cell_x, x0 in enumerate(range(0, width, loss_cell_width)):
                        cell_key = f"{steps}:{cell_x},{cell_y}"
                        y1 = min(height, y0 + loss_cell_height)
                        x1 = min(width, x0 + loss_cell_width)
                        cell_delta = delta[y0:y1, x0:x1]
                        cell_energies[cell_key] = (cell_energies.get(cell_key, 0.0) +
                                                   float(np.square(cell_delta).sum()) * dt)
    return candidate_energy, source_time, patch_time


def exact_candidate_cell(item, cell_id, rect, cell_width, cell_height, exact_ray_cache,
                         source_event_cache, path, pan_direction, horizontal_cache):
    """Integrate one screen cell exactly for one candidate, returning loss and ray tests."""
    cell_x, cell_y = map(int, cell_id.split(","))
    x0 = rect[0] + cell_x * cell_width
    y0 = rect[1] + cell_y * cell_height
    x1 = min(rect[2], x0 + cell_width)
    y1 = min(rect[3], y0 + cell_height)
    rect_width = rect[2] - rect[0]
    energy = 0.0
    ray_tests = 0
    for py in range(y0, y1):
        for px in range(x0, x1):
            pixel_index = (py - rect[1]) * rect_width + px - rect[0]
            samples = []
            for (sample_x, sample_y, weight, common, starts, source_local,
                 by_face) in exact_ray_cache[pixel_index]:
                if horizontal_cache:
                    candidate_local = instantiate_lines(
                        item["localRows"][sample_y], sample_x, item["path"])
                else:
                    candidate_local, tested = instantiate_path_lines(
                        item["localCoefficients"], sample_x, sample_y, pan_direction,
                        item["path"], item["localGrid"])
                    ray_tests += tested
                unchanged = [by_face[i] for i in item["unchangedUnion"] if i in by_face]
                samples.append((common, starts, source_local,
                                unchanged + candidate_local, weight))
            energy += exact_cached_source_events(
                samples, source_event_cache[pixel_index], item["path"])
    return energy, ray_tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=Path("out/filter-real-candidates/monkey.json"))
    parser.add_argument("--unit-index", type=int, default=0,
                        help="unit inside a multi-unit frozen capture")
    parser.add_argument("--seed-candidate", type=int, default=44000)
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--pan-angle", type=float, default=0.0,
                        help="image-plane pan direction in degrees; 0 is horizontal")
    parser.add_argument("--general-rays", action="store_true",
                        help="use barycentric path-ray intersections even for horizontal pans")
    parser.add_argument("--path-radius", type=float, default=None,
                        help="override the auto path half-length, in projected pixels")
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--tile-width", type=int, default=32)
    parser.add_argument("--tile-height", type=int, default=8)
    parser.add_argument("--loss-cell-width", type=int, default=0,
                        help="also accumulate exact loss by smaller screen cells; 0 disables")
    parser.add_argument("--loss-cell-height", type=int, default=0)
    parser.add_argument("--online-pruning", action="store_true",
                        help="raster-order cells and stop exact candidate integration using lower bounds")
    parser.add_argument("--reference-capture", type=Path, default=None,
                        help="full exact capture used only to audit the selected online candidate")
    parser.add_argument("--steps", type=int, nargs="+", default=[32, 128])
    parser.add_argument("--out", type=Path,
                        default=Path("out/shared-envelope-raster-tile-20261119.json"))
    args = parser.parse_args()
    if args.size <= 0 or args.scale <= 0 or min(args.tile_width, args.tile_height) <= 0:
        parser.error("size, scale, and tile dimensions must be positive")
    if (args.loss_cell_width < 0 or args.loss_cell_height < 0 or
            bool(args.loss_cell_width) != bool(args.loss_cell_height)):
        parser.error("loss-cell width and height must both be positive or both be zero")
    if args.online_pruning and (not args.loss_cell_width or not args.reference_capture):
        parser.error("online pruning needs positive loss-cell dimensions and --reference-capture")
    if any(step <= 0 for step in args.steps):
        parser.error("all path sample counts must be positive")

    probe_core_start = time.perf_counter()
    raw = json.loads(args.capture.read_text(encoding="utf-8"))
    if not 0 <= args.unit_index < len(raw["units"]):
        parser.error(f"unit-index must be in [0, {len(raw['units']) - 1}]")
    unit = raw["units"][args.unit_index]
    world_positions = np.asarray(unit["positions"], dtype=float)
    triangles = np.asarray(unit["triangles"], dtype=np.int64)
    candidates = unit["candidates"]
    if not candidates:
        parser.error(f"capture unit {args.unit_index} has no legal candidates")
    candidate_ids = choose_local_candidates(
        candidates, triangles, args.seed_candidate, args.candidate_limit)
    transform = raster.camera(world_positions, args.angle, args.size)
    projected = raster.project(world_positions, transform)
    pan_radians = math.radians(args.pan_angle)
    pan_direction = (math.cos(pan_radians), math.sin(pan_radians))
    triangles_list = triangles.tolist()

    batch_local_faces = set()
    bounds_vertices = set()
    target_screen = []
    for candidate_id in candidate_ids:
        candidate = candidates[candidate_id]
        _post, _faces, _valid, local = candidate_geometry(
            projected.tolist(), triangles_list,
            dict(candidate, target=raster.project(np.asarray([candidate["target"]]), transform)[0].tolist()))
        batch_local_faces.update(local)
        bounds_vertices.update((int(candidate["remove"]), int(candidate["keep"])))
        target_screen.append(raster.project(np.asarray([candidate["target"]]), transform)[0])
    for face_id in tuple(batch_local_faces):
        bounds_vertices.update(map(int, triangles[face_id]))
    bound_points = np.vstack((projected[list(bounds_vertices)], np.asarray(target_screen)))
    projected_span = bound_points[:, :2] @ np.asarray(pan_direction)
    path_radius = (float(args.path_radius) if args.path_radius is not None else
                   max(0.25, 0.75 * float(projected_span.max() - projected_span.min())))
    if path_radius <= 0.0:
        parser.error("path-radius must be positive")
    path = (-path_radius, path_radius)

    # Pixel aligned tile around the swept collapse support, clipped to the viewport.
    center_x = 0.5 * (float(bound_points[:, 0].min()) + float(bound_points[:, 0].max()))
    center_y = 0.5 * (float(bound_points[:, 1].min()) + float(bound_points[:, 1].max()))
    x0 = max(0, min(args.size - args.tile_width,
                    int(math.floor(center_x - 0.5 * args.tile_width))))
    y0 = max(0, min(args.size - args.tile_height,
                    int(math.floor(center_y - 0.5 * args.tile_height))))
    rect = (x0, y0, x0 + args.tile_width, y0 + args.tile_height)

    # Screen-space projected mesh and target positions match depth_candidate_pilot.raster.
    projected_depth = np.column_stack((projected[:, 0], projected[:, 1], projected[:, 2]))
    common_face_ids = [i for i in range(len(triangles)) if i not in batch_local_faces]
    local_face_ids = sorted(batch_local_faces)
    union_faces = {"common": np.asarray(common_face_ids, dtype=np.int64),
                   "local": np.asarray(local_face_ids, dtype=np.int64)}

    # Event cache at every actual 2x2 raster sample location in the output tile.
    ray_cache = []
    for py in range(rect[1], rect[3]):
        for px in range(rect[0], rect[2]):
            taps = []
            for sy in range(args.scale):
                for sx in range(args.scale):
                    sample_x = px + (sx + 0.5) / args.scale
                    sample_y = py + (sy + 0.5) / args.scale
                    taps.append((sample_x, sample_y, 1.0 / (args.scale * args.scale)))
            ray_cache.append(taps)
    common_start = time.perf_counter()
    sample_y_values = sorted({sample_y for taps in ray_cache
                              for _sample_x, sample_y, _weight in taps})
    horizontal_cache = (not args.general_rays and
                        abs(pan_direction[0] - 1.0) < 1e-12 and
                        abs(pan_direction[1]) < 1e-12)
    if horizontal_cache:
        source_rows = {
            sample_y: triangle_line_records(projected_depth, triangles_list,
                                           range(len(triangles)), sample_y)
            for sample_y in sample_y_values
        }
        source_coefficients = None
    else:
        source_rows = None
        source_coefficients = triangle_path_coefficients(
            projected_depth, triangles_list, range(len(triangles)))
    source_grid = (None if horizontal_cache else
                   build_path_triangle_grid(source_coefficients))
    exact_ray_cache = []
    source_event_cache = []
    path_line_candidate_tests = 0
    sample_ray_count = sum(len(taps) for taps in ray_cache)
    triangle_scan_visits = (len(triangles) * len(sample_y_values) if horizontal_cache
                            else len(triangles) * sample_ray_count)
    for taps in ray_cache:
        cached_taps = []
        source_events = []
        for sample_x, sample_y, weight in taps:
            if horizontal_cache:
                source_lines = instantiate_lines(source_rows[sample_y], sample_x, path)
            else:
                source_lines, tested = instantiate_path_lines(
                    source_coefficients, sample_x, sample_y, pan_direction, path, source_grid)
                path_line_candidate_tests += tested
            by_face = {line["face"]: line for line in source_lines}
            common_lines = [by_face[i] for i in common_face_ids if i in by_face]
            source_local = [by_face[i] for i in local_face_ids if i in by_face]
            common, _events, _depths = upper_envelope(common_lines, path)
            starts = [segment["lo"] for segment in common]
            cached_taps.append((sample_x, sample_y, weight, common, starts,
                                source_local, by_face))
            source_events.append(overlay_events(common, source_local, path)[0])
        exact_ray_cache.append(cached_taps)
        source_event_cache.append(source_events)
    if horizontal_cache:
        audit_x, audit_y, _audit_weight = ray_cache[0][0]
        cached_audit = instantiate_lines(source_rows[audit_y], audit_x, path)
        legacy_audit = mesh_lines(projected_depth, triangles_list, audit_y, audit_x, path)
        cached_by_face = {line["face"]: line for line in cached_audit}
        legacy_by_face = {line["face"]: line for line in legacy_audit}
        line_cache_audit_difference = max(
            (max(abs(cached_by_face[face][key] - legacy_by_face[face][key])
                 for key in ("lo", "hi", "slope", "intercept"))
             for face in cached_by_face.keys() & legacy_by_face.keys()),
            default=0.0)
        line_cache_audit_face_mismatch = len(cached_by_face.keys() ^ legacy_by_face.keys())
    else:
        line_cache_audit_difference = None
        line_cache_audit_face_mismatch = None
    common_event_setup_seconds = time.perf_counter() - common_start

    candidate_data = []
    candidate_preparation_seconds = 0.0
    legacy_check_diff = None
    for candidate_id in candidate_ids:
        started = time.perf_counter()
        candidate = dict(candidates[candidate_id])
        candidate["target"] = raster.project(np.asarray([candidate["target"]]), transform)[0].tolist()
        post, face_by_id, _valid_faces, local_faces = candidate_geometry(
            projected_depth.tolist(), triangles_list, candidate)
        local_set = set(local_faces)
        unchanged_union = set(local_face_ids) - local_set
        patch_ids = sorted(unchanged_union) + [i for i in local_faces if face_by_id[i] is not None]
        patch_triangles = np.asarray([face_by_id[i] if i in local_set else triangles[i]
                                     for i in patch_ids], dtype=np.int64)
        item = {"id": candidate_id, "positions": np.asarray(post, dtype=float),
                "patchTriangles": patch_triangles, "exactCellEnergy": {},
                "path": path, "unchangedUnion": unchanged_union}
        if horizontal_cache:
            item["localRows"] = {
                sample_y: triangle_line_records(post, face_by_id, local_faces, sample_y)
                for sample_y in sample_y_values
            }
            item["localCoefficients"] = None
        else:
            item["localCoefficients"] = triangle_path_coefficients(
                post, face_by_id, local_faces)
        item["localGrid"] = (None if horizontal_cache else
                             build_path_triangle_grid(item["localCoefficients"]))
        candidate_data.append(item)
        candidate_preparation_seconds += time.perf_counter() - started

    dense_results = {step: [] for step in args.steps}
    dense_common_seconds = {}
    dense_patch_seconds = {}
    for step in args.steps:
        energies, common_seconds, patch_seconds = raster_local_path(
            projected_depth, triangles, union_faces, candidate_data, rect, args.scale,
            path, pan_direction, step, args.loss_cell_width, args.loss_cell_height)
        dense_common_seconds[step] = common_seconds
        dense_patch_seconds[step] = patch_seconds
        for index, item in enumerate(candidate_data):
            dense_results[step].append(float(energies[index]))
    base_raster_steps = min(args.steps)
    rect_width, rect_height = rect[2] - rect[0], rect[3] - rect[1]
    cell_width = args.loss_cell_width or rect_width
    cell_height = args.loss_cell_height or rect_height
    cell_ids = [f"{cx},{cy}"
                for cy in range(math.ceil(rect_height / cell_height))
                for cx in range(math.ceil(rect_width / cell_width))]
    candidate_by_id = {item["id"]: item for item in candidate_data}
    raster_cell_by_id = {
        item["id"]: {cell: float(item.get("rasterCellEnergy", {}).get(
            f"{base_raster_steps}:{cell}", 0.0)) for cell in cell_ids}
        for item in candidate_data}
    candidate_order = sorted(candidate_ids, key=lambda cid: sum(raster_cell_by_id[cid].values()))

    candidate_setup_seconds = 0.0
    online_trace = []
    incumbent_id = None
    incumbent_energy = float("inf")
    for candidate_id in candidate_order:
        item = candidate_by_id[candidate_id]
        if args.online_pruning:
            cell_order = sorted(cell_ids,
                                key=lambda cell: (-raster_cell_by_id[candidate_id][cell], cell))
        else:
            cell_order = cell_ids
        lower_bound = 0.0
        visited = []
        pruned = False
        started = time.perf_counter()
        for cell_id in cell_order:
            energy, ray_tests = exact_candidate_cell(
                item, cell_id, rect, cell_width, cell_height, exact_ray_cache,
                source_event_cache, path, pan_direction, horizontal_cache)
            path_line_candidate_tests += ray_tests
            item["exactCellEnergy"][cell_id] = energy
            lower_bound += energy
            visited.append(cell_id)
            if args.online_pruning and math.isfinite(incumbent_energy):
                tolerance = 1e-12 * max(abs(incumbent_energy), 1e-300)
                if lower_bound >= incumbent_energy - tolerance:
                    pruned = len(visited) < len(cell_order)
                    break
        candidate_setup_seconds += time.perf_counter() - started
        item["exactEnergy"] = lower_bound
        item["exactEvaluationComplete"] = not pruned
        if not pruned and lower_bound < incumbent_energy:
            incumbent_id = candidate_id
            incumbent_energy = lower_bound
        online_trace.append({"candidateId": candidate_id, "cellOrder": cell_order,
                             "visitedCells": visited, "evaluatedCellCount": len(visited),
                             "lowerBound": lower_bound, "pruned": pruned,
                             "exactEvaluationComplete": not pruned})
    if not horizontal_cache:
        triangle_scan_visits = path_line_candidate_tests
    solver_core_finished = time.perf_counter()

    reference_exact = {}
    reference_winners = []
    reference_audit = None
    if args.reference_capture:
        reference_data = json.loads(args.reference_capture.read_text(encoding="utf-8"))
        reference_exact = {int(row["candidateId"]): float(row["exactEnergy"])
                           for row in reference_data["candidateRasterRows"]
                           if int(row["steps"]) == base_raster_steps}
        if set(reference_exact) != set(candidate_ids):
            parser.error("reference capture candidate IDs do not match this run")
        reference_best = min(reference_exact.values())
        tolerance = 1e-12 * max(abs(reference_best), 1e-300)
        reference_winners = [cid for cid, value in reference_exact.items()
                             if value <= reference_best + tolerance]
        reference_audit = {"selectedCandidateId": incumbent_id,
                           "selectedCandidateIsExactWinner": incumbent_id in reference_winners,
                           "referenceWinnerIds": reference_winners,
                           "selectedReferenceLoss": reference_exact[incumbent_id],
                           "minimumReferenceLoss": reference_best}

    dense_rows = []
    for step in args.steps:
        for index, item in enumerate(candidate_data):
            exact_energy = reference_exact.get(item["id"], float(item["exactEnergy"]))
            raster_energy = dense_results[step][index]
            dense_rows.append({
                "candidateId": item["id"], "steps": step,
                "exactEnergy": exact_energy, "rasterEnergy": raster_energy,
                "scheduledLowerBound": item["exactEnergy"],
                "exactEvaluationComplete": item["exactEvaluationComplete"],
                "absoluteError": abs(raster_energy - exact_energy),
                "relativeError": abs(raster_energy - exact_energy) /
                                 max(abs(exact_energy), 1e-12),
            })

    summary = {}
    for step in args.steps:
        errors = [row for row in dense_rows if row["steps"] == step]
        summary[str(step)] = {
            "commonRasterSeconds": dense_common_seconds[step],
            "candidatePatchSeconds": dense_patch_seconds[step],
            "denseTotalSeconds": dense_common_seconds[step] + dense_patch_seconds[step],
            "sumAbsoluteEnergyError": sum(row["absoluteError"] for row in errors),
            "maxRelativeEnergyError": max(row["relativeError"] for row in errors),
            "sumExactEnergy": sum(row["exactEnergy"] for row in errors),
        }
    output = {
        "scope": "pixel-aligned CPU raster tile; orthographic image-plane pan; box-filter samples",
        "warning": "Python raster oracle, one mesh and one tile; not a GPU or production benchmark",
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seedCandidate": args.seed_candidate,
        "unitIndex": args.unit_index,
        "candidateIds": candidate_ids,
        "candidateCount": len(candidate_ids),
        "cameraAngle": args.angle,
        "panAngle": args.pan_angle,
        "panDirection": pan_direction,
        "generalPathRaySolver": args.general_rays,
        "imageSize": args.size,
        "scale": args.scale,
        "tileRect": rect,
        "tilePixels": args.tile_width * args.tile_height,
        "path": path,
        "commonEventSetupSeconds": common_event_setup_seconds,
        "candidatePreparationSeconds": candidate_preparation_seconds,
        "rasterLocalPathSeconds": sum(dense_common_seconds.values()) +
                                  sum(dense_patch_seconds.values()),
        "candidateExactSetupAndIntegrationSeconds": candidate_setup_seconds,
        "solverCoreSeconds": solver_core_finished - probe_core_start,
        "onlinePruning": args.online_pruning,
        "onlineSchedule": online_trace if args.online_pruning else None,
        "onlineReferenceAudit": reference_audit,
        "triangleLineScanVisits": triangle_scan_visits,
        "lineCacheAuditMaxCoefficientDifference": line_cache_audit_difference,
        "lineCacheAuditFaceMismatch": line_cache_audit_face_mismatch,
        "legacyExactAuditDifference": legacy_check_diff,
        "lossCellSize": ([args.loss_cell_width, args.loss_cell_height]
                         if args.loss_cell_width else None),
        "candidateExactCellLosses": ([
            {"candidateId": item["id"], "cells": item["exactCellEnergy"],
             "sum": sum(item["exactCellEnergy"].values()),
             "whole": item["exactEnergy"],
             "complete": item["exactEvaluationComplete"]}
            for item in candidate_data] if args.loss_cell_width else None),
        "candidateRasterCellLosses": ([
            {"candidateId": item["id"], "cells": item.get("rasterCellEnergy", {})}
            for item in candidate_data] if args.loss_cell_width else None),
        "denseRasterResults": summary,
        "candidateRasterRows": dense_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "candidateCount", "tileRect", "tilePixels", "path", "commonEventSetupSeconds",
        "candidateExactSetupAndIntegrationSeconds", "legacyExactAuditDifference",
        "triangleLineScanVisits", "denseRasterResults")}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
