"""Reference local coverage-preserving proxies inside an existing fine BVH.

No separate support hierarchy. Fixed boundaries, contained QEM placements, and
one same-facing cone certify a local replacement for full-span any-hit queries.
These ingredients are prior art; this is a cost experiment, not a novelty claim.
"""
import math

import numpy as np

from edit_visibility_support import boundary_chain, oriented_patch
from fixed_boundary_qem_control import FixedBoundaryQEM
from visibility_query_bvh import BVH, cone_safe, fit_cone, slab, triangle_hit


def scalar_mesh_cache(tree):
    """Use the same Python scalar types for rebuilt and deserialized mesh trees."""
    if tree.triangles is None:
        raise ValueError("mesh tree required")
    tree.triangles = [tuple(tuple(map(float, vector)) for vector in tri) for tri in tree.triangles]
    tree.nodes = [(tuple(map(float, n[0])), tuple(map(float, n[1])), *n[2:6], tuple(map(float, n[6])))
                  for n in tree.nodes]
    return tree


class ContainedFixedQEM(FixedBoundaryQEM):
    def __init__(self, positions, triangles):
        self.original_lower = np.min(positions, axis=0)
        self.original_upper = np.max(positions, axis=0)
        super().__init__(positions, triangles)

    def legal(self, keep, remove, target):
        if np.any(target < self.original_lower) or np.any(target > self.original_upper):
            return False
        return super().legal(keep, remove, target)


def subtree_ranges(tree):
    result = [None] * len(tree.nodes)
    for index in reversed(range(len(tree.nodes))):
        node = tree.nodes[index]
        if node[5]:
            result[index] = node[4], node[5]
        else:
            a, b = result[node[2]], result[node[3]]
            if a[0] + a[1] != b[0]:
                raise ValueError("subtree leaves are not contiguous")
            result[index] = a[0], a[1] + b[1]
    return result


def cut_nodes(tree, capacity):
    if capacity < 4:
        raise ValueError("capacity must be at least the original leaf size")
    ranges = subtree_ranges(tree)
    stack, cut = [0], []
    while stack:
        index = stack.pop()
        if ranges[index][1] <= capacity:
            cut.append(index)
        else:
            stack.extend((tree.nodes[index][3], tree.nodes[index][2]))
    all_faces = [face for index in cut for face in tree.order[ranges[index][0]:sum(ranges[index])]]
    if sorted(all_faces) != list(range(len(tree.bounds))):
        raise ValueError("cut does not cover each source face once")
    return cut, ranges


def build_patch(tree, node_index, positions, faces, ranges):
    begin, count = ranges[node_index]
    source_ids = tree.order[begin:begin + count]
    vertices = np.unique(faces[source_ids])
    local = np.searchsorted(vertices, faces[source_ids])
    old = oriented_patch(local)
    result = dict(node=node_index, sourceFaces=list(map(int, source_ids)),
                  sourceVertices=vertices.tolist(), sourceTriangles=count)
    if old is None:
        return dict(result, status="unorientable_or_nonmanifold", active=False), None
    source_positions = positions[vertices]
    solver = ContainedFixedQEM(source_positions, old)
    solver.advance(0)
    output = solver.f[solver.alive].copy()
    if len(output) >= count:
        return dict(result, status="no_reduction", outputTriangles=len(output), active=False), None
    before, after = boundary_chain(old), boundary_chain(output)
    pinned = sorted({v for edge in before for v in edge})
    if before != after or not np.array_equal(solver.p[pinned], source_positions[pinned]):
        raise ValueError("patch changed its fixed oriented boundary")
    if np.any(solver.p < source_positions.min(0)) or np.any(solver.p > source_positions.max(0)):
        raise ValueError("patch escaped its original box")
    xyz = np.concatenate((source_positions[old], solver.p[output]))
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths < 1e-15):
        raise ValueError("degenerate source or final face")
    normals /= lengths[:, None]
    cone = fit_cone(dict(normals=normals, chainValid=True))
    active = cone[3] < 1
    result.update(status="active" if active else "uncullable_cone", active=active,
                  outputTriangles=len(output), actions=len(solver.actions),
                  sourceOrientedFaces=old.tolist(), outputPositions=solver.p.tolist(),
                  outputFaces=output.tolist(), cone=list(cone), boundaryPinnedVertices=pinned)
    if not active:
        return result, None
    proxy = scalar_mesh_cache(BVH.mesh(solver.p, output))
    source_box = tree.nodes[node_index]
    if np.any(np.asarray(proxy.nodes[0][0]) < source_box[0]) or np.any(np.asarray(proxy.nodes[0][1]) > source_box[1]):
        raise ValueError("proxy root exceeds the original source-node box")
    return result, (proxy, cone)


class FusedPatchQuery:
    """Finite ray queries with normalized directions, as checked by the harness."""
    def __init__(self, tree, patches, mode="actual"):
        if mode not in ("actual", "oracle", "baseline"):
            raise ValueError("unknown query mode")
        self.tree, self.patches, self.mode = tree, patches, mode

    @staticmethod
    def interval(tree, index, ray, costs):
        costs[0] += 1
        node = tree.nodes[index]
        full = slab(node[0], node[1], ray, -math.inf, math.inf)
        if full is None or full[1] < 0 or full[0] > ray.maximum:
            return None
        return full

    def query(self, ray, costs, metrics=None):
        full = self.interval(self.tree, 0, ray, costs)
        if full is None:
            return False
        return self._walk(0, full, ray, costs, self.mode, metrics)

    def _walk(self, index, full, ray, costs, mode, metrics):
        tree = self.tree
        patch = self.patches.get(index) if mode != "baseline" else None
        if patch is not None:
            if metrics is not None:
                metrics[0] += 1  # Attached patch visited.
            if full[0] >= 0 and full[1] <= ray.maximum:
                proxy, cone = patch
                if mode != "oracle":
                    costs[2] += 1
                if cone_safe(cone, ray.direction):
                    if metrics is not None:
                        metrics[1] += 1  # Certificate accepted.
                    if mode == "oracle":
                        original_cost, proxy_cost = [0, 0, 0], [0, 0, 0]
                        original_answer = self._walk(index, full, ray, original_cost, "baseline", None)
                        proxy_answer = proxy.query(ray, proxy_cost, known_root=full)
                        if original_answer != proxy_answer:
                            raise ValueError("certified local proxy differs from original subtree")
                        use_proxy = proxy_cost[0] + 2 * proxy_cost[1] < original_cost[0] + 2 * original_cost[1]
                        chosen = proxy_cost if use_proxy else original_cost
                        for k in range(3):
                            costs[k] += chosen[k]
                        if metrics is not None:
                            metrics[2] += int(use_proxy)
                        return proxy_answer if use_proxy else original_answer
                    if metrics is not None:
                        metrics[2] += 1
                    # The already tested source node encloses the proxy root.
                    return proxy.query(ray, costs, known_root=full)
            elif metrics is not None:
                metrics[3] += 1  # Clipped segment: do not use the coverage certificate.
        node = tree.nodes[index]
        if node[5]:
            for primitive in tree.order[node[4]:node[4] + node[5]]:
                costs[1] += 1
                if triangle_hit(tree.triangles[primitive], ray):
                    return True
            return False
        children = []
        for child in (node[2], node[3]):
            interval = self.interval(tree, child, ray, costs)
            if interval is not None:
                children.append((max(0., interval[0]), child, interval))
        children.sort()
        for _, child, interval in children:
            if self._walk(child, interval, ray, costs, mode, metrics):
                return True
        return False
