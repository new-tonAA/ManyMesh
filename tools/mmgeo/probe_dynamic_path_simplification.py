#!/usr/bin/env python3
"""Compare cached and fresh path-loss decisions in a dynamic local simplifier."""

import argparse
from collections import ChainMap, Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import camera, project, raster
from probe_incremental_path_visibility import (
    compare,
    filtered_pixel_loss,
    front_envelope,
    make_grid,
    unchanged_reason,
)
from probe_shared_envelope_raster_tile import (
    build_path_triangle_grid, instantiate_path_lines, triangle_path_coefficients,
)


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
    placement_rank: int | None = None

    @property
    def key(self):
        return self.edge if self.placement_rank is None else (*self.edge, self.placement_rank)


@dataclass
class PatchResult:
    records: list
    pixels: dict
    intersected: set
    tap_rebuilds: int
    pixel_visits: int
    partial_loss: float | None = None
    pending_pixels: set | None = None


@dataclass
class PixelBudget:
    limit: float
    current_losses: dict
    order: str
    retain_partial: bool = False


def known_support_loss(support, updates, invalid, current_losses):
    return math.fsum(updates[i][1] if i in updates else current_losses.get(i, 0.0)
                     for i in support if i not in invalid)


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
             use_dominance, cached_patch=None, invalid_pixels=None, normal_data=None,
             pixel_budget=None, prepare_pixel=None, reuse_face_records=False, scene_lines=None):
    keep, _remove = candidate.edge
    ids = candidate.faces.keys()
    if cached_patch is None:
        changed_pixels = {}
        intersected = set()
        pixels = candidate.support
    else:
        changed_pixels = {i: update for i, update in cached_patch.pixels.items()
                          if i not in invalid_pixels}
        intersected = (cached_patch.intersected.copy() if cached_patch.pending_pixels is not None
                       else cached_patch.intersected)
        pixels = sorted(invalid_pixels)
    can_discover_intersections = cached_patch is None or cached_patch.pending_pixels is not None
    lower = 0.0
    if pixel_budget is not None:
        losses = pixel_budget.current_losses
        if cached_patch is not None:
            lower = math.nextafter(known_support_loss(candidate.support, changed_pixels,
                                                      invalid_pixels, losses), -math.inf)
        if lower > pixel_budget.limit:
            records = cached_patch.records if cached_patch is not None else []
            pending = set(pixels) if pixel_budget.retain_partial else None
            return PatchResult(records, changed_pixels, intersected, 0, 0, lower, pending)
        if pixel_budget.order == "loss":
            pixels = sorted(pixels, key=lambda i: (-losses.get(i, 0.0), i))
    if reuse_face_records:
        old_records = [scene.records[i] for i in ids if i in scene.records]
        old_bins = build_path_triangle_grid(old_records)
    else:
        old_records, old_bins = make_grid(projected, faces, ids)
    if reuse_face_records and cached_patch is not None and cached_patch.records:
        records = cached_patch.records
        bins = build_path_triangle_grid(records)
    else:
        vertices = {v for tri in candidate.faces.values() if tri is not None for v in tri}
        replacement_positions = {v: projected[v] for v in vertices}
        replacement_positions[keep] = candidate.projected_target
        records, bins = make_grid(replacement_positions, candidate.faces, ids)
    lines_at = scene.lines if scene_lines is None else scene_lines
    rebuilt = 0
    visits = 0
    for visits, i in enumerate(pixels, 1):
        if prepare_pixel is not None and i not in original:
            prepare_pixel(i)
        envelopes = []
        for (x, y), cached in zip(points[i], current[i], strict=True):
            old_lines = instantiate_path_lines(old_records, x, y, direction, path, old_bins)[0]
            new_lines = instantiate_path_lines(records, x, y, direction, path, bins)[0]
            reusable = not (old_lines or new_lines)
            if not reusable and can_discover_intersections:
                intersected.add(i)
            if use_dominance and not reusable:
                reusable = unchanged_reason(cached, ids, old_lines, new_lines) == "occludedEdit"
            if reusable:
                envelopes.append(cached)
            else:
                combined = [line for line in lines_at(x, y, direction, path)
                            if line["face"] not in ids]
                combined.extend(new_lines)
                envelopes.append(front_envelope(combined, path))
                rebuilt += 1
        if any(a is not b for a, b in zip(envelopes, current[i], strict=True)):
            changed_pixels[i] = envelopes, filtered_pixel_loss(original[i], envelopes, normal_data)
        if pixel_budget is not None:
            loss = changed_pixels[i][1] if i in changed_pixels else losses.get(i, 0.0)
            # Round down at each addition so an accumulated rounding error cannot prune a tie.
            lower = math.nextafter(lower + loss, -math.inf)
            if lower > pixel_budget.limit:
                pending = set(pixels[visits:]) if pixel_budget.retain_partial else None
                return PatchResult(records, changed_pixels, intersected, rebuilt, visits, lower,
                                   pending)
    return PatchResult(records, changed_pixels, intersected, rebuilt, visits)


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
                           baseline, proposal_normals):
    full = {}
    for candidate in candidates:
        geometry = projected.copy()
        geometry[candidate.edge[0]] = candidate.projected_target
        topology = list(faces)
        for i, face in candidate.faces.items():
            topology[i] = face
        front = full_front(SceneIndex(geometry, topology), points, direction, path)
        full[candidate.edge] = math.fsum(
            filtered_pixel_loss(a, b, proposal_normals.get(candidate.edge))
            for a, b in zip(original, front, strict=True))
    difference = max(abs(full[e] - baseline[e]) for e in full)
    if winner(full) != winner(baseline) or difference > 1e-11:
        raise ValueError(f"full candidate rebuild audit failed, maximum difference {difference:g}")
    return difference


