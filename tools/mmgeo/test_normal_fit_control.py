import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('normal_fit_test',Path(__file__).with_name('normal_fit_control.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class NormalFitTests(unittest.TestCase):
    def test_filter_matches_reference_and_its_adjoint(self):
        rng=np.random.default_rng(45);raw=rng.normal(size=(24,30,3));low=rng.normal(size=(8,10,3))
        k=m.p.gaussian(.9,3)
        np.testing.assert_allclose(m.filtered(raw,k,3),m.s.filter_rgb(raw),atol=2e-15)
        self.assertAlmostEqual(float(np.sum(m.filtered(raw,k,3)*low)),
                               float(np.sum(raw*m.adjoint(low,k,3))),places=12)

    def test_actual_raster_shading_and_analytic_gradient(self):
        ps=np.array([[-1,-1,0],[1,-1,.1],[1,1,.2],[-1,1,0]],float);fs=np.array([[0,1,2],[0,2,3]])
        transform=m.p.camera(ps,.27,16);view=m.View(ps,fs,transform)
        ns=m.s.vertex_normals(ps,fs)
        expected=m.s.filter_rgb(m.s.shade(view.projected,fs,ns,view.owners,view.forward,3))
        np.testing.assert_allclose(view.render(ns,m.lights()),expected,atol=2e-14)
        problem=m.Problem(ps,fs,[transform],[expected*.94],m.lights())
        x=np.array([.01,-.02,.015,.01,-.012,.016,-.02,.005])
        value,gradient=problem.objective(x);finite=[];eps=1e-6
        for i in range(len(x)):
            delta=np.zeros_like(x);delta[i]=eps
            finite.append((problem.objective(x+delta)[0]-problem.objective(x-delta)[0])/(2*eps))
        np.testing.assert_allclose(gradient,finite,atol=2e-7,rtol=2e-6)

    def test_unit_normal_budget_and_nonlinear_fit_reduces_error(self):
        ps=np.array([[-1,-1,0],[1,-1,.1],[0,1,.2]],float);fs=np.array([[0,1,2]])
        transform=m.p.camera(ps,.21,12);view=m.View(ps,fs,transform)
        ns=m.s.vertex_normals(ps,fs);frame=m.tangent_frame(ns)
        target_ns,_=m.normalized(ns+.12*frame[:,:,0])
        target=view.render(target_ns,m.lights())
        problem=m.Problem(ps,fs,[transform],[target],m.lights());normal,report=problem.fit(80)
        self.assertLess(report['fittedSSE'],report['initialSSE']*.001)
        np.testing.assert_allclose(np.linalg.norm(normal,axis=1),1,atol=1e-14)
        self.assertLessEqual(max(abs(x) for x in report['parameters']),.5)


if __name__=='__main__':unittest.main()
