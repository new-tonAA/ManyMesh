#!/usr/bin/env python3
"""Paired comparison of cross-minus-same ReSTIR error for two target LODs."""

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


def read_single_row(path):
    with path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if len(manifest.get("rows", [])) != 1:
        raise ValueError(f"expected exactly one contrast in {path}")
    return manifest, manifest["rows"][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--alternative", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261201)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_replicates < 100:
        parser.error("bootstrap-replicates must be >= 100")

    baseline_manifest, baseline = read_single_row(args.baseline)
    alternative_manifest, alternative = read_single_row(args.alternative)
    matching_fields = (
        "name", "seed", "batches", "batchSize", "uniformProposalFloor",
        "shading", "viewCount", "sourceSha256", "referenceSamplesPerFace",
        "referenceReplicates",
    )
    mismatches = [field for field in matching_fields
                  if baseline.get(field) != alternative.get(field)]
    if mismatches:
        raise ValueError("manifests do not share the same experiment setup: " +
                         ", ".join(mismatches))
    if baseline_manifest.get("scriptSha256") != alternative_manifest.get("scriptSha256"):
        raise ValueError("manifests were produced by different driver revisions")
    if (baseline.get("sameLod", {}).get("estimatedExactRgbIntegral") !=
            alternative.get("sameLod", {}).get("estimatedExactRgbIntegral")):
        raise ValueError("source reference integrals differ; common-random pairing is invalid")

    baseline_deltas = baseline.get("batchDeltaValues")
    alternative_deltas = alternative.get("batchDeltaValues")
    if (baseline_deltas is None or alternative_deltas is None or
            len(baseline_deltas) != len(alternative_deltas)):
        raise ValueError("both manifests must contain equally sized batchDeltaValues")
    differences = [alternative_value - baseline_value
                   for baseline_value, alternative_value
                   in zip(baseline_deltas, alternative_deltas)]
    mean = statistics.fmean(differences)
    standard_error = statistics.stdev(differences) / (len(differences) ** 0.5)
    result = {
        "method": "paired common-random change in cross-minus-same normalized MSE",
        "interpretation": "negative means the alternative target lowers the cross-LOD penalty",
        "baselineTargetSha256": baseline.get("targetSha256"),
        "alternativeTargetSha256": alternative.get("targetSha256"),
        "seed": baseline.get("seed"),
        "batches": baseline.get("batches"),
        "batchSize": baseline.get("batchSize"),
        "uniformProposalFloor": baseline.get("uniformProposalFloor"),
        "baselineDeltaMean": baseline.get("pairedRelativeMseDifference", {}).get("mean"),
        "alternativeDeltaMean": alternative.get("pairedRelativeMseDifference", {}).get("mean"),
        "meanAlternativeMinusBaseline": mean,
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
        "baselineManifest": str(args.baseline),
        "alternativeManifest": str(args.alternative),
        "scriptSha256": baseline_manifest.get("scriptSha256"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
