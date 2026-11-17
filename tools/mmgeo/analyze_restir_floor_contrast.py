#!/usr/bin/env python3
"""Analyze a common-random-number uniform-proposal-floor contrast."""

import argparse
import json
import random
import statistics
from pathlib import Path


def quantile(values, q):
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    alpha = position - lower
    return ordered[lower] * (1.0 - alpha) + ordered[upper] * alpha


def bootstrap_interval(values, seed, replicates):
    rng = random.Random(seed)
    count = len(values)
    means = [statistics.fmean(values[rng.randrange(count)] for _ in range(count))
             for _ in range(replicates)]
    return [quantile(means, 0.025), quantile(means, 0.975)]


def read_manifest(path):
    with path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if len(manifest.get("rows", [])) != 1:
        raise ValueError(f"expected exactly one contrast in {path}")
    return manifest, manifest["rows"][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--low-floor", type=Path, required=True)
    parser.add_argument("--high-floor", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261128)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_replicates < 100:
        parser.error("bootstrap-replicates must be >= 100")

    low_manifest, low = read_manifest(args.low_floor)
    high_manifest, high = read_manifest(args.high_floor)
    matching_fields = (
        "name", "seed", "batches", "batchSize", "shading", "viewCount",
        "sourceSha256", "targetSha256", "referenceSamplesPerFace",
        "referenceReplicates",
    )
    mismatches = [field for field in matching_fields if low.get(field) != high.get(field)]
    if mismatches:
        raise ValueError("manifests do not share the same experiment setup: " +
                         ", ".join(mismatches))
    if low_manifest.get("scriptSha256") != high_manifest.get("scriptSha256"):
        raise ValueError("manifests were produced by different driver revisions")
    if (low.get("sameLod", {}).get("estimatedExactRgbIntegral") !=
            high.get("sameLod", {}).get("estimatedExactRgbIntegral") or
            low.get("crossLod", {}).get("estimatedExactRgbIntegral") !=
            high.get("crossLod", {}).get("estimatedExactRgbIntegral")):
        raise ValueError("reference integrals differ; cannot use paired floor comparison")

    low_deltas = low.get("batchDeltaValues")
    high_deltas = high.get("batchDeltaValues")
    if low_deltas is None or high_deltas is None or len(low_deltas) != len(high_deltas):
        raise ValueError("both manifests must contain equally sized batchDeltaValues")
    differences = [high_value - low_value
                   for low_value, high_value in zip(low_deltas, high_deltas)]
    mean = statistics.fmean(differences)
    standard_error = statistics.stdev(differences) / (len(differences) ** 0.5)
    result = {
        "method": "paired common-random-number difference in cross-minus-same normalized MSE",
        "lowFloor": low.get("uniformProposalFloor"),
        "highFloor": high.get("uniformProposalFloor"),
        "seed": low.get("seed"),
        "batches": low.get("batches"),
        "batchSize": low.get("batchSize"),
        "meanHighMinusLow": mean,
        "standardError": standard_error,
        "normal95PercentInterval": [mean - 1.96 * standard_error,
                                    mean + 1.96 * standard_error],
        "bootstrapMean95PercentInterval": bootstrap_interval(
            differences, args.seed, args.bootstrap_replicates),
        "bootstrapReplicates": args.bootstrap_replicates,
        "differenceQuantiles": {str(q): quantile(differences, q)
                                for q in (0.01, 0.05, 0.5, 0.95, 0.99)},
        "minimum": min(differences),
        "maximum": max(differences),
        "fractionBelowZero": sum(value < 0.0 for value in differences) / len(differences),
        "lowFloorManifest": str(args.low_floor),
        "highFloorManifest": str(args.high_floor),
        "scriptSha256": low_manifest.get("scriptSha256"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
