#!/usr/bin/env python3
"""Uniform, resumable, single-process continuation of every completed v2 case."""
import os
# Request one BLAS/OpenMP thread before importing numerical libraries; no global setting persists.
for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[key]='1'

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

spec=importlib.util.spec_from_file_location('serial_refinement',Path(__file__).with_name('refine_compensation_probe.py'))
r=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('parent',type=Path)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    started=time.perf_counter();recipe_path=args.parent/'proposals.json';parent_path=args.parent/'results.json'
    recipe=json.loads(recipe_path.read_text());parent=json.loads(parent_path.read_text())
    if parent['recipeSha256']!=r.digest(recipe_path):raise ValueError('parent recipe changed')
    for path,sha in (recipe['inputHashes']|parent['outputHashes']).items():
        if r.digest(path)!=sha:raise ValueError(f'changed input: {path}')
    if recipe.get('rendererContract')!='two-sided orientation from triangle geometry, independent of optimized normals':
        raise ValueError('explicit v2 renderer required')
    args.out.mkdir(parents=True,exist_ok=True);plan_path=args.out/'plan.json'
    if (args.out/'results.json').exists():raise ValueError('already completed')
    identifiers=['current']+[case['id'] for case in recipe['proposals']]
    if [row['id'] for row in parent['cases']]!=identifiers:raise ValueError('incomplete parent pool')
    if not plan_path.exists():
        plan=dict(scope='all nine normal fits, uniform sequential continuation, classical baseline',
            parent=str(args.parent),parentRecipeSha256=r.digest(recipe_path),parentResultsSha256=r.digest(parent_path),
            extraIterationsPerCase=800,workers=1,ftol=1e-12,gtol=1e-5,maxcor=50,maxls=30,
            identifiers=identifiers,rendererContract=recipe['rendererContract'],
            requestedThreadEnvironment={key:os.environ[key] for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS')},
            initialization='each saved 200-step state, all cases receive same extra cap; no selected restart',
            implementationHashes={str(path):r.digest(path) for path in (Path(__file__),Path(r.__file__))})
        plan_path.write_text(json.dumps(plan,indent=2)+'\n')
    plan=json.loads(plan_path.read_text())
    if plan['parentResultsSha256']!=r.digest(parent_path):raise ValueError('parent results changed')
    for path,sha in plan['implementationHashes'].items():
        if r.digest(path)!=sha:raise ValueError('continuation implementation changed')
    journal=args.out/'partial.json';finished=[];hashes={}
    if journal.exists():
        previous=json.loads(journal.read_text())
        if previous['planSha256']!=r.digest(plan_path):raise ValueError('continuation journal changed')
        finished=previous['cases'];hashes=previous['outputHashes']
        if [row['id'] for row in finished]!=identifiers[:len(finished)]:raise ValueError('journal prefix differs')
        for path,sha in hashes.items():
            if r.digest(path)!=sha:raise ValueError('continued normals changed')
    print('FROZEN SERIAL REFINEMENT',r.digest(plan_path),'inherited',len(finished),flush=True)
    r.initialize(recipe)
    for index,prior in enumerate(parent['cases']):
        if index<len(finished):
            if finished[index]['parentCaseSha256']!=r.case_hash(prior):raise ValueError('initialization differs')
            continue
        row,path,sha=r.refine((prior,str(args.out),plan['extraIterationsPerCase']))
        finished.append(row);hashes[path]=sha
        temporary=args.out/'partial.tmp';temporary.write_text(json.dumps(dict(planSha256=r.digest(plan_path),
            cases=finished,outputHashes=hashes),indent=2)+'\n');temporary.replace(journal)
        print(row['id'],row['fit']['continuationStartSSE'],'->',row['fit']['fittedSSE'],
            row['fit']['message'],'pg',row['fit']['projectedGradientMax'],flush=True)
    base=finished[0];candidates=finished[1:]
    selected=dict(qem=min(candidates,key=lambda row:row['qem'])['id'],
        geometry=min(candidates,key=lambda row:row['geometryFitSSE'])['id'],
        fixedRGB=min(candidates,key=lambda row:row['fit']['initialSSE'])['id'],
        fittedRGB=min(candidates,key=lambda row:row['fit']['fittedSSE'])['id'])
    for row in candidates:
        row['fit']['deltaFittedSSE']=row['fit']['fittedSSE']-base['fit']['fittedSSE']
        row['fit']['deltaFixedSSE']=row['fit']['initialSSE']-base['fit']['initialSSE']
    result=dict(scope=plan['scope'],recipeSha256=parent['recipeSha256'],planSha256=r.digest(plan_path),
        parentResultsSha256=r.digest(parent_path),cases=finished,selected=selected,outputHashes=hashes,
        allConverged=all(row['fit']['success'] for row in finished),seconds=time.perf_counter()-started,
        timingScope='this invocation only; uniform serial continuation with requested BLAS/OpenMP threads1')
    (args.out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('COMPLETE SERIAL',selected,flush=True)


if __name__=='__main__':main()
