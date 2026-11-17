#!/usr/bin/env python3
"""Reconstruct and validate an offline mixed-group cut before raster evaluation.

The tool recreates the source-vertex order used by this repository's Assimp OBJ path,
checks that recreation against the saved native g2 cut, and then writes the MILP-selected
mixed cut as a PLY. It is an experiment/audit helper, not a runtime cut assembler.
"""

import argparse
import collections
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def f32(value):
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def f32_tuple(values):
    return tuple(f32(value) for value in values)


def parse_obj_import_order(path):
    """Simulate ObjFileImporter flat corners followed by JoinIdenticalVertices.

    This matches the vendored Assimp path for the screened OBJ assets: one material mesh per
    object and JoinIdenticalVertices retaining first occurrence order. Convex polygons are
    triangulated as a fan; the exact leaf-face multiset is checked before using the map.
    The resulting count and native-cut geometry are separately verified before use.
    """
    positions = [None]
    uvs = [None]
    normals = [None]
    object_name = "default"
    material_name = "default"
    raw_faces = []
    object_order = []
    material_by_object = {}

    def resolve_index(raw, count):
        index = int(raw)
        return index if index > 0 else count + index

    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parts = line.split()
            if not parts:
                continue
            kind = parts[0]
            if kind == "v":
                positions.append(f32_tuple(parts[1:4]))
            elif kind == "vt":
                uv = list(map(float, parts[1:]))
                uvs.append(f32_tuple((uv[0], uv[1])))
            elif kind == "vn":
                normals.append(f32_tuple(parts[1:4]))
            elif kind == "o":
                object_name = parts[1] if len(parts) > 1 else "default"
                if object_name not in object_order:
                    object_order.append(object_name)
            elif kind == "usemtl":
                material_name = parts[1] if len(parts) > 1 else "default"
                material_by_object.setdefault(object_name, set()).add(material_name)
            elif kind == "f":
                corners = []
                for token in parts[1:]:
                    fields = token.split("/")
                    vi = resolve_index(fields[0], len(positions))
                    ti = resolve_index(fields[1], len(uvs)) if len(fields) > 1 and fields[1] else 0
                    ni = resolve_index(fields[2], len(normals)) if len(fields) > 2 and fields[2] else 0
                    corners.append((vi, ti, ni))
                raw_faces.append((object_name, material_name, corners))

    if any(len(corners) < 3 for _, _, corners in raw_faces):
        counts = collections.Counter(len(corners) for _, _, corners in raw_faces)
        raise ValueError(f"OBJ face has fewer than three corners: {dict(counts)}")
    if any(len(materials) != 1 for materials in material_by_object.values()):
        raise ValueError("the OBJ import-order simulation only accepts one material mesh per object")

    mesh_keys = []
    seen_meshes = set()
    for obj, material, _ in raw_faces:
        key = (obj, material)
        if key not in seen_meshes:
            seen_meshes.add(key)
            mesh_keys.append(key)
    mesh_ids = {key: index for index, key in enumerate(mesh_keys)}
    vertex_map = {}
    source_vertices = []
    source_triangles = []

    for obj, material, corners in raw_faces:
        mesh_key = (obj, material)
        mapped = []
        for vi, ti, ni in corners:
            position = positions[vi]
            uv = uvs[ti] if ti else (0.0, 0.0)
            normal = normals[ni] if ni else (0.0, 0.0, 0.0)
            # Assimp's JoinIdenticalVertices checks position, normal and UV with 1e-5
            # tolerances. The only duplicate signatures in this asset are exact matches.
            signature = (mesh_key,
                    struct.pack("<8f", *(position + normal + uv)))
            source_index = vertex_map.get(signature)
            if source_index is None:
                source_index = len(source_vertices)
                vertex_map[signature] = source_index
                source_vertices.append((position, normal, uv))
            mapped.append(source_index)
        # The checked assets use convex polygons; Assimp preserves their winding.
        source_triangles.extend((mesh_ids[mesh_key], (mapped[0], mapped[index], mapped[index + 1]))
                for index in range(1, len(mapped) - 1))

    return source_vertices, source_triangles, mesh_keys


