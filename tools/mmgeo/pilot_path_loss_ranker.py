#!/usr/bin/env python3
"""Exploratory leave-one-asset-out diagnostic for a tiny path-loss MLP ranker."""

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def compare(rows, values, ascending=True):
    pairs = correct = 0.0
    for i, first in enumerate(rows):
        for j in range(i + 1, len(rows)):
            a, b = first["exactEnergy"], rows[j]["exactEnergy"]
            tol = max(1e-12, 1e-6 * max(abs(a), abs(b)))
            if abs(a - b) <= tol:
                continue
            pairs += 1.0
            pa, pb = values[i], values[j]
            if pa == pb:
                correct += 0.5
            else:
                pred_a_better = pa < pb if ascending else pa > pb
                correct += pred_a_better == (a < b)
    return pairs, correct


def normalized_rank_targets(rows):
    targets = []
    denom = max(1, len(rows) - 1)
    for row in rows:
        value = row["exactEnergy"]
        lower = ties = 0
        for other in rows:
            tol = max(1e-12, 1e-6 * max(abs(value), abs(other["exactEnergy"])))
            delta = other["exactEnergy"] - value
            if delta < -tol:
                lower += 1
            elif abs(delta) <= tol:
                ties += 1
        targets.append((lower + 0.5 * (ties - 1)) / denom)
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path,
                        default=Path("out/pathloss-captures/path-loss-features.json"))
    parser.add_argument("--raster-steps", type=int, default=None,
                        help="optionally restrict groups to this raster path-sample count")
    parser.add_argument("--target", choices=("log_loss", "group_rank"), default="log_loss")
    parser.add_argument("--include-coarse-raster", action="store_true",
                        help="include the minimum-sample raster energy as a model feature")
    parser.add_argument("--out", type=Path,
                        default=Path("out/pathloss-captures/mlp-loao-pilot.json"))
    args = parser.parse_args()

    dataset = json.loads(args.features.read_text(encoding="utf-8"))
    by_group = defaultdict(list)
    for row in dataset["rows"]:
        if args.raster_steps is None or int(row["rasterSteps"]) == args.raster_steps:
            by_group[int(row["group"])].append(row)
    if not by_group:
        parser.error(f"no groups use raster-steps={args.raster_steps}")
    groups = list(by_group.values())
    feature_names = [name for name in groups[0][0]["features"]
                     if args.include_coarse_raster or name != "coarse_raster_energy"]
    result_groups = []
    total_pairs = total_qem_correct = total_raster_correct = total_mlp_correct = 0.0
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    assets = sorted({rows[0]["capture"] for rows in groups})
    for held_out in assets:
        train_groups = [rows for rows in groups if rows[0]["capture"] != held_out]
        test_groups = [rows for rows in groups if rows[0]["capture"] == held_out]
        if not test_groups:
            continue
        train_rows = []
        y_train_values = []
        informative_train_groups = 0
        for rows in train_groups:
            if args.target == "group_rank":
                targets = normalized_rank_targets(rows)
                if max(targets, default=0.5) - min(targets, default=0.5) <= 1e-9:
                    continue
                informative_train_groups += 1
                train_rows.extend(rows)
                y_train_values.extend(targets)
            else:
                train_rows.extend(rows)
                y_train_values.extend(np.log10(
                    np.asarray([row["exactEnergy"] for row in rows]) + 1e-12))
                informative_train_groups += 1
        if not train_rows:
            continue
        x_train = np.asarray([[row["features"][name] for name in feature_names]
                              for row in train_rows], dtype=np.float64)
        y_train = np.asarray(y_train_values, dtype=np.float64)
        model = make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(16, 8), activation="relu", solver="adam",
                         alpha=1e-2, learning_rate_init=2e-3, max_iter=400,
                         tol=1e-4, random_state=17))
        model.fit(x_train, y_train)
        for rows in test_groups:
            x_test = np.asarray([[row["features"][name] for name in feature_names]
                                 for row in rows], dtype=np.float64)
            predicted = model.predict(x_test)
            qem = np.asarray([row["features"]["qem_priority"] for row in rows])
            coarse_raster = np.asarray([row["features"]["coarse_raster_energy"]
                                        for row in rows])
            pairs, qem_correct = compare(rows, qem, ascending=True)
            _, raster_correct = compare(rows, coarse_raster, ascending=True)
            _, mlp_correct = compare(rows, predicted, ascending=True)
            if pairs:
                total_pairs += pairs
                total_qem_correct += qem_correct
                total_raster_correct += raster_correct
                total_mlp_correct += mlp_correct
            best_energy = min(row["exactEnergy"] for row in rows)
            tol = max(1e-12, 1e-6 * abs(best_energy))
            best_ids = [row["candidateId"] for row in rows
                        if row["exactEnergy"] <= best_energy + tol]
            qem_best = min(row["features"]["qem_priority"] for row in rows)
            qem_best_rows = [row for row in rows
                             if row["features"]["qem_priority"] == qem_best]
            qem_best_ids = [row["candidateId"] for row in qem_best_rows]
            raster_best = min(row["features"]["coarse_raster_energy"] for row in rows)
            raster_best_ids = [row["candidateId"] for row in rows
                               if row["features"]["coarse_raster_energy"] == raster_best]
            mlp_best_row = rows[int(np.argmin(predicted))]
            qem_tie_energies = [row["exactEnergy"] for row in qem_best_rows]
            raster_tie_energies = [row["exactEnergy"] for row in rows
                                   if row["features"]["coarse_raster_energy"] == raster_best]
            mlp_regret = max(0.0, mlp_best_row["exactEnergy"] - best_energy)
            qem_best_regret = max(0.0, min(qem_tie_energies) - best_energy)
            raster_best_regret = max(0.0, min(raster_tie_energies) - best_energy)
            energy_range = max(row["exactEnergy"] for row in rows) - best_energy
            result_groups.append({"asset": held_out, "result": rows[0]["result"],
                                  "candidateCount": len(rows), "nonTiedPairs": int(pairs),
                                  "trainingInformativeGroups": informative_train_groups,
                                  "qemPairAccuracy": qem_correct / pairs if pairs else None,
                                  "coarseRasterPairAccuracy": raster_correct / pairs
                                  if pairs else None,
                                  "mlpPairAccuracy": mlp_correct / pairs if pairs else None,
                                  "exactBestIds": best_ids, "qemBestIds": qem_best_ids,
                                  "coarseRasterBestIds": raster_best_ids,
                                  "mlpBestIds": [mlp_best_row["candidateId"]],
                                  "exactBestEnergy": best_energy,
                                  "mlpChosenEnergy": mlp_best_row["exactEnergy"],
                                  "mlpAbsoluteRegret": mlp_regret,
                                  "qemTieSetBestAbsoluteRegret": qem_best_regret,
                                  "coarseRasterTieSetBestAbsoluteRegret": raster_best_regret,
                                  "mlpRangeNormalizedRegret": mlp_regret / energy_range
                                  if energy_range > tol else None,
                                  "qemRangeNormalizedOptimisticRegret": qem_best_regret / energy_range
                                  if energy_range > tol else None,
                                  "coarseRasterRangeNormalizedOptimisticRegret": raster_best_regret /
                                  energy_range if energy_range > tol else None,
                                  "qemTieSetMeanEnergy": float(np.mean(qem_tie_energies)),
                                  "qemTieSetWorstEnergy": max(qem_tie_energies),
                                  "qemBestOverlap": bool(set(best_ids) & set(qem_best_ids)),
                                  "coarseRasterBestOverlap": bool(set(best_ids) &
                                                                   set(raster_best_ids)),
                                  "mlpBestOverlap": bool(best_ids and
                                                         mlp_best_row["candidateId"] in best_ids)})

    evaluated_groups = [row for row in result_groups if row["nonTiedPairs"]]
    output = {"scope": "exploratory leave-one-capture-asset-out path-loss MLP",
              "warning": "tiny correlated pilot set; no evidence of generalization or speedup",
              "features": feature_names, "rasterSteps": args.raster_steps,
              "target": args.target, "includesCoarseRasterFeature": args.include_coarse_raster,
              "assetCount": len(assets),
              "groupCount": len(groups), "rowCount": len(dataset["rows"]),
              "totalNonTiedPairs": int(total_pairs),
              "qemPooledPairAccuracy": total_qem_correct / total_pairs if total_pairs else None,
              "coarseRasterPooledPairAccuracy": total_raster_correct / total_pairs
              if total_pairs else None,
              "mlpPooledPairAccuracy": total_mlp_correct / total_pairs if total_pairs else None,
              "meanMlpTop1AbsoluteRegret": float(np.mean(
                  [row["mlpAbsoluteRegret"] for row in evaluated_groups]))
                  if evaluated_groups else None,
              "meanQemOptimisticTop1AbsoluteRegret": float(np.mean(
                  [row["qemTieSetBestAbsoluteRegret"] for row in evaluated_groups]))
                  if evaluated_groups else None,
              "meanMlpRangeNormalizedRegret": float(np.mean(
                  [row["mlpRangeNormalizedRegret"] for row in evaluated_groups
                   if row["mlpRangeNormalizedRegret"] is not None]))
                  if any(row["mlpRangeNormalizedRegret"] is not None
                         for row in evaluated_groups) else None,
              "meanQemRangeNormalizedOptimisticRegret": float(np.mean(
                  [row["qemRangeNormalizedOptimisticRegret"] for row in evaluated_groups
                   if row["qemRangeNormalizedOptimisticRegret"] is not None]))
                  if any(row["qemRangeNormalizedOptimisticRegret"] is not None
                         for row in evaluated_groups) else None,
              "meanCoarseRasterRangeNormalizedOptimisticRegret": float(np.mean(
                  [row["coarseRasterRangeNormalizedOptimisticRegret"] for row in evaluated_groups
                   if row["coarseRasterRangeNormalizedOptimisticRegret"] is not None]))
                  if any(row["coarseRasterRangeNormalizedOptimisticRegret"] is not None
                         for row in evaluated_groups) else None,
              "mlpTop1OverlapGroups": sum(row["mlpBestOverlap"] for row in evaluated_groups),
              "qemTop1OverlapGroups": sum(row["qemBestOverlap"] for row in evaluated_groups),
              "coarseRasterTop1OverlapGroups": sum(
                  row["coarseRasterBestOverlap"] for row in evaluated_groups),
              "heldOutGroups": result_groups}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "assetCount", "groupCount", "rowCount", "totalNonTiedPairs",
        "qemPooledPairAccuracy", "coarseRasterPooledPairAccuracy", "mlpPooledPairAccuracy",
        "meanMlpTop1AbsoluteRegret", "meanQemOptimisticTop1AbsoluteRegret",
        "meanMlpRangeNormalizedRegret", "meanQemRangeNormalizedOptimisticRegret",
        "meanCoarseRasterRangeNormalizedOptimisticRegret",
        "mlpTop1OverlapGroups", "qemTop1OverlapGroups",
        "coarseRasterTop1OverlapGroups")}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
