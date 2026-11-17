import unittest
from fractions import Fraction as F

from restir_lod_measure_preflight import estimate


class MeasurePreflightTest(unittest.TestCase):
    def test_canonical_only_and_nonuniform_sampling(self):
        domains = [dict(mapping=[0, 1], area=[F(2), F(3)], probability=[F(1, 5), F(4, 5)])]
        actual, draws = estimate(domains, [F(2), F(3)], [F(4), F(7)], [F(11), F(2)])
        self.assertEqual(actual, 29)
        self.assertEqual(draws, 2)

    def test_uncovered_target_refused(self):
        with self.assertRaises(ValueError):
            estimate([dict(mapping=[0], area=[F(1)], probability=[F(1)])],
                     [F(1), F(1)], [F(1), F(1)], [F(1), F(1)])

    def test_many_to_one_is_not_silently_a_partial_bijection(self):
        with self.assertRaises(ValueError):
            estimate([dict(mapping=[0, 0], area=[F(1), F(1)], probability=[F(1, 2)] * 2)],
                     [F(1)], [F(1)], [F(1)])


if __name__ == "__main__":
    unittest.main()
