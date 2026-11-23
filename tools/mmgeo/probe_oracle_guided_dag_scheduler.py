#!/usr/bin/env python3
"""Leave-one-asset-out replay of a tiny model imitating exact cut-frontier choices.

The teacher labels indicate how often a captured parent occurs in the exact best cut over six
work budgets and three fixed per-asset error quantiles. The student sees only the 14 pre-build
group features. This remains a retrospective four-asset feasibility screen.
"""

import json

import numpy as np

import audit_exact_cut_frontier_oracle as exact_oracle
from probe_dependency_aware_dag_scheduler import (
    ASSETS,
    BUDGET_FRACTIONS,
    build_asset,
    fit_ridge,
    reconstruct_cut,
    run_policy,
)


def build_teacher_targets(assets):
    """Make asset-local oracle labels at fixed per-asset error quantiles."""
    targets = {}
    for name, asset in assets.items():
        outputs = [int(job["output"]) for job in asset["jobs"]
                   if job["promoted"] and job["output"] is not None]
        error_values = [float(asset["nodes"][node].get("accumulatedError", 0.0))
                        for node in outputs]
        caps = np.quantile(np.asarray(error_values), [0.25, 0.5, 0.75]).tolist()
        total_work = sum(int(job["work"]) for job in asset["jobs"])
        selected_outputs = []
        for cap in caps:
            frontier = exact_oracle.exact_frontier(asset, total_work, float(cap))
            for fraction in BUDGET_FRACTIONS:
                budget = max(1, int(round(total_work * fraction)))
                state = exact_oracle.oracle_under_quality(frontier, budget)
                if state is None:
                    raise ValueError(f"{name}: no exact cut under cap {cap}, work {budget}")
                selected_outputs.append(set(map(int, state["builtParentNodes"])))
        targets[name] = {}
        for job in asset["jobs"]:
            output = job["output"]
            targets[name][job["index"]] = (
                sum(output is not None and int(output) in selected
                    for selected in selected_outputs) / len(selected_outputs))
    return targets


def pairwise_dominates(a, b):
    return (a["cutTriangles"] <= b["cutTriangles"] and
            a["maxAccumulatedErrorProxy"] <= b["maxAccumulatedErrorProxy"] + 1e-12 and
            (a["cutTriangles"] < b["cutTriangles"] or
             a["maxAccumulatedErrorProxy"] < b["maxAccumulatedErrorProxy"] - 1e-12))


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path("out/exact-cut-frontier/oracle-guided-loao.json"))
    parser.add_argument("--state-limit", type=int, default=6000)
    args = parser.parse_args()
    exact_oracle.MAX_STATES = args.state_limit
    root = Path(__file__).resolve().parents[2]
    assets = {name: build_asset(name, root / relative) for name, relative in ASSETS.items()}
    targets = build_teacher_targets(assets)
    results = []

    for heldout_name, asset in assets.items():
        train_rows = [(row["features"], targets[name][index])
                      for name, other in assets.items() if name != heldout_name
                      for index, row in enumerate(other["feature_rows"])]
        train_x = np.asarray([row[0] for row in train_rows], dtype=np.float64)
        train_y = np.asarray([row[1] for row in train_rows], dtype=np.float64)
        model = fit_ridge(train_x, train_y, ridge=4.0)
        test_x = np.asarray([row["features"] for row in asset["feature_rows"]],
                            dtype=np.float64)
        predicted = np.clip(model(test_x), 0.0, 1.0)

        # Keep the existing policy ranks for matched baselines, then add the oracle-imitation rank.
        exact_oracle.prepare_policy_scores(assets, heldout_name)
        for job, score in zip(asset["jobs"], predicted):
            job["rank"]["oracle_teacher"] = (
                float(score), -float(job["work"]), -int(job["index"]))

        total_work = sum(int(job["work"]) for job in asset["jobs"])
        baseline = reconstruct_cut(asset, set())
        for fraction in BUDGET_FRACTIONS:
            budget = max(1, int(round(total_work * fraction)))
            policy_runs = {policy: run_policy(asset, policy, budget)
                           for policy in ("fixed_level", "smallest_work", "boundary",
                                          "learned", "quality_aware_1p0", "oracle_teacher")}
            teacher_run = policy_runs["oracle_teacher"]
            best_simple = min((policy_runs[p] for p in
                               ("fixed_level", "smallest_work", "boundary")),
                              key=lambda r: (r["cut"]["cutTriangles"],
                                             r["cut"]["maxAccumulatedErrorProxy"]))
            qaw = policy_runs["quality_aware_1p0"]
            cut = teacher_run["cut"]
            rows = {policy: run["cut"] for policy, run in policy_runs.items()}
            results.append({
                "asset": heldout_name, "budgetFraction": fraction,
                "budgetWork": budget, "teacherSpentWork": teacher_run["spentWork"],
                "teacherTriangles": cut["cutTriangles"],
                "teacherMaxError": cut["maxAccumulatedErrorProxy"],
                "teacherTriangleReduction": baseline["cutTriangles"] - cut["cutTriangles"],
                "teacherSelectionScoreRange": [float(predicted.min()),
                                               float(predicted.max())],
                "qawTriangles": qaw["cut"]["cutTriangles"],
                "qawMaxError": qaw["cut"]["maxAccumulatedErrorProxy"],
                "teacherDominatesQaw": pairwise_dominates(cut, qaw["cut"]),
                "qawDominatesTeacher": pairwise_dominates(qaw["cut"], cut),
                "teacherNoWorseThanQawErrorTriangleGain": (
                    qaw["cut"]["cutTriangles"] - cut["cutTriangles"]
                    if cut["maxAccumulatedErrorProxy"] <=
                    qaw["cut"]["maxAccumulatedErrorProxy"] + 1e-12 else None),
                "teacherNoWorseThanBestSimple": not any(
                    pairwise_dominates(rows[p], cut)
                    for p in ("fixed_level", "smallest_work", "boundary")),
                "bestSimplePolicy": best_simple["policy"],
                "bestSimpleTriangles": best_simple["cut"]["cutTriangles"],
                "bestSimpleMaxError": best_simple["cut"]["maxAccumulatedErrorProxy"],
                "allCutsExactLeafCover": all(r["cut"]["exactLeafCover"]
                                              for r in policy_runs.values()),
            })

    summary = {}
    for policy_key in ("teacherDominatesQaw", "qawDominatesTeacher",
                       "teacherNoWorseThanBestSimple"):
        summary[policy_key] = sum(row[policy_key] for row in results)
    comparable = [row["teacherNoWorseThanQawErrorTriangleGain"] for row in results
                  if row["teacherNoWorseThanQawErrorTriangleGain"] is not None]
    summary["teacherComparableToQawPoints"] = len(comparable)
    summary["meanTriangleGainAtNoWorseQawError"] = (
        float(np.mean(comparable)) if comparable else None)
    output = {
        "scope": "leave-one-asset-out student trained on asset-local exact quality/work cut choices",
        "warning": "four captured assets; teacher knows promoted outcomes; target uses accumulatedError, "
                   "not rendered quality; work is input-triangles times attempts; no runtime/RSS",
        "teacher": "exact cut oracle at 3 fixed per-asset promoted-parent error quantiles x 6 work budgets",
        "model": "ridge regression from 14 pre-build group features to oracle-cut selection frequency",
        "summary": summary,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "rows": len(results),
                      "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
