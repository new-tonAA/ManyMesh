#!/usr/bin/env python3
"""Compare full-unit QEM with continuous path reranking of the same legal queue."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import project
from probe_dynamic_path_simplification import (
    Candidate, SceneIndex, heldout_raster_quality, indexed_normals,
)
from probe_incremental_path_visibility import filtered_pixel_loss, front_envelope
from probe_multiview_path_simplification import View, select_path_edge
from progressive_geometry_baseline import ProgressiveQEM


def proposal_for_entry(queue, entry, faces):
    _, keep, remove, _, _, _, point = entry
    target = np.asarray(point)
    incident = sorted(queue.inc[keep] | queue.inc[remove])
    vertices = sorted({v for face_id in incident for v in faces[face_id]})
    patch = {}
    for face_id in incident:
        triangle = tuple(keep if v == remove else v for v in faces[face_id])
        patch[face_id] = triangle if len(set(triangle)) == 3 else None
    signature = (tuple((i, faces[i]) for i in incident), queue.p[vertices].tobytes(),
                 target.tobytes())
    # There is no preprojected midpoint. Each view projects the actual optimal placement.
    return Candidate((keep, remove), target, None, patch, (), signature)


def audit_final_views(views, positions, faces, source_normals, args):
    normal_data = ((source_normals, indexed_normals(positions, faces), args.normal_weight)
                   if source_normals is not None else None)
    reports = []
    for view in views:
        final_scene = SceneIndex(project(positions, view.transform), faces)
        losses = []
        maximum = 0.0
        for y in range(view.size):
            for x in range(view.size):
                points = [(x + (sx + 0.5) / view.scale, y + (sy + 0.5) / view.scale)
                          for sy in range(view.scale) for sx in range(view.scale)]
                source = [front_envelope(view.original_scene.lines(
                    tx, ty, view.direction, view.path), view.path) for tx, ty in points]
                final = [front_envelope(final_scene.lines(
                    tx, ty, view.direction, view.path), view.path) for tx, ty in points]
                loss = filtered_pixel_loss(source, final, normal_data)
                maximum = max(maximum, abs(loss - view.losses.get(y * view.size + x, 0.0)))
                losses.append(loss)
        exact, cached = math.fsum(losses), math.fsum(view.losses.values())
        if maximum > 1e-9 or abs(exact - cached) > 1e-9:
            raise ValueError(f"rebuilding the final view changed its loss: {exact} vs {cached}")
        reports.append({"rebuiltLoss": exact, "cachedLoss": cached, "maxPixelDifference": maximum})
    return reports


def run(unit, args, target_faces, rerank):
    name = "path" if rerank else "qem"
    started = time.perf_counter()
    queue = ProgressiveQEM(unit["positions"], unit["triangles"])
    queue_setup_seconds = time.perf_counter() - started
    initial_faces = queue.face_count
    if rerank:
        faces = [tuple(f) for f in unit["triangles"]]
        start_views = time.perf_counter()
        views = [View(queue.p, faces, args.angle + offset, args)
                 for offset in (0.0, 2 * math.pi / 3, -2 * math.pi / 3)]
        source_normals = indexed_normals(queue.p, faces) if args.normal_weight else None
        current_normals = source_normals.copy() if source_normals is not None else None
        view_setup_seconds = time.perf_counter() - start_views
    else:
        view_setup_seconds = 0.0
    rows = []
    while queue.face_count > target_faces:
        step_start = time.perf_counter()
        options = queue.shortlist(args.pool if rerank else 1)
        if not options:
            break
        row = {}
        if rerank:
            candidates = [proposal_for_entry(queue, entry, faces) for entry in options]
            epoch = len(rows) + 1
            choice, (projections, patches, normals, values), stats = select_path_edge(
                views, candidates, faces, queue.p, source_normals, current_normals, epoch, args)
            rank = next(i for i, candidate in enumerate(candidates) if candidate.edge == choice)
            for view, proposal, patch in zip(views, projections, patches, strict=True):
                view.apply(proposal, patch, epoch)
            for face_id, face in projections[0].faces.items():
                faces[face_id] = face
                if current_normals is not None:
                    del current_normals[face_id]
            if normals is not None:
                current_normals.update(normals[1].maps[0])
            row.update(stats, qemRank=rank + 1, perViewScore=values)
        else:
            rank = 0
        queue.accept(options[rank])
        if rerank:
            for i, f in projections[0].faces.items():
                current = tuple(queue.f[i]) if queue.alive[i] else None
                if current != f:
                    raise ValueError("scored patch differs from the accepted QEM edit")
        action = queue.actions[-1]
        row.update(edge=[action["keep"], action["remove"]], target=action["target"],
                   faces=action["faces"], options=len(options), qemMergeCost=action["qem"],
                   seconds=time.perf_counter() - step_start)
        rows.append(row)
    print(f"{name}: {initial_faces} to {queue.face_count} faces in {len(rows)} edits", flush=True)
    result = {"initialFaces": initial_faces, "finalFaces": queue.face_count, "steps": rows,
              "queueSetupSeconds": queue_setup_seconds, "viewSetupSeconds": view_setup_seconds,
              "runSeconds": time.perf_counter() - started}
    if rerank and args.audit_final_views:
        result["finalViewAudit"] = audit_final_views(views, queue.p, faces, source_normals, args)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit-index", type=int, default=0)
    parser.add_argument("--remove-fraction", type=float, default=0.05)
    parser.add_argument("--pool", type=int, default=4)
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--pan-angle", type=float, default=90.0)
    parser.add_argument("--radius", type=float, default=1.0)
    parser.add_argument("--normal-weight", type=float, default=0.25)
    parser.add_argument("--quality-size", type=int, default=80)
    parser.add_argument("--quality-scale", type=int, default=2)
    parser.add_argument("--quality-steps", type=int, default=4)
    parser.add_argument("--audit-pruning", action="store_true")
    parser.add_argument("--audit-final-views", action="store_true",
                        help="independently rebuild every pixel of the final scoring views")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    if (not 0.0 < args.remove_fraction < 1.0
            or min(args.pool, args.size, args.scale, args.quality_size, args.quality_scale,
                   args.quality_steps) < 1
            or not all(math.isfinite(v) for v in
                       (args.angle, args.pan_angle, args.radius, args.normal_weight))
            or args.radius <= 0.0 or args.normal_weight < 0.0):
        parser.error("invalid face budget, sampling, or loss settings")
    args.exhaustive = args.partial_only_bound = False
    capture = args.capture.read_bytes()
    digest = hashlib.sha256(capture).hexdigest()
    units = json.loads(capture)["units"]
    del capture
    if not 0 <= args.unit_index < len(units):
        parser.error("invalid capture unit")
    unit = units[args.unit_index]
    initial_faces = len(unit["triangles"])
    contractions = max(1, round(initial_faces * args.remove_fraction * 0.5))
    target_faces = max(initial_faces % 2, initial_faces - 2 * contractions)
    qem = run(unit, args, target_faces, False)
    path = run(unit, args, target_faces, True)
    result = {"captureSha256": digest, "unitIndex": args.unit_index, "targetFaces": target_faces,
              "pool": args.pool, "normalWeight": args.normal_weight, "auditedPruning": args.audit_pruning,
              "optimization": {"size": args.size, "scale": args.scale, "angle": args.angle,
                               "panAngle": args.pan_angle, "radius": args.radius},
              "qem": qem, "path": path}
    if not args.score_only:
        # More azimuths than the local pilot, with four midpoint times on each path.
        validation = [(f"orbit{i}", args.angle + math.radians(a), args.pan_angle + p)
                      for i, (a, p) in enumerate(
                          ((24, 37), (75, -29), (155, 15), (190, 47), (275, -43), (330, 21)), 1)]
        result["heldoutRasterQuality"] = heldout_raster_quality(
            unit, path["steps"], qem["steps"], args, views=validation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
