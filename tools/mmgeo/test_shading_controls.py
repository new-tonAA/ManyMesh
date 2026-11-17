import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('shading_test',Path(__file__).with_name('evaluate_shading_controls.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ShadingTests(unittest.TestCase):
    def test_planar_retriangulation_has_identical_smooth_shading(self):
        ps=np.array([[2,2,.5],[10,2,.5],[10,10,.5],[2,10,.5]],float)
        a=np.array([[0,1,2],[0,2,3]]);b=np.array([[0,1,3],[1,2,3]])
        colors=[]
        for fs in (a,b):
            normals=m.vertex_normals(ps,fs)
            _,owner=m.p.raster(ps,fs,np.ones(2,bool),(0,0,12,12),3)
            colors.append(m.shade(ps,fs,normals,owner,np.array([0.,0.,1.]),3))
        np.testing.assert_allclose(colors[0],colors[1],atol=1e-14)
        self.assertTrue(np.all(colors[0][0]==0))

    def test_same_normals_shade_identically_under_reversed_winding(self):
        ps=np.array([[2,2,.5],[10,2,.5],[2,10,.5]],float)
        results=[]
        for fs in (np.array([[0,1,2]]),np.array([[0,2,1]])):
            _,owner=m.p.raster(ps,fs,np.ones(1,bool),(0,0,12,12),3)
            results.append(m.shade(ps,fs,m.vertex_normals(ps,fs),owner,np.array([0.,0.,1.]),3))
        np.testing.assert_allclose(results[0],results[1],atol=1e-14)


if __name__=='__main__':unittest.main()
