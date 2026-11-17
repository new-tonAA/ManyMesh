#!/usr/bin/env python3
"""Normal-fitting control with geometry-based two-sided orientation.

Separate renderer contract from v1: interpolated shading normals no longer select the side.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np

spec=importlib.util.spec_from_file_location('facing_fit_base',Path(__file__).with_name('normal_fit_control.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
p=base.p
lights=base.lights
normalized=base.normalized
tangent_frame=base.tangent_frame
filtered=base.filtered


def shade(projected,faces,normals,owners,forward,scale):
    # Independent reference, same loop structure as the previous controlled renderer.
    rgb=np.zeros((*owners.shape,3));yy,xx=np.nonzero(owners>=0)
    if not len(xx):return rgb
    ids=faces[owners[yy,xx]];tri=projected[ids]
    a=tri[:,0];b=tri[:,1]-a;c=tri[:,2]-a
    d=np.column_stack(((xx+.5)/scale,(yy+.5)/scale))-a[:,:2]
    area=b[:,0]*c[:,1]-b[:,1]*c[:,0]
    u=(d[:,0]*c[:,1]-d[:,1]*c[:,0])/area
    v=(b[:,0]*d[:,1]-b[:,1]*d[:,0])/area
    n=(1-u-v)[:,None]*normals[ids[:,0]]+u[:,None]*normals[ids[:,1]]+v[:,None]*normals[ids[:,2]]
    n/=np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-15)
    # For this source camera transform, signed projected area has sign(n_geometric dot forward).
    n[area<0]*=-1
    color=np.full_like(n,.06)
    for light,power in lights():
        half=light+forward;half/=max(np.linalg.norm(half),1e-15)
        color+=np.maximum(0,n@light)[:,None]*power+.2*np.maximum(0,n@half)[:,None]**64
    rgb[yy,xx]=color
    return rgb


s=SimpleNamespace(vertex_normals=base.s.vertex_normals,filter_rgb=base.s.filter_rgb,
                  shade=shade,__file__=__file__)


class View(base.View):
    def __init__(self,world,faces,transform,scale=3,sigma=.9):
        super().__init__(world,faces,transform,scale,sigma)
        tri=self.projected[self.ids];b=tri[:,1]-tri[:,0];c=tri[:,2]-tri[:,0]
        self.sign=np.where(b[:,0]*c[:,1]-b[:,1]*c[:,0]<0,-1.,1.)

    def render(self,normals,lighting,backward=False):
        m=np.einsum('ij,ijk->ik',self.weights,normals[self.ids]);n,length=normalized(m)
        oriented=n*self.sign[:,None];color=np.full_like(oriented,.06)
        derivative=np.zeros((len(n),3,3)) if backward else None
        for light,power in lighting:
            half,_=normalized(light+self.forward)
            dl=np.einsum('ij,j->i',oriented,light);dh=np.einsum('ij,j->i',oriented,half)
            color+=np.maximum(dl,0)[:,None]*power+.2*np.maximum(dh,0)[:,None]**64
            if backward:
                derivative+=(dl>0)[:,None,None]*power[None,:,None]*light[None,None,:]
                derivative+=12.8*np.maximum(dh,0)[:,None,None]**63*half[None,None,:]
        raw=np.zeros(self.raw_shape);raw[self.yy,self.xx]=color
        image=filtered(raw,self.kernel,self.scale)
        if not backward:return image
        return image,(n,length,self.sign,derivative)


class Problem(base.Problem):
    def __init__(self,world,faces,transforms,targets,lighting):
        self.used=np.unique(faces);self.initial=s.vertex_normals(world,faces)
        self.frame=tangent_frame(self.initial[self.used]);self.views=[View(world,faces,t) for t in transforms]
        self.targets=targets;self.lighting=lighting;self.evaluations=0;self.trace=[]
