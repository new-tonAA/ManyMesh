#!/usr/bin/env python3
"""Validate complete compensation-probe artifacts and report all candidate outcomes."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--refinement',type=Path)
    args=parser.parse_args();root=args.directory;artifacts=args.refinement or root
    recipe_path=root/'proposals.json';result_path=artifacts/'results.json'
    recipe=json.loads(recipe_path.read_text());result=json.loads(result_path.read_text())
    if digest(recipe_path)!=result['recipeSha256']:raise ValueError('recipe changed')
    parent=None;plan_path=None
    if args.refinement:
        parent_path=root/'results.json';parent=json.loads(parent_path.read_text())
        plan_path=artifacts/'plan.json';plan=json.loads(plan_path.read_text())
        if digest(parent_path)!=result['parentResultsSha256'] or digest(plan_path)!=result['planSha256']:
            raise ValueError('refinement parent/plan changed')
        if plan['parentRecipeSha256']!=digest(recipe_path):raise ValueError('refinement recipe differs')
        if 'implementationHashes' in plan:
            for path,sha in plan['implementationHashes'].items():
                if digest(path)!=sha:raise ValueError('refinement implementation changed')
        else:
            script=Path('tools/mmgeo/refine_compensation_probe.py')
            if digest(script)!=plan['scriptSha256']:raise ValueError('refinement implementation changed')
        parents={row['id']:row for row in parent['cases']}
        for row in result['cases']:
            prior=parents[row['id']];canonical=dict(prior)
            canonical['fit']={k:v for k,v in prior['fit'].items() if k not in ('deltaFixedSSE','deltaFittedSSE')}
            sha=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
            if sha!=row['parentCaseSha256']:raise ValueError('different saved initialization')
            np.testing.assert_allclose(row['fit']['continuationStartSSE'],prior['fit']['fittedSSE'],atol=1e-11)
            if row['fit']['iterations']>plan['extraIterationsPerCase']:raise ValueError('refinement budget exceeded')
    for path,sha in (recipe['inputHashes']|result['outputHashes']).items():
        if digest(path)!=sha:raise ValueError(f'stale input/output: {path}')
    recovery_result=parent if parent is not None else result
    if 'recoverySha256' in recovery_result:
        recovery_path=root/'recovery.json';recovery=json.loads(recovery_path.read_text())
        if digest(recovery_path)!=recovery_result['recoverySha256']:raise ValueError('recovery record changed')
        if digest('tools/mmgeo/complete_compensation_probe.py')!=recovery['scriptSha256']:
            raise ValueError('recovery implementation changed')
    rows=result['cases'];expected=['current']+[c['id'] for c in recipe['proposals']]
    if [r['id'] for r in rows]!=expected:raise ValueError('incomplete/reordered pool')
    checkpoint=np.load(recipe['checkpoint']);base=rows[0];candidates=rows[1:]
    for row,case in zip(rows,[None]+recipe['proposals']):
        faces=checkpoint['triangles'].copy()
        if case is not None:
            faces[faces==case['remove']]=case['keep']
            faces=faces[(faces[:,0]!=faces[:,1])&(faces[:,1]!=faces[:,2])&(faces[:,2]!=faces[:,0])]
        used=np.unique(faces)
        if len(faces)!=row['triangles'] or 2*len(used)!=row['fit']['attributeScalars']:
            raise ValueError('incorrect geometry/attribute budget')
        normals=np.load(artifacts/f'{row["id"]}-normals.npz')['normals']
        np.testing.assert_allclose(np.linalg.norm(normals[used],axis=1),1,atol=1e-13)
        parameters=row['fit']['parameters']
        if len(parameters)!=2*len(used) or np.max(np.abs(parameters))>.5+1e-12:
            raise ValueError('attribute parameter constraint differs')
        if [v['angle'] for v in row['views']]!=recipe['testAngles']:raise ValueError('camera mismatch')
        for light in ('original','rotated'):
            for mode in ('fixedSSE','fittedSSE'):
                np.testing.assert_allclose(sum(v[light][mode] for v in row['views']),row['test'][light][mode],
                                           rtol=1e-12,atol=1e-12)
    old_path=Path('out/shading-controls/torus.json');old=json.loads(old_path.read_text())
    old_base=old['policies'][str(Path('out/progressive-baseline/torus'))]
    # Only v1 has the previous shading-normal-facing contract. Never compare v2 as if unchanged.
    compared_previous='rendererContract' not in recipe
    if compared_previous:
        for actual,prior in zip(base['views'],old_base['views']):
            if actual['angle']!=prior['angle']:raise ValueError('reference camera differs')
            np.testing.assert_allclose(actual['original']['fixedSSE'],prior['rgbSSE'],rtol=1e-10,atol=1e-10)
    keys=dict(qem=lambda r:r['qem'],geometry=lambda r:r['geometryFitSSE'],
              fixedRGB=lambda r:r['fit']['initialSSE'],fittedRGB=lambda r:r['fit']['fittedSSE'])
    selected={name:min(candidates,key=key)['id'] for name,key in keys.items()}
    if selected!=result['selected']:raise ValueError('selection differs')
    summaries=[]
    for row in rows:
        summary=dict(id=row['id'],fitBefore=row['fit']['initialSSE'],fitAfter=row['fit']['fittedSSE'],
            success=row['fit']['success'],iterations=row['fit']['iterations'],
            projectedGradientMax=row['fit']['projectedGradientMax'],fitSeconds=row['fitSeconds'],test={})
        for light in ('original','rotated'):
            summary['test'][light]=dict(**row['test'][light],
                fittedDeltaFromCurrent=row['test'][light]['fittedSSE']-base['test'][light]['fittedSSE'],
                fittedWorseViewsFromCurrent=sum(v[light]['fittedSSE']>b[light]['fittedSSE']+1e-12
                    for v,b in zip(row['views'],base['views'])))
        summaries.append(summary)
    lookup={row['id']:row for row in rows};chosen=lookup[selected['fittedRGB']]
    contrasts={}
    for method,identifier in selected.items():
        other=lookup[identifier]
        contrasts[method]={light:dict(
            reduction=1-chosen['test'][light]['fittedSSE']/other['test'][light]['fittedSSE'],
            worseViews=sum(v[light]['fittedSSE']>b[light]['fittedSSE']+1e-12
                for v,b in zip(chosen['views'],other['views']))) for light in ('original','rotated')}
    summary=dict(scope='single development checkpoint, finite classical normal fitting',
        hashes={str(p):digest(p) for p in (recipe_path,result_path,old_path,Path(__file__))},
        rendererContract=recipe.get('rendererContract','v1 shading-normal-facing'),
        previousRGBReferenceCompared=compared_previous,
        timingScope=result.get('timingScope','original full invocation'),
        selected=selected,allOptimizerSuccess=result['allConverged'],
        allProjectedGradientsSmall=all(r['fit']['projectedGradientMax']<=1e-5 for r in rows),
        fittedWinnerVsOtherFittedWinners=contrasts,cases=summaries,seconds=result['seconds'])
    if parent is not None:
        summary['parentSelected']=parent['selected']
        summary['fittedSelectionChanged']=parent['selected']['fittedRGB']!=selected['fittedRGB']
        summary['hashes'][str(plan_path)]=digest(plan_path)
        summary['hashes'][str(root/'results.json')]=digest(root/'results.json')
    (artifacts/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
