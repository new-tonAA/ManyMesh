import unittest

import numpy as np

from probe_partition_qem_exhaustion import boundary, run_group


class PartitionQEMTest(unittest.TestCase):
    def test_reference_operator_can_stop_above_floor(self):
        world = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.],
                          [0., 1., 0.], [.5, .5, 0.]])
        source = [("a", t) for t in ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4))]
        result = run_group(world, source, list(range(4)), 2)
        # This reference QEM disallows either endpoint of a collapse being locked.
        # It cannot remove the center into a locked boundary vertex, unlike a
        # general boundary-preserving simplifier. The experiment must expose this gap.
        self.assertEqual(result["actual"], 4)
        self.assertTrue(result["heap_empty"])
        self.assertTrue(result["topology_checked"])
        self.assertTrue(result["boundary_positions_preserved"])

    def test_boundary_counts_are_independent_of_winding(self):
        self.assertEqual(boundary([[0, 1, 2], [0, 1, 3]]),
                         {(0, 2), (1, 2), (0, 3), (1, 3)})

    def test_wrong_frozen_floor_refused(self):
        with self.assertRaises(ValueError):
            run_group(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                      [("a", (0, 1, 2))], [0], 0)


if __name__ == "__main__":
    unittest.main()
