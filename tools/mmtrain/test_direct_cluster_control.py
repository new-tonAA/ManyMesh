"""Direct-displacement serialization and boundary controls."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from cluster_decoder import topology
from direct_cluster_control import encode_direct, decode_direct
from test_cluster_decoder import patch_pair


class DirectControlTest(unittest.TestCase):
    def test_roundtrip_nonzero_displacement_and_shared_face_refinement(self):
        mesh = patch_pair().checked()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"direct.sidecar"
            offset = np.array(((0, 0, .03), (0, 0, -.03), (0, 0, 0), (0, 0, 0)))
            encode_direct(path, mesh, offset, (1, 7))
            result, report = decode_direct(mesh, path, 12)
            self.assertEqual(report["triangles"], 12)
            self.assertEqual(topology(mesh)[1], topology(result)[1])
            self.assertAlmostEqual(result.positions[4, 2], .03, places=8)
            self.assertAlmostEqual(result.positions[7, 2], -.03, places=8)
            with self.assertRaisesRegex(ValueError, "budget"):
                decode_direct(mesh, path, 11)
            changed = mesh.checked()
            changed.positions[4, 2] = .001
            with self.assertRaisesRegex(ValueError, "mismatch"):
                decode_direct(changed, path, 12)

    def test_cap_and_local_flip_rejection(self):
        mesh = patch_pair().checked()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"direct.sidecar"
            encode_direct(path, mesh, ((2, 0, 0), (0, 0, 0)), np.array([], dtype=int))
            with self.assertRaisesRegex(ValueError, "offset cap"):
                decode_direct(mesh, path, 8)
            with self.assertRaisesRegex(ValueError, "local flip"):
                decode_direct(mesh, path, 8, max_offset=4)


if __name__ == "__main__":
    unittest.main()
