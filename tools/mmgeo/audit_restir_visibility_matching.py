#!/usr/bin/env python3
"""CPU self-visibility response screen for overlapping-UV ReSTIR-LoD matching.

The experiment compares the paper's nearest-world-space one-to-one assignment with a greedy
assignment minimizing a sampled diffuse directional-response signature. Each signature includes
cosine response and binary self-visibility against the corresponding LOD mesh. This is a direct-
illumination proxy, not a full path tracer, ReSTIR estimator, or novelty claim.
"""

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import random
from pathlib import Path

import numpy as np


def load_local(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uv = load_local("measure_lod_uv_transport")
vqb = load_local("visibility_query_bvh")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directions_fibonacci(count):
    golden = math.pi * (3.0 - math.sqrt(5.0))
    directions = []
    for i in range(count):
        z = 1.0 - 2.0 * (i + 0.5) / count
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        phi = golden * i
        directions.append((radius * math.cos(phi), radius * math.sin(phi), z))
    return directions


def greedy_pairs(source_matches, target_matches, cost):
    remaining_source = set(range(len(source_matches)))
    remaining_target = set(range(len(target_matches)))
    pairs = []
    while remaining_source and remaining_target:
        value, i, j = min((cost(i, j), i, j)
                          for i in remaining_source for j in remaining_target)
        pairs.append((i, j))
        remaining_source.remove(i)
        remaining_target.remove(j)
    return pairs


def make_bvh(mesh):
    positions = np.asarray([face["p"] for face in mesh["faces"]], dtype=np.float64).reshape(-1, 3)
    indices = np.arange(len(positions), dtype=np.int32).reshape(-1, 3)
    return vqb.BVH.mesh(positions, indices)


def response_signature(point, normal, bvh, directions, epsilon, max_distance):
    origin = tuple(point[axis] + normal[axis] * epsilon for axis in range(3))
    values = []
    counters = [0, 0, 0]
    for direction in directions:
        cosine = max(0.0, uv.dot3(normal, direction))
        if cosine <= 0.0:
            values.append(0.0)
            continue
        ray = vqb.Ray(origin, direction, max_distance)
        values.append(0.0 if bvh.query(ray, counters) else cosine)
    return values, counters


def rms(first, second):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)) / len(first))


