#!/usr/bin/env python3
"""Exact finite-grid configuration oracle with serial wall-time and peak-memory caps."""

import hashlib
import itertools
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "out/targetbudget-heldout-20261116/seven_asset_summary.json"
CORE_MEMORY = ROOT / "out/targetbudget-heldout-20261116/peak_memory_core.json"
HELDOUT_MEMORY = ROOT / "out/targetbudget-heldout-20261116/peak_memory_v2.json"
CORE_REPEAT_SUMMARY = ROOT / "out/targetbudget-repeat-control-20261116/summary.json"
HELDOUT_BUILD_SUMMARY = ROOT / "out/targetbudget-heldout-20261116/builds_summary.json"
OUTPUT = ROOT / "out/targetbudget-heldout-20261116/resource_oracle.json"
OUTPUT_MD = ROOT / "tools/mmgeo/TARGET_BUDGET_RESOURCE_ORACLE_20261116.md"
ASSETS = ("pirate", "monkey", "cloth", "material_sphere", "shapes")
UNIFORM_GROUPS = (2, 8, 16, 32)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def score(schedule, options):
    return sum(options[a][g]["relativeSse"] for a, g in schedule.items()) / len(schedule)


def wall_cost(schedule, options):
    return sum(options[a][g]["wallMedianSeconds"] for a, g in schedule.items())


def peak(schedule, options, field):
    return max(options[a][g][field] for a, g in schedule.items())


def fits(schedule, options, time_cap, ws_cap, commit_cap):
    return (wall_cost(schedule, options) <= time_cap + 1e-12
            and peak(schedule, options, "peakWorkingSetBytes") <= ws_cap
            and peak(schedule, options, "peakCommitBytes") <= commit_cap)


def exact_oracle(options, time_cap, ws_cap, commit_cap):
    groups = [tuple(options[asset]) for asset in ASSETS]
    best = None
    for combination in itertools.product(*groups):
        schedule = dict(zip(ASSETS, combination))
        if not fits(schedule, options, time_cap, ws_cap, commit_cap):
            continue
        key = (score(schedule, options), wall_cost(schedule, options),
                peak(schedule, options, "peakWorkingSetBytes"),
                peak(schedule, options, "peakCommitBytes"), combination)
        if best is None or key < best[0]:
            best = (key, schedule)
    if best is None:
        return None
    key, schedule = best
    return {"schedule": schedule, "relativeSseMean": key[0],
            "wallSeconds": key[1], "peakWorkingSetBytes": key[2],
            "peakCommitBytes": key[3]}


def greedy(options, start_group, time_cap, ws_cap, commit_cap):
    schedule = {asset: start_group for asset in ASSETS}
    if not fits(schedule, options, time_cap, ws_cap, commit_cap):
        return None
    while True:
        current_score = score(schedule, options)
        current_wall = wall_cost(schedule, options)
        moves = []
        for asset in ASSETS:
            for group in options[asset]:
                if group == schedule[asset]:
                    continue
                candidate = dict(schedule)
                candidate[asset] = group
                if not fits(candidate, options, time_cap, ws_cap, commit_cap):
                    continue
                gain = current_score - score(candidate, options)
                delta = wall_cost(candidate, options) - current_wall
                if gain <= 1e-15:
                    continue
                ratio = float("inf") if delta <= 0 else gain / delta
                moves.append((-ratio, wall_cost(candidate, options),
                        score(candidate, options), ASSETS.index(asset), group, candidate))
        if not moves:
            break
        schedule = min(moves, key=lambda row: row[:-1])[-1]
    return {"schedule": schedule, "relativeSseMean": score(schedule, options),
            "wallSeconds": wall_cost(schedule, options),
            "peakWorkingSetBytes": peak(schedule, options, "peakWorkingSetBytes"),
            "peakCommitBytes": peak(schedule, options, "peakCommitBytes")}


