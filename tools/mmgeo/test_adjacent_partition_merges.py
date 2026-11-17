import unittest

from probe_adjacent_partition_merges import adjacency, select


class AdjacentMergeTest(unittest.TestCase):
    def test_material_and_edge_adjacency(self):
        source = [("a", (0, 1, 2)), ("b", (1, 0, 3)), ("a", (2, 1, 4)),
                  ("a", (0, 5, 6))]
        groups = [dict(source_faces=[i]) for i in range(4)]
        self.assertEqual(dict(adjacency(source, groups)), {(0, 2): 1})

    def test_failed_queries_consume_budget_without_committing(self):
        pairs = [dict(pair=[0, 1], work=5, eligible=False, gain=10),
                 dict(pair=[0, 2], work=5, eligible=True, gain=3),
                 dict(pair=[1, 3], work=5, eligible=True, gain=4)]
        result = select(pairs, "pair_order", 10)
        self.assertEqual(result["work"], 10)
        self.assertEqual(result["queried"], [[0, 1], [0, 2]])
        self.assertEqual(result["selected"], [[0, 2]])

    def test_gain_greedy_is_not_a_global_oracle_bound(self):
        pairs = [dict(pair=[0, 1], work=2, eligible=True, gain=6),
                 dict(pair=[0, 2], work=2, eligible=True, gain=5),
                 dict(pair=[1, 3], work=2, eligible=True, gain=5)]
        result = select(pairs, "oracle_gain_per_work", 4)
        self.assertEqual(result["selected"], [[0, 1]])
        self.assertEqual(result["work"], 2)
        # The alternative matching has gain ten; greedy only obtains six.


if __name__ == "__main__":
    unittest.main()
