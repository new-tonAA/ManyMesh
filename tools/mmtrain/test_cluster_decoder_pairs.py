"""Independent analytic and brute-force controls for residual-label geometry."""

import unittest

import numpy as np

from cluster_decoder_pairs import closest_on_triangles, nearest_surface


class SurfaceLabelTest(unittest.TestCase):
    def test_known_face_edge_and_vertex_projections(self):
        triangle = np.array((((0., 0, 0), (1, 0, 0), (0, 1, 0)),))
        for query, expected in (((.2, .2, .3), (.2, .2, 0)),
                                ((2, 0, 1), (1, 0, 0)),
                                ((-1, -1, .5), (0, 0, 0)),
                                ((1, 1, 0), (.5, .5, 0))):
            point, distance = closest_on_triangles(np.array(query), triangle)
            np.testing.assert_allclose(point[0], expected, atol=1e-14)
            self.assertAlmostEqual(distance[0], np.sum((np.array(query)-expected)**2))

    def test_conservative_tree_finds_far_centroid_triangle(self):
        # The long triangle is closest at its tip, while a small offset triangle
        # has the nearer centroid. Searching only a fixed k nearest centers fails.
        triangles = np.array((((0., 0, 0), (100, 0, 0), (100, 1, 0)),
                              ((0, 0, 2), (1, 0, 2), (0, 1, 2))))
        actual, _ = nearest_surface(np.array(((.01, 0, .01),)), triangles)
        np.testing.assert_allclose(actual, ((.01, 0, 0),), atol=1e-14)

    def test_tree_matches_exhaustive_distances_on_random_triangles(self):
        random = np.random.default_rng(8701)
        triangles = random.normal(size=(40, 3, 3))
        queries = random.normal(size=(30, 3))
        actual, work = nearest_surface(queries, triangles)
        self.assertGreater(work, len(queries))
        for query, point in zip(queries, actual):
            _, distances = closest_on_triangles(query, triangles)
            self.assertAlmostEqual(np.sum((query-point)**2), distances.min(), places=12)

    def test_candidate_cap_rejects_instead_of_returning_approximation(self):
        triangles = np.array((((0., 0, 0), (1, 0, 0), (0, 1, 0)),))
        with self.assertRaisesRegex(ValueError, "cap exceeded"):
            nearest_surface(np.array(((0., 0, 1),)), triangles, max_candidates=1)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Degenerate"):
            closest_on_triangles(np.zeros(3), np.zeros((1, 3, 3)))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            nearest_surface(np.array(((np.nan, 0, 0),)), np.ones((1, 3, 3)))


if __name__ == "__main__":
    unittest.main()
