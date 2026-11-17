#!/usr/bin/env python3
"""Measure filtered-error cross terms for disjoint real collapse candidates.

Uses archived raw sample deltas, exact frozen Gaussian/box filter, same frame only.
This diagnoses candidate interaction; it is not a simplifier or novelty claim.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

p=load('interaction_depth','depth_candidate_pilot.py')


def ranking_summary(G, compatible_mask, ids):
    """Compare distinct alternatives i,j after the same non-repeated context k."""
    if np.any(np.diag(compatible_mask)):
        raise ValueError('self compatibility is forbidden')
    if len(set(ids))!=len(ids):
        raise ValueError('candidate IDs must be unique within a frame')
    e=np.diag(G)
    triples=0;reversals=0;material=0;largest=None
    for k in range(len(ids)):
        admissible=np.flatnonzero(compatible_mask[k]).tolist()
        for ai,i in enumerate(admissible):
            for j in admissible[ai+1:]:
                triples+=1
                standalone=float(e[i]-e[j])
                joint=float((e[i]+e[k]+2*G[i,k])-(e[j]+e[k]+2*G[j,k]))
                if standalone*joint>=0:continue
                reversals+=1
                total=max(float(e[i]+e[j]+2*e[k]),1e-30)
                robust=abs(standalone)>1e-12+1e-6*total and abs(joint)>1e-12+1e-6*total
                material+=int(robust)
                impact=abs(float(2*(G[i,k]-G[j,k])))
                if largest is None or impact>largest['interactionImpact']:
                    largest=dict(i=ids[i],j=ids[j],context=ids[k],
                        standaloneDifference=standalone,jointDifference=joint,
                        interactionImpact=impact,aboveNumericalFloor=robust)
    return dict(rankingTriplets=triples,rankingReversals=reversals,
                rankingReversalsAboveFloor=material,
                rankingReversalFraction=reversals/max(triples,1),largestReversal=largest)


def read_export(path):
    manifest=json.loads(path.with_suffix('.manifest.json').read_text())
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=manifest['exportSha256']:
        raise ValueError('export/manifest hash mismatch')
    rows=[]
    with path.open() as f:
        width,height,scale,sigma,count=f.readline().split()
        width,height,scale,count=map(int,(width,height,scale,count));sigma=float(sigma)
        for _ in range(count):
            frame,cid,n,energy,seconds=f.readline().split()
            events=np.array([list(map(float,f.readline().split())) for _ in range(int(n))]).reshape(-1,4)
            delta=np.zeros((height*scale,width*scale,2),dtype=float)
            if len(events):
                x,y=events[:,:2].astype(int).T
                delta[y,x]=events[:,2:]
            filtered=p.filtered(delta,sigma,scale)
            flat=filtered.reshape(-1)
            np.testing.assert_allclose(np.dot(flat,flat),float(energy),rtol=1e-8,atol=1e-12)
            rows.append(dict(frame=int(frame),id=int(cid),events=int(n),inputSSE=float(energy),
                             residual=flat))
        if f.read().strip():raise ValueError('unexpected trailing export data')
    return (width,height,scale,sigma),manifest,digest,rows


def analyze(capture_path,report_path,export_path,interaction_epsilon):
    positions,faces,candidates=p.load_capture(capture_path)
    report=json.loads(report_path.read_text())
    settings,manifest,export_hash,rows=read_export(export_path)
    if hashlib.sha256(capture_path.read_bytes()).hexdigest()!=manifest['captureSha256']:
        raise ValueError('capture hash differs from candidate deltas')
    if hashlib.sha256(report_path.read_bytes()).hexdigest()!=manifest['reportSha256']:
        raise ValueError('candidate report hash differs from exported deltas')
    if len(rows)!=manifest['cases']:raise ValueError('case count mismatch')
    per_frame=[]
    for frame in sorted(set(r['frame'] for r in rows)):
        pool=[r for r in rows if r['frame']==frame]
        ids=[r['id'] for r in pool]
        D=np.stack([r['residual'] for r in pool])
        G=D@D.T
        e=np.diag(G).copy()
        vertex_sets=[set(faces[np.asarray(candidates[cid]['affected'],dtype=int)].ravel().tolist())
                     for cid in ids]
        compatible_mask=np.zeros((len(pool),len(pool)),dtype=bool)
        for i in range(len(pool)):
            for j in range(i+1,len(pool)):
                compatible_mask[i,j]=compatible_mask[j,i]=not bool(vertex_sets[i]&vertex_sets[j])
        compatible=[];overlap=[];interactions=[]
        for i in range(len(pool)):
            for j in range(i+1,len(pool)):
                if not compatible_mask[i,j]:continue
                compatible.append((i,j))
                cross=float(G[i,j])
                if cross!=0.:overlap.append((i,j,cross))
                denom=max(float(e[i]+e[j]),1e-30)
                relative=abs(2*cross)/denom
                if relative>=interaction_epsilon:interactions.append((i,j,cross,relative))
                # Ranking reversals are measured below against a shared disjoint context.
        ranking=ranking_summary(G,compatible_mask,ids)
        best_independent=min(compatible,key=lambda ij:(e[ij[0]]+e[ij[1]],ij)) if compatible else None
        best_joint=min(compatible,key=lambda ij:(e[ij[0]]+e[ij[1]]+2*G[ij[0],ij[1]],ij)) if compatible else None
        def choice(ij):
            if ij is None:return None
            i,j=ij
            return dict(ids=[ids[i],ids[j]],independentSSE=float(e[i]+e[j]),
                        predictedJointSSE=float(e[i]+e[j]+2*G[i,j]))
        rel=np.array([x[3] for x in interactions],dtype=float)
        per_frame.append(dict(frame=frame,candidates=len(pool),compatiblePairs=len(compatible),
            imageOverlappingPairs=len(overlap),interactionPairs=len(interactions),
            interactionFractionOfCompatible=len(interactions)/max(len(compatible),1),
            relativeInteractionMedian=float(np.median(rel)) if len(rel) else 0.,
            relativeInteractionP95=float(np.percentile(rel,95)) if len(rel) else 0.,
            **ranking,
            independentBestPair=choice(best_independent),jointModelBestPair=choice(best_joint),
            largestInteractions=[dict(ids=[ids[i],ids[j]],cross=cross,relative=ratio)
                for i,j,cross,ratio in sorted(interactions,key=lambda z:z[3],reverse=True)[:10]]))
    return dict(scope='same-view captured candidates, disjoint affected vertex sets, exact linear filter',
        threshold=interaction_epsilon,settings=dict(zip(('width','height','scale','sigma'),settings)),
        hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                (capture_path,report_path,export_path,Path(__file__),Path(p.__file__))},
        frames=per_frame)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('report',type=Path);ap.add_argument('export',type=Path)
    ap.add_argument('--interaction-epsilon',type=float,default=.1)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    if not 0<=a.interaction_epsilon:ap.error('interaction epsilon must be nonnegative')
    result=analyze(a.capture,a.report,a.export,a.interaction_epsilon)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
