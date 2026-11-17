import importlib.util
from pathlib import Path
import unittest

import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

m=load('progressive_image_test','progressive_image_baseline.py')
fixture=load('progressive_fixture','test_progressive_geometry.py')


class ProgressiveImageTests(unittest.TestCase):
    def setup_solver(self,pool):
        ps,fs=fixture.torus();ps=np.asarray(ps);fs=np.asarray(fs)
        scene=m.Scene(ps,fs,size=24,scale=2)
        solver=m.ImageQEM(ps,fs,scene,0,0,np.zeros(3),1.,pool)
        return ps,fs,scene,solver

    def test_single_candidate_pool_reproduces_qem_geometry(self):
        ps,fs,scene,solver=self.setup_solver(1)
        plain=m.q.ProgressiveQEM(ps,fs)
        plain.advance(len(fs)//2);solver.advance(len(fs)//2)
        np.testing.assert_array_equal(plain.p,solver.p)
        np.testing.assert_array_equal(plain.f,solver.f)
        np.testing.assert_array_equal(plain.alive,solver.alive)
        scene.verify()

    def test_cumulative_patch_scores_match_full_rerender_after_real_history(self):
        ps,fs,scene,solver=self.setup_solver(4)
        solver.advance(3*len(fs)//4)
        scene.verify()
        self.assertGreater(sum(np.square(v['residual']).sum() for v in scene.views),0.)
        score,entry,bundle=solver.select()
        _,u,v,_,_,_,point=entry
        world=scene.world.copy();faces=scene.faces.copy()
        world[u]=point;faces[faces==v]=u
        valid=(faces[:,0]!=faces[:,1])&(faces[:,1]!=faces[:,2])&(faces[:,2]!=faces[:,0])
        expected=0.
        for view in scene.views:
            raw,_=m.p.raster(m.p.project(world,view['transform']),faces,valid,(0,0,24,24),2)
            residual=m.p.filtered(raw-view['original'],.9,2)
            expected+=float(np.square(residual).sum()-np.square(view['residual']).sum())
        self.assertAlmostEqual(score,expected,places=10)
        self.assertLessEqual(scene.evaluations,4*(len(solver.actions)+1))


if __name__=='__main__':unittest.main()
