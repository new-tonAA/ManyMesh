#!/usr/bin/env python3
"""Fixed-correspondence inverse-raster placement pilot on captured real legal edges.

Does NOT replace Corner's production placement/gates. Only positions are proposed. Sampled
constraints are proposals, full patch metrics and explicit geometric guards decide acceptance.
No material/UV validation is provided: geometry-only results cannot be enabled in production.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import math
import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

p=load('placement_depth','depth_candidate_pilot.py')
q=load('placement_constraint','raster_placement_constraints.py')


def triangle_quality(vertices):
    a,b,c=vertices
    edges=np.array([b-a,c-b,a-c])
    normal=np.cross(b-a,c-a);area2=np.linalg.norm(normal)
    denom=np.square(edges).sum()
    return (2*math.sqrt(3)*area2/denom if denom>0 else 0.),normal


def inverse_project(target,transform):
    center,radius,basis,size=transform
    local=np.array([(target[0]/size-.5)/.43,(.5-target[1]/size)/.43,(target[2]-.5)/.5])
    return center+radius*(local@basis)


def geometric_guard(world,faces,valid,c,target):
    """No new flips, min quality .02, displacement no larger than seed's worst endpoint move.

    This is NOT the complete Corner attribute/surface gate and does not prove nonintersection.
    """
    seed=np.asarray(c['target'])
    edge_a,edge_b=world[c['remove']],world[c['keep']]
    allowance=max(np.linalg.norm(seed-edge_a),np.linalg.norm(seed-edge_b))
    if max(np.linalg.norm(target-edge_a),np.linalg.norm(target-edge_b))>allowance+1e-10:
        return False
    for f in c['affected']:
        if not valid[f]:continue
        before=world[faces[f]].copy();before[faces[f]==c['keep']]=seed
        after=world[faces[f]].copy();after[faces[f]==c['keep']]=target
        qb,nb=triangle_quality(before);qa,na=triangle_quality(after)
        if qa<min(.02,qb)-1e-12:return False
        if np.dot(nb,na)<.1*np.linalg.norm(nb)*np.linalg.norm(na):return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('report',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--samples',type=int,default=64)
    args=parser.parse_args()
    if args.samples<1:parser.error('positive sample count required')
    world,faces,candidates=p.load_capture(args.capture)
    report=json.loads(args.report.read_text());size=report['size'];scale=report['scale'];sigma=report['sigma']
    result=dict(scope='real development assets; fixed seed correspondence; sampled placement proposal',
                warning='geometry/depth only; no UV/material or continuous surface guarantee',frames=[])
    for frame in report['frames']:
        transform=p.camera(world,frame['angle'],size);projected=p.project(world,transform)
        full=(0,0,size,size)
        original_raw,_=p.raster(projected,faces,np.ones(len(faces),bool),full,scale)
        rows=[]
        for observation in frame['candidates']:
            if not observation['baselineVisible']:continue
            cid=observation['id'];c=candidates[cid];rect=tuple(observation['rect'])
            changed,cf,valid=p.edited_geometry(projected,faces,c,transform)
            seed=changed[c['keep']].copy();x0,y0,x1,y1=rect
            start=time.perf_counter()
            raw,owner=p.raster(changed,cf,valid,rect,scale)
            before=original_raw[y0*scale:y1*scale,x0*scale:x1*scale]
            seed_metric=p.metrics(p.filtered(raw-before,sigma,scale))
            ys,xs=np.nonzero(np.isin(owner,c['affected']) & (before[:,:,0]>0))
            selected=np.unique(np.linspace(0,len(xs)-1,min(args.samples,len(xs))).astype(int)) if len(xs) else []
            data=[]
            for index in selected:
                y,x=int(ys[index]),int(xs[index]);f=int(owner[y,x]);tri=cf[f]
                moving=np.flatnonzero(tri==c['keep'])
                if len(moving)!=1:continue
                j=int(moving[0]);b=changed[tri[(j+1)%3]];cc=changed[tri[(j+2)%3]]
                sample=np.array([x0+(x+.5)/scale,y0+(y+.5)/scale])
                data.append((b,cc,sample,float(before[y,x,1])))
            seed_max=max((abs(q.plane_terms(seed,b,cc,s)[4]/q.plane_terms(seed,b,cc,s)[0]-z)
                          for b,cc,s,z in data),default=0.)
            accepted=False;attempts=0;feasible=0;geometry_rejects=0;best=seed_metric
            target=seed.copy(); proposed_world=np.asarray(c['target'])
            # Predetermined epsilon fractions, not fitted to measured gains.
            for fraction in (.75,.5,.25):
                if not data or seed_max<1e-12:break
                matrices=[];bounds=[]
                for b,cc,s,z in data:
                    A,rhs=q.constraints(b,cc,[s],seed,[z],seed_max*fraction)
                    matrices.append(A);bounds.append(rhs)
                # Position trust region in normalized screen/depth, keeps coverage outside patch bounded.
                keep=projected[c['keep']];remove=projected[c['remove']]
                trust=np.maximum(np.abs(keep-remove),[.1,.1,1e-5])*.5
                matrices.append(np.r_[np.eye(3),-np.eye(3)]);bounds.append(np.r_[trust,trust])
                # Maintain orientation of EVERY surviving affected triangle, not just sampled owners.
                for f in c['affected']:
                    if not valid[f]:continue
                    tri=cf[f];idx=np.flatnonzero(tri==c['keep'])
                    if len(idx)!=1:continue
                    j=int(idx[0]);b=changed[tri[(j+1)%3]];cc=changed[tri[(j+2)%3]]
                    coeff,base=q.affine_terms(b,cc,[0,0],seed)
                    sign=1 if base[0]>=0 else -1
                    matrices.append((-sign*coeff[0]).reshape(1,3));bounds.append(np.array([sign*base[0]-1e-10]))
                A=np.concatenate(matrices);rhs=np.concatenate(bounds);attempts+=1
                # Solve in world displacement coordinates, so endpoint displacement balls are
                # convex Euclidean constraints instead of an after-the-fact placement rejection.
                origin_world=np.asarray(c['target'])
                J=(np.diag([size*.43,-size*.43,.5])@transform[2])/transform[1]
                allowance=max(np.linalg.norm(origin_world-world[c['remove']]),
                              np.linalg.norm(origin_world-world[c['keep']]))
                balls=[(world[index]-origin_world,allowance) for index in (c['remove'],c['keep'])]
                world_delta=q.project_halfspaces(A@J,rhs,[0,0,0],max_sweeps=160,
                                                tolerance=1e-10,balls=balls)
                if world_delta is None:continue
                feasible+=1;trial_world=origin_world+world_delta
                trial=p.project([trial_world],transform)[0]
                if not geometric_guard(world,cf,valid,c,trial_world):
                    geometry_rejects+=1;continue
                # Conservative support must also include the new target, not only the seed.
                trial_c=dict(c,target=trial_world.tolist())
                trial_rect=p.support(projected,faces,trial_c,transform,size,6)
                union=(min(x0,trial_rect[0]),min(y0,trial_rect[1]),max(x1,trial_rect[2]),max(y1,trial_rect[3]))
                cp=changed.copy();cp[c['keep']]=trial
                traw,_=p.raster(cp,cf,valid,union,scale)
                ux0,uy0,ux1,uy1=union
                metric=p.metrics(p.filtered(traw-original_raw[uy0*scale:uy1*scale,ux0*scale:ux1*scale],sigma,scale))
                if metric['total']<best['total']-1e-14 and metric['coverage']<=seed_metric['coverage']+1e-14:
                    accepted=True;target=trial;best=metric;proposed_world=trial_world
            elapsed=time.perf_counter()-start
            rows.append(dict(id=cid,seed=seed_metric,result=best,accepted=accepted,samples=len(data),
                             attempts=attempts,feasibleWitnesses=feasible,geometryRejected=geometry_rejects,
                             seedMaxDepthError=seed_max,seconds=elapsed,target=proposed_world.tolist(),
                             projectionRoundTripMax=float(np.max(np.abs(p.project([proposed_world],transform)[0]-target)))))
        result['frames'].append(dict(frame=frame['frame'],angle=frame['angle'],candidates=rows))
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(args.capture.stem,frame['frame'],'accepted',sum(r['accepted'] for r in rows),'of',len(rows),flush=True)


if __name__=='__main__':main()
