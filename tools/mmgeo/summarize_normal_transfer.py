#!/usr/bin/env python3
"""Summarize complete, hash-validated fixed-geometry normal controls."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    rows=[];hashes={}
    for asset in ('torus','monkey','pirate'):
        path=Path('out/normal-transfer')/f'{asset}.json'
        data=json.loads(path.read_text());hashes[str(path)]=digest(path)
        if data['ratio']!='0.25':raise ValueError('unexpected checkpoint')
        for input_path,expected in data['inputHashes'].items():
            if digest(input_path)!=expected:raise ValueError(f'stale input: {input_path}')
        qem=data['policies'][str(Path('out/progressive-baseline')/asset)]
        image=data['policies'][str(Path('out/progressive-image-control')/asset)]
        if qem['triangles']!=image['triangles']:raise ValueError('unequal actual face counts')
        angles=[v['angle'] for v in qem['views']]
        if len(set(angles))!=12 or angles!=[v['angle'] for v in image['views']]:
            raise ValueError('camera population differs')
        for policy in (qem,image):
            for mode in ('derived','carried'):
                measured=sum(v[f'{mode}RgbSSE'] for v in policy['views'])
                if abs(measured-policy[f'{mode}RgbSSE'])>1e-10:raise ValueError('invalid sum')
        row=dict(asset=asset,triangles=qem['triangles'],modes={},transfer={})
        for mode in ('derived','carried'):
            key=f'{mode}RgbSSE'
            row['modes'][mode]=dict(qemRgbSSE=qem[key],imageRgbSSE=image[key],
                imageReduction=1-image[key]/qem[key],
                imageWorseViews=sum(v[key]>b[key]+1e-12 for v,b in zip(image['views'],qem['views'])))
        for name,policy in (('qem',qem),('image',image)):
            row['transfer'][name]=dict(reduction=1-policy['carriedRgbSSE']/policy['derivedRgbSSE'],
                worseViews=policy['regressedViews'],
                zeroMomentUsedVertices=policy['zeroMomentUsedVertices'],
                replayedCollapses=policy['replayedCollapses'])
        rows.append(row);print(json.dumps(row),flush=True)
    target=Path('out/normal-transfer/summary.json')
    target.write_text(json.dumps(dict(scope='classical normal control; development assets only',
        hashes=hashes,scriptSha256=digest(__file__),assets=rows),indent=2)+'\n')


if __name__=='__main__':main()
