"""Find the minimum-face cut of a saved hierarchy under explicit welded edge checks."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack

from audit_cut_edge_witnesses import edge_failures, edge_signature, edge_uses, group_leaves
from audit_mixed_group_cut_geometry import parse_obj_import_order, read_mmb, sha256
from bench_upstream_clusterlod import OBJ_SCALE, assess, boundary, compact


def load_graph(source, table, blob):
    graph = json.loads(table.read_text(encoding="utf-8"))
    vertices, source_faces, _ = parse_obj_import_order(source)
    binary = read_mmb(blob, range(len(graph["dag"])))
    if binary["sourceCount"] != len(vertices):
        raise ValueError("Source vertex table does not match the graph")
    positions = [p[0] for p in vertices + binary["generated"]]
    reference = [(-1, face) for _, face in source_faces]
    original = edge_uses(reference, positions)
    boundaries = {edge: edge_signature(uses)[1] for edge, uses in original.items()
                  if len(uses) == 1}
    if edge_failures(original, boundaries):
        raise ValueError("Expected an edge-manifold source")
    return binary, positions, reference, boundaries


def model(binary, positions, boundaries):
    nodes = binary["nodes"]
    parent_chains = defaultdict(list)
    faces = defaultdict(Counter)
    edges = defaultdict(Counter)
    oriented = defaultdict(Counter)
    raw = {}
    enabled = np.ones(len(nodes))
    for node, n in nodes.items():
        for leaf in group_leaves(nodes, node):
            parent_chains[leaf].append(node)
        indices = n["indices"]
        local = [(node, tuple(indices[i:i + 3])) for i in range(0, len(indices), 3)]
        raw[node] = local
        points = np.asarray([positions[i] for i in indices], dtype=np.float64).reshape(-1, 3, 3)
        area = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        if np.any(np.all(area == 0, axis=1)):
            enabled[node] = 0
        for _, face in local:
            faces[tuple(sorted(positions[i] for i in face))][node] += 1
        for edge, uses in edge_uses(local, positions).items():
            count, sign = edge_signature(uses)
            edges[edge][node] = count
            if sign:
                oriented[edge][node] = sign
    row, col, values, lower, upper = [], [], [], [], []

    def constrain(coefficients, lo, hi):
        row.extend([len(lower)] * len(coefficients))
        col.extend(coefficients)
        values.extend(coefficients.values())
        lower.append(lo)
        upper.append(hi)

    if set(parent_chains) != set(binary["leaves"]):
        raise ValueError("Node child references disagree with the serialized leaves")
    for ancestors in parent_chains.values():
        constrain(Counter(ancestors), 1, 1)
    for edge in edges.keys() | boundaries.keys():
        count = edges.get(edge, {})
        signed = oriented.get(edge, {})
        if edge in boundaries:
            constrain(count, 1, 1)
        elif sum(count.values()) > 2:
            constrain(count, 0, 2)
        if signed or edge in boundaries:
            direction = boundaries.get(edge, 0)
            constrain(signed, direction, direction)
    for candidates in faces.values():
        if sum(candidates.values()) > 1:
            constrain(candidates, 0, 1)

    matrix = coo_matrix((values, (row, col)), shape=(len(lower), len(nodes))).tocsc()
    cost = np.asarray([len(raw[i]) for i in range(len(nodes))], dtype=np.float64)
    return raw, cost, Bounds(0, enabled), LinearConstraint(matrix, lower, upper)


def validate_cut(solution, binary, raw, positions, boundaries, bounds):
    chosen = np.flatnonzero(solution.x > .5).tolist()
    leaf_cover = Counter(leaf for node in chosen for leaf in group_leaves(binary["nodes"], node))
    if leaf_cover != Counter(binary["leaves"]):
        raise ValueError("Solver output does not partition source leaves")
    triangles = [item for node in chosen for item in raw[node]]
    keys = {tuple(sorted(positions[i] for i in face)) for _, face in triangles}
    if len(keys) != len(triangles) or edge_failures(edge_uses(triangles, positions), boundaries):
        raise ValueError("Solver output failed independent topology checks")
    if not np.all(bounds.ub[chosen] == 1):
        raise ValueError("Solver output contains an ineligible node")
    return chosen, triangles


def solve(source, table, blob, cap, time_limit, protocol):
    binary, positions, reference, boundaries = load_graph(source, table, blob)
    started = time.perf_counter()
    raw, cost, bounds, constraints = model(binary, positions, boundaries)
    model_ms = 1000 * (time.perf_counter() - started)
    started = time.perf_counter()
    optimum = milp(cost, integrality=np.ones(len(cost)), bounds=bounds, constraints=constraints,
                   options={"time_limit": time_limit, "mip_rel_gap": 0.0})
    solve_ms = 1000 * (time.perf_counter() - started)
    result = {
        "asset": int(table.parent.name), "source_faces": len(reference), "target_faces": cap,
        "mmb_sha256": sha256(blob), "node_variables": len(cost),
        "constraint_rows": constraints.A.shape[0], "model_ms": model_ms, "solve_ms": solve_ms,
        "solver_status": int(optimum.status), "solver_message": optimum.message,
        "dual_bound": getattr(optimum, "mip_dual_bound", None),
    }
    if optimum.x is None:
        return result
    chosen, triangles = validate_cut(optimum, binary, raw, positions, boundaries, bounds)
    if len(triangles) != round(optimum.fun):
        raise ValueError("Solver output differs from the eligible face objective")
    result.update(faces=len(triangles), under_face_cap=len(triangles) <= cap, selected_nodes=chosen)
    if not result["under_face_cap"]:
        return result
    graph = json.loads(table.read_text(encoding="utf-8"))
    nodes = sorted(graph["dag"], key=lambda node: node["id"])
    quality_cost = np.asarray([node["baseTri"] * node["accumulatedError"] /
                               (len(reference) * OBJ_SCALE) for node in nodes])
    budgeted = LinearConstraint(vstack((constraints.A, cost[None, :]), format="csc"),
                                np.append(constraints.lb, 0.), np.append(constraints.ub, cap))
    started = time.perf_counter()
    best_quality = milp(quality_cost, integrality=np.ones(len(cost)), bounds=bounds,
                        constraints=budgeted, options={"time_limit": time_limit, "mip_rel_gap": 0.0})
    result["budget_cut"] = {
        "solver_status": int(best_quality.status), "solver_message": best_quality.message,
        "solve_ms": (time.perf_counter() - started) * 1000,
    }
    if best_quality.x is not None:
        chosen, triangles = validate_cut(best_quality, binary, raw, positions, boundaries, bounds)
        if len(triangles) > cap:
            raise ValueError("Quality cut exceeded the face cap")
        points = np.asarray(positions, dtype=np.float64) / OBJ_SCALE
        ref = compact(points, np.asarray([face for _, face in reference], dtype=np.int64))
        candidate = compact(points, np.asarray([face for _, face in triangles], dtype=np.int64))
        result["budget_cut"].update(
            selected_nodes=chosen, weighted_accumulated_error=float(best_quality.fun),
            **assess(ref, candidate, boundary(*ref), protocol["views"], protocol["size"],
                     result["asset"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--upstream-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset", type=int)
    parser.add_argument("--time-limit", type=float, default=15.)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    records = []
    for asset in receipt["assets"]:
        if args.asset is not None and asset["asset"] != args.asset:
            continue
        key = str(asset["asset"])
        folder = args.receipt.parent / key
        cap = next(row["target_faces"] for row in asset["cuts"] if row["upstream_cut"] == 1)
        result = solve(args.upstream_dir / key / "source.obj", folder / "lod_graph.json",
                       folder / "lod_graph.mmb", cap, args.time_limit, receipt["protocol"])
        records.append(result)
        print(key, result["solver_status"], cap, result.get("faces"), result["dual_bound"],
              flush=True)
    args.out.write_text(json.dumps({"mmgeo_sha256": receipt["mmgeo_sha256"], "assets": records},
                                  indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
