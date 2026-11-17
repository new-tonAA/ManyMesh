#!/usr/bin/env python3
"""Controlled linear-RGB shading audit for geometry-only simplification policies.

Smooth normals are derived from each mesh, not captured authored normals. No UV, shadows,
materials, GI or physical BRDF claim. Same source-normalized raster/filter for every policy.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('shade_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def vertex_normals(world,faces):
    result=np.zeros_like(world);tri=world[faces]
    normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    for i in range(3):np.add.at(result,faces[:,i],normals)
    lengths=np.linalg.norm(result,axis=1)
    np.divide(result,lengths[:,None],out=result,where=lengths[:,None]>1e-15)
    return result


def shade(projected,faces,normals,owners,forward,scale):
    rgb=np.zeros((*owners.shape,3));yy,xx=np.nonzero(owners>=0)
    if not len(xx):return rgb
    ids=faces[owners[yy,xx]];tri=projected[ids]
    a=tri[:,0];b=tri[:,1]-a;c=tri[:,2]-a
    d=np.column_stack(((xx+.5)/scale,(yy+.5)/scale))-a[:,:2]
    area=b[:,0]*c[:,1]-b[:,1]*c[:,0]
    u=(d[:,0]*c[:,1]-d[:,1]*c[:,0])/area
    v=(b[:,0]*d[:,1]-b[:,1]*d[:,0])/area
    n=(1-u-v)[:,None]*normals[ids[:,0]]+u[:,None]*normals[ids[:,1]]+v[:,None]*normals[ids[:,2]]
    length=np.linalg.norm(n,axis=1);n/=np.maximum(length[:,None],1e-15)
    n[np.einsum('ij,j->i',n,forward)<0]*=-1
    color=np.full_like(n,.06)
    lights=(((.4,.7,1.),(.65,.52,.42)),((-1.,.2,.3),(.18,.26,.38)),((.3,-.7,-.5),(.13,.1,.08)))
    for direction,power in lights:
        light=np.asarray(direction);light/=np.linalg.norm(light)
        half=light+forward;half/=max(np.linalg.norm(half),1e-15)
        diffuse=np.maximum(0,n@light)
        specular=np.maximum(0,n@half)**64*.2
        color+=diffuse[:,None]*power+specular[:,None]
    rgb[yy,xx]=color
    return rgb


def filter_rgb(rgb):
    # Reuse the exact established two-channel filter without editing it during live runs.
    rg=p.filtered(rgb[...,:2],.9,3)
    blue=p.filtered(np.stack((rgb[...,2],np.zeros_like(rgb[...,2])),axis=-1),.9,3)[...,0]
    return np.concatenate((rg,blue[...,None]),axis=-1)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('directories',type=Path,nargs='+')
    ap.add_argument('--ratio',default='0.25');ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();world,source,_=p.load_capture(args.capture)
    capture_hash=hashlib.sha256(args.capture.read_bytes()).hexdigest()
    meshes={};hashes={str(args.capture):capture_hash}
    for directory in args.directories:
        manifest_path=directory/'manifest.json';manifest=json.loads(manifest_path.read_text())
        if manifest['captureSha256']!=capture_hash:raise ValueError('source hash mismatch')
        artifact=manifest['artifacts'][args.ratio];path=Path(artifact['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('mesh hash mismatch')
        mesh=np.load(path);ps,fs=mesh['positions'],mesh['triangles']
        meshes[str(directory)]=(ps,fs,vertex_normals(ps,fs))
        hashes[str(manifest_path)]=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        hashes[str(path)]=artifact['sha256']
    source_normals=vertex_normals(world,source)
    rows={name:dict(triangles=len(fs),views=[]) for name,(ps,fs,ns) in meshes.items()}
    for vi,angle in enumerate(np.linspace(0,2*np.pi,12,endpoint=False)):
        transform=p.camera(world,float(angle),128);forward=transform[2][2]
        projected=p.project(world,transform)
        _,owners=p.raster(projected,source,np.ones(len(source),bool),(0,0,128,128),3)
        original=filter_rgb(shade(projected,source,source_normals,owners,forward,3))
        for name,(ps,fs,normals) in meshes.items():
            projected=p.project(ps,transform)
            _,owners=p.raster(projected,fs,np.ones(len(fs),bool),(0,0,128,128),3)
            image=filter_rgb(shade(projected,fs,normals,owners,forward,3))
            error=np.square(image-original)
            rows[name]['views'].append(dict(angle=float(angle),rgbSSE=float(error.sum()),
                                           rgbMSE=float(error.mean()),maxPixelSSE=float(error.sum(axis=-1).max())))
        print(args.capture.stem,'RGB audit',vi,flush=True)
    for row in rows.values():
        row['sumRgbSSE']=sum(v['rgbSSE'] for v in row['views'])
        row['worstRgbSSE']=max(v['rgbSSE'] for v in row['views'])
    hashes[str(Path(__file__))]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    hashes[str(Path(p.__file__))]=hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()
    result=dict(scope='controlled smooth-normal Lambert+Blinn-Phong RGB, no material/UV/shadow validation',
                ratio=args.ratio,sourceTriangles=len(source),inputHashes=hashes,policies=rows)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
