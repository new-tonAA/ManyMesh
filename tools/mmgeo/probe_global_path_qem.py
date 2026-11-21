#!/usr/bin/env python3
"""Compare full-unit QEM with continuous path reranking of the same legal queue."""

import argparse
from collections import ChainMap
from copy import copy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from depth_candidate_pilot import project
from probe_dynamic_path_simplification import (
    Candidate, SceneIndex, heldout_raster_quality, indexed_normals, placement_normals,
)
from probe_incremental_path_visibility import filtered_pixel_loss, front_envelope
from probe_multiview_path_simplification import View, select_path_edge
from progressive_geometry_baseline import ProgressiveQEM


def fitting_view_offsets(count):
    if count == 1:
        return (0.0,)
    if count == 2:
        return (0.0, math.pi)
    if count == 3:
        return (0.0, -2 * math.pi / 3, 2 * math.pi / 3)
    raise ValueError("fitting view count must be 1, 2, or 3")


def proposal_for_entry(queue, entry, faces, placement_rank=None):
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
    # Each view projects the proposed placement.
    return Candidate((keep, remove), target, None, patch, (), signature, placement_rank)


def audit_final_views(views, positions, faces, source_normals, args):
    normal_data = ((source_normals, indexed_normals(positions, faces), args.normal_weight)
                   if source_normals is not None else None)
    reports = []
    for view in views:
        final_scene = SceneIndex(project(positions, view.transform), faces)
        layout = view.collinear_taps if args.integrate_along_pan else None
        offsets = (layout.anchors if layout is not None else
                   [((sx + 0.5) / view.scale, (sy + 0.5) / view.scale)
                    for sy in range(view.scale) for sx in range(view.scale)])
        path = view.line_path if layout is not None else view.path
        losses = []
        maximum = 0.0
        for y in range(view.size):
            for x in range(view.size):
                points = [(x + sx, y + sy) for sx, sy in offsets]
                source = [front_envelope(view.original_scene.lines(
                    tx, ty, view.direction, path), path) for tx, ty in points]
                final = [front_envelope(final_scene.lines(
                    tx, ty, view.direction, path), path) for tx, ty in points]
                loss = (layout.loss(source, final, normal_data) if layout is not None else
                        filtered_pixel_loss(source, final, normal_data))
                maximum = max(maximum, abs(loss - view.losses.get(y * view.size + x, 0.0)))
                losses.append(loss)
        exact, cached = math.fsum(losses), math.fsum(view.losses.values())
        if maximum > 1e-9 or abs(exact - cached) > 1e-9:
            raise ValueError(f"rebuilding the final view changed its loss: {exact} vs {cached}")
        reports.append({"rebuiltLoss": exact, "cachedLoss": cached, "maxPixelDifference": maximum})
    return reports


def score_placement(views, candidate, faces, normals, epoch, args, stats,
                    limit=math.inf, reuse=True):
    projections = [view.proposal(candidate, faces) for view in views]
    outside = [view.outside_loss(proposal) for view, proposal in zip(views, projections)]
    patches, values = [], []
    for i, view in enumerate(views):
        if math.fsum((*values, *outside[i:])) > limit + 1e-12:
            return None
        cap = None
        if args.pixel_order != "off" and math.isfinite(limit):
            prefix = math.fsum((*values, *outside[i + 1:]))
            cap = math.nextafter(limit + 1e-12 - prefix, math.inf)
        value, patch, rebuilds, pixels = view.score(
            projections[i], outside[i], faces, normals, epoch, reuse, cap, args.pixel_order)
        stats["views"] += 1
        stats["frontRebuilds"] += rebuilds
        stats["pixels"] += pixels
        if patch is None:
            return None
        patches.append(patch)
        values.append(value)
    return projections, patches, values


def refine_placement(queue, faces, entry, payload, views, secondary, source_normals,
                     current_normals, epoch, args):
    projections, patches, normals, values = payload
    primary_limit = math.fsum(values)
    first = proposal_for_entry(queue, entry, faces)
    stats = {"views": 0, "frontRebuilds": 0, "pixels": 0, "eligible": 0,
             "alternatives": 0, "primaryPass": 0, "auditedPrunes": 0}
    for view in secondary:
        view.cache = {key: v for key, v in view.cache.items() if key[:2] == first.edge}
    second = score_placement(secondary, first, faces, normals, epoch, args, stats)
    secondary_limit = math.fsum(second[2])
    best = math.fsum((*values, *second[2]))
    stats["primaryReferenceLoss"] = primary_limit
    stats["secondaryReferenceLoss"] = secondary_limit if secondary else None
    result = projections + second[0], patches + second[1], normals, values + second[2]
    chosen, accepted = 0, entry
    audit_stats = dict.fromkeys(("views", "frontRebuilds", "pixels"), 0)
    for rank, placement in enumerate(queue.legal_placements(entry)):
        if rank == 0:
            continue
        stats["alternatives"] += 1
        proposal = proposal_for_entry(queue, placement, faces, rank)
        replacement_normals = None
        if current_normals is not None:
            replacement_normals = (source_normals,
                                   ChainMap(placement_normals(queue.p, proposal), current_normals),
                                   args.normal_weight)
        scored = []
        for group, limit in ((views, primary_limit), (secondary, secondary_limit)):
            score = score_placement(group, proposal, faces, replacement_normals, epoch, args,
                                    stats, limit)
            if score is None and args.audit_pruning:
                fresh = score_placement(group, proposal, faces, replacement_normals, epoch,
                                        args, audit_stats, reuse=False)
                if math.fsum(fresh[2]) < limit - 1e-12:
                    raise ValueError("pruning rejected an improving placement")
                stats["auditedPrunes"] += 1
            if score is None or (group and math.fsum(score[2]) >= limit - 1e-12):
                break
            scored.append(score)
            if group is views:
                stats["primaryPass"] += 1
        if len(scored) < 2:
            continue
        stats["eligible"] += 1
        a, b = scored
        score = math.fsum((*a[2], *b[2]))
        if score < best - 1e-12:
            best, chosen, accepted = score, rank, placement
            result = a[0] + b[0], a[1] + b[1], replacement_normals, a[2] + b[2]
    return chosen, accepted, result, stats


