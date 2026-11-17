#!/usr/bin/env python3
"""Compare nearest-point and transport-signature UV-overlap matching.

This is an offline geometric preflight for the branch-matching step used by ReSTIR-LoD. The
signature is Lambertian cosine response over a fixed uniform sphere; it has no scene visibility,
materials, path weights, reservoirs, or estimator variance. It is not a ReSTIR result or novelty
claim.
"""

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import random
from pathlib import Path

_UV_PATH = Path(__file__).with_name("measure_lod_uv_transport.py")
_UV_SPEC = importlib.util.spec_from_file_location("measure_lod_uv_transport", _UV_PATH)
uv = importlib.util.module_from_spec(_UV_SPEC)
_UV_SPEC.loader.exec_module(uv)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fibonacci_directions(count):
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for i in range(count):
        z = 1.0 - 2.0 * (i + 0.5) / count
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        phi = golden * i
        out.append((radius * math.cos(phi), radius * math.sin(phi), z))
    return out


def response_signature(normal, directions):
    return [max(0.0, uv.dot3(normal, direction)) for direction in directions]


def signature_distance(first, second):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)) / len(first))


def greedy_pairs(source_matches, target_matches, cost):
    remaining_source = set(range(len(source_matches)))
    remaining_target = set(range(len(target_matches)))
    pairs = []
    while remaining_source and remaining_target:
        best = min((cost(i, j), i, j) for i in remaining_source for j in remaining_target)
        _, i, j = best
        pairs.append((i, j))
        remaining_source.remove(i)
        remaining_target.remove(j)
    return pairs


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    at = q * (len(values) - 1)
    lo = int(at)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] * (1.0 - (at - lo)) + values[hi] * (at - lo)


def empty_metrics():
    return {"mapped_samples": 0, "ambiguous_samples": 0, "signature_rms": [],
            "position_over_bounds": [], "normal_angle_degrees": [], "abs_log2_jacobian": []}


def add_mapping(metrics, source_face, target_face, source_point, target_point, signature_cost,
                bounds_diagonal):
    metrics["mapped_samples"] += 1
    metrics["signature_rms"].append(signature_cost)
    metrics["position_over_bounds"].append(
        uv.length3(uv.sub3(source_point, target_point)) / bounds_diagonal)
    cosine = max(-1.0, min(1.0, uv.dot3(source_face["normal"], target_face["normal"])))
    metrics["normal_angle_degrees"].append(math.degrees(math.acos(cosine)))
    j = ((target_face["geom_area"] / target_face["uv_area"])
         / (source_face["geom_area"] / source_face["uv_area"]))
    metrics["abs_log2_jacobian"].append(abs(math.log2(j)))


def summarize(metrics, ambiguous_samples, sample_count):
    result = {"samples": sample_count, "mapped_samples": metrics["mapped_samples"],
              "map_rate": metrics["mapped_samples"] / sample_count if sample_count else 0.0,
              "ambiguous_uv_samples": ambiguous_samples,
              "ambiguous_uv_fraction": ambiguous_samples / sample_count if sample_count else 0.0}
    for key in ("signature_rms", "position_over_bounds", "normal_angle_degrees", "abs_log2_jacobian"):
        values = metrics[key]
        result[key] = {"mean": sum(values) / len(values) if values else None,
                       "median": quantile(values, 0.5), "p95": quantile(values, 0.95),
                       "p99": quantile(values, 0.99), "max": max(values) if values else None}
    return result


