#!/usr/bin/env python3
"""Compare cached and fresh path-loss decisions in a dynamic local simplifier."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import camera, project
from probe_incremental_path_visibility import (
    compare,
    filtered_pixel_loss,
    front_envelope,
    make_grid,
    unchanged_reason,
)
from probe_shared_envelope_raster_tile import instantiate_path_lines, triangle_path_coefficients


class SceneIndex:
    """Index the current triangle records by stable face ID."""

    cell_size = 8.0

    def __init__(self, positions, faces):
        self.records = {}
        self.bins = defaultdict(set)
        self.update(range(len(faces)), triangle_path_coefficients(positions, faces, range(len(faces))))

    def cells(self, record):
        x0, y0, x1, y1 = record[3]
        for x in range(math.floor(x0 / self.cell_size), math.floor(x1 / self.cell_size) + 1):
            for y in range(math.floor(y0 / self.cell_size), math.floor(y1 / self.cell_size) + 1):
                yield x, y

    def update(self, edited_ids, replacements):
        for face in edited_ids:
            old = self.records.pop(face, None)
            if old is None:
                continue
            for cell in self.cells(old):
                members = self.bins[cell]
                members.remove(face)
                if not members:
                    del self.bins[cell]
        for record in replacements:
            face = record[0]
            self.records[face] = record
            for cell in self.cells(record):
                self.bins[cell].add(face)

    def lines(self, x, y, direction, path):
        return instantiate_path_lines(
            self.records, x, y, direction, path, self.bins, self.cell_size)[0]


@dataclass
class Candidate:
    edge: tuple
    target: np.ndarray
    projected_target: np.ndarray
    faces: dict
    support: tuple
    signature: tuple


@dataclass
class PatchResult:
    records: list
    pixels: dict
    intersected: set
    tap_rebuilds: int


def link_cycle(vertex, incident, faces):
    links = Counter()
    adjacent = defaultdict(set)
    for face_id in incident[vertex]:
        a, b = (v for v in faces[face_id] if v != vertex)
        links[a] += 1
        links[b] += 1
        adjacent[a].add(b)
        adjacent[b].add(a)
    if not links or any(links[v] != 2 or len(adjacent[v]) != 2 for v in links):
        return set()
    visited = set()
    stack = [next(iter(links))]
    while stack:
        v = stack.pop()
        if v not in visited:
            visited.add(v)
            stack.extend(adjacent[v] - visited)
    return visited if len(visited) == len(links) else set()


def candidates_for_tile(world, projected, faces, rect, center, direction, path, limit):
    incident = defaultdict(list)
    edge_faces = defaultdict(list)
    face_counts = Counter()
    for i, face in enumerate(faces):
        if face is None:
            continue
        face_counts[tuple(sorted(face))] += 1
        for a, b in zip(face, (*face[1:], face[0])):
            incident[a].append(i)
            edge_faces[tuple(sorted((a, b)))].append(i)
    x0, y0, x1, y1 = rect
    edges = []
    for (keep, remove), common in edge_faces.items():
        if len(common) != 2:
            continue
        middle = (projected[keep] + projected[remove]) * 0.5
        if x0 <= middle[0] <= x1 and y0 <= middle[1] <= y1:
            distance = float(np.sum((middle[:2] - center) ** 2))
            edges.append((distance, keep, remove, middle, common))
    edges.sort(key=lambda row: row[:3])
    links = {}
    shift = np.asarray(path)[:, None] * np.asarray(direction)
    for _, keep, remove, middle, common in edges:
        for v in (keep, remove):
            if v not in links:
                links[v] = link_cycle(v, incident, faces)
        opposite = {v for i in common for v in faces[i]} - {keep, remove}
        if len(opposite) != 2 or links[keep] & links[remove] != opposite:
            continue
        ids = sorted(set(incident[keep]) | set(incident[remove]))
        vertices = sorted({v for i in ids for v in faces[i]})
        old_sorted = Counter(tuple(sorted(faces[i])) for i in ids)
        target = (world[keep] + world[remove]) * 0.5
        output = {}
        new_sorted = set()
        for i in ids:
            old = faces[i]
            new = tuple(keep if v == remove else v for v in old)
            if len(set(new)) != 3:
                output[i] = None
                continue
            key = tuple(sorted(new))
            if key in new_sorted or face_counts[key] > old_sorted[key]:
                break
            new_sorted.add(key)
            a, b, c = (world[v] for v in old)
            d, e, f = (target if v == keep else world[v] for v in new)
            previous = np.cross(b - a, c - a)
            following = np.cross(e - d, f - d)
            if np.dot(previous, following) <= 0.0:
                break
            output[i] = new
        else:
            patch_xy = projected[vertices, :2]
            lo = patch_xy.min(axis=0) - shift.max(axis=0) - 1e-8
            hi = patch_xy.max(axis=0) - shift.min(axis=0) + 1e-8
            if lo[0] < x0 or lo[1] < y0 or hi[0] > x1 or hi[1] > y1:
                continue
            support = tuple((y - y0) * (x1 - x0) + x - x0
                            for y in range(math.floor(lo[1]), math.ceil(hi[1]))
                            for x in range(math.floor(lo[0]), math.ceil(hi[0])))
            signature = (tuple((i, faces[i]) for i in ids), projected[vertices].tobytes())
            yield Candidate((keep, remove), target, middle, output, support, signature)
            limit -= 1
            if not limit:
                return


def evaluate(candidate, projected, faces, scene, original, current, points, direction, path,
             use_dominance, cached_patch=None, invalid_pixels=None):
    keep, _remove = candidate.edge
    ids = candidate.faces.keys()
    vertices = {v for tri in candidate.faces.values() if tri is not None for v in tri}
    replacement_positions = {v: projected[v] for v in vertices}
    replacement_positions[keep] = candidate.projected_target
    old_records, old_bins = make_grid(projected, faces, ids)
    records, bins = make_grid(replacement_positions, candidate.faces, ids)
    if cached_patch is None:
        changed_pixels = {}
        intersected = set()
        pixels = candidate.support
    else:
        changed_pixels = {i: update for i, update in cached_patch.pixels.items()
                          if i not in invalid_pixels}
        intersected = cached_patch.intersected
        pixels = sorted(invalid_pixels)
    rebuilt = 0
    for i in pixels:
        envelopes = []
        for (x, y), cached in zip(points[i], current[i], strict=True):
            old_lines = instantiate_path_lines(old_records, x, y, direction, path, old_bins)[0]
            new_lines = instantiate_path_lines(records, x, y, direction, path, bins)[0]
            reusable = not (old_lines or new_lines)
            if not reusable and cached_patch is None:
                intersected.add(i)
            if use_dominance and not reusable:
                reusable = unchanged_reason(cached, ids, old_lines, new_lines) == "occludedEdit"
            if reusable:
                envelopes.append(cached)
            else:
                combined = [line for line in scene.lines(x, y, direction, path)
                            if line["face"] not in ids]
                combined.extend(new_lines)
                envelopes.append(front_envelope(combined, path))
                rebuilt += 1
        if any(a is not b for a, b in zip(envelopes, current[i], strict=True)):
            changed_pixels[i] = envelopes, filtered_pixel_loss(original[i], envelopes)
    return PatchResult(records, changed_pixels, intersected, rebuilt)


def full_front(scene, points, direction, path):
    return [[front_envelope(scene.lines(x, y, direction, path), path) for x, y in pixel]
            for pixel in points]


def candidate_energy(losses, updates, current_energy):
    return math.fsum([current_energy, *(value - losses[i] for i, (_, value) in updates.items())])


def winner(scores):
    # Recompute the same deterministic near-tie rule in all three policies.
    best = min(scores.values())
    return min(edge for edge, score in scores.items() if score <= best + 1e-12)


def audit_candidate_scores(candidates, projected, faces, original, points, direction, path,
                           baseline):
    full = {}
    for candidate in candidates:
        geometry = projected.copy()
        geometry[candidate.edge[0]] = candidate.projected_target
        topology = list(faces)
        for i, face in candidate.faces.items():
            topology[i] = face
        front = full_front(SceneIndex(geometry, topology), points, direction, path)
        full[candidate.edge] = math.fsum(
            filtered_pixel_loss(a, b) for a, b in zip(original, front, strict=True))
    difference = max(abs(full[e] - baseline[e]) for e in full)
    if winner(full) != winner(baseline) or difference > 1e-11:
        raise ValueError(f"full candidate rebuild audit failed, maximum difference {difference:g}")
    return difference


def run(unit, args):
    world = np.asarray(unit["positions"], dtype=float)
    transform = camera(world, args.angle, args.size)
    projected = project(world, transform)
    faces = [tuple(f) for f in unit["triangles"]]
    initial_faces = len(faces)
    center = project(np.asarray([unit["candidates"][args.seed]["target"]]), transform)[0, :2]
    width, height = args.extent
    x0 = max(0, min(args.size - width, math.floor(center[0] - width / 2)))
    y0 = max(0, min(args.size - height, math.floor(center[1] - height / 2)))
    rect = (x0, y0, x0 + width, y0 + height)
    angle = math.radians(args.pan_angle)
    direction = (math.cos(angle), math.sin(angle))
    path = (-args.radius, args.radius)
    points = [[(x + (sx + 0.5) / args.scale, y + (sy + 0.5) / args.scale)
               for sy in range(args.scale) for sx in range(args.scale)]
              for y in range(rect[1], rect[3]) for x in range(rect[0], rect[2])]
    started = time.perf_counter()
    scene = SceneIndex(projected, faces)
    original = full_front(scene, points, direction, path)
    setup_seconds = time.perf_counter() - started
    front = original.copy()
    losses = [0.0] * len(points)
    stamps = [0] * len(points)
    cache = {}
    steps = []
    prior_patch = set()
    prior_vertices = set()
    for epoch in range(1, args.edits + 1):
        started = time.perf_counter()
        candidates = list(candidates_for_tile(world, projected, faces, rect, center,
                                               direction, path, args.pool))
        selection_seconds = time.perf_counter() - started
        if not candidates:
            break
        current_energy = math.fsum(losses)
        answer = {}
        work = {}
        best_update = None
        for policy in ("intersections", "dominance", "cached"):
            started = time.perf_counter()
            scores = {}
            results = {}
            taps = hits = matching_geometry = reused_pixels = 0
            next_cache = {}
            for candidate in candidates:
                edge = candidate.edge
                previous = cache.get(edge) if policy == "cached" else None
                patch = None
                invalid = None
                if previous is not None and candidate.signature == previous[0]:
                    matching_geometry += 1
                    patch = previous[2]
                    invalid = {i for i in patch.intersected if stamps[i] > previous[1]}
                    reused_pixels += len(patch.intersected) - len(invalid)
                if patch is not None and not invalid:
                    record = patch
                    hits += 1
                else:
                    record = evaluate(candidate, projected, faces, scene, original, front,
                                      points, direction, path, policy != "intersections",
                                      patch, invalid)
                    taps += record.tap_rebuilds
                results[edge] = record
                scores[edge] = candidate_energy(losses, record.pixels, current_energy)
                if policy == "cached":
                    next_cache[edge] = (candidate.signature, epoch - 1, record)
            edge = winner(scores)
            work[policy] = {"edge": edge, "seconds": time.perf_counter() - started,
                            "tapRebuilds": taps, "scoreCacheHits": hits,
                            "matchingGeometry": matching_geometry,
                            "reusedPatchPixels": reused_pixels}
            answer[policy] = scores
            if policy == "cached":
                cache = next_cache
                best_update = results[edge]
        edge = work["intersections"]["edge"]
        if any(row["edge"] != edge for row in work.values()):
            raise ValueError(f"decision differs at step {epoch}: {work}")
        discrepancy = max(abs(scores[e] - answer["intersections"][e])
                          for scores in answer.values() for e in scores)
        if discrepancy > 1e-11:
            raise ValueError(f"candidate scores differ by {discrepancy:g}")
        full_difference = (audit_candidate_scores(candidates, projected, faces, original, points,
                                                  direction, path, answer["intersections"])
                           if args.audit_all_candidates else None)
        choice = next(c for c in candidates if c.edge == edge)
        keep, _ = edge
        shared_vertices = len(set(edge) & prior_vertices)
        shared_faces = len(choice.faces.keys() & prior_patch)
        prior_vertices = set(edge)
        prior_patch = set(choice.faces)
        started = time.perf_counter()
        projected[keep] = choice.projected_target
        world[keep] = choice.target
        for i, face in choice.faces.items():
            faces[i] = face
        scene.update(choice.faces, best_update.records)
        for i, (envelopes, loss) in best_update.pixels.items():
            front[i], losses[i] = envelopes, loss
        for i in best_update.intersected:
            stamps[i] = epoch
        apply_seconds = time.perf_counter() - started
        # A fresh scene built from the accepted mesh audits both the invalidation
        # footprint and dynamic face-bin updates across overlapping edits.
        reference = full_front(SceneIndex(projected, faces), points, direction, path)
        ref_losses = [filtered_pixel_loss(a, b) for a, b in zip(original, reference, strict=True)]
        audit = compare([(reference, ref_losses)], [(front, losses)], path)
        steps.append({"step": epoch, "edge": edge, "candidates": len(candidates),
                      "loss": math.fsum(losses), "sharedVerticesWithPrevious": shared_vertices,
                      "sharedFacesWithPrevious": shared_faces, "maxCandidateDifference": discrepancy,
                      "maxFullCandidateDifference": full_difference,
                      "candidateGenerationSeconds": selection_seconds, "applySeconds": apply_seconds,
                      "policies": work, **audit})
    return {"tile": rect, "initialSetupSeconds": setup_seconds, "initialFaces": initial_faces,
            "finalFaces": sum(face is not None for face in faces),
            "maxCacheEntries": max((row["candidates"] for row in steps), default=0),
            "steps": steps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--unit-index", type=int, default=0)
    parser.add_argument("--edits", type=int, default=8)
    parser.add_argument("--pool", type=int, default=12)
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--extent", type=int, nargs=2, default=(32, 16))
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--pan-angle", type=float, default=90.0)
    parser.add_argument("--radius", type=float, default=1.0)
    parser.add_argument("--audit-all-candidates", action="store_true",
                        help="independently rebuild the full viewport tile for every proposal")
    args = parser.parse_args()
    if (min(args.edits, args.pool, args.scale, *args.extent) < 1
            or max(args.extent) > args.size or not math.isfinite(args.radius) or args.radius <= 0):
        parser.error("invalid edit budget, sample scale, tile, or path radius")
    capture = args.capture.read_bytes()
    units = json.loads(capture)["units"]
    digest = hashlib.sha256(capture).hexdigest()
    del capture
    if not 0 <= args.unit_index < len(units):
        parser.error("invalid unit index")
    unit = units[args.unit_index]
    if not 0 <= args.seed < len(unit["candidates"]):
        parser.error("invalid seed candidate index")
    result = run(unit, args)
    result.update({"captureSha256": digest, "seed": args.seed, "unitIndex": args.unit_index,
                   "requestedEdits": args.edits, "pool": args.pool, "scale": args.scale,
                   "size": args.size, "angle": args.angle, "panAngle": args.pan_angle,
                   "radius": args.radius})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result['steps'])} decisions audited, wrote {args.out}")


if __name__ == "__main__":
    main()
