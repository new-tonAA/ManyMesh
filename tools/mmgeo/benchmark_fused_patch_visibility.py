"""Frozen local-proxy cut experiment; no native/GPU or novelty claim."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import depth_candidate_pilot as raster
from fused_patch_visibility import FusedPatchQuery, build_patch, cut_nodes, scalar_mesh_cache
from visibility_query_bvh import BVH, Ray


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(binding):
    if sha(binding["path"]) != binding["sha256"]:
        raise ValueError("bound file changed: " + binding["path"])


def run_queries(query, rays, metrics=False):
    answers = np.empty(len(rays), bool)
    costs = np.empty((len(rays), 3), dtype=np.int64)
    statistics = np.zeros((len(rays), 4), dtype=np.int64)
    for i, ray in enumerate(rays):
        count, stat = [0, 0, 0], [0, 0, 0, 0]
        answers[i] = query.query(ray, count, stat) if metrics else query.query(ray, count)
        costs[i] = count
        statistics[i] = stat
    return answers, costs, statistics


def cohorts(costs, masks):
    return {name: dict(rays=int(mask.sum()), sums=costs[mask].sum(0).tolist()) for name, mask in masks.items()}


def run_asset(asset, old, output, repeats):
    for name in ("capture", "rayArtifact"):
        require(asset[name])
    fine_binding = next(iter(asset["levels"].values()))["trees"]["fine"]
    require(fine_binding)
    with np.load(fine_binding["path"], allow_pickle=False) as archive:
        tree = scalar_mesh_cache(BVH.from_packed(dict(archive)))
    with np.load(asset["rayArtifact"]["path"], allow_pickle=False) as archive:
        ray_data = dict(archive)
    if not np.allclose(np.linalg.norm(ray_data["directions"], axis=1), 1., atol=1e-14, rtol=0):
        raise ValueError("cone queries require normalized ray directions")
    rays = [Ray(tuple(o), tuple(d), float(t)) for o, d, t in zip(
        ray_data["origins"], ray_data["directions"], ray_data["maximum"])]
    expected = ray_data["fineExpected"]
    world, faces, _ = raster.load_capture(Path(asset["capture"]["path"]))
    center = (world.min(0) + world.max(0)) * .5
    radius = float(np.linalg.norm(world - center, axis=1).max())
    positions = (world - center) / radius
    if len(tree.bounds) != len(faces):
        raise ValueError("source tree face count mismatch")
    # Verify geometry/primitive indexing of the saved original tree.
    tri = positions[faces]
    cache = np.stack((tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    if not np.array_equal(cache, np.asarray(tree.triangles)):
        raise ValueError("source tree geometry differs from capture")
    baseline_answers, baseline_costs, _ = run_queries(tree, rays)
    if not np.array_equal(baseline_answers, expected):
        raise ValueError("fine query differs from independent saved raster")
    disabled = FusedPatchQuery(tree, {}, "baseline")
    answers, disabled_costs, _ = run_queries(disabled, rays)
    if not (np.array_equal(answers, expected) and np.array_equal(disabled_costs, baseline_costs)):
        raise ValueError("disabled fused traversal changes original answers/counts")
    masks = dict(viewport=np.ones(len(rays), bool), sourceRectangle=ray_data["sourceRectangle"],
                 fineHits=expected, fineMisses=~expected)
    memo, cuts = {}, []
    for capacity in (32, 64, 128):
        cut, ranges = cut_nodes(tree, capacity)
        start = time.perf_counter()
        new_nodes = 0
        for node in cut:
            if node not in memo:
                record, patch = build_patch(tree, node, positions, faces, ranges)
                memo[node] = record, patch
                new_nodes += 1
        incremental_seconds = time.perf_counter() - start
        records = [memo[node][0] for node in cut]
        active = {node: memo[node][1] for node in cut if memo[node][1] is not None}
        query = FusedPatchQuery(tree, active, "actual")
        oracle = FusedPatchQuery(tree, active, "oracle")
        answers, costs, stats = run_queries(query, rays, True)
        oracle_answers, oracle_costs, oracle_stats = run_queries(oracle, rays, True)
        if not (np.array_equal(answers, expected) and np.array_equal(oracle_answers, expected)):
            bad = np.flatnonzero((answers != expected) | (oracle_answers != expected))
            raise ValueError(f"fused coverage error {asset['asset']} {capacity}: {bad.tolist()}")
        weights = np.array([1, 2, 0])
        if np.any(oracle_costs @ weights > baseline_costs @ weights):
            raise ValueError("free local oracle exceeds fine weighted work")
        print(asset["asset"], capacity, "patches", len(active), "/", len(cut),
              "free-oracle work", float((oracle_costs @ weights).sum() / (baseline_costs @ weights).sum()), flush=True)
        # Save every constructed patch, including rejected candidates, for independent inspection.
        manifest_path = output / (asset["asset"] + f"-{capacity}-patches.json")
        manifest_path.write_text(json.dumps(dict(capacity=capacity, cut=cut, patches=records), indent=2) + "\n", encoding="utf-8")
        payloads = {}
        proxy_bindings = {}
        for node, (proxy, cone) in active.items():
            for key, value in proxy.packed().items():
                payloads[f"n{node}_{key}"] = value
            payloads[f"n{node}_cone"] = np.asarray(cone)
            packed = proxy.packed()
            proxy_bindings[node] = sum(v.nbytes for k, v in packed.items() if k != "bounds") + 4 * 8 + 4
        proxy_path = output / (asset["asset"] + f"-{capacity}-proxies.npz")
        np.savez_compressed(proxy_path, **payloads)
        arrays_path = output / (asset["asset"] + f"-{capacity}-queries.npz")
        np.savez_compressed(arrays_path, fineAnswers=expected, actualAnswers=answers,
            oracleAnswers=oracle_answers, fineCosts=baseline_costs, actualCosts=costs,
            oracleCosts=oracle_costs, actualMetrics=stats, oracleMetrics=oracle_stats)
        for candidate in (tree, query):
            run_queries(candidate, rays[:64])
        times = dict(fine=[], actual=[])
        for repeat in range(repeats):
            order = (("fine", tree), ("actual", query))
            if repeat % 2:
                order = order[::-1]
            for label, candidate in order:
                start = time.perf_counter()
                repeated_answers, repeated_costs, _ = run_queries(candidate, rays)
                times[label].append(time.perf_counter() - start)
                reference = baseline_costs if label == "fine" else costs
                if not (np.array_equal(repeated_answers, expected) and np.array_equal(repeated_costs, reference)):
                    raise ValueError("timed query is not deterministic")
        # Fine payload excludes primitive bounds that are only needed by the builder.
        fine_payload = sum(v.nbytes for k, v in tree.packed().items() if k != "bounds")
        row = dict(capacity=capacity, cutNodes=len(cut), activePatches=len(active),
            statuses=dict(Counter(record["status"] for record in records)),
            sourceTrianglesCovered=sum(record["sourceTriangles"] for record in records),
            activeSourceTriangles=sum(record["sourceTriangles"] for record in records if record["active"]),
            activeProxyTriangles=sum(record["outputTriangles"] for record in records if record["active"]),
            incrementalBuildPythonSeconds=incremental_seconds, newNodesBuilt=new_nodes,
            counterCohorts=dict(fine=cohorts(baseline_costs, masks), actual=cohorts(costs, masks),
                               oracle=cohorts(oracle_costs, masks)),
            actualMetrics=stats.sum(0).tolist(), oracleMetrics=oracle_stats.sum(0).tolist(),
            timingInstrumentedPythonSeconds=times,
            medianFineOverActualPythonTime=float(np.median(times["fine"]) / np.median(times["actual"])),
            freeOracleOverFineWeightedWork=float((oracle_costs @ weights).sum() / (baseline_costs @ weights).sum()),
            runtimeArrayPayloadBytes=dict(fine=fine_payload, proxiesAndCones=sum(proxy_bindings.values())),
            patches=dict(path=str(manifest_path), sha256=sha(manifest_path)),
            proxies=dict(path=str(proxy_path), sha256=sha(proxy_path)),
            queries=dict(path=str(arrays_path), sha256=sha(arrays_path)))
        cuts.append(row)
        print(asset["asset"], capacity, "Python fine/actual", row["medianFineOverActualPythonTime"], flush=True)
    return dict(asset=asset["asset"], source=asset["capture"], rays=asset["rayArtifact"], fineTree=fine_binding,
                uniquePatchCandidatesBuilt=len(memo), cuts=cuts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, default=Path("out/visibility-query-bvh-20261115/report.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        raise ValueError("positive repeats required")
    previous = json.loads(args.prior.read_text(encoding="utf-8"))
    if previous["kernelSha256"] != sha(Path(__file__).with_name("visibility_query_bvh.py")):
        raise ValueError("original query kernel changed")
    args.out.mkdir(parents=True, exist_ok=True)
    names = (Path(__file__).name, "fused_patch_visibility.py", "visibility_query_bvh.py",
             "fixed_boundary_qem_control.py", "progressive_geometry_baseline.py",
             "edit_visibility_support.py", "depth_candidate_pilot.py")
    result = dict(schema=1, scope="local fixed-boundary proxies in existing BVH; instrumented Python only",
        prior=dict(path=str(args.prior), sha256=sha(args.prior)),
        sourceHashes={name: sha(Path(__file__).with_name(name)) for name in names},
        capacities=[32, 64, 128], repeats=args.repeats,
        oracleWeights=[1, 2, 0], metricOrder=["patch visits", "certificates accepted", "proxy chosen", "clipped patch visits"],
        costOrder=["AABB tests", "triangle tests", "cone tests"], assets=[])
    for asset in previous["assets"]:
        result["assets"].append(run_asset(asset, previous, args.out, args.repeats))
        (args.out / "partial.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["caveats"] = ["existing spatial SAH hierarchy; no independent support traversal",
        "source/final oriented boundary and contained placements checked; no robust float proof",
        "unit direction, fixed orthographic binary any-hit cohort; no shading or realistic shadow workload",
        "free oracle knows local outcomes and costs; not an implementable selector",
        "array payload excludes object/container overhead and is not GPU memory",
        "geometry-only local QEM; not production Corner or authored attribute preservation",
        "three reused development assets; no unseen generalization or novelty conclusion"]
    (args.out / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("wrote", args.out / "report.json", flush=True)


if __name__ == "__main__":
    main()
