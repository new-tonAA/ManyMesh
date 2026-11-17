#!/usr/bin/env python3
"""Check exact-cut substitutions enabled by mined shared-parent alternatives.

This is a structural/local-error audit. It checks native target-ratio cuts for exact-once
leaf coverage, then asks whether a same-budget parent alternative can replace a selected
parent while preserving its leaf region and serialized boundary signature. It does not render.
"""

import argparse
import hashlib
import json
import math
import struct
from collections import defaultdict
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_graph_index(manifests):
    graphs = {}
    manifest_records = []
    for manifest_path in manifests:
        manifest_path = Path(manifest_path).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_records.append({"path": str(manifest_path), "sha256": sha256(manifest_path)})
        for record in manifest["records"]:
            if int(record.get("repeat", -1)) != 1:
                continue
            command = record["command"]
            output = Path(command[command.index("--out") + 1]).resolve()
            graph_path = output / "lod_graph.json"
            if sha256(graph_path) != record["graphSha256"]:
                raise ValueError(f"graph hash mismatch: {graph_path}")
            key = (record["asset"], int(record["groupSize"]))
            graphs[key] = {"path": graph_path, "output": output, "record": record}
    return graphs, manifest_records


def descendant_leaves(graph):
    nodes = {int(node["id"]): node for node in graph["dag"]}
    cache = {}

    def leaves(node_id):
        if node_id not in cache:
            children = list(map(int, nodes[node_id]["children"]))
            if not children:
                cache[node_id] = (node_id,)
            else:
                merged = [leaf for child in children for leaf in leaves(child)]
                if len(merged) != len(set(merged)):
                    raise ValueError(f"overlapping descendant leaves at node {node_id}")
                cache[node_id] = tuple(sorted(merged))
        return cache[node_id]

    return nodes, leaves


def check_native_cut(graph, nodes, leaves):
    selected = list(map(int, graph["selectedNodes"]))
    covered = []
    triangles = 0
    for node_id in selected:
        covered.extend(leaves(node_id))
        triangles += int(nodes[node_id]["tri"])
    expected = set(map(int, graph["leaves"]))
    return {
        "selectedNodeCount": len(selected),
        "selectedTrianglesFromNodes": triangles,
        "reportedSelectedTriangles": int(graph["selectedTriangles"]),
        "exactOnceLeafCoverage": len(covered) == len(set(covered)) and set(covered) == expected,
        "coveredLeafCount": len(covered),
        "expectedLeafCount": len(expected),
        "selectedNodeIds": selected,
    }


def bounds_equal(a, b, tolerance=2e-5):
    if not a or not b:
        return False
    if len(a["center"]) != 3 or len(b["center"]) != 3:
        return False
    values_a = list(map(float, a["center"])) + [float(a["radius"])]
    values_b = list(map(float, b["center"])) + [float(b["radius"])]
    return all(abs(x - y) <= tolerance for x, y in zip(values_a, values_b))


def default_obj_camera(source_path):
    source_path = Path(source_path)
    if source_path.suffix.lower() != ".obj":
        return None
    positions = []
    for line in source_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("v "):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        positions.append(tuple(struct.unpack("<f", struct.pack("<f", float(value)))[0]
                                for value in fields[1:4]))
    if not positions:
        return None
    lo = tuple(min(position[i] for position in positions) for i in range(3))
    hi = tuple(max(position[i] for position in positions) for i in range(3))
    extent = tuple(hi[i] - lo[i] for i in range(3))
    center = tuple((lo[i] + hi[i]) * 0.5 for i in range(3))
    fov = math.radians(45.0)
    height = 1080
    width = height * 16 // 9
    aspect = width / height
    tangent = math.tan(fov * 0.5)
    distance_y = (extent[1] * 0.5) / tangent
    distance_x = (extent[0] * 0.5) / (tangent * aspect)
    distance = max(distance_y, distance_x) * 1.05 + extent[2] * 0.5
    return {
        "eye": (center[0], center[1], center[2] + max(distance, 1e-3)),
        "target": center,
        "near": max(distance * 0.01, 1e-4),
        "pixelsPerRadian": height / (2.0 * tangent),
        "boundsMin": lo,
        "boundsMax": hi,
        "screen": [width, height],
        "fovDegrees": 45.0,
    }


