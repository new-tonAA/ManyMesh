#!/usr/bin/env python3
"""Score multiple continuous raster paths with exact candidate early stopping."""

import argparse
from collections import ChainMap, defaultdict
from copy import copy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import camera, project
from probe_dynamic_path_simplification import (
    SceneIndex,
    candidates_for_tile,
    evaluate,
    heldout_raster_quality,
    indexed_normals,
    placement_normals,
    winner,
)
from probe_incremental_path_visibility import front_envelope


class View:
    def __init__(self, world, faces, azimuth, args):
        self.transform = camera(world, azimuth, args.size)
        self.projected = project(world, self.transform)
        self.original_scene = SceneIndex(self.projected, faces)
        # The unchanged face records are immutable. Only the face map and bins are copied.
        self.scene = copy(self.original_scene)
        self.scene.records = self.original_scene.records.copy()
        self.scene.bins = defaultdict(set, ((cell, ids.copy())
                                            for cell, ids in self.original_scene.bins.items()))
        self.size = args.size
        self.scale = args.scale
        radians = math.radians(args.pan_angle)
        self.direction = math.cos(radians), math.sin(radians)
        self.path = (-args.radius, args.radius)
        delta = np.asarray(self.path)[:, None] * np.asarray(self.direction)
        self.shift_min = delta.min(axis=0)
        self.shift_max = delta.max(axis=0)
        self.original = {}
        self.front = {}
        self.points = {}
        self.losses = {}
        self.stamps = {}
        self.cache = {}

    def proposal(self, candidate, faces):
        keep, remove = candidate.edge
        target = (self.projected[keep] + self.projected[remove]) * 0.5
        ids = sorted({v for face_id in candidate.faces for v in faces[face_id]})
        xy = self.projected[ids, :2]
        lo = xy.min(axis=0) - self.shift_max - 1e-8
        hi = xy.max(axis=0) - self.shift_min + 1e-8
        support = tuple(y * self.size + x
                        for y in range(max(0, math.floor(lo[1])), min(self.size, math.ceil(hi[1])))
                        for x in range(max(0, math.floor(lo[0])), min(self.size, math.ceil(hi[0]))))
        return replace(candidate, projected_target=target, support=support)

    def outside_loss(self, proposal):
        # Nonnegative contributions unaffected by this edit, even in unscored views.
        support = set(proposal.support)
        return math.fsum(value for i, value in self.losses.items() if i not in support)

    def score(self, proposal, outside_loss, faces, normal_data, epoch, reuse):
        for i in proposal.support:
            if i in self.original:
                continue
            y, x = divmod(i, self.size)
            points = [(x + (sx + 0.5) / self.scale, y + (sy + 0.5) / self.scale)
                      for sy in range(self.scale) for sx in range(self.scale)]
            self.points[i] = points
            self.original[i] = [front_envelope(self.original_scene.lines(
                tx, ty, self.direction, self.path), self.path) for tx, ty in points]
            self.front[i] = self.original[i]
        previous = self.cache.get(proposal.edge) if reuse else None
        patch, invalid = None, None
        if previous is not None and proposal.signature == previous[0]:
            patch = previous[2]
            invalid = {i for i in patch.intersected if self.stamps.get(i, 0) > previous[1]}
        if patch is not None and not invalid:
            result = patch
            rebuilt = 0
        else:
            result = evaluate(proposal, self.projected, faces, self.scene, self.original,
                              self.front, self.points, self.direction, self.path, True,
                              patch, invalid, normal_data)
            rebuilt = result.tap_rebuilds
        if reuse:
            self.cache[proposal.edge] = (proposal.signature, epoch - 1, result)
        pixel_losses = (result.pixels[i][1] if i in result.pixels else self.losses.get(i, 0.0)
                        for i in proposal.support)
        score = math.fsum((outside_loss, math.fsum(pixel_losses)))
        return score, result, rebuilt

    def apply(self, proposal, result, epoch):
        self.projected[proposal.edge[0]] = proposal.projected_target
        self.scene.update(proposal.faces, result.records)
        for i, (envelopes, loss) in result.pixels.items():
            self.front[i] = envelopes
            self.losses[i] = loss
        for i in result.intersected:
            self.stamps[i] = epoch