def run(unit, args, target_faces, rerank, compare_placements=False, refine=None):
    name = ("pathGuarded" if refine == "orthogonal" else "pathRefined" if refine else
            "pathPlacements" if compare_placements else "path" if rerank else "qem")
    started = time.perf_counter()
    started_cpu = time.process_time()
    queue = ProgressiveQEM(unit["positions"], unit["triangles"])
    queue_setup_seconds = time.perf_counter() - started
    initial_faces = queue.face_count
    if rerank:
        faces = [tuple(f) for f in unit["triangles"]]
        start_views = time.perf_counter()
        views = [View(queue.p, faces, args.angle + offset, args)
                 for offset in fitting_view_offsets(args.fit_view_count)]
        secondary = []
        if refine == "orthogonal":
            orthogonal = copy(args)
            orthogonal.pan_angle = (args.pan_angle + 90.0) % 360.0
            secondary = [View(queue.p, faces, args.angle + offset, orthogonal)
                         for offset in fitting_view_offsets(args.fit_view_count)]
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
        ranked_options = list(enumerate(options, 1))
        if rerank and args.candidate_order == "reverse-qem":
            ranked_options.reverse()
        row = {}
        if rerank:
            entries = {}
            candidates = []
            for edge_rank, entry in ranked_options:
                placements = queue.legal_placements(entry) if compare_placements else (entry,)
                for placement_rank, placement in enumerate(placements):
                    candidate = proposal_for_entry(
                        queue, placement, faces, placement_rank if compare_placements else None)
                    candidates.append(candidate)
                    entries[candidate.key] = edge_rank, placement_rank, placement
            epoch = len(rows) + 1
            choice, payload, stats = select_path_edge(
                views, candidates, faces, queue.p, source_normals, current_normals, epoch, args)
            rank, placement_rank, accepted = entries[choice]
            if refine:
                placement_rank, accepted, payload, refinement = refine_placement(
                    queue, faces, accepted, payload, views, secondary, source_normals,
                    current_normals, epoch, args)
                row.update(placementRank=placement_rank, refinement=refinement)
            projections, patches, normals, values = payload
            for view, proposal, patch in zip(views + secondary, projections, patches, strict=True):
                view.apply(proposal, patch, epoch)
            for face_id, face in projections[0].faces.items():
                faces[face_id] = face
                if current_normals is not None:
                    del current_normals[face_id]
            if normals is not None:
                current_normals.update(normals[1].maps[0])
            row.update(stats, qemRank=rank, perViewScore=values)
            if compare_placements:
                row.update(placementRank=placement_rank, placementOptions=len(candidates))
        else:
            accepted = options[0]
        queue.accept(accepted)
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
              "runSeconds": time.perf_counter() - started,
              "runCpuSeconds": time.process_time() - started_cpu}
    if rerank and args.audit_final_views:
        result["finalViewAudit"] = audit_final_views(
            views + secondary, queue.p, faces, source_normals, args)
    if rerank:
        result["perViewRayCachePeak"] = [view.ray_cache_peak for view in views + secondary]
        result["perViewAxisRowCachePeakLines"] = [
            [view.original_scene.row_cache_peak_lines, view.scene.row_cache_peak_lines]
            for view in views + secondary]
        result["perViewAxisRowCacheStats"] = [
            {"source": view.original_scene.row_cache_stats(),
             "current": view.scene.row_cache_stats()}
            for view in views + secondary]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit-index", type=int, default=0)
    parser.add_argument("--remove-fraction", type=float, default=0.05)
    parser.add_argument("--pool", type=int, default=4)
    parser.add_argument("--candidate-order",
                        choices=("qem", "reverse-qem", "first-view", "coarse-raster"),
                        default="qem",
                        help="order exact path scoring of the QEM shortlist")
    parser.add_argument("--coarse-exact-top-k", type=int, default=0,
                        help="exactly score only the best K coarse-raster candidates (0 scores all)")
    parser.add_argument("--fit-view-count", type=int, choices=(1, 2, 3), default=3,
                        help="number of evenly spaced camera paths used to rank edits")
    parser.add_argument("--axis-row-cache", action="store_true",
                        help="cache exact triangle/pan intervals per scanline with a bounded line budget")
    parser.add_argument("--compare-placements", action="store_true",
                        help="also rerank all legal QEM placements of each shortlisted edge")
    parser.add_argument("--refine-placements", choices=("primary", "orthogonal", "both"),
                        help="reconsider the winning edge's placement after path reranking")
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--share-collinear-taps", action="store_true",
                        help="share visibility envelopes along each row or column of box taps")
    parser.add_argument("--integrate-along-pan", action="store_true",
                        help="integrate a continuous box filter along the pan axis")
    parser.add_argument("--strip-width", type=int, default=1,
                        help="share each proposal's envelopes across this many adjacent pixels")
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--pan-angle", type=float, default=90.0)
    parser.add_argument("--radius", type=float, default=1.0)
    parser.add_argument("--normal-weight", type=float, default=0.25)
    parser.add_argument("--quality-size", type=int, default=80)
    parser.add_argument("--quality-scale", type=int, default=2)
    parser.add_argument("--quality-steps", type=int, default=4)
    parser.add_argument("--audit-pruning", action="store_true")
    parser.add_argument("--pixel-order", choices=("off", "scan", "loss"), default="off",
                        help="optionally prune within views in scan or descending current-loss order")
    parser.add_argument("--retain-partial", action="store_true",
                        help="retain processed pixels after a pixel-bound stop")
    parser.add_argument("--cached-view-bound", action="store_true",
                        help="include valid cached pixels in unscored view bounds")
    parser.add_argument("--reuse-face-records", action="store_true")
    parser.add_argument("--ray-cache-lines", type=int, default=0,
                        help="limit cached current-scene line records per view, zero disables it")
    parser.add_argument("--audit-final-views", action="store_true",
                        help="independently rebuild every pixel of the final scoring views")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    if (not 0.0 < args.remove_fraction < 1.0
            or min(args.pool, args.size, args.scale, args.quality_size, args.quality_scale,
                   args.quality_steps) < 1
            or not all(math.isfinite(v) for v in
                       (args.angle, args.pan_angle, args.radius, args.normal_weight))
            or args.radius <= 0.0 or args.normal_weight < 0.0 or args.ray_cache_lines < 0
            or args.coarse_exact_top_k < 0
            or (args.coarse_exact_top_k and args.candidate_order != "coarse-raster")):
        parser.error("invalid face budget, sampling, or loss settings")
    if args.retain_partial and args.pixel_order == "off":
        parser.error("retaining partial patches requires pixel pruning")
    if args.integrate_along_pan:
        args.share_collinear_taps = True
    if args.share_collinear_taps and args.pan_angle % 90.0 != 0.0:
        parser.error("tap sharing needs a multiple of 90 degree pan")
    if args.share_collinear_taps and not args.integrate_along_pan and args.scale < 2:
        parser.error("discrete tap sharing needs at least two taps per axis")
    if not 1 <= args.strip_width <= 16:
        parser.error("strip width must be between 1 and 16 pixels")
    if args.strip_width > 1 and (not args.share_collinear_taps or args.ray_cache_lines):
        parser.error("strip sharing requires collinear taps and the per-tap line cache disabled")
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
              "pool": args.pool, "fitViewCount": args.fit_view_count,
              "axisRowCache": args.axis_row_cache,
              "normalWeight": args.normal_weight, "auditedPruning": args.audit_pruning,
              "pixelOrder": args.pixel_order,
              "shareCollinearTaps": args.share_collinear_taps,
              "integrateAlongPan": args.integrate_along_pan,
              "stripWidth": args.strip_width,
              "retainPartial": args.retain_partial,
              "cachedViewBound": args.cached_view_bound,
              "reuseFaceRecords": args.reuse_face_records, "rayCacheLines": args.ray_cache_lines,
              "optimization": {"size": args.size, "scale": args.scale, "angle": args.angle,
                               "panAngle": args.pan_angle, "radius": args.radius},
              "qem": qem, "path": path}
    extra_steps = {}
    if args.compare_placements:
        placements = run(unit, args, target_faces, True, compare_placements=True)
        result["pathPlacements"] = placements
        extra_steps["pathPlacements"] = placements["steps"]
    for refine, name in (("primary", "pathRefined"), ("orthogonal", "pathGuarded")):
        if args.refine_placements in (refine, "both"):
            result[name] = run(unit, args, target_faces, True, refine=refine)
            extra_steps[name] = result[name]["steps"]
    if not args.score_only:
        # More azimuths than the local pilot, with four midpoint times on each path.
        validation = [(f"orbit{i}", args.angle + math.radians(a), args.pan_angle + p)
                      for i, (a, p) in enumerate(
                          ((24, 37), (75, -29), (155, 15), (190, 47), (275, -43), (330, 21)), 1)]
        result["heldoutRasterQuality"] = heldout_raster_quality(
            unit, path["steps"], qem["steps"], args, extra_steps=extra_steps, views=validation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
