#!/usr/bin/env python3
"""Sample target UV-overlap multiplicity against ReSTIR-LoD's bounded hit list."""

import argparse
import bisect
import hashlib
import importlib.util
import json
import random
from pathlib import Path


def load_transport_helper():
    path = Path(__file__).with_name("measure_lod_uv_transport.py")
    spec = importlib.util.spec_from_file_location("restir_uv_transport", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def quantile(sorted_values, q):
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    alpha = position - lower
    return sorted_values[lower] * (1.0 - alpha) + sorted_values[upper] * alpha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--grid-resolution", type=int, default=64)
    parser.add_argument("--max-retained-hits", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.samples <= 0 or args.grid_resolution <= 0 or args.max_retained_hits <= 0:
        parser.error("samples, grid-resolution, and max-retained-hits must be positive")

    transport = load_transport_helper()
    source = transport.prepare(args.source)
    target = transport.prepare(args.target)
    transport.build_uv_bins(source, args.grid_resolution)
    transport.build_uv_bins(target, args.grid_resolution)

    rng = random.Random(args.seed)
    cumulative, total_uv_area = [], 0.0
    for face in source["faces"]:
        total_uv_area += face["uv_area"]
        cumulative.append(total_uv_area)

    hit_counts = []
    for _ in range(args.samples):
        face_index = bisect.bisect_left(cumulative, rng.random() * total_uv_area)
        face_index = min(face_index, len(source["faces"]) - 1)
        face = source["faces"][face_index]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1.0:
            r1, r2 = 1.0 - r1, 1.0 - r2
        bary = (1.0 - r1 - r2, r1, r2)
        uv_point = transport.add_weighted(face["uv"], bary)
        source_point = transport.add_weighted(face["p"], bary)
        hit_counts.append(len(transport.surface_matches(target, uv_point, source_point)))

    ordered = sorted(hit_counts)
    misses = sum(count == 0 for count in hit_counts)
    over_capacity = sum(count > args.max_retained_hits for count in hit_counts)
    data = {
        "schema": 1,
        "scope": "sampled target UV-hit multiplicity under source-UV-area sampling; not a global maximum or renderer ray-query result",
        "source": str(args.source),
        "target": str(args.target),
        "source_sha256": sha256(args.source),
        "target_sha256": sha256(args.target),
        "helper_sha256": sha256(Path(__file__).with_name("measure_lod_uv_transport.py")),
        "script_sha256": sha256(Path(__file__)),
        "samples": args.samples,
        "seed": args.seed,
        "grid_resolution": args.grid_resolution,
        "retained_hit_limit": args.max_retained_hits,
        "source_triangles": source["triangle_count"],
        "target_triangles": target["triangle_count"],
        "unsupported_samples": misses,
        "unsupported_fraction": misses / args.samples,
        "hit_multiplicity_quantiles": {
            str(q): quantile(ordered, q) for q in (0.5, 0.95, 0.99, 1.0)
        },
        "samples_over_retained_hit_limit": over_capacity,
        "fraction_over_retained_hit_limit": over_capacity / args.samples,
        "one_sided_95_upper_bound_if_no_overflow":
            1.0 - 0.05 ** (1.0 / args.samples) if over_capacity == 0 else None,
        "interpretation_limit": "finite UV-area samples do not prove that the full UV domain has no higher multiplicity; material alpha testing and the GPU ray-query path are not modeled",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: data[key] for key in (
        "samples", "unsupported_samples", "hit_multiplicity_quantiles",
        "samples_over_retained_hit_limit", "fraction_over_retained_hit_limit",
        "one_sided_95_upper_bound_if_no_overflow")}, indent=2))


if __name__ == "__main__":
    main()
