#!/usr/bin/env python3
"""Small CPU MLP feasibility screen for raster-path collapse candidate shortlisting."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


ASSETS = ("monkey", "pirate", "torus")


def load_pilot():
    path = Path(__file__).with_name("depth_candidate_pilot.py")
    spec = importlib.util.spec_from_file_location("learned_shortlist_pilot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def extract_asset(pilot, capture_path, report_path, asset):
    positions, triangles, candidates = pilot.load_capture(capture_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ids = [int(cid) for cid in report["candidateIds"]]
    angles = np.asarray(report["angles"], dtype=np.float64)
    size = int(report["size"])
    faces = triangles
    tri_pos = positions[faces]
    cross = np.cross(tri_pos[:, 1] - tri_pos[:, 0], tri_pos[:, 2] - tri_pos[:, 0])
    tri_area = 0.5 * np.linalg.norm(cross, axis=1)
    tri_normal = cross / np.maximum(2 * tri_area[:, None], 1e-20)
    total_area = max(float(tri_area.sum()), 1e-20)

    # Number of incident faces per undirected edge exposes boundary-like neighborhoods.
    edge_counts = {}
    vertex_face_count = np.zeros(len(positions), dtype=np.int32)
    for face in triangles:
        vertex_face_count[face] += 1
        for j in range(3):
            a, b = int(face[j]), int(face[(j + 1) % 3])
            key = (a, b) if a < b else (b, a)
            edge_counts[key] = edge_counts.get(key, 0) + 1
    boundary_vertices = np.zeros(len(positions), dtype=bool)
    for (a, b), count in edge_counts.items():
        if count == 1:
            boundary_vertices[a] = boundary_vertices[b] = True

    projected_patch_area = np.zeros((len(ids), len(angles)), dtype=np.float64)
    for vi, angle in enumerate(angles):
        projected = pilot.project(positions, pilot.camera(positions, float(angle), size))
        tri_xy = projected[triangles[:, :], :2]
        area2 = ((tri_xy[:, 1, 0] - tri_xy[:, 0, 0]) *
                 (tri_xy[:, 2, 1] - tri_xy[:, 0, 1]) -
                 (tri_xy[:, 1, 1] - tri_xy[:, 0, 1]) *
                 (tri_xy[:, 2, 0] - tri_xy[:, 0, 0]))
        projected_area = 0.5 * np.abs(area2) / float(size * size)
        for ci, candidate_id in enumerate(ids):
            affected = np.asarray(candidates[candidate_id]["affected"], dtype=np.int64)
            projected_patch_area[ci, vi] = projected_area[affected].sum()

    features = []
    path_losses = []
    qem_priority = []
    for ci, candidate_id in enumerate(ids):
        candidate = candidates[candidate_id]
        remove, keep = int(candidate["remove"]), int(candidate["keep"])
        affected = np.asarray(candidate["affected"], dtype=np.int64)
        patch_areas = tri_area[affected]
        patch_normals = tri_normal[affected]
        weights = patch_areas / max(float(patch_areas.sum()), 1e-20)
        mean_normal = np.sum(patch_normals * weights[:, None], axis=0)
        normal_coherence = float(np.linalg.norm(mean_normal))
        edge_length = float(np.linalg.norm(positions[remove] - positions[keep]))
        target = np.asarray(candidate["target"], dtype=np.float64)
        target_displacement = float(np.linalg.norm(target - positions[keep]))
        mean_patch_area = float(patch_areas.mean()) if len(patch_areas) else 0.0
        max_patch_area = float(patch_areas.max()) if len(patch_areas) else 0.0
        boundary = float(boundary_vertices[remove] or boundary_vertices[keep])
        projected = projected_patch_area[ci]

        features.append([
            np.log1p(max(float(candidate.get("priority", 0.0)), 0.0)),
            np.log1p(edge_length / max(np.sqrt(total_area), 1e-12)),
            np.log1p(target_displacement / max(edge_length, 1e-12)),
            np.log1p(len(affected)),
            np.log1p(float(patch_areas.sum()) / total_area),
            np.log1p(mean_patch_area / total_area),
            np.log1p(max_patch_area / total_area),
            1.0 - normal_coherence,
            boundary,
            np.log1p(float(projected.mean())),
            np.log1p(float(projected.std())),
            np.log1p(float(projected.max())),
            float(projected[-1] - projected[0]),
        ])

        row_scores = []
        for view in report["views"]:
            row = next(r for r in view["rows"] if int(r["id"]) == candidate_id)
            row_scores.append(float(row["errors"]["total"]))
        weights_path = np.ones(len(row_scores), dtype=np.float64)
        if len(weights_path) > 1:
            weights_path[[0, -1]] = 0.5
        path_losses.append(float(np.average(row_scores, weights=weights_path)))
        qem_priority.append(float(candidate.get("priority", 0.0)))

    target_rank = average_rank(np.asarray(path_losses, dtype=np.float64))
    return {
        "asset": asset,
        "features": np.asarray(features, dtype=np.float64),
        "targetRank": target_rank,
        "losses": np.asarray(path_losses, dtype=np.float64),
        "qemPriority": np.asarray(qem_priority, dtype=np.float64),
        "candidateIds": ids,
        "viewCount": len(angles),
        "reportHash": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "captureHash": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
    }


def train_mlp(train_x, train_y, seed, hidden=8, epochs=800):
    rng = np.random.default_rng(seed)
    mean = train_x.mean(axis=0)
    std = np.maximum(train_x.std(axis=0), 1e-6)
    x = np.clip((train_x - mean) / std, -6, 6)
    d = x.shape[1]
    w1 = rng.normal(0, 1 / np.sqrt(d), (d, hidden))
    b1 = np.zeros(hidden)
    w2 = rng.normal(0, 1 / np.sqrt(hidden), hidden)
    b2 = np.zeros((), dtype=np.float64)
    params = [w1, b1, w2, b2]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    step = 0
    lr = 0.01
    batch_size = 32
    for _ in range(epochs):
        shuffled = rng.permutation(len(x))
        for start in range(0, len(x), batch_size):
            ix = shuffled[start:start + batch_size]
            xb, yb = x[ix], train_y[ix]
            z1 = xb @ w1 + b1
            h = np.tanh(z1)
            pred = h @ w2 + float(b2)
            error = pred - yb
            gpred = (2.0 / len(ix)) * error
            gw2 = h.T @ gpred + 1e-4 * w2
            gb2 = np.asarray(gpred.sum())
            gh = gpred[:, None] * w2[None, :]
            gz = gh * (1.0 - h * h)
            gw1 = xb.T @ gz + 1e-4 * w1
            gb1 = gz.sum(axis=0)
            grads = [gw1, gb1, gw2, gb2]
            step += 1
            for j, (param, grad) in enumerate(zip(params, grads)):
                m[j] = 0.9 * m[j] + 0.1 * grad
                v[j] = 0.999 * v[j] + 0.001 * grad * grad
                mhat = m[j] / (1 - 0.9 ** step)
                vhat = v[j] / (1 - 0.999 ** step)
                param -= lr * mhat / (np.sqrt(vhat) + 1e-8)

    def predict(test_x):
        xt = np.clip((test_x - mean) / std, -6, 6)
        return np.tanh(xt @ w1 + b1) @ w2 + float(b2)
    return predict


def spearman(a, b):
    ra, rb = average_rank(np.asarray(a)), average_rank(np.asarray(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def average_rank(values):
    values = np.asarray(values)
    order = np.argsort(values, kind="stable")
    result = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    if len(values) > 1:
        result /= len(values) - 1
    return result


def evaluate_fold(test, predictions, name):
    exact = test["targetRank"]
    order = np.argsort(predictions, kind="stable")
    losses = test["losses"]
    best_loss = float(np.min(losses))
    median_loss = float(np.median(losses))
    scale = max(median_loss - best_loss, 1e-15)
    top5_loss = float(np.min(losses[order[:5]]))
    top1_loss = float(losses[order[0]])
    tol = max(1e-15, 1e-10 * abs(best_loss))
    return {
        "asset": test["asset"],
        "method": name,
        "candidateCount": len(exact),
        "optimalLossInTop1": top1_loss <= best_loss + tol,
        "optimalLossInTop5": top5_loss <= best_loss + tol,
        "bestExactRankWithinTop5": float(exact[order[:5]].min()),
        "shortlistCandidateIds": [int(test["candidateIds"][i])
                                  for i in order[:5]],
        "shortlistPredictedScores": [float(predictions[i]) for i in order[:5]],
        "selectedTop1ExactRank": float(exact[order[0]]),
        "top1Loss": top1_loss,
        "top5BestLoss": top5_loss,
        "bestLoss": best_loss,
        "medianLoss": median_loss,
        "normalizedTop1Regret": (top1_loss - best_loss) / scale,
        "normalizedTop5Regret": (top5_loss - best_loss) / scale,
        "spearman": spearman(predictions, exact),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=73)
    args = parser.parse_args()
    pilot = load_pilot()
    root = Path("out")
    data = []
    for asset in ASSETS:
        capture = root / "filter-real-candidates" / f"{asset}.json"
        report = root / "camera-rank-stability" / f"{asset}-pool0-{'32' if asset == 'torus' else '16'}.json"
        data.append(extract_asset(pilot, capture, report, asset))

    folds = []
    for fold_index, test in enumerate(data):
        train = [row for row in data if row["asset"] != test["asset"]]
        train_x = np.concatenate([row["features"] for row in train], axis=0)
        train_y = np.concatenate([row["targetRank"] for row in train], axis=0)
        predictor = train_mlp(train_x, train_y, args.seed + fold_index)
        mlp = evaluate_fold(test, predictor(test["features"]), "tiny_mlp")
        qem_low = evaluate_fold(test, test["qemPriority"], "priority_low")
        qem_high = evaluate_fold(test, -test["qemPriority"], "priority_high")
        random_predictions = np.random.default_rng(args.seed + 100 + fold_index).random(
            len(test["targetRank"]))
        random = evaluate_fold(test, random_predictions, "random")
        folds.extend((mlp, qem_low, qem_high, random))

    summary = {}
    for method in ("tiny_mlp", "priority_low", "priority_high", "random"):
        rows = [row for row in folds if row["method"] == method]
        summary[method] = {
            "folds": len(rows),
            "top1OptimalCount": sum(row["optimalLossInTop1"] for row in rows),
            "top5OptimalCount": sum(row["optimalLossInTop5"] for row in rows),
            "meanBestRankWithinTop5": float(np.mean(
                [row["bestExactRankWithinTop5"] for row in rows])),
            "meanNormalizedTop5Regret": float(np.mean(
                [row["normalizedTop5Regret"] for row in rows])),
            "meanSelectedTop1Rank": float(np.mean(
                [row["selectedTop1ExactRank"] for row in rows])),
            "meanSpearman": float(np.mean([row["spearman"] for row in rows])),
        }

    output = {
        "scope": "exploratory leave-one-asset-out tiny-MLP candidate shortlist screen",
        "warning": "three assets and 48 candidates each are insufficient for a generalization or novelty claim",
        "featureNames": [
            "log_priority", "log_edge_length", "log_target_offset_ratio",
            "log_affected_face_count", "log_patch_area_fraction",
            "log_mean_face_area_fraction", "log_max_face_area_fraction",
            "normal_incoherence", "boundary_touch", "log_projected_area_mean",
            "log_projected_area_std", "log_projected_area_max", "projected_area_delta",
        ],
        "model": {"hiddenUnits": 8, "epochs": 800, "optimizer": "numpy Adam",
                  "trainingSamplesPerFold": 96, "testSamplesPerFold": 48,
                  "parameterCount": 8 * 13 + 8 + 8 + 1},
        "data": [{"asset": row["asset"], "candidates": len(row["candidateIds"]),
                  "views": row["viewCount"], "captureSha256": row["captureHash"],
                  "reportSha256": row["reportHash"]} for row in data],
        "foldResults": folds,
        "summary": summary,
        "seed": args.seed,
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
