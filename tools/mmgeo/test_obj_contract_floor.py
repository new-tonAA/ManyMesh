"""Independent small-complex checks for the conditional topological bound."""
import unittest
import json
from pathlib import Path
import tempfile

from audit_obj_contract_floor import audit_partition, component_floor, read_capture


class ContractFloorTest(unittest.TestCase):
    def test_capture_materials_and_cross_unit_welding(self):
        data = dict(version=1, units=[dict(material=7, positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                                          triangles=[[0, 1, 2]]),
                                      dict(material=8, positions=[[1, 0, 0], [1, 1, 0], [0, 1, 0]],
                                          triangles=[[0, 1, 2]])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            faces, sizes, vertices = read_capture(path)
        self.assertEqual(vertices, 4)
        self.assertEqual(sizes, {3: 2})
        self.assertEqual(audit_partition(faces, False)["component_count"], 1)
        self.assertEqual(audit_partition(faces, True)["component_count"], 2)

    def test_capture_out_of_range_indices_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(dict(version=1, units=[dict(material=1,
                positions=[[0, 0, 0]], triangles=[[0, -1, 0]])])), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_capture(path)

    def test_tetrahedron_cannot_reduce_below_four(self):
        result = component_floor([(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)])
        self.assertTrue(result["supported"])
        self.assertEqual((result["chi"], result["conditional_floor"]), (2, 4))

    def test_disk_boundary_is_a_constraint(self):
        result = component_floor([(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
        self.assertTrue(result["supported"])
        self.assertEqual((result["chi"], result["boundary_edges"], result["conditional_floor"]), (1, 4, 2))

    def test_vertex_pinch_and_duplicate_are_unsupported(self):
        for triangles in ([(0, 1, 2), (0, 3, 4)], [(0, 1, 2), (0, 1, 2)]):
            result = component_floor(triangles)
            self.assertFalse(result["supported"])
            self.assertIsNone(result["conditional_floor"])

    def test_material_partition_adds_fixed_boundary(self):
        faces = [("a", (0, 1, 2)), ("b", (0, 2, 3))]
        global_result = audit_partition(faces, False)
        materials = audit_partition(faces, True)
        self.assertEqual(global_result["component_count"], 1)
        self.assertEqual(materials["component_count"], 2)
        self.assertEqual(materials["conditional_floor"], 2)

    def test_annulus_has_two_boundary_loops(self):
        triangles = []
        for i in range(4):
            j = (i + 1) % 4
            triangles.extend([(i, j, j + 4), (i, j + 4, i + 4)])
        result = component_floor(triangles)
        self.assertTrue(result["supported"])
        self.assertEqual((result["chi"], result["boundary_edges"], result["conditional_floor"]), (0, 8, 8))

    def test_nonmanifold_rejected(self):
        self.assertFalse(component_floor([(0, 1, 2), (1, 0, 3), (0, 1, 4)])["supported"])

    def test_repairable_winding_does_not_invalidate_floor(self):
        result = component_floor([(0, 1, 2), (0, 1, 3)])
        self.assertTrue(result["supported"])
        self.assertTrue(result["orientable"])
        self.assertEqual(result["orientation_conflicts"], 1)
        self.assertEqual(result["winding_flip_count"], 1)
        self.assertEqual(result["conditional_floor"], 2)

    def test_nonorientable_manifold_still_has_euler_floor(self):
        triangles = []
        for i in range(5):
            a, b = 2 * i, 2 * i + 1
            c, d = (2 * i + 2, 2 * i + 3) if i < 4 else (1, 0)
            triangles.extend([(a, b, c), (b, d, c)])
        result = component_floor(triangles)
        self.assertTrue(result["supported"])
        self.assertFalse(result["orientable"])
        self.assertIsNone(result["winding_flip_count"])
        self.assertEqual((result["chi"], result["conditional_floor"]), (0, 10))

    def test_partial_population_does_not_get_complete_bound(self):
        result = audit_partition([("a", (0, 1, 2)), ("b", (3, 4, 5)),
                                  ("b", (3, 6, 7))], True)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["conditional_floor"])
        self.assertEqual(result["supported_components_floor"], 1)


if __name__ == "__main__":
    unittest.main()
