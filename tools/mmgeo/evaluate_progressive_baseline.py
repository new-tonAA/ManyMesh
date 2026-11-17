#!/usr/bin/env python3
"""Full-view image and topology measurements at substantial actual mesh reductions."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('progressive_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def topology(ps,fs):
    if fs.min()<0 or fs.max()>=len(ps):raise ValueError('invalid output indices')
    keys=np.sort(fs,axis=1)
    if np.any(keys[:,1:]==keys[:,:-1]):raise ValueError('repeated vertex in triangle')
    duplicates=len(keys)-len(np.unique(keys,axis=0))
    edges=np.sort(np.concatenate([fs[:,[0,1]],fs[:,[1,2]],fs[:,[2,0]]]),axis=1)
    unique,counts=np.unique(edges,axis=0,return_counts=True)
    tri=ps[fs];areas=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)
    return dict(vertices=len(np.unique(fs)),triangles=len(fs),edges=len(unique),
                euler=len(np.unique(fs))-len(unique)+len(fs),boundaryEdges=int(np.sum(counts==1)),
                nonmanifoldEdges=int(np.sum(counts>2)),duplicateFaces=duplicates,
                zeroAreaFaces=int(np.sum(areas<=1e-15)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('directory',type=Path)
    a=ap.parse_args();manifest=json.loads((a.directory/'manifest.json').read_text())
    if hashlib.sha256(a.capture.read_bytes()).hexdigest()!=manifest['captureSha256']:
        raise ValueError('source differs from run')
    world,faces,_=p.load_capture(a.capture)
    meshes={}
    for ratio,artifact in manifest['artifacts'].items():
        path=Path(artifact['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('mesh hash mismatch')
        data=np.load(path);meshes[ratio]=(data['positions'],data['triangles'])
    stats={r:dict(actualRatio=len(fs)/len(faces),topology=topology(ps,fs),views=[])
           for r,(ps,fs) in meshes.items()}
    source_stats=topology(world,faces)
    for vi,angle in enumerate(np.linspace(0,2*np.pi,12,endpoint=False)):
        transform=p.camera(world,float(angle),128)
        raw,_=p.raster(p.project(world,transform),faces,np.ones(len(faces),bool),(0,0,128,128),3)
        for ratio,(ps,fs) in meshes.items():
            candidate,_=p.raster(p.project(ps,transform),fs,np.ones(len(fs),bool),(0,0,128,128),3)
            metrics=p.metrics(p.filtered(candidate-raw,.9,3))
            stats[ratio]['views'].append(dict(angle=float(angle),**metrics,
                rawCoverageChanged=int(np.count_nonzero(candidate[...,0]!=raw[...,0]))))
        print(a.capture.stem,'full-view',vi,flush=True)
    for row in stats.values():
        row['sumSSE']=sum(v['total'] for v in row['views'])
        row['worstViewSSE']=max(v['total'] for v in row['views'])
    result=dict(scope='development assets; full static orbit; geometry/depth only; standard QEM baseline',
        captureSha256=manifest['captureSha256'],
        manifestSha256=hashlib.sha256((a.directory/'manifest.json').read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        rasterSha256=hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest(),
        source=source_stats,levels=stats)
    (a.directory/'evaluation.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
