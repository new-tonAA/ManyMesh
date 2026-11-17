"""Reload serialized BVHs; verify queries, counters, cohorts, and cost sensitivity."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from visibility_query_bvh import BVH, Hybrid, Ray


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(binding):
    if sha(binding["path"]) != binding["sha256"]:
        raise ValueError("bound artifact changed: " + binding["path"])


def load_tree(binding):
    require(binding)
    with np.load(binding["path"], allow_pickle=False) as arrays:
        data = dict(arrays)
    if sum(a.nbytes for a in data.values()) != binding["packedBytes"]:
        raise ValueError("packed payload count differs")
    # Fine/coarse primitive bounds are build data; mesh query uses node bounds.
    runtime_bytes = sum(a.nbytes for key, a in data.items() if key != "bounds" or "triangles" not in data)
    return BVH.from_packed(data), runtime_bytes


def trace(query, rays):
    answers, costs = [], []
    for ray in rays:
        count = [0, 0, 0]
        answers.append(query.query(ray, count))
        costs.append(count)
    return np.array(answers, bool), np.array(costs, np.int64)


def sensitivity(fine, hybrid):
    boxes, triangles, cones = (hybrid - fine).tolist()
    rows = []
    for cone_cost in (0, .25, .5, 1, 2):
        # Let AABB cost=1, triangle cost=w and cone cost=k; need dB+w*dT+k*dC<0.
        numerator = boxes + cone_cost * cones
        if triangles < 0:
            rows.append(dict(coneToBoxCost=cone_cost,
                strictGainRequiresTriangleToBoxCostAbove=max(0., numerator / -triangles)))
        else:
            rows.append(dict(coneToBoxCost=cone_cost, strictGainRequiresTriangleToBoxCostAbove=None,
                noPositiveTriangleWeightHelpsWhenNumeratorNonnegative=numerator >= 0))
    models = []
    for triangle_cost in (1, 2, 4, 8):
        for cone_cost in (.25, .5, 1):
            weights = np.array([1, triangle_cost, cone_cost])
            models.append(dict(triangleToBoxCost=triangle_cost, coneToBoxCost=cone_cost,
                hybridOverFineWeightedWork=float(hybrid @ weights / (fine @ weights))))
    return dict(counterDelta=[boxes, triangles, cones],
        hybridDominatedInAllPrimitiveCounts=boxes >= 0 and triangles >= 0 and cones >= 0,
        triangleCostThresholds=rows, hypotheticalCostModels=models)


def oracle_controls(fine_costs, coarse_costs, fine_answers, coarse_answers, decisions):
    # These have access to hidden query outcomes/costs and pay zero selection cost.
    # They are offline controls, never runtime performance predictions.
    compact_oracle = fine_costs.copy()
    compact_oracle[decisions == "coarse"] = coarse_costs[decisions == "coarse"]
    mismatch = fine_answers != coarse_answers
    rows = []
    for triangle_cost in (1, 2, 4, 8):
        weights = np.array([1, triangle_cost, 0])
        a, b = fine_costs @ weights, coarse_costs @ weights
        optimal = np.where(mismatch, a, np.minimum(a, b))
        rows.append(dict(triangleToBoxCost=triangle_cost,
            freeCompactClassifierOverFineWork=float((compact_oracle @ weights).sum() / a.sum()),
            perfectFreeOutcomeAndCostSwitchOverFineWork=float(optimal.sum() / a.sum())))
    return dict(freeCompactClassifierCounters=compact_oracle.sum(0).tolist(), models=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report["kernelSha256"] != sha(Path(__file__).with_name("visibility_query_bvh.py")):
        raise ValueError("query kernel changed")
    if report["scriptSha256"] != sha(Path(__file__).with_name("benchmark_visibility_query_bvh.py")):
        raise ValueError("benchmark changed")
    require(report["priorSupportReport"])
    cases, checked = [], 0
    for asset in report["assets"]:
        for field in ("capture", "manifest", "rayArtifact"):
            require(asset[field])
        with np.load(asset["rayArtifact"]["path"], allow_pickle=False) as archive:
            ray_data = dict(archive)
        rays = [Ray(tuple(o), tuple(d), float(t)) for o, d, t in zip(
            ray_data["origins"], ray_data["directions"], ray_data["maximum"])]
        cohort_masks = dict(viewport=np.ones(len(rays), bool),
                            sourceRectangle=ray_data["sourceRectangle"],
                            fineHits=ray_data["fineExpected"], fineMisses=~ray_data["fineExpected"])
        for ratio, level in asset["levels"].items():
            require(level["costArtifact"])
            with np.load(level["costArtifact"]["path"], allow_pickle=False) as archive:
                saved = dict(archive)
            fine, fine_bytes = load_tree(level["trees"]["fine"])
            coarse, coarse_bytes = load_tree(level["trees"]["coarse"])
            support, support_bytes = load_tree(level["trees"]["support"])
            hybrid = Hybrid(fine, coarse, support)
            for name, tree, expected in (("fine", fine, ray_data["fineExpected"]),
                                        ("coarse", coarse, ray_data["coarseExpected_" + ratio]),
                                        ("hybrid", hybrid, ray_data["fineExpected"])):
                answers, counts = trace(tree, rays)
                if not (np.array_equal(answers, expected) and np.array_equal(answers, saved[name + "Answers"])
                        and np.array_equal(counts, saved[name + "Costs"])):
                    raise ValueError(f"serialized query/cost mismatch {asset['asset']} {ratio} {name}")
                checked += len(rays)
            select_counts, decisions = [], []
            for ray in rays:
                count = [0, 0, 0]
                decisions.append(hybrid.classify(ray, count)[0])
                select_counts.append(count)
            if not (np.array_equal(saved["decisions"], decisions)
                    and np.array_equal(saved["selectorCosts"], select_counts)):
                raise ValueError("selector accounting changed")
            for cohort, mask in cohort_masks.items():
                for label, key in (("fine", "fineCosts"), ("hybrid", "hybridCosts"),
                                   ("selector", "selectorCosts"), ("coarseBiased", "coarseCosts")):
                    statistics = level["cohorts"][cohort][label]
                    if statistics["rays"] != int(mask.sum()) or statistics["sums"] != saved[key][mask].sum(0).tolist():
                        raise ValueError("cohort totals differ")
            cohorts = {}
            for cohort, mask in cohort_masks.items():
                if not np.any(mask):
                    continue
                a, b = saved["fineCosts"][mask].sum(0), saved["hybridCosts"][mask].sum(0)
                cohorts[cohort] = sensitivity(a, b)
                cohorts[cohort]["oracles"] = oracle_controls(
                    saved["fineCosts"][mask], saved["coarseCosts"][mask],
                    saved["fineAnswers"][mask], saved["coarseAnswers"][mask], saved["decisions"][mask])
            cases.append(dict(asset=asset["asset"], ratio=ratio,
                runtimeArrayPayloadBytes=dict(fine=fine_bytes, coarse=coarse_bytes, support=support_bytes),
                hybridOverFineRuntimePayload=(fine_bytes + coarse_bytes + support_bytes) / fine_bytes,
                queryPythonFineOverHybridTime=level["medianFineOverHybridPythonTime"], cohorts=cohorts))
            print(asset["asset"], ratio, "serialized kernels and full costs validated", flush=True)
    result = dict(reportSha256=sha(args.report), validatorSha256=sha(__file__),
                  checkedRayQueries=checked, cases=cases,
                  caveat="cost weights are hypothetical; array payload excludes Python overhead and is not GPU memory")
    (args.report.parent / "validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("validated", checked, "ray queries", flush=True)


if __name__ == "__main__":
    main()