def source_quadrics(positions, faces):
    """Accumulate area-weighted plane quadrics, matching the progressive QEM control."""
    triangles = np.asarray(faces, dtype=np.int64)
    points = positions[triangles]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    twice_area = np.linalg.norm(normals, axis=1)
    valid = twice_area > 0.0
    normals[valid] /= twice_area[valid, None]
    planes = np.column_stack((normals, -np.sum(normals * points[:, 0], axis=1)))
    face_quadrics = planes[:, :, None] * planes[:, None, :] * (0.5 * twice_area[:, None, None])
    quadrics = np.zeros((len(positions), 4, 4), dtype=np.float64)
    for corner in range(3):
        np.add.at(quadrics, triangles[:, corner], face_quadrics)
    return quadrics


def quadric_cost(candidate, quadrics, origin):
    a, b = candidate.edge
    point = np.append(candidate.target - origin, 1.0)
    return max(0.0, float(point @ (quadrics[a] + quadrics[b]) @ point))


def indexed_normals(world, faces):
    ids = [i for i, face in enumerate(faces) if face is not None]
    return dict(zip(ids, flat_world_normals(world, [faces[i] for i in ids]), strict=True))


def placement_normals(world, candidate):
    keep, _ = candidate.edge
    result = {}
    for i, face in candidate.faces.items():
        if face is None:
            continue
        a, b, c = (candidate.target if v == keep else world[v] for v in face)
        normal = np.cross(b - a, c - a)
        result[i] = normal / np.linalg.norm(normal)
    return result


def run(unit, args, decision="path"):
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
    source_normals = indexed_normals(world, faces) if args.normal_weight else None
    current_normals = source_normals.copy() if source_normals is not None else None
    setup_seconds = time.perf_counter() - started
    quadric_origin = world.mean(axis=0)
    quadric_start = time.perf_counter()
    quadrics = source_quadrics(world - quadric_origin, faces) if decision == "qem" else None
    quadric_seconds = time.perf_counter() - quadric_start if quadrics is not None else None
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
        proposal_normals = {
            c.edge: (source_normals, ChainMap(placement_normals(world, c), current_normals),
                     args.normal_weight)
            for c in candidates
        } if current_normals is not None else {}
        selection_seconds = time.perf_counter() - started
        if not candidates:
            break
        current_energy = math.fsum(losses)
        answer = {}
        work = {}
        best_update = None
        for policy in (("intersections", "dominance", "cached") if quadrics is None else ("qem",)):
            started = time.perf_counter()
            if policy == "qem":
                choice = min(candidates, key=lambda c: (quadric_cost(c, quadrics, quadric_origin),
                                                        c.edge))
                work[policy] = {"edge": choice.edge, "seconds": time.perf_counter() - started}
                best_update = evaluate(choice, projected, faces, scene, original, front,
                                       points, direction, path, True,
                                       normal_data=proposal_normals.get(choice.edge))
                continue
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
                                      patch, invalid, proposal_normals.get(edge))
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
        edge = work["intersections" if quadrics is None else "qem"]["edge"]
        if any(row["edge"] != edge for row in work.values()):
            raise ValueError(f"decision differs at step {epoch}: {work}")
        discrepancy = (max(abs(scores[e] - answer["intersections"][e])
                           for scores in answer.values() for e in scores) if answer else None)
        if discrepancy is not None and discrepancy > 1e-11:
            raise ValueError(f"candidate scores differ by {discrepancy:g}")
        full_difference = (audit_candidate_scores(candidates, projected, faces, original, points,
                                                  direction, path, answer["intersections"],
                                                  proposal_normals)
                           if args.audit_all_candidates and answer else None)
        choice = next(c for c in candidates if c.edge == edge)
        keep, remove = edge
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
        if current_normals is not None:
            for face_id in choice.faces:
                current_normals.pop(face_id)
            current_normals.update(proposal_normals[edge][1].maps[0])
        if quadrics is not None:
            quadrics[keep] += quadrics[remove]
            quadrics[remove].fill(0.0)
        apply_seconds = time.perf_counter() - started
        # A fresh scene built from the accepted mesh audits both the invalidation
        # footprint and dynamic face-bin updates across overlapping edits.
        reference = full_front(SceneIndex(projected, faces), points, direction, path)
        ref_normals = ((source_normals, indexed_normals(world, faces), args.normal_weight)
                       if current_normals is not None else None)
        ref_losses = [filtered_pixel_loss(a, b, ref_normals)
                      for a, b in zip(original, reference, strict=True)]
        audit = compare([(reference, ref_losses)], [(front, losses)], path)
        steps.append({"step": epoch, "edge": edge, "target": choice.target.tolist(),
                      "candidates": len(candidates),
                      "loss": math.fsum(losses), "sharedVerticesWithPrevious": shared_vertices,
                      "sharedFacesWithPrevious": shared_faces, "maxCandidateDifference": discrepancy,
                      "maxFullCandidateDifference": full_difference,
                      "candidateGenerationSeconds": selection_seconds, "applySeconds": apply_seconds,
                      "policies": work, **audit})
    return {"tile": rect, "initialSetupSeconds": setup_seconds, "initialFaces": initial_faces,
            "quadricSetupSeconds": quadric_seconds,
            "finalFaces": sum(face is not None for face in faces),
            "maxCacheEntries": max((row["candidates"] for row in steps), default=0),
            "steps": steps}


