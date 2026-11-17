"""Shared scalar reference kernels and ordinary binned-SAH BVHs.

Spatial/normal cone hierarchies are prior art. This Python reference measures
the full proposed query path, not hardware ray-tracing or a new data structure.
"""
from dataclasses import dataclass
import math

import numpy as np


@dataclass
class Ray:
    origin: tuple
    direction: tuple
    maximum: float


def slab(lower, upper, ray, minimum=0.0, maximum=None):
    near, far = minimum, ray.maximum if maximum is None else maximum
    for axis in range(3):
        d = ray.direction[axis]
        if abs(d) < 1e-15:
            if ray.origin[axis] < lower[axis] or ray.origin[axis] > upper[axis]:
                return None
            continue
        a = (lower[axis] - ray.origin[axis]) / d
        b = (upper[axis] - ray.origin[axis]) / d
        if a > b:
            a, b = b, a
        near, far = max(near, a), min(far, b)
        if far < near:
            return None
    return near, far


def triangle_hit(triangle, ray):
    """Two-sided Moller--Trumbore; identical routine for fine and coarse meshes."""
    a, e1, e2 = triangle
    dx, dy, dz = ray.direction
    px, py, pz = dy * e2[2] - dz * e2[1], dz * e2[0] - dx * e2[2], dx * e2[1] - dy * e2[0]
    determinant = e1[0] * px + e1[1] * py + e1[2] * pz
    if abs(determinant) <= 1e-14:
        return False
    tx, ty, tz = ray.origin[0] - a[0], ray.origin[1] - a[1], ray.origin[2] - a[2]
    inverse = 1 / determinant
    u = (tx * px + ty * py + tz * pz) * inverse
    if u < -1e-10 or u > 1 + 1e-10:
        return False
    qx, qy, qz = ty * e1[2] - tz * e1[1], tz * e1[0] - tx * e1[2], tx * e1[1] - ty * e1[0]
    v = (dx * qx + dy * qy + dz * qz) * inverse
    if v < -1e-10 or u + v > 1 + 1e-10:
        return False
    distance = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * inverse
    return 0 <= distance <= ray.maximum


def uncullable():
    return (0.0, 0.0, 0.0, 1.0)


def fit_cone(edit):
    if not edit["chainValid"] or not len(edit["normals"]):
        return uncullable()
    normals = edit["normals"]
    axis = normals.sum(0)
    length = np.linalg.norm(axis)
    if length < 1e-12:
        return uncullable()
    axis /= length
    cosine = float(np.min(normals @ axis))
    if cosine <= 0:
        return uncullable()
    sine = math.sqrt(max(0.0, 1 - min(1.0, cosine) ** 2))
    return (*map(float, axis), min(1.0, sine + 1e-9))


def cone_safe(cone, direction):
    return abs(cone[0] * direction[0] + cone[1] * direction[1] + cone[2] * direction[2]) > cone[3] + 1e-9


def merge_cones(first, second):
    """Contain each child cone up to a consistent sign flip of that subtree."""
    if first[3] >= 1 or second[3] >= 1:
        return uncullable()
    a, b = np.asarray(first[:3]), np.asarray(second[:3])
    if np.dot(a, b) < 0:
        b = -b  # Flipping a whole patch preserves its two-sided invariant test.
    axis = a + b
    axis /= np.linalg.norm(axis)
    angle = max(math.acos(float(np.clip(np.dot(axis, a), -1, 1))) + math.asin(first[3]),
                math.acos(float(np.clip(np.dot(axis, b), -1, 1))) + math.asin(second[3]))
    if angle >= math.pi / 2:
        return uncullable()
    return (*map(float, axis), min(1.0, math.sin(angle) + 1e-9))


def surface_area(lower, upper):
    x, y, z = np.maximum(0, upper - lower)
    return 2 * (x * y + y * z + z * x)


