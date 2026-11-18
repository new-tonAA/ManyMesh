#!/usr/bin/env python3
"""Measure finite-orbit candidate regret when only a subset of views is scored.

This is a diagnostic over frozen raster-oracle reports. It does not estimate a continuous
camera integral or establish a runtime method. Random subsets use a fixed seed per asset/k.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, q):
    return float(np.quantile(np.asarray(values, dtype=np.float64), q))


def analyze(path, random_trials):
    report = json.loads(path.read_text(encoding="utf-8"))
    ids = report["candidateIds"]
    views = report["views"]
    matrix = np.asarray([
        [next(float(row["total"]) for row in view["rows"] if row["id"] == cid)
         for cid in ids]
        for view in views
    ], dtype=np.float64)
    nviews = len(views)
    full_mean = matrix.mean(axis=0)
    optimum = int(np.argmin(full_mean))
    scale = float(np.median(full_mean))
    rows = []
    for k in sorted({1, 2, 4, 8, 12, 16, nviews}):
        if k > nviews:
            continue
        subsets = []
        if nviews % k == 0:
            stride = nviews // k
            subsets.extend([list(range(offset, nviews, stride))
                            for offset in range(stride)])
        else:
            subsets.append(list(range(0, nviews, k))[:k])
        rng = np.random.default_rng(9173 + k)
        subsets.extend(sorted(rng.choice(nviews, k, replace=False).tolist())
                       for _ in range(random_trials))
        selected = np.asarray([int(np.argmin(matrix[subset].mean(axis=0)))
                               for subset in subsets], dtype=np.int64)
        regret = np.maximum(0.0, full_mean[selected] - full_mean[optimum])
        normalized = regret / max(scale, np.finfo(np.float64).tiny)
        top5 = np.argsort(full_mean, kind="stable")[:min(5, len(ids))]
        rows.append({
            "viewsScored": k,
            "evaluationFraction": k / nviews,
            "subsetCount": len(subsets),
            "fullOrbitWinnerMatchRate": float(np.mean(selected == optimum)),
            "fullOrbitTop5Rate": float(np.mean(np.isin(selected, top5))),
            "normalizedRegretP50P95Max": {
                "p50": percentile(normalized, 0.5),
                "p95": percentile(normalized, 0.95),
                "max": float(normalized.max()),
            },
        })
    return {
        "asset": path.stem.split("-pool", 1)[0],
        "input": str(path),
        "inputSha256": sha256(path),
        "scope": report["scope"],
        "viewCount": nviews,
        "candidateCount": len(ids),
        "finiteOrbitWinnerId": ids[optimum],
        "finiteOrbitMinimumMeanLoss": float(full_mean[optimum]),
        "medianCandidateMeanLoss": scale,
        "zeroViewScoreFraction": float(np.mean(matrix == 0.0)),
        "sampling": rows,
        "interpretation": "Finite sampled-orbit subset ranking only; not a continuous integral or speed claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--random-trials", type=int, default=500)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.random_trials < 1:
        parser.error("--random-trials must be positive")
    result = {
        "scope": "fixed finite-orbit raster-score subset diagnostic",
        "seedRule": "NumPy default_rng(9173 + viewsScored)",
        "randomTrialsPerK": args.random_trials,
        "reports": [analyze(path, args.random_trials) for path in args.reports],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for report in result["reports"]:
        print(f"{report['asset']}: views={report['viewCount']} pool={report['candidateCount']} "
              f"winner={report['finiteOrbitWinnerId']} zero={report['zeroViewScoreFraction']:.3f}")
        for row in report["sampling"]:
            regret = row["normalizedRegretP50P95Max"]
            print(f"  k={row['viewsScored']:2d} match={row['fullOrbitWinnerMatchRate']:.3f} "
                  f"top5={row['fullOrbitTop5Rate']:.3f} "
                  f"regret/median p50={regret['p50']:.4g} p95={regret['p95']:.4g} "
                  f"max={regret['max']:.4g}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
