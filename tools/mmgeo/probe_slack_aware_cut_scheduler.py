#!/usr/bin/env python3
"""Replay a deterministic error-slack scheduler on captured strict-gate DAG builds.

Every policy receives the same hard cut-error cap: parents whose children already exceed it are
pruned without work, and a newly built parent is published only if its exact accumulated error
fits. The new priority is normalized remaining error slack divided by a pre-build work proxy from
locked/boundary fractions. This is a frozen-outcome screen, not a production runtime benchmark.
"""

import argparse
import json
from pathlib import Path

import numpy as np

import audit_exact_cut_frontier_oracle as exact_oracle
from probe_dependency_aware_dag_scheduler import (
    ASSETS,
    BUDGET_FRACTIONS,
    build_asset,
    reconstruct_cut,
)


POLICIES = ("fixed_level", "smallest_work", "boundary", "quality_aware_1p0",
            "slack_aware")
ERROR_QUANTILES = (0.25, 0.50, 0.75)


def prepare_slack_ranks(asset, error_cap):
    for job in asset["jobs"]:
        f = job["features"]
        locked_fraction = max(0.0, float(f[3]))
        boundary_fraction = max(0.0, float(f[4]))
        max_child_boundary = max(0.0, float(f[5]))
        estimated_attempts = 1.0 + locked_fraction + boundary_fraction + max_child_boundary
        estimated_work = max(1.0, job["triangles_in"] * estimated_attempts)
        slack = max(0.0, error_cap - float(job["child_error"]))
        score = (slack / max(error_cap, 1e-12)) / estimated_attempts
        job["estimatedSlackWork"] = estimated_work
        job["rank"]["slack_aware"] = (
            score, -estimated_work, -int(job["index"]))


def run_capped_policy(asset, policy, budget, error_cap):
    jobs = asset["jobs"]
    impossible = {job["index"] for job in jobs
                  if float(job["child_error"]) > error_cap + 1e-12}
    attempted = set(impossible)
    built_outputs = set()
    available_nodes = set(asset["initial_nodes"])
    spent = 0

    while True:
        ready = [job for job in jobs if job["index"] not in attempted and
                 all(member in available_nodes for member in job["members"])]
        fitting = [job for job in ready if spent + job["work"] <= budget]
        if not fitting:
            break
        job = max(fitting, key=lambda candidate: candidate["rank"][policy])
        attempted.add(job["index"])
        spent += int(job["work"])
        if not job["promoted"]:
            continue
        output = int(job["output"])
        output_error = float(asset["nodes"][output].get("accumulatedError", 0.0))
        if output_error <= error_cap + 1e-12:
            built_outputs.add(output)
            available_nodes.add(output)

    cut = reconstruct_cut(asset, built_outputs)
    if cut["maxAccumulatedErrorProxy"] > error_cap + 1e-12:
        raise ValueError(f"{asset['name']}: capped policy exceeded its max-error threshold")
    return {
        "policy": policy, "budgetWork": int(budget), "spentWork": int(spent),
        "attemptedGroups": len(attempted) - len(impossible),
        "prunedImpossibleGroups": len(impossible),
        "builtPromotedGroups": len(built_outputs), "cut": cut,
    }


def strict_dominates(a, b):
    return (a["cutTriangles"] <= b["cutTriangles"] and
            a["maxAccumulatedErrorProxy"] <= b["maxAccumulatedErrorProxy"] + 1e-12 and
            (a["cutTriangles"] < b["cutTriangles"] or
             a["maxAccumulatedErrorProxy"] < b["maxAccumulatedErrorProxy"] - 1e-12))


