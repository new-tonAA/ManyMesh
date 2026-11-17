#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('constraints',Path(__file__).with_name('raster_placement_constraints.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


class PlacementTests(unittest.TestCase):
    def test_numerators_affine_for_random_positions(self):
        rng=np.random.default_rng(913)
        for _ in range(500):
            b,c,origin=rng.normal(size=(3,3));sample=rng.normal(size=2)
            A,base=p.affine_terms(b,c,sample,origin)
            delta=rng.normal(size=3)
            np.testing.assert_allclose(A@delta+base,p.plane_terms(origin+delta,b,c,sample),
                                       atol=1e-12,rtol=1e-12)

    def test_halfspaces_equivalent_to_direct_raster_tests(self):
        rng=np.random.default_rng(41)
        origin=np.array([0.,0.,.4]);b=np.array([4.,0.,.7]);c=np.array([0.,4.,.1])
        samples=np.array([[.5,.5],[1.5,.5],[.5,1.5]])
        depths=np.array([p.plane_terms(origin,b,c,s)[4]/p.plane_terms(origin,b,c,s)[0] for s in samples])
        A,rhs=p.constraints(b,c,samples,origin,depths,.02)
        for _ in range(500):
            delta=rng.normal(0,.2,3)
            valid=True
            for s,z in zip(samples,depths):
                terms=p.plane_terms(origin+delta,b,c,s)
                valid &= terms[0]>=1e-10 and np.all(terms[1:4]>=0)
                valid &= abs(terms[4]/terms[0]-z)<=.02
            self.assertEqual(bool(np.all(A@delta<=rhs)),bool(valid))

    def test_halfspaces_and_endpoint_balls(self):
        A=np.array([[-1.,0,0],[0,-1.,0]])
        rhs=np.array([-.2,-.2])
        balls=[(np.zeros(3),1.),(np.array([.5,0,0]),.6)]
        x=p.project_halfspaces(A,rhs,[2,-3,0],balls=balls)
        self.assertIsNotNone(x)
        self.assertTrue(np.all(A@x<=rhs+1e-9))
        for center,radius in balls:self.assertLessEqual(np.linalg.norm(x-center),radius+1e-9)

    def test_world_to_multiview_affine_jacobians(self):
        # Independent affine cameras, including flipped screen-y and unequal depth scale.
        rng=np.random.default_rng(314)
        world=rng.normal(size=(3,3))
        for angle in (-.12,0.,.12,.29):
            rotation=np.array([[np.cos(angle),0,np.sin(angle)],
                               [0,1,0],[-np.sin(angle),0,np.cos(angle)]])
            J=np.diag([20.,-20.,.5])@rotation
            offset=np.array([64.,64.,.5])
            projected=world@J.T+offset
            origin,b,c=projected
            sample=(origin[:2]+b[:2]+c[:2])/3
            coeff,base=p.affine_terms(b,c,sample,origin)
            for _ in range(20):
                delta=rng.normal(0,.01,3)
                actual=p.plane_terms((world[0]+delta)@J.T+offset,b,c,sample)
                np.testing.assert_allclose(coeff@J@delta+base,actual,atol=1e-10,rtol=1e-10)

    def test_feasible_witness_respects_full_system(self):
        A=np.array([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]],float)
        rhs=np.ones(6)
        x=p.project_halfspaces(A,rhs,[4,-3,2])
        self.assertIsNotNone(x);self.assertTrue(np.all(A@x<=rhs+1e-9))
        self.assertIsNone(p.project_halfspaces(np.array([[0.,0.,0.]]),np.array([-1.]),[0,0,0]))


if __name__=='__main__':unittest.main()
