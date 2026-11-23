"""Metric identity/degradation and geometry-render controls using official backends."""

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"mmmetrics"))
from perceptual import ImageMetrics
from cluster_decoder_quality import render


class QualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = ImageMetrics()

    def test_identity_and_known_corruption(self):
        reference = np.random.default_rng(43).uniform(.1, .9, (64, 64, 3)).astype(np.float32)
        identity = self.metrics(reference, reference)
        self.assertTrue(identity["identical"])
        self.assertEqual(identity["ssim"], 1.)
        self.assertAlmostEqual(identity["flip"], 0., places=6)
        self.assertAlmostEqual(identity["lpips_squeeze"], 0., places=6)
        changed = self.metrics(reference, np.full_like(reference, .5))
        self.assertLess(changed["ssim"], 1)
        self.assertGreater(changed["flip"], 0)
        self.assertGreater(changed["lpips_squeeze"], 0)
        self.assertAlmostEqual(changed["psnr_db"], -10*np.log10(changed["mse"]))

    def test_centroid_retriangulation_keeps_flat_shading_and_coverage(self):
        positions = np.array(((-.5, -.5, 0), (.5, -.5, 0), (0, .5, 0)))
        faces = np.array(((0, 1, 2),))
        refined = np.vstack((positions, positions.mean(axis=0)))
        reference, coverage = render(positions, faces, np.eye(3), 64, 2)
        candidate, after = render(refined, np.array(((0, 1, 3), (1, 2, 3), (2, 0, 3))),
                                  np.eye(3), 64, 2)
        np.testing.assert_array_equal(coverage, after)
        np.testing.assert_array_equal(reference, candidate)

    def test_metric_rejects_invalid_images(self):
        reference = np.zeros((64, 64, 3))
        with self.assertRaises(ValueError):
            self.metrics(reference, np.zeros((32, 32, 3)))
        with self.assertRaises(ValueError):
            self.metrics(reference, np.full_like(reference, np.nan))


if __name__ == "__main__":
    unittest.main()
