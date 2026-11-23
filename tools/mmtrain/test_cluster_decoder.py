"""Mechanical decoder tests; no learned quality or performance claim is tested."""

import json
from pathlib import Path
import tempfile
import struct
import unittest

import numpy as np

from cluster_decoder import FEATURES, Mesh, Model, decode, topology, write_sidecar
from cluster_decoder_pilot import partition_faces, read_stl


def patch_pair():
    # Two square fans share the edge x=1; only their centers may move.
    positions = np.array(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (.5, .5, 0),
                          (2, 0, 0), (2, 1, 0), (1.5, .5, 0)), dtype=float)
    faces = np.array(((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4),
                      (1, 5, 7), (5, 6, 7), (6, 2, 7), (2, 1, 7)))
    return Mesh(positions, faces, np.array((0, 0, 0, 0, 1, 1, 1, 1)))


class DecoderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "residual.sidecar"
        self.mesh = patch_pair()
        weights = np.zeros((FEATURES, 2, 3), dtype=np.float32)
        weights[0, 0, 2] = 0.05
        weights[1, 1, 0] = 0.02
        self.model = Model(weights)

    def save(self, latent=None, refine=()):
        if latent is None:
            latent = np.zeros((2, 2))
        write_sidecar(self.path, self.mesh, self.model, latent, refine)

    def corrupt(self, **changes):
        with np.load(self.path, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
        arrays.update(changes)
        with self.path.open("wb") as stream:
            np.savez(stream, **arrays)

    def test_identity_roundtrip_keeps_order_and_positions(self):
        self.save()
        mesh, report = decode(self.mesh, self.model, self.path, 8)
        np.testing.assert_array_equal(mesh.positions, self.mesh.positions)
        np.testing.assert_array_equal(mesh.triangles, self.mesh.triangles)
        np.testing.assert_array_equal(mesh.face_clusters, self.mesh.face_clusters)
        self.assertEqual(report["sidecar_bytes"], self.path.stat().st_size)
        self.assertEqual(report["added_triangles"], 0)
        self.assertFalse(report["global_intersections_checked"])

    def test_nonzero_latents_move_interiors_but_not_interfaces(self):
        self.save(((1, 0), (-1, 0)))
        mesh, report = decode(self.mesh, self.model, self.path, 8)
        locked, boundary, _ = topology(self.mesh.checked())
        self.assertEqual(report["locked_vertices"], 6)
        np.testing.assert_array_equal(mesh.positions[locked], self.mesh.positions[locked])
        self.assertGreater(mesh.positions[4, 2], 0)
        self.assertLess(mesh.positions[7, 2], 0)
        self.assertEqual(topology(mesh)[1], boundary)

    def test_independent_clusters_are_local(self):
        self.save(((1, 0), (0, 0)))
        result, _ = decode(self.mesh, self.model, self.path, 8)
        np.testing.assert_array_equal(result.positions[5:], self.mesh.positions[5:])

    def test_refine_both_sides_without_splitting_shared_edge(self):
        # Refine the faces incident on the common edge, in deliberately reversed order.
        self.save(((1, 0), (-1, 0)), (7, 1))
        result, report = decode(self.mesh, self.model, self.path, 12)
        self.assertEqual(len(result.triangles), 12)
        self.assertEqual(report["added_triangles"], 4)
        self.assertEqual(len(result.positions), 10)
        self.assertEqual(topology(result)[1], topology(self.mesh.checked())[1])
        for edge in ((1, 2), (2, 1)):
            count = sum(tuple(pair) == edge for face in result.triangles
                        for pair in zip(face, np.roll(face, -1)))
            self.assertEqual(count, 1)

    def test_budget_rejection_does_not_mutate_input(self):
        before = self.mesh.positions.copy()
        self.save(refine=(0,))
        with self.assertRaisesRegex(ValueError, "exceed budget"):
            decode(self.mesh, self.model, self.path, 9)
        np.testing.assert_array_equal(before, self.mesh.positions)

    def test_sidecar_rejects_changed_model_or_partition_or_geometry(self):
        self.save()
        other = Model(self.model.weights.copy())
        other.weights[0, 0, 0] = 0.01
        with self.assertRaisesRegex(ValueError, "mismatch"):
            decode(self.mesh, other, self.path, 8)
        for edit in ("positions", "face_clusters"):
            mesh = self.mesh.checked()
            if edit == "positions":
                mesh.positions[4, 2] = 0.01
            else:
                mesh.face_clusters[:] = 1 - mesh.face_clusters
            with self.assertRaisesRegex(ValueError, "mismatch"):
                decode(mesh, self.model, self.path, 8)

    def test_corrupted_sidecar_arrays_and_version(self):
        for changes in ({"latent": np.zeros((2, 2), dtype=np.float64)},
                        {"latent": np.full((2, 2), np.nan, dtype=np.float32)},
                        {"latent": np.zeros((1, 2), dtype=np.float32)},
                        {"refine_faces": np.array((0, 0))},
                        {"refine_faces": np.array((8,))},
                        {"refine_faces": np.array((0.5,))}):
            with self.subTest(changes=list(changes)):
                self.save()
                self.corrupt(**changes)
                with self.assertRaises(ValueError):
                    decode(self.mesh, self.model, self.path, 20)
        self.save()
        self.corrupt(metadata=np.frombuffer(json.dumps({"version": 2}).encode(), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            decode(self.mesh, self.model, self.path, 8)

    def test_offset_cap_rejects_before_emitting_output(self):
        self.save(((100, 0), (0, 0)))
        with self.assertRaisesRegex(ValueError, "offset cap"):
            decode(self.mesh, self.model, self.path, 8)

    def test_winding_duplicate_and_degenerate_inputs_rejected(self):
        for faces in (self.mesh.triangles[:, ::-1] * 0,
                      np.vstack((self.mesh.triangles, self.mesh.triangles[0]))):
            mesh = Mesh(self.mesh.positions, faces, np.zeros(len(faces), dtype=int))
            with self.assertRaises(ValueError):
                mesh.checked()
        mesh = self.mesh.checked()
        mesh.triangles[0] = mesh.triangles[0, ::-1]
        with self.assertRaisesRegex(ValueError, "oriented edge"):
            mesh.checked()

    def test_chart_duplicates_stay_locked(self):
        mesh = self.mesh.checked()
        mesh.positions = np.vstack((mesh.positions, mesh.positions[1]))
        mesh.triangles[4, 0] = 8
        locked, _, _ = topology(mesh.checked())
        self.assertTrue(locked[1] and locked[8])

    def test_large_cluster_id_and_noninteger_indices_rejected(self):
        mesh = self.mesh.checked()
        mesh.face_clusters[0] = 2**60
        with self.assertRaisesRegex(ValueError, "dense"):
            mesh.checked()
        mesh = self.mesh.checked()
        mesh.triangles = mesh.triangles.astype(float)
        with self.assertRaisesRegex(ValueError, "integers"):
            mesh.checked()

    def test_interior_flip_is_rejected(self):
        weights = np.zeros((FEATURES, 1, 3), dtype=np.float32)
        weights[0, 0, 0] = 2.0
        model = Model(weights, max_offset=3)
        write_sidecar(self.path, self.mesh, model, ((1,), (0,)))
        with self.assertRaisesRegex(ValueError, "flip"):
            decode(self.mesh, model, self.path, 8)

    def test_stl_binary_offsets_match_ascii_and_truncation_fails(self):
        # Deliberately use nonzero normals/attributes so an incorrect offset is detected.
        ascii_data = ("solid demo\nfacet normal 0 0 1\nouter loop\n"
                      "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
                      "endloop\nendfacet\nendsolid demo\n")
        ascii_path = Path(self.temp.name) / "ascii.stl"
        binary_path = Path(self.temp.name) / "binary.stl"
        ascii_path.write_bytes(ascii_data.encode())
        binary = b"solid binary".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack(
            "<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 7)
        binary_path.write_bytes(binary)
        for actual, expected in zip(read_stl(binary_path), read_stl(ascii_path)):
            np.testing.assert_array_equal(actual, expected)
        binary_path.write_bytes(binary[:-1])
        with self.assertRaises((ValueError, UnicodeError)):
            read_stl(binary_path)
        ascii_path.write_bytes(ascii_data.replace("vertex 0 1 0\n", "").encode())
        with self.assertRaises(ValueError):
            read_stl(ascii_path)

    def test_partition_respects_cap_and_is_deterministic(self):
        groups = partition_faces(self.mesh.triangles, 3)
        self.assertTrue(np.all(np.bincount(groups) <= 3))
        np.testing.assert_array_equal(groups, partition_faces(self.mesh.triangles, 3))
        np.testing.assert_array_equal(np.unique(groups), np.arange(groups.max() + 1))
        with self.assertRaises(ValueError):
            partition_faces(self.mesh.triangles, 0)


if __name__ == "__main__":
    unittest.main()
