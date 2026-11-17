#!/usr/bin/env python3
"""Halfspaces for one moving triangle vertex at fixed sample ownership and depth tolerance.

Not a full simplifier. A cell fixes signs of edge functions; it does NOT make correspondence,
visibility changes, connectivity or all placements globally convex. Depth tolerance times area
would be bilinear if tolerance were optimized jointly: use fixed tolerance or outer bisection.
"""
import numpy as np


def cross2(a,b): return a[0]*b[1]-a[1]*b[0]


def plane_terms(moving,b,c,sample):
    """Return area, barycentric numerators and depth numerator; all affine in moving xyz."""
    a=np.asarray(moving);b=np.asarray(b);c=np.asarray(c);s=np.asarray(sample)
    area=cross2(b[:2]-a[:2],c[:2]-a[:2])
    wa=cross2(b[:2]-s,c[:2]-s)
    wb=cross2(c[:2]-s,a[:2]-s)
    wc=cross2(a[:2]-s,b[:2]-s)
    numerator=wa*a[2]+wb*b[2]+wc*c[2]
    return np.array([area,wa,wb,wc,numerator])


def affine_terms(b,c,sample,origin):
    base=plane_terms(origin,b,c,sample)
    columns=[]
    for axis in range(3):
        point=np.asarray(origin,dtype=float).copy();point[axis]+=1
        columns.append(plane_terms(point,b,c,sample)-base)
    # Functions operate on displacement from origin for numerical conditioning.
    return np.column_stack(columns),base


def constraints(b,c,samples,origin,depths,tolerance,min_area=1e-10):
    """Build A delta <= rhs, preserving inside coverage and depth intervals for assigned samples."""
    if tolerance<0 or not np.isfinite(tolerance): raise ValueError('finite nonnegative tolerance')
    A=[];rhs=[]
    for sample,depth in zip(samples,depths):
        coeff,base=affine_terms(b,c,sample,origin)
        sign=1. if base[0]>=0 else -1.
        coeff*=sign;base*=sign
        # area >= min_area, all three barycentric numerators >= 0.
        for index in range(4):
            A.append(-coeff[index]);rhs.append(base[index]-(min_area if index==0 else 0.))
        # (depth-eps)*area <= numerator <= (depth+eps)*area.
        low=depth-tolerance;high=depth+tolerance
        A.extend((low*coeff[0]-coeff[4],coeff[4]-high*coeff[0]))
        rhs.extend((base[4]-low*base[0],high*base[0]-base[4]))
    return np.asarray(A).reshape(-1,3),np.asarray(rhs)


def project_halfspaces(A,rhs,seed,max_sweeps=300,tolerance=1e-9,balls=()):
    """Dependency-free alternating projections. Feasible witness only, NOT infeasibility proof.

    Returns None on exhausted iteration budget. Does not claim nearest-point optimality.
    """
    x=np.asarray(seed,dtype=float).copy()
    if not np.isfinite(A).all() or not np.isfinite(rhs).all() or not np.isfinite(x).all():
        raise ValueError('finite coefficients required')
    norms=np.einsum('ij,ij->i',A,A)
    if np.any((norms<1e-28)&(rhs < -tolerance)):return None
    def balls_valid(point):
        return all(np.linalg.norm(point-center)<=radius+tolerance for center,radius in balls)
    for center,radius in balls:
        if not np.isfinite(center).all() or not np.isfinite(radius) or radius<0:
            raise ValueError('finite ball with nonnegative radius required')
    for _ in range(max_sweeps):
        violations=A@x-rhs
        if np.max(violations,initial=-np.inf)<=tolerance and balls_valid(x):return x
        for i in np.flatnonzero(violations>tolerance):
            if norms[i]>1e-28:
                violation=float(A[i]@x-rhs[i])
                if violation>0:x-=violation/norms[i]*A[i]
        for center,radius in balls:
            offset=x-center;distance=np.linalg.norm(offset)
            if distance>radius:x=center+offset*(radius/distance)
    return x if np.max(A@x-rhs,initial=-np.inf)<=tolerance and balls_valid(x) else None
