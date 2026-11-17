#!/usr/bin/env python3
"""Aggregate the frozen visibility ablation, preserving mismatched-budget cases."""
import hashlib
import json
from pathlib import Path


def main():
    policies={'qem':'progressive-baseline','all':'source-contour-control',
              'visible':'visible-contour-control','matched':'matched-contour-control'}
    rows=[];hashes={};counts=[]
    for name in ('torus','monkey','pirate'):
        visibility_path=Path(f'out/contour-visibility/{name}.json')
        visibility=json.loads(visibility_path.read_text())
        hashes[str(visibility_path)]=hashlib.sha256(visibility_path.read_bytes()).hexdigest()
        counts.append(dict(asset=name,constraints=sum(u['constraints'] for u in visibility['units']),
                           hidden=sum(u.get('hidden',0) for u in visibility['units']),
                           partial=sum(u.get('partial',0) for u in visibility['units']),
                           preprocessingSeconds=visibility['seconds']))
        data={}
        for policy,root in policies.items():
            path=Path('out')/root/name/'evaluation.json'
            hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            data[policy]=json.loads(path.read_text())
            if data[policy]['captureSha256']!=visibility['captureSha256']:
                raise ValueError('source hash mismatch')
        if len({d['rasterSha256'] for d in data.values()})!=1:raise ValueError('raster versions differ')
        for ratio in data['qem']['levels']:
            levels={k:d['levels'][ratio] for k,d in data.items()}
            if len({tuple(v['angle'] for v in d['views']) for d in levels.values()})!=1:
                raise ValueError('camera population differs')
            faces={k:d['topology']['triangles'] for k,d in levels.items()}
            errors={k:d['sumSSE'] for k,d in levels.items()}
            reductions={}
            regressions={}
            for base in ('qem','all','matched'):
                matched=faces[base]==faces['visible']
                reductions[base]=1-errors['visible']/errors[base] if matched and errors[base] else None
                regressions[base]=sum(v['total']>b['total']+1e-12 for v,b in
                                     zip(levels['visible']['views'],levels[base]['views'])) if matched else None
            rows.append(dict(asset=name,ratio=float(ratio),faces=faces,errors=errors,
                              visibleReductionAgainst=reductions,visibleRegressedViews=regressions,
                              topology={k:d['topology'] for k,d in levels.items()}))
    result=dict(scope='source-only visibility ablation; all cases, no policy selection by test outcomes',
                inputHashes=hashes,scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                counts=counts,rows=rows)
    path=Path('out/contour-visibility/summary.json');path.write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print(row['asset'],row['ratio'],row['faces'],row['visibleReductionAgainst'])


if __name__=='__main__':main()