def validate_error_monotonicity(asset):
    """Pruning an over-cap child cut is safe only if every ancestor error is monotone."""
    violations = []
    for node_id, node in asset["nodes"].items():
        child_ids = list(map(int, node.get("children", [])))
        if not child_ids:
            continue
        parent_error = float(node.get("accumulatedError", 0.0))
        child_error = max(float(asset["nodes"][child_id].get("accumulatedError", 0.0))
                          for child_id in child_ids)
        if parent_error + 1e-12 < child_error:
            violations.append((int(node_id), parent_error, child_error))
    if violations:
        raise ValueError(f"{asset['name']}: accumulated error is not monotone; "
                         f"unsafe to pre-prune {len(violations)} ancestors; "
                         f"worst={violations[0]}")
    return len(asset["nodes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path("out/exact-cut-frontier/slack-aware-cut-replay.json"))
    parser.add_argument("--state-limit", type=int, default=6000)
    args = parser.parse_args()
    exact_oracle.MAX_STATES = args.state_limit
    root = Path(__file__).resolve().parents[2]
    assets = {name: build_asset(name, root / relative) for name, relative in ASSETS.items()}
    monotone_node_counts = {name: validate_error_monotonicity(asset)
                            for name, asset in assets.items()}
    results = []
    cap_summary = {}

    for heldout_name, asset in assets.items():
        exact_oracle.prepare_policy_scores(assets, heldout_name)
        output_errors = [float(asset["nodes"][int(job["output"])].get("accumulatedError", 0.0))
                         for job in asset["jobs"]
                         if job["promoted"] and job["output"] is not None]
        caps = [float(x) for x in np.quantile(output_errors, ERROR_QUANTILES)]
        total_work = sum(int(job["work"]) for job in asset["jobs"])
        base_cut = reconstruct_cut(asset, set())

        for cap_index, error_cap in enumerate(caps):
            prepare_slack_ranks(asset, error_cap)
            frontier = exact_oracle.exact_frontier(asset, total_work, error_cap)
            cap_summary[f"{heldout_name}:q{int(ERROR_QUANTILES[cap_index] * 100)}"] = {
                "errorCap": error_cap, "oracleStateCount": len(frontier)}
            for fraction in BUDGET_FRACTIONS:
                budget = max(1, int(round(total_work * fraction)))
                oracle_state = exact_oracle.oracle_under_quality(frontier, budget)
                runs = {policy: run_capped_policy(asset, policy, budget, error_cap)
                        for policy in POLICIES}
                oracle_triangles = int(oracle_state["triangles"])
                for policy, run in runs.items():
                    cut = run["cut"]
                    qaw_cut = runs["quality_aware_1p0"]["cut"]
                    results.append({
                        "asset": heldout_name,
                        "errorQuantile": ERROR_QUANTILES[cap_index],
                        "errorCap": error_cap, "budgetFraction": fraction,
                        "budgetWork": budget, "policy": policy,
                        "spentWork": run["spentWork"],
                        "attemptedGroups": run["attemptedGroups"],
                        "prunedImpossibleGroups": run["prunedImpossibleGroups"],
                        "cutTriangles": cut["cutTriangles"],
                        "maxError": cut["maxAccumulatedErrorProxy"],
                        "triangleReductionFromNoBuild": (
                            base_cut["cutTriangles"] - cut["cutTriangles"]),
                        "oracleTriangles": oracle_triangles,
                        "oracleGapTriangles": cut["cutTriangles"] - oracle_triangles,
                        "dominatesQaw": strict_dominates(cut, qaw_cut),
                        "qawDominates": strict_dominates(qaw_cut, cut),
                        "exactLeafCover": cut["exactLeafCover"],
                    })

    slack_rows = [row for row in results if row["policy"] == "slack_aware"]
    qaw_rows = [row for row in results if row["policy"] == "quality_aware_1p0"]
    summary = {
        "assetCount": len(assets), "errorCapsPerAsset": len(ERROR_QUANTILES),
        "budgetFractions": len(BUDGET_FRACTIONS), "pointsPerPolicy": len(slack_rows),
        "slackStrictlyDominatesQaw": sum(row["dominatesQaw"] for row in slack_rows),
        "qawStrictlyDominatesSlack": sum(row["qawDominates"] for row in slack_rows),
        "slackMeanTriangleReduction": float(np.mean(
            [row["triangleReductionFromNoBuild"] for row in slack_rows])),
        "qawMeanTriangleReduction": float(np.mean(
            [row["triangleReductionFromNoBuild"] for row in qaw_rows])),
        "slackMeanOracleGap": float(np.mean([row["oracleGapTriangles"] for row in slack_rows])),
        "qawMeanOracleGap": float(np.mean([row["oracleGapTriangles"] for row in qaw_rows])),
        "allCutsRespectCapAndLeafCover": all(
            row["maxError"] <= row["errorCap"] + 1e-12 and row["exactLeafCover"]
            for row in results),
    }
    output = {
        "scope": "asset-held-out priority scores with fixed error caps and frozen outcomes",
        "warning": "cost is input-triangle-attempt proxy; caps use accumulatedError, not raster quality; "
                   "policies see exact historical attempt work; no runtime/RSS is measured",
        "priority": "normalized child-error slack divided by 1 + locked fraction + boundary-per-triangle "
                    "+ max-child-boundary fraction; tie-break by estimated input work",
        "estimatedWorkProxy": "inputTriangles * (1 + lockedFraction + boundaryPerTriangle + maxChildBoundaryFraction)",
        "monotoneAccumulatedErrorNodesChecked": monotone_node_counts,
        "capSummary": cap_summary, "summary": summary, "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "caps": cap_summary,
                      "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
