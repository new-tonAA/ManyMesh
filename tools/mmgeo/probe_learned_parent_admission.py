#!/usr/bin/env python3
"""Cross-asset screen for a tiny predictor that skips futile DAG parent builds."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ASSETS = {
    "cloth": "out/quality-witness-current/cloth-regroup-pilot-200k/diagnostics.json",
    "material_sphere": "out/quality-witness-current/material-sphere-regroup-pilot-200k/diagnostics.json",
    "monkey": "out/quality-witness-current/monkey-regroup-pilot-200k/diagnostics.json",
    "shapes": "out/quality-witness-current/shapes-regroup-pilot-200k/diagnostics.json",
}

FEATURES = [
    "log_input_triangles", "log_child_count", "log_vertices", "locked_fraction",
    "boundary_edges_per_triangle", "max_child_boundary_fraction",
    "mean_child_boundary_fraction", "max_child_error_px_proxy",
    "mean_child_error_px_proxy", "min_child_quality", "mean_child_quality",
    "max_child_normal_error", "max_child_uv_error", "level",
]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_asset(name, path):
    data = json.loads(path.read_text(encoding="utf-8"))
    graph_path = path.with_name("lod_graph.json")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = {int(node["id"]): node for node in graph["dag"]}
    rows = []
    for group in data["groups"]:
        if int(group.get("trial", 0)) != 0:
            continue
        members = [nodes[int(node_id)] for node_id in group["members"]]
        input_triangles = max(int(group["inputTriangles"]), 1)
        input_vertices = max(len(set(map(int, group["inputIndices"]))), 1)
        locked = len(set(map(int, group["lockedVertices"])))
        child_triangles = np.asarray([max(int(node["tri"]), 0) for node in members],
                                     dtype=np.float64)
        boundary = np.asarray([int(node.get("boundaryEdges", 0)) for node in members],
                              dtype=np.float64)
        boundary_fraction = boundary / np.maximum(child_triangles, 1.0)
        errors = np.asarray([float(node.get("accumulatedError", 0.0)) for node in members],
                            dtype=np.float64)
        qualities = np.asarray([float(node.get("minQuality", 0.0)) for node in members],
                              dtype=np.float64)
        normals = np.asarray([float(node.get("normalErrorDeg", 0.0)) for node in members],
                             dtype=np.float64)
        uvs = np.asarray([float(node.get("uvError", 0.0)) for node in members],
                         dtype=np.float64)
        features = [
            np.log1p(input_triangles), np.log1p(len(members)), np.log1p(input_vertices),
            locked / input_vertices,
            float(boundary.sum()) / input_triangles,
            float(boundary_fraction.max(initial=0.0)),
            float(boundary_fraction.mean()) if len(boundary_fraction) else 0.0,
            float(errors.max(initial=0.0)),
            float(errors.mean()) if len(errors) else 0.0,
            float(qualities.min()) if len(qualities) else 0.0,
            float(qualities.mean()) if len(qualities) else 0.0,
            float(normals.max(initial=0.0)), float(uvs.max(initial=0.0)),
            float(group["level"]),
        ]
        attempts = max(int(group.get("attempts", 0)), 1)
        rows.append({
            "asset": name,
            "features": features,
            "promoted": int(bool(group["promoted"])),
            "work": input_triangles * attempts,
            "inputTriangles": input_triangles,
            "attempts": attempts,
            "members": len(members),
            "level": int(group["level"]),
        })
    return rows, {
        "asset": name, "groups": len(rows),
        "promoted": sum(row["promoted"] for row in rows),
        "diagnosticsSha256": sha256(path), "graphSha256": sha256(graph_path),
    }


def fit_logistic(train_x, train_y, seed=37):
    mean = train_x.mean(axis=0)
    std = np.maximum(train_x.std(axis=0), 1e-5)
    x = np.clip((train_x - mean) / std, -5.0, 5.0)
    prevalence = np.clip(float(train_y.mean()), 1e-4, 1.0 - 1e-4)
    w = np.zeros(x.shape[1], dtype=np.float64)
    b = np.asarray(np.log(prevalence / (1.0 - prevalence)))
    rng = np.random.default_rng(seed)
    m_w, v_w = np.zeros_like(w), np.zeros_like(w)
    m_b, v_b = np.zeros_like(b), np.zeros_like(b)
    step = 0
    for _ in range(1800):
        ix = rng.permutation(len(x))
        for start in range(0, len(ix), 64):
            step += 1
            batch = ix[start:start + 64]
            xb, yb = x[batch], train_y[batch]
            logits = np.clip(xb @ w + b, -30, 30)
            prob = 1.0 / (1.0 + np.exp(-logits))
            delta = (prob - yb) / len(batch)
            gw = xb.T @ delta + 1e-3 * w
            gb = np.asarray(delta.sum())
            m_w = 0.9 * m_w + 0.1 * gw
            v_w = 0.999 * v_w + 0.001 * gw * gw
            m_b = 0.9 * m_b + 0.1 * gb
            v_b = 0.999 * v_b + 0.001 * gb * gb
            rate = 0.01
            w -= rate * (m_w / (1 - 0.9 ** step)) / (
                np.sqrt(v_w / (1 - 0.999 ** step)) + 1e-8)
            b -= rate * (m_b / (1 - 0.9 ** step)) / (
                np.sqrt(v_b / (1 - 0.999 ** step)) + 1e-8)

    def predict(test_x):
        z = np.clip((test_x - mean) / std, -5.0, 5.0)
        logits = np.clip(z @ w + b, -30, 30)
        return 1.0 / (1.0 + np.exp(-logits))

    return predict


def average_precision(labels, scores):
    order = np.argsort(-scores, kind="stable")
    positives = int(labels.sum())
    if positives == 0:
        return 0.0
    precision = np.cumsum(labels[order]) / (np.arange(len(order)) + 1)
    return float(np.sum(precision * labels[order]) / positives)


def threshold_for_recall(labels, scores, target):
    positive_scores = scores[labels == 1]
    if not len(positive_scores):
        return float("-inf")
    return float(np.quantile(positive_scores, max(0.0, 1.0 - target), method="lower"))


def evaluate_fold(asset, rows, scores, thresholds):
    labels = np.asarray([row["promoted"] for row in rows], dtype=np.int32)
    work = np.asarray([row["work"] for row in rows], dtype=np.float64)
    result = {
        "asset": asset, "groupCount": len(rows), "promotionRate": float(labels.mean()),
        "averagePrecision": average_precision(labels, scores),
        "alwaysAttemptWork": float(work.sum()),
        "riskThresholds": [],
        "workBudgetSkips": [],
    }
    for target in thresholds:
        train_threshold = target["threshold"]
        admitted = scores >= train_threshold
        false_negative = int(np.count_nonzero((labels == 1) & ~admitted))
        skipped_work = float(work[~admitted].sum())
        saved_work_fraction = skipped_work / max(float(work.sum()), 1.0)
        result["riskThresholds"].append({
            "trainingRecallTarget": target["recall"],
            "admittedGroups": int(admitted.sum()),
            "positiveGroups": int(labels.sum()),
            "falseNegativePromotions": false_negative,
            "heldoutPromotionRecall": float(1.0 - false_negative / max(int(labels.sum()), 1)),
            "estimatedWorkSavedFraction": saved_work_fraction,
            "estimatedWorkSaved": skipped_work,
        })
    # A cheap, parameter-free geometric control: prefer groups with fewer boundary edges
    # per input triangle, using the same feature representation at index 4.
    boundary_goodness = -np.asarray([row["features"][4] for row in rows])
    result["boundaryHeuristicAP"] = average_precision(labels, boundary_goodness)
    positive_floor = float(scores[labels == 1].min()) if np.any(labels == 1) else float("inf")
    boundary_floor = (float(boundary_goodness[labels == 1].min())
            if np.any(labels == 1) else float("inf"))
    for method, rank, floor in (("tiny_logistic", scores, positive_floor),
                                ("boundary_ratio", boundary_goodness, boundary_floor)):
        skip = rank < floor
        skipped_work = float(work[skip].sum())
        result.setdefault("observedZeroMissUpperBound", []).append({
            "method": method,
            "usesHeldoutPromotionLabels": True,
            "falseNegativePromotions": int(np.count_nonzero((labels == 1) & skip)),
            "estimatedWorkSavedFraction": skipped_work / max(float(work.sum()), 1.0),
            "estimatedWorkSaved": skipped_work,
            "skippedGroups": int(skip.sum()),
        })
    input_cost = np.asarray([row["inputTriangles"] for row in rows], dtype=np.float64)
    actual_work = work
    model_failure_per_input = (1.0 - scores) / np.maximum(input_cost, 1.0)
    boundary_failure_per_input = np.asarray(
        [row["features"][4] for row in rows], dtype=np.float64) / np.maximum(input_cost, 1.0)
    for target_fraction in (0.10, 0.20, 0.30, 0.50):
        for method, ratio in (("tiny_logistic", model_failure_per_input),
                              ("boundary_ratio", boundary_failure_per_input)):
            order = np.argsort(-ratio, kind="stable")
            selected = np.zeros(len(rows), dtype=bool)
            selected_input = 0.0
            target_input = float(input_cost.sum()) * target_fraction
            for index in order:
                if selected_input >= target_input:
                    break
                selected[index] = True
                selected_input += float(input_cost[index])
            misses = int(np.count_nonzero((labels == 1) & selected))
            skipped_work = float(actual_work[selected].sum())
            result["workBudgetSkips"].append({
                "method": method, "targetInputTriangleFractionSkipped": target_fraction,
                "actualInputTriangleFractionSkipped": selected_input / max(float(input_cost.sum()), 1.0),
                "actualAttemptWorkFractionSkipped": skipped_work / max(float(actual_work.sum()), 1.0),
                "skippedGroupCount": int(selected.sum()),
                "missedPromotedGroups": misses,
                "retainedPromotionRecall": float(1.0 - misses / max(int(labels.sum()), 1)),
            })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    assets = {}
    provenance = []
    for name, relative in ASSETS.items():
        rows, record = load_asset(name, root / relative)
        assets[name] = rows
        provenance.append(record)

    folds = []
    for index, (asset, rows) in enumerate(assets.items()):
        train_rows = [row for other, values in assets.items() if other != asset for row in values]
        train_x = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
        train_y = np.asarray([row["promoted"] for row in train_rows], dtype=np.float64)
        test_x = np.asarray([row["features"] for row in rows], dtype=np.float64)
        test_y = np.asarray([row["promoted"] for row in rows], dtype=np.int32)
        predictor = fit_logistic(train_x, train_y, seed=37 + index)
        scores = predictor(test_x)
        targets = []
        for recall in (0.95, 0.98, 0.99, 1.0):
            cutoff = threshold_for_recall(train_y.astype(np.int32),
                    predictor(train_x), recall)
            targets.append({"recall": recall, "threshold": cutoff})
        folds.append(evaluate_fold(asset, rows, scores, targets))

    result = {
        "scope": "leave-one-asset-out tiny logistic screen for pre-build DAG parent admission",
        "warning": "retrospective group labels; work is input-triangle count times observed attempts; no runtime scheduler or cut-level quality is tested",
        "features": FEATURES,
        "model": {"type": "regularized logistic regression", "parameters": len(FEATURES) + 1,
                  "optimizer": "NumPy Adam", "trainingEpochs": 1800},
        "assets": provenance,
        "folds": folds,
        "summary": {
            "meanAveragePrecision": float(np.mean([f["averagePrecision"] for f in folds])),
            "meanBoundaryHeuristicAP": float(np.mean([f["boundaryHeuristicAP"] for f in folds])),
            "zeroFalseNegativeFoldsAtTrainingRecall95": sum(
                f["riskThresholds"][0]["falseNegativePromotions"] == 0 for f in folds),
            "meanWorkSavedAtTrainingRecall95": float(np.mean(
                [f["riskThresholds"][0]["estimatedWorkSavedFraction"] for f in folds])),
        },
        "scriptSha256": sha256(__file__),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": result["summary"], "folds": folds}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
