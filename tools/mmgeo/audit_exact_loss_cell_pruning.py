#!/usr/bin/env python3
"""Offline bound-pruning replay for exact per-cell collapse losses.

The contribution-sorted policy is intentionally clairvoyant: it sees the exact
unvisited cell contributions. It is an upper bound on what a learned allocator
could achieve, not a deployable scheduling policy.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def replay(candidate_rows, cell_rows, contribution_order, raster_cells=None, raster_steps=None):
    cell_ids = sorted(next(iter(cell_rows.values()))["cells"])
    exact = {int(row["candidateId"]): float(row["whole"]) for row in cell_rows.values()}
    cells = {int(row["candidateId"]): row["cells"] for row in cell_rows.values()}
    candidate_rows = sorted(candidate_rows, key=lambda row: float(row["rasterEnergy"]))
    incumbent_id = None
    incumbent = float("inf")
    evaluated = 0
    candidate_summaries = []
    for row in candidate_rows:
        candidate_id = int(row["candidateId"])
        values = cells[candidate_id]
        if contribution_order == "oracle_descending":
            ordered_cells = sorted(cell_ids, key=lambda key: (-float(values[key]), key))
        elif contribution_order == "raster_descending":
            coarse = raster_cells[candidate_id]
            ordered_cells = sorted(
                cell_ids,
                key=lambda key: (-float(coarse[f"{raster_steps}:{key}"]), key))
        elif contribution_order == "learned_descending":
            predicted = raster_cells[candidate_id]
            ordered_cells = sorted(
                cell_ids,
                key=lambda key: (-float(predicted[f"{raster_steps}:{key}"]), key))
        else:
            ordered_cells = cell_ids
        lower_bound = 0.0
        count = 0
        pruned = False
        if incumbent_id is not None:
            tolerance = 1e-12 * max(abs(incumbent), 1e-300)
            for cell_id in ordered_cells:
                lower_bound += float(values[cell_id])
                count += 1
                if lower_bound >= incumbent - tolerance:
                    pruned = True
                    break
        else:
            lower_bound = exact[candidate_id]
            count = len(ordered_cells)
        evaluated += count
        if not pruned:
            incumbent_id = candidate_id
            incumbent = exact[candidate_id]
        candidate_summaries.append({"candidateId": candidate_id,
                                    "cellsEvaluated": count,
                                    "totalCells": len(cell_ids),
                                    "pruned": pruned,
                                    "lowerBoundAtStop": lower_bound,
                                    "exactLoss": exact[candidate_id]})
    minimum = min(exact.values())
    winner_tolerance = 1e-12 * max(abs(minimum), 1e-300)
    exact_winners = {candidate_id for candidate_id, energy in exact.items()
                     if energy <= minimum + winner_tolerance}
    return {"policy": contribution_order,
            "evaluatedCellIntegrations": evaluated,
            "fullCellIntegrations": len(exact) * len(cell_ids),
            "fractionAvoided": 1.0 - evaluated / (len(exact) * len(cell_ids)),
            "selectedCandidateId": incumbent_id,
            "selectedCandidateExactLoss": exact[incumbent_id],
            "selectedIsExactWinner": incumbent_id in exact_winners,
            "trace": candidate_summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--steps", type=int, default=None,
                        help="raster sample budget used to order candidates; default is minimum")
    parser.add_argument("--train-on", type=Path, nargs="+", default=None,
                        help="fit a tiny per-cell MLP on these captures and evaluate on capture")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    data = json.loads(args.capture.read_text(encoding="utf-8"))
    if not data.get("candidateExactCellLosses"):
        parser.error("capture does not contain per-cell exact losses; rerun probe with --loss-cell-width/height")
    cell_rows = {int(row["candidateId"]): row
                 for row in data["candidateExactCellLosses"]}
    if any(not row.get("complete", True) for row in cell_rows.values()):
        parser.error("offline scheduling replay requires full exact cell labels")
    raster_cell_rows = {int(row["candidateId"]): row["cells"]
                        for row in data.get("candidateRasterCellLosses", [])}
    for candidate_id, row in cell_rows.items():
        error = abs(float(row["sum"]) - float(row["whole"]))
        if error > 1e-10 * max(abs(float(row["whole"])), 1e-300):
            parser.error(f"candidate {candidate_id}: per-cell sum differs from whole loss by {error:g}")
    available_steps = sorted({int(row["steps"]) for row in data["candidateRasterRows"]})
    step = args.steps if args.steps is not None else min(available_steps)
    raster_rows = [row for row in data["candidateRasterRows"] if int(row["steps"]) == step]
    if len(raster_rows) != len(cell_rows):
        parser.error("raster candidates and exact per-cell candidates do not match")
    policies = ["fixed"]
    if raster_cell_rows:
        policies.append("raster_descending")
    learned_priorities = None
    if args.train_on:
        train_captures = [json.loads(path.read_text(encoding="utf-8"))
                          for path in args.train_on]
        if not raster_cell_rows or any(
                not capture.get("candidateExactCellLosses") or
                not capture.get("candidateRasterCellLosses")
                for capture in train_captures):
            parser.error("training and held-out captures must contain exact and raster cell losses")
        held_steps = step
        held_norm = max(float(np.mean([row["whole"] for row in cell_rows.values()])), 1e-300)

        def feature_rows(exact_map, raster_map, sample_steps, normalizer):
            features, targets = [], []
            keys = sorted(next(iter(exact_map.values()))["cells"])
            max_x = max(int(key.split(",")[0]) for key in keys) or 1
            max_y = max(int(key.split(",")[1]) for key in keys) or 1
            for candidate_id, exact_row in exact_map.items():
                raster_values = raster_map[candidate_id]
                total_raster = sum(float(value) for key, value in raster_values.items()
                                   if key.startswith(f"{sample_steps}:"))
                for cell in keys:
                    x, y = map(int, cell.split(","))
                    raster_value = float(raster_values[f"{sample_steps}:{cell}"])
                    exact_value = float(exact_row["cells"][cell])
                    features.append([
                        math.log10(raster_value / normalizer + 1e-8),
                        math.log10(total_raster / normalizer + 1e-8),
                        x / max_x, y / max_y])
                    targets.append(math.log10(exact_value / normalizer + 1e-8))
            return np.asarray(features), np.asarray(targets)

        x_train_parts, y_train_parts = [], []
        for train_data in train_captures:
            train_exact = {int(row["candidateId"]): row
                           for row in train_data["candidateExactCellLosses"]}
            train_raster = {int(row["candidateId"]): row["cells"]
                            for row in train_data["candidateRasterCellLosses"]}
            train_steps = min({int(key.split(":", 1)[0])
                               for row in train_raster.values() for key in row})
            train_norm = max(float(np.mean([row["whole"]
                                            for row in train_exact.values()])), 1e-300)
            x_part, y_part = feature_rows(train_exact, train_raster,
                                          train_steps, train_norm)
            x_train_parts.append(x_part)
            y_train_parts.append(y_part)
        x_train = np.vstack(x_train_parts)
        y_train = np.concatenate(y_train_parts)
        model = make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(8,), activation="relu", solver="lbfgs",
                         alpha=1.0, max_iter=1000, tol=1e-4, random_state=23))
        model.fit(x_train, y_train)
        learned_priorities = {}
        for candidate_id, exact_row in cell_rows.items():
            raster_values = raster_cell_rows[candidate_id]
            total_raster = sum(float(value) for key, value in raster_values.items()
                               if key.startswith(f"{held_steps}:"))
            keys = sorted(exact_row["cells"])
            max_x = max(int(key.split(",")[0]) for key in keys) or 1
            max_y = max(int(key.split(",")[1]) for key in keys) or 1
            x_test = []
            for cell in keys:
                x, y = map(int, cell.split(","))
                raster_value = float(raster_values[f"{held_steps}:{cell}"])
                x_test.append([
                    math.log10(raster_value / held_norm + 1e-8),
                    math.log10(total_raster / held_norm + 1e-8),
                    x / max_x, y / max_y])
            predictions = model.predict(np.asarray(x_test))
            learned_priorities[candidate_id] = {
                f"{held_steps}:{cell}": float(value)
                for cell, value in zip(keys, predictions)}
        policies.append("learned_descending")
    policies.append("oracle_descending")
    results = [replay(raster_rows, cell_rows, policy,
                      raster_cells=(learned_priorities if policy == "learned_descending"
                                    else raster_cell_rows or None),
                      raster_steps=step)
               for policy in policies]
    output = {"scope": "offline exact-bound pruning replay; candidate integration counts only",
              "warning": "oracle_descending uses unseen exact values and is not deployable",
              "input": str(args.capture), "rasterSteps": step,
              "trainingCaptures": [str(path) for path in args.train_on] if args.train_on else None,
              "candidateCount": len(cell_rows),
              "cellCount": len(next(iter(cell_rows.values()))["cells"]),
              "results": results}
    target = args.out or args.capture.with_name(args.capture.stem + "-cell-pruning.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "rasterSteps", "candidateCount", "cellCount", "results")}, indent=2))
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
