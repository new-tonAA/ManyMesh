#!/usr/bin/env python3
"""Analytic smooth-normal fitting control; fixed geometry, actual raster ownership.

Classical inverse-rendering baseline. Finite nonlinear fitting is NOT a global optimum or bound.
"""
import importlib.util
from pathlib import Path

import numpy as np
from scipy.ndimage import convolve1d
from scipy.optimize import minimize

spec=importlib.util.spec_from_file_location('fit_shading',Path(__file__).with_name('evaluate_shading_controls.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
p=s.p
LIGHTS=(((.4,.7,1.),(.65,.52,.42)),((-1.,.2,.3),(.18,.26,.38)),((.3,-.7,-.5),(.13,.1,.08)))


def lights(rotation=0.):
    c,t=np.cos(rotation),np.sin(rotation)
    R=np.array([[c,0,t],[0,1,0],[-t,0,c]])
    return [(R@np.asarray(d)/np.linalg.norm(d),np.asarray(w)) for d,w in LIGHTS]


def blur(image,kernel):
    return convolve1d(convolve1d(image,kernel,axis=0,mode='constant',cval=0.),
                      kernel,axis=1,mode='constant',cval=0.)


def filtered(image,kernel,scale):
    h,w,c=image.shape
    return blur(image,kernel).reshape(h//scale,scale,w//scale,scale,c).mean(axis=(1,3))


def adjoint(image,kernel,scale):
    # D averages each box, so D^T repeats with 1/scale^2; symmetric zero-padded G^T=G.
    return blur(np.repeat(np.repeat(image,scale,axis=0),scale,axis=1)/(scale*scale),kernel)


def normalized(vector):
    length=np.linalg.norm(vector,axis=-1)
    return vector/np.maximum(length[...,None],1e-15),length


def normalization_backward(gradient,unit,length):
    return (gradient-unit*np.einsum('ij,ij->i',gradient,unit)[:,None])/np.maximum(length[:,None],1e-15)


def tangent_frame(normals):
    axis=np.eye(3)[np.argmin(np.abs(normals),axis=1)]
    a,_=normalized(np.cross(normals,axis));b=np.cross(normals,a)
    return np.stack((a,b),axis=2)


class View:
    def __init__(self,world,faces,transform,scale=3,sigma=.9):
        self.scale=scale;self.size=transform[3];self.forward=transform[2][2]
        projected=p.project(world,transform)
        self.geometry_raw,owners=p.raster(projected,faces,np.ones(len(faces),bool),(0,0,self.size,self.size),scale)
        self.owners=owners;self.projected=projected
        self.yy,self.xx=np.nonzero(owners>=0);self.ids=faces[owners[self.yy,self.xx]]
        tri=projected[self.ids];a=tri[:,0];b=tri[:,1]-a;c=tri[:,2]-a
        d=np.column_stack(((self.xx+.5)/scale,(self.yy+.5)/scale))-a[:,:2]
        area=b[:,0]*c[:,1]-b[:,1]*c[:,0]
        u=(d[:,0]*c[:,1]-d[:,1]*c[:,0])/area
        v=(b[:,0]*d[:,1]-b[:,1]*d[:,0])/area
        self.weights=np.column_stack((1-u-v,u,v));self.kernel=p.gaussian(sigma,scale)
        self.raw_shape=(*owners.shape,3);self.vertices=len(world)

    def render(self,normals,lighting,backward=False):
        m=np.einsum('ij,ijk->ik',self.weights,normals[self.ids]);n,length=normalized(m)
        sign=np.where(np.einsum('ij,j->i',n,self.forward)<0,-1.,1.)
        oriented=n*sign[:,None];color=np.full_like(oriented,.06)
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
        return image,(n,length,sign,derivative)

    def loss(self,normals,target,lighting):
        image,cache=self.render(normals,lighting,True);residual=image-target
        raw_gradient=adjoint(2*residual,self.kernel,self.scale)[self.yy,self.xx]
        n,length,sign,derivative=cache
        grad=np.einsum('ic,icd->id',raw_gradient,derivative)*sign[:,None]
        grad=normalization_backward(grad,n,length)
        result=np.zeros((self.vertices,3))
        for i in range(3):np.add.at(result,self.ids[:,i],grad*self.weights[:,i,None])
        return float(np.square(residual).sum()),result


class Problem:
    def __init__(self,world,faces,transforms,targets,lighting):
        self.used=np.unique(faces);self.initial=s.vertex_normals(world,faces)
        self.frame=tangent_frame(self.initial[self.used]);self.views=[View(world,faces,t) for t in transforms]
        self.targets=targets;self.lighting=lighting;self.evaluations=0;self.trace=[]

    def normals(self,x):
        raw=self.initial[self.used]+np.einsum('ijk,ik->ij',self.frame,x.reshape(-1,2))
        unit,length=normalized(raw);normals=self.initial.copy();normals[self.used]=unit
        return normals,(unit,length)

    def objective(self,x):
        normals,(unit,length)=self.normals(x);value=0.;gradient=np.zeros_like(normals)
        for view,target in zip(self.views,self.targets):
            loss,grad=view.loss(normals,target,self.lighting);value+=loss;gradient+=grad
        grad=normalization_backward(gradient[self.used],unit,length)
        result=np.einsum('ijk,ij->ik',self.frame,grad).ravel()
        self.evaluations+=1;self.trace.append(value)
        return value,result

    def fit(self,iterations=200):
        # Equal box-constrained tangent budget, two scalars per surviving vertex. Max tilt 35.27 deg.
        x0=np.zeros(2*len(self.used));start=self.objective(x0)[0]
        result=minimize(self.objective,x0,jac=True,method='L-BFGS-B',bounds=[(-.5,.5)]*len(x0),
                        options=dict(maxiter=iterations,maxls=30,ftol=1e-11,gtol=1e-5,maxcor=10))
        normals,_=self.normals(result.x)
        # Re-evaluate instead of trusting a stale optimizer score.
        end,gradient=self.objective(result.x)
        if end>start+1e-10:raise ValueError('fitting increased objective')
        bound=np.abs(result.x)>=.5-1e-10
        projected=gradient.copy()
        projected[(result.x<=-.5+1e-10)&(gradient>0)]=0
        projected[(result.x>=.5-1e-10)&(gradient<0)]=0
        report=dict(initialSSE=start,fittedSSE=end,success=bool(result.success),message=str(result.message),
            iterations=int(result.nit),evaluations=self.evaluations,trace=self.trace,
            projectedGradientMax=float(np.max(np.abs(projected))),boundScalars=int(bound.sum()),
            attributeScalars=len(x0),parameters=result.x.tolist())
        return normals,report
