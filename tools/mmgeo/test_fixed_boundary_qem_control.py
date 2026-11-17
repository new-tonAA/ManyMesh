import unittest

import numpy as np

from fixed_boundary_qem_control import FixedBoundaryQEM
from probe_partition_qem_exhaustion import boundary


class FixedBoundaryQEMTest(unittest.TestCase):
    def setUp(self):
        self.positions = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.],
                                   [0., 1., 0.], [.5, .5, 0.]])
        self.faces = np.array([(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])

    def test_disk_reaches_boundary_preserving_two_triangles(self):
        solver = FixedBoundaryQEM(self.positions, self.faces)
        self.assertEqual(solver.advance(0), 2)
        self.assertEqual(boundary(solver.f[solver.alive]), boundary(self.faces))
        np.testing.assert_array_equal(solver.p[:4], self.positions[:4])
        self.assertEqual(len(solver.actions), 1)
        self.assertEqual(solver.actions[0]["remove"], 4)

    def test_boundary_cannot_be_deleted_or_moved(self):
        solver = FixedBoundaryQEM(self.positions, self.faces)
        self.assertFalse(solver.legal(4, 0, self.positions[0]))
        self.assertFalse(solver.legal(0, 4, self.positions[0] + .01))
        self.assertFalse(solver.legal(0, 1, self.positions[0]))

    def test_locked_target_direction_when_its_id_is_larger(self):
        order = [4, 0, 1, 2, 3]
        inverse = {old: new for new, old in enumerate(order)}
        solver = FixedBoundaryQEM(self.positions[order],
                                  [[inverse[int(v)] for v in t] for t in self.faces])
        self.assertEqual(solver.advance(0), 2)
        self.assertEqual(solver.actions[0]["remove"], 0)
        np.testing.assert_array_equal(solver.p[1:], self.positions[order][1:])


if __name__ == "__main__":
    unittest.main()
