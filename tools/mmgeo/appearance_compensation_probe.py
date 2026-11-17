#!/usr/bin/env python3
"""Freeze and measure a real-mesh, fixed-budget normal-compensation candidate pool.

This is an existing inverse-rendering method family, not a new simplifier or optimum certificate.
"""
import argparse
import hashlib
import heapq
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


m=load('compensated_normals','normal_fit_control.py')
q=load('compensated_qem','progressive_geometry_baseline.py')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(args):
    root=args.out;root.mkdir(parents=True,exist_ok=True);path=root/'proposals.json'
    if path.exists():raise ValueError('use an unused output directory to freeze another experiment')
    capture=Path('out/filter-real-candidates/torus.json')
    directory=Path('out/progressive-baseline/torus');manifest_path=directory/'manifest.json'
    manifest=json.loads(manifest_path.read_text());artifact=manifest['artifacts']['0.25']
    if digest(capture)!=manifest['captureSha256'] or digest(artifact['path'])!=artifact['sha256']:
        raise ValueError('stale geometry inputs')
    raw=json.loads(capture.read_text())['units'][0];ps=np.asarray(raw['positions'],float)
    center=(ps.min(0)+ps.max(0))*.5;radius=float(np.linalg.norm(ps-center,axis=1).max())
    solver=q.ProgressiveQEM((ps-center)/radius,raw['triangles']);solver.advance(288)
    saved=np.load(artifact['path']);world=solver.p*radius+center;faces=solver.f[solver.alive]
    np.testing.assert_allclose(world,saved['positions'],atol=1e-14,rtol=1e-14)
    np.testing.assert_array_equal(faces,saved['triangles'])
    proposals=[];seen=set()
    while solver.heap and len(proposals)<8:
        cost,u,v,vu,vv,index,target=heapq.heappop(solver.heap)
        if vu!=solver.versions[u] or vv!=solver.versions[v] or (u,v) in seen:continue
        if not solver.inc[u] or not solver.inc[v] or not solver.legal(u,v,np.asarray(target)):continue
        seen.add((u,v));proposals.append(dict(id=f'edge-{len(proposals):02}',keep=u,remove=v,qem=cost,
            placement=index,target=(center+radius*np.asarray(target)).tolist()))
    if len(proposals)!=8:raise ValueError('insufficient legal distinct candidates')
    hashes={str(p):digest(p) for p in (capture,manifest_path,Path(artifact['path']),Path(__file__),
        Path(m.__file__),Path(m.s.__file__),Path(m.p.__file__),Path(q.__file__))}
    recipe=dict(scope='eight current legal Torus proposals; classical normal-fit control',
        capture=str(capture),checkpoint=artifact['path'],sourceFaces=len(raw['triangles']),currentFaces=len(faces),
        fitAngles=(.13+2*np.pi*np.arange(3)/3).tolist(),testAngles=np.linspace(0,2*np.pi,12,endpoint=False).tolist(),
        size=128,scale=3,sigma=.9,fitLightRotation=0.,testLightRotation=.7,iterations=200,
        attributePolicy='two tangent scalars per used vertex, each [-.5,.5], anchored on derived normal',
        solver='L-BFGS-B, analytic gradient, ftol1e-11, gtol1e-5, maxls30, maxcor10, zero start',
        environment=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
        environmentCaveat='installed SciPy warns NumPy 2.5.4 exceeds its supported <2.5.0 range; numerical tests passed',
        inputHashes=hashes,proposals=proposals)
    path.write_text(json.dumps(recipe,indent=2)+'\n');print('FROZEN',path,digest(path),flush=True)


