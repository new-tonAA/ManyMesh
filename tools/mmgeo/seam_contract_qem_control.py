"""Geometry-only reference with the existing shared-position/no-new-locked-edge contract."""
import numpy as np

from fixed_boundary_qem_control import FixedBoundaryQEM


def edges(triangles):
    return {tuple(sorted((int(t[i]), int(t[(i + 1) % 3])))) for t in triangles for i in range(3)}


class SeamContractQEM(FixedBoundaryQEM):
    def __init__(self, positions, triangles, seam_locked):
        self.seam_locked = set(map(int, seam_locked))
        if any(v < 0 or v >= len(positions) for v in self.seam_locked):
            raise ValueError("invalid seam mask index")
        self.seam_points = {tuple(positions[v]) for v in self.seam_locked}
        self.source_locked_edges = {
            tuple(sorted((tuple(positions[a]), tuple(positions[b])))) for a, b in edges(triangles)
            if tuple(positions[a]) in self.seam_points and tuple(positions[b]) in self.seam_points}
        super().__init__(positions, triangles)

    def push(self, u, v):
        # Base construction populates locked vertices before it dispatches push().
        # Apply the caller's seam mask before any initial candidate is queued.
        self.locked.update(self.seam_locked)
        self.boundary_targets.update(self.seam_locked)
        return super().push(u, v)

    def legal(self, u, v, target):
        if not super().legal(u, v, target):
            return False
        affected = self.inc[u] | self.inc[v]
        for face in affected:
            triangle = self.f[face].copy()
            triangle[triangle == v] = u
            if len(set(triangle)) != 3:
                continue
            for a, b in edges([triangle]):
                pa = tuple(target if a == u else self.p[a])
                pb = tuple(target if b == u else self.p[b])
                if pa in self.seam_points and pb in self.seam_points and tuple(sorted((pa, pb))) not in self.source_locked_edges:
                    return False
        return True

    def check_seams(self):
        output = self.f[self.alive]
        referenced = {tuple(self.p[int(v)]) for v in output.reshape(-1)}
        return (self.seam_points <= referenced and
                all(tuple(sorted((tuple(self.p[a]), tuple(self.p[b])))) in self.source_locked_edges
                    for a, b in edges(output) if tuple(self.p[a]) in self.seam_points and tuple(self.p[b]) in self.seam_points))
