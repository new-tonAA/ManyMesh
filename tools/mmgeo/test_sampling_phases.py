#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location(
    'phases', Path(__file__).with_name('evaluate_sampling_phases.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PhaseTests(unittest.TestCase):
    def test_global_phase_and_worst_absolute_change(self):
        c, z = m.phase_errors([[4, 8, -1, -.2], [7, 11, 0, .3], [0, 1, 0, -.7]], 3)
        self.assertEqual(c[7], 1.)
        self.assertEqual(z[7], .3)
        self.assertEqual(z[3], .7)
        self.assertEqual(np.count_nonzero(c), 1)
        self.assertEqual(np.count_nonzero(z), 2)

    def test_empty_delta_is_safe_for_every_phase(self):
        c, z = m.phase_errors([], 3)
        np.testing.assert_array_equal(c, np.zeros(9))
        np.testing.assert_array_equal(z, np.zeros(9))


if __name__ == '__main__':
    unittest.main()
