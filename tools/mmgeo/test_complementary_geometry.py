#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location(
    'complementary', Path(__file__).with_name('complementary_geometry.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BiasTests(unittest.TestCase):
    def test_opposite_residuals_cancel_but_iid_has_finite_variance(self):
        result = m.solve_bias([[1., 0.], [-1., 0.]])
        self.assertLess(result['energy'], 1e-20)
        self.assertAlmostEqual(result['iid8'], 1./8)
        np.testing.assert_allclose(result['weights'], [.5, .5])

    def test_one_sided_residuals_have_irreducible_bias(self):
        result = m.solve_bias([[1., 2.], [2., 4.]])
        self.assertAlmostEqual(result['energy'], 5.)
        self.assertAlmostEqual(result['lower'], 5.)

    def test_two_state_solution_against_analytic_segment_projection(self):
        rng = np.random.default_rng(853)
        for _ in range(100):
            a, b = rng.normal(size=(2, 8))
            direction = b-a
            t = np.clip(-np.dot(a, direction)/np.dot(direction, direction), 0., 1.)
            exact = np.square(a+t*direction).sum()
            result = m.solve_bias([a, b])
            self.assertAlmostEqual(result['energy'], exact, places=11)
            self.assertLessEqual(result['lower'], exact+1e-11)

    def test_certificate_bounds_enumerated_simplex_and_is_scale_consistent(self):
        d = np.array([[1., 2.], [-2., 1.], [1., -1.]])
        result = m.solve_bias(d, max_steps=3)
        grid = [np.square(np.array([i, j, 100-i-j])/100 @ d).sum()
                for i in range(101) for j in range(101-i)]
        self.assertLessEqual(result['lower'], min(grid)+1e-12)
        # This triangle contains the origin with weights (1/9, 1/3, 5/9).
        self.assertLessEqual(result['lower'], 1e-12)
        scaled = m.solve_bias(d*1e-7, max_steps=3)
        self.assertAlmostEqual(scaled['energy']/1e-14, result['energy'], places=10)
        self.assertAlmostEqual(sum(result['weights']), 1.)
        self.assertTrue(np.all(result['weights'] >= 0))

    def test_zero_and_single_state(self):
        self.assertEqual(m.solve_bias([[0., 0.]])['energy'], 0.)
        result = m.solve_bias([[3., 4.]])
        self.assertEqual(result['energy'], 25.)
        self.assertEqual(result['iid16'], 25.)


if __name__ == '__main__':
    unittest.main()
