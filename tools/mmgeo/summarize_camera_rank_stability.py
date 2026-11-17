#!/usr/bin/env python3
"""Summarize winner margins and stale-winner regret from frozen camera-orbit reports.

This is a read-only analysis of existing sampled-orbit outputs. It does not render, certify a
continuous camera domain, or claim production runtime savings.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * q
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] * (hi - x) + values[hi] * (x - lo)


def summarize(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    ids = report["candidateIds"]
    views = report["views"]
    rows_by_view = []
    per_view = []

    for view in views:
        rows = view["rows"]
        if [row["id"] for row in rows] != ids:
            raise ValueError(f"candidate order changed in {path}, frame {view['frame']}")
        scores = {row["id"]: float(row["total"]) for row in rows}
        ranked = sorted(scores.items(), key=lambda item: item[1])
        vals = [score for _, score in ranked]
        best_id, best = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else best
        middle = percentile(vals, 0.5)
        gap = runner_up - best
        per_view.append({
            "frame": view["frame"],
            "angle": view["angle"],
            "winner": best_id,
            "winnerScore": best,
            "runnerUpScore": runner_up,
            "exactZeroCandidates": sum(score == 0.0 for score in vals),
            "winnerMargin": gap,
            "winnerMarginOverMedianCandidateScore": gap / middle if middle else None,
            "medianCandidateScore": middle,
        })
        rows_by_view.append(scores)

    adjacent = []
    for i in range(len(views) - 1):
        old_id = per_view[i]["winner"]
        new_id = per_view[i + 1]["winner"]
        next_scores = rows_by_view[i + 1]
        next_best = min(next_scores.values())
        stale_score = next_scores[old_id]
        regret = max(0.0, stale_score - next_best)
        median = per_view[i + 1]["medianCandidateScore"]
        adjacent.append({
            "fromFrame": views[i]["frame"],
            "toFrame": views[i + 1]["frame"],
            "winnerChanged": old_id != new_id,
            "oldWinner": old_id,
            "newWinner": new_id,
            "newViewOldWinnerScore": stale_score,
            "newViewBestScore": next_best,
            "staleWinnerRegret": regret,
            "regretOverMedianCandidateScore": regret / median if median else None,
            "bothWinnersHaveZeroScore": (
                rows_by_view[i][old_id] == 0.0 and next_scores[new_id] == 0.0
            ),
        })

    normalized_regrets = [
        row["regretOverMedianCandidateScore"]
        for row in adjacent if row["regretOverMedianCandidateScore"] is not None
    ]
    normalized_margins = [
        row["winnerMarginOverMedianCandidateScore"]
        for row in per_view if row["winnerMarginOverMedianCandidateScore"] is not None
    ]
    thresholds = (1e-4, 1e-3, 1e-2)
    return {
        "asset": path.stem.split("-pool", 1)[0],
        "inputPath": str(path),
        "inputSha256": sha256(path),
        "sourceCaptureSha256": report["captureSha256"],
        "candidateReportSha256": report["candidateReportSha256"],
        "analysisScope": report["scope"],
        "candidateCount": len(ids),
        "views": per_view,
        "adjacentTransitions": adjacent,
        "summary": {
            "viewCount": len(views),
            "distinctWinners": len(set(row["winner"] for row in per_view)),
            "winnerChanges": sum(row["winnerChanged"] for row in adjacent),
            "winnerChangesWithZeroLossOnBothViews": sum(
                row["winnerChanged"] and row["bothWinnersHaveZeroScore"] for row in adjacent
            ),
            "viewsWithMultipleExactZeroCandidates": sum(
                row["exactZeroCandidates"] > 1 for row in per_view
            ),
            "winnerMarginOverMedianCandidateScoreP50P90": {
                "p50": percentile(normalized_margins, 0.5),
                "p90": percentile(normalized_margins, 0.9),
            },
            "staleWinnerRegretOverMedianCandidateScoreP50P90Max": {
                "p50": percentile(normalized_regrets, 0.5),
                "p90": percentile(normalized_regrets, 0.9),
                "max": max(normalized_regrets) if normalized_regrets else None,
            },
            "transitionsAboveRelativeRegretThreshold": {
                str(threshold): sum(value > threshold for value in normalized_regrets)
                for threshold in thresholds
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = {
        "scope": "diagnostic of sampled fixed-pool camera sweeps; no continuous certificate or speed claim",
        "scriptSha256": sha256(Path(__file__)),
        "reports": [summarize(path) for path in args.reports],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for report in result["reports"]:
        print(report["asset"], report["summary"], flush=True)
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
