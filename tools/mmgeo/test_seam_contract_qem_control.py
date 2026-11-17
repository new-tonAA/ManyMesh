import unittest

import numpy as np

from seam_contract_qem_control import SeamContractQEM


class SeamContractQEMTest(unittest.TestCase):
    def setUp(self):
        self.positions = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.],
                                   [0., 1., 0.], [.5, .5, 0.]])
        self.faces = np.array([(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])

    def test_physical_boundary_does_not_imply_seam_mask(self):
        solver = SeamContractQEM(self.positions, self.faces, [])
        self.assertEqual(solver.advance(0), 2)
        self.assertTrue(solver.check_seams())

    def test_new_seam_chord_is_rejected(self):
        solver = SeamContractQEM(self.positions, self.faces, [0, 1, 2, 3])
        self.assertEqual(solver.advance(0), 4)
        self.assertTrue(solver.check_seams())
        np.testing.assert_array_equal(solver.p[:4], self.positions[:4])

    def test_shared_interior_vertex_cannot_be_removed(self):
        solver = SeamContractQEM(self.positions, self.faces, [4])
        self.assertEqual(solver.advance(0), 4)
        self.assertTrue(solver.check_seams())

    def test_invalid_seam_index(self):
        with self.assertRaises(ValueError):
            SeamContractQEM(self.positions, self.faces, [5])

    def test_position_alias_cannot_hide_a_new_locked_edge(self):
        solver = SeamContractQEM(self.positions, self.faces, [0, 1, 2, 3])
        solver.p[4] = solver.p[0]
        self.assertFalse(solver.check_seams())


if __name__ == "__main__":
    unittest.main()
