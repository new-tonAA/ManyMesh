#!/usr/bin/env python3
"""Controlled normal-transfer attribution at fixed geometry and light setup."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

s=load('transfer_shading','evaluate_shading_controls.py')
t=load('transfer_history','collapse_normal_transfer.py')
p=s.p


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('directories',nargs='+',type=Path)
    ap.add_argument('--reference-rgb',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--ratio',default='0.25')
    args=ap.parse_args();started=time.perf_counter()
    world,faces,_=p.load_capture(args.capture);source_normals=s.vertex_normals(world,faces)
    capture_hash=hashlib.sha256(args.capture.read_bytes()).hexdigest()
    prior=json.loads(args.reference_rgb.read_text());meshes={};rows={};hashes={}
    # Exact same reference renderer/version, not a revised light model selected after failures.
    for path in (Path(s.__file__),Path(p.__file__)):
        if prior['inputHashes'][str(path)]!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('reference shading/raster implementation differs')
    for directory in args.directories:
        manifest_path=directory/'manifest.json';manifest=json.loads(manifest_path.read_text())
        if manifest['captureSha256']!=capture_hash:raise ValueError('source differs')
        if prior['inputHashes'][str(manifest_path)]!=hashlib.sha256(manifest_path.read_bytes()).hexdigest():
            raise ValueError('reference RGB uses another checkpoint run')
        path=Path(manifest['artifacts'][args.ratio]['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['artifacts'][args.ratio]['sha256']:
            raise ValueError('checkpoint differs')
        mesh=np.load(path);ps,fs=mesh['positions'],mesh['triangles']
        before=s.vertex_normals(ps,fs);start=time.perf_counter()
        carried,report=t.transfer(args.capture,manifest,args.ratio,ps,fs)
        # A zero summed source moment has no defined orientation. Report and use derived normal.
        zero=np.linalg.norm(carried,axis=1)<=1e-15;carried[zero]=before[zero]
        meshes[str(directory)]=(ps,fs,before,carried)
        rows[str(directory)]=dict(triangles=len(fs),transferSeconds=time.perf_counter()-start,**report,views=[])
        hashes[str(manifest_path)]=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        hashes[str(path)]=manifest['artifacts'][args.ratio]['sha256']
    for vi,angle in enumerate(np.linspace(0,2*np.pi,12,endpoint=False)):
        transform=p.camera(world,float(angle),128);forward=transform[2][2];projected=p.project(world,transform)
        _,owner=p.raster(projected,faces,np.ones(len(faces),bool),(0,0,128,128),3)
        original=s.filter_rgb(s.shade(projected,faces,source_normals,owner,forward,3))
        for name,(ps,fs,before,carried) in meshes.items():
            projected=p.project(ps,transform)
            _,owner=p.raster(projected,fs,np.ones(len(fs),bool),(0,0,128,128),3)
            before_image=s.filter_rgb(s.shade(projected,fs,before,owner,forward,3))
            after_image=s.filter_rgb(s.shade(projected,fs,carried,owner,forward,3))
            before_error=float(np.square(before_image-original).sum())
            ref=prior['policies'][name]['views'][vi]
            if ref['angle']!=float(angle):raise ValueError('camera mismatch')
            np.testing.assert_allclose(before_error,ref['rgbSSE'],rtol=1e-10,atol=1e-10)
            rows[name]['views'].append(dict(angle=float(angle),derivedRgbSSE=before_error,
                carriedRgbSSE=float(np.square(after_image-original).sum())))
        print(args.capture.stem,'normal attribution',vi,flush=True)
    for row in rows.values():
        row['derivedRgbSSE']=sum(v['derivedRgbSSE'] for v in row['views'])
        row['carriedRgbSSE']=sum(v['carriedRgbSSE'] for v in row['views'])
        row['regressedViews']=sum(v['carriedRgbSSE']>v['derivedRgbSSE']+1e-12 for v in row['views'])
    for path in (args.capture,args.reference_rgb,Path(__file__),Path(t.__file__),Path(s.__file__),Path(p.__file__)):
        hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    result=dict(scope='fixed geometry, source-area moment transfer vs derived normals; classical control',
        ratio=args.ratio,inputHashes=hashes,policies=rows,seconds=time.perf_counter()-started)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
