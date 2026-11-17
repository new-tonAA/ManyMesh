"""Paid two-sided outcome-specific certificates on frozen local patches."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster
from fused_patch_visibility import cut_nodes, scalar_mesh_cache
from visibility_query_bvh import BVH, Ray, cone_safe, fit_cone, slab, triangle_hit


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cone_for(positions, faces):
    xyz = positions[faces]
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths < 1e-15):
        raise ValueError("degenerate face in frozen patch")
    normals /= lengths[:, None]
    return fit_cone(dict(normals=normals, chainValid=True))


class PaidAsymmetricQuery:
    # Counters: AABB, triangle, cone. Metrics: patch, hit cert, miss cert,
    # proxy+fine, proxy traversals, clipped bypasses.
    def __init__(self, tree, patches):
        self.tree, self.patches = tree, patches

    def interval(self, index, ray, costs):
        costs[0] += 1
        node = self.tree.nodes[index]
        full = slab(node[0], node[1], ray, -np.inf, np.inf)
        if full is None or full[1] < 0 or full[0] > ray.maximum:
            return None
        return full

    def query(self, ray, costs, metrics):
        full = self.interval(0, ray, costs)
        return False if full is None else self.walk(0, full, ray, costs, metrics)

    def fine_subtree(self, index, full, ray, costs):
        node = self.tree.nodes[index]
        if node[5]:
            for primitive in self.tree.order[node[4]:node[4] + node[5]]:
                costs[1] += 1
                if triangle_hit(self.tree.triangles[primitive], ray):
                    return True
            return False
        children = []
        for child in (node[2], node[3]):
            interval = self.interval(child, ray, costs)
            if interval is not None:
                children.append((max(0., interval[0]), child, interval))
        children.sort()
        for _, child, interval in children:
            if self.fine_subtree(child, interval, ray, costs):
                return True
        return False

    def walk(self, index, full, ray, costs, metrics):
        patch = self.patches.get(index)
        if patch is not None:
            metrics[0] += 1
            proxy, source_cone, proxy_cone = patch
            if full[0] >= 0 and full[1] <= ray.maximum:
                # The already intersected source node contains the proxy root.
                proxy_hit = proxy.query(ray, costs, known_root=full)
                metrics[4] += 1
                # A proxy hit is sufficient only when proxy orientation is one-signed.
                if proxy_hit:
                    costs[2] += 1
                    if cone_safe(proxy_cone, ray.direction):
                        metrics[1] += 1
                        return True
                    metrics[3] += 1
                    return self.fine_subtree(index, full, ray, costs)
                # A proxy miss is sufficient only when source orientation is one-signed.
                costs[2] += 1
                if cone_safe(source_cone, ray.direction):
                    metrics[2] += 1
                    return False
                metrics[3] += 1
                return self.fine_subtree(index, full, ray, costs)
            metrics[5] += 1
        node = self.tree.nodes[index]
        if node[5]:
            for primitive in self.tree.order[node[4]:node[4] + node[5]]:
                costs[1] += 1
                if triangle_hit(self.tree.triangles[primitive], ray):
                    return True
            return False
        children = []
        for child in (node[2], node[3]):
            interval = self.interval(child, ray, costs)
            if interval is not None:
                children.append((max(0., interval[0]), child, interval))
        children.sort()
        for _, child, interval in children:
            if self.walk(child, interval, ray, costs, metrics):
                return True
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    outcomes = []
    total_queries = 0
    weights = np.array([1., 2., .5])
    for asset in report["assets"]:
        for binding in (asset["source"], asset["rays"], asset["fineTree"]):
            if sha(binding["path"]) != binding["sha256"]:
                raise ValueError("input hash mismatch: " + binding["path"])
        with np.load(asset["fineTree"]["path"], allow_pickle=False) as z:
            tree = scalar_mesh_cache(BVH.from_packed(dict(z)))
        with np.load(asset["rays"]["path"], allow_pickle=False) as z:
            rays_data = dict(z)
        rays = [Ray(tuple(o), tuple(d), float(t)) for o, d, t in zip(
            rays_data["origins"], rays_data["directions"], rays_data["maximum"])]
        expected = rays_data["fineExpected"]
        world, faces, _ = raster.load_capture(Path(asset["source"]["path"]))
        center = (world.min(0) + world.max(0)) * .5
        positions = (world - center) / np.linalg.norm(world - center, axis=1).max()
        for row in asset["cuts"]:
            for binding in (row["patches"], row["proxies"], row["queries"]):
                if sha(binding["path"]) != binding["sha256"]:
                    raise ValueError("cut input hash mismatch: " + binding["path"])
            pdata = json.loads(Path(row["patches"]["path"]).read_text(encoding="utf-8"))
            cut, _ = cut_nodes(tree, row["capacity"])
            if cut != pdata["cut"]:
                raise ValueError("frozen cut differs")
            patches = {}
            with np.load(row["proxies"]["path"], allow_pickle=False) as archive:
                for rec, node in zip(pdata["patches"], cut):
                    if "outputFaces" not in rec:
                        continue
                    src_vertices = np.asarray(rec["sourceVertices"], int)
                    src_pos = positions[src_vertices]
                    old_cone = cone_for(src_pos, np.asarray(rec["sourceOrientedFaces"], int))
                    proxy_pos = np.asarray(rec["outputPositions"], float)
                    proxy_faces = np.asarray(rec["outputFaces"], int)
                    new_cone = cone_for(proxy_pos, proxy_faces)
                    # Recover active serialized proxies; construct formerly inactive ones
                    # so the asymmetric certificate is not biased by the old combined cone.
                    prefix = f"n{node}_"
                    if prefix + "nodeBounds" in archive.files:
                        packed = {k[len(prefix):]: archive[k] for k in archive.files
                                  if k.startswith(prefix) and k != prefix + "cone"}
                        proxy = scalar_mesh_cache(BVH.from_packed(packed))
                    else:
                        proxy = scalar_mesh_cache(BVH.mesh(proxy_pos, proxy_faces))
                    patches[node] = proxy, old_cone, new_cone
            query = PaidAsymmetricQuery(tree, patches)
            got, counters, metrics = [], [], []
            for ray in rays:
                c, m = [0, 0, 0], [0, 0, 0, 0, 0, 0]
                got.append(query.query(ray, c, m))
                counters.append(c)
                metrics.append(m)
            got, counters, metrics = np.asarray(got, bool), np.asarray(counters), np.asarray(metrics)
            if not np.array_equal(got, expected):
                raise ValueError(f"query mismatch {asset['asset']} {row['capacity']}")
            with np.load(row["queries"]["path"], allow_pickle=False) as archive:
                fine_costs = archive["fineCosts"]
            if np.any(counters @ weights > fine_costs @ weights):
                # The runtime can fall back after paying for a proxy; report rather than
                # conceal this if some individual queries exceed fine cost.
                pass
            total_queries += len(rays)
            base = float((fine_costs @ weights).sum())
            ours = float((counters @ weights).sum())
            outcomes.append(dict(asset=asset["asset"], capacity=row["capacity"],
                reducedPatches=len(patches), totalCostRatio=ours / base,
                weightedSaving=1 - ours / base, costSums=counters.sum(0).tolist(),
                fineCostSums=fine_costs.sum(0).tolist(), metricSums=metrics.sum(0).tolist(),
                perRayCostWorseThanFine=int(np.sum(counters @ weights > fine_costs @ weights))))
            print(asset["asset"], row["capacity"], "cost ratio", ours / base,
                  "metrics", metrics.sum(0).tolist(), flush=True)
    result = dict(schema=1, evaluatorSha256=sha(__file__), reportSha256=sha(args.report),
        weightModel={"aabb": 1, "triangle": 2, "cone": .5},
        checkedQueries=total_queries, cases=outcomes,
        scope="paid asymmetric full-span binary any-hit certificates on frozen local patches",
        caveats=["synthetic orthographic rays and three reused assets; no held-out scene",
                 "hypothetical operation weights, not calibrated hardware costs",
                 "same-boundary winding implications are prior art; this is only a workload screen",
                 "not a depth, shading, or general mesh simplification guarantee"])
    out = args.report.parent / "asymmetric-paid-queries.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
