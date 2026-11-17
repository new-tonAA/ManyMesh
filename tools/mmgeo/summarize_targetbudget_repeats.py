#!/usr/bin/env python3
"""Validate and summarize repeated target-budget DAG build controls."""

import hashlib
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPEATS = ROOT / "out/targetbudget-repeat-control-20261116/build_repeats.json"
VISIBILITY = {
    "pirate": ROOT / "out/targetbudget-frontier-pilot-20261116/visibility_audit.json",
    "monkey": ROOT / "out/targetbudget-crossasset-20261116/monkey_visibility_audit.json",
}
INITIAL_GRAPHS = {
    "pirate": ROOT / "out/targetbudget-frontier-pilot-20261116",
    "monkey": ROOT / "out/targetbudget-crossasset-20261116",
}
ASSET_RELATIVE_PATHS = {
    "pirate": "third_party/meshoptimizer/demo/pirate.obj",
    "monkey": "assets/models/monkey/monkey.obj",
}
OUTPUT_JSON = ROOT / "out/targetbudget-repeat-control-20261116/summary.json"
OUTPUT_MD = ROOT / "tools/mmgeo/TARGET_BUDGET_MULTI_ASSET_20261116.md"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_graph(path, asset):
    graph = json.loads(path.read_text(encoding="utf-8"))
    source = graph["source"].replace("\\", "/")
    expected_suffix = ASSET_RELATIVE_PATHS[asset]
    if not source.endswith(expected_suffix):
        raise ValueError(f"unexpected source path in {path}: {source}")
    graph["source"] = expected_suffix
    canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    return graph, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main():
    repeat_data = json.loads(REPEATS.read_text(encoding="utf-8"))
    expected = len(repeat_data["settings"]["assets"]) * len(
            repeat_data["settings"]["groups"]) * repeat_data["settings"]["repeats"]
    if len(repeat_data["records"]) != expected:
        raise ValueError(f"expected {expected} repeated runs, found {len(repeat_data['records'])}")

    visibility_data = {asset: json.loads(path.read_text(encoding="utf-8"))
            for asset, path in VISIBILITY.items()}
    groups = {}
    for record in repeat_data["records"]:
        if not record["graphMetadataMatchesCommand"]:
            raise ValueError(f"metadata mismatch: {record['asset']} group {record['groupSize']}")
        groups.setdefault((record["asset"], record["groupSize"]), []).append(record)

    summaries = []
    for (asset, group), records in sorted(groups.items()):
        if len(records) != repeat_data["settings"]["repeats"]:
            raise ValueError(f"unexpected repetition count: {asset} group {group}")
        graph_hashes = sorted({record["graphSha256"] for record in records})
        baseline_graph = INITIAL_GRAPHS[asset] / f"{asset}-g{group}/lod_graph.json"
        if not baseline_graph.is_file():
            raise FileNotFoundError(baseline_graph)
        baseline_data, baseline_canonical_hash = canonical_graph(baseline_graph, asset)
        repeated_graphs = [canonical_graph(
                REPEATS.parent / f"rep-{r['repeat']:02d}" / f"{asset}-g{group}" /
                "lod_graph.json", asset) for r in records]
        canonical_hashes = sorted({item[1] for item in repeated_graphs})
        if any(item[0] != baseline_data for item in repeated_graphs):
            raise ValueError(f"graph contents differ from initial sweep: {asset} group {group}")
        image_key = f"g{group}" if asset == "monkey" else str(group)
        image_metric = visibility_data[asset]["meanViewMetrics"][image_key][
                "filteredTotalSse"]
        errors = sorted({record["worstSelectedScreenErrorPx"] for record in records})
        triangles = sorted({record["selectedTriangles"] for record in records})
        summary = {
            "asset": asset,
            "groupSize": group,
            "repeats": len(records),
            "dagBuildSeconds": {
                "median": statistics.median(r["dagBuildSeconds"] for r in records),
                "min": min(r["dagBuildSeconds"] for r in records),
                "max": max(r["dagBuildSeconds"] for r in records),
                "samples": [r["dagBuildSeconds"] for r in records],
            },
            "wallSeconds": {
                "median": statistics.median(r["wallSeconds"] for r in records),
                "min": min(r["wallSeconds"] for r in records),
                "max": max(r["wallSeconds"] for r in records),
            },
            "screenErrorPx": errors,
            "selectedTriangles": triangles,
            "visibilityFilteredTotalSse": image_metric,
            "repeatedGraphHashes": graph_hashes,
            "canonicalGraphHashes": canonical_hashes,
            "matchesInitialSweepGraph": len(canonical_hashes) == 1 and
                    canonical_hashes[0] == baseline_canonical_hash,
            "initialSweepGraphSha256": sha256(baseline_graph),
            "initialSweepCanonicalGraphSha256": baseline_canonical_hash,
        }
        summaries.append(summary)

    if any(len(s["repeatedGraphHashes"]) != 1 or
            not s["matchesInitialSweepGraph"] or len(s["screenErrorPx"]) != 1 or
            len(s["selectedTriangles"]) != 1 for s in summaries):
        raise ValueError("repeated runs changed graph/output metrics or differ from initial sweep")

    data = {
        "scope": "three randomized/interleaved single-asset DAG-build repetitions per setting, with separate 16-view CPU visibility diagnostic",
        "repeatInput": str(REPEATS.relative_to(ROOT)),
        "repeatInputSha256": sha256(REPEATS),
        "settings": repeat_data["settings"],
        "provenance": repeat_data["provenance"],
        "aggregationScript": {
            "path": str(Path(__file__).relative_to(ROOT)),
            "sha256": sha256(Path(__file__)),
        },
        "visibilityInputs": {asset: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "sourceTriangles": visibility_data[asset]["settings"]["sourceTriangles"],
            "candidateTriangles": visibility_data[asset]["settings"]["candidateTriangles"],
            "views": visibility_data[asset]["settings"]["views"],
            "rasterResolution": visibility_data[asset]["settings"]["size"],
            "supersampling": visibility_data[asset]["settings"]["scale"],
            "filterSigma": visibility_data[asset]["settings"]["sigma"],
            "sourceObjSha256": visibility_data[asset]["hashes"]["sourceObj"],
            "rasterOracleSha256": visibility_data[asset]["hashes"]["rasterOracle"],
            "candidateGraphHashes": visibility_data[asset]["hashes"]["graphs"],
        } for asset, path in VISIBILITY.items()},
        "summaries": summaries,
    }
    OUTPUT_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    by_key = {(item["asset"], item["groupSize"]): item for item in summaries}
    lines = [
        "# Multi-Asset Target-Budget LOD Control (2026-11-16)",
        "",
        "## Question and scope",
        "",
        "Does the same fixed `--dag-group` choice give a stable construction-cost / visible-geometry tradeoff across assets? This is a small falsification control for the proposed adaptive-construction direction; it is not an algorithm comparison or a novelty claim.",
        "",
        "The fresh Monkey sweep and the earlier Pirate sweep both target 55% of source triangles. All candidate cuts have a fixed triangle count within each asset. Build cost is measured by the binary's reported DAG build time and repeated three times in randomized interleaved order. The quality proxy is the separate CPU raster diagnostic: mean filtered coverage plus normalized first-hit-depth SSE over 16 evenly spaced azimuths at one elevation, 256x256, 2x supersampling, Gaussian sigma 0.9.",
        "",
        "## Results",
        "",
        "| Asset | Group | DAG build median [min, max] s | Total wall median s | Auto-camera sphere error px | 16-view coverage/depth SSE | Graph reproducible and matches initial sweep |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for asset in ("pirate", "monkey"):
        for group in repeat_data["settings"]["groups"]:
            item = by_key[(asset, group)]
            build = item["dagBuildSeconds"]
            lines.append(
                f"| {asset.title()} | {group} | {build['median']:.2f} [{build['min']:.2f}, {build['max']:.2f}] | "
                f"{item['wallSeconds']['median']:.2f} | {item['screenErrorPx'][0]:.4f} | "
                f"{item['visibilityFilteredTotalSse']:.4f} | yes |"
            )

    lines += [
        "",
        "For each asset/group, all three raw graph-file SHA-256 values agree. The canonical graph object (normalizing only the absolute-versus-relative input path) also matches the earlier visibility sweep exactly. Triangle counts and the reported screen-error value remain identical across repetitions. Timing ranges are reported rather than treated as exact costs.",
        "",
        "The same fixed parameter does not give a consistent ranking across these two meshes. Pirate group 2 has both the shortest median build ("
        f"{by_key[('pirate', 2)]['dagBuildSeconds']['median']:.2f}s) and lowest raster SSE ("
        f"{by_key[('pirate', 2)]['visibilityFilteredTotalSse']:.4f}). Monkey group 2 is fastest ("
        f"{by_key[('monkey', 2)]['dagBuildSeconds']['median']:.2f}s) but has the highest SSE ("
        f"{by_key[('monkey', 2)]['visibilityFilteredTotalSse']:.4f}); group 8 has the lowest Monkey SSE ("
        f"{by_key[('monkey', 8)]['visibilityFilteredTotalSse']:.4f}) at a build median of "
        f"{by_key[('monkey', 8)]['dagBuildSeconds']['median']:.2f}s. Group 32 is dominated by group 8 for Monkey on these two measured axes. The two examples therefore show asset-dependent choices, not a universal best group size.",
        "",
        "The auto-camera sphere-error proxy ranks the groups differently from the multi-view raster SSE on Monkey. This confirms that the current proxy is not a substitute for rendered-image validation. With only two meshes, one elevation, and one raster/filter setup, this cannot establish a general law.",
        "",
        "## Literature boundary",
        "",
        "A fixed group-size sweep is not a contribution. Perceptual and appearance-aware mesh simplification, view-dependent LOD selection, and construction-time/resource tuning are established themes. In particular, Ladeuil et al. (Computer Graphics Forum 2026) already construct clustered HLOD using progressive internal and boundary meshes, allowing crack-free boundary simplification across neighboring clusters. This rules out presenting adaptive boundary simplification or freeing locked boundaries as the new idea. Benthin and Peters' HPG 2023 DAG2 already use split-and-reinsert to improve cluster merging, so multi-parent alternatives alone are also insufficient.",
        "",
        "RTX Mega Geometry is a relevant systems baseline rather than a directly equivalent simplifier: its public implementation exposes baked cluster/group sizes, LOD-node width, simplification weights, error metric and meshoptimizer settings, and records bake time, worker count and peak RAM. It targets streaming/ray-tracing cluster LOD at much larger scale; its output and gate contract must be normalized before a matched quality/cost comparison.",
        "",
        "## Research decision",
        "",
        "Do not claim SIGGRAPH readiness or novelty from these controls. The evidence supports only this narrower observation: the hierarchy builder's quality/cost ranking is asset-dependent under a geometry visibility proxy, and its current single-camera sphere-error score can disagree with that proxy. That is a motivation to test a stronger hypothesis, not the hypothesis itself.",
        "",
        "A viable next gate is an offline budgeted hierarchy-construction policy that schedules additional simplification attempts only when they enlarge the complete, crack-free, attribute-valid cut frontier under a declared multi-view image-space objective. Its scope must stay distinct from per-mesh LOD-rate allocation, perceptual cut selection, progressive boundary simplification and DAG2 splitting, all established directions. It must beat (1) the best fixed group/retry schedule, (2) the exact best schedule over the tested finite configuration grid under the same wall-clock and peak-memory budget, and (3) HLOD ASAP / DAG2 / current cluster-LOD baselines when their outputs can satisfy the same strict gate. First measure whether this finite-grid oracle improves the frontier across a held-out, diverse asset set; then compare a simple marginal-gain-per-build-second scheduler against that oracle. If the oracle has no material headroom, abandon this direction. Even positive headroom would not establish novelty without a wider literature and implementation search.",
        "",
        "## Reproduction and limitations",
        "",
        "Build repetitions: `python -I tools/mmgeo/benchmark_target_budget_builds.py` (the run data is already captured; the driver refuses to overwrite the output folder). Aggregate and validate hashes with `python -I tools/mmgeo/summarize_targetbudget_repeats.py`. Recreate the Pirate visibility diagnostic with `python -I tools/mmgeo/audit_target_budget_visibility.py` (defaults are the frozen Pirate sweep and 16-view settings). Recreate Monkey with `python -I tools/mmgeo/audit_crossasset_visibility.py --mesh assets/models/monkey/monkey.obj --asset monkey --cut g2=out/targetbudget-crossasset-20261116/monkey-g2/selected_ratio_0.55.ply --cut g4=out/targetbudget-crossasset-20261116/monkey-g4/selected_ratio_0.55.ply --cut g8=out/targetbudget-crossasset-20261116/monkey-g8/selected_ratio_0.55.ply --cut g16=out/targetbudget-crossasset-20261116/monkey-g16/selected_ratio_0.55.ply --cut g32=out/targetbudget-crossasset-20261116/monkey-g32/selected_ratio_0.55.ply --output out/targetbudget-crossasset-20261116/monkey_visibility_audit.json`.",
        "",
        "This is geometry-only binary coverage and normalized first-hit depth; no materials, normals, textures, PBR, animation, user study or camera distribution beyond one orbit are included. Two models are not enough for generalization. The CPU raster score is a proxy and has not been calibrated to perception. Build timing was measured on one executable/machine; three repetitions quantify local timing variation only. No C++ was changed and no software tests were run.",
        "",
        "Machine-readable aggregate with source, executable, graph and visibility hashes: `out/targetbudget-repeat-control-20261116/summary.json`.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "runs": len(repeat_data["records"]),
        "summary": str(OUTPUT_JSON),
        "report": str(OUTPUT_MD),
        "hashChecks": all(item["matchesInitialSweepGraph"] for item in summaries),
    }, indent=2))


if __name__ == "__main__":
    main()
