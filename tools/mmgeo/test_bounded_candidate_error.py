#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

p=load('bound_depth','depth_candidate_pilot.py')
r=load('bound_raster','transactional_raster.py')
b=load('bound_error','bounded_candidate_error.py')


class BoundTests(unittest.TestCase):
    def test_blocks_match_full_loss_with_nonzero_history(self):
        v=np.array([[4,4,.2],[26,4,.2],[4,26,.2],[4,4,.8],[26,4,.8],[4,26,.8]])
        faces=np.array([[0,1,2],[3,4,5]])
        cache=r.FragmentCache(v,faces,32,3)
        edit=cache.propose([1],{})
        rng=np.random.default_rng(13)
        residual=rng.normal(0,.02,(32,32,2))
        rect=(0,0,32,32)
        delta=p.filtered(cache.resolve(rect,edit)-cache.resolve(rect),.9,3)
        expected=float((2*residual*delta+delta*delta).sum())
        for block in (3,8,32):
            result=b.evaluate(cache,edit,residual,rect,.9,3,p.filtered,block_size=block)
            self.assertFalse(result['pruned'])
            self.assertAlmostEqual(result['score'],expected,places=11)
            lazy=b.evaluate(cache,None,residual,rect,.9,3,p.filtered,block_size=block,
                            edit=([1],{}))
            self.assertAlmostEqual(lazy['score'],expected,places=11)
            early=b.evaluate(cache,edit,residual,rect,.9,3,p.filtered,incumbent=-100,
                             block_size=block)
            self.assertLessEqual(early['lower'],expected+1e-11)

    def test_cancellation_may_improve_error(self):
        v=np.array([[4,4,.2],[20,4,.2],[4,20,.2]])
        cache=r.FragmentCache(v,np.array([[0,1,2]]),24,2)
        edit=cache.propose([0],{})
        rect=(0,0,24,24)
        delta=p.filtered(cache.resolve(rect,edit)-cache.resolve(rect),.9,2)
        residual=-delta
        expected=-float(np.square(delta).sum())
        result=b.evaluate(cache,edit,residual,rect,.9,2,p.filtered,incumbent=0,block_size=4)
        self.assertFalse(result['pruned'])
        self.assertAlmostEqual(result['score'],expected,places=11)
        self.assertLess(result['score'],0)


if __name__=='__main__':unittest.main()
