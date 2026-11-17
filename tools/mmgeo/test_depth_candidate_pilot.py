#!/usr/bin/env python3
"""Independent small-scene checks for the depth diagnostic."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('pilot',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class DepthPilotTests(unittest.TestCase):
    def test_frontmost_and_disocclusion(self):
        vertices=np.array([[2,2,.2],[14,2,.2],[2,14,.2],
                           [2,2,.8],[14,2,.8],[2,14,.8]],dtype=float)
        triangles=np.array([[0,1,2],[3,4,5]])
        raw,owner=p.raster(vertices,triangles,np.array([True,True]),(0,0,16,16),2)
        self.assertEqual(owner[8,8],1)
        self.assertAlmostEqual(raw[8,8,1],.8)
        behind,_=p.raster(vertices,triangles,np.array([True,False]),(0,0,16,16),2)
        self.assertAlmostEqual(behind[8,8,1],.2)
        self.assertEqual(behind[8,8,0],1.)

    def test_patch_and_full_match_including_unchanged_occluder(self):
        vertices=np.array([[10,10,.2],[20,10,.2],[10,20,.2],
                           [0,0,.9],[32,0,.9],[0,12,.9]],dtype=float)
        faces=np.array([[0,1,2],[3,4,5]])
        alive=np.ones(2,dtype=bool)
        raw,_=p.raster(vertices,faces,alive,(0,0,32,32),3)
        changed=vertices.copy(); changed[0]=[11,11,.7]
        residual,_=p.patch_residual(changed,faces,alive,(4,4,26,26),3,.9,raw)
        other,_=p.raster(changed,faces,alive,(0,0,32,32),3)
        expected=p.filtered(other,.9,3)-p.filtered(raw,.9,3)
        actual=np.zeros_like(expected); actual[4:26,4:26]=residual
        np.testing.assert_allclose(actual,expected,atol=1e-14)

    def test_projection_uses_fixed_frame(self):
        vertices=np.array([[-1,-2,-3],[1,2,3],[.2,.4,.8]],dtype=float)
        transform=p.camera(vertices,2.13,128)
        together=p.project(vertices,transform)
        individually=np.concatenate([p.project([v],transform) for v in vertices])
        np.testing.assert_allclose(together,individually,atol=1e-14)
        center=transform[0]
        np.testing.assert_allclose(p.project([center],transform)[0],[64,64,.5])

    def test_sketch_dimensions_and_energy_bound(self):
        rng=np.random.default_rng(42)
        residual=rng.normal(size=(12,15,2))
        basis=p.dct_basis(12,15)
        coeff=p.sketch(residual,basis)
        self.assertEqual(coeff.shape,(32,))
        self.assertLessEqual(float(np.square(coeff).sum()),float(np.square(residual).sum())+1e-10)
        gram=np.einsum('khw,jhw->kj',basis[0],basis[0])
        for i in range(32):
            for j in range(32):
                if basis[1][i]==basis[1][j]:
                    self.assertAlmostEqual(gram[i,j],float(i==j),places=12)

    def test_hidden_face_can_become_visible(self):
        vertices=np.array([[2,2,.2],[14,2,.2],[2,14,.2],
                           [2,2,.8],[14,2,.8],[2,14,.8]],dtype=float)
        faces=np.array([[0,1,2],[3,4,5]])
        alive=np.ones(2,dtype=bool)
        before,owner=p.raster(vertices,faces,alive,(0,0,16,16),2)
        self.assertNotIn(0,np.unique(owner))
        vertices[:3,2]=.9
        after,new_owner=p.raster(vertices,faces,alive,(0,0,16,16),2)
        self.assertIn(0,np.unique(new_owner))
        self.assertGreater(np.square(after-before).sum(),0)

    def test_filter_halo_on_viewport_edge(self):
        vertices=np.array([[-4,0,.5],[7,0,.5],[-4,10,.5]])
        faces=np.array([[0,1,2]]); alive=np.array([True])
        before,_=p.raster(vertices,faces,alive,(0,0,24,24),3)
        vertices[1,0]=6
        residual,_=p.patch_residual(vertices,faces,alive,(0,0,14,17),3,.9,before)
        after,_=p.raster(vertices,faces,alive,(0,0,24,24),3)
        full=p.filtered(after,.9,3)-p.filtered(before,.9,3)
        partial=np.zeros_like(full); partial[:17,:14]=residual
        np.testing.assert_allclose(full,partial,atol=1e-14)

    def test_empty_and_offscreen(self):
        vertices=np.array([[-5,-5,.2],[-2,-5,.2],[-5,-2,.2]])
        raw,owner=p.raster(vertices,np.array([[0,1,2]]),np.array([True]),(0,0,16,16),2)
        self.assertTrue(np.all(owner==-1))
        self.assertTrue(np.all(raw==0))


if __name__=='__main__':
    unittest.main()
