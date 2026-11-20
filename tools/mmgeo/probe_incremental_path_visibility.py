#!/usr/bin/env python3
"""Audit continuous visibility reuse across disjoint captured edge collapses."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import camera, project
from probe_real_collapse_depth_events import events_for_lines
from probe_shared_envelope_raster_tile import (
    build_path_triangle_grid,
    instantiate_path_lines,
    triangle_path_coefficients,
)


def front_envelope(lines, path):
    """Retain only breakpoints at which the front surface changes."""
    events, _ = events_for_lines(lines, include_depth=True)
    events.update(path)
    edges = sorted(events)
    result = []
    for lo, hi in zip(edges, edges[1:]):
        # Interval membership stays well-defined if the midpoint rounds to an endpoint.
        mid = lo + 0.5 * (hi - lo)
        active = (line for line in lines if line["lo"] <= lo and hi <= line["hi"])
        line = max(active, default=None,
                   key=lambda item: (item["slope"] * mid + item["intercept"], -item["face"]))
        if result and result[-1][2] is line:
            result[-1] = (result[-1][0], hi, line)
        else:
            result.append((lo, hi, line))
    return result


def shift_envelope(front, shift, path):
    """Restrict an envelope at p + direction * t to the tap at p + direction * shift."""
    result = []
    for lo, hi, line in front:
        start = max(path[0], lo - shift)
        end = min(path[1], hi - shift)
        if start < end:
            if line is not None:
                line = dict(line, lo=line["lo"] - shift, hi=line["hi"] - shift,
                            intercept=line["intercept"] + line["slope"] * shift)
            result.append((start, end, line))
    # In exact arithmetic the expanded path includes both ends of every tap path.
    # Restore the ends explicitly after subtracting the offset in floating point.
    first, last = result[0], result[-1]
    result[0] = (path[0], first[1], first[2])
    result[-1] = (result[-1][0], path[1], last[2])
    return result


class CollinearTaps:
    """Share front-envelope work among regular box taps along an axis-aligned path."""

    def __init__(self, scale, direction, path, continuous_box=False):
        self.path = path
        self.continuous_box = continuous_box
        offsets = [(i + 0.5) / scale for i in range(scale)]
        horizontal = direction[1] == 0.0
        sign = direction[0] if horizontal else direction[1]
        self.anchors = ([(0.5, y) for y in offsets] if horizontal
                        else [(x, 0.5) for x in offsets])
        self.taps = [(iy if horizontal else ix, sign * (offsets[ix if horizontal else iy] - 0.5))
                     for iy in range(scale) for ix in range(scale)]
        margin = 0.5 if continuous_box else max(abs(shift) for _, shift in self.taps)
        self.expanded_path = (math.nextafter(path[0] - margin, -math.inf),
                              math.nextafter(path[1] + margin, math.inf))

    def expand(self, fronts):
        return [shift_envelope(fronts[index], shift, self.path) for index, shift in self.taps]

    def reference(self, fronts):
        return fronts if self.continuous_box else self.expand(fronts)

    def loss(self, original, current, normal_data):
        if self.continuous_box:
            return continuous_box_loss(original, current, self.path, normal_data)
        return filtered_pixel_loss(original, self.expand(current), normal_data)


def integrated_front(front, queries, normals):
    """Integrate coverage, depth and optionally normals from the first endpoint."""
    edges = np.asarray([front[0][0], *(hi for _, hi, _ in front)])
    duration = np.diff(edges)
    values = np.zeros((len(front), 2 if normals is None else 5))
    slopes = np.zeros(len(front))
    for i, (lo, _, line) in enumerate(front):
        if line is not None:
            slopes[i] = line["slope"]
            values[i, :2] = 1., line["intercept"] + lo * slopes[i]
            if normals is not None:
                values[i, 2:] = normals[line["face"]]
    areas = duration[:, None] * values
    areas[:, 1] += 0.5 * slopes * duration ** 2
    prefix = np.vstack((np.zeros(values.shape[1]), np.cumsum(areas, axis=0)))
    indices = np.clip(np.searchsorted(edges, queries, side="right") - 1, 0, len(front) - 1)
    width = (queries - edges[indices]).clip(0.0, duration[indices])
    result = prefix[indices] + width[:, None] * values[indices]
    result[:, 1] += 0.5 * slopes[indices] * width ** 2
    return result


def continuous_box_loss(original, current, path, normal_data=None):
    """Integrate squared residuals after a unit box filter along the pan direction."""
    boundaries = {t for front in (*original, *current) for lo, hi, _ in front for t in (lo, hi)}
    edges = {t + offset for t in boundaries for offset in (-0.5, 0.5)}
    edges = np.asarray([path[0], *sorted(t for t in edges if path[0] < t < path[1]), path[1]])
    widths = np.diff(edges)
    midpoint = edges[:-1] + widths * 0.5
    # Window integrals are quadratic between shifted events. Three Gauss points
    # integrate their squared norm (degree four) exactly on each interval.
    nodes = np.asarray((-math.sqrt(3.0 / 5.0), 0., math.sqrt(3.0 / 5.0)))
    weights = np.asarray((5. / 18., 4. / 9., 5. / 18.))
    times = (midpoint[:, None] + 0.5 * widths[:, None] * nodes).ravel()
    queries = np.r_[times - 0.5, times + 0.5]
    residual = np.zeros((len(times), 2 if normal_data is None else 5))
    for i, fronts in enumerate((original, current)):
        for front in fronts:
            prefix = integrated_front(front, queries, None if normal_data is None else normal_data[i])
            residual += (1 if i == 0 else -1) * (prefix[len(times):] - prefix[:len(times)])
    residual /= len(original)
    squared = np.square(residual)
    if normal_data is not None:
        squared[:, 2:] *= normal_data[2]
    return float(widths @ (squared.sum(axis=1).reshape(-1, 3) @ weights))


def position_in_bounds(x, y, bounds):
    return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]


def unchanged_reason(front, edited_ids, old_lines, new_lines):
    if not old_lines and not new_lines:
        return "noIntersection"
    if any(line is not None and line["face"] in edited_ids for _, _, line in front):
        return "editedWinner"
    for changed in new_lines:
        for lo, hi, winner in front:
            start = max(lo, changed["lo"])
            end = min(hi, changed["hi"])
            if start >= end:
                continue
            if winner is None:
                return "newFront"
            # The gap is affine. A strict gap at both ends proves dominance on
            # the whole interval. Send numerically ambiguous gaps to rebuilding.
            slope = winner["slope"] - changed["slope"]
            intercept = winner["intercept"] - changed["intercept"]
            margin = 1e-12 * (1.0 + abs(winner["intercept"]) + abs(changed["intercept"])
                              + max(abs(start), abs(end))
                              * (abs(winner["slope"]) + abs(changed["slope"])))
            if min(slope * start + intercept, slope * end + intercept) <= margin:
                return "newFront"
    return "occludedEdit"


def repair_front(front, edited_ids, new_lines, scene_lines):
    """Restore the complete line set only over intervals with a removed winner."""
    result = []
    exposed_duration = 0.0
    exposed_inputs = 0
    for lo, hi, winner in front:
        exposed = winner is not None and winner["face"] in edited_ids
        if exposed:
            candidates = scene_lines
            exposed_duration += hi - lo
        elif winner is None:
            candidates = new_lines
        else:
            candidates = sorted([winner, *new_lines], key=lambda line: line["face"])
        by_face = {line["face"]: line for line in candidates
                   if line["lo"] < hi and lo < line["hi"]}
        clipped = [dict(line, lo=max(lo, line["lo"]), hi=min(hi, line["hi"]))
                   for line in by_face.values()]
        if exposed:
            exposed_inputs += len(clipped)
        for a, b, clipped_winner in front_envelope(clipped, (lo, hi)):
            line = None if clipped_winner is None else by_face[clipped_winner["face"]]
            if result and result[-1][2] is line:
                result[-1] = (result[-1][0], b, line)
            else:
                result.append((a, b, line))
    return result, exposed_duration, exposed_inputs


def filtered_pixel_loss(original, current, normal_data=None):
    envelopes = original + current
    weight = 1.0 / len(original)
    edges = sorted({edge for front in envelopes for lo, hi, _ in front for edge in (lo, hi)})
    indices = [0] * len(envelopes)
    total = 0.0
    for lo, hi in zip(edges, edges[1:]):
        mid = lo + 0.5 * (hi - lo)
        coverage, slope, intercept = 0, 0.0, 0.0
        normal = np.zeros(3) if normal_data is not None else None
        for i, front in enumerate(envelopes):
            while front[indices[i]][1] <= lo:
                indices[i] += 1
            line = front[indices[i]][2]
            if line is not None:
                sign = 1 if i < len(original) else -1
                coverage += sign
                slope += sign * line["slope"]
                intercept += sign * line["intercept"]
                if normal is not None:
                    face_normals = normal_data[0 if sign > 0 else 1]
                    normal += sign * face_normals[line["face"]]
        duration = hi - lo
        midpoint_depth = slope * mid + intercept
        total += duration * (coverage ** 2 + midpoint_depth ** 2
                             + (slope * duration) ** 2 / 12.0)
        if normal is not None:
            total += duration * normal_data[2] * float(normal @ normal)
    return total * weight ** 2


def make_grid(positions, faces, ids):
    records = triangle_path_coefficients(positions, faces, ids)
    return records, build_path_triangle_grid(records)


def pick_edits(positions, faces, candidates, seed, count, rect, direction, path):
    """Use mutually vertex-disjoint edited patches from the initial capture."""
    incident = [[] for _ in positions]
    for face_id, triangle in enumerate(faces):
        for vertex in triangle:
            incident[vertex].append(face_id)
    centers = np.asarray([positions[int(row["keep"]), :2] + positions[int(row["remove"]), :2]
                          for row in candidates]) * 0.5
    distance = np.sum((centers - centers[seed]) ** 2, axis=1)
    delta = np.asarray(path)[:, None] * np.asarray(direction)
    edits = []
    used_vertices = set()
    order = [seed, *[int(i) for i in np.argsort(distance, kind="stable") if i != seed]]
    for index in order:
        candidate = candidates[index]
        remove, keep = int(candidate["remove"]), int(candidate["keep"])
        ids = set(incident[remove]) | set(incident[keep])
        vertices = {v for face_id in ids for v in faces[face_id]}
        if used_vertices & vertices or not ids:
            continue
        target = candidate["projectedTarget"]
        points = np.vstack((positions[sorted(vertices)], target))
        lower = points[:, :2].min(axis=0) - delta.max(axis=0) - 1e-8
        upper = points[:, :2].max(axis=0) - delta.min(axis=0) + 1e-8
        if upper[0] < rect[0] or upper[1] < rect[1] or lower[0] > rect[2] or lower[1] > rect[3]:
            continue
        edited_faces = {}
        for face_id in sorted(ids):
            face = tuple(keep if v == remove else v for v in faces[face_id])
            edited_faces[face_id] = face if len(set(face)) == 3 else None
        edits.append({"id": index, "faces": edited_faces, "keep": keep, "target": target,
                      "bounds": (*lower, *upper)})
        used_vertices.update(vertices)
        if len(edits) == count:
            break
    return edits


def replay(positions, faces, edits, pixels, direction, path, policy, source_grid, original):
    def lines(grid, x, y):
        records, bins = grid
        return instantiate_path_lines(records, x, y, direction, path, bins)[0]

    positions = positions.copy()
    faces = list(faces)
    front = original.copy()
    losses = [0.0] * len(pixels)
    patches = []
    retired = set()
    reports = []
    audits = []
    for edit in edits:
        started = time.perf_counter()
        ids = edit["faces"].keys()
        old_patch = make_grid(positions, faces, sorted(ids)) if policy != "full" else None
        positions[edit["keep"]] = edit["target"]
        for i, face in edit["faces"].items():
            faces[i] = face
        if policy == "full":
            current_grid = make_grid(positions, faces, range(len(faces)))
        else:
            new_patch = make_grid(positions, faces, sorted(ids))
            patches.append(new_patch)
            retired.update(ids)
        counters = Counter()
        for i, points in enumerate(pixels):
            before = front[i]
            after = []
            dirty = False
            for (x, y), envelope in zip(points, before):
                if policy == "full":
                    reason = "fullRebuild"
                    combined = lines(current_grid, x, y)
                    next_envelope = front_envelope(combined, path)
                    counters["sceneLineInputs"] += len(combined)
                    counters["sceneDuration"] += path[1] - path[0]
                else:
                    if position_in_bounds(x, y, edit["bounds"]):
                        old = lines(old_patch, x, y)
                        new = lines(new_patch, x, y)
                        if policy == "intersections":
                            reason = "intersected" if old or new else "noIntersection"
                        else:
                            reason = unchanged_reason(envelope, ids, old, new)
                    else:
                        reason = "outsideSweptBounds"
                    next_envelope = envelope
                    if reason in {"intersected", "editedWinner", "newFront"}:
                        combined = []
                        if policy != "intervals" or reason == "editedWinner":
                            combined = [line for line in lines(source_grid, x, y)
                                        if line["face"] not in retired]
                            for patch in patches:
                                combined.extend(lines(patch, x, y))
                            combined.sort(key=lambda line: line["face"])
                        if policy == "intervals":
                            next_envelope, duration, inputs = repair_front(envelope, ids, new,
                                                                           combined)
                            counters["sceneDuration"] += duration
                            counters["sceneLineInputs"] += inputs
                        else:
                            next_envelope = front_envelope(combined, path)
                            counters["sceneDuration"] += path[1] - path[0]
                            counters["sceneLineInputs"] += len(combined)
                counters[reason] += 1
                dirty |= next_envelope is not envelope
                after.append(next_envelope)
            if dirty:
                front[i] = after
                losses[i] = filtered_pixel_loss(original[i], after)
                counters["pixelsReintegrated"] += 1
        total = math.fsum(losses)
        counters.setdefault("pixelsReintegrated", 0)
        counters.setdefault("sceneDuration", 0.0)
        counters.setdefault("sceneLineInputs", 0)
        reports.append({"candidateId": edit["id"], "objective": total,
                        "seconds": time.perf_counter() - started, **counters})
        audits.append((front.copy(), losses.copy()))
    return reports, audits


def compare(full, incremental, path):
    """Audit face identity and depth on every interval of the combined partition."""
    maximum = 0.0
    max_visibility_difference = 0.0
    visibility_tolerance = 128 * max(math.ulp(t) for t in path)
    for (reference, ref_losses), (observed, losses) in zip(full, incremental, strict=True):
        for full_pixel, incr_pixel in zip(reference, observed, strict=True):
            for a, b in zip(full_pixel, incr_pixel, strict=True):
                i = j = 0
                unmatched_duration = 0.0
                while i < len(a) and j < len(b):
                    lo_a, hi_a, line_a = a[i]
                    lo_b, hi_b, line_b = b[j]
                    if line_a != line_b:
                        unmatched_duration += max(0.0, min(hi_a, hi_b) - max(lo_a, lo_b))
                    i += hi_a <= hi_b
                    j += hi_b <= hi_a
                if unmatched_duration > visibility_tolerance:
                    raise ValueError(f"a tap differs for {unmatched_duration:g} of the path")
                max_visibility_difference = max(max_visibility_difference, unmatched_duration)
        difference = max(abs(a - b) for a, b in zip(ref_losses, losses, strict=True))
        if difference > 1e-11:
            raise ValueError(f"per-pixel loss differs by {difference:g}")
        maximum = max(maximum, difference)
    return {"maxPixelLossDifference": maximum,
            "maxTapVisibilityDisagreementDuration": max_visibility_difference}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--unit-index", type=int, default=0)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--extent", nargs=2, type=int, default=(32, 16), metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--pan-angle", type=float, default=90)
    parser.add_argument("--path-radius", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    width, height = args.extent
    if not (1 <= width <= args.size and 1 <= height <= args.size and args.scale >= 1
            and args.count >= 2 and math.isfinite(args.path_radius) and args.path_radius > 0):
        parser.error("invalid tile, tap scale, edit count, or path radius")
    payload = args.capture.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    units = json.loads(payload)["units"]
    if not 0 <= args.unit_index < len(units):
        parser.error("unit-index must identify a capture unit")
    unit = units[args.unit_index]
    del payload
    world = np.asarray(unit["positions"], dtype=float)
    transform = camera(world, args.angle, args.size)
    positions = project(world, transform)
    candidates = unit["candidates"]
    if not 0 <= args.seed < len(candidates):
        parser.error("seed must be a captured candidate index")
    targets = project(np.asarray([row["target"] for row in candidates]), transform)
    for row, target in zip(candidates, targets):
        row["projectedTarget"] = target
    faces = unit["triangles"]
    cx, cy = targets[args.seed][:2]
    x0 = max(0, min(args.size - width, math.floor(cx - width / 2)))
    y0 = max(0, min(args.size - height, math.floor(cy - height / 2)))
    rect = (x0, y0, x0 + width, y0 + height)
    angle = math.radians(args.pan_angle)
    direction = (math.cos(angle), math.sin(angle))
    path = (-args.path_radius, args.path_radius)
    edits = pick_edits(positions, faces, candidates, args.seed, args.count, rect, direction, path)
    if len(edits) < 2:
        parser.error("fewer than two mutually disjoint edits touch the tile")
    pixels = [[(x + (sx + 0.5) / args.scale, y + (sy + 0.5) / args.scale)
               for sy in range(args.scale) for sx in range(args.scale)]
              for y in range(rect[1], rect[3]) for x in range(rect[0], rect[2])]
    started = time.perf_counter()
    source_grid = make_grid(positions, faces, range(len(faces)))
    records, bins = source_grid
    original = [[front_envelope(instantiate_path_lines(records, x, y, direction, path, bins)[0],
                                 path) for x, y in points] for points in pixels]
    setup_seconds = time.perf_counter() - started
    output = {"captureSha256": digest, "scope": __doc__,
              "unitIndex": args.unit_index, "imageSize": args.size, "cameraAngle": args.angle,
              "tile": rect, "scale": args.scale, "panAngle": args.pan_angle,
              "path": path, "initialSetupSeconds": setup_seconds,
              "appliedEdits": len(edits), "tapsPerEdit": len(pixels) * args.scale ** 2,
              "policies": {}}
    full_reports, reference = replay(positions, faces, edits, pixels, direction, path, "full",
                                     source_grid, original)
    output["policies"]["full"] = {"steps": full_reports}
    for policy in ("intersections", "dominance", "intervals"):
        reports, audited = replay(positions, faces, edits, pixels, direction, path, policy,
                                  source_grid, original)
        audit = compare(reference, audited, path)
        output["policies"][policy] = {**audit, "steps": reports}
        del audited
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"audited {len(edits)} disjoint edits over {len(pixels)} pixels, wrote {args.out}")


if __name__ == "__main__":
    main()