def replay_geometry(unit, steps):
    world = np.array(unit["positions"], dtype=float)
    faces = np.array(unit["triangles"], dtype=np.int64)
    for step in steps:
        keep, remove = step["edge"]
        world[keep] = step["target"]
        faces[faces == remove] = keep
    alive = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) &
             (faces[:, 2] != faces[:, 0]))
    return world, faces[alive]


def collapse_map_bound(source, target, steps):
    """Bound both surface distances when the collapse map covers exactly the final mesh."""
    positions, faces = source
    simplified, target_faces = target
    representative = np.arange(len(positions))
    for step in steps:
        keep, remove = step["edge"]
        if (not 0 <= keep < len(positions) or not 0 <= remove < len(positions)
                or keep == remove or representative[keep] != keep
                or representative[remove] != remove):
            raise ValueError("collapse map must merge two distinct live vertices")
        representative[remove] = keep
    while True:
        compressed = representative[representative]
        if np.array_equal(compressed, representative):
            break
        representative = compressed
    mapped = representative[faces]
    alive = ((mapped[:, 0] != mapped[:, 1]) & (mapped[:, 1] != mapped[:, 2]) &
             (mapped[:, 2] != mapped[:, 0]))
    final_vertices = set(target_faces.flat)
    final_edges = {tuple(sorted((face[i], face[(i + 1) % 3])))
                   for face in target_faces for i in range(3)}
    covers_both = np.array_equal(mapped[alive], target_faces)
    for face in mapped[~alive]:
        image = sorted(set(face))
        if ((len(image) == 1 and image[0] not in final_vertices) or
                (len(image) == 2 and tuple(image) not in final_edges)):
            covers_both = False
            break
    used = np.unique(faces)
    displacement = np.linalg.norm(simplified[representative[used]] - positions[used], axis=1)
    bound = float(displacement.max(initial=0.0))
    center = 0.5 * (positions.min(axis=0) + positions.max(axis=0))
    radius = max(1e-12, float(np.linalg.norm(positions - center, axis=1).max()))
    return {"maxVertexDisplacement": bound, "relativeToSourceRadius": bound / radius,
            "coversBothSurfaces": bool(covers_both),
            "symmetricSurfaceDistanceUpperBound": bound if covers_both else None}


def raster_attributes(projected, faces, normals, displacement, size, scale):
    shifted = projected.copy()
    shifted[:, :2] -= displacement
    image, owners = raster(shifted, faces, np.ones(len(faces), dtype=bool),
                           (0, 0, size, size), scale)
    normal_image = np.zeros((*owners.shape, 3), dtype=float)
    valid = owners >= 0
    normal_image[valid] = normals[owners[valid]]
    shape = (size, scale, size, scale)
    return (image.reshape(*shape, 2).mean(axis=(1, 3)),
            normal_image.reshape(*shape, 3).mean(axis=(1, 3)))


