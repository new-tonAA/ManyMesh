"""Reconstruct local proxies from saved arrays and check geometry/cost/oracle claims."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster
from edit_visibility_support import boundary_chain
from fused_patch_visibility import FusedPatchQuery, cut_nodes, scalar_mesh_cache
from visibility_query_bvh import BVH, Ray, fit_cone


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(binding):
    if sha(binding["path"]) != binding["sha256"]:
        raise ValueError("artifact hash mismatch: " + binding["path"])


def trace(query, rays, metrics=False):
    answers, counters, stats = [], [], []
    for ray in rays:
        count, stat = [0, 0, 0], [0, 0, 0, 0]
        answers.append(query.query(ray, count, stat) if metrics else query.query(ray, count))
        counters.append(count)
        stats.append(stat)
    return np.asarray(answers), np.asarray(counters), np.asarray(stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = json.loads(args.report.read_text(encoding="utf-8"))
    for name, expected in result["sourceHashes"].items():
        if sha(Path(__file__).with_name(name)) != expected:
            raise ValueError("source changed: " + name)
    require(result["prior"])
    weights = np.array([1, 2, 0])
    cases, queries, geometric_patches = [], 0, 0
    for asset in result["assets"]:
        for name in ("source", "rays", "fineTree"):
            require(asset[name])
        with np.load(asset["fineTree"]["path"], allow_pickle=False) as archive:
            fine = scalar_mesh_cache(BVH.from_packed(dict(archive)))
        with np.load(asset["rays"]["path"], allow_pickle=False) as archive:
            ray_data = dict(archive)
        rays = [Ray(tuple(o), tuple(d), float(t)) for o, d, t in zip(
            ray_data["origins"], ray_data["directions"], ray_data["maximum"])]
        expected = ray_data["fineExpected"]
        world, source_faces, _ = raster.load_capture(Path(asset["source"]["path"]))
        center = (world.min(0) + world.max(0)) * .5
        radius = np.linalg.norm(world - center, axis=1).max()
        positions = (world - center) / radius
        fine_answer, fine_costs, _ = trace(fine, rays)
        if not np.array_equal(fine_answer, expected):
            raise ValueError("fine intersections differ from saved raster")
        queries += len(rays)
        for row in asset["cuts"]:
            for name in ("patches", "proxies", "queries"):
                require(row[name])
            patch_data = json.loads(Path(row["patches"]["path"]).read_text(encoding="utf-8"))
            cut, ranges = cut_nodes(fine, row["capacity"])
            if cut != patch_data["cut"]:
                raise ValueError("saved cut differs from original source tree")
            active = {}
            with np.load(row["proxies"]["path"], allow_pickle=False) as archive:
                for record, node in zip(patch_data["patches"], cut):
                    begin, count = ranges[node]
                    ids = fine.order[begin:begin + count]
                    vertices = np.unique(source_faces[ids])
                    if (record["node"] != node or record["sourceFaces"] != ids
                            or record["sourceVertices"] != vertices.tolist()):
                        raise ValueError("patch does not match its source subtree")
                    if "outputPositions" not in record:
                        if record["active"]:
                            raise ValueError("active patch lacks geometry")
                        continue
                    old = np.asarray(record["sourceOrientedFaces"], int)
                    expected_faces = np.searchsorted(vertices, source_faces[ids])
                    if not np.array_equal(np.sort(old, axis=1), np.sort(expected_faces, axis=1)):
                        raise ValueError("oriented source does not match old triangles")
                    p, f = np.asarray(record["outputPositions"]), np.asarray(record["outputFaces"])
                    before, after = boundary_chain(old), boundary_chain(f)
                    pinned = sorted({v for edge in before for v in edge})
                    original = positions[vertices]
                    if before != after or not np.array_equal(p[pinned], original[pinned]):
                        raise ValueError("fixed oriented boundary differs")
                    if np.any(p < original.min(0)) or np.any(p > original.max(0)):
                        raise ValueError("proxy escaped original box")
                    xyz = np.concatenate((original[old], p[f]))
                    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
                    normals /= np.linalg.norm(normals, axis=1)[:, None]
                    cone = fit_cone(dict(normals=normals, chainValid=True))
                    if list(cone) != record["cone"]:
                        raise ValueError("saved circular cone does not match source/final normals")
                    geometric_patches += 1
                    if not record["active"]:
                        continue
                    prefix = f"n{node}_"
                    packed = {key[len(prefix):]: archive[key] for key in archive.files
                              if key.startswith(prefix) and key != prefix + "cone"}
                    proxy = scalar_mesh_cache(BVH.from_packed(packed))
                    tri = p[f]
                    cache = np.stack((tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
                    if not np.array_equal(cache, np.asarray(proxy.triangles)):
                        raise ValueError("serialized proxy geometry differs")
                    if not np.array_equal(archive[prefix + "cone"], cone):
                        raise ValueError("proxy binding cone differs")
                    if (np.any(np.asarray(proxy.nodes[0][0]) < fine.nodes[node][0])
                            or np.any(np.asarray(proxy.nodes[0][1]) > fine.nodes[node][1])):
                        raise ValueError("proxy root exceeds source-node bound")
                    active[node] = proxy, cone
            if len(active) != row["activePatches"]:
                raise ValueError("active patch count differs")
            with np.load(row["queries"]["path"], allow_pickle=False) as archive:
                saved = dict(archive)
            if not np.array_equal(saved["fineCosts"], fine_costs):
                raise ValueError("fine primitive costs changed")
            for label, mode in (("actual", "actual"), ("oracle", "oracle")):
                query = FusedPatchQuery(fine, active, mode)
                answer, cost, metrics = trace(query, rays, True)
                if not (np.array_equal(answer, expected) and np.array_equal(answer, saved[label + "Answers"])
                        and np.array_equal(cost, saved[label + "Costs"])
                        and np.array_equal(metrics, saved[label + "Metrics"])):
                    raise ValueError("serialized fused queries/counters/metrics differ")
                queries += len(rays)
            if np.any(saved["oracleCosts"] @ weights > fine_costs @ weights):
                raise ValueError("free local oracle is worse than baseline")
            models = []
            for triangle_cost in (1, 2, 4, 8):
                for cone_cost in (.25, .5, 1):
                    w = np.array([1, triangle_cost, cone_cost])
                    models.append(dict(triangleToBox=triangle_cost, coneToBox=cone_cost,
                        actualOverFineWork=float((saved["actualCosts"] @ w).sum() / (fine_costs @ w).sum())))
            # Use paired ratios; ratio-of-medians can be misleading under changing scheduling/load.
            a = np.asarray(row["timingInstrumentedPythonSeconds"]["fine"])
            b = np.asarray(row["timingInstrumentedPythonSeconds"]["actual"])
            paired = (a / b).tolist()
            cases.append(dict(asset=asset["asset"], capacity=row["capacity"], activePatches=len(active),
                freeOracleOverFineWork=float((saved["oracleCosts"] @ weights).sum() / (fine_costs @ weights).sum()),
                actualCostModels=models, pairedFineOverActualWallRatios=paired,
                medianPairedFineOverActualWallRatio=float(np.median(paired)),
                wallTimeSpreadFine=float(a.max() / a.min()), wallTimeSpreadActual=float(b.max() / b.min()),
                runtimePayloadOverFine=1 + row["runtimeArrayPayloadBytes"]["proxiesAndCones"] / row["runtimeArrayPayloadBytes"]["fine"]))
            print(asset["asset"], row["capacity"], "geometry + serialized queries checked", flush=True)
    output = dict(reportSha256=sha(args.report), validatorSha256=sha(__file__),
                  checkedRayQueries=queries, checkedReducedPatchGeometries=geometric_patches, cases=cases,
                  scope="same independent raster targets; no native/GPU or novelty conclusion")
    (args.report.parent / "validation.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("checked", queries, "queries and", geometric_patches, "reduced patch geometries", flush=True)


if __name__ == "__main__":
    main()
