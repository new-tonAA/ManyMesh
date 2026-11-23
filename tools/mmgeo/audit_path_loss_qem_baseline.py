#!/usr/bin/env python3
"""Audit whether existing QEM priorities predict exact path-loss candidate rankings."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def pairwise_accuracy(rows, score_key, reverse=False):
    comparable = correct = 0
    for i, first in enumerate(rows):
        for second in rows[i + 1:]:
            a, b = float(first["exactEnergy"]), float(second["exactEnergy"])
            scale = max(abs(a), abs(b))
            if abs(a - b) <= max(1e-12, 1e-6 * scale):
                continue
            pa, pb = float(first[score_key]), float(second[score_key])
            comparable += 1
            if pa == pb:
                correct += 0.5
                continue
            predicted_a_better = pa > pb if reverse else pa < pb
            exact_a_better = a < b
            correct += predicted_a_better == exact_a_better
    return {"pairs": comparable, "correct": correct,
            "accuracy": correct / comparable if comparable else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=Path("out/filter-real-candidates"))
    parser.add_argument("--results", type=Path, default=Path("out"))
    parser.add_argument("--out", type=Path,
                        default=Path("out/path-loss-qem-baseline-audit.json"))
    args = parser.parse_args()

    captures = {}
    for path in sorted(args.captures.glob("*.json")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        captures[digest] = (path, json.loads(path.read_text(encoding="utf-8")))

    seen = set()
    groups = []
    unmatched = []
    for path in sorted(args.results.glob("shared-envelope-raster*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        digest = result.get("captureSha256")
        if digest not in captures:
            unmatched.append(path.name)
            continue
        key = (digest, tuple(result.get("candidateIds", ())),
               tuple(result.get("path", ())), tuple(result.get("tileRect", ())),
               result.get("cameraAngle"), result.get("panAngle", 0.0),
               tuple(sorted({int(row["steps"])
                             for row in result.get("candidateRasterRows", [])})))
        if key in seen:
            continue
        seen.add(key)
        capture_path, capture = captures[digest]
        unit_index = result.get("unitIndex", 0)
        candidates = capture["units"][unit_index]["candidates"]
        raster_rows = result.get("candidateRasterRows", [])
        min_steps = min((int(row["steps"]) for row in raster_rows), default=-1)
        max_steps = max((int(row["steps"]) for row in raster_rows), default=-1)
        label_by_id = {int(row["candidateId"]): {
            "exactEnergy": float(row["exactEnergy"]),
            "coarseRasterEnergy": float(row["rasterEnergy"])}
            for row in raster_rows if int(row["steps"]) == min_steps}
        exact_by_id = {int(row["candidateId"]): float(row["exactEnergy"])
                       for row in raster_rows if int(row["steps"]) == max_steps}
        rows = [{"candidateId": candidate_id,
                 "priority": float(candidates[candidate_id]["priority"]),
                 "exactEnergy": exact_by_id[candidate_id],
                 "coarseRasterEnergy": label_by_id[candidate_id]["coarseRasterEnergy"]}
                for candidate_id in result.get("candidateIds", ())
                if candidate_id < len(candidates) and candidate_id in label_by_id and
                candidate_id in exact_by_id]
        if len(rows) >= 2:
            best_energy = min(row["exactEnergy"] for row in rows)
            best_tolerance = max(1e-12, 1e-6 * abs(best_energy))
            exact_winners = [row["candidateId"] for row in rows
                             if row["exactEnergy"] <= best_energy + best_tolerance]
            best_priority = min(row["priority"] for row in rows)
            qem_winners = [row["candidateId"] for row in rows
                           if row["priority"] == best_priority]
            exact_seconds = (float(result.get("commonEventSetupSeconds", 0.0)) +
                             float(result.get("candidateExactSetupAndIntegrationSeconds", 0.0)))
            raster_seconds = float(result.get("denseRasterResults", {}).get(
                str(min_steps), {}).get("denseTotalSeconds", 0.0))
            raster_quality = result.get("denseRasterResults", {}).get(str(min_steps), {})
            informative = pairwise_accuracy(rows, "priority")["pairs"] > 0
            shortlist = {}
            ranked = sorted(rows, key=lambda row: row["coarseRasterEnergy"])
            energy_range = max(row["exactEnergy"] for row in rows) - best_energy
            for k in (1, 2, 4, 8):
                top = ranked[:min(k, len(ranked))]
                reranked_energy = min(row["exactEnergy"] for row in top)
                shortlist[str(k)] = {
                    "recallExactBest": bool(set(row["candidateId"] for row in top) &
                                             set(exact_winners)),
                    "normalizedRegretAfterExactRerank":
                    max(0.0, reranked_energy - best_energy) / energy_range
                    if informative and energy_range > best_tolerance else 0.0,
                    "estimatedHybridSeconds": raster_seconds + exact_seconds -
                    float(result.get("candidateExactSetupAndIntegrationSeconds", 0.0)) +
                    float(result.get("candidateExactSetupAndIntegrationSeconds", 0.0)) *
                    min(k, len(rows)) / len(rows),
                }
            groups.append({"result": path.name, "capture": capture_path.name,
                           "candidateCount": len(rows), "rasterSteps": min_steps,
                           "exactSeconds": exact_seconds,
                           "coarseRasterSeconds": raster_seconds,
                           "exactToRasterSpeedRatio": exact_seconds / raster_seconds
                           if raster_seconds > 0 else None,
                           "sumExactEnergy": float(raster_quality.get("sumExactEnergy", 0.0)),
                           "sumAbsoluteEnergyError": float(
                               raster_quality.get("sumAbsoluteEnergyError", 0.0)),
                           "maxRelativeEnergyError": float(
                               raster_quality.get("maxRelativeEnergyError", 0.0)),
                           "coarseToExactShortlist": shortlist,
                           "priorityLower": pairwise_accuracy(rows, "priority"),
                           "priorityHigher": pairwise_accuracy(rows, "priority", reverse=True),
                           "coarseRaster": pairwise_accuracy(rows, "coarseRasterEnergy"),
                           "exactWinnerCount": len(exact_winners),
                           "qemBestTieSetOverlapsExact": bool(set(qem_winners) & set(exact_winners)),
                           "exactWinnerIds": exact_winners,
                           "qemBestIds": qem_winners})

    raster_by_steps = {}
    for step in sorted({group["rasterSteps"] for group in groups}):
        step_groups = [group for group in groups if group["rasterSteps"] == step]
        pair_count = sum(group["coarseRaster"]["pairs"] for group in step_groups)
        correct = sum(group["coarseRaster"]["correct"] for group in step_groups)
        qem_correct = sum(group["priorityLower"]["correct"] for group in step_groups)
        qem_pairs = sum(group["priorityLower"]["pairs"] for group in step_groups)
        timed = [group for group in step_groups if group["coarseRasterSeconds"] > 0]
        informative_groups = [group for group in step_groups
                              if group["priorityLower"]["pairs"] > 0]
        shortlist_summary = {}
        for k in (1, 2, 4, 8):
            entries = [group["coarseToExactShortlist"][str(k)]
                       for group in informative_groups]
            shortlist_summary[str(k)] = {
                "exactBestRecall": sum(entry["recallExactBest"] for entry in entries) /
                len(entries) if entries else None,
                "meanNormalizedRegretAfterExactRerank": statistics.mean(
                    entry["normalizedRegretAfterExactRerank"] for entry in entries)
                    if entries else None,
                "medianEstimatedHybridSeconds": statistics.median(
                    entry["estimatedHybridSeconds"] for entry in entries)
                    if entries else None,
            }
        raster_by_steps[str(step)] = {"groupCount": len(step_groups), "pairs": pair_count,
                                      "correct": correct,
                                      "accuracy": correct / pair_count if pair_count else None,
                                      "qemAccuracySameGroups": qem_correct / qem_pairs
                                      if qem_pairs else None,
                                      "medianExactSeconds": statistics.median(
                                          [group["exactSeconds"] for group in timed])
                                      if timed else None,
                                      "medianRasterSeconds": statistics.median(
                                          [group["coarseRasterSeconds"] for group in timed])
                                      if timed else None,
                                      "medianExactToRasterSpeedRatio": statistics.median(
                                          [group["exactToRasterSpeedRatio"] for group in timed])
                                      if timed else None,
                                      "aggregateRelativeEnergyError": sum(
                                          group["sumAbsoluteEnergyError"] for group in step_groups) /
                                      max(sum(group["sumExactEnergy"] for group in step_groups), 1e-30),
                                      "worstGroupRelativeEnergyError": max(
                                          (group["maxRelativeEnergyError"] for group in step_groups),
                                          default=0.0),
                                      "informativeGroupCount": len(informative_groups),
                                      "coarseToExactShortlist": shortlist_summary}
    output = {"scope": "exact path-loss screens versus QEM and minimum-sample raster rankings",
              "warning": "small, correlated pilot pools; these are not generalization results",
              "rasterAccuracyByMinimumSampleCount": raster_by_steps,
              "groups": groups, "unmatchedResults": unmatched}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"groupCount": len(groups), "unmatchedResultCount": len(unmatched),
                      "rasterAccuracyByMinimumSampleCount": raster_by_steps}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
