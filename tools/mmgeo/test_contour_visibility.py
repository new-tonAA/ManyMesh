import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('visibility',Path(__file__).with_name('source_contour_visibility.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class VisibilityTests(unittest.TestCase):
    def test_triangle_hides_known_half_of_segment_only_when_in_front(self):
        a=np.array([0.,0.,0.]);b=np.array([1.,0.,0.])
        tri=np.array([[[.5,-1,1],[1.5,-1,1],[.5,1,1]]],float)
        self.assertAlmostEqual(m.visible_fraction(a,b,tri),.5,places=9)
        tri[:,:,2]=-1
        self.assertEqual(m.visible_fraction(a,b,tri),1.)

    def test_union_and_incident_exclusion(self):
        a=np.array([0.,0.,0.]);b=np.array([1.,0.,0.])
        tri=np.array([[[.2,-1,1],[2.2,-1,1],[.2,1,1]]],float)
        self.assertAlmostEqual(m.visible_fraction(a,b,np.concatenate((tri,tri))),.2,places=9)
        self.assertEqual(m.visible_fraction(a,b,tri,[0]),1.)

    def test_coplanar_surface_is_not_an_occluder(self):
        tri=np.array([[[-2,-2,0],[2,-2,0],[0,2,0]]],float)
        self.assertEqual(m.visible_fraction(np.array([0.,0.,0.]),np.array([.1,0.,0.]),tri),1.)

    def test_depth_crossing_splits_visible_interval(self):
        # Triangle covers the whole edge; its plane z=x-.6 crosses the edge at t=.6.
        tri=np.array([[[-2,-2,-2.6],[2,-2,1.4],[0,2,-.6]]],float)
        self.assertAlmostEqual(m.visible_fraction(np.array([0.,0.,0.]),
                                                 np.array([1.,0.,0.]),tri),.6,places=8)

    def test_disjoint_hidden_intervals_are_not_filled_between(self):
        triangles=[]
        for left,right in ((.2,.4),(.6,.8)):
            triangles.append([[left,-1,1],[2*right-left,-1,1],[left,1,1]])
        self.assertAlmostEqual(m.visible_fraction(np.array([0.,0.,0.]),
            np.array([1.,0.,0.]),np.array(triangles)),.6,places=8)


if __name__=='__main__':unittest.main()
