#!/usr/bin/env python3
"""Held-out screen for a tiny residual corrector plus exact path-loss shortlist.

The cheap raster score is the ranking baseline. A small CPU regressor predicts only
the log residual between that score and the continuous event-integrated target.
This is an offline feasibility audit, not a certified fallback policy.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


EPS = 1e-12


class NumpyRidge:
    """Small centered ridge regression, avoiding additional native sklearn modules."""
    def fit(self, x, y):
        self.x_mean = x.mean(axis=0)
        self.y_mean = float(y.mean())
        centered = x - self.x_mean
        self.scale = np.maximum(centered.std(axis=0), 1e-12)
        normalized = centered / self.scale
        self.weights = np.linalg.solve(
            normalized.T @ normalized + 10.0 * np.eye(normalized.shape[1]),
            normalized.T @ (y - self.y_mean))
        return self

    def predict(self, x):
        return ((x - self.x_mean) / self.scale) @ self.weights + self.y_mean


def non_tied_pair_accuracy(rows, scores):
    pairs = correct = 0
    for i, first in enumerate(rows):
        for j in range(i + 1, len(rows)):
            second = rows[j]
            a, b = float(first["exactEnergy"]), float(second["exactEnergy"])
            tol = max(EPS, 1e-6 * max(abs(a), abs(b)))
            if abs(a - b) <= tol:
                continue
            pairs += 1
            predicted = scores[i] < scores[j]
            correct += predicted == (a < b)
    return pairs, correct


def rank_metrics(rows, scores, ks):
    exact = np.asarray([row["exactEnergy"] for row in rows], dtype=float)
    order = np.argsort(np.asarray(scores, dtype=float), kind="stable")
    best = float(exact.min())
    tol = max(EPS, 1e-6 * abs(best))
    winners = {i for i, value in enumerate(exact) if value <= best + tol}
    span = max(float(exact.max() - best), tol)
    out = {"top1Recall": bool(int(order[0]) in winners),
           "top1RegretNormalized": max(0.0, float(exact[order[0]]) - best) / span}
    out["topKRecall"] = {str(k): bool(winners.intersection(map(int, order[:k])))
                         for k in ks}
    out["topKBestRegretNormalized"] = {
        str(k): max(0.0, float(exact[order[:k]].min()) - best) / span for k in ks}
    return out


def path_key(rows):
    """Return camera and image-plane pan directions; path length is not part of this split."""
    f = rows[0]["features"]
    view = round(float(np.arctan2(f["view_sin"], f["view_cos"])), 3)
    pan = round(float(np.arctan2(f["pan_sin"], f["pan_cos"])), 3)
    return (view, pan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path,
                        default=Path("out/pathloss-captures/path-loss-features-current.json"))
    parser.add_argument("--out", type=Path,
                        default=Path("out/pathloss-captures/residual-hybrid-loao.json"))
    parser.add_argument("--model", choices=("ridge", "mlp"), default="ridge")
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--raster-steps", type=int, default=None,
                        help="restrict to one cheap-raster sample budget")
    parser.add_argument("--split", choices=("asset", "path", "joint"), default="asset",
                        help="hold out meshes, path signatures, or their intersection")
    args = parser.parse_args()

    dataset = json.loads(args.features.read_text(encoding="utf-8"))
    by_group = defaultdict(list)
    for row in dataset["rows"]:
        if args.raster_steps is not None and int(row["rasterSteps"]) != args.raster_steps:
            continue
        by_group[int(row["group"])].append(row)
    if not by_group:
        parser.error(f"no groups use raster-steps={args.raster_steps}")
    assets = sorted({rows[0]["capture"] for rows in by_group.values()})
    paths = sorted({path_key(rows) for rows in by_group.values()})
    result = []
    all_correct = defaultdict(float)
    all_pairs = 0
    all_group_metrics = defaultdict(list)

    folds = []
    if args.split == "asset":
        folds = [(asset, None,
                  [g for g in by_group.values() if g[0]["capture"] != asset],
                  [g for g in by_group.values() if g[0]["capture"] == asset])
                 for asset in assets]
    elif args.split == "path":
        folds = [(None, path,
                  [g for g in by_group.values() if path_key(g) != path],
                  [g for g in by_group.values() if path_key(g) == path])
                 for path in paths]
    else:
        folds = [(asset, path,
                  [g for g in by_group.values()
                   if g[0]["capture"] != asset and path_key(g) != path],
                  [g for g in by_group.values()
                   if g[0]["capture"] == asset and path_key(g) == path])
                 for asset in assets for path in paths]

    for held_asset, held_path, train_groups, test_groups in folds:
        if not test_groups:
            continue
        train_rows = [row for group in train_groups for row in group
                      if float(row["exactEnergy"]) > EPS or
                      float(row["features"]["coarse_raster_energy"]) > EPS]
        if not train_rows:
            continue
        feature_names = [name for name in train_rows[0]["features"]
                         if name != "coarse_raster_energy"]
        x_train = np.asarray([[row["features"][name] for name in feature_names]
                              for row in train_rows], dtype=np.float64)
        y_train = np.asarray([
            np.log10(float(row["exactEnergy"]) + EPS) -
            np.log10(float(row["features"]["coarse_raster_energy"]) + EPS)
            for row in train_rows], dtype=np.float64)
        if args.model == "ridge":
            model = NumpyRidge().fit(x_train, y_train)
        else:
            model = make_pipeline(
                StandardScaler(),
                MLPRegressor(hidden_layer_sizes=(8,), activation="relu", solver="lbfgs",
                             alpha=1.0, max_iter=300, random_state=17))
        model.fit(x_train, y_train)

        for rows in test_groups:
            features = np.asarray([[row["features"][name] for name in feature_names]
                                   for row in rows], dtype=np.float64)
            correction = np.clip(model.predict(features), -4.0, 4.0)
            raster = np.asarray([row["features"]["coarse_raster_energy"]
                                 for row in rows], dtype=float)
            exact = np.asarray([row["exactEnergy"] for row in rows], dtype=float)
            corrected = np.power(10.0, np.log10(raster + EPS) + correction) - EPS
            scores = {"coarseRaster": raster, "qem": np.asarray(
                [row["features"]["qem_priority"] for row in rows], dtype=float),
                      "residualCorrected": corrected}
            pairs, _ = non_tied_pair_accuracy(rows, raster)
            all_pairs += pairs
            group_result = {"heldOutAsset": held_asset, "heldOutPath": held_path,
                            "asset": rows[0]["capture"], "path": path_key(rows),
                            "result": rows[0]["result"],
                            "candidateCount": len(rows), "nonTiedPairs": pairs,
                            "models": {}}
            for name, rank_score in scores.items():
                _, correct = non_tied_pair_accuracy(rows, rank_score)
                all_correct[name] += correct
                metrics = rank_metrics(rows, rank_score, args.top_k)
                all_group_metrics[name].append(metrics)
                group_result["models"][name] = {
                    "pairAccuracy": correct / pairs if pairs else None, **metrics}
            result.append(group_result)

    summary = {}
    for name, group_metrics in all_group_metrics.items():
        summary[name] = {
            "pooledPairAccuracy": all_correct[name] / all_pairs if all_pairs else None,
            "top1RecallGroups": sum(x["top1Recall"] for x in group_metrics),
            "groupCount": len(group_metrics),
            "meanNormalizedTop1Regret": float(np.mean(
                [x["top1RegretNormalized"] for x in group_metrics])),
            "topKRecallGroups": {str(k): sum(x["topKRecall"][str(k)]
                                              for x in group_metrics)
                                 for k in args.top_k},
            "meanBestTopKRegret": {str(k): float(np.mean(
                [x["topKBestRegretNormalized"][str(k)] for x in group_metrics]))
                for k in args.top_k},
        }
    output = {"scope": "held-out residual correction of coarse raster score",
              "warning": "small correlated screen; exact shortlist is empirical, not certified",
              "model": args.model, "rasterSteps": args.raster_steps,
              "split": args.split, "assets": assets, "paths": paths,
              "groupCount": len(result),
              "featureNames": feature_names, "summary": summary, "groups": result}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, "assets": len(assets),
                      "groupCount": len(result), "nonTiedPairs": all_pairs,
                      "summary": summary, "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
