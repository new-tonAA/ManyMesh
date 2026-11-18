#!/usr/bin/env python3
"""Summarize full-budget spatial-retry policy curves from audit JSON files."""

import argparse
import json
from pathlib import Path


POLICIES = (
    "rejectsPerKInput",
    "attributeRejectsPerKInput",
    "topologyRejectsPerKInput",
    "geometryRejectsPerKInput",
    "smallestWorkFirst",
)


def summarize(paths):
    levels = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        for level in report["levels"]:
            frontier = level["fullBudgetFrontier"]
            if not frontier["eligibleWork"]:
                continue
            points = frontier["policies"]
            oracle_area = sum(point["oracleSaved"]
                    for point in points["smallestWorkFirst"]["points"])
            row = {
                "asset": path.stem,
                "level": level["level"],
                "retryWork": level["retryInputTriangleWork"],
                "eligibleWork": frontier["eligibleWork"],
                "oracleIntegratedSavedTriangles": oracle_area,
                "policies": {},
            }
            for name in POLICIES:
                policy = points[name]
                policy_area = sum(point["trianglesSaved"] for point in policy["points"])
                positive = [point for point in policy["points"] if point["oracleSaved"] > 0]
                row["policies"][name] = {
                    "integratedSavedTriangleRatioToOracle": policy_area / oracle_area
                        if oracle_area else 1.0,
                    "oracleMatchRateWhereOraclePositive": sum(
                        point["trianglesSaved"] == point["oracleSaved"]
                        for point in positive) / len(positive) if positive else 1.0,
                    "qualityValidBudgetFraction": sum(
                        point["valid"] for point in policy["points"])
                        / len(policy["points"]),
                    "integratedSavedTriangles": policy_area,
                }
            levels.append(row)

    totals = {name: 0 for name in POLICIES}
    oracle_total = sum(row["oracleIntegratedSavedTriangles"] for row in levels)
    comparisons = {name: {"beatsCost": 0, "tiesCost": 0, "losesToCost": 0}
            for name in POLICIES[:-1]}
    for row in levels:
        cost = row["policies"]["smallestWorkFirst"]["integratedSavedTriangles"]
        for name in POLICIES:
            value = row["policies"][name]["integratedSavedTriangles"]
            totals[name] += value
            if name != "smallestWorkFirst":
                key = "beatsCost" if value > cost else "losesToCost" if value < cost else "tiesCost"
                comparisons[name][key] += 1
    return {
        "schema": 1,
        "scope": "Retrospective schema-1 local retry packages; 101 equal caps from zero to total all-retry input-triangle work; each level normalized over its own caps; oracle sees frozen outcomes; no raster quality, wall time, peak memory, or held-out assets.",
        "levelsWithOracleEligiblePackages": len(levels),
        "integratedRatioToOracleAcrossLevels": {
            name: totals[name] / oracle_total if oracle_total else 1.0
            for name in POLICIES
        },
        "comparisonsAgainstSmallestWorkFirst": comparisons,
        "levels": levels,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    reports = sorted(args.reports_dir.glob("*.json"))
    if not reports:
        parser.error(f"no audit JSON reports in {args.reports_dir}")
    result = summarize(reports)
    payload = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
