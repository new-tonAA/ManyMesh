#!/usr/bin/env python3
"""Uniform continuation of ALL nine finite normal fits; no candidate-specific extra budget."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

spec=importlib.util.spec_from_file_location('refine_facing',Path(__file__).with_name('normal_fit_control_v2.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def case_hash(row):
    # The parent adds these two derived deltas at finalization after emitting the case journal.
    canonical=dict(row)
    canonical['fit']={k:v for k,v in row['fit'].items() if k not in ('deltaFixedSSE','deltaFittedSSE')}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()


def initialize(recipe):
    global context
    source,faces,_=m.p.load_capture(Path(recipe['capture']));saved=np.load(recipe['checkpoint'])
    fitting=[m.p.camera(source,a,recipe['size']) for a in recipe['fitAngles']]
    testing=[m.p.camera(source,a,recipe['size']) for a in recipe['testAngles']]
    lighting=m.lights();relight=m.lights(recipe['testLightRotation']);sn=m.s.vertex_normals(source,faces)
    targets=[m.View(source,faces,t).render(sn,lighting) for t in fitting]
    tests=[]
    for transform in testing:
        view=m.View(source,faces,transform);tests.append((view.render(sn,lighting),view.render(sn,relight)))
    context=(saved['positions'],saved['triangles'],fitting,targets,testing,tests,lighting,relight,recipe)


def refine(task):
    row,out,budget=task;started=time.perf_counter()
    current,faces,fitting,targets,testing,tests,lighting,relight,recipe=context
    ps=current.copy();fs=faces.copy()
    if row['id']!='current':
        ps[row['keep']]=row['target'];fs[fs==row['remove']]=row['keep']
        fs=fs[(fs[:,0]!=fs[:,1])&(fs[:,1]!=fs[:,2])&(fs[:,2]!=fs[:,0])]
    problem=m.Problem(ps,fs,fitting,targets,lighting);x0=np.asarray(row['fit']['parameters'])
    initial,_=problem.objective(x0)
    np.testing.assert_allclose(initial,row['fit']['fittedSSE'],rtol=1e-11,atol=1e-11)
    result=minimize(problem.objective,x0,jac=True,method='L-BFGS-B',bounds=[(-.5,.5)]*len(x0),
        options=dict(maxiter=budget,maxls=30,ftol=1e-12,gtol=1e-5,maxcor=50))
    normals,_=problem.normals(result.x);value,gradient=problem.objective(result.x)
    if value>initial+1e-10:raise ValueError('continued solve increased objective')
    projected=gradient.copy()
    projected[(result.x<=-.5+1e-10)&(gradient>0)]=0
    projected[(result.x>=.5-1e-10)&(gradient<0)]=0
    fit=dict(initialSSE=row['fit']['initialSSE'],fittedSSE=value,continuationStartSSE=initial,
        success=bool(result.success),message=str(result.message),iterations=int(result.nit),
        evaluations=problem.evaluations,trace=problem.trace,
        projectedGradientMax=float(np.abs(projected).max()),boundScalars=int(np.sum(np.abs(result.x)>=.5-1e-10)),
        attributeScalars=len(x0),parameters=result.x.tolist())
    reference=0.
    for view,target in zip(problem.views,targets):
        rendered=m.s.filter_rgb(m.s.shade(view.projected,fs,normals,view.owners,view.forward,3))
        reference+=float(np.square(rendered-target).sum())
    np.testing.assert_allclose(reference,value,rtol=1e-11,atol=1e-11)
    fit_seconds=time.perf_counter()-started;views=[]
    for angle,transform,pair in zip(recipe['testAngles'],testing,tests):
        view=m.View(ps,fs,transform);entry=dict(angle=angle)
        for label,lights,target in zip(('original','rotated'),(lighting,relight),pair):
            entry[label]=dict(fixedSSE=float(np.square(view.render(problem.initial,lights)-target).sum()),
                fittedSSE=float(np.square(view.render(normals,lights)-target).sum()))
        views.append(entry)
    path=Path(out)/f'{row["id"]}-normals.npz';np.savez_compressed(path,normals=normals)
    refined=dict(row);refined.update(fit=fit,views=views,fitSeconds=fit_seconds,
        totalSeconds=time.perf_counter()-started,parentCaseSha256=case_hash(row),
        test={label:{mode:sum(v[label][mode] for v in views) for mode in ('fixedSSE','fittedSSE')}
              for label in ('original','rotated')})
    return refined,str(path),digest(path)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('parent',type=Path)
    ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    started=time.perf_counter();recipe_path=args.parent/'proposals.json';recipe=json.loads(recipe_path.read_text())
    if recipe.get('rendererContract')!='two-sided orientation from triangle geometry, independent of optimized normals':
        raise ValueError('only the explicitly versioned geometric-facing contract is supported')
    for path,sha in recipe['inputHashes'].items():
        if digest(path)!=sha:raise ValueError(f'changed parent input: {path}')
    args.out.mkdir(parents=True,exist_ok=True);plan_path=args.out/'plan.json'
    if plan_path.exists():raise ValueError('use an unused directory for another refinement')
    identifiers=['current']+[c['id'] for c in recipe['proposals']];budget=800;workers=3
    plan=dict(scope='uniform continuation, existing normal-fit method; no global optimum claim',
        parent=str(args.parent),parentRecipeSha256=digest(recipe_path),identifiers=identifiers,
        extraIterationsPerCase=budget,workers=workers,ftol=1e-12,gtol=1e-5,maxcor=50,maxls=30,
        initialization='each saved parent 200-iteration state; no new start selected per candidate',
        rendererContract=recipe['rendererContract'],
        timingCaveat='three workers and a concurrently running parent; timings are not serial benchmark timings',
        scriptSha256=digest(__file__))
    plan_path.write_text(json.dumps(plan,indent=2)+'\n')
    print('FROZEN REFINEMENT',digest(plan_path),flush=True)
    futures={};finished={};hashes={};submitted=set();parent_final=None
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize,initargs=(recipe,)) as pool:
        while len(finished)<len(identifiers):
            parent_path=args.parent/'results.json'
            if not parent_path.exists():parent_path=args.parent/'partial.json'
            try:data=json.loads(parent_path.read_text())
            except (FileNotFoundError,json.JSONDecodeError):
                time.sleep(1);continue
            if data['recipeSha256']!=plan['parentRecipeSha256']:raise ValueError('parent recipe differs')
            if parent_path.name=='results.json':parent_final=data
            for row in data['cases']:
                if row['id'] in submitted:continue
                if row['id'] not in identifiers:raise ValueError('unexpected parent case')
                submitted.add(row['id']);future=pool.submit(refine,(row,str(args.out),budget));futures[future]=row['id']
            for future in list(futures):
                if not future.done():continue
                row,path,sha=future.result();finished[row['id']]=row;hashes[path]=sha;del futures[future]
                (args.out/'partial.json').write_text(json.dumps(dict(planSha256=digest(plan_path),
                    cases=[finished[i] for i in identifiers if i in finished]),indent=2)+'\n')
                print(row['id'],row['fit']['continuationStartSSE'],'->',row['fit']['fittedSSE'],
                    row['fit']['message'],'pg',row['fit']['projectedGradientMax'],flush=True)
            time.sleep(1)
    if parent_final is None:
        parent_final=json.loads((args.parent/'results.json').read_text())
    for row in parent_final['cases']:
        if case_hash(row)!=finished[row['id']]['parentCaseSha256']:raise ValueError('parent case changed')
    rows=[finished[i] for i in identifiers];base=rows[0];candidates=rows[1:]
    selected=dict(qem=min(candidates,key=lambda r:r['qem'])['id'],
        geometry=min(candidates,key=lambda r:r['geometryFitSSE'])['id'],
        fixedRGB=min(candidates,key=lambda r:r['fit']['initialSSE'])['id'],
        fittedRGB=min(candidates,key=lambda r:r['fit']['fittedSSE'])['id'])
    for row in candidates:
        row['fit']['deltaFittedSSE']=row['fit']['fittedSSE']-base['fit']['fittedSSE']
        row['fit']['deltaFixedSSE']=row['fit']['initialSSE']-base['fit']['initialSSE']
    final=dict(scope=plan['scope'],recipeSha256=plan['parentRecipeSha256'],planSha256=digest(plan_path),
        parentResultsSha256=digest(args.parent/'results.json'),cases=rows,selected=selected,
        outputHashes=hashes,allConverged=all(r['fit']['success'] for r in rows),seconds=time.perf_counter()-started)
    (args.out/'results.json').write_text(json.dumps(final,indent=2)+'\n')
    print('COMPLETE',selected,'allConverged',final['allConverged'],flush=True)


if __name__=='__main__':main()