def main():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    core_memory = json.loads(CORE_MEMORY.read_text(encoding="utf-8"))
    heldout_memory = json.loads(HELDOUT_MEMORY.read_text(encoding="utf-8"))
    core_repeats = json.loads(CORE_REPEAT_SUMMARY.read_text(encoding="utf-8"))
    heldout_builds = json.loads(HELDOUT_BUILD_SUMMARY.read_text(encoding="utf-8"))
    memory_records = core_memory["records"] + heldout_memory["records"]
    memory_by_key = {(r["asset"], r["groupSize"]): r for r in memory_records}
    if len(memory_by_key) != 35:
        raise ValueError(f"expected 35 unique peak-memory samples, got {len(memory_by_key)}")

    core_hash = {(r["asset"], r["groupSize"]): r["repeatedGraphHashes"][0]
            for r in core_repeats["summaries"]}
    heldout_hash = {(r["asset"], r["groupSize"]): r["graphSha256"]
            for r in heldout_builds["summaries"]}
    expected_graphs = {**core_hash, **heldout_hash}
    expected_sources = {asset: summary["visibilityInputs"][asset]["sourceHash"]
            for asset in ASSETS}
    options = {}
    for asset in ASSETS:
        asset_row = next(r for r in summary["assetSummaries"] if r["asset"] == asset)
        groups = {}
        for row in asset_row["groups"]:
            if not row["visibilityAudited"]:
                continue
            key = (asset, row["groupSize"])
            memory = memory_by_key[key]
            if memory["graphSha256"] != expected_graphs[key]:
                raise ValueError(f"memory capture graph mismatch: {key}")
            if memory["sourceSha256"] != expected_sources[asset]:
                raise ValueError(f"memory capture source mismatch: {key}")
            groups[row["groupSize"]] = {
                "wallMedianSeconds": row["wallMedianSeconds"],
                "dagBuildMedianSeconds": row["buildMedianSeconds"],
                "visibilitySse": row["visibilitySse"],
                "relativeSse": row["visibilitySse"] / asset_row["groups"][0]["visibilitySse"],
                "selectedTriangles": row["selectedTriangles"],
                "peakWorkingSetBytes": memory["peakWorkingSetBytes"],
                "peakCommitBytes": memory["peakPagefileBytes"],
                "memoryCaptureWallSeconds": memory["wallSeconds"],
            }
        options[asset] = groups

    uniform = []
    for group in UNIFORM_GROUPS:
        if any(group not in options[asset] for asset in ASSETS):
            continue
        baseline = {asset: group for asset in ASSETS}
        time_cap = wall_cost(baseline, options)
        ws_cap = peak(baseline, options, "peakWorkingSetBytes")
        commit_cap = peak(baseline, options, "peakCommitBytes")
        oracle = exact_oracle(options, time_cap, ws_cap, commit_cap)
        greedy_result = greedy(options, group, time_cap, ws_cap, commit_cap)
        eligible_fixed = []
        for fixed_group in UNIFORM_GROUPS:
            fixed = {asset: fixed_group for asset in ASSETS}
            if fits(fixed, options, time_cap, ws_cap, commit_cap):
                eligible_fixed.append((score(fixed, options), wall_cost(fixed, options), fixed_group))
        best_fixed = min(eligible_fixed) if eligible_fixed else None
        oracle_gain_percent = None if oracle is None or best_fixed is None else (
                100.0 * (best_fixed[0] - oracle["relativeSseMean"]) / best_fixed[0])
        greedy_gap_percent = None if oracle is None or greedy_result is None else (
                100.0 * (greedy_result["relativeSseMean"] - oracle["relativeSseMean"])
                / oracle["relativeSseMean"])
        uniform.append({
            "budgetSourceGroup": group,
            "timeCapSeconds": time_cap,
            "peakWorkingSetCapBytes": ws_cap,
            "peakCommitCapBytes": commit_cap,
            "uniformSchedule": baseline,
            "uniformScore": score(baseline, options),
            "oracle": oracle,
            "oracleGainOverBestFixedPercent": oracle_gain_percent,
            "marginalGreedy": greedy_result,
            "greedyGapToOraclePercent": greedy_gap_percent,
            "bestFeasibleFixedGroup": None if best_fixed is None else {
                "group": best_fixed[2], "score": best_fixed[0], "wallSeconds": best_fixed[1]},
        })

    all_best = {asset: min(options[asset], key=lambda g:
            (options[asset][g]["relativeSse"], options[asset][g]["wallMedianSeconds"]))
            for asset in ASSETS}
    all_best_stats = {"schedule": all_best, "score": score(all_best, options),
            "wallSeconds": wall_cost(all_best, options),
            "peakWorkingSetBytes": peak(all_best, options, "peakWorkingSetBytes"),
            "peakCommitBytes": peak(all_best, options, "peakCommitBytes")}
    count = math.prod(len(options[asset]) for asset in ASSETS)
    result = {
        "scope": "exact enumeration of the 2,500 measured settings combinations for five exact-face-budget assets; serial wall-time, peak working-set and peak process commit constraints",
        "qualityObjective": "equal-weight average of each asset's candidate 16-view filtered coverage/depth SSE divided by its g2 SSE; lower is better",
        "costObjective": "sum of per-asset median full-process wall seconds for serial builds; one process per asset",
        "memoryObjective": "maximum single-process PeakWorkingSetSize and PeakPagefileUsage across the serial asset builds; memory measured once per setting with Windows GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)",
        "inputs": {p.name: {"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in (
            SUMMARY, CORE_MEMORY, HELDOUT_MEMORY, CORE_REPEAT_SUMMARY, HELDOUT_BUILD_SUMMARY)},
        "enumeratedSchedules": count,
        "uniformBudgetsAndOracles": uniform,
        "unconstrainedQualityBest": all_best_stats,
        "perAssetOptions": options,
        "analysisScript": {"path": str(Path(__file__).relative_to(ROOT)),
                "sha256": sha256(Path(__file__))},
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Finite-Grid Target-Budget Resource Oracle (2026-11-16)",
        "",
        "## Definition and resource evidence",
        "",
        "This exact enumeration covers 2,500 schedules over Pirate, Monkey, Cloth, Material Sphere and Shapes. Shapes g4 is excluded because it has one extra triangle. Quality is the equal-weight mean of each mesh's 16-view filtered coverage/depth SSE normalized by its own g2 SSE. The serial wall budget is the sum of per-asset median full-process wall times from three randomized builds. The peak-memory cap is the maximum single-process peak across the sequence, not a sum.",
        "",
        "Peak working set and peak process commit were captured once per group setting through Windows `GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)`. Microsoft documents `PeakWorkingSetSize` as peak resident working set and `PeakPagefileUsage` as peak commit charge. See the [official structure documentation](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex). Each memory run's graph/source hashes were checked against the repeated build manifests. These are single memory samples per configuration; timing has three repetitions, memory does not.",
        "",
        "## Matched time and memory results",
        "",
        "| Cap source | Wall cap s | Peak WS cap MiB | Peak commit cap MiB | Best feasible fixed group / score | Exact oracle schedule / score | Oracle cost s | Oracle peak WS MiB | Oracle gain over fixed | Greedy score / schedule | Greedy gap to oracle |",
        "|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|",
    ]
    for row in uniform:
        oracle = row["oracle"]
        greedy_result = row["marginalGreedy"]
        fixed = row["bestFeasibleFixedGroup"]
        fixed_text = "none" if fixed is None else f"g{fixed['group']} / {fixed['score']:.4f}"
        oracle_text = "none" if oracle is None else (
            f"`{json.dumps(oracle['schedule'], sort_keys=True)}` / {oracle['relativeSseMean']:.4f}")
        oracle_cost = "-" if oracle is None else f"{oracle['wallSeconds']:.2f}"
        oracle_ws = "-" if oracle is None else f"{oracle['peakWorkingSetBytes'] / 2**20:.1f}"
        greedy_text = "none" if greedy_result is None else (
            f"{greedy_result['relativeSseMean']:.4f} / `"
            f"{json.dumps(greedy_result['schedule'], sort_keys=True)}`")
        oracle_gain = "-" if row["oracleGainOverBestFixedPercent"] is None else (
            f"{row['oracleGainOverBestFixedPercent']:.1f}%")
        greedy_gap = "-" if row["greedyGapToOraclePercent"] is None else (
            f"{row['greedyGapToOraclePercent']:.3f}%")
        lines.append(f"| {row['budgetSourceGroup']} | {row['timeCapSeconds']:.2f} | "
                f"{row['peakWorkingSetCapBytes'] / 2**20:.1f} | "
                f"{row['peakCommitCapBytes'] / 2**20:.1f} | {fixed_text} | {oracle_text} | "
                f"{oracle_cost} | {oracle_ws} | {oracle_gain} | {greedy_text} | {greedy_gap} |")
    gains = ", ".join(f"g{row['budgetSourceGroup']}: {row['oracleGainOverBestFixedPercent']:.1f}%"
            for row in uniform if row["oracleGainOverBestFixedPercent"] is not None)
    greedy_matches = all(row["oracle"] is not None and row["marginalGreedy"] is not None
            and row["oracle"]["schedule"] == row["marginalGreedy"]["schedule"]
            and abs(row["greedyGapToOraclePercent"]) < 1e-9 for row in uniform)
    lines += [
        "",
        "The g4 fixed baseline is omitted: Shapes has no exact-budget g4 quality metric. The marginal greedy starts from the uniform schedule that defines the current time and peak-memory caps, then repeatedly chooses the feasible one-asset switch with the highest normalized SSE gain per added wall second while preserving both memory caps.",
        "",
        f"Unconstrained per-asset quality minima: `{json.dumps(all_best, sort_keys=True)}`; score {all_best_stats['score']:.4f}, serial wall {all_best_stats['wallSeconds']:.2f}s, peak WS {all_best_stats['peakWorkingSetBytes'] / 2**20:.1f} MiB, peak commit {all_best_stats['peakCommitBytes'] / 2**20:.1f} MiB.",
        "",
        "## Interpretation",
        "",
        "This oracle is exact only over the measured finite group-size grid. It answers whether per-asset group selection provides headroom over a globally fixed group under measured serial wall and process-memory caps. It does not evaluate node-local candidate generation, new hierarchy structures, scene rendering, material quality, or a perceptual metric. The greedy control is not a proposed contribution.",
        "",
        f"The exact heterogeneous schedule improves over the best feasible fixed group by {gains}. The marginal greedy {'matches the exact oracle schedule at all four caps' if greedy_matches else 'does not match the exact oracle at every cap'} in this measured grid. That confirms the headroom is ordinary per-asset allocation, not a new scheduling mechanism; scene-level model-specific simplification-rate allocation is already published. Memory is one sample per setting and outputs differ in `--dump-obj` mode between the core Pirate/Monkey and held-out asset sweeps, so this is a controlled within-asset comparison but not a production-wide memory claim.",
        "",
        "Per-asset allocation is closed as a contribution candidate. The only remaining hierarchy question is whether a new within-mesh patch-generation mechanism expands the complete strict-gate-valid cut frontier beyond the measured configuration oracle. A small offline prototype would have to beat that oracle and its matching greedy at equal measured work and memory on held-out models, then beat DAG2/HLOD ASAP/current cluster LOD under one validity contract before core implementation is justified. No novelty or SIGGRAPH readiness is established.",
        "",
        "Machine-readable records and all source/config hashes: `out/targetbudget-heldout-20261116/resource_oracle.json`.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"configurations": count, "output": str(OUTPUT),
            "report": str(OUTPUT_MD), "budgets": uniform}, indent=2))


if __name__ == "__main__":
    main()
