#!/usr/bin/env python3
#
# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Depth-sharing invariants; run with python -m unittest discover -s tools/mmtrain."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from lod_proxy import Graph, frame_scores, resolve_cuts


class ResolveCutsTest(unittest.TestCase):
    def test_no_candidates_needs_no_rasterization(self):
        graph = object.__new__(Graph)
        graph.vertices = 3
        graph.positions = np.arange(3)
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "oracle_baseline.obj").write_text(
                "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
            (path / "oracle.csv").write_text(
                "stem,triangles\noracle_reference,1\noracle_baseline,1\n", encoding="utf-8")
            with patch("lod_proxy.fragments", side_effect=AssertionError("Unexpected raster")):
                scores, work = frame_scores(path, {}, 16, 16, graph, True)
            self.assertEqual(work["shared_raster_triangles"], 0)
            self.assertEqual(work["interaction_values"], [])
            for value in scores.values():
                np.testing.assert_array_equal(value, [0])

    def check_resolve(self, cuts, triangles, face, pixel, depth, count):
        actual, work = resolve_cuts(cuts, triangles, face, pixel, depth, count)
        for cut, image in zip(cuts, actual, strict=True):
            expected = np.zeros(count)
            for f, p, z in zip(face, pixel, depth, strict=True):
                if triangles[f] in cut:
                    expected[p] = max(expected[p], z)
            np.testing.assert_array_equal(image, expected)
            self.assertFalse(image.flags.writeable)
        return actual, work

    def test_random_occlusion_and_duplicates(self):
        rng = np.random.default_rng(42)
        triangles = [(i, i + 1, i + 2) for i in range(32)]
        for _ in range(100):
            common = set(triangles[:4])
            cuts = [common | {tri for tri in triangles[4:] if rng.random() < 0.5}
                    for _ in range(5)]
            cuts.append(cuts[0].copy())
            images, work = self.check_resolve(
                cuts, triangles, rng.integers(0, 32, 500), rng.integers(0, 64, 500),
                rng.integers(1, 8, 500).astype(float), 64)
            self.assertIs(images[0], images[-1])
            self.assertLessEqual(work["unique_depth_resolves"], 5)

    def test_reference_excludes_candidate_occluder(self):
        triangles = [(0, 1, 2), (3, 4, 5)]
        images, work = self.check_resolve(
            [set(triangles), set(triangles), {triangles[1]}], triangles,
            np.array([0, 1]), np.array([0, 0]), np.array([2.0, 1.0]), 2)
        self.assertEqual(images[2][0], 1)
        self.assertEqual(work["common_raster_triangles"], 1)

    def test_disjoint_and_empty_fragments(self):
        triangles = [(0, 1, 2), (3, 4, 5)]
        self.check_resolve([{triangles[0]}, {triangles[1]}, set()], triangles,
                           np.array([0, 1]), np.array([0, 0]), np.array([1., 2.]), 1)
        self.check_resolve([set(), set()], [], np.array([], dtype=int),
                           np.array([], dtype=int), np.array([]), 4)


if __name__ == "__main__":
    unittest.main()
