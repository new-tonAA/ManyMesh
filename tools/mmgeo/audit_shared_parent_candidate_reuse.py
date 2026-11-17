#!/usr/bin/env python3
"""Mine deterministic group-size DAG captures for shared-child parent alternatives.

This preflight decodes MMB v7 node geometry and attributes, verifies the corresponding JSON,
then searches deterministic group-size variants for accepted parent alternatives with identical
immediate child mesh states. It checks exact oriented boundaries, but does not render images.
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


def manifest_graphs(manifest_paths):
    by_asset = defaultdict(list)
    manifest_records = []
    for manifest_path in manifest_paths:
        manifest_path = Path(manifest_path).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_records.append({
            "path": str(manifest_path),
            "sha256": sha256(manifest_path),
            "settings": manifest.get("settings", {}),
        })
        for record in manifest["records"]:
            if int(record.get("repeat", -1)) != 1:
                continue
            command = record["command"]
            try:
                output_index = command.index("--out") + 1
            except ValueError as exc:
                raise ValueError(f"missing --out in record: {record}") from exc
            graph_path = Path(command[output_index]) / "lod_graph.json"
            graph_path = graph_path.resolve()
            mmb_path = graph_path.with_name("lod_graph.mmb")
            if not graph_path.is_file():
                raise FileNotFoundError(graph_path)
            if not mmb_path.is_file():
                raise FileNotFoundError(mmb_path)
            if sha256(graph_path) != record["graphSha256"]:
                raise ValueError(f"graph hash mismatch: {graph_path}")
            by_asset[record["asset"]].append({
                "group": int(record["groupSize"]),
                "qualityGateEnabled": command[command.index("--quality-gate") + 1] == "1"
                if "--quality-gate" in command else False,
                "graphPath": str(graph_path),
                "graphSha256": record["graphSha256"],
                "mmbPath": str(mmb_path),
                "mmbSha256": sha256(mmb_path),
                "sourceSha256": record["sourceSha256"],
                "manifestPath": str(manifest_path),
                "record": record,
            })
    return by_asset, manifest_records


def decode_binary_graph(path, json_graph):
    blob = Path(path).read_bytes()
    cursor = 0

    def u32():
        nonlocal cursor
        value = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        return value

    magic = u32()
    version = u32()
    node_count = u32()
    root_count = u32()
    leaf_count = u32()
    level_count = u32()
    base_triangles = struct.unpack_from("<Q", blob, cursor)[0]
    cursor += 8
    vertex_count = u32() if version >= 3 else 0
    if magic != 0x474C4D4D or version != 7:
        raise ValueError(f"unsupported MMB header in {path}: {magic:#x}, v{version}")

    roots = [u32() for _ in range(root_count)]
    leaves = [u32() for _ in range(leaf_count)]
    generated_count = u32()
    generated_stride = 40
    generated = [blob[cursor + i * generated_stride:
                      cursor + (i + 1) * generated_stride]
                 for i in range(generated_count)]
    cursor += generated_count * generated_stride
    position_id_count = u32()
    position_ids = [u32() for _ in range(position_id_count)]
    if position_id_count != vertex_count:
        raise ValueError(f"position-id count mismatch in {path}")
    offsets = list(struct.unpack_from(f"<{node_count + 1}Q", blob, cursor))
    cursor += (node_count + 1) * 8
    if (offsets[0] != cursor or offsets[-1] != len(blob)
            or any(a > b for a, b in zip(offsets, offsets[1:]))):
        raise ValueError(f"invalid node offset table in {path}")
    source_vertex_count = vertex_count - generated_count
    if source_vertex_count != int(json_graph["sourceVertices"]):
        raise ValueError(f"source vertex count mismatch in {path}")

    node_data = {}
    for node_id in range(node_count):
        start = offsets[node_id]
        end = offsets[node_id + 1]
        node_cursor = start
        fields = struct.unpack_from("<6I", blob, node_cursor)
        level, parent, material, submesh, child_count, index_count = fields
        node_cursor += 24
        base_tri = struct.unpack_from("<Q", blob, node_cursor)[0]
        node_cursor += 8
        self_error, accumulated_error = struct.unpack_from("<2f", blob, node_cursor)
        node_cursor += 8
        node_cursor += 44  # bounds and normal cone
        node_cursor += 4   # simplified flag and padding
        # TopologyStats counters are uint64_t in Quality.h and Streaming.cpp writes
        # all eight counters at their native width.
        topology = struct.unpack_from("<8Q", blob, node_cursor)
        node_cursor += 64
        min_quality, mean_quality = struct.unpack_from("<2f", blob, node_cursor)
        node_cursor += 8
        mean_normal_error, max_normal_error, mean_uv_error, max_uv_error = \
            struct.unpack_from("<4f", blob, node_cursor)
        node_cursor += 16
        node_cursor += 4   # attribute sample count
        node_cursor += 4   # approximated flag and padding
        children = list(struct.unpack_from(f"<{child_count}I", blob, node_cursor))
        node_cursor += child_count * 4
        indices = list(struct.unpack_from(f"<{index_count}I", blob, node_cursor))
        node_cursor += index_count * 4
        if node_cursor != end:
            raise ValueError(f"node {node_id} record length mismatch in {path}")
        if len(indices) % 3:
            raise ValueError(f"node {node_id} has a partial triangle in {path}")

        geometry_keys = {}
        geometry_ids = {}
        geometry_key_ids = {}
        geometry_id_keys = []
        state_keys = {}
        for index in set(indices):
            position_id = position_ids[index]
            if position_id < source_vertex_count:
                geometry_key = b"P" + struct.pack("<I", position_id)
            else:
                representative = position_id - source_vertex_count
                if representative >= len(generated):
                    raise ValueError(f"position id {position_id} is outside {path}")
                # Generated positions are keyed by their serialized xyz, while source
                # position ids remain stable within a same-source build family. This
                # matches the cut assembler's canonical-position welding semantics.
                geometry_key = b"P" + generated[representative][4:16]
            if index < source_vertex_count:
                state_key = b"S" + struct.pack("<I", index)
            else:
                generated_index = index - source_vertex_count
                if generated_index >= len(generated):
                    raise ValueError(f"vertex index {index} is outside {path}")
                record = generated[generated_index]
                # Keep full generated attributes in the state hash so input compatibility
                # remains exact even when two vertices share a canonical position.
                state_key = b"G" + record
            geometry_keys[index] = geometry_key
            geometry_id = geometry_key_ids.get(geometry_key)
            if geometry_id is None:
                geometry_id = len(geometry_id_keys)
                geometry_key_ids[geometry_key] = geometry_id
                geometry_id_keys.append(geometry_key)
            geometry_ids[index] = geometry_id
            state_keys[index] = state_key
        oriented_geometry_faces = []
        oriented_state_faces = []
        edge_counts = {}
        edge_directions = {}
        for offset in range(0, len(indices), 3):
            geometry_face = tuple(geometry_keys[indices[offset + k]] for k in range(3))
            geometry_id_face = tuple(geometry_ids[indices[offset + k]] for k in range(3))
            state_face = tuple(state_keys[indices[offset + k]] for k in range(3))
            oriented_geometry_faces.append(min(
                geometry_face, geometry_face[1:] + geometry_face[:1],
                geometry_face[2:] + geometry_face[:2]))
            oriented_state_faces.append(min(
                state_face, state_face[1:] + state_face[:1],
                state_face[2:] + state_face[:2]))
            for edge in ((geometry_id_face[0], geometry_id_face[1]),
                         (geometry_id_face[1], geometry_id_face[2]),
                         (geometry_id_face[2], geometry_id_face[0])):
                lo, hi = sorted(edge)
                edge_id = (lo << 32) | hi
                count = edge_counts.get(edge_id, 0) + 1
                edge_counts[edge_id] = count
                if count == 1:
                    edge_directions[edge_id] = edge
                elif count == 2:
                    edge_directions.pop(edge_id, None)

        def hash_faces(faces):
            digest = hashlib.sha256(struct.pack("<II", material, submesh))
            for face in sorted(faces):
                digest.update(b"F")
                for key in face:
                    digest.update(struct.pack("<I", len(key)))
                    digest.update(key)
            return digest.hexdigest()

        geometry_hash = hash_faces(oriented_geometry_faces)
        state_hash = hash_faces(oriented_state_faces)
        boundary_hash = hashlib.sha256()
        oriented_boundary_hash = hashlib.sha256()
        boundary_edges = []
        for edge_id, count in edge_counts.items():
            if count != 1:
                continue
            lo = edge_id >> 32
            hi = edge_id & 0xFFFFFFFF
            edge = tuple(sorted((geometry_id_keys[lo], geometry_id_keys[hi])))
            oriented_edge = tuple(
                geometry_id_keys[vertex_id] for vertex_id in edge_directions[edge_id])
            boundary_edges.append((edge, oriented_edge))
        for edge, oriented_edge in sorted(boundary_edges):
            boundary_hash.update(b"E")
            for key in edge:
                boundary_hash.update(struct.pack("<I", len(key)))
                boundary_hash.update(key)
            oriented_boundary_hash.update(b"E")
            for key in oriented_edge:
                oriented_boundary_hash.update(struct.pack("<I", len(key)))
                oriented_boundary_hash.update(key)

        node_data[node_id] = {
            "level": level,
            "parent": parent,
            "material": material,
            "submesh": submesh,
            "children": children,
            "baseTriangles": base_tri,
            "triangles": len(indices) // 3,
            "selfError": self_error,
            "accumulatedError": accumulated_error,
            "boundaryEdges": topology[3],
            "nonManifoldEdges": topology[4],
            "duplicateTriangles": topology[5],
            "degenerateTriangles": topology[6],
            "flippedTriangles": topology[7],
            "minQuality": min_quality,
            "meanQuality": mean_quality,
            "meanNormalErrorRadians": mean_normal_error,
            "maxNormalErrorRadians": max_normal_error,
            "meanUvError": mean_uv_error,
            "maxUvError": max_uv_error,
            "geometrySha256": geometry_hash,
            "meshStateSha256": state_hash,
            "boundarySha256": boundary_hash.hexdigest(),
            "orientedBoundarySha256": oriented_boundary_hash.hexdigest(),
        }

    if (node_count != len(json_graph["dag"])
            or roots != list(map(int, json_graph["roots"]))
            or leaves != list(map(int, json_graph["leaves"]))):
        raise ValueError(f"JSON/MMB node table mismatch in {path}")
    for json_node in json_graph["dag"]:
        node_id = int(json_node["id"])
        binary = node_data[node_id]
        for field in ("level", "parent", "material", "submesh", "children"):
            if binary[field] != json_node[field]:
                raise ValueError(f"JSON/MMB {field} mismatch at node {node_id} in {path}")
        if binary["triangles"] != int(json_node["tri"]):
            raise ValueError(f"JSON/MMB triangle count mismatch at node {node_id} in {path}")
        integer_fields = {
            "boundaryEdges": 3,
            "nonManifoldEdges": 4,
            "duplicateTriangles": 5,
            "degenerateTriangles": 6,
        }
        for field in integer_fields:
            if binary[field] != int(json_node[field]):
                raise ValueError(f"JSON/MMB {field} mismatch at node {node_id} in {path}")
        float_fields = {
            "minQuality": binary["minQuality"],
            "normalErrorDeg": binary["maxNormalErrorRadians"] * 57.29577951308232,
            "uvError": binary["maxUvError"],
        }
        for field, expected in float_fields.items():
            if not math.isclose(float(json_node[field]), expected, rel_tol=2e-5, abs_tol=2e-6):
                raise ValueError(f"JSON/MMB {field} mismatch at node {node_id} in {path}")
    return {
        "version": version,
        "nodeCount": node_count,
        "rootCount": root_count,
        "leafCount": leaf_count,
        "roots": roots,
        "leaves": leaves,
        "levelCount": level_count,
        "baseTriangles": base_triangles,
        "sourceVertexCount": source_vertex_count,
        "generatedVertexCount": generated_count,
        "positionIdCount": position_id_count,
        "nodeData": node_data,
    }


def parse_graph(entry):
    graph = json.loads(Path(entry["graphPath"]).read_text(encoding="utf-8"))
    binary = decode_binary_graph(entry["mmbPath"], graph)
    nodes = {int(node["id"]): node for node in graph["dag"]}
    if len(nodes) != len(graph["dag"]):
        raise ValueError(f"duplicate node ids in {entry['graphPath']}")
    roots = set(map(int, graph["roots"]))
    for node_id, node in nodes.items():
        children = list(map(int, node.get("children", [])))
        if len(children) != len(set(children)):
            raise ValueError(f"duplicate children on node {node_id}")
        parent = int(node.get("parent", (1 << 32) - 1))
        if parent == (1 << 32) - 1:
            if node_id not in roots:
                raise ValueError(f"parentless node {node_id} is not a root")
        elif parent not in nodes or node_id not in nodes[parent].get("children", []):
            raise ValueError(f"inconsistent parent link for node {node_id}")
        for child in children:
            if child not in nodes or int(nodes[child].get("parent", -1)) != node_id:
                raise ValueError(f"inconsistent child link {node_id}->{child}")

    leaf_cache = {}
    visiting = set()

    def leaves(node_id):
        if node_id in leaf_cache:
            return leaf_cache[node_id]
        if node_id in visiting:
            raise ValueError(f"cycle at node {node_id}")
        visiting.add(node_id)
        children = list(map(int, nodes[node_id].get("children", [])))
        if not children:
            value = (node_id,)
        else:
            merged = []
            for child in children:
                merged.extend(leaves(child))
            if len(merged) != len(set(merged)):
                raise ValueError(f"overlapping descendant leaves below node {node_id}")
            value = tuple(sorted(merged))
        visiting.remove(node_id)
        leaf_cache[node_id] = value
        return value

    reachable = set()
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            raise ValueError(f"non-forest graph or repeated reachability at node {node_id}")
        reachable.add(node_id)
        stack.extend(map(int, nodes[node_id].get("children", [])))
    if reachable != set(nodes):
        raise ValueError(f"unreachable nodes in {entry['graphPath']}")
    for root in roots:
        leaves(root)

    leaf_nodes = {}
    for node_id, node in nodes.items():
        if not node.get("children", []):
            leaf_nodes[node_id] = {
                "tri": int(node["tri"]),
                "baseTri": int(node.get("baseTri", node["tri"])),
                "material": int(node.get("material", -1)),
                "submesh": int(node.get("submesh", -1)),
                "bounds": node.get("bounds"),
            }

    parents_by_children = defaultdict(list)
    for node_id, node in nodes.items():
        children = list(map(int, node.get("children", [])))
        if not children:
            continue
        child_regions = tuple(sorted(leaves(child) for child in children))
        parents_by_children[child_regions].append({
            "node": node_id,
            "level": int(node["level"]),
            "leafCount": len(leaves(node_id)),
            "baseTriangles": int(node.get("baseTri", 0)),
            "childTriangles": sum(int(nodes[child]["tri"]) for child in children),
            "triangles": int(node["tri"]),
            "selfError": float(node.get("selfError", 0.0)),
            "accumulatedError": float(node.get("accumulatedError", 0.0)),
            "boundaryEdges": int(node.get("boundaryEdges", 0)),
            "nonManifoldEdges": int(node.get("nonManifoldEdges", 0)),
            "duplicateTriangles": int(node.get("duplicateTriangles", 0)),
            "degenerateTriangles": int(node.get("degenerateTriangles", 0)),
            "minQuality": float(node.get("minQuality", 0.0)),
            "normalErrorDeg": float(node.get("normalErrorDeg", 0.0)),
            "uvError": float(node.get("uvError", 0.0)),
            "parentGeometrySha256": binary["nodeData"][node_id]["geometrySha256"],
            "parentMeshStateSha256": binary["nodeData"][node_id]["meshStateSha256"],
            "parentBoundarySha256": binary["nodeData"][node_id]["boundarySha256"],
            "parentOrientedBoundarySha256":
                binary["nodeData"][node_id]["orientedBoundarySha256"],
            "parentBounds": node.get("bounds"),
            "childMeshStateSha256s": tuple(sorted(
                binary["nodeData"][child]["meshStateSha256"] for child in children)),
            "meanNormalErrorDeg": binary["nodeData"][node_id]["meanNormalErrorRadians"]
            * 57.29577951308232,
            "meanUvError": binary["nodeData"][node_id]["meanUvError"],
            "storedAttributeLimitsPass": (
                binary["nodeData"][node_id]["maxNormalErrorRadians"]
                <= math.radians(35.0)
                and binary["nodeData"][node_id]["meanNormalErrorRadians"]
                <= math.radians(17.5)
                and binary["nodeData"][node_id]["meanUvError"] <= 0.10
                and binary["nodeData"][node_id]["maxUvError"] <= 0.80
                and binary["nodeData"][node_id]["minQuality"] >= 0.02
            ),
            "flippedTriangles": binary["nodeData"][node_id]["flippedTriangles"],
        })

    for candidate_rows in parents_by_children.values():
        for row in candidate_rows:
            row["group"] = entry["group"]
            row["graphPath"] = entry["graphPath"]

    return graph, nodes, leaf_nodes, leaf_cache, parents_by_children, binary


def pareto_rows(rows):
    result = []
    for candidate in rows:
        dominated = any(
            other is not candidate
            and other["triangles"] <= candidate["triangles"]
            and other["accumulatedError"] <= candidate["accumulatedError"]
            and (other["triangles"] < candidate["triangles"]
                 or other["accumulatedError"] < candidate["accumulatedError"])
            for other in rows
        )
        if not dominated:
            result.append(candidate)
    return result


def audit_asset(asset, entries):
    entries = sorted(entries, key=lambda entry: entry["group"])
    graphs = [parse_graph(entry) for entry in entries]
    if len({entry["group"] for entry in entries}) != len(entries):
        raise ValueError(f"duplicate group variants for asset {asset}")
    base_triangles = {int(graph[0]["baseTriangles"]) for graph in graphs}
    target_ratios = {float(graph[0]["targetRatio"]) for graph in graphs}
    config_fields = ("cornerSeam", "cornerSplitUv", "attributeQem", "tier")
    configs = {tuple(graph[0].get(field) for field in config_fields) for graph in graphs}
    if len(base_triangles) != 1 or len(target_ratios) != 1 or len(configs) != 1:
        raise ValueError(f"group variants do not share source/budget/config for {asset}")

    reference_leaves = graphs[0][2]
    stable_leaf_ids = True
    for graph_data in graphs[1:]:
        if graph_data[2] != reference_leaves:
            stable_leaf_ids = False
            break

    merged_parents = defaultdict(list)
    total_parent_nodes = 0
    for entry, graph_data in zip(entries, graphs):
        graph, nodes, leaf_nodes, leaf_cache, by_children, binary = graph_data
        total_parent_nodes += sum(bool(node.get("children", [])) for node in nodes.values())
        if stable_leaf_ids:
            for child_regions, rows in by_children.items():
                merged_parents[child_regions].extend(rows)

    matched = []
    for child_regions, rows in merged_parents.items():
        groups = sorted({row["group"] for row in rows})
        if len(groups) < 2:
            continue
        pareto = pareto_rows(rows)
        same_child_mesh_inputs = len({row["childMeshStateSha256s"] for row in rows}) == 1
        input_matched_rows = rows if same_child_mesh_inputs else []
        input_matched_pareto = pareto_rows(input_matched_rows)
        distinct_parent_meshes = len({row["parentGeometrySha256"] for row in rows})
        distinct_parent_states = len({row["parentMeshStateSha256"] for row in rows})
        metrics = {(row["triangles"], row["selfError"], row["accumulatedError"],
                    row["boundaryEdges"], row["nonManifoldEdges"],
                    row["duplicateTriangles"], row["degenerateTriangles"],
                    row["minQuality"], row["normalErrorDeg"], row["uvError"])
                   for row in rows}
        matched.append({
            "childRegionCount": len(child_regions),
            "leafCount": sum(len(region) for region in child_regions),
            "groups": groups,
            "parentCandidateCount": len(rows),
            "distinctReportedMetricTuples": len(metrics),
            "paretoAlternativeCountByTrianglesAndAccumulatedError": len(pareto),
            "sameChildMeshInputsAcrossVariants": same_child_mesh_inputs,
            "distinctParentMeshGeometryHashes": distinct_parent_meshes,
            "distinctParentMeshStateHashes": distinct_parent_states,
            "allParentBoundaryHashesMatch": len({
                row["parentBoundarySha256"] for row in rows}) == 1,
            "allParentOrientedBoundaryHashesMatch": len({
                row["parentOrientedBoundarySha256"] for row in rows}) == 1,
            "paretoAlternativeCountWithIdenticalChildMeshInputs": len(input_matched_pareto),
            "allParetoParentsHaveZeroFlippedTriangles": all(
                row["flippedTriangles"] == 0 for row in pareto),
            "parents": rows,
            "paretoParents": pareto,
            "identicalInputParetoParents": input_matched_pareto,
        })
    matched.sort(key=lambda item: (-item["paretoAlternativeCountByTrianglesAndAccumulatedError"],
                                   -item["parentCandidateCount"], item["leafCount"]))
    return {
        "asset": asset,
        "groups": [entry["group"] for entry in entries],
        "sourceSha256": sorted({entry["sourceSha256"] for entry in entries}),
        "baseTriangles": next(iter(base_triangles)),
        "leafCount": len(reference_leaves),
        "stableLeafIdsAndPartitionsAcrossVariants": stable_leaf_ids,
        "commonConfig": dict(zip(config_fields, next(iter(configs)))),
        "targetRatio": next(iter(target_ratios)),
        "qualityGateEnabledInEveryBuild": all(entry["qualityGateEnabled"] for entry in entries),
        "parentNodesAcrossVariants": total_parent_nodes,
        "binaryGeometryDecodedAndJsonCrossChecked": True,
        "sharedImmediateChildRegionSets": len(matched),
        "sharedSetsWithDistinctReportedMetrics": sum(
            item["distinctReportedMetricTuples"] > 1 for item in matched),
        "sharedSetsWithMultipleParetoAlternatives": sum(
            item["paretoAlternativeCountByTrianglesAndAccumulatedError"] > 1
            for item in matched),
        "maxDistinctParetoAlternativesForOneChildSet": max((
            item["paretoAlternativeCountByTrianglesAndAccumulatedError"]
            for item in matched), default=0),
        "sharedSetsWithIdenticalChildMeshInputs": sum(
            item["sameChildMeshInputsAcrossVariants"] for item in matched),
        "sharedSetsWithDistinctParentMeshOutputsAndIdenticalInputs": sum(
            item["sameChildMeshInputsAcrossVariants"]
            and item["distinctParentMeshGeometryHashes"] > 1 for item in matched),
        "sharedSetsWithParetoAlternativesAndIdenticalInputs": sum(
            item["paretoAlternativeCountWithIdenticalChildMeshInputs"] > 1
            for item in matched),
        "sharedParentGeometryAlternativeSets": [
            {
                "childRegionCount": item["childRegionCount"],
                "leafCount": item["leafCount"],
                "groups": item["groups"],
                "parentCandidateCount": item["parentCandidateCount"],
                "distinctParentMeshGeometryHashes":
                    item["distinctParentMeshGeometryHashes"],
                "allParentBoundaryHashesMatch": item["allParentBoundaryHashesMatch"],
                "allParentOrientedBoundaryHashesMatch":
                    item["allParentOrientedBoundaryHashesMatch"],
                "parents": [
                    {key: row[key] for key in (
                        "group", "node", "triangles", "selfError", "accumulatedError",
                        "minQuality", "normalErrorDeg", "meanNormalErrorDeg", "uvError",
                        "meanUvError", "storedAttributeLimitsPass", "nonManifoldEdges",
                        "duplicateTriangles", "degenerateTriangles", "flippedTriangles",
                        "parentGeometrySha256", "parentBoundarySha256")}
                        | {"parentOrientedBoundarySha256": row[
                            "parentOrientedBoundarySha256"], "parentBounds": row["parentBounds"]}
                    for row in item["parents"]
                ],
            }
            for item in matched
            if item["sameChildMeshInputsAcrossVariants"]
            and item["distinctParentMeshGeometryHashes"] > 1
        ],
        "sharedChildRegionExamples": [
            {key: item[key] for key in (
                "childRegionCount", "leafCount", "groups", "parentCandidateCount",
                "distinctReportedMetricTuples",
                "paretoAlternativeCountByTrianglesAndAccumulatedError",
                "sameChildMeshInputsAcrossVariants", "distinctParentMeshGeometryHashes",
                "distinctParentMeshStateHashes", "allParentBoundaryHashesMatch")}
                | {"allParentOrientedBoundaryHashesMatch":
                   item["allParentOrientedBoundaryHashesMatch"]}
            for item in matched[:100]
        ],
        "limitations": [
            "Parent surface identity is a canonical oriented-face hash over the graph's canonical position ids and serialized generated positions; it is exact for these same-source captures but is not a geometric distance metric.",
            "The quality-gate flag and stored node metrics establish build provenance and local checks, not a mixed-cut quality or rendered image comparison.",
            "A shared-child alternative needs a mixed-cut exact-once coverage, crack, and strict-gate audit before it can count as a valid DAG2 parent patch.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    by_asset, manifests = manifest_graphs(args.manifests)
    results = [audit_asset(asset, entries) for asset, entries in sorted(by_asset.items())]
    report = {
        "scope": "decoded geometry and attribute search for shared-child parent alternatives mined from deterministic group-size graph variants",
        "manifests": manifests,
        "assets": results,
        "scriptSha256": sha256(Path(__file__)),
    }
    output_path = args.out.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output_path),
        "assets": [{
            "asset": row["asset"],
            "stableLeafIdsAndPartitionsAcrossVariants": row["stableLeafIdsAndPartitionsAcrossVariants"],
            "sharedImmediateChildRegionSets": row["sharedImmediateChildRegionSets"],
            "sharedSetsWithMultipleParetoAlternatives":
                row["sharedSetsWithMultipleParetoAlternatives"],
        } for row in results],
    }, indent=2))


if __name__ == "__main__":
    main()