def measure(args):
    root=args.out;recipe_path=root/'proposals.json';recipe=json.loads(recipe_path.read_text())
    for path,sha in recipe['inputHashes'].items():
        if digest(path)!=sha:raise ValueError(f'changed frozen input: {path}')
    if (root/'results.json').exists():raise ValueError('completed experiment already exists')
    started=time.perf_counter();source,source_faces,_=m.p.load_capture(Path(recipe['capture']))
    saved=np.load(recipe['checkpoint']);current=saved['positions'];current_faces=saved['triangles']
    fitting=[m.p.camera(source,a,recipe['size']) for a in recipe['fitAngles']]
    testing=[m.p.camera(source,a,recipe['size']) for a in recipe['testAngles']]
    lighting=m.lights();relight=m.lights(recipe['testLightRotation'])
    source_normals=m.s.vertex_normals(source,source_faces)
    fit_targets=[];fit_geometry=[];test_targets=[]
    for transform in fitting:
        view=m.View(source,source_faces,transform)
        fit_targets.append(view.render(source_normals,lighting))
        fit_geometry.append(m.p.filtered(view.geometry_raw,.9,3))
    for transform in testing:
        view=m.View(source,source_faces,transform)
        test_targets.append((view.render(source_normals,lighting),view.render(source_normals,relight)))
    cases=[dict(id='current')]+recipe['proposals'];rows=[];outputs={}
    for case in cases:
        start=time.perf_counter();ps=current.copy();fs=current_faces.copy()
        if case['id']!='current':
            ps[case['keep']]=case['target'];fs[fs==case['remove']]=case['keep']
            fs=fs[(fs[:,0]!=fs[:,1])&(fs[:,1]!=fs[:,2])&(fs[:,2]!=fs[:,0])]
            if len(fs)!=len(current_faces)-2:raise ValueError('unequal proposal face budgets')
        problem=m.Problem(ps,fs,fitting,fit_targets,lighting)
        geometry=sum(float(np.square(m.p.filtered(view.geometry_raw,.9,3)-target).sum())
                     for view,target in zip(problem.views,fit_geometry))
        normals,report=problem.fit(recipe['iterations']);fit_seconds=time.perf_counter()-start
        # Independent reference implementation validates actual fitted training score.
        reference=0.
        for view,target in zip(problem.views,fit_targets):
            rendered=m.s.filter_rgb(m.s.shade(view.projected,fs,normals,view.owners,view.forward,3))
            reference+=float(np.square(rendered-target).sum())
        np.testing.assert_allclose(reference,report['fittedSSE'],rtol=1e-11,atol=1e-11)
        per_view=[]
        for angle,transform,targets in zip(recipe['testAngles'],testing,test_targets):
            view=m.View(ps,fs,transform);entry=dict(angle=angle)
            for label,lights,target in zip(('original','rotated'),(lighting,relight),targets):
                entry[label]=dict(fixedSSE=float(np.square(view.render(problem.initial,lights)-target).sum()),
                    fittedSSE=float(np.square(view.render(normals,lights)-target).sum()))
            per_view.append(entry)
        artifact=root/f'{case["id"]}-normals.npz';np.savez_compressed(artifact,normals=normals)
        outputs[str(artifact)]=digest(artifact)
        row=dict(**case,triangles=len(fs),geometryFitSSE=geometry,fit=report,fitSeconds=fit_seconds,
            totalSeconds=time.perf_counter()-start,views=per_view,
            test={label:{mode:sum(v[label][mode] for v in per_view) for mode in ('fixedSSE','fittedSSE')}
                  for label in ('original','rotated')})
        rows.append(row)
        (root/'partial.json').write_text(json.dumps(dict(recipeSha256=digest(recipe_path),cases=rows),indent=2)+'\n')
        print(case['id'],'fit',report['initialSSE'],'->',report['fittedSSE'],
              'success',report['success'],'pg',report['projectedGradientMax'],
              'seconds',row['totalSeconds'],flush=True)
    candidates=rows[1:];base=rows[0]
    selected=dict(qem=min(candidates,key=lambda r:r['qem'])['id'],
        geometry=min(candidates,key=lambda r:r['geometryFitSSE'])['id'],
        fixedRGB=min(candidates,key=lambda r:r['fit']['initialSSE'])['id'],
        fittedRGB=min(candidates,key=lambda r:r['fit']['fittedSSE'])['id'])
    for row in candidates:
        row['fit']['deltaFittedSSE']=row['fit']['fittedSSE']-base['fit']['fittedSSE']
        row['fit']['deltaFixedSSE']=row['fit']['initialSSE']-base['fit']['initialSSE']
    result=dict(scope=recipe['scope'],recipeSha256=digest(recipe_path),cases=rows,selected=selected,
        outputHashes=outputs,allConverged=all(r['fit']['success'] for r in rows),seconds=time.perf_counter()-started)
    (root/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('COMPLETE',selected,'allConverged',result['allConverged'],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('prepare','measure'))
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    (prepare if args.mode=='prepare' else measure)(args)


if __name__=='__main__':main()
