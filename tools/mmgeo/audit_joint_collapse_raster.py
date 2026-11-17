#!/usr/bin/env python3
"""Actually apply selected independent collapses and audit the additive image model.

Selected strongest examples are a disconfirmation set, never a population quality benchmark.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

spec=importlib.util.spec_from_file_location('joint_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('audit',type=Path)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    world,faces,cs=p.load_capture(args.capture)
    audit=json.loads(args.audit.read_text())
    if hashlib.sha256(args.capture.read_bytes()).hexdigest()!=audit['hashes'][str(args.capture)]:
        raise ValueError('capture hash mismatch')
    size=audit['settings']['width'];scale=audit['settings']['scale'];sigma=audit['settings']['sigma']
    results=[];started=time.perf_counter()
    for frame in audit['frames']:
        transform=p.camera(world,float(np.linspace(2.13,2.48,6)[frame['frame']]),size)
        projected=p.project(world,transform)
        pairs={tuple(sorted(item['ids'])) for item in frame['largestInteractions']}
        for key in ('independentBestPair','jointModelBestPair'):
            if frame.get(key):pairs.add(tuple(sorted(frame[key]['ids'])))
        reversal=frame['largestReversal']
        if reversal:
            if len({reversal['i'],reversal['j'],reversal['context']})!=3:
                raise ValueError('invalid repeated-context reversal')
            pairs.update(tuple(sorted((reversal[k],reversal['context']))) for k in ('i','j'))
        rows=[]
        for i,j in sorted(pairs):
            supports=[set(faces[cs[k]['affected']].ravel()) for k in (i,j)]
            if supports[0]&supports[1]:raise ValueError('overlapping geometry support')
            rects=[p.support(projected,faces,cs[k],transform,size,int(np.ceil(4*sigma))+2) for k in (i,j)]
            rect=(min(r[0] for r in rects),min(r[1] for r in rects),
                  max(r[2] for r in rects),max(r[3] for r in rects))
            base,_=p.raster(projected,faces,np.ones(len(faces),bool),rect,scale)
            def render(ids):
                cp=projected.copy();cf=faces.copy()
                for cid in ids:
                    c=cs[cid];cf[cf==c['remove']]=c['keep']
                    cp[c['keep']]=p.project([c['target']],transform)[0]
                valid=(cf[:,0]!=cf[:,1])&(cf[:,1]!=cf[:,2])&(cf[:,2]!=cf[:,0])
                raw,_=p.raster(cp,cf,valid,rect,scale)
                return raw-base,int(np.count_nonzero(~valid))
            a,na=render([i]);b,nb=render([j]);joint,njoint=render([i,j])
            if njoint!=na+nb:raise ValueError('nonadditive deleted face count')
            fa=p.filtered(a,sigma,scale);fb=p.filtered(b,sigma,scale)
            fj=p.filtered(joint,sigma,scale);pred=fa+fb
            residual=joint-a-b
            rows.append(dict(ids=[i,j],removedTriangles=njoint,
                standaloneSSE=[float(np.square(fa).sum()),float(np.square(fb).sum())],
                predictedJointSSE=float(np.square(pred).sum()),actualJointSSE=float(np.square(fj).sum()),
                maxRawNonadditivity=float(np.abs(residual).max(initial=0)),
                nonadditiveSamples=int(np.count_nonzero(np.any(abs(residual)>1e-12,axis=-1))),
                filteredModelError=float(np.square(fj-pred).sum())))
        rank=None
        if reversal:
            r={tuple(row['ids']):row for row in rows}
            ai=r[tuple(sorted((reversal['i'],reversal['context'])))]['actualJointSSE']
            aj=r[tuple(sorted((reversal['j'],reversal['context'])))]['actualJointSSE']
            rank=dict(**reversal,actualJointDifference=ai-aj,
                      reversalSurvives=bool(reversal['standaloneDifference']*(ai-aj)<0))
        lookup={tuple(row['ids']):row for row in rows}
        selection={key:lookup[tuple(sorted(frame[key]['ids']))] for key in
                   ('independentBestPair','jointModelBestPair') if frame.get(key)}
        results.append(dict(frame=frame['frame'],pairs=rows,reversal=rank,selection=selection))
        print(args.capture.stem,frame['frame'],'joint pairs',len(rows),flush=True)
    result=dict(scope='selected strongest cases; local disjointness only, no global intersection/attribute proof',
                hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                        (args.capture,args.audit,Path(__file__),Path(p.__file__))},
                seconds=time.perf_counter()-started,frames=results)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