def read_mmb(path, node_ids):
    blob = Path(path).read_bytes()
    cursor = 0

    def take_u32():
        nonlocal cursor
        value = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        return value

    magic = take_u32()
    version = take_u32()
    node_count = take_u32()
    root_count = take_u32()
    leaf_count = take_u32()
    _level_count = take_u32()
    _base_triangles = struct.unpack_from("<Q", blob, cursor)[0]
    cursor += 8
    vertex_count = take_u32()
    if magic != 0x474C4D4D or version != 7:
        raise ValueError(f"unsupported MMB header at {path}: {magic:#x} v{version}")
    roots = list(struct.unpack_from(f"<{root_count}I", blob, cursor))
    cursor += root_count * 4
    leaves = list(struct.unpack_from(f"<{leaf_count}I", blob, cursor))
    cursor += leaf_count * 4
    generated_count = take_u32()
    generated = []
    for _ in range(generated_count):
        row = struct.unpack_from("<I9f", blob, cursor)
        generated.append((row[1:4], row[4:7], row[7:9]))
        cursor += 40
    position_id_count = take_u32()
    position_ids = list(struct.unpack_from(f"<{position_id_count}I", blob, cursor))
    cursor += position_id_count * 4
    if position_id_count != vertex_count:
        raise ValueError(f"position-id count mismatch in {path}")
    offsets = list(struct.unpack_from(f"<{node_count + 1}Q", blob, cursor))
    cursor += (node_count + 1) * 8
    if offsets[0] != cursor or offsets[-1] != len(blob):
        raise ValueError(f"invalid MMB offsets in {path}")

    selected = {}
    source_count = vertex_count - generated_count
    for node_id in set(node_ids):
        if node_id < 0 or node_id >= node_count:
            raise ValueError(f"node id {node_id} outside {path}")
        pos = offsets[node_id]
        level, parent, material, submesh, child_count, index_count = struct.unpack_from(
                "<6I", blob, pos)
        pos += 184
        children = list(struct.unpack_from(f"<{child_count}I", blob, pos))
        pos += child_count * 4
        indices = list(struct.unpack_from(f"<{index_count}I", blob, pos))
        pos += index_count * 4
        if pos != offsets[node_id + 1] or index_count % 3:
            raise ValueError(f"invalid node record {node_id} in {path}")
        if any(index >= vertex_count for index in indices):
            raise ValueError(f"node {node_id} vertex index outside graph vertex table")
        selected[node_id] = {
            "level": level, "parent": parent, "material": material,
            "submesh": submesh, "children": children, "indices": indices,
        }
    return {
        "sourceCount": source_count, "generated": generated,
        "positionIds": position_ids, "roots": roots, "leaves": leaves,
        "nodes": selected,
    }


def load_ply(path):
    with Path(path).open("rb") as stream:
        header = []
        while True:
            raw = stream.readline()
            if not raw:
                raise ValueError(f"unterminated PLY header in {path}")
            line = raw.decode("ascii").strip()
            header.append(line)
            if line == "end_header":
                break
        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"expected binary little-endian PLY: {path}")
        vertex_count = next(int(line.split()[2]) for line in header if line.startswith("element vertex "))
        face_count = next(int(line.split()[2]) for line in header if line.startswith("element face "))
        vertex_properties = []
        in_vertex = False
        for line in header:
            if line.startswith("element "):
                in_vertex = line.startswith("element vertex ")
            elif in_vertex and line.startswith("property "):
                parts = line.split()
                vertex_properties.append((parts[2], parts[1]))
        expected = [(name, "float") for name in ("x", "y", "z", "nx", "ny", "nz", "s", "t")]
        if vertex_properties != expected:
            raise ValueError(f"unsupported PLY vertex schema: {vertex_properties}")
        raw_vertices = stream.read(vertex_count * 32)
        vertices = np.frombuffer(raw_vertices, dtype="<f4").reshape(vertex_count, 8).copy()
        faces = []
        for _ in range(face_count):
            count = stream.read(1)
            if count != b"\x03":
                raise ValueError(f"non-triangle or truncated face in {path}")
            faces.append(struct.unpack("<iiiII", stream.read(20)))
    return vertices, faces


