import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('facing_fit_test',Path(__file__).with_name('normal_fit_control_v2.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class FacingFitTests(unittest.TestCase):
    def test_triangle_facing_matches_world_geometric_normal_and_reference(self):
        ps=np.array([[-1,-1,0],[1,-1,.1],[1,1,.2],[-1,1,0]],float);fs=np.array([[0,1,2],[0,2,3]])
        for faces in (fs,fs[:,::-1]):
            for angle in (.27,3.1,4.7):
                tr=m.p.camera(ps,angle,16);view=m.View(ps,faces,tr)
                triangles=ps[view.ids]
                n=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
                signs=np.where(n@view.forward<0,-1.,1.)
                np.testing.assert_array_equal(view.sign,signs)
                normals=m.s.vertex_normals(ps,faces)
                reference=m.s.filter_rgb(m.shade(view.projected,faces,normals,view.owners,view.forward,3))
                np.testing.assert_allclose(view.render(normals,m.lights()),reference,atol=2e-14)

    def test_shading_normal_horizon_crossing_is_continuous_and_gradient_correct(self):
        ps=np.array([[-1,-1,0],[1,-1,0],[0,1,0]],float);fs=np.array([[0,1,2]])
        tr=m.p.camera(ps,.21,16);view=m.View(ps,fs,tr)
        # Normals deliberately cross the viewer horizon. The geometric side stays fixed.
        tangent=np.cross(view.forward,[0,1,0]);tangent/=np.linalg.norm(tangent)
        left=np.tile(tangent-1e-8*view.forward,(3,1));right=np.tile(tangent+1e-8*view.forward,(3,1))
        self.assertLess(float(np.max(np.abs(view.render(left,m.lights())-view.render(right,m.lights())))),1e-7)
        normals=np.tile(tangent+.025*view.forward,(3,1));normals,_=m.normalized(normals)
        target=view.render(normals,m.lights())*.95
        loss,g=view.loss(normals,target,m.lights());rng=np.random.default_rng(44)
        d=rng.normal(size=normals.shape);eps=1e-6
        finite=(view.loss(normals+eps*d,target,m.lights())[0]-view.loss(normals-eps*d,target,m.lights())[0])/(2*eps)
        np.testing.assert_allclose(np.sum(g*d),finite,atol=2e-7,rtol=2e-6)


if __name__=='__main__':unittest.main()
