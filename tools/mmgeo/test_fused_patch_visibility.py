import unittest

import numpy as np

from edit_visibility_support import boundary_chain
from fused_patch_visibility import ContainedFixedQEM, FusedPatchQuery, build_patch, cut_nodes, scalar_mesh_cache
from visibility_query_bvh import BVH, Ray, cone_safe, fit_cone


class FusedPatchTest(unittest.TestCase):
    def test_loaded_and_new_mesh_caches_have_identical_scalar_types(self):
        p = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        source = BVH.mesh(p, [[0, 1, 2]])
        loaded = scalar_mesh_cache(BVH.from_packed(source.packed()))
        rebuilt = scalar_mesh_cache(source)
        self.assertTrue(all(type(x) is float for tree in (loaded, rebuilt)
                            for tri in tree.triangles for v in tri for x in v))
        self.assertTrue(all(type(x) is float for tree in (loaded, rebuilt)
                            for node in tree.nodes for bound in node[:2] for x in bound))
        self.assertEqual(loaded.nodes, rebuilt.nodes)
        self.assertEqual(loaded.triangles, rebuilt.triangles)

    def test_contained_disk_simplifies_and_keeps_boundary(self):
        p = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [.5, .5, 0]], float)
        f = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
        solver = ContainedFixedQEM(p, f)
        self.assertFalse(solver.legal(0, 4, np.array([2., 2., 0.])))
        self.assertEqual(solver.advance(0), 2)
        self.assertEqual(boundary_chain(f), boundary_chain(solver.f[solver.alive]))
        tree = BVH.mesh(p, f)
        cut, ranges = cut_nodes(tree, 4)
        self.assertEqual(cut, [0])
        record, patch = build_patch(tree, 0, p, f, ranges)
        self.assertTrue(record["active"])
        self.assertEqual(record["outputTriangles"], 2)
        fused = FusedPatchQuery(tree, {0: patch})
        for x, y in ((.1, .2), (.6, .7), (1.2, .3)):
            ray = Ray((x, y, 2), (0, 0, -1), 4)
            self.assertEqual(fused.query(ray, [0, 0, 0]), tree.query(ray, [0, 0, 0]))

    def test_disabled_fused_traversal_matches_original_counts(self):
        rng = np.random.default_rng(9177)
        p = rng.normal(size=(180, 3))
        f = np.arange(180).reshape(-1, 3)
        tree = BVH.mesh(p, f)
        fused = FusedPatchQuery(tree, {}, "baseline")
        for _ in range(120):
            ray = Ray(tuple(rng.normal(size=3) * 4), tuple(rng.normal(size=3)), 10.)
            a, b = [0, 0, 0], [0, 0, 0]
            self.assertEqual(fused.query(ray, a), tree.query(ray, b))
            self.assertEqual(a, b)

    def test_clipped_local_proxy_falls_back_even_when_facing_matches(self):
        p = np.array([[-1, -1, 1], [1, -1, 0], [1, 1, 0], [-1, 1, 0],
                      [-.3, 0, 0], [.3, 0, 0]], float)
        f = np.array([[0, 1, 5], [0, 5, 4], [1, 2, 5], [2, 3, 4], [2, 4, 5], [3, 0, 4]])
        q = p.copy()
        q[4] = [0, 0, .5]
        g = f.copy()
        g[g == 5] = 4
        g = g[np.array([len(set(t)) == 3 for t in g])]
        xyz = np.concatenate((p[f], q[g]))
        normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        cone = fit_cone(dict(normals=normals, chainValid=True))
        tree, proxy = BVH.mesh(p, f), BVH.mesh(q, g)
        fused = FusedPatchQuery(tree, {0: (proxy, cone)})
        ray = Ray((.07, .04, .2), (0, 0, 1), .8)
        self.assertTrue(cone_safe(cone, ray.direction))
        self.assertFalse(tree.query(ray, [0, 0, 0]))
        self.assertTrue(proxy.query(ray, [0, 0, 0]))
        metrics = [0, 0, 0, 0]
        self.assertFalse(fused.query(ray, [0, 0, 0], metrics))
        self.assertEqual(metrics[3], 1)

    def test_cut_covers_primitives_and_oracle_does_not_pay_unselected_branch(self):
        p = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [.5, .5, 0]], float)
        f = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
        tree = BVH.mesh(p, f)
        _, ranges = cut_nodes(tree, 4)
        _, patch = build_patch(tree, 0, p, f, ranges)
        ray = Ray((.2, .3, 2), (0, 0, -1), 4)
        fine_cost, oracle_cost = [0, 0, 0], [0, 0, 0]
        expected = tree.query(ray, fine_cost)
        oracle = FusedPatchQuery(tree, {0: patch}, "oracle")
        self.assertEqual(oracle.query(ray, oracle_cost), expected)
        self.assertEqual(oracle_cost[2], 0)
        self.assertLessEqual(oracle_cost[0] + 2 * oracle_cost[1], fine_cost[0] + 2 * fine_cost[1])


if __name__ == "__main__":
    unittest.main()
