"""Low-rank field controls independent of the real-asset training corpus."""

import unittest

import numpy as np

from cluster_decoder import features
from fit_cluster_decoder import encode_pair, learn_basis, solve_ridge


class FitControlTest(unittest.TestCase):
    def synthetic_pair(self):
        random = np.random.default_rng(321)
        points = random.uniform(-.5, .5, (120, 3))
        basis = features(points)
        groups = np.repeat(np.arange(6), 20)
        offsets = np.zeros_like(points)
        for group in range(6):
            mask = groups == group
            offsets[mask, 2] = .01 + .005 * group * points[mask, 0]
        return {"features": basis, "offsets": offsets, "query_clusters": groups,
                "face_clusters": groups, "free_vertices": np.arange(120),
                "queries": points, "targets": points+offsets,
                "triangles": np.zeros((0, 3), dtype=np.int64)}

    def test_learned_subspace_recovers_known_shared_fields(self):
        pair = self.synthetic_pair()
        model, singular = learn_basis([pair], rank=4, ridge=1e-8, mode="fixed")
        self.assertEqual(model.weights.shape, (10, 4, 3))
        latent, refine, diagnostics = encode_pair(pair, model, 1e-8, 0)
        self.assertEqual(latent.shape, (6, 4))
        self.assertEqual(len(refine), 0)
        self.assertLess(diagnostics["normalized_label_sse"],
                        diagnostics["zero_residual_label_sse"] * 1e-8)
        self.assertGreater(singular[0], 0)

    def test_no_free_queries_cannot_train_fixed_model(self):
        pair = self.synthetic_pair()
        pair["free_vertices"] = np.array([], dtype=np.int64)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            learn_basis([pair], 4, 1e-5, "fixed")

    def test_empty_encoding_and_invalid_regularization(self):
        np.testing.assert_array_equal(solve_ridge(np.empty((0, 4)), np.empty((0, 1)), 1e-5),
                                      np.zeros((4, 1)))
        with self.assertRaises(ValueError):
            solve_ridge(np.ones((3, 2)), np.ones((3, 1)), -1)


if __name__ == "__main__":
    unittest.main()
