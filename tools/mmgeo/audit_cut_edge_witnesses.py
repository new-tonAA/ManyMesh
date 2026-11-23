"""Locate assembled ManyMesh edge violations in the serialized node geometry."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

import numpy as np

from audit_mixed_group_cut_geometry import parse_obj_import_order, read_mmb, sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmtrain"))
from compare_manymesh_clusterlod import load_position_ply


def oriented(face):
    return min(face, face[1:] + face[:1], face[2:] + face[:2])


def group_leaves(nodes, node):
    if not nodes[node]["children"]:
        yield node
    for child in nodes[node]["children"]:
        yield from group_leaves(nodes, child)


def assemble(nodes, selected, position_ids):
    seen = set()
    triangles = []
    skipped = 0
    for node in selected:
        indices = nodes[node]["indices"]
        for offset in range(0, len(indices), 3):
            face = tuple(indices[offset:offset + 3])
            key = tuple(sorted(position_ids[i] for i in face))
            if len(set(face)) != 3 or key in seen:
                skipped += 1
                continue
            seen.add(key)
            triangles.append((node, face))
    return triangles, skipped


def edge_uses(triangles, positions):
    edges = defaultdict(list)
    for node, triangle in triangles:
        for va, vb in zip(triangle, triangle[1:] + triangle[:1]):
            a, b = positions[va], positions[vb]
            if a <= b:
                edges[a, b].append((node, 1))
            else:
                edges[b, a].append((node, -1))
    return edges


def edge_signature(uses):
    return len(uses), sum(direction for _, direction in uses)


def edge_failures(edges, source_boundaries):
    bad = {}
    for edge, uses in edges.items():
        total, signed = edge_signature(uses)
        target = (1, source_boundaries[edge]) if edge in source_boundaries else (2, 0)
        if total != target[0] or signed != target[1]:
            bad[edge] = uses
    for edge in source_boundaries.keys() - edges.keys():
        bad[edge] = []
    return bad


def reconcile_output(output_positions, output_triangles, assembled_positions):
    expected = set(assembled_positions)
    output = {tuple(output_positions[i]) for i in np.unique(output_triangles)}
    mapping = {point: point for point in output & expected}
    max_delta = 0.
    if output - expected:
        candidates = sorted(expected)
        coordinates = np.asarray(candidates, dtype=np.float32)
        tolerance = 2 * np.abs(np.spacing(coordinates))
        for point in output - expected:
            deltas = np.abs(coordinates.astype(np.float64) - point)
            matches = np.flatnonzero(np.all(deltas <= tolerance, axis=1))
            if len(matches) != 1:
                raise ValueError("Unable to associate a PLY vertex with a unique node vertex")
            match = matches[0]
            mapping[point] = candidates[match]
            max_delta = max(max_delta, float(deltas[match].max()))
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("The reconciled PLY vertex mapping is not injective")
    faces = Counter(oriented(tuple(mapping[tuple(output_positions[i])] for i in face))
                    for face in output_triangles)
    return faces, len(output - expected), max_delta


def audit(source, graph_path, mmb_path, ply_path, target_faces):
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    source_vertices, source_triangles, _ = parse_obj_import_order(source)
    binary = read_mmb(mmb_path, range(len(graph["dag"])))
    nodes = binary["nodes"]
    positions = [point[0] for point in source_vertices + binary["generated"]]
    if binary["sourceCount"] != len(source_vertices) or graph["culledTriangles"] != 0:
        raise ValueError("Expected the complete uncropped source")
    expected_leaf_ids = Counter(binary["leaves"])
    selected = graph["selectedNodes"]
    if Counter(leaf for node in selected for leaf in group_leaves(nodes, node)) != expected_leaf_ids:
        raise ValueError("The selected nodes do not partition the hierarchy leaves")
    raw_reference = [(-1, face) for _, face in source_triangles]
    leaf_triangles, _ = assemble(nodes, binary["leaves"], binary["positionIds"])
    as_faces = lambda rows: Counter(oriented(tuple(positions[i] for i in face))
                                    for _, face in rows)
    if as_faces(raw_reference) != as_faces(leaf_triangles):
        raise ValueError("Serialized leaves differ from the staged source")

    chosen, removed = assemble(nodes, selected, binary["positionIds"])
    output_positions, output_triangles = load_position_ply(ply_path)
    output, rounded, max_delta = reconcile_output(
        output_positions, output_triangles, (positions[i] for _, face in chosen for i in face))
    if as_faces(chosen) != output:
        raise ValueError("The PLY does not match the assembled node geometry")
    source_edges = edge_uses(raw_reference, positions)
    boundaries = {edge: edge_signature(uses)[1] for edge, uses in source_edges.items()
                  if len(uses) == 1}
    if edge_failures(source_edges, boundaries):
        raise ValueError("The input has invalid edge incidence")

    selected_edges = edge_uses(chosen, positions)
    defects = edge_failures(selected_edges, boundaries)
    nonmanifold = {edge: uses for edge, uses in defects.items() if len(uses) > 2}
    across = {edge: uses for edge, uses in nonmanifold.items()
              if len({node for node, _ in uses}) > 1}
    introduced = {edge: uses for edge, uses in across.items() if edge not in source_edges}
    raw_node_edges = {}
    examples = []
    for edge, uses in sorted(nonmanifold.items())[:12]:
        by_node = {}
        for node, _ in uses:
            if node not in raw_node_edges:
                faces, _ = assemble(nodes, [node], binary["positionIds"])
                raw_node_edges[node] = edge_uses(faces, positions)
            raw = raw_node_edges[node].get(edge, [])
            by_node[str(node)] = {"level": nodes[node]["level"],
                                 "before_assembly": edge_signature(raw),
                                 "after_assembly": edge_signature(
                                     [(owner, sign) for owner, sign in uses if owner == node])}
        examples.append({"edge": edge, "total_incidence": len(uses), "owners": by_node,
                         "source_incidence": len(source_edges.get(edge, []))})

    start = time.perf_counter()
    rounds = []
    while True:
        refine = {node for uses in defects.values() for node, _ in uses
                  if nodes[node]["children"]}
        # A missing boundary has no owner in this cut and is outside this heuristic.
        if not defects or not refine:
            break
        selected = [child for node in selected
                    for child in (nodes[node]["children"] if node in refine else [node])]
        triangles, _ = assemble(nodes, selected, binary["positionIds"])
        defects = edge_failures(edge_uses(triangles, positions), boundaries)
        rounds.append({"expanded_nodes": sorted(refine), "faces": len(triangles),
                       "remaining_edge_failures": len(defects)})
    after_faces = rounds[-1]["faces"] if rounds else len(chosen)
    return {
        "asset": int(graph_path.parent.name), "target_faces": target_faces,
        "hashes": {path.name: sha256(path) for path in (source, graph_path, mmb_path, ply_path)},
        "ply_matches_assembly": True, "source_faces": len(raw_reference),
        "ply_reconciled_position_count": rounded, "ply_max_position_delta": max_delta,
        "selected_faces": len(chosen), "assembly_dropped_faces": removed,
        "edge_failures": len(edge_failures(selected_edges, boundaries)),
        "nonmanifold_edges": len(nonmanifold), "multi_owner_nonmanifold_edges": len(across),
        "introduced_multi_owner_nonmanifold_edges": len(introduced),
        "examples": examples, "refinement": {
            "rounds": rounds, "passes_edge_check": not defects,
            "faces": after_faces, "under_face_cap": after_faces <= target_faces,
            "python_ms": (time.perf_counter() - start) * 1000,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    records = []
    for asset in receipt["assets"]:
        key = str(asset["asset"])
        folder = args.receipt.parent / key
        depth1 = next(row for row in asset["cuts"] if row["upstream_cut"] == 1)
        records.append(audit(args.upstream_dir / key / "source.obj", folder / "lod_graph.json",
                             folder / "lod_graph.mmb", folder / "selected.ply",
                             depth1["target_faces"]))
        print(key, records[-1]["nonmanifold_edges"], records[-1]["refinement"]["faces"], flush=True)
    args.out.write_text(json.dumps({"mmgeo_sha256": receipt["mmgeo_sha256"], "assets": records},
                                  indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
