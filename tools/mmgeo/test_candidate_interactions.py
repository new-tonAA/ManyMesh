import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('interactions',Path(__file__).with_name('audit_real_candidate_interactions.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RankingTests(unittest.TestCase):
    def test_disjoint_images_never_reverse_and_do_not_repeat_context(self):
        # The old true diagonal falsely compares i+k to k+k here.
        G=np.diag([1.,2.,4.])
        mask=~np.eye(3,dtype=bool)
        result=m.ranking_summary(G,mask,[10,20,30])
        self.assertEqual(result['rankingTriplets'],3)
        self.assertEqual(result['rankingReversals'],0)
        with self.assertRaises(ValueError):m.ranking_summary(G,np.ones((3,3),bool),[10,20,30])

    def test_real_cross_term_reverses_against_distinct_context(self):
        D=np.array([[1.,0.],[0.,2.],[2.,0.]])
        mask=np.zeros((3,3),bool)
        mask[0,2]=mask[2,0]=mask[1,2]=mask[2,1]=True
        result=m.ranking_summary(D@D.T,mask,[10,20,30])
        self.assertEqual(result['rankingTriplets'],1)
        self.assertEqual(result['rankingReversals'],1)
        r=result['largestReversal']
        self.assertEqual(len({r['i'],r['j'],r['context']}),3)
        self.assertAlmostEqual(r['standaloneDifference'],-3.)
        self.assertAlmostEqual(r['jointDifference'],1.)


if __name__=='__main__':unittest.main()
