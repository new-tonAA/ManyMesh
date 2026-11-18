#!/usr/bin/env python3
"""Reconstruct per-generation LOD cuts with and without spatial retry groups.

This is a read-only audit for the schema-1 DAG diagnostic ledger and its matching
lod_graph.json. It measures the local cut delta at each builder generation. It does
not measure retry wall time, whole-hierarchy Pareto dominance, or rendered quality.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_inputs(diagnostics_path, graph_path):
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if diagnostics.get("schema") not in (1, 2):
        raise ValueError("expected DAG diagnostics schema 1 or 2")
    nodes = {int(node["id"]): node for node in graph["dag"]}
    if len(nodes) != len(graph["dag"]):
        raise ValueError("duplicate DAG node IDs")
    records = [row for row in diagnostics["groups"] if int(row.get("trial", 0)) == 0]
    by_level = defaultdict(list)
    for row in records:
        members = tuple(map(int, row["members"]))
        if not members or len(set(members)) != len(members):
            raise ValueError("group has empty or duplicate members")
        missing = set(members) - nodes.keys()
        if missing:
            raise ValueError(f"group references missing graph nodes: {sorted(missing)[:8]}")
        triangle_sum = sum(int(nodes[member]["tri"]) for member in members)
        if triangle_sum != int(row["inputTriangles"]):
            raise ValueError("diagnostic input triangle count disagrees with its graph members")
        row["_members"] = frozenset(members)
        by_level[int(row["level"])].append(row)

    graph_parents = defaultdict(list)
    for node in graph["dag"]:
        children = tuple(map(int, node.get("children", [])))
        if children:
            graph_parents[(int(node["level"]), children)].append(node)
    for row in records:
        if not row.get("promoted"):
            continue
        candidates = graph_parents.get((int(row["level"]), tuple(map(int, row["members"]))), [])
        if len(candidates) != 1:
            raise ValueError("promoted diagnostic group does not map to one graph parent")
        node = candidates[0]
        if int(node["tri"]) != int(row["outputTriangles"]):
            raise ValueError("promoted group triangle count disagrees with graph parent")
        if abs(float(node["accumulatedError"]) - float(row["accumulatedError"])) > 2e-6:
            raise ValueError("promoted group error disagrees with graph parent")
    return diagnostics, graph, nodes, by_level


def audit_level(rows, nodes):
    by_members = {}
    for row in rows:
        members = row["_members"]
        if members in by_members:
            raise ValueError("duplicate group member set at one generation")
        by_members[members] = row

    roots = [row for row in rows if not any(
        len(other["_members"]) > len(row["_members"])
        and row["_members"] < other["_members"] for other in rows)]
    for i, left in enumerate(roots):
        if any(left["_members"] & right["_members"] for right in roots[i + 1:]):
            raise ValueError("top-level diagnostic groups overlap")

    children = {}
    for row in rows:
        members = row["_members"]
        subsets = [other for other in rows if other["_members"] < members]
        direct = [other for other in subsets if not any(
            len(mid["_members"]) > len(other["_members"])
            and other["_members"] < mid["_members"] < members for mid in subsets)]
        covered = set()
        for child in direct:
            if covered & child["_members"]:
                raise ValueError("retry children overlap")
            covered.update(child["_members"])
        if direct and row.get("promoted"):
            raise ValueError("a promoted candidate unexpectedly has retry descendants")
        children[id(row)] = (direct, members - covered)

    def source_state(members):
        return (
            sum(int(nodes[member]["tri"]) for member in members),
            max((float(nodes[member]["accumulatedError"]) for member in members), default=0.0),
        )

    def retry_state(row):
        if row.get("promoted"):
            return int(row["outputTriangles"]), float(row["accumulatedError"])
        direct, residual = children[id(row)]
        if not direct:
            return source_state(row["_members"])
        child_states = [retry_state(child) for child in direct]
        residual_state = source_state(residual)
        return (
            sum(state[0] for state in child_states) + residual_state[0],
            max([state[1] for state in child_states] + [residual_state[1]]),
        )

    baseline_triangles = retry_triangles = 0
    baseline_error = retry_error = 0.0
    retry_roots = accepted_retry_groups = pareto_roots = 0
    retry_triangles_saved = 0
    retry_packages = []
    for root in roots:
        if root.get("promoted"):
            baseline = (int(root["outputTriangles"]), float(root["accumulatedError"]))
        else:
            baseline = source_state(root["_members"])
        actual = retry_state(root)
        baseline_triangles += baseline[0]
        retry_triangles += actual[0]
        baseline_error = max(baseline_error, baseline[1])
        retry_error = max(retry_error, actual[1])
        direct, _ = children[id(root)]
        if direct:
            retry_roots += 1
            saved = baseline[0] - actual[0]
            retry_triangles_saved += saved
            descendants = []
            pending = list(direct)
            while pending:
                candidate = pending.pop()
                descendants.append(candidate)
                pending.extend(children[id(candidate)][0])
            retry_packages.append({
                "work": sum(int(candidate["inputTriangles"]) for candidate in descendants),
                "saved": saved,
                "error": actual[1],
                "baselineError": baseline[1],
                "features": rejection_features(root),
                "tieKey": tuple(sorted(root["_members"])),
            })
            if actual[0] <= baseline[0] and actual[1] <= baseline[1] and (
                    actual[0] < baseline[0] or actual[1] < baseline[1]):
                pareto_roots += 1

    non_roots = [row for row in rows if row not in roots]
    accepted_retry_groups = sum(bool(row.get("promoted")) for row in non_roots)
    first_pass_input_triangles = sum(int(row["inputTriangles"]) for row in roots)
    retry_input_triangles = sum(int(row["inputTriangles"]) for row in non_roots)
    eligible = [item for item in retry_packages
            if item["work"] > 0 and item["saved"] > 0 and item["error"] <= baseline_error]
    eligible_work = sum(item["work"] for item in eligible)
    budget = [0] * (eligible_work + 1)
    for item in eligible:
        for used in range(eligible_work, item["work"] - 1, -1):
            previous = budget[used - item["work"]]
            if previous >= 0:
                budget[used] = max(budget[used], previous + item["saved"])
    prefix_best = []
    best = 0
    for value in budget:
        best = max(best, value)
        prefix_best.append(best)
    oracle = []
    for fraction in (0.25, 0.50, 0.75, 1.0):
        limit = int(eligible_work * fraction)
        oracle.append({
            "budgetFraction": fraction,
            "inputTriangleWorkBudget": limit,
            "maxTrianglesSaved": prefix_best[limit] if prefix_best else 0,
        })
    policies = {}
    for feature in ("rejectsPerKInput", "attributeRejectsPerKInput",
            "topologyRejectsPerKInput", "geometryRejectsPerKInput"):
        ordered = sorted(retry_packages,
                key=lambda item: (-item["features"][feature], item["tieKey"]))
        rows_for_policy = []
        for fraction in (0.25, 0.50, 0.75, 1.0):
            limit = int(retry_input_triangles * fraction)
            chosen = []
            used = 0
            for item in ordered:
                if item["work"] and used + item["work"] <= limit:
                    chosen.append(item)
                    used += item["work"]
            chosen_ids = {id(item) for item in chosen}
            error = max(
                [item["error"] if id(item) in chosen_ids else item["baselineError"]
                    for item in retry_packages] + [
                        float(row["accumulatedError"]) for row in roots
                        if not children[id(row)][0]])
            rows_for_policy.append({
                "budgetFraction": fraction,
                "inputTriangleWorkBudget": limit,
                "inputTriangleWorkUsed": used,
                "trianglesSaved": sum(item["saved"] for item in chosen),
                "groupUnionMaxError": error,
                "withinBaselineError": error <= baseline_error,
            })
        policies[feature] = rows_for_policy
    ordered = sorted(retry_packages,
            key=lambda item: (item["work"], item["tieKey"]))
    rows_for_policy = []
    for fraction in (0.25, 0.50, 0.75, 1.0):
        limit = int(retry_input_triangles * fraction)
        chosen = []
        used = 0
        for item in ordered:
            if item["work"] and used + item["work"] <= limit:
                chosen.append(item)
                used += item["work"]
        chosen_ids = {id(item) for item in chosen}
        error = max(
            [item["error"] if id(item) in chosen_ids else item["baselineError"]
                for item in retry_packages] + [
                    float(row["accumulatedError"]) for row in roots
                    if not children[id(row)][0]])
        rows_for_policy.append({
            "budgetFraction": fraction,
            "inputTriangleWorkBudget": limit,
            "inputTriangleWorkUsed": used,
            "trianglesSaved": sum(item["saved"] for item in chosen),
            "groupUnionMaxError": error,
            "withinBaselineError": error <= baseline_error,
        })
    policies["smallestWorkFirst"] = rows_for_policy
    return {
        "level": int(rows[0]["level"]),
        "rootGroups": len(roots),
        "diagnosticGroups": len(rows),
        "retryGroups": len(non_roots),
        "acceptedRetryGroups": accepted_retry_groups,
        "firstPassInputTriangleWork": first_pass_input_triangles,
        "retryInputTriangleWork": retry_input_triangles,
        "retrySimplificationAttempts": sum(int(row.get("attempts", 0)) for row in non_roots),
        "retryBudgetOracle": {
            "scope": "whole observed retry trees per failed root; frozen outcomes; same group-union max error cap",
            "eligibleRootTrees": len(eligible),
            "eligibleRetryInputTriangleWork": eligible_work,
            "allRetryTrianglesSaved": retry_triangles_saved,
            "budgets": oracle,
        },
        "firstPassMaskRankPolicies": {
            "scope": "retrospective feature ranking; first-pass masks rank roots, frozen full-tree work/outcomes evaluate quality",
            "policies": policies,
        },
        "triangleSavingsPerRetryInputTriangle": retry_triangles_saved / retry_input_triangles
            if retry_input_triangles else 0.0,
        "rootsWithRetries": retry_roots,
        "locallyParetoImprovedRoots": pareto_roots,
        "retryTrianglesSaved": retry_triangles_saved,
        "baselineTriangles": baseline_triangles,
        "retryTriangles": retry_triangles,
        "groupUnionMaxErrorBaseline": baseline_error,
        "groupUnionMaxErrorRetry": retry_error,
        "groupUnionCutDominates": retry_triangles <= baseline_triangles
            and retry_error <= baseline_error
            and (retry_triangles < baseline_triangles or retry_error < baseline_error),
    }


def rejection_features(row):
    masks = row.get("rejectedMaskCounts", [0] * 32)
    counts = list(map(int, masks))
    total = sum(counts)
    denominator = max(int(row["inputTriangles"]), 1) / 1000.0
    return {
        "rejectsPerKInput": total / denominator,
        "attributeRejectsPerKInput": sum(count for mask, count in enumerate(counts)
                if mask & 4) / denominator,
        "topologyRejectsPerKInput": sum(count for mask, count in enumerate(counts)
                if mask & 1) / denominator,
        "geometryRejectsPerKInput": sum(count for mask, count in enumerate(counts)
                if mask & 2) / denominator,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("lod_graph", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    diagnostics, graph, nodes, by_level = load_inputs(args.diagnostics, args.lod_graph)
    result = {
        "scope": "per-generation group-union cut; no retry timing or rendered metric",
        "diagnostics": str(args.diagnostics),
        "lodGraph": str(args.lod_graph),
        "diagnosticsSchema": diagnostics["schema"],
        "graphNodes": len(nodes),
        "levels": [audit_level(rows, nodes) for _, rows in sorted(by_level.items())],
    }
    payload = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
