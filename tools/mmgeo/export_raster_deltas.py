#!/usr/bin/env python3
"""Export measured real-candidate sample deltas for native scorer comparison.

Extraction is NOT free: reports time and does not claim an end-to-end speedup. No thresholding
of nonzero deltas; sampled visibility is resolved exactly as the existing reference.
"""
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

p=load('export_depth','depth_candidate_pilot.py')
r=load('export_raster','transactional_raster.py')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    vertices,faces,candidates=p.load_capture(args.capture)
    report=json.loads(args.report.read_text())
    size=128;scale=3;sigma=.9;records=[];setup=[]
    for f in report['frames']:
        angle=np.linspace(2.13,2.48,6)[f['frame']]
        transform=p.camera(vertices,float(angle),size);projected=p.project(vertices,transform)
        start=time.perf_counter();cache=r.FragmentCache(projected,faces,size,scale)
        setup.append(time.perf_counter()-start)
        for obs in f['candidates']:
            c=candidates[obs['id']]
            start=time.perf_counter()
            changed,changed_faces,valid=p.edited_geometry(projected,faces,c,transform)
            replacement={i:changed[changed_faces[i]] for i in c['affected'] if valid[i]}
            transaction=cache.propose(c['affected'],replacement)
            rect=p.support(projected,faces,c,transform,size,6)
            before=cache.resolve(rect);after=cache.resolve(rect,transaction)
            delta=after-before
            yy,xx=np.nonzero(np.any(delta!=0,axis=2))
            values=delta[yy,xx]
            extraction=time.perf_counter()-start
            filtered=p.filtered(delta,sigma,scale)
            energy=float(np.square(filtered).sum())
            data=np.column_stack((xx+rect[0]*scale,yy+rect[1]*scale,values))
            records.append((f['frame'],obs['id'],energy,extraction,data))
        print(args.capture.stem,f['frame'],'exported',len(f['candidates']),flush=True)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('w') as out:
        out.write(f'{size} {size} {scale} {sigma:.17g} {len(records)}\n')
        for frame,cid,energy,seconds,data in records:
            out.write(f'{frame} {cid} {len(data)} {energy:.17g} {seconds:.17g}\n')
            for x,y,a,b in data:out.write(f'{int(x)} {int(y)} {a:.17g} {b:.17g}\n')
    args.out.with_suffix('.manifest.json').write_text(json.dumps(dict(
        captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        reportSha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
        exportSha256=hashlib.sha256(args.out.read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=len(records),cacheSetupSeconds=setup,
        note='CPU Python extraction and native scoring must not be presented as a native end-to-end measurement'),indent=2)+'\n')


if __name__=='__main__':main()
