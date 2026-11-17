#!/usr/bin/env python3
"""Paired CPU single-merge RIS screen with mesh self-visibility.

This extends the UV-mapped LOD weight preflight with actual triangle-BVH
visibility for a discrete directional environment. It is still a direct-light
surface-integral proxy, not a path tracer or a full ReSTIR implementation.
"""

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import random
import statistics
from pathlib import Path

import numpy as np


def load_local(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRANSPORT = load_local("measure_lod_uv_transport")
VISIBILITY = load_local("visibility_query_bvh")

LIGHTS = (
    ((0.372033136067503, 0.7139014232646679, 0.5932420277833156), (1.0, 0.15, 0.08)),
    ((-0.8105675960454269, 0.32022423547473655, 0.49034336057069033), (0.08, 1.0, 0.15)),
    ((0.24065063626587385, -0.9124669958414384, 0.3308946248655766), (0.1, 0.18, 1.0)),
    ((-0.5492590001874574, -0.20971707279884735, 0.8089087093669828), (0.9, 0.85, 0.12)),
)
VIEWS = (
    (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
)
LUMINANCE = (0.2126, 0.7152, 0.0722)
ALBEDO = 0.8
GLOSSY_DIFFUSE = 0.25
GLOSSY_SPECULAR = 0.75
PHONG_EXPONENT = 64


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def luminance(rgb):
    return sum(rgb[i] * LUMINANCE[i] for i in range(3))


def make_mesh_bvh(mesh):
    positions = np.asarray([p for face in mesh["faces"] for p in face["p"]], dtype=np.float64)
    triangles = np.arange(len(positions), dtype=np.int32).reshape(-1, 3)
    return VISIBILITY.BVH.mesh(positions, triangles)


def light_is_visible(face, point, light_index, bvh, epsilon, max_distance, counters):
    direction, color = LIGHTS[light_index]
    cosine = max(0.0, TRANSPORT.dot3(face["normal"], direction))
    if cosine <= 0.0:
        return False
    origin = tuple(point[a] + face["normal"][a] * epsilon for a in range(3))
    ray = VISIBILITY.Ray(origin, direction, max_distance)
    return not bvh.query(ray, counters)


def surface_contribution(face, light_index, view_index, shading, visible):
    direction, color = LIGHTS[light_index]
    normal = face["normal"]
    cosine_in = max(0.0, TRANSPORT.dot3(normal, direction))
    if cosine_in <= 0.0 or not visible:
        return (0.0, 0.0, 0.0)
    if shading == "diffuse":
        scale = ALBEDO * cosine_in / math.pi
    else:
        view = VIEWS[view_index]
        cosine_out = TRANSPORT.dot3(normal, view)
        if cosine_out <= 0.0:
            return (0.0, 0.0, 0.0)
        reflected = tuple(2.0 * cosine_in * normal[i] - direction[i]
                          for i in range(3))
        alignment = max(0.0, TRANSPORT.dot3(reflected, view))
        diffuse = GLOSSY_DIFFUSE / math.pi
        specular = (GLOSSY_SPECULAR * (PHONG_EXPONENT + 2) / (2.0 * math.pi) *
                    alignment ** PHONG_EXPONENT)
        scale = cosine_in * (diffuse + specular)
    return tuple(scale * value for value in color)


def build_source_sampler(mesh):
    cumulative, total_uv_area = [], 0.0
    for face in mesh["faces"]:
        total_uv_area += face["uv_area"]
        cumulative.append(total_uv_area)
    return cumulative, total_uv_area


def choose_path(probabilities, rng, view_count):
    draw = rng.random()
    cumulative = 0.0
    for light_index, probability in enumerate(probabilities):
        cumulative += probability
        if draw <= cumulative:
            return light_index // view_count, light_index % view_count, probability
    index = len(probabilities) - 1
    return index // view_count, index % view_count, probabilities[-1]


def sample_uv_point(mesh, cumulative, total_uv_area, rng):
    face_index = min(bisect.bisect_left(cumulative, rng.random() * total_uv_area),
                     len(mesh["faces"]) - 1)
    face = mesh["faces"][face_index]
    r1, r2 = rng.random(), rng.random()
    if r1 + r2 > 1.0:
        r1, r2 = 1.0 - r1, 1.0 - r2
    bary = (1.0 - r1 - r2, r1, r2)
    uv = TRANSPORT.add_weighted(face["uv"], bary)
    point = TRANSPORT.add_weighted(face["p"], bary)
    return face, uv, point


def source_probabilities(face, point, bvh, epsilon, max_distance, counters,
                         uniform_floor, shading, view_count):
    visible = [light_is_visible(face, point, i, bvh, epsilon, max_distance, counters)
               for i in range(len(LIGHTS))]
    target = [luminance(surface_contribution(face, light, view, shading, visible[light]))
              for light in range(len(LIGHTS)) for view in range(view_count)]
    total = sum(target)
    count = len(target)
    if total <= 1e-30:
        return [1.0 / count] * count
    return [(1.0 - uniform_floor) * value / total + uniform_floor / count
            for value in target]


def exact_direct_integral(mesh, bvh, epsilon, max_distance, samples_per_face,
                          seed, shading, view_count):
    """Stratified Monte Carlo reference over every geometric triangle and light."""
    rng = random.Random(seed)
    total = [0.0, 0.0, 0.0]
    counters = [0, 0, 0]
    for face in mesh["faces"]:
        summed = [0.0, 0.0, 0.0]
        for _ in range(samples_per_face):
            r1, r2 = rng.random(), rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            point = TRANSPORT.add_weighted(face["p"], (1.0 - r1 - r2, r1, r2))
            visible = [light_is_visible(face, point, light, bvh, epsilon,
                                        max_distance, counters)
                       for light in range(len(LIGHTS))]
            for light_index in range(len(LIGHTS)):
                for view_index in range(view_count):
                    rgb = surface_contribution(face, light_index, view_index,
                                               shading, visible[light_index])
                    for channel in range(3):
                        summed[channel] += rgb[channel]
        for channel in range(3):
            total[channel] += face["geom_area"] * summed[channel] / samples_per_face
    return total, counters


def average_rgb(vectors):
    return [statistics.fmean(vector[channel] for vector in vectors)
            for channel in range(3)]


def rgb_standard_error(vectors):
    if len(vectors) < 2:
        return [0.0, 0.0, 0.0]
    return [statistics.stdev(vector[channel] for vector in vectors) / math.sqrt(len(vectors))
            for channel in range(3)]


def add_counters(first, second):
    return [a + b for a, b in zip(first, second)]


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    alpha = position - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha


def bootstrap_mean_interval(values, seed, replicate_count):
    rng = random.Random(seed)
    count = len(values)
    means = [statistics.fmean(values[rng.randrange(count)] for _ in range(count))
             for _ in range(replicate_count)]
    return [quantile(means, 0.025), quantile(means, 0.975)]


def evaluate_batch(bvh, samples, source_uv_area, batch_size, epsilon,
                   max_distance, counters, cross_lod, shading):
    estimate = [0.0, 0.0, 0.0]
    weights = []
    weighted_g_norm2 = 0.0
    misses = ambiguous = 0
    for (source_face, source_point, light_index, view_index, probability,
         target_face, target_point) in samples:
        face = target_face if cross_lod else source_face
        point = target_point if cross_lod else source_point
        if face is None or point is None:
            misses += 1
            weights.append(0.0)
            continue
        visible = light_is_visible(face, point, light_index, bvh, epsilon,
                                   max_distance, counters)
        rgb = surface_contribution(face, light_index, view_index, shading, visible)
        target_h = luminance(rgb)
        if target_h <= 1e-30:
            weights.append(0.0)
            continue
        jacobian = face["geom_area"] / face["uv_area"]
        weight = target_h * source_uv_area * jacobian / (probability * batch_size)
        g = tuple(value / target_h for value in rgb)
        weights.append(weight)
        for channel in range(3):
            estimate[channel] += weight * g[channel]
        weighted_g_norm2 += weight * sum(value * value for value in g)
    total_weight = sum(weights)
    conditional_trace = total_weight * weighted_g_norm2 - sum(value * value for value in estimate)
    conditional_trace = max(0.0, conditional_trace)
    square_sum = sum(value * value for value in weights)
    ess = total_weight * total_weight / square_sum if square_sum else 0.0
    if square_sum and ess < 1.0 - 1e-10:
        raise ArithmeticError("positive RIS weights violated the ESS >= 1 invariant")
    return {"estimate": estimate, "conditionalTrace": conditional_trace,
            "ess": ess, "zeroWeightBatch": square_sum == 0.0,
            "activeCandidates": sum(value > 0.0 for value in weights),
            "misses": misses, "ambiguous": ambiguous}


def make_samples(source, target, source_bvh, source_cumulative, source_uv_area,
                 rng, batch_count, batch_size, epsilon, max_distance,
                 uniform_floor, source_counters, target_counters, shading, view_count):
    batches = []
    misses = ambiguous = 0
    for _ in range(batch_count):
        batch = []
        for _ in range(batch_size):
            source_face, uv, point = sample_uv_point(source, source_cumulative,
                                                     source_uv_area, rng)
            probabilities = source_probabilities(source_face, point, source_bvh,
                                                 epsilon, max_distance,
                                                 source_counters, uniform_floor,
                                                 shading, view_count)
            light_index, view_index, probability = choose_path(probabilities, rng, view_count)
            matches = TRANSPORT.surface_matches(target, uv, point)
            target_face = min(matches, key=lambda item: item[0])[1] if matches else None
            if not matches:
                misses += 1
            elif len(matches) > 1:
                ambiguous += 1
            target_point = min(matches, key=lambda item: item[0])[2] if matches else None
            batch.append((source_face, point, light_index, view_index, probability,
                          target_face, target_point))
        if len(batch) != batch_size:
            raise ArithmeticError("candidate batch size does not match the configured value")
        batches.append(batch)
    return batches, misses, ambiguous


def run_pair(name, source_path, target_path, args, pair_index):
    source = TRANSPORT.prepare(source_path)
    target = TRANSPORT.prepare(target_path)
    TRANSPORT.build_uv_bins(source, args.grid_resolution)
    TRANSPORT.build_uv_bins(target, args.grid_resolution)
    source_bvh, target_bvh = make_mesh_bvh(source), make_mesh_bvh(target)
    all_points = [p for mesh in (source, target) for face in mesh["faces"] for p in face["p"]]
    bounds_min = [min(point[a] for point in all_points) for a in range(3)]
    bounds_max = [max(point[a] for point in all_points) for a in range(3)]
    diagonal = max(TRANSPORT.length3(tuple(bounds_max[a] - bounds_min[a] for a in range(3))),
                   1e-20)
    epsilon, max_distance = diagonal * 1e-5, diagonal * 4.0
    source_cumulative, source_uv_area = build_source_sampler(source)
    target_uv_area = sum(face["uv_area"] for face in target["faces"])
    source_counters, target_counters = [0, 0, 0], [0, 0, 0]
    shading = args.shading
    view_count = len(VIEWS) if shading == "glossy" else 1

    seed = args.seed + pair_index * 100003
    rng = random.Random(seed)
    batches, misses, ambiguous = make_samples(
        source, target, source_bvh, source_cumulative, source_uv_area,
        rng, args.batches, args.batch_size, epsilon, max_distance,
        args.uniform_floor, source_counters, target_counters, shading, view_count)

    source_references, target_references = [], []
    source_reference_counters, target_reference_counters = [0, 0, 0], [0, 0, 0]
    for replicate in range(args.reference_replicates):
        source_reference, source_counts = exact_direct_integral(
            source, source_bvh, epsilon, max_distance, args.reference_samples_per_face,
            seed + 900001 + replicate * 7919, shading, view_count)
        target_reference, target_counts = exact_direct_integral(
            target, target_bvh, epsilon, max_distance, args.reference_samples_per_face,
            seed + 900002 + replicate * 7919, shading, view_count)
        source_references.append(source_reference)
        target_references.append(target_reference)
        source_reference_counters = add_counters(source_reference_counters, source_counts)
        target_reference_counters = add_counters(target_reference_counters, target_counts)
    source_exact, target_exact = average_rgb(source_references), average_rgb(target_references)
    source_reference_se = rgb_standard_error(source_references)
    target_reference_se = rgb_standard_error(target_references)
    exact_values = {"same": source_exact, "cross": target_exact}
    exact_norm2 = {key: sum(value * value for value in rgb)
                   for key, rgb in exact_values.items()}

    same_rows, cross_rows = [], []
    same_estimates, cross_estimates = [], []
    ess_same, ess_cross = [], []
    cond_same, cond_cross = [], []
    zero_batches_same = zero_batches_cross = 0
    active_same, active_cross = [], []
    for batch in batches:
        same = evaluate_batch(source_bvh, batch, source_uv_area, args.batch_size,
                              epsilon, max_distance, source_counters,
                              cross_lod=False, shading=shading)
        cross = evaluate_batch(target_bvh, batch, source_uv_area, args.batch_size,
                               epsilon, max_distance, target_counters,
                               cross_lod=True, shading=shading)
        same_mse = (same["conditionalTrace"] +
                    sum((same["estimate"][c] - source_exact[c]) ** 2 for c in range(3)))
        cross_mse = (cross["conditionalTrace"] +
                     sum((cross["estimate"][c] - target_exact[c]) ** 2 for c in range(3)))
        same_rows.append(same_mse / exact_norm2["same"] if exact_norm2["same"] else 0.0)
        cross_rows.append(cross_mse / exact_norm2["cross"] if exact_norm2["cross"] else 0.0)
        same_estimates.append(same["estimate"])
        cross_estimates.append(cross["estimate"])
        ess_same.append(same["ess"])
        ess_cross.append(cross["ess"])
        zero_batches_same += same["zeroWeightBatch"]
        zero_batches_cross += cross["zeroWeightBatch"]
        active_same.append(same["activeCandidates"])
        active_cross.append(cross["activeCandidates"])
        cond_same.append(same["conditionalTrace"] / exact_norm2["same"]
                         if exact_norm2["same"] else 0.0)
        cond_cross.append(cross["conditionalTrace"] / exact_norm2["cross"]
                          if exact_norm2["cross"] else 0.0)

    deltas = [cross_rows[i] - same_rows[i] for i in range(args.batches)]
    delta_mean = statistics.fmean(deltas)
    delta_se = statistics.stdev(deltas) / math.sqrt(args.batches)
    source_mse, target_mse = statistics.fmean(same_rows), statistics.fmean(cross_rows)
    same_mean_estimate = average_rgb(same_estimates)
    cross_mean_estimate = average_rgb(cross_estimates)
    return {
        "name": name,
        "source": str(source_path), "target": str(target_path),
        "sourceSha256": sha256(source_path), "targetSha256": sha256(target_path),
        "sourceTriangles": source["triangle_count"], "targetTriangles": target["triangle_count"],
        "sourceUvArea": source_uv_area, "targetUvArea": target_uv_area,
        "seed": seed, "batches": args.batches, "batchSize": args.batch_size,
        "referenceSamplesPerFace": args.reference_samples_per_face,
        "referenceReplicates": args.reference_replicates,
        "uniformProposalFloor": args.uniform_floor,
        "shading": shading, "viewCount": view_count,
        "sameLod": {"estimatedExactRgbIntegral": source_exact,
                    "referenceStandardErrorRgb": source_reference_se,
                    "referenceRelativeStandardErrorL2":
                        math.sqrt(sum(value * value for value in source_reference_se)) /
                        math.sqrt(exact_norm2["same"]) if exact_norm2["same"] else None,
                    "relativeMse": source_mse,
                    "meanEstimatorRgb": same_mean_estimate,
                    "relativeBiasNorm": math.sqrt(sum((same_mean_estimate[c] - source_exact[c]) ** 2
                                                       for c in range(3)) / exact_norm2["same"])
                    if exact_norm2["same"] else None,
                    "meanNormalizedConditionalTrace": statistics.fmean(cond_same),
                    "meanEssIncludingZeroWeightBatches": statistics.fmean(ess_same),
                    "meanEssNonzeroBatches": statistics.fmean([value for value in ess_same if value > 0.0])
                    if any(value > 0.0 for value in ess_same) else 0.0,
                    "zeroWeightBatches": zero_batches_same,
                    "meanActiveCandidates": statistics.fmean(active_same)},
        "crossLod": {"estimatedExactRgbIntegral": target_exact,
                     "referenceStandardErrorRgb": target_reference_se,
                     "referenceRelativeStandardErrorL2":
                         math.sqrt(sum(value * value for value in target_reference_se)) /
                         math.sqrt(exact_norm2["cross"]) if exact_norm2["cross"] else None,
                     "relativeMse": target_mse,
                     "meanEstimatorRgb": cross_mean_estimate,
                     "relativeBiasNorm": math.sqrt(sum((cross_mean_estimate[c] - target_exact[c]) ** 2
                                                        for c in range(3)) / exact_norm2["cross"])
                     if exact_norm2["cross"] else None,
                     "meanNormalizedConditionalTrace": statistics.fmean(cond_cross),
                     "meanEssIncludingZeroWeightBatches": statistics.fmean(ess_cross),
                     "meanEssNonzeroBatches": statistics.fmean([value for value in ess_cross if value > 0.0])
                     if any(value > 0.0 for value in ess_cross) else 0.0,
                     "zeroWeightBatches": zero_batches_cross,
                     "meanActiveCandidates": statistics.fmean(active_cross)},
        "relativeMseRatioCrossOverSame": target_mse / source_mse if source_mse else None,
        "pairedRelativeMseDifference": {
            "mean": delta_mean, "standardError": delta_se,
            "normal95PercentInterval": [delta_mean - 1.96 * delta_se,
                                         delta_mean + 1.96 * delta_se],
            "bootstrapMean95PercentInterval": bootstrap_mean_interval(
                deltas, seed + 700003, args.bootstrap_replicates),
            "bootstrapReplicates": args.bootstrap_replicates,
            "deltaQuantiles": {str(q): quantile(deltas, q)
                               for q in (0.01, 0.05, 0.5, 0.95, 0.99)},
            "minimum": min(deltas), "maximum": max(deltas),
        },
        "batchDeltaValues": deltas if args.store_batch_deltas else None,
        "mappedSampleMisses": misses, "ambiguousMappedSamples": ambiguous,
        "rayCounters": {"sourceCandidatesAndBaseline": source_counters,
                        "targetCandidatesAndCross": target_counters,
                        "sourceReference": source_reference_counters,
                        "targetReference": target_reference_counters},
    }


def parse_pair(value):
    name, separator, paths = value.partition("=")
    source, path_separator, target = paths.partition("|")
    if not separator or not path_separator or not name or not source or not target:
        raise argparse.ArgumentTypeError("pair must be NAME=SOURCE.obj|TARGET.obj")
    return name, Path(source), Path(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", type=parse_pair, required=True)
    parser.add_argument("--batches", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20261121)
    parser.add_argument("--uniform-floor", type=float, default=0.05)
    parser.add_argument("--shading", choices=("diffuse", "glossy"), default="diffuse")
    parser.add_argument("--reference-samples-per-face", type=int, default=64)
    parser.add_argument("--reference-replicates", type=int, default=4)
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--store-batch-deltas", action="store_true")
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (args.batches < 2 or args.batch_size < 1 or args.reference_samples_per_face < 1 or
            args.reference_replicates < 2 or args.bootstrap_replicates < 100):
        parser.error("batches must be >=2 and batch/reference sample counts must be positive")
    if not 0.0 < args.uniform_floor <= 1.0:
        parser.error("uniform-floor must be in (0,1]")

    rows = [run_pair(name, source, target, args, index)
            for index, (name, source, target) in enumerate(args.pair)]
    critical = statistics.NormalDist().inv_cdf(1.0 - 0.05 / (2.0 * len(rows)))
    for row in rows:
        interval = row["pairedRelativeMseDifference"]["normal95PercentInterval"]
        mean = row["pairedRelativeMseDifference"]["mean"]
        se = row["pairedRelativeMseDifference"]["standardError"]
        row["pairedRelativeMseDifference"]["bonferroni95PercentFamilyInterval"] = [
            mean - critical * se, mean + critical * se]

    manifest = {
        "schema": 1,
        "method": "paired single-merge RGB RIS with source-conditioned directional proposal and mesh self-visibility",
        "lighting": [{"direction": direction, "rgb": rgb} for direction, rgb in LIGHTS],
        "views": list(VIEWS) if args.shading == "glossy" else None,
        "albedo": ALBEDO,
        "glossyMaterial": {"diffuse": GLOSSY_DIFFUSE, "specular": GLOSSY_SPECULAR,
                           "phongExponent": PHONG_EXPONENT},
        "luminanceCoefficients": LUMINANCE,
        "measure": "source UV area, mapped by nearest world-space point at the same UV; target density includes dA/dUV",
        "weights": "w_i=(1/M)*targetLuminance_i/q_i; q_i=p_source(light|uv)/(sourceUvArea*targetGeomArea/targetUvArea)",
        "limitations": [
            "surface-integrated direct lighting only; no camera path domain or multi-bounce transport",
            "four discrete directional lights and constant diffuse or synthetic Phong BSDF; no textures",
            "self-visibility against each LOD mesh only; no external occluders or transparent surfaces",
            "reference direct integral is an independent finite Monte Carlo estimate",
            "one RIS merge only; no iterative spatial/temporal reservoir history or inter-frame covariance",
            "existing LOD order only; no alternative collapse sequence tested",
        ],
        "scriptSha256": sha256(Path(__file__)),
        "transportHelperSha256": sha256(Path(__file__).with_name("measure_lod_uv_transport.py")),
        "visibilityBvhSha256": sha256(Path(__file__).with_name("visibility_query_bvh.py")),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"out": str(args.out), "results": [
        {"name": row["name"], "ratio": row["relativeMseRatioCrossOverSame"],
         "pairedFamilyInterval": row["pairedRelativeMseDifference"][
             "bonferroni95PercentFamilyInterval"],
         "misses": row["mappedSampleMisses"],
         "ambiguous": row["ambiguousMappedSamples"]} for row in rows]}, indent=2))


if __name__ == "__main__":
    main()
