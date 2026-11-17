#!/usr/bin/env python3
"""Frozen scalar normal-offset control at fixed face count. No novelty claim."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

spec=importlib.util.spec_from_file_location('offset_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
ALPHAS=(0.,-.015625,.015625,-.03125,.03125,-.0625,.0625)
FIT=.13+2*np.pi*np.arange(8)/8


def normal_field(positions,faces):
    """Unit area-weighted normal times mean incident EDGE length; freeze all boundaries."""
    field=np.zeros_like(positions);tri=positions[faces]
    normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    for col in range(3):np.add.at(field,faces[:,col],normals)
    lengths=np.linalg.norm(field,axis=1)
    field[lengths>1e-15]/=lengths[lengths>1e-15,None]
    edges=np.sort(np.concatenate((faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]])),axis=1)
    edges,counts=np.unique(edges,axis=0,return_counts=True)
    total=np.zeros(len(positions));degree=np.zeros(len(positions))
    distance=np.linalg.norm(positions[edges[:,0]]-positions[edges[:,1]],axis=1)
    for col in range(2):np.add.at(total,edges[:,col],distance);np.add.at(degree,edges[:,col],1)
    field*=np.divide(total,degree,out=np.zeros_like(total),where=degree>0)[:,None]
    field[np.unique(edges[counts!=2])]=0.
    return field


def geometry_safe(before,after,faces):
    if not np.isfinite(after).all():return False
    a=before[faces];b=after[faces]
    na=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]);nb=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0])
    la=np.linalg.norm(na,axis=1);lb=np.linalg.norm(nb,axis=1)
    if np.any(lb<=1e-15) or np.any(np.einsum('ij,ij->i',na,nb)<.1*la*lb):return False
    def quality(t,l):return 2*np.sqrt(3)*l/np.square(t-np.roll(t,1,axis=1)).sum(axis=(1,2))
    return bool(np.all(quality(b,lb)>=np.minimum(.02,quality(a,la))-1e-12))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('baseline',type=Path)
    ap.add_argument('--ratio',default='0.25');ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();started=time.perf_counter()
    manifest_path=args.baseline/'manifest.json';manifest=json.loads(manifest_path.read_text())
    capture_hash=hashlib.sha256(args.capture.read_bytes()).hexdigest()
    if capture_hash!=manifest['captureSha256']:raise ValueError('source hash differs')
    artifact=manifest['artifacts'][args.ratio];path=Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('baseline mesh differs')
    data=np.load(path);positions=data['positions'];faces=data['triangles']
    world,source,_=p.load_capture(args.capture)
    # Normalize gate tests globally to make fixed epsilon independent of source-unit scale.
    center=(world.min(0)+world.max(0))*.5
    radius=max(float(np.linalg.norm(world-center,axis=1).max()),1e-12)
    normalized=(positions-center)/radius;field=normal_field(normalized,faces)
    variants=[(alpha,positions.copy() if alpha==0 else (normalized+alpha*field)*radius+center) for alpha in ALPHAS
              if geometry_safe(normalized,normalized+alpha*field,faces)]
    fit=[dict(alpha=alpha,total=0.,coverage=0.,depth=0.,views=[]) for alpha,_ in variants]
    for vi,angle in enumerate(FIT):
        transform=p.camera(world,float(angle),128)
        raw,_=p.raster(p.project(world,transform),source,np.ones(len(source),bool),(0,0,128,128),3)
        for row,(alpha,ps) in zip(fit,variants):
            image,_=p.raster(p.project(ps,transform),faces,np.ones(len(faces),bool),(0,0,128,128),3)
            metrics=p.metrics(p.filtered(image-raw,.9,3))
            row['views'].append(dict(angle=float(angle),**metrics))
            for channel in ('total','coverage','depth'):row[channel]+=metrics[channel]
        print(args.capture.stem,'offset fit',vi,flush=True)
    # Zero is first for deterministic ties. Test views never participate in selection.
    selected=min(range(len(fit)),key=lambda i:fit[i]['total'])
    alpha,ps=variants[selected];args.out.mkdir(parents=True,exist_ok=True)
    mesh_path=args.out/'mesh.npz';np.savez_compressed(mesh_path,positions=ps,triangles=faces)
    report=dict(scope='scalar normal displacement, fixed topology and actual face count; development assets',
        baselinePolicy=manifest.get('policy','qem'),ratio=args.ratio,
        selectedAlpha=alpha,selectedFit=fit[selected],baselineFit=fit[0],
        candidateAlphas=ALPHAS,geometryRejected=[alpha for alpha in ALPHAS if alpha not in [a for a,_ in variants]],
        fit=fit,hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                       (args.capture,manifest_path,path,Path(__file__),Path(p.__file__))},
        seconds=time.perf_counter()-started)
    (args.out/'fit.json').write_text(json.dumps(report,indent=2)+'\n')
    # Compatible format for the existing full-orbit evaluator.
    output=dict(scope='normal-offset control; full attribute/global intersection gates absent',
                captureSha256=capture_hash,fitReportSha256=hashlib.sha256((args.out/'fit.json').read_bytes()).hexdigest(),
                artifacts={args.ratio:dict(path=str(mesh_path),sha256=hashlib.sha256(mesh_path.read_bytes()).hexdigest(),triangles=len(faces))})
    (args.out/'manifest.json').write_text(json.dumps(output,indent=2)+'\n')
    print(args.capture.stem,'selected alpha',alpha,'fit reduction',1-fit[selected]['total']/fit[0]['total'],flush=True)


if __name__=='__main__':main()
