import unittest

import numpy as np

from edit_visibility_support import edit_geometry
import test_edit_visibility_support as geometry_tests
from visibility_query_bvh import BVH, Hybrid, Ray, cone_safe, fit_cone, merge_cones, slab, uncullable


class QueryBVHTest(unittest.TestCase):
    def test_sah_and_packed_roundtrip_against_independent_linear_solver(self):
        rng = np.random.default_rng(7703)
        p = rng.normal(size=(90, 3))
        faces = np.arange(90).reshape(-1, 3)
        tree = BVH.mesh(p, faces)
        restored = BVH.from_packed(tree.packed())
        for _ in range(160):
            origin = rng.normal(size=3) * 2
            direction = rng.normal(size=3)
            direction /= np.linalg.norm(direction)
            ray = Ray(tuple(origin), tuple(direction), 8.)
            expected = False
            for a, b, c in p[faces]:
                matrix = np.column_stack((direction, a - b, a - c))
                if abs(np.linalg.det(matrix)) < 1e-12:
                    continue
                t, u, v = np.linalg.solve(matrix, a - origin)
                expected |= 0 <= t <= 8 and min(u, v) >= -1e-10 and u + v <= 1 + 1e-10
            count_a, count_b = [0, 0, 0], [0, 0, 0]
            self.assertEqual(tree.query(ray, count_a), expected)
            self.assertEqual(restored.query(ray, count_b), expected)
            self.assertEqual(count_a, count_b)

    def test_merged_double_cones_never_exclude_a_covered_child_patch(self):
        rng = np.random.default_rng(9091)
        patches, cones = [], []
        for sign in (1, -1, 1):
            normals = rng.normal(scale=.08, size=(15, 3)) + [0, 0, sign]
            normals /= np.linalg.norm(normals, axis=1)[:, None]
            patches.append(normals)
            cones.append(fit_cone(dict(normals=normals, chainValid=True)))
        parent = merge_cones(merge_cones(cones[0], cones[1]), cones[2])
        safe = 0
        for direction in rng.normal(size=(2000, 3)):
            direction /= np.linalg.norm(direction)
            if cone_safe(parent, direction):
                safe += 1
                for normals in patches:
                    dots = normals @ direction
                    self.assertTrue(np.all(dots > 0) or np.all(dots < 0))
        self.assertGreater(safe, 100)
        self.assertEqual(merge_cones(parent, uncullable()), uncullable())

    def test_segment_guard_catches_clipped_facing_invariant_patch(self):
        p, f = geometry_tests.EditSupportTest.disk()
        target = np.array([0, 0, .5])
        edit = edit_geometry(p, f, 4, 5, target)
        extra = np.array([[10, 0, 1], [11, 0, 1], [10, 1, 1]])
        fine = np.concatenate((p, extra))
        source_faces = np.concatenate((f, [[6, 7, 8]]))
        changed = fine.copy()
        changed[4] = target
        coarse_faces = source_faces.copy()
        coarse_faces[coarse_faces == 5] = 4
        coarse_faces = coarse_faces[np.array([len(set(t)) == 3 for t in coarse_faces])]
        bounds = np.array([[edit["hulls"].min(axis=(0, 1)), edit["hulls"].max(axis=(0, 1))]])
        support = BVH(bounds, cones=[fit_cone(edit)])
        a, b = BVH.mesh(fine, source_faces), BVH.mesh(changed, coarse_faces)
        hybrid = Hybrid(a, b, support)
        ray = Ray((.07, .04, .1), (0, 0, 1), .9)
        self.assertFalse(a.query(ray, [0, 0, 0]))
        self.assertTrue(b.query(ray, [0, 0, 0]))
        self.assertFalse(support.query(ray, [0, 0, 0]))
        self.assertEqual(hybrid.classify(ray, [0, 0, 0])[0], "clipped")
        self.assertFalse(hybrid.query(ray, [0, 0, 0]))

    def test_parallel_slab_and_inside_origin(self):
        self.assertEqual(slab((0, 0, 0), (1, 1, 1), Ray((.5, .5, -1), (0, 0, 1), 3)), (1, 2))
        self.assertIsNone(slab((0, 0, 0), (1, 1, 1), Ray((2, .5, -1), (0, 0, 1), 3)))
        self.assertEqual(slab((0, 0, 0), (1, 1, 1), Ray((.5, .5, .5), (1, 0, 0), 1)), (0, .5))


if __name__ == "__main__":
    unittest.main()
