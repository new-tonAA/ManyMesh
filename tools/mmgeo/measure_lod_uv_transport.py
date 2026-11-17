#!/usr/bin/env python3
"""Measure a UV-space surface-map proxy between exported OBJ LODs.

This is a geometric/map-support preflight only. It does not sample camera paths, BSDFs,
visibility, ReSTIR reservoirs, or the path distribution used by a renderer.
"""

import argparse
import bisect
import hashlib
import json
import math
import random
from pathlib import Path


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def sub2(a, b):
    return a[0] - b[0], a[1] - b[1]


def sub3(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def length3(a):
    return math.sqrt(dot3(a, a))


def add_weighted(values, weights):
    return tuple(sum(values[i][axis] * weights[i] for i in range(3))
                 for axis in range(len(values[0])))


def triangle_area2(a, b, c):
    return abs(cross2(sub2(b, a), sub2(c, a))) * 0.5


def triangle_area3(a, b, c):
    return length3(cross3(sub3(b, a), sub3(c, a))) * 0.5


def load_obj(path):
    positions = []
    texcoords = []
    triangles = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "v" and len(fields) >= 4:
                positions.append(tuple(map(float, fields[1:4])))
            elif fields[0] == "vt" and len(fields) >= 3:
                texcoords.append(tuple(map(float, fields[1:3])))
            elif fields[0] == "f":
                corners = []
                for field in fields[1:]:
                    items = field.split("/")
                    if len(items) < 2 or not items[0] or not items[1]:
                        raise ValueError(f"{path}:{line_number}: face corner has no UV index")
                    pi = int(items[0])
                    ti = int(items[1])
                    pi = len(positions) + pi if pi < 0 else pi - 1
                    ti = len(texcoords) + ti if ti < 0 else ti - 1
                    if not (0 <= pi < len(positions) and 0 <= ti < len(texcoords)):
                        raise ValueError(f"{path}:{line_number}: OBJ index is out of range")
                    corners.append((pi, ti))
                for i in range(1, len(corners) - 1):
                    triangles.append((corners[0], corners[i], corners[i + 1]))
    if not positions or not texcoords or not triangles:
        raise ValueError(f"{path}: expected positions, UVs, and triangular faces")
    return positions, texcoords, triangles


def prepare(path):
    positions, texcoords, indices = load_obj(path)
    faces = []
    for corners in indices:
        p = tuple(positions[c[0]] for c in corners)
        uv = tuple(texcoords[c[1]] for c in corners)
        uv_area = triangle_area2(*uv)
        geom_area = triangle_area3(*p)
        if uv_area <= 1e-15 or geom_area <= 1e-20:
            continue
        raw_normal = cross3(sub3(p[1], p[0]), sub3(p[2], p[0]))
        normal_length = length3(raw_normal)
        normal = tuple(v / normal_length for v in raw_normal)
        faces.append({"p": p, "uv": uv, "uv_area": uv_area, "geom_area": geom_area,
                      "normal": normal})
    if not faces:
        raise ValueError(f"{path}: no non-degenerate UV/geometric triangles")
    return {"path": path, "positions": positions, "texcoords": texcoords,
            "triangle_count": len(indices), "faces": faces}


def build_uv_bins(mesh, resolution):
    all_uv = [uv for face in mesh["faces"] for uv in face["uv"]]
    min_x = min(p[0] for p in all_uv)
    min_y = min(p[1] for p in all_uv)
    max_x = max(p[0] for p in all_uv)
    max_y = max(p[1] for p in all_uv)
    span_x = max(max_x - min_x, 1e-12)
    span_y = max(max_y - min_y, 1e-12)
    bins = {}

    def cell(point):
        x = int((point[0] - min_x) / span_x * resolution)
        y = int((point[1] - min_y) / span_y * resolution)
        return min(max(x, 0), resolution - 1), min(max(y, 0), resolution - 1)

    for face_id, face in enumerate(mesh["faces"]):
        lo = cell((min(p[0] for p in face["uv"]), min(p[1] for p in face["uv"])))
        hi = cell((max(p[0] for p in face["uv"]), max(p[1] for p in face["uv"])))
        for y in range(lo[1], hi[1] + 1):
            for x in range(lo[0], hi[0] + 1):
                bins.setdefault((x, y), []).append(face_id)
    mesh["uv_bins"] = bins
    mesh["uv_cell"] = cell


def barycentric_uv(point, tri, epsilon=1e-10):
    a, b, c = tri
    denominator = cross2(sub2(b, a), sub2(c, a))
    if abs(denominator) <= 1e-20:
        return None
    wb = cross2(sub2(point, a), sub2(c, a)) / denominator
    wc = cross2(sub2(b, a), sub2(point, a)) / denominator
    wa = 1.0 - wb - wc
    if min(wa, wb, wc) < -epsilon or max(wa, wb, wc) > 1.0 + epsilon:
        return None
    return wa, wb, wc


def surface_matches(mesh, uv_point, reference_point):
    candidates = mesh["uv_bins"].get(mesh["uv_cell"](uv_point), ())
    matches = []
    for face_id in candidates:
        face = mesh["faces"][face_id]
        bary = barycentric_uv(uv_point, face["uv"])
        if bary is not None:
            point = add_weighted(face["p"], bary)
            distance2 = sum((reference_point[a] - point[a]) ** 2 for a in range(3))
            matches.append((distance2, face, point))
    return matches


def quantiles(values):
    if not values:
        return {"min": None, "median": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)

    def at(q):
        index = q * (len(ordered) - 1)
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        alpha = index - lower
        return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha

    return {"min": ordered[0], "median": at(0.5), "p95": at(0.95),
            "p99": at(0.99), "max": ordered[-1]}


def measure(source, target, sample_count, seed, grid_resolution):
    build_uv_bins(source, grid_resolution)
    build_uv_bins(target, grid_resolution)
    rng = random.Random(seed)
    source_faces = source["faces"]
    cumulative = []
    total_uv_area = 0.0
    for face in source_faces:
        total_uv_area += face["uv_area"]
        cumulative.append(total_uv_area)
    bbox_min = [min(p[a] for face in source_faces for p in face["p"]) for a in range(3)]
    bbox_max = [max(p[a] for face in source_faces for p in face["p"]) for a in range(3)]
    bounds_diagonal = length3(tuple(bbox_max[a] - bbox_min[a] for a in range(3)))
    bounds_diagonal = max(bounds_diagonal, 1e-20)

    supported = 0
    target_ambiguous = 0
    source_ambiguous = 0
    mutual_nearest = 0
    position_errors = []
    round_trip_errors = []
    normal_angles = []
    jacobians = []
    log2_jacobians = []
    for _ in range(sample_count):
        face_index = bisect.bisect_left(cumulative, rng.random() * total_uv_area)
        face_index = min(face_index, len(source_faces) - 1)
        face = source_faces[face_index]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1.0:
            r1, r2 = 1.0 - r1, 1.0 - r2
        source_bary = (1.0 - r1 - r2, r1, r2)
        uv_point = add_weighted(face["uv"], source_bary)
        source_point = add_weighted(face["p"], source_bary)
        matches = surface_matches(target, uv_point, source_point)
        if not matches:
            continue
        supported += 1
        if len(matches) > 1:
            target_ambiguous += 1
        source_matches = surface_matches(source, uv_point, min(matches, key=lambda item: item[0])[2])
        if len(source_matches) > 1:
            source_ambiguous += 1
        if source_matches:
            inverse_point = min(source_matches, key=lambda item: item[0])[2]
            round_trip_distance = length3(sub3(source_point, inverse_point))
            round_trip_errors.append(round_trip_distance / bounds_diagonal)
            if round_trip_distance <= 1e-5 * bounds_diagonal:
                mutual_nearest += 1
        _, target_face, target_point = min(matches, key=lambda item: item[0])
        position_errors.append(math.sqrt(min(item[0] for item in matches)) / bounds_diagonal)
        cosine = max(-1.0, min(1.0, dot3(face["normal"], target_face["normal"])))
        normal_angles.append(math.degrees(math.acos(cosine)))
        jacobian = ((target_face["geom_area"] / target_face["uv_area"]) /
                    (face["geom_area"] / face["uv_area"]))
        jacobians.append(jacobian)
        log2_jacobians.append(math.log2(jacobian))

    coverage = supported / sample_count if sample_count else 0.0
    return {
        "source": str(source["path"]),
        "target": str(target["path"]),
        "source_triangles": source["triangle_count"],
        "target_triangles": target["triangle_count"],
        "samples": sample_count,
        "seed": seed,
        "uv_domain_coverage_estimate": coverage,
        "coverage_standard_error": math.sqrt(coverage * (1.0 - coverage) / sample_count)
        if sample_count else None,
        "coverage_miss_rate_upper_95_if_no_misses": 1.0 - 0.05 ** (1.0 / sample_count)
        if supported == sample_count and sample_count else None,
        "target_ambiguous_uv_hit_fraction_of_all_samples": target_ambiguous / sample_count
        if sample_count else None,
        "source_ambiguous_round_trip_fraction_of_all_supported_samples": source_ambiguous / supported
        if supported else None,
        "mutual_nearest_round_trip_fraction_of_all_supported_samples": mutual_nearest / supported
        if supported else None,
        "normalized_round_trip_displacement": quantiles(round_trip_errors),
        "normalized_world_displacement": quantiles(position_errors),
        "geometric_normal_angle_degrees": quantiles(normal_angles),
        "area_jacobian_target_over_source": quantiles(jacobians),
        "log2_area_jacobian": quantiles(log2_jacobians),
        "interpretation_limit": "uniform source-UV-area nearest-map proxy; not a camera/path/ReSTIR distribution or proof of a globally partial-bijective map",
    }


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="finest/reference LOD OBJ")
    parser.add_argument("--target", type=Path, action="append", required=True,
                        help="coarser LOD OBJ; may be repeated")
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.samples <= 0 or args.grid_resolution <= 0:
        parser.error("--samples and --grid-resolution must be positive")
    source = prepare(args.source)
    targets = [prepare(path) for path in args.target]
    rows = [measure(source, target, args.samples, args.seed + i, args.grid_resolution)
            for i, target in enumerate(targets)]
    data = {
        "schema": 1,
        "scope": "UV-domain surface-map proxy; not a path tracer or a ReSTIR estimator",
        "source_sha256": sha256(args.source),
        "target_sha256": {str(path): sha256(path) for path in args.target},
        "script_sha256": sha256(Path(__file__)),
        "results": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
