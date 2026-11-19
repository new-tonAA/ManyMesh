#!/usr/bin/env python3
"""Batch replay of nearby legal collapses using one cached common depth envelope.

All candidates use the same small filter-sample tile and orthographic translation path. The
reference rebuilds each post-collapse full-mesh line set. The cached method builds the unchanged
mesh envelope once and overlays only each candidate's edited triangles. This is a CPU research
probe, not a full image or local-redraw comparison.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from probe_real_collapse_depth_events import (
    DEFAULT_CAPTURE,
    FILTER_OFFSETS,
    FILTER_WEIGHTS,
    camera_coordinates,
    camera_frame,
    exact_envelope_overlay,
    exact_integral,
    mesh_lines,
    mesh_lines_for_ids,
    upper_envelope,
)


def choose_local_candidates(candidates, triangles, seed_candidate, limit):
    seed = candidates[seed_candidate]
    seed_vertices = {int(seed["remove"]), int(seed["keep"])}
    ring = set(seed_vertices)
    for face in triangles:
        if any(int(vertex) in seed_vertices for vertex in face):
            ring.update(map(int, face))
    ids = [seed_candidate]
    ids.extend(i for i, candidate in enumerate(candidates)
               if i != seed_candidate and int(candidate["remove"]) in ring and
               int(candidate["keep"]) in ring)
    return ids[:limit]


def candidate_geometry(positions, triangles, candidate):
    remove, keep = int(candidate["remove"]), int(candidate["keep"])
    post_positions = [point[:] for point in positions]
    post_positions[keep] = list(map(float, candidate["target"]))
    faces_by_id = []
    valid_faces = []
    local = []
    for face_id, face in enumerate(triangles):
        if remove in face or keep in face:
            local.append(face_id)
        changed = [keep if vertex == remove else vertex for vertex in face]
        if len(set(changed)) < 3:
            faces_by_id.append(None)
        else:
            faces_by_id.append(changed)
            valid_faces.append(changed)
    return post_positions, faces_by_id, valid_faces, local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--seed-candidate", type=int, default=5852)
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--angle", type=float, default=2.3)
    parser.add_argument("--out", type=Path,
                        default=Path("out/shared-depth-envelope-batch-20261119.json"))
    args = parser.parse_args()

    data = json.loads(args.capture.read_text(encoding="utf-8"))
    unit = data["units"][0]
    raw_positions = unit["positions"]
    triangles = [list(map(int, face)) for face in unit["triangles"]]
    candidates = unit["candidates"]
    candidate_ids = choose_local_candidates(candidates, triangles,
                                            args.seed_candidate, args.candidate_limit)

    frame = camera_frame(raw_positions, args.angle)
    positions = camera_coordinates(raw_positions, frame).tolist()
    batch_local_faces = set()
    batch_vertices = set()
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        _post, _faces, _valid, local = candidate_geometry(
            positions, triangles, candidate)
        batch_local_faces.update(local)
        batch_vertices.update(map(int, (candidate["remove"], candidate["keep"])))
    for face_id in tuple(batch_local_faces):
        batch_vertices.update(triangles[face_id])

    xs = [positions[v][0] for v in batch_vertices]
    ys = [positions[v][1] for v in batch_vertices]
    sample_center_x = 0.5 * (min(xs) + max(xs))
    sample_y = 0.5 * (min(ys) + max(ys))
    radius = max(0.02, 0.75 * (max(xs) - min(xs)))
    path = (-radius, radius)
    common_face_ids = [face_id for face_id in range(len(triangles))
                       if face_id not in batch_local_faces]

    # Shared source setup: also supplies the source side of the full-mesh reference.
    sample_sources = []
    common_envelopes = []
    source_line_seconds = 0.0
    common_envelope_seconds = 0.0
    for offset in FILTER_OFFSETS:
        sample_x = sample_center_x + offset
        line_started = time.perf_counter()
        source_lines = mesh_lines(positions, triangles, sample_y, sample_x, path)
        source_line_seconds += time.perf_counter() - line_started
        source_by_face = {line["face"]: line for line in source_lines}
        common_lines = [source_by_face[i] for i in common_face_ids if i in source_by_face]
        union_source_lines = [source_by_face[i] for i in batch_local_faces if i in source_by_face]
        sample_sources.append((sample_x, source_lines, source_by_face, union_source_lines))
        env_start = time.perf_counter()
        envelope, envelope_events, depth_event_count = upper_envelope(common_lines, path)
        common_envelope_seconds += time.perf_counter() - env_start
        common_envelopes.append((envelope, len(envelope_events), depth_event_count))
    source_setup_seconds = source_line_seconds

    rows = []
    naive_candidate_visits = 0
    cached_candidate_visits = 0
    naive_candidate_seconds = 0.0
    cached_candidate_seconds = 0.0
    for candidate_id in candidate_ids:
        candidate = dict(candidates[candidate_id])
        candidate["target"] = camera_coordinates([candidate["target"]], frame)[0].tolist()
        post_positions, faces_by_id, valid_faces, local_faces = candidate_geometry(
            positions, triangles, candidate)
        local_set = set(local_faces)
        unchanged_union_ids = batch_local_faces - local_set
        naive_sample_lines = []
        cached_sample_lines = []
        full_lines_seconds = 0.0
        local_lines_seconds = 0.0
        for sample_index, (sample_x, source_lines, source_by_face,
                           union_source_lines) in enumerate(sample_sources):
            weight = FILTER_WEIGHTS[sample_index]
            t0 = time.perf_counter()
            candidate_full_lines = mesh_lines(post_positions, valid_faces,
                                              sample_y, sample_x, path)
            full_lines_seconds += time.perf_counter() - t0
            naive_sample_lines.append((source_lines, candidate_full_lines, weight))

            t1 = time.perf_counter()
            unchanged_union_lines = [source_by_face[i] for i in unchanged_union_ids
                                     if i in source_by_face]
            candidate_local_lines = mesh_lines_for_ids(
                post_positions, faces_by_id, local_faces, sample_y, sample_x, path)
            local_lines_seconds += time.perf_counter() - t1
            common_envelope = common_envelopes[sample_index][0]
            cached_sample_lines.append((
                common_envelope,
                union_source_lines,
                unchanged_union_lines + candidate_local_lines,
                weight))

        full_solve_start = time.perf_counter()
        full_energy, full_events, full_depth_events = exact_integral(
            naive_sample_lines, path, True)
        full_solve_seconds = time.perf_counter() - full_solve_start
        cache_solve_start = time.perf_counter()
        cached_energy, cached_events, cached_depth_events = exact_envelope_overlay(
            cached_sample_lines, path)
        cached_solve_seconds = time.perf_counter() - cache_solve_start

        naive_candidate_seconds += full_lines_seconds + full_solve_seconds
        cached_candidate_seconds += local_lines_seconds + cached_solve_seconds
        naive_candidate_visits += len(valid_faces) * len(FILTER_OFFSETS)
        cached_candidate_visits += len(local_faces) * len(FILTER_OFFSETS)
        rows.append({
            "candidateId": candidate_id,
            "remove": int(candidate["remove"]),
            "keep": int(candidate["keep"]),
            "localFaceCount": len(local_faces),
            "fullEnergy": full_energy,
            "cachedEnergy": cached_energy,
            "relativeDifference": abs(full_energy - cached_energy) /
                                 max(abs(full_energy), 1e-12),
            "fullEventCount": len(full_events),
            "cachedEventCount": cached_events,
            "fullDepthEvents": full_depth_events,
            "cachedDepthEvents": cached_depth_events,
            "fullCandidateLineSetupSeconds": full_lines_seconds,
            "cachedLocalLineSetupSeconds": local_lines_seconds,
            "fullEventSolveSeconds": full_solve_seconds,
            "cachedOverlaySolveSeconds": cached_solve_seconds,
        })

    baseline_seconds = source_setup_seconds + naive_candidate_seconds
    shared_seconds = source_setup_seconds + common_envelope_seconds + cached_candidate_seconds
    output = {
        "scope": "fixed local filter tile; legal Monkey one-ring candidates; orthographic x-translation",
        "warning": "this compares full-mesh event-line reconstruction against common-envelope "
                   "reuse only; it is not a full-image, local-redraw, or renderer benchmark",
        "captureSha256": __import__("hashlib").sha256(args.capture.read_bytes()).hexdigest(),
        "seedCandidate": args.seed_candidate,
        "cameraAngle": args.angle,
        "candidateIds": candidate_ids,
        "candidateCount": len(candidate_ids),
        "sourceTriangles": len(triangles),
        "batchLocalFaceUnion": len(batch_local_faces),
        "commonFaceCount": len(common_face_ids),
        "filterSampleCount": len(FILTER_OFFSETS),
        "sampleCenter": [sample_center_x, sample_y],
        "path": path,
        "commonSourceSetupSeconds": source_setup_seconds,
        "commonEnvelopeBuildSeconds": common_envelope_seconds,
        "fullCandidateLineVisits": naive_candidate_visits,
        "cachedCandidateLocalLineVisits": cached_candidate_visits,
        "fullCandidateSeconds": naive_candidate_seconds,
        "cachedCandidateSeconds": cached_candidate_seconds,
        "baselineTotalSeconds": baseline_seconds,
        "sharedEnvelopeTotalSeconds": shared_seconds,
        "sharedEnvelopeTotalSpeedup": baseline_seconds / max(shared_seconds, 1e-12),
        "candidateResults": rows,
        "maxRelativeEnergyDifference": max(row["relativeDifference"] for row in rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in (
        "candidateCount", "candidateIds", "batchLocalFaceUnion", "commonFaceCount",
        "fullCandidateLineVisits", "cachedCandidateLocalLineVisits",
        "baselineTotalSeconds", "sharedEnvelopeTotalSeconds", "sharedEnvelopeTotalSpeedup",
        "maxRelativeEnergyDifference")}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
