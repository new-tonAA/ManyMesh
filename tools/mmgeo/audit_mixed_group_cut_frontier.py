#!/usr/bin/env python3
"""Solve a relaxed mixed-group cut cover over already captured ManyMesh DAGs.

The MILP is an offline headroom screen. It allows region patches from different
group-size builds to mix when their source leaf regions form an exact cover. It
does not certify that those patches stitch into a valid mesh or improve rendered
image quality.
"""

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pulp


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_bounds(path):
    positions = []
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    positions.append(tuple(float(value) for value in parts[1:4]))
    if not positions:
        raise ValueError(f"no OBJ positions in {path}")
    low = tuple(min(point[i] for point in positions) for i in range(3))
    high = tuple(max(point[i] for point in positions) for i in range(3))
    center = tuple((low[i] + high[i]) * 0.5 for i in range(3))
    extent = tuple(high[i] - low[i] for i in range(3))
    return center, extent


def projected_error(node, camera):
    sphere = node["bounds"]
    depth = camera["eyeZ"] - sphere["center"][2] - sphere["radius"]
    return float(node["accumulatedError"]) / max(depth, camera["near"]) * camera["pixelsPerRadian"]


def graph_paths(root, manifest, asset, group):
    matches = [record for record in manifest["records"]
            if int(record["repeat"]) == 1
            and record["asset"] == asset
            and int(record["groupSize"]) == group]
    if len(matches) != 1:
        raise ValueError(f"expected one repeat-1 manifest record for {asset}/g{group}, got {len(matches)}")
    record = matches[0]
    command = record["command"]
    if "--quality-gate" not in command or command[command.index("--quality-gate") + 1] != "1":
        raise ValueError(f"quality gate was not enabled for {asset}/g{group}")
    out_dir = Path(command[command.index("--out") + 1])
    graph_path = out_dir / "lod_graph.json"
    mmb_path = out_dir / "lod_graph.mmb"
    if not graph_path.is_absolute():
        graph_path = root / graph_path
    if not mmb_path.is_absolute():
        mmb_path = root / mmb_path
    if sha256(graph_path) != record["graphSha256"]:
        raise ValueError(f"graph hash mismatch for {asset}/g{group}")
    return record, graph_path, mmb_path


def load_group(root, manifest, asset, group, leaf_ids, camera):
    record, graph_path, mmb_path = graph_paths(root, manifest, asset, group)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    source_path = root / record["source"]
    if sha256(source_path) != record["sourceSha256"]:
        raise ValueError(f"source hash mismatch for {asset}/g{group}")

    leaves = tuple(sorted(map(int, graph["leaves"])))
    if leaf_ids is not None and leaves != leaf_ids:
        raise ValueError(f"source leaf partition differs at {asset}/g{group}")
    if len(leaves) != len(set(leaves)):
        raise ValueError(f"duplicate source leaf ids at {asset}/g{group}")
    leaf_bit = {node_id: 1 << index for index, node_id in enumerate(leaves)}
    nodes = {int(node["id"]): node for node in graph["dag"]}
    if len(nodes) != len(graph["dag"]):
        raise ValueError(f"duplicate node ids at {asset}/g{group}")

    masks = {}
    for node in sorted(graph["dag"], key=lambda item: (int(item["level"]), int(item["id"]))):
        node_id = int(node["id"])
        children = list(map(int, node.get("children", [])))
        if not children:
            if node_id not in leaf_bit:
                raise ValueError(f"childless node {node_id} is not a recorded source leaf")
            masks[node_id] = leaf_bit[node_id]
        else:
            mask = 0
            for child in children:
                if child not in masks:
                    raise ValueError(f"child {child} was not processed before parent {node_id}")
                if mask & masks[child]:
                    raise ValueError(f"overlapping child leaf regions at node {node_id}")
                mask |= masks[child]
            masks[node_id] = mask

    all_leaves = (1 << len(leaves)) - 1
    selected_mask = 0
    selected_triangles = 0
    for node_id in map(int, graph["selectedNodes"]):
        if selected_mask & masks[node_id]:
            raise ValueError(f"native g{group} cut overlaps source leaves")
        selected_mask |= masks[node_id]
        selected_triangles += int(nodes[node_id]["tri"])
    if selected_mask != all_leaves or selected_triangles != int(graph["selectedTriangles"]):
        raise ValueError(f"native g{group} cut failed exact leaf/triangle coverage")
    if selected_triangles != int(record["selectedTriangles"]):
        raise ValueError(f"manifest triangle count mismatch at {asset}/g{group}")

    sys.path.insert(0, str(root / "tools" / "mmgeo"))
    from audit_shared_parent_candidate_reuse import decode_binary_graph

    binary = decode_binary_graph(mmb_path, graph)
    candidates = []
    for node_id, node in nodes.items():
        boundary = binary["nodeData"][node_id]["orientedBoundarySha256"]
        candidates.append({
            "region": masks[node_id],
            "group": group,
            "node": node_id,
            "triangles": int(node["tri"]),
            "errorPx": projected_error(node, camera),
            "boundary": boundary,
            "material": int(node.get("material", 0)),
            "submesh": int(node.get("submesh", 0)),
        })

    native_error = max((candidate["errorPx"] for candidate in candidates
            if candidate["node"] in set(map(int, graph["selectedNodes"]))), default=0.0)
    return {
        "graph": graph,
        "record": record,
        "graphPath": graph_path,
        "mmbPath": mmb_path,
        "leaves": leaves,
        "allLeaves": all_leaves,
        "candidates": candidates,
        "nativeErrorPx": native_error,
        "nativeTriangles": selected_triangles,
    }