class BVH:
    def __init__(self, bounds, cones=None, triangles=None, leaf_size=4, bins=12):
        self.bounds = np.asarray(bounds, float).reshape(-1, 2, 3)
        if not len(self.bounds) or not np.isfinite(self.bounds).all() or np.any(self.bounds[:, 0] > self.bounds[:, 1]):
            raise ValueError("nonempty finite ordered bounds required")
        if (cones is None) == (triangles is None):
            raise ValueError("exactly one primitive type required")
        self.cones = None if cones is None else [tuple(map(float, c)) for c in cones]
        self.triangles = None if triangles is None else [tuple(tuple(map(float, v)) for v in t) for t in triangles]
        if len(self.cones if cones is not None else self.triangles) != len(self.bounds):
            raise ValueError("primitive count differs from bounds")
        self.nodes, self.order = [], []
        centers = self.bounds.mean(1)

        def build(indices):
            lower, upper = self.bounds[indices, 0].min(0), self.bounds[indices, 1].max(0)
            index = len(self.nodes)
            self.nodes.append(None)
            if len(indices) <= leaf_size:
                begin = len(self.order)
                self.order.extend(map(int, indices))
                cone = uncullable()
                if self.cones is not None:
                    cone = self.cones[int(indices[0])]
                    for primitive in indices[1:]:
                        cone = merge_cones(cone, self.cones[int(primitive)])
                self.nodes[index] = (tuple(lower), tuple(upper), -1, -1, begin, len(indices), cone)
                return index
            best = None
            for axis in range(3):
                lo, hi = centers[indices, axis].min(), centers[indices, axis].max()
                if hi - lo <= 1e-15:
                    continue
                bucket = np.minimum(bins - 1, ((centers[indices, axis] - lo) / (hi - lo) * bins).astype(int))
                counts = np.bincount(bucket, minlength=bins)
                blo = np.full((bins, 3), np.inf)
                bhi = np.full((bins, 3), -np.inf)
                np.minimum.at(blo, bucket, self.bounds[indices, 0])
                np.maximum.at(bhi, bucket, self.bounds[indices, 1])
                left_count = counts.cumsum()
                right_count = counts[::-1].cumsum()[::-1]
                left_low, left_high = np.minimum.accumulate(blo), np.maximum.accumulate(bhi)
                right_low = np.minimum.accumulate(blo[::-1])[::-1]
                right_high = np.maximum.accumulate(bhi[::-1])[::-1]
                for split in range(bins - 1):
                    if left_count[split] == 0 or right_count[split + 1] == 0:
                        continue
                    cost = (surface_area(left_low[split], left_high[split]) * left_count[split]
                            + surface_area(right_low[split + 1], right_high[split + 1]) * right_count[split + 1])
                    if best is None or cost < best[0]:
                        best = cost, bucket <= split
            if best is None:
                axis = int(np.argmax(upper - lower))
                ordered = indices[np.argsort(centers[indices, axis], kind="stable")]
                left_ids, right_ids = np.array_split(ordered, 2)
            else:
                left_ids, right_ids = indices[best[1]], indices[~best[1]]
            left, right = build(left_ids), build(right_ids)
            cone = (merge_cones(self.nodes[left][6], self.nodes[right][6])
                    if self.cones is not None else uncullable())
            self.nodes[index] = (tuple(lower), tuple(upper), left, right, 0, 0, cone)
            return index

        build(np.arange(len(self.bounds)))

    @classmethod
    def mesh(cls, positions, faces):
        xyz = np.asarray(positions)[faces]
        triangles = np.stack((xyz[:, 0], xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1)
        # Conservative padding is a prototype tolerance, not a rounding proof.
        bounds = np.stack((xyz.min(1) - 1e-10, xyz.max(1) + 1e-10), axis=1)
        return cls(bounds, triangles=triangles)

    def packed(self):
        data = dict(bounds=self.bounds, nodeBounds=np.asarray([(n[0], n[1]) for n in self.nodes]),
                    links=np.asarray([n[2:6] for n in self.nodes], dtype=np.int32),
                    order=np.asarray(self.order, dtype=np.int32))
        if self.cones is not None:
            data.update(cones=np.asarray(self.cones), nodeCones=np.asarray([n[6] for n in self.nodes]))
        else:
            data["triangles"] = np.asarray(self.triangles)
        return data

    @classmethod
    def from_packed(cls, data):
        result = object.__new__(cls)
        result.bounds = np.asarray(data["bounds"])
        result.order = list(map(int, data["order"]))
        result.cones = [tuple(c) for c in data["cones"]] if "cones" in data else None
        result.triangles = ([tuple(tuple(v) for v in t) for t in data["triangles"]]
                            if "triangles" in data else None)
        result.nodes = []
        for i, (bound, link) in enumerate(zip(data["nodeBounds"], data["links"])):
            cone = tuple(data["nodeCones"][i]) if result.cones is not None else uncullable()
            result.nodes.append((tuple(bound[0]), tuple(bound[1]), *map(int, link), cone))
        if len(result.order) != len(result.bounds) or sorted(result.order) != list(range(len(result.bounds))):
            raise ValueError("invalid primitive order")
        for i, node in enumerate(result.nodes):
            left, right, begin, count = node[2:6]
            if count:
                if left != -1 or right != -1 or begin < 0 or begin + count > len(result.order):
                    raise ValueError("invalid leaf")
            elif not (i < left < len(result.nodes) and i < right < len(result.nodes)):
                raise ValueError("invalid preorder links")
        return result

    def query(self, ray, counters, known_root=None):
        # Counters: AABB tests, triangle tests, cone tests. No relative cost assumed.
        if known_root is None:
            counters[0] += 1
            interval = slab(self.nodes[0][0], self.nodes[0][1], ray)
            if interval is None:
                return False
        stack = [0]
        while stack:
            index = stack.pop()
            lower, upper, left, right, begin, count, cone = self.nodes[index]
            if self.cones is not None:
                counters[2] += 1
                if cone_safe(cone, ray.direction):
                    continue
            if count:
                for primitive in self.order[begin:begin + count]:
                    if self.cones is None:
                        counters[1] += 1
                        if triangle_hit(self.triangles[primitive], ray):
                            return True
                    else:
                        counters[0] += 1
                        bound = self.bounds[primitive]
                        if slab(bound[0], bound[1], ray) is None:
                            continue
                        counters[2] += 1
                        if not cone_safe(self.cones[primitive], ray.direction):
                            return True
                continue
            children = []
            for child in (left, right):
                counters[0] += 1
                interval = slab(self.nodes[child][0], self.nodes[child][1], ray)
                if interval is not None:
                    children.append((interval[0], child))
            children.sort(reverse=True)
            stack.extend(child for _, child in children)
        return False


class Hybrid:
    def __init__(self, fine, coarse, support):
        self.fine, self.coarse, self.support = fine, coarse, support
        self.lower = np.minimum.reduce([b.nodes[0][0] for b in (fine, coarse, support)])
        self.upper = np.maximum.reduce([b.nodes[0][1] for b in (fine, coarse, support)])

    def classify(self, ray, counters):
        counters[0] += 1
        root = slab(self.fine.nodes[0][0], self.fine.nodes[0][1], ray)
        if root is None:
            return "miss", None
        counters[0] += 1
        full = slab(self.lower, self.upper, ray, -math.inf, math.inf)
        if full is None:
            raise ValueError("union box missed a fine-box ray")
        # Require the segment to span the whole box containing all intermediate edits.
        if full[0] < 0 or full[1] > ray.maximum:
            return "clipped", root
        if self.support.query(ray, counters):
            return "fine", root
        return "coarse", None

    def query(self, ray, counters):
        decision, root = self.classify(ray, counters)
        if decision == "miss":
            return False
        if decision in ("fine", "clipped"):
            return self.fine.query(ray, counters, known_root=root)
        return self.coarse.query(ray, counters)