def node_screen_error(node, camera):
    bounds = node["bounds"]
    depth = camera["eye"][2] - float(bounds["center"][2]) - float(bounds["radius"])
    distance = max(depth, camera["near"], 1e-6)
    return (float(node["accumulatedError"]) / distance) * camera["pixelsPerRadian"]


def audit_asset(asset, alternatives, graph_index):
    graph_cache = {}

    def load(group):
        key = (asset, int(group))
        if key not in graph_cache:
            entry = graph_index[key]
            graph = json.loads(entry["path"].read_text(encoding="utf-8"))
            nodes, leaves = descendant_leaves(graph)
            graph_cache[key] = (entry, graph, nodes, leaves, check_native_cut(graph, nodes, leaves))
        return graph_cache[key]

    substitutions = []
    cut_checks = {}
    for candidate_set_index, candidate_set in enumerate(alternatives):
        rows = candidate_set["parents"]
        row_info = {}
        for row in rows:
            entry, graph, nodes, leaves, cut = load(row["group"])
            node_id = int(row["node"])
            node = nodes[node_id]
            child_regions = tuple(sorted(leaves(int(child)) for child in node["children"]))
            row_info[(row["group"], node_id)] = {
                "row": row,
                "entry": entry,
                "graph": graph,
                "nodes": nodes,
                "leaves": leaves,
                "cut": cut,
                "node": node,
                "childRegions": child_regions,
                "leafRegion": leaves(node_id),
            }
            cut_checks[str(row["group"])] = cut

        leaf_regions = {value["leafRegion"] for value in row_info.values()}
        child_region_sets = {value["childRegions"] for value in row_info.values()}
        if len(leaf_regions) != 1 or len(child_region_sets) != 1:
            raise ValueError(f"candidate set no longer maps to one child region: {asset}")

        for source in row_info.values():
            source_id = int(source["node"]["id"])
            source_cut = source["cut"]
            if source_id not in source_cut["selectedNodeIds"]:
                continue
            if not source_cut["exactOnceLeafCoverage"]:
                raise ValueError(f"native cut is not an exact leaf cover: {asset}")
            source_bounds = source["node"].get("bounds")
            for target in row_info.values():
                if target is source:
                    continue
                if int(target["row"]["triangles"]) != int(source["row"]["triangles"]):
                    continue
                same_bounds = bounds_equal(source_bounds, target["node"].get("bounds"))
                same_boundary = (
                    source["row"]["parentBoundarySha256"]
                    == target["row"]["parentBoundarySha256"]
                    and source["row"]["parentOrientedBoundarySha256"]
                    == target["row"]["parentOrientedBoundarySha256"]
                )
                source_region = set(source["leafRegion"])
                target_region = set(target["leafRegion"])
                virtual_covered = [
                    leaf for selected_id in source_cut["selectedNodeIds"]
                    if selected_id != source_id
                    for leaf in source["leaves"](selected_id)
                ] + list(target_region)
                virtual_exact_cover = (
                    len(virtual_covered) == len(set(virtual_covered))
                    and set(virtual_covered) == set(map(int, source["graph"]["leaves"]))
                    and source_region == target_region
                )
                before = float(source["row"]["accumulatedError"])
                after = float(target["row"]["accumulatedError"])
                camera = default_obj_camera(source["graph"]["source"])
                screen_audit = None
                if camera is not None:
                    original_node_errors = {
                        selected_id: node_screen_error(source["nodes"][selected_id], camera)
                        for selected_id in source_cut["selectedNodeIds"]
                    }
                    original_max = max(original_node_errors.values(), default=0.0)
                    replacement_error = node_screen_error(target["node"], camera)
                    replacement_max = max(
                        [error for selected_id, error in original_node_errors.items()
                         if selected_id != source_id] + [replacement_error],
                        default=0.0)
                    reported_max = float(source["graph"].get("maxScreenErrorPx", 0.0))
                    screen_audit = {
                        "camera": camera,
                        "reconstructedNativeMaxScreenErrorPx": original_max,
                        "reportedNativeMaxScreenErrorPx": reported_max,
                        "nativeMaxReconstructionMatches": abs(original_max - reported_max) <= 0.02,
                        "reconstructedMaxAfterSubstitutionPx": replacement_max,
                        "wholeCutMaxScreenErrorReductionPx": original_max - replacement_max,
                        "wholeCutMaxScreenErrorReduced": replacement_max < original_max - 1e-6,
                    }
                substitutions.append({
                    "asset": asset,
                    "candidateSet": candidate_set_index,
                    "sourceGroup": source["row"]["group"],
                    "sourceNode": source_id,
                    "alternativeGroup": target["row"]["group"],
                    "alternativeNode": target["row"]["node"],
                    "leafCount": len(source_region),
                    "trianglesBefore": int(source["row"]["triangles"]),
                    "trianglesAfter": int(target["row"]["triangles"]),
                    "triangleDelta": int(target["row"]["triangles"])
                    - int(source["row"]["triangles"]),
                    "nativeCutExactOnceLeafCoverage": source_cut["exactOnceLeafCoverage"],
                    "virtualCutExactOnceLeafCoverage": virtual_exact_cover,
                    "sameDirectChildLeafRegions": len(child_region_sets) == 1,
                    "sameOrientedBoundary": same_boundary,
                    "sameParentBounds": same_bounds,
                    "accumulatedErrorBefore": before,
                    "accumulatedErrorAfter": after,
                    "localErrorReductionFraction": (before - after) / before if before > 0 else None,
                    "localScreenErrorMonotoneAtSameBounds": same_bounds,
                    "allCandidateParentsPassStoredAttributeLimits": all(
                        bool(row["storedAttributeLimitsPass"]) for row in rows),
                    "screenErrorAudit": screen_audit,
                })

    return {
        "asset": asset,
        "nativeCuts": cut_checks,
        "sameBudgetSubstitutionsFromNativeSelectedNodes": substitutions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry_report", type=Path)
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    geometry_report = json.loads(args.geometry_report.read_text(encoding="utf-8"))
    graph_index, manifests = load_graph_index(args.manifests)
    results = []
    for asset_report in geometry_report["assets"]:
        alternatives = asset_report["sharedParentGeometryAlternativeSets"]
        if alternatives:
            results.append(audit_asset(asset_report["asset"], alternatives, graph_index))
    report = {
        "scope": "virtual equal-budget substitutions in saved native target-ratio cuts; structural and local projected-error proxy only",
        "geometryReport": str(args.geometry_report.resolve()),
        "geometryReportSha256": sha256(args.geometry_report),
        "manifests": manifests,
        "assets": results,
        "limitations": [
            "An alternative node is virtual: this audit does not mutate the saved single-parent graph or implement a runtime DAG2 selector.",
            "Whole-cut maximum screen error is reconstructed only for OBJ inputs using the default auto-framed camera and is reported only when it matches the saved maximum; this is not a rendered-image comparison.",
            "Matching oriented boundaries and exact-once leaf coverage preserve the cut's external interface; rendering, shading, and full cross-node topology still need evaluation.",
        ],
    }
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = []
    for asset in results:
        rows = [item for item in asset["sameBudgetSubstitutionsFromNativeSelectedNodes"]
                if item["virtualCutExactOnceLeafCoverage"] and item["sameOrientedBoundary"]
                and item["sameParentBounds"]]
        summary.append({"asset": asset["asset"], "eligibleNativeCutSubstitutions": len(rows),
                        "lowerLocalErrorSubstitutions": sum(
                            item["localErrorReductionFraction"] > 0 for item in rows),
                        "reconstructedWholeCutMaxImprovements": sum(
                            bool(item["screenErrorAudit"] and
                                 item["screenErrorAudit"]["nativeMaxReconstructionMatches"] and
                                 item["screenErrorAudit"]["wholeCutMaxScreenErrorReduced"])
                            for item in rows)})
    print(json.dumps({"output": str(output), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
