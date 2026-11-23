#!/usr/bin/env python3
"""Compare exact path-event scores with each raster sample budget in saved screens."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    output = []
    for path in args.results:
        data = json.loads(path.read_text(encoding="utf-8"))
        by_steps = {}
        for row in data["candidateRasterRows"]:
            by_steps.setdefault(int(row["steps"]), []).append(row)
        step_results = {}
        for steps, rows in sorted(by_steps.items()):
            pairs = correct = 0
            for i, first in enumerate(rows):
                for second in rows[i + 1:]:
                    a, b = first["exactEnergy"], second["exactEnergy"]
                    tol = max(1e-12, 1e-6 * max(abs(a), abs(b)))
                    if abs(a - b) <= tol:
                        continue
                    pairs += 1
                    pred_a_better = first["rasterEnergy"] < second["rasterEnergy"]
                    correct += pred_a_better == (a < b)
            quality = data["denseRasterResults"][str(steps)]
            exact_min = min(row["exactEnergy"] for row in rows)
            tie_tolerance = max(1e-12, 1e-6 * abs(exact_min))
            exact_best_ids = [row["candidateId"] for row in rows
                              if row["exactEnergy"] <= exact_min + tie_tolerance]
            raster_ranked = sorted(rows, key=lambda row: row["rasterEnergy"])
            energy_range = max(row["exactEnergy"] for row in rows) - exact_min
            step_results[str(steps)] = {
                "nonTiedPairs": pairs,
                "pairwiseAccuracy": correct / pairs if pairs else None,
                "sumExactEnergy": quality["sumExactEnergy"],
                "sumAbsoluteEnergyError": quality["sumAbsoluteEnergyError"],
                "aggregateRelativeEnergyError": quality["sumAbsoluteEnergyError"] /
                max(quality["sumExactEnergy"], 1e-30),
                "maxRelativeEnergyError": quality["maxRelativeEnergyError"],
                "rasterSeconds": quality["denseTotalSeconds"],
                "exactBestIds": exact_best_ids,
                "rasterTop1Ids": [row["candidateId"] for row in raster_ranked
                                  if row["rasterEnergy"] == raster_ranked[0]["rasterEnergy"]],
                "topKExactBestRecall": {
                    str(k): bool(set(row["candidateId"] for row in raster_ranked[:k]) &
                                 set(exact_best_ids))
                    for k in (1, 2, 4, 8)},
                "top1RangeNormalizedRegret":
                max(0.0, raster_ranked[0]["exactEnergy"] - exact_min) / energy_range
                if energy_range > tie_tolerance else 0.0,
            }
        output.append({"result": path.name, "captureSha256": data["captureSha256"],
                       "panAngle": data.get("panAngle", 0.0),
                       "panDirection": data.get("panDirection", [1.0, 0.0]),
                       "path": data["path"], "exactSeconds":
                       data["commonEventSetupSeconds"] +
                       data["candidateExactSetupAndIntegrationSeconds"],
                       "candidateIds": data["candidateIds"], "rasterBySteps": step_results})
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
