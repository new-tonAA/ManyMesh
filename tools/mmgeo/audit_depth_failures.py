#!/usr/bin/env python3
"""Re-render the worst measured coarse-ranking regression per asset; no candidate cherry-picking."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('pilot',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary',type=Path)
    parser.add_argument('--captures',required=True,type=Path)
    parser.add_argument('--reports',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    audit=[]
    for result in json.loads(args.summary.read_text()):
        group=max((g for g in result['groups'] if g['baselineVisible']),
                  key=lambda g:g['predictions'][2]['metrics']['total']-g['baseline']['total'])
        name=result['asset']; frame=group['frame']; cid=group['predictions'][2]['id']
        report=json.loads((args.reports/(name+'.json')).read_text())
        record=report['frames'][frame]
        candidate_record=next(c for c in record['candidates'] if c['id']==cid)
        vertices,faces,candidates=p.load_capture(args.captures/(name+'.json'))
        c=candidates[cid]; size=report['size']; scale=report['scale']; sigma=report['sigma']
        transform=p.camera(vertices,record['angle'],size)
        projected=p.project(vertices,transform)
        changed,changed_faces,valid=p.edited_geometry(projected,faces,c,transform)
        raw,_=p.raster(projected,faces,np.ones(len(faces),bool),(0,0,size,size),scale)
        other,_=p.raster(changed,changed_faces,valid,(0,0,size,size),scale)
        base=p.filtered(raw,sigma,scale); image=p.filtered(other,sigma,scale)
        residual=image-base
        p.write_overlay(args.out,projected,changed,faces,c,candidate_record['rect'],base,
                        image,residual,f'{name}-worst-{frame}-{cid}')
        # Reproject the entire edited vertex buffer with frozen original camera, independently
        # of edited_geometry's singleton target projection.
        new_vertices=vertices.copy(); new_vertices[c['keep']]=c['target']
        independently_projected=p.project(new_vertices,transform)
        projection_difference=float(np.max(np.abs(independently_projected-changed)))
        if projection_difference>1e-12:
            raise AssertionError('target projection mismatch')
        actual=p.metrics(residual)
        if abs(actual['total']-candidate_record['metrics']['total'])>1e-10:
            raise AssertionError('rerender does not reproduce saved error')
        audit.append(dict(asset=name,frame=frame,id=cid,projectionMaxDifference=projection_difference,
                          metrics=actual,baselineMetrics=group['baseline'],
                          prediction=candidate_record['predictions'][2]))
    (args.out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')


if __name__=='__main__':
    main()
