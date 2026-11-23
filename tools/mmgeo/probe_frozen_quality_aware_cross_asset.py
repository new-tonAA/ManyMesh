#!/usr/bin/env python3
"""Evaluate a frozen quality-aware DAG priority on additional held-out meshes.

The inverse-error exponent is fixed at 1.0 from the prior four-asset development screen.
This leave-one-new-asset-out replay uses historical outcomes and triangle-work proxies; it
does not measure RSS, wall time, I/O, or rendered image error.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from probe_dependency_aware_dag_scheduler import (
    BUDGET_FRACTIONS,
    build_asset,
    fit_ridge,
    reconstruct_cut,
    run_policy,
    score_jobs,
)
from probe_learned_parent_admission import fit_logistic


DATASETS = {
    # Development geometries used by the prior screen.
    "cloth": "out/quality-witness-current/cloth-regroup-pilot-200k/diagnostics.json",
    "material_sphere": "out/quality-witness-current/material-sphere-regroup-pilot-200k/diagnostics.json",
    "monkey": "out/quality-witness-current/monkey-regroup-pilot-200k/diagnostics.json",
    "shapes": "out/quality-witness-current/shapes-regroup-pilot-200k/diagnostics.json",
    # Additional geometries, not used to choose the frozen exponent.
    "crease": "out/regroup-diagnostics-cache-fix/crease-4/diagnostics.json",
    "pirate": "out/regroup-diagnostics-cache-fix/pirate-4/diagnostics.json",
    "smooth": "out/regroup-diagnostics-cache-fix/smooth-4/diagnostics.json",
    "thin": "out/regroup-diagnostics-cache-fix/thin-4/diagnostics.json",
    "torus": "out/regroup-diagnostics-cache-fix/torus-4/diagnostics.json",
    "uv": "out/regroup-diagnostics-cache-fix/uv-4/diagnostics.json",
}
NEW_HOLDOUTS = ("crease", "pirate", "smooth", "thin", "torus", "uv")
POLICIES = ("fixed_level", "smallest_work", "boundary", "quality_aware_1p0",
            "clairvoyant")
EVALUATION_BUDGETS = (0.10, 0.20, 0.50)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def regression_summary(train_rows, test_rows, reduction_model, error_model):
    positive_train = [row for row in train_rows if row["promoted"]]
    positive_test = [row for row in test_rows if row["promoted"]]
    if not positive_test:
        return {"heldoutPromotedGroups": 0}

    test_x = np.asarray([row["features"] for row in positive_test], dtype=np.float64)
    pred_reduction = np.clip(reduction_model(test_x), 0.0, 0.9)
    pred_delta = np.maximum(error_model(test_x), 0.0)
    actual_reduction = np.asarray([
        max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
        max(row["inputTriangles"], 1) for row in positive_test], dtype=np.float64)
    actual_delta = np.asarray([row["errorDelta"] for row in positive_test], dtype=np.float64)
    train_reduction = np.asarray([
        max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
        max(row["inputTriangles"], 1) for row in positive_train], dtype=np.float64)
    train_delta = np.asarray([row["errorDelta"] for row in positive_train], dtype=np.float64)
    return {
        "heldoutPromotedGroups": len(positive_test),
        "reductionMae": float(np.mean(np.abs(pred_reduction - actual_reduction))),
        "reductionTrainMeanMae": float(np.mean(np.abs(train_reduction.mean() -
                                                       actual_reduction))),
        "errorDeltaMae": float(np.mean(np.abs(pred_delta - actual_delta))),
        "errorDeltaTrainMeanMae": float(np.mean(np.abs(train_delta.mean() - actual_delta))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    assets = {}
    provenance = []
    for name, relative in DATASETS.items():
        path = root / relative
        asset = build_asset(name, path)
        graph = json.loads(path.with_name("lod_graph.json").read_text(encoding="utf-8"))
        asset["source"] = graph.get("source")
        assets[name] = asset
        provenance.append({
            "asset": name,
            "source": asset["source"],
            "diagnosticsSha256": sha256(path),
            "lodGraphSha256": sha256(path.with_name("lod_graph.json")),
            "groups": len(asset["jobs"]),
            "promotedGroups": sum(job["promoted"] for job in asset["jobs"]),
            "baseTriangles": asset["base_triangles"],
            "role": "new-heldout" if name in NEW_HOLDOUTS else "development-training",
        })

    replay = []
    for heldout_name in NEW_HOLDOUTS:
        asset = assets[heldout_name]
        train_rows = [row for name, candidate in assets.items() if name != heldout_name
                      for row in candidate["feature_rows"]]
        train_x = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
        train_y = np.asarray([row["promoted"] for row in train_rows], dtype=np.float64)
        test_x = np.asarray([row["features"] for row in asset["feature_rows"]],
                            dtype=np.float64)
        success_model = fit_logistic(train_x, train_y, seed=1907 + NEW_HOLDOUTS.index(heldout_name))

        positive_train = [row for row in train_rows if row["promoted"]]
        positive_x = np.asarray([row["features"] for row in positive_train], dtype=np.float64)
        reduction_y = np.asarray([
            max(0.0, row["inputTriangles"] - row["outputTriangles"]) /
            max(row["inputTriangles"], 1) for row in positive_train], dtype=np.float64)
        error_delta_y = np.asarray([row["errorDelta"] for row in positive_train],
                                   dtype=np.float64)
        reduction_model = fit_ridge(positive_x, reduction_y)
        error_model = fit_ridge(positive_x, error_delta_y)
        scores = success_model(test_x)
        score_jobs(asset, scores, train_rows, reduction_model, error_model)
        prediction = regression_summary(train_rows, asset["feature_rows"],
                                        reduction_model, error_model)

        total_work = sum(job["work"] for job in asset["jobs"])
        no_build_triangles = reconstruct_cut(asset, set())["cutTriangles"]
        for fraction in EVALUATION_BUDGETS:
            budget = max(1, int(round(total_work * fraction)))
            for policy in POLICIES:
                result = run_policy(asset, policy, budget)
                reduced_fraction = (result["triangleReductionFromNoBuildCut"] /
                                    max(no_build_triangles, 1))
                if not -1e-9 <= reduced_fraction <= 1.0 + 1e-9:
                    raise ValueError(f"{heldout_name}: invalid triangle reduction fraction "
                                     f"{reduced_fraction}; check cut baseline reconstruction")
                result.update({
                    "asset": heldout_name,
                    "budgetFraction": fraction,
                    "fractionOfNoBuildTrianglesReduced": reduced_fraction,
                    "predictionQuality": prediction,
                })
                replay.append(result)

    output = {
        "scope": "frozen exponent 1.0, leave-one-additional-geometry-out replay",
        "frozenPolicy": "P(promote) * predictedReduction / work / predictedOutputError",
        "selectionNote": "exponent was fixed before examining the six additional geometry results; "
                         "the initial four geometries were used in prior development screens",
        "warning": "historical outcomes; triangle work is inputTriangles*attempts; error is "
                   "accumulatedError proxy, not rendered image loss; no RSS, wall-time, or I/O "
                   "measurement; new holdout assets with fewer than 10 groups are descriptive only",
        "datasets": provenance,
        "newHoldouts": NEW_HOLDOUTS,
        "budgets": EVALUATION_BUDGETS,
        "policies": POLICIES,
        "replay": replay,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"datasetCount": len(provenance),
                      "newHoldouts": [{"asset": p["asset"], "groups": p["groups"],
                                       "promotedGroups": p["promotedGroups"]}
                                      for p in provenance if p["role"] == "new-heldout"],
                      "replayCount": len(replay), "result": str(args.out)}, indent=2))
if __name__ == "__main__":
    main()
