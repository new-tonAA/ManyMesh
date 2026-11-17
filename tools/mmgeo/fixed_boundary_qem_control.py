"""Classical fixed-target control extending the archived geometry-only QEM reference."""
import heapq

import numpy as np

from progressive_geometry_baseline import ProgressiveQEM
from probe_partition_qem_exhaustion import boundary


class FixedBoundaryQEM(ProgressiveQEM):
    def __init__(self, positions, triangles):
        self.fixed_boundary = boundary(triangles)
        self.boundary_targets = {v for edge in self.fixed_boundary for v in edge}
        super().__init__(positions, triangles)

    def push(self, u, v):
        u, v = sorted((int(u), int(v)))
        if u not in self.locked and v not in self.locked:
            return super().push(u, v)
        if u in self.locked and v in self.locked:
            return
        if v in self.locked:
            u, v = v, u
        if u not in self.boundary_targets or not self.inc[u] or not self.inc[v]:
            return
        target = self.p[u].copy()
        h = np.r_[target, 1.]
        cost = max(0., float(h @ (self.q[u] + self.q[v]) @ h))
        heapq.heappush(self.heap, (cost, u, v, int(self.versions[u]), int(self.versions[v]),
                                   0, tuple(target)))

    def legal(self, u, v, target):
        if v in self.locked:
            return False
        if u in self.locked:
            if u not in self.boundary_targets or not np.array_equal(target, self.p[u]):
                return False
        if not super().legal(u, v, target):
            return False
        if u in self.locked:
            candidate = self.f[self.alive].copy()
            candidate[candidate == v] = u
            candidate = candidate[(candidate[:, 0] != candidate[:, 1]) &
                                  (candidate[:, 1] != candidate[:, 2]) &
                                  (candidate[:, 0] != candidate[:, 2])]
            if boundary(candidate) != self.fixed_boundary:
                return False
        return True
