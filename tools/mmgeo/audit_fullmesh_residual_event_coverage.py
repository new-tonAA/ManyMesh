#!/usr/bin/env python3
"""Audit candidate-local coverage events against all mesh edges in its sample support."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load_module(name, filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def triangle_inside_samples(pilot, camera_positions, positions, triangles, valid,
                            angle, samples, size):
    projected = pilot.project(positions, pilot.camera(camera_positions, angle, size))
    face = projected[triangles][:, :, :2]
    a = face[:, 0]
    ab = face[:, 1] - a
    ac = face[:, 2] - a
    det = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    safe = np.abs(det) > 1e-14
    denom = np.where(safe, det, 1.0)
    output = np.zeros((len(samples), len(triangles)), dtype=bool)
    for lo in range(0, len(samples), 16):
        hi = min(len(samples), lo + 16)
        q = samples[None, lo:hi, :] - a[:, None, :]
        u = (q[:, :, 0] * ac[:, None, 1] - q[:, :, 1] * ac[:, None, 0]) / denom[:, None]
        v = (ab[:, None, 0] * q[:, :, 1] - ab[:, None, 1] * q[:, :, 0]) / denom[:, None]
        inside = (safe[:, None] & valid[:, None] & (u >= -1e-10) & (v >= -1e-10) &
                  (u + v <= 1 + 1e-10))
        output[lo:hi] = inside.T
    return output


def triangle_inside_ids(pilot, camera_positions, positions, triangles, face_ids,
                        angle, sample, size):
    if not len(face_ids):
        return np.empty(0, dtype=bool)
    faces = triangles[face_ids]
    vertices, inverse = np.unique(faces.reshape(-1), return_inverse=True)
    transform = pilot.camera(camera_positions, angle, size)
    projected = pilot.project(positions[vertices], transform)
    face = projected[inverse.reshape(-1, 3), :2]
    a = face[:, 0]
    ab = face[:, 1] - a
    ac = face[:, 2] - a
    q = np.asarray(sample, dtype=np.float64)[None, :] - a
    det = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    safe = np.abs(det) > 1e-14
    denom = np.where(safe, det, 1.0)
    u = (q[:, 0] * ac[:, 1] - q[:, 1] * ac[:, 0]) / denom
    v = (ab[:, 0] * q[:, 1] - ab[:, 1] * q[:, 0]) / denom
    return safe & (u >= -1e-10) & (v >= -1e-10) & (u + v <= 1 + 1e-10)


def edge_geometry_key(a, b):
    pa = tuple(np.asarray(a, dtype=np.float64))
    pb = tuple(np.asarray(b, dtype=np.float64))
    return (pa, pb) if pa <= pb else (pb, pa)


def mesh_edge_incidence(positions, triangles, valid):
    edges = {}
    for face_id in np.flatnonzero(valid):
        face = triangles[face_id]
        for i in range(3):
            a = positions[int(face[i])]
            b = positions[int(face[(i + 1) % 3])]
            edges.setdefault(edge_geometry_key(a, b), set()).add(int(face_id))
    return edges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("local_events", type=Path)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pilot = load_module("fullmesh_event_pilot", "depth_candidate_pilot.py")
    edge_probe = load_module("fullmesh_edge_probe", "probe_batched_edge_event_roots.py")
    positions, triangles, candidates = pilot.load_capture(args.capture)
    local_report = json.loads(args.local_events.read_text(encoding="utf-8"))
    camera = local_report["camera"]
    size, scale = int(camera["size"]), int(camera["scale"])
    start, end = float(camera["start"]), float(camera["end"])
    candidate = candidates[args.candidate_id]
    local_row = next(row for row in local_report["assets"]
                     if row["candidateId"] == args.candidate_id)
    sample_coordinates = np.asarray(local_row.get(
        "supportSampleCoordinates", local_row["sampleCoordinates"]), dtype=np.int64)
    if not len(sample_coordinates):
        parser.error("local event report has no candidate support samples")

    post_positions = positions.copy()
    post_positions[candidate["keep"]] = np.asarray(candidate["target"], dtype=np.float64)
    post_triangles = triangles.copy()
    post_triangles[post_triangles == candidate["remove"]] = candidate["keep"]
    source_valid = np.ones(len(triangles), dtype=bool)
    post_valid = ((post_triangles[:, 0] != post_triangles[:, 1]) &
                  (post_triangles[:, 1] != post_triangles[:, 2]) &
                  (post_triangles[:, 2] != post_triangles[:, 0]))

    source_incidence = mesh_edge_incidence(positions, triangles, source_valid)
    post_incidence = mesh_edge_incidence(post_positions, post_triangles, post_valid)
    edge_incidence = {}
    for key, face_ids in source_incidence.items():
        edge_incidence.setdefault(key, [set(), set()])[0].update(face_ids)
    for key, face_ids in post_incidence.items():
        edge_incidence.setdefault(key, [set(), set()])[1].update(face_ids)
    edge_keys = sorted(edge_incidence)
    source_faces_by_edge = [edge_incidence[key][0] for key in edge_keys]
    post_faces_by_edge = [edge_incidence[key][1] for key in edge_keys]
    events_by_sample_angle = {}
    started = time.perf_counter()

    root_started = time.perf_counter()
    batch_events = edge_probe.edge_event_pairs(
        pilot, positions, edge_keys, sample_coordinates, start, end, size, scale)
    root_seconds = time.perf_counter() - root_started
    for edge_id, angle, sx, sy in batch_events:
        event_key = (sx, sy, round(float(angle), 10))
        state = events_by_sample_angle.setdefault(event_key, [set(), set()])
        state[0].update(source_faces_by_edge[edge_id])
        state[1].update(post_faces_by_edge[edge_id])

    global_toggles = set()
    ambiguous = 0
    event_count = 0
    state_disagreements = 0
    sample_xy = np.column_stack(((sample_coordinates[:, 0] + 0.5) / scale,
                                 (sample_coordinates[:, 1] + 0.5) / scale))
    sweep_started = time.perf_counter()
    source_states = triangle_inside_samples(
        pilot, positions, positions, triangles, source_valid, start + 1e-7,
        sample_xy, size)
    post_states = triangle_inside_samples(
        pilot, positions, post_positions, post_triangles, post_valid, start + 1e-7,
        sample_xy, size)
    source_counts = source_states.sum(axis=1).astype(np.int64)
    post_counts = post_states.sum(axis=1).astype(np.int64)
    sample_ids_by_coord = {tuple(map(int, xy)): i
                           for i, xy in enumerate(sample_coordinates)}
    events_by_sample = {}
    for (sx, sy, angle), faces in events_by_sample_angle.items():
        events_by_sample.setdefault((sx, sy), []).append((angle, faces))
    for (sx, sy), sample_events in events_by_sample.items():
        sample_events.sort(key=lambda row: row[0])
        sample_id = sample_ids_by_coord[(sx, sy)]
        sample = sample_xy[sample_id]
        ordered = [row[0] for row in sample_events]
        for i, (angle, face_sets) in enumerate(sample_events):
            left_gap = angle - (ordered[i - 1] if i else start)
            right_gap = (ordered[i + 1] if i + 1 < len(ordered) else end) - angle
            epsilon = min(1e-6, 0.2 * left_gap, 0.2 * right_gap)
            if epsilon < 1e-9:
                ambiguous += 1
                continue
            event_count += 1
            before_angle, after_angle = angle - epsilon, angle + epsilon
            source_ids = np.asarray(sorted(face_sets[0]), dtype=np.int64)
            post_ids = np.asarray(sorted(face_sets[1]), dtype=np.int64)
            current_source = source_states[sample_id, source_ids]
            current_post = post_states[sample_id, post_ids]
            source_before = triangle_inside_ids(
                pilot, positions, positions, triangles, source_ids, before_angle,
                sample, size)
            post_before = triangle_inside_ids(
                pilot, positions, post_positions, post_triangles, post_ids,
                before_angle, sample, size)
            state_disagreements += int(np.count_nonzero(current_source != source_before))
            state_disagreements += int(np.count_nonzero(current_post != post_before))
            source_before_covered = source_counts[sample_id] > 0
            post_before_covered = post_counts[sample_id] > 0
            source_after = triangle_inside_ids(
                pilot, positions, positions, triangles, source_ids, after_angle,
                sample, size)
            post_after = triangle_inside_ids(
                pilot, positions, post_positions, post_triangles, post_ids,
                after_angle, sample, size)
            source_counts[sample_id] += int(source_after.sum()) - int(current_source.sum())
            post_counts[sample_id] += int(post_after.sum()) - int(current_post.sum())
            source_states[sample_id, source_ids] = source_after
            post_states[sample_id, post_ids] = post_after
            source_after_covered = source_counts[sample_id] > 0
            post_after_covered = post_counts[sample_id] > 0
            if (source_before_covered != post_before_covered and
                    source_after_covered == post_after_covered):
                global_toggles.add((round(angle, 10), sx, sy))
            elif (source_before_covered == post_before_covered and
                  source_after_covered != post_after_covered):
                global_toggles.add((round(angle, 10), sx, sy))

    end_source_states = triangle_inside_samples(
        pilot, positions, positions, triangles, source_valid, end - 1e-7,
        sample_xy, size)
    end_post_states = triangle_inside_samples(
        pilot, positions, post_positions, post_triangles, post_valid, end - 1e-7,
        sample_xy, size)
    endpoint_state_disagreements = int(np.count_nonzero(source_states != end_source_states))
    endpoint_state_disagreements += int(np.count_nonzero(post_states != end_post_states))
    sweep_seconds = time.perf_counter() - sweep_started

    local_toggles = {(round(float(row["angle"]), 10), int(row["sampleX"]),
                      int(row["sampleY"]))
                     for row in local_row["residualTransitions"]}
    match_tolerance = 1e-7
    local_by_sample = {}
    global_by_sample = {}
    for angle, sx, sy in local_toggles:
        local_by_sample.setdefault((sx, sy), []).append(angle)
    for angle, sx, sy in global_toggles:
        global_by_sample.setdefault((sx, sy), []).append(angle)
    unmatched_global = 0
    unmatched_local = 0
    max_matched_time_error = 0.0
    unmatched_examples = []
    for sample in sorted(set(local_by_sample) | set(global_by_sample)):
        local_angles = sorted(local_by_sample.get(sample, []))
        global_angles = sorted(global_by_sample.get(sample, []))
        common = min(len(local_angles), len(global_angles))
        for i in range(common):
            delta = abs(local_angles[i] - global_angles[i])
            max_matched_time_error = max(max_matched_time_error, delta)
            if delta > match_tolerance:
                unmatched_local += 1
                unmatched_global += 1
                if len(unmatched_examples) < 32:
                    unmatched_examples.append({
                        "sampleX": sample[0], "sampleY": sample[1],
                        "localAngle": local_angles[i], "globalAngle": global_angles[i],
                        "absoluteAngleError": delta,
                    })
        for angle in local_angles[common:]:
            unmatched_local += 1
            if len(unmatched_examples) < 32:
                unmatched_examples.append({"sampleX": sample[0], "sampleY": sample[1],
                                           "localOnlyAngle": angle})
        for angle in global_angles[common:]:
            unmatched_global += 1
            if len(unmatched_examples) < 32:
                unmatched_examples.append({"sampleX": sample[0], "sampleY": sample[1],
                                           "globalOnlyAngle": angle})
    output = {
        "scope": "all source and collapsed mesh edge events restricted to candidate-local swept sample support",
        "limitations": [
            "sample support is the union of initial local coverage mismatches and candidate-local edge crossing samples",
            "continuous completeness depends on the analytic edge root solver and finite-precision grouping",
            "coverage only; depth-order and filtered-loss runtime are not audited",
        ],
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "localEventReportSha256": hashlib.sha256(args.local_events.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidateId": args.candidate_id,
        "camera": camera,
        "meshEdgeGeometryCount": len(edge_keys),
        "candidateSupportSampleCount": int(len(sample_coordinates)),
        "samplesWithGlobalEdgeEvents": len(events_by_sample),
        "globalUniqueSampleEventsTested": event_count,
        "rawBatchedEdgeSampleEvents": len(batch_events),
        "rootGenerationSeconds": root_seconds,
        "ambiguousNearCoincidentGlobalEvents": ambiguous,
        "incrementalStateDisagreements": state_disagreements,
        "endpointStateDisagreements": endpoint_state_disagreements,
        "incrementalSweepSeconds": sweep_seconds,
        "localResidualTransitions": len(local_toggles),
        "globalResidualTransitions": len(global_toggles),
        "angleMatchTolerance": match_tolerance,
        "maxMatchedAngleDifference": max_matched_time_error,
        "unmatchedGlobalTransitions": unmatched_global,
        "unmatchedLocalTransitions": unmatched_local,
        "unmatchedTransitionExamples": unmatched_examples,
        "wallSeconds": time.perf_counter() - started,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"edges={len(edge_keys)} supportSamples={len(sample_coordinates)} "
          f"rawEvents={len(batch_events)} globalEvents={event_count} "
          f"rootSeconds={root_seconds:.2f} sweepSeconds={sweep_seconds:.2f} "
          f"localToggles={len(local_toggles)} globalToggles={len(global_toggles)} "
          f"stateErrors={state_disagreements + endpoint_state_disagreements} unmatched="
          f"{unmatched_global}/{unmatched_local} "
          f"seconds={output['wallSeconds']:.2f}; wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
