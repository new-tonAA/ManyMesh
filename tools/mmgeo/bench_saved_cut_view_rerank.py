"""Rerank a bounded pool of feasible saved DAG cuts on calibration views."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack

from audit_manifold_cut_feasibility import load_graph, model, validate_cut
from audit_mixed_group_cut_geometry import sha256
from bench_upstream_clusterlod import OBJ_SCALE, compact
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics
from make_refinement_pairs import view_basis


FIT = (0, 2, 4, 6)
TEST = (1, 3, 5, 7)
SEED = 20261122
OBJECTIVES = ("geometric-error",) * 4 + ("fewest-faces",) * 2 + ("random",) * 6


def summarize(metrics, indices):
    mean = {key: float(np.mean([metrics[i][key] for i in indices]))
            for key in ("mse", "ssim", "flip", "silhouette_xor_fraction", "coverage_mae")}
    mean["psnr_db"] = -10 * float(np.log10(mean["mse"])) if mean["mse"] else None
    return mean


def raster_metrics(points, triangles, captures, size):
    per_view = []
    for basis, reference, ref_coverage in captures:
        image, coverage = render(points, triangles, basis, size, 2)
        per_view.append(image_metrics(reference, image, ref_coverage, coverage, 67.))
    return {"fit": summarize(per_view, FIT), "held_out": summarize(per_view, TEST),
            "per_view": per_view}


def solve_pool(binary, graph, positions, reference, boundaries, cap, asset):
    raw, face_cost, bounds, constraints = model(binary, positions, boundaries)
    # Scale the objective without changing its ordering.
    geometry_cost = np.asarray([
        node["baseTri"] * node["accumulatedError"] / (len(reference) * OBJ_SCALE)
        for node in sorted(graph["dag"], key=lambda node: node["id"])
    ])
    draws = np.random.default_rng(np.random.SeedSequence([SEED, asset]))
    matrix = vstack([constraints.A, face_cost[None, :]], format="csc")
    lower = np.append(constraints.lb, 0.)
    upper = np.append(constraints.ub, cap)
    found, attempts = [], []
    integrality = np.ones(len(face_cost))
    for name in OBJECTIVES:
        if name == "geometric-error":
            cost = geometry_cost
        elif name == "fewest-faces":
            cost = face_cost
        else:
            cost = draws.normal(size=len(face_cost))
        started = time.perf_counter()
        solution = milp(cost, integrality=integrality, bounds=bounds,
                        constraints=LinearConstraint(matrix, lower, upper),
                        options={"mip_rel_gap": 0., "time_limit": 8.})
        attempts.append({"objective": name, "status": int(solution.status),
                         "ms": (time.perf_counter() - started) * 1000})
        if solution.x is None:
            if solution.status == 2:
                break  # With the previous covers excluded, the finite pool is exhausted.
            continue
        chosen, triangles = validate_cut(solution, binary, raw, positions, boundaries, bounds)
        if len(triangles) > cap or any(row["nodes"] == chosen for row, _ in found):
            raise ValueError("Solver produced an over-budget or already excluded cover")
        found.append(({"nodes": chosen, "faces": len(triangles), "objective": name,
                       "geometric_error": float(geometry_cost[chosen].sum())}, triangles))
        # Complete covers cannot contain another complete cover as a strict subset.
        row = csr_matrix((np.ones(len(chosen)), (np.zeros(len(chosen)), chosen)),
                         shape=(1, len(face_cost)))
        matrix = vstack((matrix, row), format="csc")
        lower = np.append(lower, -np.inf)
        upper = np.append(upper, len(chosen) - 1)
    return found, attempts


def run(args):
    graph_receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    upstream = json.loads(args.upstream.read_text(encoding="utf-8"))
    if (graph_receipt["upstream_receipt_sha256"] != sha256(args.upstream)
            or graph_receipt["protocol"] != upstream["protocol"]
            or len(FIT) + len(TEST) != upstream["protocol"]["views"]):
        raise ValueError("Graph export and upstream reference use different view protocols")
    by_asset = {a["asset"]: a for a in upstream["assets"]}
    size = upstream["protocol"]["size"]
    result = {"historical_mmgeo_sha256": graph_receipt["mmgeo_sha256"],
              "upstream_receipt_sha256": sha256(args.upstream), "graph_receipt_sha256": sha256(args.receipt),
              "script_sha256": sha256(Path(__file__)), "fit_views": FIT, "held_out_views": TEST,
              "pool_objective_schedule": OBJECTIVES, "seed": SEED, "assets": []}
    for asset_receipt in graph_receipt["assets"]:
        asset = asset_receipt["asset"]
        if args.asset is not None and asset != args.asset:
            continue
        start = time.perf_counter()
        directory = args.receipt.parent / str(asset)
        graph_path = directory / "lod_graph.json"
        blob = directory / "lod_graph.mmb"
        source = args.upstream_dir / str(asset) / "source.obj"
        binary, positions, reference, boundaries = load_graph(source, graph_path, blob)
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        baseline = next(c["clusterlod"] for c in by_asset[asset]["cuts"] if c["cut"] == 1)
        cap = baseline["faces"]
        if cap != next(c["target_faces"] for c in asset_receipt["cuts"] if c["upstream_cut"] == 1):
            raise ValueError("Selected cut and upstream face budgets differ")
        pool, attempts = solve_pool(binary, graph, positions, reference, boundaries, cap, asset)
        entry = {"asset": asset, "face_cap": cap, "mmb_sha256": sha256(blob),
                 "source_obj_sha256": sha256(source), "attempts": attempts,
                 "exhausted": attempts[-1]["status"] == 2,
                 "upstream": {"fit": summarize(baseline["per_view"], FIT),
                              "held_out": summarize(baseline["per_view"], TEST)},
                 "candidates": []}
        if pool:
            points = np.asarray(positions) / OBJ_SCALE
            reference_geometry = compact(points, np.asarray([face for _, face in reference]))
            bases = [view_basis(i, 8) for i in range(8)]
            captures = [(basis, *render(*reference_geometry, basis, size, 2)) for basis in bases]
            for row, faces in pool:
                geometry = compact(points, np.asarray([face for _, face in faces]))
                row.update(raster_metrics(*geometry, captures, size))
                entry["candidates"].append(row)
            entry["geometric_index"] = 0
            entry["fitted_index"] = min(range(len(pool)), key=lambda i: pool[i][0]["fit"]["flip"])
            entry["hindsight_index"] = min(range(len(pool)),
                                           key=lambda i: pool[i][0]["held_out"]["flip"])
        entry["elapsed_ms"] = (time.perf_counter() - start) * 1000
        result["assets"].append(entry)
        print(asset, cap, len(pool), entry["exhausted"], entry.get("fitted_index"), flush=True)
    if not result["assets"]:
        raise ValueError("No matching assets")
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset", type=int)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