def measure(source, target, samples, seed, grid_resolution, direction_count):
    uv.build_uv_bins(source, grid_resolution)
    uv.build_uv_bins(target, grid_resolution)
    rng = random.Random(seed)
    directions = fibonacci_directions(direction_count)
    for mesh in (source, target):
        for face in mesh["faces"]:
            face["signature"] = response_signature(face["normal"], directions)

    source_faces = source["faces"]
    cumulative, total_uv_area = [], 0.0
    for face in source_faces:
        total_uv_area += face["uv_area"]
        cumulative.append(total_uv_area)
    bbox_min = [min(p[a] for face in source_faces for p in face["p"]) for a in range(3)]
    bbox_max = [max(p[a] for face in source_faces for p in face["p"]) for a in range(3)]
    bounds_diagonal = max(uv.length3(tuple(bbox_max[a] - bbox_min[a] for a in range(3))), 1e-20)

    modes = {"nearest_world": empty_metrics(), "lambertian_signature": empty_metrics()}
    ambiguous_samples = 0
    changed_pair_samples = 0
    changed_ambiguous_pair_samples = 0
    for _ in range(samples):
        face_index = min(bisect.bisect_left(cumulative, rng.random() * total_uv_area),
                         len(source_faces) - 1)
        source_face = source_faces[face_index]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1.0:
            r1, r2 = 1.0 - r1, 1.0 - r2
        bary = (1.0 - r1 - r2, r1, r2)
        uv_point = uv.add_weighted(source_face["uv"], bary)
        source_point = uv.add_weighted(source_face["p"], bary)
        source_matches = uv.surface_matches(source, uv_point, source_point)
        target_matches = uv.surface_matches(target, uv_point, source_point)
        if len(source_matches) > 1 or len(target_matches) > 1:
            ambiguous_samples += 1
        if not source_matches or not target_matches:
            continue

        source_index = next((i for i, item in enumerate(source_matches)
                             if item[1] is source_face), None)
        if source_index is None:
            continue
        nearest_pairs = greedy_pairs(source_matches, target_matches,
                                     lambda i, j: sum((source_matches[i][2][a] - target_matches[j][2][a]) ** 2
                                         for a in range(3)))
        signature_pairs = greedy_pairs(source_matches, target_matches,
                                       lambda i, j: signature_distance(
                                           source_matches[i][1]["signature"],
                                           target_matches[j][1]["signature"]))
        nearest_target = next((j for i, j in nearest_pairs if i == source_index), None)
        signature_target = next((j for i, j in signature_pairs if i == source_index), None)
        if nearest_target is not None and signature_target is not None:
            if nearest_target != signature_target:
                changed_pair_samples += 1
                if len(source_matches) > 1 or len(target_matches) > 1:
                    changed_ambiguous_pair_samples += 1
        for name, target_index in (("nearest_world", nearest_target),
                                   ("lambertian_signature", signature_target)):
            if target_index is None:
                continue
            _, mapped_face, mapped_point = target_matches[target_index]
            metrics = modes[name]
            if len(source_matches) > 1 or len(target_matches) > 1:
                metrics["ambiguous_samples"] += 1
            add_mapping(metrics, source_face, mapped_face, source_point, mapped_point,
                        signature_distance(source_face["signature"], mapped_face["signature"]),
                        bounds_diagonal)

    summaries = {name: summarize(metric, metric["ambiguous_samples"], samples)
                 for name, metric in modes.items()}
    summaries["delta"] = {
        "signature_mean_relative_change": (
            summaries["lambertian_signature"]["signature_rms"]["mean"] /
            max(summaries["nearest_world"]["signature_rms"]["mean"], 1e-30) - 1.0)
            if summaries["nearest_world"]["signature_rms"]["mean"] is not None else None,
        "position_mean_relative_change": (
            summaries["lambertian_signature"]["position_over_bounds"]["mean"] /
            max(summaries["nearest_world"]["position_over_bounds"]["mean"], 1e-30) - 1.0)
            if summaries["nearest_world"]["position_over_bounds"]["mean"] is not None else None,
        "normal_angle_mean_relative_change": (
            summaries["lambertian_signature"]["normal_angle_degrees"]["mean"] /
            max(summaries["nearest_world"]["normal_angle_degrees"]["mean"], 1e-30) - 1.0)
            if summaries["nearest_world"]["normal_angle_degrees"]["mean"] is not None else None,
    }
    return {"samples": samples, "seed": seed, "grid_resolution": grid_resolution,
            "signature_directions": direction_count,
            "ambiguous_uv_samples": ambiguous_samples,
            "ambiguous_uv_fraction": ambiguous_samples / samples if samples else 0.0,
            "changed_pair_samples": changed_pair_samples,
            "changed_pair_fraction": changed_pair_samples / samples if samples else 0.0,
            "changed_ambiguous_pair_samples": changed_ambiguous_pair_samples,
            "matching": summaries,
            "scope": "uniform source UV-area samples; greedy one-to-one matching; Lambertian cosine signature only; no scene visibility, texture/BSDF, path estimator, ReSTIR variance, or global smoothness proof"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--directions", type=int, default=128)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.samples <= 0 or args.grid_resolution <= 0 or args.directions <= 0:
        parser.error("sample count, UV grid resolution, and direction count must be positive")
    source, target = uv.prepare(args.source), uv.prepare(args.target)
    report = {"schema": 1, "source": str(args.source), "target": str(args.target),
              "source_sha256": sha256(args.source), "target_sha256": sha256(args.target),
              "script_sha256": sha256(Path(__file__)),
              "result": measure(source, target, args.samples, args.seed,
                                args.grid_resolution, args.directions)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report["result"], indent=2))


if __name__ == "__main__":
    main()