def vertex_bytes(vertex):
    return struct.pack("<8f", *map(float, vertex))


def oriented_face_key(vertices):
    row = tuple(vertex_bytes(vertex) for vertex in vertices)
    return min(row, row[1:] + row[:1], row[2:] + row[:2])


def face_counter_from_ply(vertices, faces):
    counts = collections.Counter()
    for a, b, c, material, submesh in faces:
        counts[(int(material), int(submesh), oriented_face_key(
                (vertices[a], vertices[b], vertices[c])))] += 1
    return counts


def oriented_position_key(vertices):
    row = tuple(tuple(round(float(value), 6) for value in vertex[:3]) for vertex in vertices)
    return min(row, row[1:] + row[:1], row[2:] + row[:2])


def oriented_position_attribute_key(vertices):
    row = tuple((tuple(round(float(value), 6) for value in vertex[:3]),
            struct.pack("<5f", *map(float, vertex[3:8]))) for vertex in vertices)
    return min(row, row[1:] + row[:1], row[2:] + row[:2])


def position_face_counter_from_ply(vertices, faces):
    counts = collections.Counter()
    for a, b, c, material, submesh in faces:
        counts[(int(material), int(submesh), oriented_position_key(
                (vertices[a], vertices[b], vertices[c])))] += 1
    return counts


def position_attribute_face_counter_from_ply(vertices, faces):
    counts = collections.Counter()
    for a, b, c, material, submesh in faces:
        counts[(int(material), int(submesh), oriented_position_attribute_key(
                (vertices[a], vertices[b], vertices[c])))] += 1
    return counts


def node_triangles(node, source_vertices, mmb):
    indices = node["indices"]
    result = []
    for offset in range(0, len(indices), 3):
        vertices = []
        for index in indices[offset:offset + 3]:
            if index < mmb["sourceCount"]:
                source = source_vertices[index]
                vertices.append(source[0] + source[1] + source[2])
            else:
                generated = mmb["generated"][index - mmb["sourceCount"]]
                vertices.append(generated[0] + generated[1] + generated[2])
        result.append((node["material"], node["submesh"], tuple(vertices)))
    return result


def triangle_counter(triangles):
    counts = collections.Counter()
    for material, submesh, vertices in triangles:
        counts[(material, submesh, oriented_face_key(vertices))] += 1
    return counts


def triangle_position_counter(triangles):
    counts = collections.Counter()
    for material, submesh, vertices in triangles:
        counts[(material, submesh, oriented_position_key(vertices))] += 1
    return counts


def triangle_position_attribute_counter(triangles):
    counts = collections.Counter()
    for material, submesh, vertices in triangles:
        counts[(material, submesh, oriented_position_attribute_key(vertices))] += 1
    return counts


def max_matched_position_delta(expected_triangles, actual_triangles):
    def buckets(triangles):
        result = collections.defaultdict(list)
        for material, submesh, vertices in triangles:
            key = (material, submesh, oriented_position_key(vertices))
            rotations = [vertices, vertices[1:] + vertices[:1], vertices[2:] + vertices[:2]]
            canonical = min(rotations, key=lambda row: tuple(
                    tuple(round(float(value), 6) for value in vertex[:3]) for vertex in row))
            result[key].append(canonical)
        return result

    expected = buckets(expected_triangles)
    actual = buckets(actual_triangles)
    if {key: len(value) for key, value in expected.items()} != {
            key: len(value) for key, value in actual.items()}:
        return None
    return max((abs(float(a[corner][axis]) - float(b[corner][axis]))
            for key in expected
            for a, b in zip(expected[key], actual[key])
            for corner in range(3) for axis in range(3)), default=0.0)


def source_face_counter(source_vertices, source_triangles):
    counts = collections.Counter()
    for submesh, triangle in source_triangles:
        vertices = [source_vertices[index][0] + source_vertices[index][1]
                + source_vertices[index][2] for index in triangle]
        # OBJ material ids are not needed for this independent vertex-order check.
        counts[(submesh, oriented_face_key(vertices))] += 1
    return counts


