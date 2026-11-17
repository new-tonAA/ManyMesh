"""Adversarial local geometry checks for the edit-support prototype."""
import unittest

import numpy as np

from edit_visibility_support import box_mask, direction_invariant, edit_geometry, oriented_patch


class EditSupportTest(unittest.TestCase):
    @staticmethod
    def disk():
        # Two interior vertices; boundary square is unchanged by collapsing 4--5.
        p = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0],
                      [-.3, 0, 0], [.3, 0, 0]], float)
        f = np.array([[0, 1, 5], [0, 5, 4], [1, 2, 5], [2, 3, 4], [2, 4, 5], [3, 0, 4]])
        return p, f

    def test_internal_disk_same_boundary_and_facing(self):
        p, f = self.disk()
        edit = edit_geometry(p, f, 4, 5, np.array([0, 0, .05]))
        self.assertTrue(edit["chainValid"])
        self.assertTrue(direction_invariant(edit, [0, 0, 1]))
        self.assertTrue(direction_invariant(edit, [0, 0, -1]))
        self.assertFalse(direction_invariant(edit, [1, 0, 0]))
        # Every old/new triangle is contained in its four-point simplex.
        np.testing.assert_array_equal(edit["hulls"][:, :3], p[f])

    def test_reversed_input_winding_is_repaired_locally(self):
        p, f = self.disk()
        f[1] = f[1, [0, 2, 1]]
        edit = edit_geometry(p, f, 4, 5, np.array([0, 0, .05]))
        self.assertTrue(edit["chainValid"])
        self.assertTrue(direction_invariant(edit, [0, 0, 1]))

    def test_direction_certificate_against_independent_projected_union(self):
        p, f = self.disk()
        p[4, 2], p[5, 2] = .12, -.17
        target = np.array([.07, -.11, .2])
        edit = edit_geometry(p, f, 4, 5, target)
        changed = p.copy()
        changed[4] = target
        new = f.copy()
        new[new == 5] = 4
        new = new[np.array([len(set(tri)) == 3 for tri in new])]
        rng = np.random.default_rng(7031)
        pts = rng.uniform(-1.6, 1.6, (4096, 2))
        def union(projected, triangles):
            covered = np.zeros(len(pts), bool)
            for tri in projected[triangles]:
                signs = []
                for a, b in zip(tri, np.roll(tri, -1, axis=0)):
                    delta = b - a
                    signs.append(delta[0] * (pts[:, 1] - a[1]) - delta[1] * (pts[:, 0] - a[0]))
                signs = np.array(signs)
                covered |= np.all(signs >= 0, axis=0) | np.all(signs <= 0, axis=0)
            return covered
        certified = 0
        for direction in rng.normal(size=(60, 3)):
            direction /= np.linalg.norm(direction)
            if not direction_invariant(edit, direction):
                continue
            right = np.cross(direction, [0, 1, 0])
            right /= np.linalg.norm(right)
            basis = np.stack((right, np.cross(right, direction)))
            np.testing.assert_array_equal(union(p @ basis.T, f), union(changed @ basis.T, new))
            certified += 1
        self.assertGreater(certified, 10)

    def test_moving_boundary_and_folded_projection_refused(self):
        p, f = self.disk()
        boundary = edit_geometry(p, f[:3], 4, 5, np.array([0, 0, .05]))
        self.assertFalse(boundary["chainValid"])
        self.assertFalse(direction_invariant(boundary, [0, 0, 1]))
        folded = edit_geometry(p, f, 4, 5, np.array([3, 0, 0]))
        self.assertTrue(folded["chainValid"])
        self.assertFalse(direction_invariant(folded, [0, 0, 1]))

    def test_finite_segment_is_explicit_counterexample_to_full_line_extension(self):
        p, f = self.disk()
        target = np.array([0, 0, .5])
        edit = edit_geometry(p, f, 4, 5, target)
        self.assertTrue(direction_invariant(edit, [0, 0, 1]))
        changed = p.copy()
        changed[4] = target
        new = f.copy()
        new[new == 5] = 4
        new = new[np.array([len(set(tri)) == 3 for tri in new])]
        point = np.array([.07, .04])
        def segment_hit(positions, faces):
            for xyz in positions[faces]:
                uv = np.linalg.solve((xyz[1:, :2] - xyz[0, :2]).T, point - xyz[0, :2])
                if min(uv) >= 0 and uv.sum() <= 1:
                    z = xyz[0, 2] + uv @ (xyz[1:, 2] - xyz[0, 2])
                    if .1 < z < 1:
                        return True
            return False
        self.assertFalse(segment_hit(p, f))
        self.assertTrue(segment_hit(changed, new))

    def test_nonmanifold_patch_refused(self):
        self.assertIsNone(oriented_patch([[0, 1, 2], [1, 0, 3], [0, 1, 4]]))

    def test_box_union_matches_independent_direct_sample_test(self):
        low = np.array([[-2, -3], [.25, .75], [1.2, 0], [5, 5]])
        high = np.array([[.5, .5], [1.75, 2.25], [2.7, 2.8], [6, 6]])
        actual = box_mask(low, high, size=3, scale=2)
        y, x = np.mgrid[:6, :6]
        pts = np.stack(((x + .5) / 2, (y + .5) / 2), axis=-1)
        expected = np.any(np.all((pts[:, :, None] >= low) & (pts[:, :, None] <= high), axis=-1), axis=-1)
        np.testing.assert_array_equal(actual, expected)
        self.assertFalse(box_mask([], [], 3, 2).any())


if __name__ == "__main__":
    unittest.main()
