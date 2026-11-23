import unittest

import numpy as np

from cluster_decoder_surface_quality import sample_surface, surface_metrics


class SurfaceQualityTests(unittest.TestCase):
    def setUp(self):
        self.positions = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        self.triangles = np.array([[0, 1, 2]])

    def test_sampling_is_reproducible_and_area_bounded(self):
        a = sample_surface(self.positions, self.triangles, 1024, 123)
        b = sample_surface(self.positions, self.triangles, 1024, 123)
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])
        self.assertTrue(np.all(a[0] >= 0))
        self.assertTrue(np.all(a[0][:, :2].sum(axis=1) <= 1 + 1e-12))

    def test_identity_surface_has_zero_distance_and_unit_normal_agreement(self):
        result = surface_metrics((self.positions, self.triangles),
                                 (self.positions, self.triangles), 2000, 5)
        self.assertEqual(result["chamfer_l1_mean"], 0.)
        self.assertEqual(result["chamfer_l2_squared_mean"], 0.)
        self.assertEqual(result["normal_consistency_absdot"], 1.)

    def test_offset_has_positive_distance(self):
        moved = self.positions.copy()
        moved[:, 2] = .1
        result = surface_metrics((self.positions, self.triangles),
                                 (moved, self.triangles), 2000, 7)
        self.assertLess(abs(result["chamfer_l1_mean"] - .1), .001)
        self.assertAlmostEqual(result["normal_consistency_absdot"], 1., places=10)

    def test_degenerate_surface_is_rejected(self):
        degenerate = self.positions.copy()
        degenerate[2] = degenerate[1]
        with self.assertRaises(ValueError):
            sample_surface(degenerate, self.triangles, 1000, 1)


if __name__ == "__main__":
    unittest.main()