def write_ply(path, triangles):
    vertex_ids = {}
    vertices = []
    faces = []
    for material, submesh, triangle in triangles:
        face = []
        for vertex in triangle:
            key = vertex
            index = vertex_ids.get(key)
            if index is None:
                index = len(vertices)
                vertex_ids[key] = index
                vertices.append(vertex)
            face.append(index)
        faces.append((face[0], face[1], face[2], material, submesh))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        header = (
            "ply\nformat binary_little_endian 1.0\n"
            f"element vertex {len(vertices)}\n"
            "property float x\nproperty float y\nproperty float z\n"
            "property float nx\nproperty float ny\nproperty float nz\n"
            "property float s\nproperty float t\n"
            f"element face {len(faces)}\n"
            "property list uchar int vertex_indices\n"
            "property uint material_id\nproperty uint submesh_id\nend_header\n"
        )
        stream.write(header.encode("ascii"))
        for vertex in vertices:
            stream.write(struct.pack("<8f", *vertex))
        for a, b, c, material, submesh in faces:
            stream.write(struct.pack("<BiiiII", 3, a, b, c, material, submesh))
    return len(vertices), len(faces)


def topology_summary(triangles):
    edge_use = collections.Counter()
    directed_use = collections.Counter()
    face_use = collections.Counter()
    degenerate = 0
    for _material, _submesh, vertices in triangles:
        point_keys = [tuple(round(float(value), 6) for value in vertex[:3]) for vertex in vertices]
        face_use[tuple(sorted(point_keys))] += 1
        points = np.asarray([vertex[:3] for vertex in vertices], dtype=np.float64)
        if np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0])) <= 1e-12:
            degenerate += 1
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edge = (point_keys[a], point_keys[b])
            undirected = tuple(sorted(edge))
            edge_use[undirected] += 1
            directed_use[(undirected, edge[0] == undirected[0])] += 1
    boundaries = collections.Counter(edge for edge, count in edge_use.items() if count == 1)
    nonmanifold = sum(count > 2 for count in edge_use.values())
    same_direction = sum(
        count == 2 and directed_use[(edge, True)] in (0, 2)
        for edge, count in edge_use.items())
    return {
        "triangleCount": len(triangles),
        "uniqueGeometricFaces": len(face_use),
        "duplicateGeometricFaces": sum(count - 1 for count in face_use.values() if count > 1),
        "degenerateTriangles": degenerate,
        "boundaryEdges": sum(boundaries.values()),
        "nonManifoldEdges": nonmanifold,
        "sameDirectionTwoFaceEdges": same_direction,
        "boundaryCounter": boundaries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mixed-json", type=Path,
            default=ROOT / "out/mixed-group-frontier-20261117/shapes.json")
    parser.add_argument("--native-ply", type=Path,
            default=ROOT / "out/targetbudget-heldout-20261116/rep-01/shapes-g2/selected_ratio_0.55.ply")
    parser.add_argument("--output-ply", type=Path,
            default=ROOT / "out/mixed-group-frontier-20261117/shapes-mixed.ply")
    parser.add_argument("--output-json", type=Path,
            default=ROOT / "out/mixed-group-frontier-20261117/geometry_audit.json")
    args = parser.parse_args()

    result = json.loads(args.mixed_json.read_text(encoding="utf-8"))
    source_path = Path(result["inputs"]["source"]["path"])
    if sha256(source_path) != result["inputs"]["source"]["sha256"]:
        raise ValueError("source hash differs from the mixed-frontier run")
    source_vertices, source_triangles, mesh_keys = parse_obj_import_order(source_path)

    sys_path = str(ROOT / "tools/mmgeo")
    if sys_path not in __import__("sys").path:
        __import__("sys").path.insert(0, sys_path)
    from audit_shared_parent_candidate_reuse import decode_binary_graph

    graphs = {}
    mmbs = {}
    graph_records = {int(row["group"]): row for row in result["inputs"]["graphs"]}
    for group in result["groups"]:
        record = graph_records[int(group)]
        graph_path = Path(record["path"])
        mmb_path = Path(record["mmbPath"])
        if sha256(graph_path) != record["sha256"] or sha256(mmb_path) != record["mmbSha256"]:
            raise ValueError(f"input graph/MMB hash mismatch for group {group}")
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        # Reuse the full JSON/MMB metadata and binary topology audit before extracting faces.
        decode_binary_graph(mmb_path, graph)
        graphs[int(group)] = graph
        needed = set(map(int, graph["leaves"])) if int(group) == 2 else set()
        if int(group) == 2:
            needed.update(map(int, graph["selectedNodes"]))
        needed.update(int(row["node"]) for row in result["chosen"]
                if int(row["group"]) == int(group))
        mmbs[int(group)] = read_mmb(mmb_path, needed)

    source_count = len(source_vertices)
    expected_source_count = int(graphs[2]["sourceVertices"])
    if source_count != expected_source_count:
        raise ValueError(f"simulated Assimp source count {source_count} != graph {expected_source_count}")
    if len(mesh_keys) != max(int(node["submesh"]) for node in graphs[2]["dag"]) + 1:
        raise ValueError("OBJ mesh order does not match graph submesh ids")

    # Validate source-index order against every exact base leaf triangle.
    leaf_triangles = []
    graph2_nodes = {int(node["id"]): node for node in graphs[2]["dag"]}
    for leaf_id in graphs[2]["leaves"]:
        binary_node = mmbs[2]["nodes"][int(leaf_id)]
        if any(index >= source_count for index in binary_node["indices"]):
            raise ValueError(f"base leaf {leaf_id} unexpectedly references generated vertices")
        leaf_triangles.extend(node_triangles(binary_node, source_vertices, mmbs[2]))
    expected_source = source_face_counter(source_vertices, source_triangles)
    actual_source = collections.Counter()
    for _material, submesh, vertices in leaf_triangles:
        actual_source[(submesh, oriented_face_key(vertices))] += 1
    if actual_source != expected_source:
        missing = expected_source - actual_source
        extra = actual_source - expected_source
        raise ValueError(f"source mapping failed base-leaf face check: missing={sum(missing.values())}, extra={sum(extra.values())}")

    # Reconstruct the saved native cut and require exact position/normal/UV and face agreement.
    native_triangles = []
    for node_id in map(int, graphs[2]["selectedNodes"]):
        node = mmbs[2]["nodes"][node_id]
        json_node = graph2_nodes[node_id]
        if node["material"] != int(json_node["material"]) or node["submesh"] != int(json_node["submesh"]):
            raise ValueError(f"native node metadata mismatch at {node_id}")
        native_triangles.extend(node_triangles(node, source_vertices, mmbs[2]))
    native_vertices, native_faces = load_ply(args.native_ply)
    native_expected = face_counter_from_ply(native_vertices, native_faces)
    native_actual = triangle_counter(native_triangles)
    native_expected_positions = position_face_counter_from_ply(native_vertices, native_faces)
    native_actual_positions = triangle_position_counter(native_triangles)
    if native_actual_positions != native_expected_positions:
        missing = native_expected_positions - native_actual_positions
        extra = native_actual_positions - native_expected_positions
        raise ValueError(f"native MMB positions do not match saved PLY: missing={sum(missing.values())}, extra={sum(extra.values())}")
    native_expected_attributes = position_attribute_face_counter_from_ply(native_vertices, native_faces)
    native_actual_attributes = triangle_position_attribute_counter(native_triangles)
    native_ply_triangles = [(int(material), int(submesh), tuple(tuple(map(float, native_vertices[index]))
            for index in (a, b, c))) for a, b, c, material, submesh in native_faces]
    native_position_delta = max_matched_position_delta(native_ply_triangles, native_triangles)

    # Independently verify the selected region cover against every group's hierarchy.
    common_leaves = tuple(map(int, graphs[2]["leaves"]))
    leaf_bit = {leaf: 1 << index for index, leaf in enumerate(common_leaves)}
    chosen_cover = 0
    chosen_triangles = []
    chosen_records = []
    for group, graph in graphs.items():
        if tuple(map(int, graph["leaves"])) != common_leaves:
            raise ValueError(f"source leaf partition differs in g{group}")
    for row in result["chosen"]:
        group, node_id = int(row["group"]), int(row["node"])
        graph = graphs[group]
        json_nodes = {int(node["id"]): node for node in graph["dag"]}
        masks = {}
        for node in sorted(graph["dag"], key=lambda item: (int(item["level"]), int(item["id"]))):
            node_id_current = int(node["id"])
            children = list(map(int, node.get("children", [])))
            if not children:
                masks[node_id_current] = leaf_bit[node_id_current]
            else:
                mask = 0
                for child in children:
                    if mask & masks[child]:
                        raise ValueError(f"overlapping child regions at g{group}/node{node_id_current}")
                    mask |= masks[child]
                masks[node_id_current] = mask
        mask = masks[node_id]
        if chosen_cover & mask:
            raise ValueError(f"mixed cut overlaps leaf region at g{group}/node{node_id}")
        chosen_cover |= mask
        node = mmbs[group]["nodes"][node_id]
        if len(node["indices"]) // 3 != int(row["triangles"]):
            raise ValueError(f"candidate triangle count mismatch at g{group}/node{node_id}")
        if node["material"] != int(row["material"]) or node["submesh"] != int(row["submesh"]):
            raise ValueError(f"candidate material/submesh mismatch at g{group}/node{node_id}")
        chosen_triangles.extend(node_triangles(node, source_vertices, mmbs[group]))
        chosen_records.append((group, node_id, mask.bit_count()))
    all_leaves = (1 << len(common_leaves)) - 1
    if chosen_cover != all_leaves:
        raise ValueError("mixed candidate nodes do not cover every source leaf exactly once")
    triangle_count = sum(int(row["triangles"]) for row in result["chosen"])
    if triangle_count != int(result["triangleCount"]):
        raise ValueError("mixed triangle sum differs from MILP record")

    native_topology = topology_summary(native_triangles)
    mixed_topology = topology_summary(chosen_triangles)
    boundary_equal = native_topology["boundaryCounter"] == mixed_topology["boundaryCounter"]
    output_vertices, output_faces = write_ply(args.output_ply, chosen_triangles)
    payload = {
        "scope": "offline mixed-group patch reconstruction and geometry audit; no runtime assembler or rendering claim",
        "asset": result["asset"],
        "sourceVertexOrder": {
            "simulatedAssimpSourceVertices": source_count,
            "graphSourceVertices": expected_source_count,
            "submeshes": [{"id": index, "object": obj, "material": material}
                    for index, (obj, material) in enumerate(mesh_keys)],
            "baseLeafFaceMultisetExact": True,
        },
        "nativeCutPlyMatch": {
            "path": str(args.native_ply.resolve()),
            "triangleCount": len(native_triangles),
            "orientedPositionMaterialSubmeshMultisetMatchesAt1e-6": True,
            "orientedPositionNormalUvMaterialSubmeshMultisetExactAt1e-6Position":
                    native_actual_attributes == native_expected_attributes,
            "normalUvAttributeFaceMismatches": sum((native_expected_attributes
                    - native_actual_attributes).values()),
            "maxMatchedPositionDelta": native_position_delta,
            "bitwiseFloat8FaceMultisetExact": native_actual == native_expected,
        },
        "mixedCut": {
            "groups": result["groups"],
            "patchCount": len(result["chosen"]),
            "triangleCount": triangle_count,
            "triangleBudget": int(result["triangleBudget"]),
            "exactLeafCover": True,
            "generatedPly": str(args.output_ply.resolve()),
            "plyVertexCount": output_vertices,
            "plyTriangleCount": output_faces,
            "patchComposition": dict(collections.Counter(str(group) for group, _, _ in chosen_records)),
        },
        "topology": {
            "positionWeldTolerance": 1e-6,
            "nativeG2": {key: value for key, value in native_topology.items() if key != "boundaryCounter"},
            "mixed": {key: value for key, value in mixed_topology.items() if key != "boundaryCounter"},
            "boundaryEdgesMatchNativeG2Exactly": boundary_equal,
        },
        "hashes": {
            "mixedFrontierJson": sha256(args.mixed_json),
            "sourceObj": sha256(source_path),
            "nativePly": sha256(args.native_ply),
            "generatedMixedPly": sha256(args.output_ply),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "nativeCutPlyMatch": payload["nativeCutPlyMatch"],
        "mixedCut": payload["mixedCut"],
        "topology": payload["topology"],
        "output": str(args.output_json.resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
