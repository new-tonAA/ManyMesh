#!/usr/bin/env python3
"""Joint world-space placement constraints, frozen fitting/evaluation view split.

All candidate IDs from the existing real-asset report, not selected from single-view successes.
Original placement is fallback; fitting acceptance is NOT independent evidence of improvement.
This remains a geometry-only placement experiment without full Corner attribute validation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np

spec=importlib.util.spec_from_file_location('single_placement',Path(__file__).with_name('evaluate_raster_placement.py'))
single=importlib.util.module_from_spec(spec);sys.modules[spec.name]=single;spec.loader.exec_module(single)
p=single.p;q=single.q
FIT=(-.12,0.,.12)
TEST=(-.27,-.06,.06,.29)


def context(world,faces,c,angle,size,scale,sigma,limit):
    transform=p.camera(world,angle,size);projected=p.project(world,transform)
    rect=p.support(projected,faces,c,transform,size,6)
    changed,cf,valid=p.edited_geometry(projected,faces,c,transform)
    # A full source image is shared by all proposals for this candidate/view (not free).
    original,_=p.raster(projected,faces,np.ones(len(faces),bool),(0,0,size,size),scale)
    seed=changed[c['keep']].copy();x0,y0,x1,y1=rect
    raw,owner=p.raster(changed,cf,valid,rect,scale)
    before=original[y0*scale:y1*scale,x0*scale:x1*scale]
    metric=p.metrics(p.filtered(raw-before,sigma,scale))
    ys,xs=np.nonzero(np.isin(owner,c['affected']) & (before[:,:,0]>0))
    indices=np.unique(np.linspace(0,len(xs)-1,min(limit,len(xs))).astype(int)) if len(xs) else []
    equations=[];max_error=0.
    J=(np.diag([size*.43,-size*.43,.5])@transform[2])/transform[1]
    for index in indices:
        y,x=int(ys[index]),int(xs[index]);tri=cf[int(owner[y,x])]
        moving=np.flatnonzero(tri==c['keep'])
        if len(moving)!=1:continue
        j=int(moving[0]);b=changed[tri[(j+1)%3]];cc=changed[tri[(j+2)%3]]
        sample=np.array([x0+(x+.5)/scale,y0+(y+.5)/scale]);depth=float(before[y,x,1])
        coeff,base=q.affine_terms(b,cc,sample,seed)
        sign=1 if base[0]>=0 else -1;coeff*=sign;base*=sign
        max_error=max(max_error,abs(base[4]/base[0]-depth))
        equations.append((coeff@J,base,depth))
    orientations=[]
    for f in c['affected']:
        if not valid[f]:continue
        tri=cf[f];j=int(np.flatnonzero(tri==c['keep'])[0])
        coeff,base=q.affine_terms(changed[tri[(j+1)%3]],changed[tri[(j+2)%3]],[0,0],seed)
        sign=1 if base[0]>=0 else -1
        orientations.append((-sign*coeff[0]@J,sign*base[0]-1e-10))
    trust=np.maximum(np.abs(projected[c['keep']]-projected[c['remove']]),[.1,.1,1e-5])*.5
    return dict(transform=transform,projected=projected,changed=changed,faces=cf,valid=valid,
                original=original,rect=rect,metric=metric,equations=equations,
                maxError=max_error,orientations=orientations,J=J,trust=trust)


def joint_system(contexts,fraction):
    matrices=[];bounds=[]
    for ctx in contexts:
        eps=max(ctx['maxError']*fraction,1e-12)
        for coeff,base,depth in ctx['equations']:
            for i in range(4):
                matrices.append(-coeff[i]);bounds.append(base[i]-(1e-10 if i==0 else 0.))
            matrices.extend(((depth-eps)*coeff[0]-coeff[4],coeff[4]-(depth+eps)*coeff[0]))
            bounds.extend((base[4]-(depth-eps)*base[0],(depth+eps)*base[0]-base[4]))
        for a,b in ctx['orientations']:matrices.append(a);bounds.append(b)
        matrices.extend(ctx['J']);bounds.extend(ctx['trust'])
        matrices.extend(-ctx['J']);bounds.extend(ctx['trust'])
    return np.asarray(matrices).reshape(-1,3),np.asarray(bounds)


def evaluate(ctx,c,target,size,scale,sigma):
    trial=dict(c,target=np.asarray(target).tolist())
    rect=p.support(ctx['projected'],ctx['faces'],trial,ctx['transform'],size,6)
    a=ctx['rect'];rect=(min(a[0],rect[0]),min(a[1],rect[1]),max(a[2],rect[2]),max(a[3],rect[3]))
    cp=ctx['changed'].copy();cp[c['keep']]=p.project([target],ctx['transform'])[0]
    raw,_=p.raster(cp,ctx['faces'],ctx['valid'],rect,scale)
    x0,y0,x1,y1=rect
    residual=p.filtered(raw-ctx['original'][y0*scale:y1*scale,x0*scale:x1*scale],sigma,scale)
    return p.metrics(residual)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path);parser.add_argument('report',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=64)
    args=parser.parse_args()
    if args.samples<1:parser.error('positive sample count required')
    world,faces,cs=p.load_capture(args.capture);report=json.loads(args.report.read_text())
    size=report['size'];scale=report['scale'];sigma=report['sigma']
    result=dict(scope='joint view constraints; development assets; not independent asset generalization',
                fittingOffsets=FIT,testOffsets=TEST,seedFallback=True,
                hashes=dict(capture=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                            script=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),frames=[])
    for frame in report['frames']:
        rows=[]
        for obs in frame['candidates']:
            if not obs['baselineVisible']:continue
            c=cs[obs['id']];seed=np.asarray(c['target']);start=time.perf_counter()
            contexts=[context(world,faces,c,frame['angle']+off,size,scale,sigma,args.samples) for off in FIT]
            baseline=[ctx['metric'] for ctx in contexts];best=sum(m['total'] for m in baseline)
            allowance=max(np.linalg.norm(seed-world[i]) for i in (c['remove'],c['keep']))
            balls=[(world[i]-seed,allowance) for i in (c['remove'],c['keep'])]
            target=seed.copy();accepted=False;feasible=0
            for fraction in (.75,.5,.25):
                if max(ctx['maxError'] for ctx in contexts)<1e-12:break
                A,rhs=joint_system(contexts,fraction)
                delta=q.project_halfspaces(A,rhs,[0,0,0],max_sweeps=160,tolerance=1e-10,balls=balls)
                if delta is None:continue
                feasible+=1;candidate=seed+delta
                if not single.geometric_guard(world,contexts[0]['faces'],contexts[0]['valid'],c,candidate):continue
                metrics=[evaluate(ctx,c,candidate,size,scale,sigma) for ctx in contexts]
                # No fitting view may regress in coverage OR depth; sum must strictly improve.
                safe=all(m[ch]<=b[ch]+1e-14 for m,b in zip(metrics,baseline) for ch in ('coverage','depth'))
                score=sum(m['total'] for m in metrics)
                if safe and score<best-1e-14:target=candidate;accepted=True;best=score
            fitting_seconds=time.perf_counter()-start
            tests=[]
            if accepted:
                for off in TEST:
                    ctx=context(world,faces,c,frame['angle']+off,size,scale,sigma,args.samples)
                    tests.append(dict(offset=off,seed=ctx['metric'],result=evaluate(ctx,c,target,size,scale,sigma)))
            rows.append(dict(id=obs['id'],accepted=accepted,target=target.tolist(),
                seedFitError=sum(m['total'] for m in baseline),resultFitError=best,
                feasibleWitnesses=feasible,fittingSeconds=fitting_seconds,tests=tests,
                fallbackUntestedViewsIdentical=not accepted))
        result['frames'].append(dict(frame=frame['frame'],angle=frame['angle'],candidates=rows))
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(args.capture.stem,frame['frame'],'accepted',sum(r['accepted'] for r in rows),flush=True)


if __name__=='__main__':main()
