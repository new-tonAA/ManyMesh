#!/usr/bin/env python3
"""Enumerate the exact finite group-size schedule oracle and a greedy control."""

import hashlib
import itertools
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "out/targetbudget-heldout-20261116/seven_asset_summary.json"
OUTPUT = ROOT / "out/targetbudget-heldout-20261116/config_oracle.json"
OUTPUT_MD = ROOT / "tools/mmgeo/TARGET_BUDGET_CONFIG_ORACLE_20261116.md"
ASSET_ORDER = ("pirate", "monkey", "cloth", "material_sphere", "shapes")
UNIFORM_GROUPS = (2, 8, 16, 32)  # group 4 is unavailable for Shapes at an equal face budget


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def objective(schedule, options):
    return sum(options[asset][group]["relativeSse"] for asset, group in schedule.items()) / len(schedule)


def total_cost(schedule, options):
    return sum(options[asset][group]["wallSeconds"] for asset, group in schedule.items())


def choose_schedule(cap, options):
    choices = [tuple(options[asset]) for asset in ASSET_ORDER]
    best = None
    for groups in itertools.product(*choices):
        schedule = dict(zip(ASSET_ORDER, groups))
        cost = total_cost(schedule, options)
        if cost > cap + 1e-12:
            continue
        score = objective(schedule, options)
        key = (score, cost, groups)
        if best is None or key < best[0]:
            best = (key, schedule)
    if best is None:
        raise ValueError(f"no tested schedule fits cost cap {cap}")
    key, schedule = best
    return {"schedule": schedule, "relativeSseMean": key[0],
            "totalWallSeconds": key[1]}


def greedy_schedule(cap, options):
    schedule = {asset: 2 for asset in ASSET_ORDER}
    while True:
        current_cost = total_cost(schedule, options)
        current_score = objective(schedule, options)
        moves = []
        for asset in ASSET_ORDER:
            old_group = schedule[asset]
            for new_group in options[asset]:
                if new_group == old_group:
                    continue
                candidate = dict(schedule)
                candidate[asset] = new_group
                new_cost = total_cost(candidate, options)
                new_score = objective(candidate, options)
                gain = current_score - new_score
                delta_cost = new_cost - current_cost
                if gain <= 1e-15 or new_cost > cap + 1e-12:
                    continue
                ratio = float("inf") if delta_cost <= 0 else gain / delta_cost
                # Stable tie-breaking: largest gain per extra second, then lower cost,
                # lower objective, asset order, then group size.
                moves.append((-ratio, new_cost, new_score,
                        ASSET_ORDER.index(asset), new_group, candidate))
        if not moves:
            return {"schedule": schedule, "relativeSseMean": current_score,
                    "totalWallSeconds": current_cost}
        schedule = min(moves, key=lambda item: item[:-1])[-1]


