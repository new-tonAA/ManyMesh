#!/usr/bin/env python3
"""Classical hidden-line visibility intervals for a frozen source-contour control.

Clips an edge parameter against triangle coverage and frontmost-depth inequalities.
No sampling predictor, no novelty claim; source-only, orthographic, opaque/two-sided.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def visible_fraction(a,b,triangles,exclude=()):
    """Triangles and edge endpoints are projected xyz; larger z is nearer."""
    tri=np.asarray(triangles)
    lo=tri[:,:,:2].min(axis=1);hi=tri[:,:,:2].max(axis=1)
    active=np.all(hi>=np.minimum(a[:2],b[:2])-1e-12,axis=1)&np.all(lo<=np.maximum(a[:2],b[:2])+1e-12,axis=1)
    active[list(exclude)]=False
    tri=tri[active]
    if not len(tri):return 1.
    x=tri[:,1]-tri[:,0];y=tri[:,2]-tri[:,0]
    area=x[:,0]*y[:,1]-x[:,1]*y[:,0]
    valid=np.abs(area)>1e-14
    tri,x,y,area=tri[valid],x[valid],y[valid],area[valid]
    if not len(tri):return 1.
    def terms(point):
        d=point-tri[:,0]
        u=(d[:,0]*y[:,1]-d[:,1]*y[:,0])/area
        v=(x[:,0]*d[:,1]-x[:,1]*d[:,0])/area
        # Coverage plus nearer-depth constraint; depth tolerance is in normalized source units.
        gap=tri[:,0,2]+u*x[:,2]+v*y[:,2]-point[2]-2e-10
        return np.stack((1-u-v+1e-12,u+1e-12,v+1e-12,gap),axis=1)
    base=terms(a);slope=terms(b)-base
    lower=np.zeros(len(tri));upper=np.ones(len(tri));possible=np.ones(len(tri),bool)
    for k in range(4):
        s=slope[:,k];q=base[:,k]
        rising=s>1e-15;falling=s< -1e-15
        lower[rising]=np.maximum(lower[rising],-q[rising]/s[rising])
        upper[falling]=np.minimum(upper[falling],-q[falling]/s[falling])
        possible&=rising|falling|(q>=0)
    intervals=sorted(zip(lower[possible&(upper>lower)],upper[possible&(upper>lower)]))
    hidden=0.;last=0.
    for left,right in intervals:
        left=max(left,last)
        if right>left:hidden+=right-left;last=right
    return float(np.clip(1-hidden,0.,1.))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();source=json.loads(args.capture.read_text());started=time.perf_counter()
    world=[];faces=[];vo=0;fo=0;units=[]
    for unit in source['units']:
        ps=np.asarray(unit['positions'],float).reshape(-1,3)
        fs=np.asarray(unit['triangles'],int).reshape(-1,3)
        units.append((ps,fs,vo,fo));world.extend(ps);faces.extend(fs+vo)
        vo+=len(ps);fo+=len(fs)
    world=np.asarray(world);faces=np.asarray(faces)
    center=(world.min(0)+world.max(0))*.5
    radius=max(np.linalg.norm(world-center,axis=1).max(),1e-12)
    world=(world-center)/radius
    angles=.13+2*np.pi*np.arange(8)/8
    directions=np.array([[np.sin(a),.37,np.cos(a)] for a in angles])
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    projected=[]
    for forward in directions:
        right=np.cross(forward,[0,1,0]);right/=np.linalg.norm(right)
        up=np.cross(right,forward);projected.append(world@np.stack((right,up,forward)).T)
    result=[]
    for ui,(ps,fs,vo,fo) in enumerate(units):
        if not len(fs):result.append(dict(weights={},matchedStrength=0.,constraints=0));continue
        tri=ps[fs];normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        edges={}
        for fi,tri in enumerate(fs):
            for u,v in zip(tri,np.roll(tri,-1)):edges.setdefault(tuple(sorted((int(u),int(v)))),[]).append(fi)
        weights={};total=kept=0.;hidden=partial=0
        for (u,v),incident in sorted(edges.items()):
            if len(incident)!=2:continue
            length=float(np.linalg.norm(ps[v]-ps[u]))
            for di,direction in enumerate(directions):
                signs=normals[incident]@direction
                if signs[0]*signs[1]>=0:continue
                proj=projected[di]
                weight=visible_fraction(proj[vo+u],proj[vo+v],proj[faces],np.array(incident)+fo)
                weights[f'{u},{v},{di}']=weight
                total+=length;kept+=length*weight
                hidden+=int(weight<1e-8);partial+=int(1e-8<=weight<1-1e-8)
        result.append(dict(weights=weights,matchedStrength=kept/total if total else 0.,
                           constraints=len(weights),hidden=hidden,partial=partial,
                           sourceLength=total,visibleLength=kept))
        print(args.capture.stem,ui,'constraints',len(weights),'hidden',hidden,'partial',partial,flush=True)
    report=dict(scope='exact piecewise-linear source segment visibility with finite floating tolerances',
                captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                angles=angles.tolist(),directions=directions.tolist(),units=result,
                seconds=time.perf_counter()-started)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
