import unittest

from audit_partition_boundary_floor import evaluate, partition


class PartitionFloorTest(unittest.TestCase):
    def test_coverage_capacity_material_and_repeatability(self):
        faces = [("a", (0, 1, 2)), ("b", (1, 0, 3)), ("a", (2, 1, 4))]
        groups = partition(faces, 2)
        self.assertEqual(groups, partition(faces, 2))
        self.assertEqual(sorted(i for g in groups for i in g), list(range(3)))
        self.assertTrue(all(len(g) <= 2 for g in groups))
        self.assertTrue(all(len({faces[i][0] for i in g}) == 1 for g in groups))

    def test_locked_partition_cost_on_disk(self):
        faces = [("a", t) for t in ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4))]
        self.assertEqual(evaluate(faces, 1)["conditional_floor"], 4)
        self.assertEqual(evaluate(faces, 4)["conditional_floor"], 2)

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            partition([("a", (0, 1, 2))], 0)


if __name__ == "__main__":
    unittest.main()