def main():
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    asset_rows = {row["asset"]: row for row in source["assetSummaries"]}
    options = {}
    for asset in ASSET_ORDER:
        row = asset_rows[asset]
        groups = {entry["groupSize"]: entry for entry in row["groups"]
                if entry["visibilityAudited"]}
        baseline = groups[2]["visibilitySse"]
        if baseline <= 0:
            raise ValueError(f"invalid group-2 baseline for {asset}")
        options[asset] = {
            group: {
                "wallSeconds": data["wallMedianSeconds"],
                "dagBuildSeconds": data["buildMedianSeconds"],
                "visibilitySse": data["visibilitySse"],
                "relativeSse": data["visibilitySse"] / baseline,
                "selectedTriangles": data["selectedTriangles"],
                "screenErrorPx": data["screenErrorPx"],
            } for group, data in groups.items()
        }

    valid_group_intersection = set.intersection(*(set(options[asset])
            for asset in ASSET_ORDER))
    uniform_results = []
    for group in UNIFORM_GROUPS:
        if group not in valid_group_intersection:
            continue
        schedule = {asset: group for asset in ASSET_ORDER}
        cap = total_cost(schedule, options)
        uniform_results.append({
            "fixedGroup": group,
            "budgetCapSeconds": cap,
            "relativeSseMean": objective(schedule, options),
            "schedule": schedule,
            "finiteGridOracle": choose_schedule(cap, options),
            "marginalGreedy": greedy_schedule(cap, options),
        })
    for row in uniform_results:
        eligible_fixed = [candidate for candidate in uniform_results
                if candidate["budgetCapSeconds"] <= row["budgetCapSeconds"] + 1e-12]
        best_fixed = min(eligible_fixed, key=lambda candidate:
                (candidate["relativeSseMean"], candidate["budgetCapSeconds"]))
        row["bestFixedUnderBudget"] = {
            "group": best_fixed["fixedGroup"],
            "costSeconds": best_fixed["budgetCapSeconds"],
            "relativeSseMean": best_fixed["relativeSseMean"],
        }

    all_best = {asset: min(options[asset], key=lambda group:
            (options[asset][group]["relativeSse"],
             options[asset][group]["wallSeconds"])) for asset in ASSET_ORDER}
    all_best_cost = total_cost(all_best, options)
    configuration_count = math.prod(len(options[asset]) for asset in ASSET_ORDER)
    result = {
        "scope": "exact enumeration of the measured finite group-size grid for five exactly budget-matched assets; build wall-time only; no peak-memory data",
        "qualityObjective": "equal-weight mean over assets of each candidate's 16-view filtered coverage/depth SSE divided by that asset's group-2 SSE; lower is better; group-2 all-asset schedule equals 1",
        "costObjective": "sum of per-asset median whole-process wall seconds from serial single-asset builds on the same machine; does not include combined scene rendering or peak memory",
        "inputs": {
            "summary": str(INPUT.relative_to(ROOT)),
            "summarySha256": sha256(INPUT),
            "assetOrder": list(ASSET_ORDER),
            "testedGroupOptions": {asset: sorted(options[asset]) for asset in ASSET_ORDER},
            "enumeratedSchedules": configuration_count,
        },
        "enumeration": {
            "configurationCount": configuration_count,
            "exactQualityMinimumSchedule": all_best,
            "exactQualityMinimumCostSeconds": all_best_cost,
            "exactQualityMinimumMeanRelativeSse": objective(all_best, options),
            "uniformGroupBaselinesAndMatchedBudgetOracles": uniform_results,
            "allAssetGroup2CostSeconds": total_cost(
                    {asset: 2 for asset in ASSET_ORDER}, options),
        },
        "perAssetOptions": options,
    }
    result["analysisScript"] = {"path": str(Path(__file__).relative_to(ROOT)),
            "sha256": sha256(Path(__file__))}
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Finite-Grid Target-Budget Configuration Oracle (2026-11-16)",
        "",
        "## Definition",
        "",
        "This is an exact enumeration of the configurations already measured for the five meshes with exactly equal candidate triangle counts across group settings: Pirate, Monkey, Cloth, Material Sphere, and Shapes. It enumerates the Cartesian product of the per-asset group-size settings (Shapes g4 is excluded because its cut has one extra triangle). No new algorithm is claimed.",
        "",
        "Quality is the equal-weight mean across assets of (candidate 16-view filtered coverage/depth SSE / that asset's g2 SSE), so the all-g2 schedule has quality score 1. This normalization prevents the large absolute Pirate error from dominating simply because its SSE has different scale. Lower is better; it is a study objective, not perceptual calibration.",
        "",
        "Construction budget is the sum of per-asset median whole-process wall seconds from the randomized serial builds on one executable/machine. It assumes assets are built sequentially and omits peak-memory limits, combined-scene rendering, cache effects, and scheduling overhead. Each oracle row minimizes the quality score over every enumerated schedule whose cost is at most the matched fixed-group budget.",
        "",
        f"The exact search enumerated {configuration_count:,} schedules. Its unconstrained per-asset best schedule is `{json.dumps(all_best, sort_keys=True)}`, cost {all_best_cost:.2f}s, normalized mean SSE {objective(all_best, options):.4f}.",
        "",
        "## Matched-budget results",
        "",
        "| Budget cap from uniform g | Cap (sum wall s) | Best fixed group under cap / score | Finite-grid oracle schedule | Oracle cost s | Oracle score | Marginal greedy schedule | Greedy cost s | Greedy score |",
        "|---:|---:|---|---|---:|---:|---|---:|---:|",
    ]
    for row in uniform_results:
        oracle = row["finiteGridOracle"]
        greedy = row["marginalGreedy"]
        best_fixed = row["bestFixedUnderBudget"]
        lines.append(
            f"| {row['fixedGroup']} | {row['budgetCapSeconds']:.2f} | g{best_fixed['group']} / "
            f"{best_fixed['relativeSseMean']:.4f} | "
            f"`{json.dumps(oracle['schedule'], sort_keys=True)}` | {oracle['totalWallSeconds']:.2f} | "
            f"{oracle['relativeSseMean']:.4f} | `{json.dumps(greedy['schedule'], sort_keys=True)}` | "
            f"{greedy['totalWallSeconds']:.2f} | {greedy['relativeSseMean']:.4f} |"
        )
    lines += [
        "",
        "The table omits uniform g4 because Shapes lacks an exactly matched cut at that setting. The oracle is exact only over this finite, already measured parameter grid; it does not search node-local repairs, new DAG structures, or continuous settings. The greedy control repeatedly takes the currently available one-asset switch with the largest normalized SSE reduction per added wall second, skipping switches that exceed the current cap. It is a deliberately simple baseline and is not represented as state of the art.",
        "",
        "## Interpretation and next decision",
        "",
        "Any oracle advantage over one global group size is an asset-configuration allocation baseline, not a novel result. The useful remaining question is whether construction effort can be allocated *within* an asset so as to create additional complete, strict-gate-valid cuts, beyond choosing among prebuilt fixed group sizes. That requires a distinct candidate-generation mechanism and gate-matched HLOD ASAP/DAG2/cluster-LOD comparisons.",
        "",
        "At the four caps tested, the one-step marginal greedy schedule matches the finite-grid oracle exactly. That weakens the case for a sophisticated *per-asset group-size scheduler*: on these data, a trivial heuristic recovers the entire measured-grid frontier. Any remaining method must add value inside an asset by constructing new valid hierarchy alternatives. This still does not prove that such a mechanism is novel.",
        "The experiment does not meet the full planned resource match because peak memory was not recorded. Repeating all grid configurations with process peak-working-set capture is required before saying the oracle is matched in both wall time and memory. The quality objective is based on five meshes, one target ratio, one elevation, and an uncalibrated geometry-only raster proxy; no result here establishes perceptual quality, generalization, novelty, or SIGGRAPH readiness.",
        "",
        "Machine-readable input/output hashes and all individual settings: `out/targetbudget-heldout-20261116/config_oracle.json`.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "enumeratedSchedules": configuration_count,
        "allBestSchedule": all_best,
        "allBestCostSeconds": all_best_cost,
        "allBestMeanRelativeSse": objective(all_best, options),
        "fixedBaselines": uniform_results,
        "output": str(OUTPUT),
        "report": str(OUTPUT_MD),
    }, indent=2))


if __name__ == "__main__":
    main()
