#!/usr/bin/env python3
"""Screen adaptive camera-path samples on frozen raster-score matrices.

The adaptive rule refines the interval with the greatest observed score variation and candidate
rank disagreement. This is an offline diagnostic over already measured views, not a renderer or a
continuous-path guarantee.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np


def load_report(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    ids = report["candidateIds"]
    views = report["views"]
    matrix = np.asarray([
        [next(float(row["total"]) for row in view["rows"] if row["id"] == cid)
         for cid in ids]
        for view in views
    ], dtype=np.float64)
    angles = np.asarray([float(view["angle"]) for view in views], dtype=np.float64)
    order = np.argsort(angles)
    return report, ids, angles[order], matrix[order]


def quadrature_mean(indices, angles, matrix):
    indices = sorted(indices)
    x = angles[indices]
    values = matrix[indices]
    span = float(angles[-1] - angles[0])
    if len(indices) == 1 or span <= 0:
        return values.mean(axis=0)
    weights = np.zeros(len(indices), dtype=np.float64)
    gaps = np.diff(x)
    weights[:-1] += gaps * 0.5
    weights[1:] += gaps * 0.5
    return (values * weights[:, None]).sum(axis=0) / span


def interval_priority(a, b, matrix, angles):
    left = matrix[a]
    right = matrix[b]
    floor = max(float(np.median(np.maximum(left, right))) * 1e-6,
                np.finfo(np.float64).tiny)
    relative_change = np.median(np.abs(right - left) / np.maximum(np.maximum(left, right), floor))
    left_order = np.argsort(left, kind="stable")
    right_order = np.argsort(right, kind="stable")
    left_rank = np.empty(len(left_order), dtype=np.int32)
    right_rank = np.empty(len(right_order), dtype=np.int32)
    left_rank[left_order] = np.arange(len(left_order))
    right_rank[right_order] = np.arange(len(right_order))
    rank_disagreement = float(np.mean(np.abs(left_rank - right_rank))) / max(len(left) - 1, 1)
    winner_flip = float(int(left_order[0] != right_order[0]))
    width = float(angles[b] - angles[a]) / max(float(angles[-1] - angles[0]),
                                                np.finfo(np.float64).tiny)
    return width * (relative_change + rank_disagreement + winner_flip)


def adaptive_indices(k, angles, matrix):
    n = len(angles)
    selected = {0, n // 2, n - 1}
    while len(selected) < min(k, n):
        ordered = sorted(selected)
        intervals = []
        for a, b in zip(ordered, ordered[1:]):
            if b - a > 1:
                intervals.append((interval_priority(a, b, matrix, angles), a, b))
        if not intervals:
            break
        _, a, b = max(intervals)
        midpoint = (angles[a] + angles[b]) * 0.5
        choices = range(a + 1, b)
        chosen = min(choices, key=lambda i: abs(angles[i] - midpoint))
        selected.add(chosen)
    return sorted(selected)


def score_selection(indices, angles, matrix, candidate_ids):
    indices = sorted(int(i) for i in indices)
    estimate = quadrature_mean(indices, angles, matrix)
    full = quadrature_mean(range(len(matrix)), angles, matrix)
    best = int(np.argmin(estimate))
    oracle = int(np.argmin(full))
    scale = max(float(np.median(full)), np.finfo(np.float64).tiny)
    top5 = np.argsort(full, kind="stable")[:min(5, len(full))]
    return {
        "indices": indices,
        "angles": [float(angles[i]) for i in indices],
        "selectedCandidate": int(candidate_ids[best]),
        "finitePathWinner": int(candidate_ids[oracle]),
        "winnerMatch": bool(best == oracle),
        "top5Match": bool(best in top5),
        "normalizedRegret": float(max(0.0, full[best] - full[oracle]) / scale),
        "sampledQuadratureMean": float(estimate[best]),
        "finitePathMean": float(full[best]),
    }


def subset_controls(k, angles, matrix, candidate_ids, asset):
    n = len(angles)
    interior = range(1, n - 1)
    total = math.comb(n - 2, k - 2)
    if total <= 2000:
        subsets = [([0] + list(choice) + [n - 1])
                   for choice in itertools.combinations(interior, k - 2)]
        mode = "exhaustive endpoint-anchored subsets"
    else:
        rng = np.random.default_rng(60413 + k + sum(map(ord, asset)))
        subsets = [[0] + sorted(rng.choice(n - 2, k - 2, replace=False) + 1) + [n - 1]
                   for _ in range(2000)]
        mode = "2000 endpoint-anchored random subsets"
    values = [score_selection(indices, angles, matrix, candidate_ids) for indices in subsets]
    regret = np.asarray([row["normalizedRegret"] for row in values], dtype=np.float64)
    return {
        "mode": mode,
        "subsetCount": len(values),
        "winnerMatchRate": float(np.mean([row["winnerMatch"] for row in values])),
        "top5MatchRate": float(np.mean([row["top5Match"] for row in values])),
        "regretP50": float(np.quantile(regret, .5)),
        "regretP95": float(np.quantile(regret, .95)),
        "regretMax": float(regret.max()),
        "bestSubsetRegret": float(regret.min()),
        "bestSubsetIndices": values[int(np.argmin(regret))]["indices"],
    }


def analyze(path):
    report, ids, angles, matrix = load_report(path)
    n = len(angles)
    rows = []
    for k in sorted({3, 4, 6, 8, 12, n}):
        if k > n:
            continue
        adaptive = adaptive_indices(k, angles, matrix)
        uniform = sorted(set(np.rint(np.linspace(0, n - 1, k)).astype(int).tolist()))
        rows.append({
            "views": k,
            "adaptive": score_selection(adaptive, angles, matrix, ids),
            "uniform": score_selection(uniform, angles, matrix, ids),
            "endpointAnchoredControl": subset_controls(k, angles, matrix, ids,
                                                       path.stem.split("-pool", 1)[0]),
        })
    return {
        "asset": path.stem.split("-pool", 1)[0],
        "input": str(path),
        "inputSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidateReportSha256": report.get("candidateReportSha256"),
        "candidateCount": len(ids),
        "viewCount": n,
        "scope": "finite sampled camera segment; oracle is the mean over captured views",
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = {
        "method": "midpoint refinement by observed candidate-score variation and rank disagreement",
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "frozen candidate pool and finite captured views",
            "uniform score rows are raster measurements; no new rendering was performed",
            "does not establish a continuous-path integral or a speedup",
            "adaptive quadrature and multi-view simplification are established broad concepts",
        ],
        "reports": [analyze(path) for path in args.reports],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for asset in result["reports"]:
        print(f"{asset['asset']}: views={asset['viewCount']} candidates={asset['candidateCount']}")
        for row in asset["results"]:
            a, u = row["adaptive"], row["uniform"]
            print(f"  k={row['views']:2d} adaptive regret={a['normalizedRegret']:.4g} "
                  f"match={int(a['winnerMatch'])} uniform regret={u['normalizedRegret']:.4g} "
                  f"match={int(u['winnerMatch'])}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
