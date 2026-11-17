#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module
    spec.loader.exec_module(module); return module

r=load('transactional_raster','transactional_raster.py')
p=load('depth_candidate_pilot','depth_candidate_pilot.py')


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.vertices=np.array([[1,1,.2],[15,1,.2],[1,15,.2],
                                [1,1,.8],[15,1,.8],[1,15,.8]],dtype=float)
        self.faces=np.array([[0,1,2],[3,4,5]])
        self.cache=r.FragmentCache(self.vertices,self.faces,16,3)

    def test_delete_restores_hidden_depth_and_undo(self):
        initial=self.cache.resolve((0,0,16,16))
        edit=self.cache.propose([1],{})
        expected,_=p.raster(self.vertices,self.faces,np.array([True,False]),(0,0,16,16),3)
        np.testing.assert_allclose(self.cache.resolve((0,0,16,16),edit),expected,atol=1e-14)
        self.cache.commit(edit)
        np.testing.assert_allclose(self.cache.resolve((0,0,16,16)),expected,atol=1e-14)
        self.cache.undo(edit)
        np.testing.assert_array_equal(self.cache.resolve((0,0,16,16)),initial)

    def test_new_tiles_and_stale_version(self):
        changed=self.vertices.copy(); changed[3:,:2]+=7
        edit=self.cache.propose([1],{1:changed[self.faces[1]]})
        stale=self.cache.propose([0],{})
        expected,_=p.raster(changed,self.faces,np.ones(2,bool),(0,0,16,16),3)
        np.testing.assert_allclose(self.cache.resolve((0,0,16,16),edit),expected,atol=1e-14)
        for rect in ((0,0,16,16),(3,5,11,13)):
            np.testing.assert_allclose(self.cache.resolve_edit(rect,[1],{1:changed[self.faces[1]]}),
                                       self.cache.resolve(rect,edit),atol=1e-14)
        self.cache.commit(edit)
        with self.assertRaises(ValueError): self.cache.commit(stale)
        with self.assertRaises(ValueError): self.cache.resolve((0,0,16,16),stale)
        self.cache.undo(edit)
        with self.assertRaises(ValueError): self.cache.undo(edit)

    def test_arbitrarily_deep_layers(self):
        vertices=np.concatenate([self.vertices[:3]+[0,0,i*.01] for i in range(20)])
        faces=np.arange(60).reshape(-1,3)
        cache=r.FragmentCache(vertices,faces,16,2)
        edit=cache.propose(range(1,20),{})
        expected,_=p.raster(vertices,faces,np.arange(20)==0,(0,0,16,16),2)
        np.testing.assert_allclose(cache.resolve((0,0,16,16),edit),expected,atol=1e-14)

    def test_multiple_committed_edits_match_new_geometry(self):
        vertices=self.vertices.copy()
        vertices[3:,:2]+=2
        first=self.cache.propose([1],{1:vertices[self.faces[1]]})
        self.cache.commit(first)
        vertices[:3,2]=.95
        second=self.cache.propose([0],{0:vertices[self.faces[0]]})
        self.cache.commit(second)
        expected,_=p.raster(vertices,self.faces,np.ones(2,bool),(0,0,16,16),3)
        np.testing.assert_allclose(self.cache.resolve((0,0,16,16)),expected,atol=1e-14)
        with self.assertRaises(ValueError): self.cache.undo(first)
        self.cache.undo(second)
        vertices[:3,2]=self.vertices[:3,2]
        expected,_=p.raster(vertices,self.faces,np.ones(2,bool),(0,0,16,16),3)
        np.testing.assert_allclose(self.cache.resolve((0,0,16,16)),expected,atol=1e-14)

    def test_equal_depth_and_tile_crossing(self):
        self.vertices[3:,2]=.2
        cache=r.FragmentCache(self.vertices,self.faces,16,3,tile_size=2)
        edit=cache.propose([1],{})
        expected,_=p.raster(self.vertices,self.faces,np.array([True,False]),(0,0,16,16),3)
        np.testing.assert_allclose(cache.resolve((0,0,16,16),edit),expected,atol=1e-14)

    def test_random_transaction_sequence_against_full_redraw(self):
        rng=np.random.default_rng(20261114)
        vertices=np.column_stack((rng.uniform(-4,20,(36,2)),rng.uniform(0,1,36)))
        faces=np.arange(36).reshape(-1,3)
        alive=np.ones(12,dtype=bool)
        cache=r.FragmentCache(vertices,faces,16,2,tile_size=3)
        for step in range(24):
            face=step%12
            changed=vertices.copy(); updated_alive=alive.copy()
            if step%4==0:
                updated_alive[face]=False; replacements={}
            else:
                changed[faces[face],:2]+=rng.uniform(-2,2,(3,2))
                changed[faces[face],2]=rng.uniform(0,1,3)
                updated_alive[face]=True
                replacements={face:changed[faces[face]]}
            edit=cache.propose([face],replacements)
            expected,_=p.raster(changed,faces,updated_alive,(0,0,16,16),2)
            np.testing.assert_allclose(cache.resolve((0,0,16,16),edit),expected,atol=1e-12)
            cache.commit(edit)
            np.testing.assert_allclose(cache.resolve((0,0,16,16)),expected,atol=1e-12)
            if step%3==0:
                cache.undo(edit)
                expected,_=p.raster(vertices,faces,alive,(0,0,16,16),2)
                np.testing.assert_allclose(cache.resolve((0,0,16,16)),expected,atol=1e-12)
            else:
                vertices=changed; alive=updated_alive

    def test_foreign_and_outside_replacement_rejected(self):
        edit=self.cache.propose([1],{})
        other=r.FragmentCache(self.vertices,self.faces,16,3)
        with self.assertRaises(ValueError): other.commit(edit)
        with self.assertRaises(ValueError): self.cache.propose([0],{1:self.vertices[:3]})


if __name__=='__main__': unittest.main()
