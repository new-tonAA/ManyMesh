#!/usr/bin/env python3
"""Exact finite frontier oracle for captured successful ManyMesh DAG parents.

This is a retrospective upper bound, not an online policy. It enumerates the full-cut
triangle/error/work frontier induced by already captured successful parent nodes. Failed
groups are optimistically skipped, so the oracle is allowed to know outcomes in advance.
"""

import argparse
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from probe_dependency_aware_dag_scheduler import (
    ASSETS,
    BUDGET_FRACTIONS,
    build_asset,
    fit_logistic,
    fit_ridge,
    reconstruct_cut,
    run_policy,
    score_jobs,
)


MAX_STATES = 30000
POLICIES = ("fixed_level", "smallest_work", "boundary", "learned",
            "quality_aware_0p5", "quality_aware_1p0", "quality_aware_2p0",
            "clairvoyant")


def pareto_prune(states):
    """Keep the work/triangle frontier for one fixed maximum-error threshold."""
    unique = {}
    for state in states:
        key = (state[0], state[1])
        if key not in unique:
            unique[key] = state
    ordered = sorted(unique.values(), key=lambda s: (s[0], s[1]))
    frontier = []
    best_triangles = float("inf")
    for state in ordered:
        work, triangles, _cut = state
        if triangles >= best_triangles:
            continue
        frontier.append(state)
        best_triangles = triangles
        if len(frontier) > MAX_STATES:
            raise RuntimeError(f"frontier exceeded safety limit {MAX_STATES}")
    return frontier


def combine_frontiers(first, second, max_work):
    """Convolve two cut frontiers while bounding temporary state memory."""
    combined = []
    for a in first:
        row = [(a[0] + b[0], a[1] + b[1], a[2] + b[2])
               for b in second if a[0] + b[0] <= max_work]
        combined.extend(row)
        if len(combined) > MAX_STATES * 2:
            combined = pareto_prune(combined)
    return pareto_prune(combined)


def exact_frontier(asset, max_work, error_cap):
    nodes = asset["nodes"]
    initial_nodes = set(map(int, asset["initial_nodes"]))
    jobs_by_output = {int(job["output"]): job for job in asset["jobs"]
                      if job["promoted"] and job["output"] is not None}
    children = {int(node_id): tuple(map(int, node.get("children", [])))
                for node_id, node in nodes.items()}

    # A single-parent graph is required for the tree dynamic program to count work once.
    parent_count = {int(node_id): 0 for node_id in nodes}
    for child_ids in children.values():
        for child in child_ids:
            parent_count[child] = parent_count.get(child, 0) + 1
    shared = [node_id for node_id, count in parent_count.items() if count > 1]
    if shared:
        raise ValueError(f"{asset['name']}: shared-child DAG needs a coupled-state oracle; "
                         f"found {len(shared)} multiply-parented nodes")

    @lru_cache(maxsize=None)
    def force_cost(node_id):
        """Work needed to make this exact node available as a cut element."""
        if node_id in initial_nodes:
            return 0
        child_ids = children[node_id]
        if not child_ids:
            return 0
        job = jobs_by_output.get(node_id)
        if job is None:
            return None
        dependency_costs = [force_cost(child) for child in child_ids]
        if any(cost is None for cost in dependency_costs):
            return None
        return int(job["work"] + sum(dependency_costs))

    @lru_cache(maxsize=None)
    def cut_states(node_id):
        child_ids = children[node_id]
        node = nodes[node_id]
        if not child_ids:
            if float(node.get("accumulatedError", 0.0)) > error_cap + 1e-12:
                return ()
            return ((0, int(node["tri"]), (node_id,)),)

        # Option one: leave this parent unavailable and choose cuts independently below it.
        combined = [(0, 0, ())]
        for child in child_ids:
            combined = combine_frontiers(combined, cut_states(child), max_work)

        # Option two: build this node and every successful dependency needed to expose it.
        build_work = force_cost(node_id)
        if (node_id in jobs_by_output and build_work is not None and
                build_work <= max_work and
                float(node.get("accumulatedError", 0.0)) <= error_cap + 1e-12):
            combined.append((int(build_work), int(node["tri"]), (node_id,)))
        return tuple(pareto_prune(combined))

    forest = [(0, 0, ())]
    for root in asset["roots"]:
        forest = combine_frontiers(forest, cut_states(int(root)), max_work)

    frontier = []
    for work, triangles, cut_nodes in forest:
        built = set()
        stack = list(cut_nodes)
        while stack:
            node_id = int(stack.pop())
            if node_id in initial_nodes:
                continue
            child_ids = children[node_id]
            if child_ids and node_id in jobs_by_output:
                built.add(node_id)
                stack.extend(child_ids)
            elif child_ids:
                raise ValueError(f"{asset['name']}: cut uses unproduced node {node_id}")
        measured_work = sum(int(jobs_by_output[node_id]["work"]) for node_id in built)
        if measured_work != work:
            raise ValueError(f"{asset['name']}: DP work {work} != closure work {measured_work}")
        cut = reconstruct_cut(asset, built)
        if cut["cutTriangles"] != triangles or cut["maxAccumulatedErrorProxy"] > error_cap + 1e-12:
            state_triangles = sum(int(nodes[node_id]["tri"]) for node_id in cut_nodes)
            internal_cut = [node_id for node_id in cut_nodes if children[int(node_id)]]
            raise ValueError(f"{asset['name']}: DP cut metrics disagree with reconstruction: "
                             f"state={triangles}, cap={error_cap}, rebuilt=({cut['cutTriangles']},"
                             f"{cut['maxAccumulatedErrorProxy']}), cutSum={state_triangles}, "
                             f"internalCut={internal_cut[:12]}, cut={cut_nodes}")
        frontier.append({"work": int(work), "triangles": int(triangles),
                         "maxError": float(cut["maxAccumulatedErrorProxy"]),
                         "cutNodeCount": len(cut_nodes),
                         "builtParentCount": len(built),
                         "builtParentNodes": sorted(map(int, built)),
                         "exactLeafCover": True})
    return frontier