def run(unit, control, args):
    world = np.asarray(unit["positions"], dtype=float)
    faces = [tuple(face) for face in unit["triangles"]]
    started = time.perf_counter()
    views = [View(world, faces, args.angle + offset, args) for offset in args.view_offsets]
    primary = views[0]
    center = project(np.asarray([unit["candidates"][args.seed]["target"]]),
                     primary.transform)[0, :2]
    rect = tuple(control["tile"])
    source_normals = indexed_normals(world, faces) if args.normal_weight else None
    current_normals = source_normals.copy() if source_normals is not None else None
    setup_seconds = time.perf_counter() - started
    rows = []
    for epoch in range(1, args.edits + 1):
        started = time.perf_counter()
        candidates = list(candidates_for_tile(world, primary.projected, faces, rect, center,
                                             primary.direction, primary.path, args.pool))
        if not candidates:
            break
        edges = {candidate.edge for candidate in candidates}
        for view in views:
            # Bound cache storage by the live pool, even for candidates pruned early this step.
            view.cache = {edge: value for edge, value in view.cache.items() if edge in edges}
        scores, complete, pending = {}, {}, {}
        counts = [0] * len(views)
        rebuilt = [0] * len(views)
        best = math.inf
        for candidate in candidates:
            edge = candidate.edge
            projections = [view.proposal(candidate, faces) for view in views]
            outside = [view.outside_loss(proposal) for view, proposal in zip(views, projections)]
            normals = ((source_normals, ChainMap(placement_normals(world, candidate),
                                                  current_normals), args.normal_weight)
                       if current_normals is not None else None)
            values = []
            patches = []
            for i, view in enumerate(views):
                lower = (math.fsum(values) if args.partial_only_bound
                         else math.fsum((*values, *outside[i:])))
                # Allow all candidates in the same numerical tie class as the incumbent.
                if not args.exhaustive and lower > best + 2e-12:
                    if args.audit_pruning:
                        pending[edge] = projections, outside, normals, values, lower
                    break
                value, patch, taps = view.score(projections[i], outside[i], faces, normals,
                                                epoch, True)
                counts[i] += 1
                rebuilt[i] += taps
                values.append(value)
                patches.append(patch)
            else:
                score = math.fsum(values)
                scores[edge] = score
                complete[edge] = projections, patches, normals, values
                best = min(best, score)
        choice = winner(scores)
        scoring_seconds = time.perf_counter() - started
        if args.audit_pruning:
            full = scores.copy()
            for edge, (projections, outside, normals, values, lower) in pending.items():
                first = len(values)
                more = [view.score(projections[i], outside[i], faces, normals, epoch, False)[0]
                        for i, view in enumerate(views[first:], first)]
                full[edge] = math.fsum((*values, *more))
                if lower > full[edge] + 1e-11:
                    raise ValueError("partial loss exceeded its completed candidate score")
            if winner(full) != choice:
                raise ValueError(f"early stopping changed the chosen edge at step {epoch}")
        projections, patches, normals, values = complete[choice]
        for view, proposal, patch in zip(views, projections, patches, strict=True):
            view.apply(proposal, patch, epoch)
        chosen = projections[0]
        world[choice[0]] = chosen.target
        for face_id, face in chosen.faces.items():
            faces[face_id] = face
            if current_normals is not None:
                del current_normals[face_id]
        if normals is not None:
            current_normals.update(normals[1].maps[0])
        rows.append({"step": epoch, "edge": choice, "target": chosen.target.tolist(),
                     "candidates": len(candidates), "completedCandidates": len(scores),
                     "perViewScore": values, "perViewEvaluations": counts,
                     "perViewTapRebuilds": rebuilt, "seconds": scoring_seconds,
                     "auditedPrunedCandidates": len(pending)})
    result = {"steps": rows, "setupSeconds": setup_seconds, "tile": rect,
              "viewOffsets": args.view_offsets, "auditedPruning": args.audit_pruning,
              "exhaustive": args.exhaustive, "partialOnlyBound": args.partial_only_bound,
              "normalWeight": args.normal_weight}
    if not args.score_only:
        result["heldoutRasterQuality"] = heldout_raster_quality(
            unit, rows, control["qemControl"]["steps"], args, {"singlePath": control["steps"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--view-offsets", nargs="+", type=float,
                        default=(0.0, 2 * math.pi / 3, -2 * math.pi / 3))
    parser.add_argument("--audit-pruning", action="store_true")
    parser.add_argument("--exhaustive", action="store_true")
    parser.add_argument("--partial-only-bound", action="store_true",
                        help="ablate the unchanged-pixel contribution of unscored views")
    parser.add_argument("--score-only", action="store_true",
                        help="skip independent held-out rendering for scoring comparisons")
    args = parser.parse_args()
    if (not args.view_offsets or args.view_offsets[0] != 0.0
            or not all(math.isfinite(value) for value in args.view_offsets)):
        parser.error("view offsets must be finite and start with zero for the primary view")
    control_bytes = args.control.read_bytes()
    control = json.loads(control_bytes)
    capture = args.capture.read_bytes()
    digest = hashlib.sha256(capture).hexdigest()
    if control.get("captureSha256") != digest or "qemControl" not in control:
        parser.error("control must be a single-path/QEM comparison of this exact capture")
    for attribute, field in (("seed", "seed"), ("unit_index", "unitIndex"),
                             ("edits", "requestedEdits"), ("pool", "pool"),
                             ("scale", "scale"), ("size", "size"), ("angle", "angle"),
                             ("pan_angle", "panAngle"), ("radius", "radius"),
                             ("normal_weight", "normalWeight")):
        setattr(args, attribute, control[field])
    quality = control["heldoutRasterQuality"]
    args.quality_size, args.quality_scale, args.quality_steps = (
        quality["size"], quality["scale"], quality["steps"])
    unit = json.loads(capture)["units"][args.unit_index]
    del capture
    result = run(unit, control, args)
    result.update({"captureSha256": digest, "control": str(args.control),
                   "controlSha256": hashlib.sha256(control_bytes).hexdigest()})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result['steps'])} decisions, wrote {args.out}")


if __name__ == "__main__":
    main()
