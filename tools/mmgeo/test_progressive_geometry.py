import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('progressive',Path(__file__).with_name('progressive_geometry_baseline.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def torus(n=12,k=8):
    positions=[];faces=[]
    for i in range(n):
        a=2*np.pi*i/n
        for j in range(k):
            b=2*np.pi*j/k;r=1+.3*np.cos(b)
            positions.append([r*np.cos(a),r*np.sin(a),.3*np.sin(b)])
            u=i*k+j;v=((i+1)%n)*k+j;w=i*k+(j+1)%k;z=((i+1)%n)*k+(j+1)%k
            faces.extend([[u,v,z],[u,z,w]])
    return positions,faces


class ProgressiveTests(unittest.TestCase):
    def test_source_contour_penalty_is_positive_semidefinite_and_optional(self):
        ps,fs=torus()
        plain=m.ProgressiveQEM(ps,fs)
        contour=m.ProgressiveQEM(ps,fs,[[0.,.37,1.],[1.,.37,0.]])
        zero=m.ProgressiveQEM(ps,fs,[[0.,.37,1.]],contour_strength=0.)
        np.testing.assert_array_equal(plain.q,zero.q)
        added=contour.q-plain.q
        self.assertGreater(contour.contour_constraints,0)
        self.assertGreater(np.linalg.norm(added),0.)
        self.assertGreaterEqual(np.linalg.eigvalsh(added).min(),-1e-12)
        with self.assertRaises(ValueError):m.ProgressiveQEM(ps,fs,[[0,0,0]])

    def test_visibility_weight_limits_reproduce_full_and_absent_constraints(self):
        ps,fs=torus()
        keys={f'{min(u,v)},{max(u,v)},0':1. for tri in fs
              for u,v in zip(tri,np.roll(tri,-1))}
        full=m.ProgressiveQEM(ps,fs,[[0.,.37,1.]])
        visible=m.ProgressiveQEM(ps,fs,[[0.,.37,1.]],contour_weights=keys)
        np.testing.assert_array_equal(full.q,visible.q)
        zero=m.ProgressiveQEM(ps,fs,[[0.,.37,1.]],
                             contour_weights={key:0. for key in keys})
        plain=m.ProgressiveQEM(ps,fs)
        np.testing.assert_array_equal(zero.q,plain.q)

    def test_regenerated_closed_mesh_keeps_topology_and_adjacency_at_large_reduction(self):
        ps,fs=torus();s=m.ProgressiveQEM(ps,fs)
        for fraction in (.75,.5,.25):
            count=s.advance(int(len(fs)*fraction));faces=s.f[s.alive]
            self.assertLessEqual(count,int(len(fs)*fraction))
            edges={};keys=set()
            for tri in faces:
                self.assertEqual(len(set(tri)),3)
                key=tuple(sorted(tri));self.assertNotIn(key,keys);keys.add(key)
                for u,v in zip(tri,np.roll(tri,-1)):
                    e=tuple(sorted((u,v)));edges[e]=edges.get(e,0)+1
            self.assertTrue(all(c==2 for c in edges.values()))
            self.assertEqual(len(set(faces.ravel()))-len(edges)+len(faces),0)
            for v in range(len(s.p)):
                expected=set(np.flatnonzero(s.alive & np.any(s.f==v,axis=1)))
                self.assertEqual(s.inc[v],expected)
        self.assertGreater(len(s.actions),len(ps)//2)

    def test_tetrahedron_cannot_collapse_into_duplicate_faces(self):
        s=m.ProgressiveQEM([[1,1,1],[1,-1,-1],[-1,1,-1],[-1,-1,1]],
                           [[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
        self.assertEqual(s.advance(2),4)

    def test_boundary_locked_patch_reports_unreachable_target(self):
        s=m.ProgressiveQEM([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],[[0,1,2],[0,2,3]])
        self.assertEqual(s.locked,{0,1,2,3})
        self.assertEqual(s.advance(1),2)


if __name__=='__main__':unittest.main()
