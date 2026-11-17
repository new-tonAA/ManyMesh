import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('offset',Path(__file__).with_name('normal_offset_control.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
bspec=importlib.util.spec_from_file_location('coverage_bias',Path(__file__).with_name('audit_silhouette_bias.py'))
bias=importlib.util.module_from_spec(bspec);bspec.loader.exec_module(bias)


class OffsetTests(unittest.TestCase):
    def test_signed_coverage_separates_missing_and_extra(self):
        reference=np.array([[1,1,0,0],[1,0,0,0]])
        candidate=np.array([[0,1,1,0],[0,0,0,0]])
        result=bias.coverage_bias(reference,candidate)
        self.assertEqual(result['missingSamples'],2)
        self.assertEqual(result['extraSamples'],1)
        self.assertEqual(result['netMissing'],1)
        self.assertAlmostEqual(result['imbalance'],1/3)

    def test_equal_coverage_has_zero_bias(self):
        a=np.array([[0,1]])
        self.assertEqual(bias.coverage_bias(a,a)['imbalance'],0.)

    def test_boundary_vertices_are_exactly_fixed(self):
        p=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[.5,.5,0]],float)
        f=np.array([[0,1,4],[1,2,4],[2,3,4],[3,0,4]])
        field=m.normal_field(p,f)
        np.testing.assert_array_equal(field[:4],np.zeros((4,3)))
        np.testing.assert_allclose(field[4],[0,0,np.sqrt(.5)])

    def test_gate_rejects_flips_and_zero_area(self):
        p=np.array([[0,0,0],[1,0,0],[0,1,0]],float);f=np.array([[0,1,2]])
        self.assertTrue(m.geometry_safe(p,p,f))
        self.assertFalse(m.geometry_safe(p,p[[0,2,1]],f))
        collapsed=p.copy();collapsed[2]=p[1]
        self.assertFalse(m.geometry_safe(p,collapsed,f))


if __name__=='__main__':unittest.main()