def flat_world_normals(positions, faces):
    a, b, c = positions[np.asarray(faces, dtype=np.int64).reshape(-1, 3)].transpose(1, 0, 2)
    normals = np.cross(b - a, c - a)
    length = np.linalg.norm(normals, axis=1)
    nonzero = length > 0.0
    normals[nonzero] /= length[nonzero, None]
    return normals


def heldout_raster_quality(unit, path_steps, qem_steps, args, extra_steps=None, views=None):
    policies = {"path": path_steps, "qem": qem_steps, **(extra_steps or {})}
    count = min(map(len, policies.values()))
    meshes = {"original": replay_geometry(unit, []),
              **{name: replay_geometry(unit, steps[:count]) for name, steps in policies.items()}}
    if len({len(meshes[name][1]) for name in policies}) != 1:
        raise ValueError("the final meshes must use the same face budget")
    size = args.quality_size
    # Avoid revisiting the optimization segment. The last two paths also change azimuth.
    if views is None:
        views = (("differentPan", args.angle, args.pan_angle + 37.0),
                 ("changedView", args.angle + 0.65, args.pan_angle - 29.0),
                 ("oppositeView", args.angle + math.pi, args.pan_angle + 15.0))
    radius = 1.25 * args.radius * size / args.size
    times = [radius * (2.0 * (i + 0.5) / args.quality_steps - 1.0)
             for i in range(args.quality_steps)]
    rows = []
    normals = {name: flat_world_normals(*mesh) for name, mesh in meshes.items()}
    for label, azimuth, pan in views:
        transform = camera(meshes["original"][0], azimuth, size)
        direction = np.asarray([math.cos(math.radians(pan)), math.sin(math.radians(pan))])
        projected = {name: project(mesh[0], transform) for name, mesh in meshes.items()}
        totals = {name: np.zeros(3) for name in policies}
        for t in times:
            displacement = direction * t
            source, source_normals = raster_attributes(projected["original"],
                                                       meshes["original"][1],
                                                       normals["original"], displacement,
                                                       size, args.quality_scale)
            for name in totals:
                image, normal = raster_attributes(projected[name], meshes[name][1], normals[name],
                                                  displacement, size, args.quality_scale)
                totals[name][:2] += np.square(source - image).mean(axis=(0, 1))
                totals[name][2] += np.square(source_normals - normal).sum(axis=2).mean()
        metrics = ("coverageMse", "depthMse", "flatNormalSquaredDistance")
        rows.append({"view": label, "azimuth": azimuth, "panAngle": pan,
                     **{name: dict(zip(metrics, values.tolist(), strict=True))
                        for name, values in ((k, v / len(times)) for k, v in totals.items())}})
    geometry = {name: collapse_map_bound(meshes["original"], meshes[name], steps[:count])
                for name, steps in policies.items()}
    return {"matchedEdits": count, "matchedFaces": len(meshes["path"][1]),
            "size": size, "scale": args.quality_scale, "steps": len(times),
            "radius": radius, "views": rows, "geometry": geometry}


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
    parser.add_argument("--compare-qem", action="store_true",
                        help="compare midpoint QEM and evaluate final meshes on other raster paths")
    parser.add_argument("--normal-weight", type=float, default=0.0,
                        help="weight of squared filtered flat-normal difference in the exact loss")
    parser.add_argument("--quality-size", type=int, default=80)
    parser.add_argument("--quality-scale", type=int, default=2)
    parser.add_argument("--quality-steps", type=int, default=8)
    args = parser.parse_args()
    if (min(args.edits, args.pool, args.scale, args.quality_size, args.quality_scale,
            args.quality_steps, *args.extent) < 1
            or max(args.extent) > args.size or not math.isfinite(args.radius) or args.radius <= 0
            or not math.isfinite(args.normal_weight) or args.normal_weight < 0):
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
    if args.compare_qem:
        control = run(unit, args, "qem")
        result["qemControl"] = control
        result["heldoutRasterQuality"] = heldout_raster_quality(
            unit, result["steps"], control["steps"], args)
    result.update({"captureSha256": digest, "seed": args.seed, "unitIndex": args.unit_index,
                   "requestedEdits": args.edits, "pool": args.pool, "scale": args.scale,
                   "size": args.size, "angle": args.angle, "panAngle": args.pan_angle,
                   "radius": args.radius, "normalWeight": args.normal_weight})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result['steps'])} decisions audited, wrote {args.out}")


if __name__ == "__main__":
    main()
