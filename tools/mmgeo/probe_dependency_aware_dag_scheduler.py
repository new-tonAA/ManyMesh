#!/usr/bin/env python3
"""Retrospective, dependency-aware replay of learned DAG parent scheduling.

This is a frozen-outcome proxy experiment, not a runtime memory benchmark. It replays
historically observed parent-group outcomes under work budgets and reconstructs complete
cuts by expanding any unavailable parent to its recorded children.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from probe_learned_parent_admission import ASSETS, fit_logistic, load_asset


POLICIES = ("fixed_level", "smallest_work", "boundary", "learned",
            "quality_aware_0p5", "quality_aware_1p0", "quality_aware_2p0",
            "clairvoyant")
BUDGET_FRACTIONS = (0.10, 0.20, 0.30, 0.50, 0.75, 1.00)


def build_asset(name, diagnostic_path):
    path = Path(diagnostic_path)
    diagnostics = json.loads(path.read_text(encoding="utf-8"))
    graph = json.loads(path.with_name("lod_graph.json").read_text(encoding="utf-8"))
    nodes = {int(node["id"]): node for node in graph["dag"]}
    groups = [g for g in diagnostics["groups"] if int(g.get("trial", 0)) == 0]

    output_to_group = {}
    group_to_output = {}
    output_by_children = {}
    for group_index, group in enumerate(groups):
        if not group["promoted"]:
            continue
        key = tuple(sorted(map(int, group["members"])))
        output = next((node for node in graph["dag"]
                       if tuple(sorted(map(int, node.get("children", [])))) == key), None)
        if output is None:
            raise ValueError(f"{name}: promoted group {group_index} has no DAG parent")
        output_id = int(output["id"])
        if output_id in output_to_group:
            raise ValueError(f"{name}: duplicate producer for DAG node {output_id}")
        output_to_group[output_id] = group_index
        group_to_output[group_index] = output
        output_by_children[key] = output_id

    rows, _ = load_asset(name, path)
    if len(rows) != len(groups):
        raise ValueError(f"{name}: feature extraction changed group ordering/count")
    for group, row in zip(groups, rows):
        row["outputTriangles"] = int(group["outputTriangles"])
    for group_index, (group, row) in enumerate(zip(groups, rows)):
        output = group_to_output.get(group_index)
        if output is not None:
            child_error = max((float(nodes[node_id].get("accumulatedError", 0.0))
                               for node_id in map(int, group["members"])), default=0.0)
            row["errorDelta"] = max(0.0, float(output.get("accumulatedError", 0.0)) -
                                    child_error)
        else:
            row["errorDelta"] = None

    producers = set(output_to_group)
    initial_nodes = set()
    for group in groups:
        initial_nodes.update(map(int, group["members"]))
    initial_nodes.difference_update(producers)

    jobs = []
    for group_index, (group, row) in enumerate(zip(groups, rows)):
        member_ids = tuple(map(int, group["members"]))
        deps = sorted({output_to_group[node_id] for node_id in member_ids
                       if node_id in output_to_group})
        output_id = next((node_id for node_id, producer in output_to_group.items()
                          if producer == group_index), None)
        features = np.asarray(row["features"], dtype=np.float64)
        jobs.append({
            "index": group_index,
            "members": member_ids,
            "dependencies": deps,
            "output": output_id,
            "level": int(group["level"]),
            "promoted": bool(group["promoted"]),
            "work": max(int(group["inputTriangles"]) * max(int(group.get("attempts", 0)), 1), 1),
            "triangles_in": int(group["inputTriangles"]),
            "triangles_out": int(group["outputTriangles"]),
            "child_error": float(row["features"][7]),
            "features": features,
        })

    # Validate that each recorded success is produced only after its successful producers.
    for job in jobs:
        if job["promoted"] and any(not jobs[dep]["promoted"] for dep in job["dependencies"]):
            raise ValueError(f"{name}: promoted parent depends on a recorded failed parent")

    return {
        "name": name,
        "nodes": nodes,
        "roots": list(map(int, graph["roots"])),
        "leaves": list(map(int, graph["leaves"])),
        "jobs": jobs,
        "initial_nodes": initial_nodes,
        "feature_rows": rows,
        "base_triangles": int(graph["baseTriangles"]),
    }


def fit_ridge(train_x, train_y, ridge=1.0):
    train_y = np.asarray(train_y, dtype=np.float64)
    mean_x = train_x.mean(axis=0)
    std_x = np.maximum(train_x.std(axis=0), 1e-5)
    x = np.clip((train_x - mean_x) / std_x, -5.0, 5.0)
    mean_y = float(train_y.mean())
    std_y = max(float(train_y.std()), 1e-6)
    y = (train_y - mean_y) / std_y
    weights = np.linalg.solve(x.T @ x + ridge * np.eye(x.shape[1]), x.T @ y)

    def predict(test_x):
        z = np.clip((test_x - mean_x) / std_x, -5.0, 5.0)
        return mean_y + std_y * (z @ weights)

    return predict


def score_jobs(asset, heldout_scores, train_rows, reduction_predictor,
               error_delta_predictor):
    jobs = asset["jobs"]
    train_positive = [r for r in train_rows if r["promoted"]]
    mean_reduction_ratio = float(np.mean([
        max(0.0, r["inputTriangles"] - r["outputTriangles"]) /
        max(r["inputTriangles"], 1) for r in train_positive
    ])) if train_positive else 0.0

    test_x = np.asarray([job["features"] for job in jobs], dtype=np.float64)
    predicted_reduction = np.clip(reduction_predictor(test_x), 0.0, 0.9)
    predicted_error_delta = np.maximum(error_delta_predictor(test_x), 0.0)
    for job, probability, reduction, error_delta in zip(
            jobs, heldout_scores, predicted_reduction, predicted_error_delta):
        job["predicted_reduction"] = float(reduction)
        job["predicted_error_delta"] = float(error_delta)
        predicted_output_error = max(0.0, job["child_error"] + float(error_delta))
        expected_gain_per_work = (float(probability) * float(reduction) *
                                  job["triangles_in"] / job["work"])
        job["rank"] = {
            "fixed_level": (-job["level"], -job["index"]),
            "smallest_work": (-1.0 / job["work"], -job["level"], -job["index"]),
            "boundary": (-float(job["features"][4]), -job["level"], -job["index"]),
            # Expected triangle savings / work, using a train-only mean reduction ratio.
            "learned": (float(probability) * mean_reduction_ratio * job["triangles_in"] /
                        job["work"], float(probability), -job["index"]),
            "quality_aware_0p5": (expected_gain_per_work /
                                  (predicted_output_error + 1e-4) ** 0.5,
                                  float(probability), -job["index"]),
            "quality_aware_1p0": (expected_gain_per_work /
                                  (predicted_output_error + 1e-4),
                                  float(probability), -job["index"]),
            "quality_aware_2p0": (expected_gain_per_work /
                                  (predicted_output_error + 1e-4) ** 2.0,
                                  float(probability), -job["index"]),
            # Feasible hindsight comparator; it knows the captured outcome and reduction.
            "clairvoyant": ((max(0, job["triangles_in"] - job["triangles_out"])
                             if job["promoted"] else 0) / job["work"],
                            float(job["promoted"]), -job["index"]),
        }


def reconstruct_cut(asset, built_outputs):
    nodes = asset["nodes"]
    cut = []

    def visit(node_id):
        node = nodes[node_id]
        if node_id in built_outputs or not node.get("children"):
            cut.append(node_id)
            return
        for child in node["children"]:
            visit(int(child))

    for root in asset["roots"]:
        visit(root)

    leaf_visits = []
    for node_id in cut:
        stack = [node_id]
        while stack:
            current = nodes[stack.pop()]
            children = current.get("children", [])
            if children:
                stack.extend(map(int, children))
            else:
                leaf_visits.append(int(current["id"]))
    expected = sorted(asset["leaves"])
    actual = sorted(leaf_visits)
    exact_cover = actual == expected
    if not exact_cover:
        raise ValueError(f"{asset['name']}: incomplete/overlapping cut: "
                         f"{len(actual)} visits vs {len(expected)} leaves")

    tri_count = sum(int(nodes[node_id]["tri"]) for node_id in cut)
    max_error = max((float(nodes[node_id].get("accumulatedError", 0.0)) for node_id in cut),
                    default=0.0)
    return {"cutNodes": len(cut), "cutTriangles": tri_count,
            "maxAccumulatedErrorProxy": max_error, "exactLeafCover": exact_cover}


def run_policy(asset, policy, budget):
    jobs = asset["jobs"]
    attempted = set()
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
        spent += job["work"]
        if job["promoted"]:
            built_outputs.add(int(job["output"]))
            available_nodes.add(int(job["output"]))

    cut = reconstruct_cut(asset, built_outputs)
    baseline_cut = reconstruct_cut(asset, set())
    return {
        "policy": policy,
        "budgetWork": int(budget),
        "spentWork": int(spent),
        "attemptedGroups": len(attempted),
        "builtPromotedGroups": len(built_outputs),
        "triangleReductionFromNoBuildCut": baseline_cut["cutTriangles"] - cut["cutTriangles"],
        "cut": cut,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    assets = {}
    provenance = []
    for name, relative in ASSETS.items():
        path = root / relative
        asset = build_asset(name, path)
        assets[name] = asset
        provenance.append({"asset": name,
                           "groups": len(asset["jobs"]),
                           "promotedGroups": sum(j["promoted"] for j in asset["jobs"]),
                           "baseTriangles": asset["base_triangles"]})

    replay = []
    for heldout_name, asset in assets.items():
        train_rows = [row for other, other_asset in assets.items() if other != heldout_name
                      for row in other_asset["feature_rows"]]
        train_x = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
        train_y = np.asarray([row["promoted"] for row in train_rows], dtype=np.float64)
        predictor = fit_logistic(train_x, train_y, seed=37 + list(assets).index(heldout_name))
        test_x = np.asarray([row["features"] for row in asset["feature_rows"]], dtype=np.float64)
        scores = predictor(test_x)
        positive_train = [row for row in train_rows if row["promoted"]]
        positive_x = np.asarray([row["features"] for row in positive_train], dtype=np.float64)
        reduction_y = np.asarray([
            max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
            max(row["inputTriangles"], 1) for row in positive_train], dtype=np.float64)
        error_delta_y = np.asarray([row["errorDelta"] for row in positive_train],
                                   dtype=np.float64)
        reduction_model = fit_ridge(positive_x, reduction_y)
        error_model = fit_ridge(positive_x, error_delta_y)
        predicted_reduction = np.clip(reduction_model(test_x), 0.0, 0.9)
        predicted_error_delta = np.maximum(error_model(test_x), 0.0)
        heldout_positive = [row for row in asset["feature_rows"] if row["promoted"]]
        positive_indices = [i for i, row in enumerate(asset["feature_rows"])
                            if row["promoted"]]
        actual_reduction = np.asarray([
            max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
            max(row["inputTriangles"], 1) for row in heldout_positive], dtype=np.float64)
        actual_error_delta = np.asarray([row["errorDelta"] for row in heldout_positive],
                                        dtype=np.float64)
        train_reduction_mean = float(np.mean(reduction_y)) if len(reduction_y) else 0.0
        train_error_delta_mean = float(np.mean(error_delta_y)) if len(error_delta_y) else 0.0
        regression_quality = {
            "heldoutPromotedGroups": len(heldout_positive),
            "reductionFractionMae": float(np.mean(np.abs(
                predicted_reduction[positive_indices] - actual_reduction))),
            "reductionFractionMeanBaselineMae": float(np.mean(np.abs(
                train_reduction_mean - actual_reduction))),
            "errorDeltaMae": float(np.mean(np.abs(
                predicted_error_delta[positive_indices] - actual_error_delta))),
            "errorDeltaMeanBaselineMae": float(np.mean(np.abs(
                train_error_delta_mean - actual_error_delta))),
            "meanActualErrorDelta": float(np.mean(actual_error_delta)),
            "meanPredictedErrorDelta": float(np.mean(
                predicted_error_delta[positive_indices])),
        }
        score_jobs(asset, scores, train_rows, reduction_model, error_model)
        total_work = sum(job["work"] for job in asset["jobs"])
        for fraction in BUDGET_FRACTIONS:
            budget = max(1, int(round(total_work * fraction)))
            for policy in POLICIES:
                run = run_policy(asset, policy, budget)
                run.update({"asset": heldout_name,
                            "budgetFraction": fraction,
                            "fractionOfNoBuildTrianglesReduced":
                                run["triangleReductionFromNoBuildCut"] /
                                max(reconstruct_cut(asset, set())["cutTriangles"], 1)})
                run["predictionQuality"] = regression_quality
                replay.append(run)

    result = {
        "scope": "leave-one-asset-out, frozen-outcome, dependency-aware DAG replay",
        "warning": "work is input-triangles times observed attempts; memory is not measured; "
                   "cut quality uses accumulatedError and triangle count, not raster loss; "
                   "the clairvoyant row is a feasible hindsight priority, not an optimum bound",
        "assets": provenance,
        "budgetFractions": BUDGET_FRACTIONS,
        "policies": POLICIES,
        "replay": replay,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assets": provenance, "replayCount": len(replay),
                      "resultPath": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
