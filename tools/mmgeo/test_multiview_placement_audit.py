#!/usr/bin/env python3
"""Regression tests for population-wide research reporting."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'audit', Path(__file__).with_name('audit_multiview_placement.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SummaryTests(unittest.TestCase):
    def test_fallbacks_contribute_to_denominator_and_regressions_remain(self):
        rows = [dict(seed=dict(total=100., coverage=1.),
                     result=dict(total=100., coverage=1.)),
                dict(seed=dict(total=4., coverage=1.),
                     result=dict(total=1., coverage=0.)),
                dict(seed=dict(total=2., coverage=0.),
                     result=dict(total=3., coverage=1.))]
        result = audit.summarize(rows)
        self.assertEqual(result['cases'], 3)
        self.assertAlmostEqual(result['relativeReduction'], 2./106.)
        self.assertEqual(result['improved'], 1)
        self.assertEqual(result['regressed'], 1)
        self.assertEqual(result['coverageRegressed'], 1)

    def test_empty_and_zero_error_do_not_claim_relative_gain(self):
        self.assertIsNone(audit.summarize([])['relativeReduction'])
        zero = dict(total=0., coverage=0.)
        self.assertIsNone(audit.summarize([dict(seed=zero, result=zero)])['relativeReduction'])


if __name__ == '__main__':
    unittest.main()
