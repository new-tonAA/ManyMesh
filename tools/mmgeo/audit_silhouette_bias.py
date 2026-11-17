#!/usr/bin/env python3
"""Audit inward/outward coverage bias before proposing curvature compensation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('bias_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def coverage_bias(reference,candidate):
    missing=int(np.count_nonzero((reference>0)&(candidate==0)))
    extra=int(np.count_nonzero((reference==0)&(candidate>0)))
    return dict(missingSamples=missing,extraSamples=extra,netMissing=missing-extra,
                imbalance=(missing-extra)/(missing+extra) if missing+extra else 0.)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('directory',type=Path)
    ap.add_argument('--ratio',default='0.25')
    args=ap.parse_args();manifest=json.loads((args.directory/'manifest.json').read_text())
    if hashlib.sha256(args.capture.read_bytes()).hexdigest()!=manifest['captureSha256']:
        raise ValueError('source hash differs')
    artifact=manifest['artifacts'][args.ratio];path=Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('mesh differs')
    world,faces,_=p.load_capture(args.capture);mesh=np.load(path)
    low,fs=mesh['positions'],mesh['triangles'];views=[]
    # Frozen existing measurement orbit, not used for selecting any correction.
    for i,angle in enumerate(np.linspace(0,2*np.pi,12,endpoint=False)):
        transform=p.camera(world,float(angle),128)
        raw,_=p.raster(p.project(world,transform),faces,np.ones(len(faces),bool),(0,0,128,128),3)
        candidate,_=p.raster(p.project(low,transform),fs,np.ones(len(fs),bool),(0,0,128,128),3)
        views.append(dict(angle=float(angle),**coverage_bias(raw[...,0],candidate[...,0])))
        print(args.capture.stem,'signed coverage',i,flush=True)
    missing=sum(r['missingSamples'] for r in views);extra=sum(r['extraSamples'] for r in views)
    result=dict(scope='static development-view signed coverage; no curvature mechanism tested',
        requestedRatio=args.ratio,actualTriangles=len(fs),sourceTriangles=len(faces),
        missingSamples=missing,extraSamples=extra,imbalance=(missing-extra)/(missing+extra) if missing+extra else 0.,
        inwardViews=sum(r['netMissing']>0 for r in views),outwardViews=sum(r['netMissing']<0 for r in views),
        hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                (args.capture,args.directory/'manifest.json',path,Path(__file__),Path(p.__file__))},views=views)
    (args.directory/f'coverage-bias-{args.ratio}.json').write_text(json.dumps(result,indent=2)+'\n')
    print({k:v for k,v in result.items() if k not in ('views','hashes')})


if __name__=='__main__':main()
