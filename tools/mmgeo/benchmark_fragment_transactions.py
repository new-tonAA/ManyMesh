#!/usr/bin/env python3
"""Compare exact sampled fragment transactions against a spatially indexed patch redraw.

Uses the previous frozen real-asset candidate trajectory. No new candidate selection and no
quality oracle in the mechanism. Includes setup, persistent arrays and amortization threshold.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time
import hashlib
import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m

p=load('depth_pilot','depth_candidate_pilot.py')
r=load('fragment_transactions','transactional_raster.py')


class SpatialFaces:
    def __init__(self,projected,faces,size,tile=8):
        self.tile=tile; self.cols=(size+tile-1)//tile; self.bins={}
        xy=projected[faces][:,:,:2]
        lo=np.maximum(0,np.floor(xy.min(1)/tile).astype(int))
        hi=np.minimum(self.cols-1,np.floor(xy.max(1)/tile).astype(int))
        for face in range(len(faces)):
            for y in range(lo[face,1],hi[face,1]+1):
                for x in range(lo[face,0],hi[face,0]+1):
                    self.bins.setdefault(y*self.cols+x,set()).add(face)

    def query(self,rect,affected):
        x0,y0,x1,y1=rect; ids=set(affected)
        for y in range(y0//self.tile,(y1-1)//self.tile+1):
            for x in range(x0//self.tile,(x1-1)//self.tile+1):
                ids.update(self.bins.get(y*self.cols+x,()))
        return np.asarray(sorted(ids),dtype=int)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--frames',type=int,default=6)
    parser.add_argument('--batch',type=int,default=0,
                        help='sample this many distinct visible-support candidates, no oracle filtering')
    args=parser.parse_args()
    old=json.loads(args.report.read_text())
    positions,faces,candidates=p.load_capture(args.capture)
    size=old['size']; scale=old['scale']; sigma=old['sigma']
    result=dict(scope='exact sampled depth/coverage; Python CPU; static-camera transaction batch',
                reportSha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                implementationSha256=hashlib.sha256(Path(r.__file__).read_bytes()).hexdigest(),
                baseline='spatially indexed patch rerasterization; same filter and samples',frames=[])
    for frame in old['frames'][:args.frames]:
        transform=p.camera(positions,frame['angle'],size); projected=p.project(positions,transform)
        start=time.perf_counter(); spatial=SpatialFaces(projected,faces,size)
        spatial_setup=time.perf_counter()-start
        start=time.perf_counter(); cache=r.FragmentCache(projected,faces,size,scale)
        cache_setup=time.perf_counter()-start
        start=time.perf_counter(); base=cache.resolve((0,0,size,size))
        resolve_setup=time.perf_counter()-start
        start=time.perf_counter()
        reference,owners=p.raster(projected,faces,np.ones(len(faces),bool),(0,0,size,size),scale)
        reference_setup=time.perf_counter()-start
        np.testing.assert_allclose(base,reference,atol=1e-12)
        observations=frame['candidates']
        if args.batch:
            visible=set(np.unique(owners[owners>=0]).tolist())
            eligible=sorted((c['priority'],i) for i,c in enumerate(candidates)
                            if visible.intersection(c['affected']))
            chosen=np.unique(np.linspace(0,len(eligible)-1,min(args.batch,len(eligible))).astype(int))
            observations=[]
            for index in chosen:
                cid=eligible[index][1]
                rect=p.support(projected,faces,candidates[cid],transform,size,math.ceil(4*sigma)+2)
                if rect is not None: observations.append(dict(id=cid,rect=rect))
        row=dict(frame=frame['frame'],cacheSetupSeconds=cache_setup,
                 spatialSetupSeconds=spatial_setup,resolveSetupSeconds=resolve_setup,
                 referenceSetupSeconds=reference_setup,cacheArrayBytes=cache.array_bytes,
                 fragments=cache.reference_fragments,candidates=[])
        for observation in observations:
            cid=observation['id']; c=candidates[cid]; rect=tuple(observation['rect'])
            changed,changed_faces,valid=p.edited_geometry(projected,faces,c,transform)
            affected=c['affected']
            replacements={int(f):changed[changed_faces[f]] for f in affected if valid[f]}
            x0,y0,x1,y1=rect
            original=base[y0*scale:y1*scale,x0*scale:x1*scale]
            def redraw():
                ids=spatial.query(rect,affected)
                raw,_=p.raster(changed,changed_faces[ids],valid[ids],rect,scale)
                return p.filtered(raw-original,sigma,scale)
            def transaction():
                proposal=cache.propose(affected,replacements)
                raw=cache.resolve(rect,proposal)
                return p.filtered(raw-original,sigma,scale),proposal
            # Untimed warm-up and result check; timed repetitions alternate order.
            truth=redraw(); predicted,proposal=transaction()
            difference=float(np.max(np.abs(truth-predicted)))
            if difference>1e-12: raise AssertionError(('raster mismatch',cid,difference))
            if 'metrics' in observation:
                np.testing.assert_allclose(p.metrics(truth)['total'],observation['metrics']['total'],
                                           rtol=1e-8,atol=1e-12)
            times={'redraw':[],'transaction':[]}
            for repeat in range(4):
                order=('redraw','transaction') if repeat%2==0 else ('transaction','redraw')
                for mode in order:
                    start=time.perf_counter()
                    if mode=='redraw': measured=redraw()
                    else: measured,_=transaction()
                    times[mode].append(time.perf_counter()-start)
                    if not np.isfinite(measured).all(): raise AssertionError('invalid output')
            # Actually execute then undo the edit; this tests stateful behavior, not just scores.
            start=time.perf_counter(); cache.commit(proposal); commit=time.perf_counter()-start
            committed=cache.resolve(rect)
            np.testing.assert_allclose(p.filtered(committed-original,sigma,scale),truth,atol=1e-12)
            start=time.perf_counter(); cache.undo(proposal); undo=time.perf_counter()-start
            np.testing.assert_allclose(cache.resolve(rect),original,atol=1e-12)
            row['candidates'].append(dict(id=cid,referenceError=p.metrics(truth),
                redrawSeconds=statistics.median(times['redraw']),
                transactionSeconds=statistics.median(times['transaction']),
                commitSeconds=commit,undoSeconds=undo,maxDifference=difference,
                replacementFaces=len(replacements),affectedFaces=len(affected),
                transientArrayBytes=sum(t.nbytes for t in proposal.after.values())))
        redraw_total=sum(c['redrawSeconds'] for c in row['candidates'])
        transaction_total=sum(c['transactionSeconds'] for c in row['candidates'])
        count=len(row['candidates']); saving=(redraw_total-transaction_total)/max(count,1)
        # Two distinct costs: if the original image already exists, transaction construction is
        # extra. From scratch, each method also needs its own original-image setup.
        row['batchRedrawSeconds']=redraw_total+spatial_setup
        row['batchTransactionSeconds']=transaction_total+cache_setup+resolve_setup
        row['fromScratchRedrawSeconds']=row['batchRedrawSeconds']+reference_setup
        row['fromScratchTransactionSeconds']=row['batchTransactionSeconds']
        row['breakEvenCandidates']=max(0,cache_setup+resolve_setup-spatial_setup)/saving if saving>0 else None
        result['frames'].append(row)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(args.capture.stem,frame['frame'],'query ratio',redraw_total/transaction_total,
              'total ratio',row['batchRedrawSeconds']/row['batchTransactionSeconds'],
              'break even',row['breakEvenCandidates'],flush=True)


if __name__=='__main__': main()
