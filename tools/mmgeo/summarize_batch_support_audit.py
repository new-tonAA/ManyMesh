#!/usr/bin/env python3
"""Summarize per-view support-batching audits across mesh assets."""

import argparse
import json
from pathlib import Path


def ratio(numerator, denominator):
    if denominator == 0.0:
        return float("inf") if numerator > 0.0 else 1.0
    return numerator / denominator


def summarize(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    frames = report["frames"]
    projected_conflicts = [
        100.0 * frame["projectedBoxConflictFractionAmongTopologyCompatiblePairs"]
        for frame in frames
    ]
    residual_conflicts = [
        100.0 * frame["actualDeltaSupportConflictFractionAmongTopologyCompatiblePairs"]
        for frame in frames
    ]
    screen_counts = []
    screen_ratios = []
    screen_absolute_increases = []
    residual_counts = []
    residual_ratios = []
    residual_absolute_increases = []
    residual_additivity = []
    residual_valid = []
    zero_mip_gaps = []
    for frame in frames:
        exact = frame["exactMilpSchedules"]
        screen = exact["screenAwareMaximum"]
        screen_match = exact["topologyOnlyAtScreenMaximumCardinality"]
        residual = exact["actualDeltaSupportMaximum"]
        residual_match = exact["topologyOnlyAtActualDeltaMaximumCardinality"]
        screen_counts.append(screen["optimization"]["maximumCardinality"])
        screen_error = screen["actualComposite"]["fullCompositeRerasterSse"]
        screen_match_error = screen_match["actualComposite"]["fullCompositeRerasterSse"]
        screen_ratios.append(ratio(screen_error, screen_match_error))
        screen_absolute_increases.append(screen_error - screen_match_error)
        residual_counts.append(residual["optimization"]["maximumCardinality"])
        residual_actual = residual["actualComposite"]
        residual_error = residual_actual["fullCompositeRerasterSse"]
        residual_match_error = residual_match["actualComposite"]["fullCompositeRerasterSse"]
        residual_ratios.append(ratio(residual_error, residual_match_error))
        residual_absolute_increases.append(residual_error - residual_match_error)
        residual_additivity.append(abs(residual_actual["rerasterMinusAdditiveSse"]))
        residual_valid.append(residual_actual["basicTopologyValid"]
                              and residual_actual["orientationValid"])
        for key in ("screenAwareMaximum", "actualDeltaSupportMaximum"):
            optimization = exact[key]["optimization"]
            zero_mip_gaps.append(optimization["minimumCostMipGap"] == 0.0)
            if optimization["optimalMaximumCardinalityProven"]:
                zero_mip_gaps.append(optimization["maximumCardinalityMipGap"] == 0.0)

    return {
        "asset": Path(path).name.split("-")[0],
        "views": len(frames),
        "projectedBoxConflictPercentRange": [min(projected_conflicts), max(projected_conflicts)],
        "projectedBoxMaxBatchRange": [min(screen_counts), max(screen_counts)],
        "residualSupportConflictPercentRange": [min(residual_conflicts), max(residual_conflicts)],
        "residualSupportMaxBatchRange": [min(residual_counts), max(residual_counts)],
        "projectedBoxErrorRatioRangeAtMatchedCount": [min(screen_ratios), max(screen_ratios)],
        "projectedBoxAbsoluteSseIncreaseRangeAtMatchedCount": [
            min(screen_absolute_increases), max(screen_absolute_increases)],
        "residualSupportErrorRatioRangeAtMatchedCount": [min(residual_ratios), max(residual_ratios)],
        "residualSupportAbsoluteSseIncreaseRangeAtMatchedCount": [
            min(residual_absolute_increases), max(residual_absolute_increases)],
        "maxResidualSupportAdditivityAbsoluteError": max(residual_additivity),
        "allResidualSupportCompositesPassTopologyAndOrientation": all(residual_valid),
        "allReportedMilpGapsZero": all(zero_mip_gaps),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.reports], indent=2))


if __name__ == "__main__":
    main()
