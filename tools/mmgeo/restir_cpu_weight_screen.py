#!/usr/bin/env python3
"""CPU screen of single-vertex GRIS reuse weights on real UV-mapped LOD pairs.

This is a deliberately small estimator preflight. It samples a surface point from
the source mesh's UV-area measure plus discrete light and view directions, maps
the point by the same nearest UV rule as the local transport preflight, and
computes exact single-merge RIS conditional covariance. It omits camera sampling,
visibility, multi-vertex paths, and the iterative ReSTIR passes.
"""

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics


TRANSPORT_PATH = Path(__file__).with_name("measure_lod_uv_transport.py")
SPEC = importlib.util.spec_from_file_location("lod_uv_transport", TRANSPORT_PATH)
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)


RAW_LIGHTS = (
    ((0.37, 0.71, 0.59), (1.00, 0.15, 0.08)),
    ((-0.81, 0.32, 0.49), (0.08, 1.00, 0.15)),
    ((0.24, -0.91, 0.33), (0.10, 0.18, 1.00)),
    ((-0.55, -0.21, 0.81), (0.90, 0.85, 0.12)),
)
RAW_VIEWS = (
    (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
)


def normalize(v):
    length = math.sqrt(sum(x * x for x in v))
    return tuple(x / length for x in v)


LIGHTS = tuple((normalize(direction), color) for direction, color in RAW_LIGHTS)
VIEWS = tuple(normalize(direction) for direction in RAW_VIEWS)
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


def source_sampler(mesh):
    cumulative = []
    total_uv_area = 0.0
    for face in mesh["faces"]:
        total_uv_area += face["uv_area"]
        cumulative.append(total_uv_area)
    if total_uv_area <= 0:
        raise ValueError("source mesh has no positive UV area")
    return cumulative, total_uv_area


def directional_paths(face, shading, view_count):
    return [(light_index, view_index, contribution(face, light_index, view_index, shading)[1])
            for light_index in range(len(LIGHTS))
            for view_index in range(view_count)]


def source_direction_probabilities(face, shading, view_count, uniform_floor):
    paths = directional_paths(face, shading, view_count)
    target_sum = sum(path[2] for path in paths)
    count = len(paths)
    if target_sum <= 1e-30:
        return [(light, view, 1.0 / count) for light, view, _ in paths]
    return [(light, view, (1.0 - uniform_floor) * target / target_sum +
             uniform_floor / count) for light, view, target in paths]


def sample_source_path(mesh, cumulative, total_uv_area, rng, shading, view_count,
                       uniform_floor):
    face_index = min(bisect.bisect_left(cumulative, rng.random() * total_uv_area),
                     len(mesh["faces"]) - 1)
    face = mesh["faces"][face_index]
    r1, r2 = rng.random(), rng.random()
    if r1 + r2 > 1.0:
        r1, r2 = 1.0 - r1, 1.0 - r2
    bary = (1.0 - r1 - r2, r1, r2)
    uv = TRANSPORT.add_weighted(face["uv"], bary)
    source_point = TRANSPORT.add_weighted(face["p"], bary)
    probabilities = source_direction_probabilities(face, shading, view_count, uniform_floor)
    draw = rng.random()
    cumulative_probability = 0.0
    for light_index, view_index, probability in probabilities:
        cumulative_probability += probability
        if draw <= cumulative_probability:
            return uv, source_point, light_index, view_index, probability
    light_index, view_index, probability = probabilities[-1]
    return uv, source_point, light_index, view_index, probability


def contribution(face, light_index, view_index, shading):
    direction, color = LIGHTS[light_index]
    normal = face["normal"]
    cosine_in = max(0.0, TRANSPORT.dot3(normal, direction))
    if shading == "diffuse":
        scale = ALBEDO * cosine_in / math.pi
    else:
        view = VIEWS[view_index]
        cosine_out = TRANSPORT.dot3(normal, view)
        if cosine_in <= 0.0 or cosine_out <= 0.0:
            scale = 0.0
        else:
            reflected = tuple(2.0 * cosine_in * normal[i] - direction[i]
                              for i in range(3))
            alignment = max(0.0, TRANSPORT.dot3(reflected, view))
            diffuse = GLOSSY_DIFFUSE / math.pi
            specular = (GLOSSY_SPECULAR * (PHONG_EXPONENT + 2) / (2.0 * math.pi) *
                        alignment ** PHONG_EXPONENT)
            scale = cosine_in * (diffuse + specular)
    rgb = tuple(scale * c for c in color)
    target = sum(rgb[i] * LUMINANCE[i] for i in range(3))
    return rgb, target


def exact_integral(mesh, shading, view_count):
    result = [0.0, 0.0, 0.0]
    for face in mesh["faces"]:
        for light_index in range(len(LIGHTS)):
            for view_index in range(view_count):
                rgb, _ = contribution(face, light_index, view_index, shading)
                for channel in range(3):
                    result[channel] += face["geom_area"] * rgb[channel]
    return result


def map_batch(target, samples, total_source_uv_area, batch_size, shading):
    weighted_rgb = [0.0, 0.0, 0.0]
    weights = []
    weighted_g_norm2 = 0.0
    misses = 0
    ambiguous = 0
    zero_target = 0
    for uv, source_point, light_index, view_index, path_probability in samples:
        matches = TRANSPORT.surface_matches(target, uv, source_point)
        if not matches:
            misses += 1
            weights.append(0.0)
            continue
        if len(matches) > 1:
            ambiguous += 1
        target_face = min(matches, key=lambda item: item[0])[1]
        rgb, target_density = contribution(target_face, light_index, view_index, shading)
        if target_density <= 1e-30:
            zero_target += 1
            weights.append(0.0)
            continue

        # q(y, light, view) is the source-conditioned path probability divided by
        # source UV area and the target's dA/dUV Jacobian.
        # m_i = 1 / batch_size is the single-merge RIS mixture weight.
        inverse_proposal = (total_source_uv_area *
                            target_face["geom_area"] / target_face["uv_area"] *
                            (1.0 / path_probability))
        weight = target_density * inverse_proposal / batch_size
        g = tuple(c / target_density for c in rgb)
        weights.append(weight)
        for channel in range(3):
            weighted_rgb[channel] += weight * g[channel]
        weighted_g_norm2 += weight * sum(c * c for c in g)

    total_weight = sum(weights)
    weight_square_sum = sum(w * w for w in weights)
    conditional_trace = (total_weight * weighted_g_norm2 -
                         sum(c * c for c in weighted_rgb))
    conditional_trace = max(0.0, conditional_trace)
    ess = total_weight * total_weight / weight_square_sum if weight_square_sum else 0.0
    return {
        "mean": weighted_rgb,
        "conditionalTrace": conditional_trace,
        "ess": ess,
        "misses": misses,
        "ambiguous": ambiguous,
        "zeroTarget": zero_target,
    }


def describe_case(mesh, samples_by_batch, source_uv_area, batch_size, shading, view_count):
    exact = exact_integral(mesh, shading, view_count)
    exact_norm2 = sum(x * x for x in exact)
    batch_rows = [map_batch(mesh, samples, source_uv_area, batch_size, shading)
                  for samples in samples_by_batch]
    batch_count = len(batch_rows)
    mean = [statistics.fmean(row["mean"][c] for row in batch_rows)
            for c in range(3)]
    between_trace = sum(
        sum((row["mean"][c] - mean[c]) ** 2 for c in range(3))
        for row in batch_rows) / max(1, batch_count - 1)
    mean_conditional = statistics.fmean(row["conditionalTrace"] for row in batch_rows)
    mse_rows = [row["conditionalTrace"] +
                sum((row["mean"][c] - exact[c]) ** 2 for c in range(3))
                for row in batch_rows]
    total_mse = statistics.fmean(mse_rows)
    relative_mse_rows = [mse / exact_norm2 for mse in mse_rows] if exact_norm2 else []
    return {
        "targetTriangles": mesh["triangle_count"],
        "exactRgbIntegral": exact,
        "meanEstimatorRgb": mean,
        "relativeBiasNorm": math.sqrt(sum((mean[c] - exact[c]) ** 2 for c in range(3)) /
                                       exact_norm2) if exact_norm2 else None,
        "meanConditionalCovarianceTrace": mean_conditional,
        "betweenCandidateSetCovarianceTrace": between_trace,
        "totalRgbMseTrace": total_mse,
        "relativeTotalRgbMse": total_mse / exact_norm2 if exact_norm2 else None,
        "meanWeightEss": statistics.fmean(row["ess"] for row in batch_rows),
        "p05WeightEss": quantile([row["ess"] for row in batch_rows], 0.05),
        "p95WeightEss": quantile([row["ess"] for row in batch_rows], 0.95),
        "misses": sum(row["misses"] for row in batch_rows),
        "ambiguousMappedSamples": sum(row["ambiguous"] for row in batch_rows),
        "zeroTargetSamples": sum(row["zeroTarget"] for row in batch_rows),
        "candidatePaths": batch_count * batch_size,
        "_relativeTotalMseByBatch": relative_mse_rows,
    }


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    index = q * (len(ordered) - 1)
    lo, hi = int(index), math.ceil(index)
    return ordered[lo] * (hi - index) + ordered[hi] * (index - lo)


def parse_pair(value):
    name, separator, paths = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("pair must be NAME=SOURCE.obj|TARGET.obj")
    source, separator, target = paths.partition("|")
    if not separator or not name or not source or not target:
        raise argparse.ArgumentTypeError("pair must be NAME=SOURCE.obj|TARGET.obj")
    return name, Path(source), Path(target)


def run_pair(name, source_path, target_path, args, pair_index, shading, shading_index):
    source = TRANSPORT.prepare(source_path)
    target = TRANSPORT.prepare(target_path)
    TRANSPORT.build_uv_bins(source, args.grid_resolution)
    TRANSPORT.build_uv_bins(target, args.grid_resolution)
    cumulative, total_uv_area = source_sampler(source)
    source_uv_area = total_uv_area
    target_uv_area = sum(face["uv_area"] for face in target["faces"])

    view_count = len(VIEWS) if shading == "glossy" else 1
    run_seed = args.seed + pair_index * 100003 + shading_index * 200003
    rng = random.Random(run_seed)
    source_identity_batches = []
    cross_lod_batches = []
    for _ in range(args.batches):
        samples = [sample_source_path(source, cumulative, total_uv_area, rng, shading,
                                      view_count, args.uniform_proposal_floor)
                   for _ in range(args.batch_size)]
        source_identity_batches.append(samples)
        cross_lod_batches.append(samples)

    same_lod = describe_case(source, source_identity_batches, source_uv_area,
                             args.batch_size, shading, view_count)
    cross_lod = describe_case(target, cross_lod_batches, source_uv_area,
                              args.batch_size, shading, view_count)
    same_mse_rows = same_lod.pop("_relativeTotalMseByBatch")
    cross_mse_rows = cross_lod.pop("_relativeTotalMseByBatch")
    paired_delta = [cross_mse_rows[i] - same_mse_rows[i]
                    for i in range(args.batches)]
    paired_delta_mean = statistics.fmean(paired_delta)
    paired_delta_se = statistics.stdev(paired_delta) / math.sqrt(args.batches)
    reduction = 1.0 - target["triangle_count"] / source["triangle_count"]
    uv_area_relative_delta = ((target_uv_area - source_uv_area) / source_uv_area
                              if source_uv_area else None)
    return {
        "name": name,
        "source": str(source_path),
        "target": str(target_path),
        "sourceSha256": sha256(source_path),
        "targetSha256": sha256(target_path),
        "sourceTriangles": source["triangle_count"],
        "targetTriangles": target["triangle_count"],
        "triangleReductionFraction": reduction,
        "sourceUvArea": source_uv_area,
        "targetUvArea": target_uv_area,
        "relativeUvAreaDelta": uv_area_relative_delta,
        "batchCount": args.batches,
        "batchSize": args.batch_size,
        "seed": run_seed,
        "shading": shading,
        "directionProposal": "source-luminance with uniform support mixture",
        "uniformProposalFloor": args.uniform_proposal_floor,
        "sameLodIdentity": same_lod,
        "crossLodReuse": cross_lod,
        "relativeTotalMseRatioCrossOverIdentity":
            (cross_lod["relativeTotalRgbMse"] / same_lod["relativeTotalRgbMse"]
             if same_lod["relativeTotalRgbMse"] else None),
        "pairedRelativeTotalMseDifferenceCrossMinusIdentity": {
            "mean": paired_delta_mean,
            "standardError": paired_delta_se,
            "normal95PercentInterval": [
                paired_delta_mean - 1.96 * paired_delta_se,
                paired_delta_mean + 1.96 * paired_delta_se,
            ],
            "batches": args.batches,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", type=parse_pair, required=True,
                        help="NAME=SOURCE.obj|TARGET.obj; repeat for each transition")
    parser.add_argument("--batches", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--uniform-proposal-floor", type=float, default=0.05)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--shading", action="append", choices=("diffuse", "glossy"),
                        help="repeatable; defaults to diffuse and glossy")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.batches < 2 or args.batch_size < 1 or args.grid_resolution < 1:
        parser.error("batches must be >=2 and batch-size/grid-resolution must be positive")
    if not 0.0 < args.uniform_proposal_floor <= 1.0:
        parser.error("uniform-proposal-floor must be in (0,1]")

    shadings = args.shading or ["diffuse", "glossy"]
    rows = [run_pair(name, source, target, args, pair_index, shading, shading_index)
            for pair_index, (name, source, target) in enumerate(args.pair)
            for shading_index, shading in enumerate(shadings)]
    critical = statistics.NormalDist().inv_cdf(1.0 - 0.05 / (2.0 * len(rows)))
    for row in rows:
        contrast = row["pairedRelativeTotalMseDifferenceCrossMinusIdentity"]
        contrast["bonferroni95PercentFamilyInterval"] = [
            contrast["mean"] - critical * contrast["standardError"],
            contrast["mean"] + critical * contrast["standardError"],
        ]
    manifest = {
        "schema": 1,
        "method": "single-vertex RGB GRIS/RIS screen; UV-area source proposal; nearest UV shift",
        "formula": {
            "proposalDensity": "q(y,k,v)=p_source(k,v|uv)/(sourceUvArea*(targetGeomArea/targetUvArea))",
            "proposal": "source-face luminance importance with a uniform directional mixture floor",
            "target": "luminance of diffuse or Phong response to sampled discrete light and view directions",
            "weight": "w_i=(1/batchSize)*target(y_i,k_i)/q(y_i,k_i)",
            "conditionalCovarianceTrace": "W*sum_i(w_i*||g_i||^2)-||sum_i(w_i*g_i)||^2",
            "g": "RGBContribution/target",
        },
        "lighting": [
            {"direction": direction, "rgb": color} for direction, color in LIGHTS
        ],
        "views": list(VIEWS),
        "albedo": ALBEDO,
        "uniformProposalFloor": args.uniform_proposal_floor,
        "glossyMaterial": {"diffuse": GLOSSY_DIFFUSE, "specular": GLOSSY_SPECULAR,
                           "phongExponent": PHONG_EXPONENT},
        "luminanceCoefficients": LUMINANCE,
        "limitations": [
            "one mapped surface vertex only; no camera domain or multi-vertex path",
            "no visibility, shadowing, or texture variation; glossy mode uses a synthetic Phong BRDF",
            "one RIS/GRIS merge only; no iterative reservoir history or inter-frame covariance",
            "screen is a metric preflight, not a full ReSTIR estimator or contribution claim",
        ],
        "scriptSha256": sha256(Path(__file__)),
        "transportHelperSha256": sha256(TRANSPORT_PATH),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "pairs": [{
            "name": row["name"] + "-" + row["shading"],
            "triangles": [row["sourceTriangles"], row["targetTriangles"]],
            "relativeMseRatio": row["relativeTotalMseRatioCrossOverIdentity"],
            "pairedDeltaInterval": row["pairedRelativeTotalMseDifferenceCrossMinusIdentity"][
                "bonferroni95PercentFamilyInterval"],
            "crossLodEss": row["crossLodReuse"]["meanWeightEss"],
            "misses": row["crossLodReuse"]["misses"],
            "ambiguous": row["crossLodReuse"]["ambiguousMappedSamples"],
        } for row in rows],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