def pareto_candidates(candidates):
    by_signature = defaultdict(dict)
    for candidate in candidates:
        key = (candidate["region"], candidate["boundary"],
                candidate["material"], candidate["submesh"])
        quality_key = (candidate["triangles"], round(candidate["errorPx"], 12))
        incumbent = by_signature[key].get(quality_key)
        if incumbent is None or (candidate["group"], candidate["node"]) < (incumbent["group"], incumbent["node"]):
            by_signature[key][quality_key] = candidate

    result = []
    before = 0
    for options in by_signature.values():
        rows = list(options.values())
        before += len(rows)
        for candidate in rows:
            dominated = any(
                other["triangles"] <= candidate["triangles"]
                and other["errorPx"] <= candidate["errorPx"]
                and (other["triangles"] < candidate["triangles"]
                    or other["errorPx"] < candidate["errorPx"])
                for other in rows)
            if not dominated:
                result.append(candidate)
    result.sort(key=lambda row: (row["group"], row["node"]))
    return result, before


def solve_cover(candidates, leaf_count, triangle_budget, time_limit):
    model = pulp.LpProblem("mixed_group_cut_region_cover", pulp.LpMinimize)
    choices = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(len(candidates))]
    worst = pulp.LpVariable("worst_projected_error_px", lowBound=0.0)
    model += worst

    leaf_options = [[] for _ in range(leaf_count)]
    for index, candidate in enumerate(candidates):
        mask = candidate["region"]
        while mask:
            bit = mask & -mask
            leaf = bit.bit_length() - 1
            leaf_options[leaf].append(choices[index])
            mask ^= bit
        model += worst >= candidate["errorPx"] * choices[index]

    for leaf, options in enumerate(leaf_options):
        if not options:
            raise ValueError(f"no patch candidate covers source leaf {leaf}")
        model += pulp.lpSum(options) == 1, f"cover_leaf_{leaf}"
    model += pulp.lpSum(candidate["triangles"] * choices[index]
            for index, candidate in enumerate(candidates)) <= triangle_budget, "triangle_budget"

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=0.0)
    model.solve(solver)
    status = pulp.LpStatus[model.status]
    chosen = [candidate for index, candidate in enumerate(candidates)
            if pulp.value(choices[index]) is not None and pulp.value(choices[index]) > 0.5]
    total_triangles = sum(candidate["triangles"] for candidate in chosen)
    actual_worst = max((candidate["errorPx"] for candidate in chosen), default=None)
    covered = 0
    for candidate in chosen:
        if covered & candidate["region"]:
            raise ValueError("solver output has overlapping source leaf regions")
        covered |= candidate["region"]
    return {
        "status": status,
        "objectiveErrorPx": pulp.value(worst),
        "chosenWorstErrorPx": actual_worst,
        "triangleCount": total_triangles,
        "leafCoverExact": covered == (1 << leaf_count) - 1,
        "chosen": [{key: value for key, value in candidate.items() if key != "region"}
                | {"leafCount": candidate["region"].bit_count()}
                for candidate in chosen],
    }


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="shapes")
    parser.add_argument("--groups", nargs="+", type=int, default=[2, 4, 8, 16, 32])
    parser.add_argument("--build-manifest", type=Path,
            default=root / "out/targetbudget-heldout-20261116/builds.json")
    parser.add_argument("--time-limit", type=int, default=120)
    parser.add_argument("--out", type=Path,
            default=root / "out/mixed-group-frontier-20261117/shapes.json")
    args = parser.parse_args()

    manifest = json.loads(args.build_manifest.read_text(encoding="utf-8"))
    source_path = root / f"assets/models/{args.asset}/{args.asset}.obj"
    center, extent = source_bounds(source_path)
    fov_y = math.radians(45.0)
    tan_half_fov = math.tan(fov_y * 0.5)
    aspect = 16.0 / 9.0
    distance = max(extent[1] * 0.5 / tan_half_fov,
            extent[0] * 0.5 / (tan_half_fov * aspect)) * 1.05 + extent[2] * 0.5
    camera = {
        "eyeZ": center[2] + max(distance, 1e-3),
        "near": max(distance * 0.01, 1e-4),
        "pixelsPerRadian": 1080 / (2.0 * tan_half_fov),
    }

    loaded = []
    leaf_ids = None
    for group in args.groups:
        item = load_group(root, manifest, args.asset, group, leaf_ids, camera)
        if leaf_ids is None:
            leaf_ids = item["leaves"]
        loaded.append(item)
    budgets = {item["nativeTriangles"] for item in loaded}
    base_triangles = {int(item["graph"]["baseTriangles"]) for item in loaded}
    if len(base_triangles) != 1:
        raise ValueError(f"groups do not share one source triangle count: {base_triangles}")

    raw = [candidate for item in loaded for candidate in item["candidates"]]
    options, pre_prune_count = pareto_candidates(raw)
    budget = min(budgets)
    result = solve_cover(options, len(leaf_ids), budget, args.time_limit)
    best_native = min(item["nativeErrorPx"] for item in loaded
            if item["nativeTriangles"] <= budget)
    result.update({
        "asset": args.asset,
        "groups": args.groups,
        "leafCount": len(leaf_ids),
        "triangleBudget": budget,
        "baseTriangles": next(iter(base_triangles)),
        "nativeCuts": [{
            "group": item["record"]["groupSize"],
            "triangles": item["nativeTriangles"],
            "worstProjectedErrorPx": item["nativeErrorPx"],
            "withinMixedBudget": item["nativeTriangles"] <= budget,
        } for item in loaded],
        "nativeTriangleBudgets": sorted(budgets),
        "budgetPolicy": "use the minimum native selected triangle count; higher-count native cuts are excluded from the matched baseline, while their individually qualified patches remain in the mixed candidate pool",
        "bestNativeWorstErrorPx": best_native,
        "relaxedImprovementPercent": ((best_native - result["chosenWorstErrorPx"])
                / best_native * 100.0 if result["chosenWorstErrorPx"] is not None else None),
        "candidateCountRaw": len(raw),
        "candidateCountAfterParetoPruning": len(options),
        "candidateCountBeforeDominancePruning": pre_prune_count,
        "objective": "minimize worst projected sphere error over an exact source-leaf region cover at a matched triangle budget",
        "relaxations": [
            "Candidate patch geometry is taken from separately built group-size graphs; the mixed output is not assembled or rasterized.",
            "Exact source leaf coverage is enforced, but cross-patch oriented boundary and attribute stitching are not verified.",
            "Projected sphere error is optimized; this proxy disagrees with filtered image SSE on some assets.",
            "All group-size builds are treated as already available; generation time and memory for the combined candidate pool are not charged.",
            "A positive oracle result is only headroom evidence, not a realizable cut, method, or novelty claim.",
        ],
        "inputs": {
            "buildManifest": {"path": str(args.build_manifest), "sha256": sha256(args.build_manifest)},
            "source": {"path": str(source_path), "sha256": sha256(source_path)},
            "graphs": [{"group": item["record"]["groupSize"],
                "path": str(item["graphPath"]), "sha256": sha256(item["graphPath"]),
                "mmbPath": str(item["mmbPath"]), "mmbSha256": sha256(item["mmbPath"])}
                for item in loaded],
            "script": {"path": str(Path(__file__)), "sha256": sha256(__file__)},
        },
    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "status", "asset", "groups", "triangleBudget", "bestNativeWorstErrorPx",
        "chosenWorstErrorPx", "triangleCount", "leafCoverExact",
        "relaxedImprovementPercent", "candidateCountRaw",
        "candidateCountAfterParetoPruning", "out")
        if key in result} | {"out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