def measure(source_path, target_path, sample_count, seed, grid_resolution, direction_count):
    source, target = uv.prepare(source_path), uv.prepare(target_path)
    for mesh in (source, target):
        for face_id, face in enumerate(mesh["faces"]):
            face["face_id"] = face_id
    uv.build_uv_bins(source, grid_resolution)
    uv.build_uv_bins(target, grid_resolution)
    source_bvh, target_bvh = make_bvh(source), make_bvh(target)
    directions = directions_fibonacci(direction_count)
    source_faces = source["faces"]
    cumulative, total_area = [], 0.0
    for face in source_faces:
        total_area += face["uv_area"]
        cumulative.append(total_area)
    all_points = [p for mesh in (source, target) for face in mesh["faces"] for p in face["p"]]
    bounds_min = [min(p[a] for p in all_points) for a in range(3)]
    bounds_max = [max(p[a] for p in all_points) for a in range(3)]
    diagonal = max(uv.length3(tuple(bounds_max[a] - bounds_min[a] for a in range(3))), 1e-20)
    epsilon, max_distance = diagonal * 1e-5, diagonal * 4.0
    rng = random.Random(seed)
    changed, ambiguous, mapped = 0, 0, 0
    baseline_errors, visibility_errors = [], []
    baseline_displacements, visibility_displacements = [], []
    baseline_normal_angles, visibility_normal_angles = [], []
    changed_examples = []
    ray_counters = [0, 0, 0]

    for sample_id in range(sample_count):
        face_index = min(bisect.bisect_left(cumulative, rng.random() * total_area),
                         len(source_faces) - 1)
        sampled_face = source_faces[face_index]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1.0:
            r1, r2 = 1.0 - r1, 1.0 - r2
        bary = (1.0 - r1 - r2, r1, r2)
        uv_point = uv.add_weighted(sampled_face["uv"], bary)
        sampled_point = uv.add_weighted(sampled_face["p"], bary)
        source_matches = uv.surface_matches(source, uv_point, sampled_point)
        target_matches = uv.surface_matches(target, uv_point, sampled_point)
        if not source_matches or not target_matches:
            continue
        if len(source_matches) > 1 or len(target_matches) > 1:
            ambiguous += 1
        source_index = next((i for i, item in enumerate(source_matches)
                             if item[1] is sampled_face), None)
        if source_index is None:
            continue

        source_signatures = []
        target_signatures = []
        for _, face, point in source_matches:
            signature, counts = response_signature(point, face["normal"], source_bvh, directions,
                                                   epsilon, max_distance)
            source_signatures.append(signature)
            ray_counters = [a + b for a, b in zip(ray_counters, counts)]
        for _, face, point in target_matches:
            signature, counts = response_signature(point, face["normal"], target_bvh, directions,
                                                   epsilon, max_distance)
            target_signatures.append(signature)
            ray_counters = [a + b for a, b in zip(ray_counters, counts)]

        nearest = greedy_pairs(source_matches, target_matches,
                               lambda i, j: sum((source_matches[i][2][a] -
                                                target_matches[j][2][a]) ** 2 for a in range(3)))
        transport = greedy_pairs(source_matches, target_matches,
                                 lambda i, j: rms(source_signatures[i], target_signatures[j]))
        nearest_target = next((j for i, j in nearest if i == source_index), None)
        transport_target = next((j for i, j in transport if i == source_index), None)
        if nearest_target is None or transport_target is None:
            continue
        mapped += 1
        for pairs, errors, displacements, angles in (
                (nearest, baseline_errors, baseline_displacements, baseline_normal_angles),
                (transport, visibility_errors, visibility_displacements, visibility_normal_angles)):
            target_index = next(j for i, j in pairs if i == source_index)
            _, source_face, source_point = source_matches[source_index]
            _, target_face, target_point = target_matches[target_index]
            errors.append(rms(source_signatures[source_index], target_signatures[target_index]))
            displacements.append(uv.length3(uv.sub3(source_point, target_point)) / diagonal)
            cosine = max(-1.0, min(1.0, uv.dot3(source_face["normal"], target_face["normal"])))
            angles.append(math.degrees(math.acos(cosine)))
        if nearest_target != transport_target:
            changed += 1
            changed_examples.append({
                "sample": sample_id,
                "uv": list(uv_point),
                "source_face": face_index,
                "nearest_target_face": target_matches[nearest_target][1].get("face_id"),
                "transport_target_face": target_matches[transport_target][1].get("face_id"),
                "nearest_signature_rms": baseline_errors[-1],
                "transport_signature_rms": visibility_errors[-1],
                "nearest_displacement_over_bounds": baseline_displacements[-1],
                "transport_displacement_over_bounds": visibility_displacements[-1]})

    def stats(values):
        array = np.asarray(values, dtype=np.float64)
        return {"mean": float(array.mean()) if len(array) else None,
                "median": float(np.quantile(array, .5)) if len(array) else None,
                "p95": float(np.quantile(array, .95)) if len(array) else None,
                "p99": float(np.quantile(array, .99)) if len(array) else None,
                "max": float(array.max()) if len(array) else None}

    return {
        "source": str(source_path), "target": str(target_path), "samples_requested": sample_count,
        "samples_mapped": mapped, "seed": seed, "grid_resolution": grid_resolution,
        "direction_count": direction_count, "uv_ambiguous_samples": ambiguous,
        "uv_ambiguous_fraction_of_requested": ambiguous / sample_count if sample_count else 0.0,
        "changed_assignments": changed,
        "changed_fraction_of_mapped": changed / mapped if mapped else None,
        "nearest_world": {"visibility_signature_rms": stats(baseline_errors),
                          "displacement_over_bounds": stats(baseline_displacements),
                          "normal_angle_degrees": stats(baseline_normal_angles)},
        "visibility_signature": {"visibility_signature_rms": stats(visibility_errors),
                                 "displacement_over_bounds": stats(visibility_displacements),
                                 "normal_angle_degrees": stats(visibility_normal_angles)},
        "changed_examples": changed_examples[:32],
        "query_counters": {"aabb": ray_counters[0], "triangles": ray_counters[1],
                           "cones": ray_counters[2]},
        "scope": "uniform source UV-area samples; diffuse cosine times binary self-visibility to a uniform directional environment; no textures, direct external occluders, glossy BSDF, multi-bounce paths, ReSTIR reservoirs, estimator variance, or runtime cost"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--directions", type=int, default=32)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if min(args.samples, args.grid_resolution, args.directions) <= 0:
        parser.error("samples, grid resolution, and directions must be positive")
    report = measure(args.source, args.target, args.samples, args.seed,
                     args.grid_resolution, args.directions)
    report.update({"schema": 1, "source_sha256": sha256(args.source),
                   "target_sha256": sha256(args.target), "script_sha256": sha256(Path(__file__))})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