def prepare_policy_scores(assets, heldout_name):
    asset = assets[heldout_name]
    train_rows = [row for name, other in assets.items() if name != heldout_name
                  for row in other["feature_rows"]]
    train_x = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
    train_y = np.asarray([row["promoted"] for row in train_rows], dtype=np.float64)
    predictor = fit_logistic(train_x, train_y, seed=37 + list(assets).index(heldout_name))
    test_x = np.asarray([row["features"] for row in asset["feature_rows"]], dtype=np.float64)
    scores = predictor(test_x)
    positives = [row for row in train_rows if row["promoted"]]
    positive_x = np.asarray([row["features"] for row in positives], dtype=np.float64)
    reduction_y = np.asarray([
        max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
        max(row["inputTriangles"], 1) for row in positives], dtype=np.float64)
    error_y = np.asarray([row["errorDelta"] for row in positives], dtype=np.float64)
    reduction_model = fit_ridge(positive_x, reduction_y)
    error_model = fit_ridge(positive_x, error_y)
    score_jobs(asset, scores, train_rows, reduction_model, error_model)


def best_at_budget(frontier, budget):
    return [state for state in frontier if state["work"] <= budget]


def oracle_under_quality(frontier, budget):
    options = [state for state in frontier if state["work"] <= budget]
    if not options:
        return None
    return min(options, key=lambda s: (s["triangles"], s["work"], s["maxError"]))


def main():
    global MAX_STATES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset", choices=("all", *ASSETS), default="all")
    parser.add_argument("--state-limit", type=int, default=MAX_STATES)
    args = parser.parse_args()
    MAX_STATES = args.state_limit
    root = Path(__file__).resolve().parents[2]
    selected = list(ASSETS) if args.asset == "all" else [args.asset]
    assets = {name: build_asset(name, root / ASSETS[name]) for name in ASSETS}
    results = []
    oracle_state_counts = {}

    for name in selected:
        asset = assets[name]
        prepare_policy_scores(assets, name)
        total_work = sum(int(job["work"]) for job in asset["jobs"])
        baseline = reconstruct_cut(asset, set())
        policy_runs = {}
        for fraction in BUDGET_FRACTIONS:
            budget = max(1, int(round(total_work * fraction)))
            for policy in POLICIES:
                measured = run_policy(asset, policy, budget)
                policy_runs[(fraction, policy)] = (budget, measured)
        error_caps = sorted({float(measured["cut"]["maxAccumulatedErrorProxy"])
                             for _fraction, measured in policy_runs.values()})
        oracle_by_cap = {}
        for error_cap in error_caps:
            frontier = exact_frontier(asset, total_work, error_cap)
            oracle_by_cap[error_cap] = frontier
        oracle_state_counts[name] = {f"{cap:.12g}": len(frontier)
                                     for cap, frontier in oracle_by_cap.items()}
        for (fraction, policy), (budget, measured) in policy_runs.items():
            point = measured["cut"]
            cap = float(point["maxAccumulatedErrorProxy"])
            quality_oracle = oracle_under_quality(oracle_by_cap[cap], budget)
            results.append({
                "asset": name, "budgetFraction": fraction, "budgetWork": budget,
                "policy": policy, "spentWork": measured["spentWork"],
                "policyTriangles": point["cutTriangles"],
                "policyMaxError": point["maxAccumulatedErrorProxy"],
                "oracleAtPolicyError": quality_oracle,
                "oracleTriangleAdvantage": (
                    point["cutTriangles"] - quality_oracle["triangles"]
                    if quality_oracle else None),
                "oracleFrontierStateCount": len(oracle_by_cap[cap]),
                "noBuildTriangles": baseline["cutTriangles"],
                "allFrontierStatesLeafCoverVerified": True,
            })

    output = {
        "scope": "exact finite Pareto frontier over captured successful DAG parents",
        "warning": "retrospective optimistic upper bound: failed jobs are skipped for free; "
                   "work is input-triangles times attempts; error is accumulatedError proxy, "
                   "not rendered image error; no runtime, RSS, or I/O is measured",
        "assets": selected,
        "policies": POLICIES,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assets": selected, "rows": len(results),
                      "oracleStates": oracle_state_counts,
                      "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
