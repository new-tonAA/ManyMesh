#!/usr/bin/env python3
"""Enumerate the exact worst-error optimum over cuts of a saved single-parent LOD forest.

This is an offline analysis of the stored projected-sphere-error metric. It does not measure
rendered image quality and cannot score hierarchy alternatives absent from the serialized graph.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path


UINT32_MAX = (1 << 32) - 1


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_bounds(path):
    positions = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    positions.append(tuple(float(value) for value in parts[1:4]))
    if not positions:
        raise ValueError(f"no OBJ vertex positions in {path}")
    low = tuple(min(point[axis] for point in positions) for axis in range(3))
    high = tuple(max(point[axis] for point in positions) for axis in range(3))
    center = tuple((low[axis] + high[axis]) * 0.5 for axis in range(3))
    extent = tuple(high[axis] - low[axis] for axis in range(3))
    return center, extent


def validate_forest(nodes, roots):
    if len(nodes) != len(set(nodes)):
        raise ValueError("duplicate node ids")
    root_set = set(roots)
    if len(root_set) != len(roots):
        raise ValueError("duplicate roots")
    if any(root not in nodes for root in roots):
        raise ValueError("root id is absent")

    for node_id, node in nodes.items():
        children = node.get("children", [])
        if len(children) != len(set(children)):
            raise ValueError(f"node {node_id} lists a child more than once")
        parent = node.get("parent", UINT32_MAX)
        if parent == UINT32_MAX:
            if node_id not in root_set:
                raise ValueError(f"parentless node {node_id} is absent from roots")
        elif parent not in nodes or node_id not in nodes[parent].get("children", []):
            raise ValueError(f"parent relation for node {node_id} is inconsistent")
        for child in children:
            if child not in nodes or nodes[child].get("parent", UINT32_MAX) != node_id:
                raise ValueError(f"child relation {node_id}->{child} is inconsistent")
        if children and node["tri"] >= sum(nodes[child]["tri"] for child in children):
            raise ValueError(f"parent node {node_id} does not reduce its direct-child triangle count")

    visited = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            raise ValueError("nodes are shared or the graph contains a cycle")
        visited.add(node_id)
        stack.extend(nodes[node_id].get("children", []))
    if visited != set(nodes):
        raise ValueError("some nodes are unreachable from roots")


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path,
            nargs="?", default=root / "out/target-budget-oracle-20261116/pirate-g8/lod_graph.json")
    parser.add_argument("--mesh", type=Path,
            default=root / "third_party/meshoptimizer/demo/pirate.obj")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["dag"]}
    if len(nodes) != len(graph["dag"]):
        raise ValueError("duplicate node ids")
    validate_forest(nodes, graph["roots"])

    center, extent = source_bounds(args.mesh)
    height = 1080
    tan_half_fov = math.tan(math.radians(45.0 * 0.5))
    aspect = 16.0 / 9.0
    distance = max(extent[1] * 0.5 / tan_half_fov,
            extent[0] * 0.5 / (tan_half_fov * aspect)) * 1.05 + extent[2] * 0.5
    eye_z = center[2] + max(distance, 1e-3)
    near = max(distance * 0.01, 1e-4)
    pixels_per_radian = height / (2.0 * tan_half_fov)

    error = {}
    for node_id, node in nodes.items():
        sphere = node["bounds"]
        depth = eye_z - sphere["center"][2] - sphere["radius"]
        error[node_id] = node["accumulatedError"] / max(depth, near) * pixels_per_radian

    def cut_at_threshold(threshold):
        cut = []

        def visit(node_id):
            node = nodes[node_id]
            children = node.get("children", [])
            if children and error[node_id] > threshold:
                for child in children:
                    visit(child)
            else:
                cut.append(node_id)

        for tree_root in graph["roots"]:
            visit(tree_root)
        return cut

    requested_budget = math.ceil(graph["baseTriangles"] * graph["targetRatio"])
    if requested_budget != graph["selectedTriangles"]:
        raise ValueError("stored selected triangle count differs from requested target budget")

    feasible = []
    thresholds = sorted(set(error.values()))
    for threshold in thresholds:
        cut = cut_at_threshold(threshold)
        triangles = sum(nodes[node_id]["tri"] for node_id in cut)
        if triangles <= requested_budget:
            worst_error = max((error[node_id] for node_id in cut), default=0.0)
            feasible.append((worst_error, triangles, cut))
    if not feasible:
        raise ValueError("no threshold cut fits the requested triangle budget")

    best = min(feasible, key=lambda item: (item[0], item[1]))
    selected = set(graph["selectedNodes"])
    selected_triangles = sum(nodes[node_id]["tri"] for node_id in selected)
    selected_error = max((error[node_id] for node_id in selected), default=0.0)
    ranked_selected = sorted(((error[node_id], node_id, nodes[node_id]["tri"])
            for node_id in selected), reverse=True)

    relevant_paths = {
        "mesh": args.mesh,
        "graph": args.graph,
        "analysisScript": Path(__file__),
        "lodGraphSource": root / "libs/manymesh/src/LodGraph.cpp",
        "mmgeoSource": root / "tools/mmgeo/src/main.cpp",
        "executable": root / "out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe",
    }
    report = {
        "scope": "exact minimax projected-sphere-error optimum over cuts of the saved single-parent forest",
        "limitations": [
            "The objective is the stored accumulated geometric error projected with the auto-frame sphere proxy, not rendered image quality.",
            "The optimization cannot introduce parent patches or hierarchy alternatives absent from this graph.",
            "The source is auto-framed in full; no view-frustum culling is modeled.",
        ],
        "graph": {
            "nodes": len(nodes),
            "roots": len(graph["roots"]),
            "leaves": len(graph["leaves"]),
            "singleParentForestValidated": True,
            "monotoneTriangleCountsValidated": True,
        },
        "method": "Enumerate every distinct node error threshold. For each threshold, descending only where a node exceeds it yields the minimum-triangle legal cut because every parent has fewer triangles than its direct children combined. The smallest threshold whose cut fits the budget is the exact minimax optimum over this forest.",
        "camera": {
            "screen": [1920, height],
            "fovYDegrees": 45.0,
            "eyeZ": eye_z,
            "near": near,
        },
        "budget": requested_budget,
        "uniqueNodeErrorThresholdsEnumerated": len(thresholds),
        "feasibleThresholds": len(feasible),
        "exactTreeOptimum": {
            "worstProjectedErrorPx": best[0],
            "triangles": best[1],
            "selectedNodeCount": len(best[2]),
            "selectedNodes": sorted(best[2]),
        },
        "storedSelection": {
            "worstProjectedErrorPx": selected_error,
            "triangles": selected_triangles,
            "selectedNodeCount": len(selected),
            "matchesExactTreeOptimum": set(best[2]) == selected,
            "worstNodes": [
                {"id": node_id, "errorPx": node_error, "triangles": triangles}
                for node_error, node_id, triangles in ranked_selected[:5]
            ],
        },
        "inputs": {
            key: {"path": str(path), "sha256": sha256(path)}
            for key, path in relevant_paths.items() if path.exists()
        },
    }

    output_path = args.output or args.graph.with_name("tree_cut_optimum.json")
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "budget": requested_budget,
        "exactTreeOptimum": report["exactTreeOptimum"],
        "storedSelection": report["storedSelection"],
        "thresholdsEnumerated": len(thresholds),
        "output": str(output_path),
    }, indent=2))


if __name__ == "__main__":
    main()
