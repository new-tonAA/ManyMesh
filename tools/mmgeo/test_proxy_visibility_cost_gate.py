"""Independent finite-enumeration and optimization checks for the proxy gate."""
from fractions import Fraction as F
import math
import unittest

import numpy as np

from proxy_visibility_cost_gate import coverage_image_gate, moments, optimum


class CostGateTest(unittest.TestCase):
    def test_image_variance_excludes_between_pixel_variance(self):
        # Three pixels: empty, fully occupied, and half occupied. A wrong proxy
        # changes a constant pixel, so it adds noise where direct fine has none.
        fine = np.array([[0, 0, 1, 1, 0, 1], [0, 0, 1, 1, 0, 1]])
        coarse = fine.copy()
        coarse[0, 0] = 1
        image = coverage_image_gate(fine, coarse, 2)
        self.assertAlmostEqual(image["meanWithinPixelFineVariance"], 1 / 12)
        self.assertEqual(image["mismatchesInsideConstantFinePixels"], 1)
        self.assertEqual(image["strictGainRequiresCostRatioBelow"], 0)
        for probability in (F(1, 5), F(1, 2), F(1)):
            variances = []
            for pixel in range(3):
                values = list(zip(fine[:, 2 * pixel:2 * pixel + 2].ravel(),
                                  coarse[:, 2 * pixel:2 * pixel + 2].ravel()))
                mean, second = F(0), F(0)
                for f, g in values:
                    for b, mass in ((0, 1 - probability), (1, probability)):
                        y = int(g) + F(b) / probability * (int(f) - int(g))
                        mean += mass * y / len(values)
                        second += mass * y * y / len(values)
                variances.append(second - mean * mean)
            expected = F(1, 12) + F(1, 12) * (1 / probability - 1)
            self.assertEqual(sum(variances) / 3, expected)

    def test_unbiased_and_variance_by_exact_bernoulli_enumeration(self):
        # Each cell has different weight; both directions of mismatch are present.
        counts = [7, 2, 3, 11]
        for p in (F(1, 7), F(2, 5), F(1)):
            mean, second = F(0), F(0)
            for n, (fine, coarse) in zip(counts, ((0, 0), (0, 1), (1, 0), (1, 1))):
                for b, probability in ((0, 1 - p), (1, p)):
                    y = coarse + F(b, 1) / p * (fine - coarse)
                    mass = F(n, sum(counts)) * probability
                    mean += mass * y
                    second += mass * y * y
            self.assertEqual(mean, F(14, 23))
            v = F(14, 23) * F(9, 23)
            self.assertEqual(second - mean * mean, v + F(5, 23) * (1 / p - 1))

    def test_optimum_against_independent_probability_grid(self):
        for counts in ([40, 1, 2, 57], [1, 4, 3, 2], [0, 1, 0, 9]):
            m = moments(counts)
            v, q = m["fineVariance"], m["disagreement"]
            for r in (.01, .1, .5, 1, 2):
                result = optimum(v, q, r)
                grid = np.linspace(.00001, 1, 200001)
                brute = np.min((r + grid) * (v + q * (1 / grid - 1))) / v
                self.assertLessEqual(result["relativeCostVariance"], brute + 1e-12)
                self.assertLess(brute - result["relativeCostVariance"], 1e-7)

    def test_threshold_is_strict_break_even(self):
        m = moments([40, 1, 2, 57])
        threshold = m["strictGainRequiresCostRatioBelow"]
        for scale, sign in ((.9, -1), (1, 0), (1.1, 1)):
            value = optimum(m["fineVariance"], m["disagreement"], threshold * scale)
            delta = value["relativeCostVariance"] - 1
            if sign == 0:
                self.assertAlmostEqual(delta, 0, places=14)
            else:
                self.assertGreater(sign * delta, 0)

    def test_exact_proxy_and_zero_variance(self):
        m = moments([5, 0, 0, 5])
        self.assertEqual(m["strictGainRequiresCostRatioBelow"], 1)
        result = optimum(m["fineVariance"], 0, .2)
        self.assertEqual(result["oracleCorrectionProbability"], 0)
        self.assertEqual(result["relativeCostVariance"], .2)
        m = moments([0, 0, 0, 10])
        self.assertEqual(m["strictGainRequiresCostRatioBelow"], 0)
        self.assertIsNone(optimum(0, 0, .2)["relativeCostVariance"])

    def test_no_gain_and_invalid_inputs(self):
        m = moments([1, 4, 3, 2])
        self.assertEqual(m["strictGainRequiresCostRatioBelow"], 0)
        self.assertEqual(optimum(m["fineVariance"], m["disagreement"], .01)
                         ["withDirectFineFallback"], 1)
        for counts in ([0, 0, 0, 0], [1, -1, 1, 1], [1.5, 1, 1, 1]):
            with self.assertRaises(ValueError):
                moments(counts)
        for parameters in ((.2, .1, 0), (.2, 1.1, 1), (.2, .1, math.inf)):
            with self.assertRaises(ValueError):
                optimum(*parameters)


if __name__ == "__main__":
    unittest.main()
