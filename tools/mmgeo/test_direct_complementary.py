#!/usr/bin/env python3
import importlib.util
import itertools
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location(
    'direct', Path(__file__).with_name('direct_complementary.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DirectTests(unittest.TestCase):
    def test_expected_error_matches_exhaustive_iid_sequences(self):
        a = np.array([[[1., -2.], [3., .5]]])
        b = np.array([[[-.5, 3.], [2., -1.]]])
        errors = [np.square(np.mean(sequence, axis=0)).sum()
                  for sequence in itertools.product([a, b], repeat=4)]
        self.assertAlmostEqual(m.pair_metrics(a, b, 4)['expected'], np.mean(errors))

    def test_equal_states_reduce_to_static_error(self):
        a = np.array([[[1., 2.]]])
        self.assertEqual(m.pair_metrics(a, a)['expected'], 5.)
        self.assertEqual(m.pair_metrics(a, a)['coverageExpected'], 1.)

    def test_affine_renderer_midpoint_dominates_finite_history_pair(self):
        rng = np.random.default_rng(2027)
        for _ in range(50):
            A, b = rng.normal(size=(6, 3)), rng.normal(size=6)
            x, y = rng.normal(size=(2, 3))
            a, c = (A@x+b).reshape(1, 3, 2), (A@y+b).reshape(1, 3, 2)
            midpoint = A@((x+y)*.5)+b
            expected = np.square(midpoint).sum()+np.square(A@(x-y)).sum()/32
            self.assertAlmostEqual(m.pair_metrics(a, c)['expected'], expected)
            self.assertGreaterEqual(expected+1e-12, np.square(midpoint).sum())

    def test_nonlinear_residual_can_escape_static_curve(self):
        # Analytic toy, not evidence of mesh/raster benefit. Minimum static error is 1/16.
        def residual(x):
            return np.array([[[x, x*x-.25]]])
        pair = m.pair_metrics(residual(-.5), residual(.5))
        self.assertAlmostEqual(pair['expected'], 1./32)
        self.assertLess(pair['expected'], 1./16)

    def test_budget_and_rejected_geometry_never_rendered(self):
        for paired in (False, True):
            calls = []
            def evaluate(target):
                calls.append(target.copy())
                return np.array([[[0., target[0]-1.]]])
            result = m.search(np.zeros(3), 1., evaluate,
                              lambda x: bool(np.all(x == 0)), paired)
            self.assertEqual(result['attempts'], 48)
            self.assertEqual(result['rejected'], 48)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['score'], 1.)

    def test_static_search_improves_and_records_best(self):
        result = m.search(np.zeros(3), 1., lambda x: np.array([[[0., x[0]-.2]]]),
                          lambda x: True, False)
        self.assertLess(result['score'], .04)
        self.assertAlmostEqual(result['score'], result['bestSingle'])
        self.assertEqual(result['rasters'], 49)


if __name__ == '__main__':
    unittest.main()
