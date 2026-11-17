#!/usr/bin/env python3
"""Resume the frozen v2 protocol sequentially after a verified process failure."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

spec=importlib.util.spec_from_file_location('recover_probe',Path(__file__).with_name('appearance_compensation_probe_v2.py'))
v=importlib.util.module_from_spec(spec);sys.modules[spec.name]=v;spec.loader.exec_module(v)
m=v.variant


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('directory',type=Path)
    args=ap.parse_args();root=args.directory;started=time.perf_counter()
    if (root/'results.json').exists():raise ValueError('experiment already completed')
    recipe_path=root/'proposals.json';recipe=json.loads(recipe_path.read_text())
    for path,sha in recipe['inputHashes'].items():
        if digest(path)!=sha:raise ValueError(f'changed frozen input: {path}')
    data=json.loads((root/'partial.json').read_text());rows=data['cases']
    if data['recipeSha256']!=digest(recipe_path):raise ValueError('journal recipe differs')
    cases=[dict(id='current')]+recipe['proposals'];ids=[case['id'] for case in cases]
    if [row['id'] for row in rows]!=ids[:len(rows)]:raise ValueError('journal is not a complete prefix')
    recovery_path=root/'recovery.json'
    if not recovery_path.exists():
        recovery=dict(reason='parent session85465 exited1 with NumPy allocation failure; parallel refinement stopped',
            originalRecipeSha256=digest(recipe_path),originalJournalSha256=digest(root/'partial.json'),
            inheritedCases=[row['id'] for row in rows],scriptSha256=digest(__file__),
            inheritedNormalHashes={str(root/f'{r["id"]}-normals.npz'):digest(root/f'{r["id"]}-normals.npz') for r in rows},
            solver='unchanged Problem.fit from frozen v2, 200 iterations, zero start; one case at a time')
        recovery_path.write_text(json.dumps(recovery,indent=2)+'\n')
    recovery=json.loads(recovery_path.read_text())
    if recovery['scriptSha256']!=digest(__file__) or recovery['originalRecipeSha256']!=digest(recipe_path):
        raise ValueError('recovery implementation or recipe changed')
    for path,sha in recovery['inheritedNormalHashes'].items():
        if digest(path)!=sha:raise ValueError('inherited normals changed')
    source,source_faces,_=m.p.load_capture(Path(recipe['capture']));saved=np.load(recipe['checkpoint'])
    current=saved['positions'];current_faces=saved['triangles']
    fitting=[m.p.camera(source,a,recipe['size']) for a in recipe['fitAngles']]
    testing=[m.p.camera(source,a,recipe['size']) for a in recipe['testAngles']]
    lighting=m.lights();relight=m.lights(recipe['testLightRotation']);sn=m.s.vertex_normals(source,source_faces)
    fit_targets=[];fit_geometry=[];test_targets=[]
    for transform in fitting:
        view=m.View(source,source_faces,transform);fit_targets.append(view.render(sn,lighting))
        fit_geometry.append(m.p.filtered(view.geometry_raw,.9,3))
    for transform in testing:
        view=m.View(source,source_faces,transform);test_targets.append((view.render(sn,lighting),view.render(sn,relight)))
    for index,case in enumerate(cases):
        start=time.perf_counter();ps=current.copy();fs=current_faces.copy()
        if case['id']!='current':
            ps[case['keep']]=case['target'];fs[fs==case['remove']]=case['keep']
            fs=fs[(fs[:,0]!=fs[:,1])&(fs[:,1]!=fs[:,2])&(fs[:,2]!=fs[:,0])]
            if len(fs)!=len(current_faces)-2:raise ValueError('face budget differs')
        problem=m.Problem(ps,fs,fitting,fit_targets,lighting)
        if index<len(rows):
            row=rows[index];x=np.asarray(row['fit']['parameters']);normals,_=problem.normals(x)
            np.testing.assert_allclose(normals,np.load(root/f'{case["id"]}-normals.npz')['normals'],atol=1e-14)
            score,_=problem.objective(x)
            np.testing.assert_allclose(score,row['fit']['fittedSSE'],rtol=1e-11,atol=1e-11)
            print('VALIDATED inherited',case['id'],flush=True);continue
        geometry=sum(float(np.square(m.p.filtered(view.geometry_raw,.9,3)-target).sum())
            for view,target in zip(problem.views,fit_geometry))
        normals,report=problem.fit(recipe['iterations']);fit_seconds=time.perf_counter()-start
        reference=0.
        for view,target in zip(problem.views,fit_targets):
            image=m.s.filter_rgb(m.s.shade(view.projected,fs,normals,view.owners,view.forward,3))
            reference+=float(np.square(image-target).sum())
        np.testing.assert_allclose(reference,report['fittedSSE'],rtol=1e-11,atol=1e-11)
        views=[]
        for angle,transform,pair in zip(recipe['testAngles'],testing,test_targets):
            view=m.View(ps,fs,transform);entry=dict(angle=angle)
            for label,lights,target in zip(('original','rotated'),(lighting,relight),pair):
                entry[label]=dict(fixedSSE=float(np.square(view.render(problem.initial,lights)-target).sum()),
                    fittedSSE=float(np.square(view.render(normals,lights)-target).sum()))
            views.append(entry)
        np.savez_compressed(root/f'{case["id"]}-normals.npz',normals=normals)
        rows.append(dict(**case,triangles=len(fs),geometryFitSSE=geometry,fit=report,fitSeconds=fit_seconds,
            totalSeconds=time.perf_counter()-start,views=views,
            test={label:{mode:sum(view[label][mode] for view in views) for mode in ('fixedSSE','fittedSSE')}
                for label in ('original','rotated')}))
        temporary=root/'partial.tmp';temporary.write_text(json.dumps(dict(recipeSha256=digest(recipe_path),cases=rows),indent=2)+'\n')
        temporary.replace(root/'partial.json')
        print('RECOVERED',case['id'],report['fittedSSE'],report['message'],flush=True)
    base=rows[0];candidates=rows[1:]
    selected=dict(qem=min(candidates,key=lambda r:r['qem'])['id'],
        geometry=min(candidates,key=lambda r:r['geometryFitSSE'])['id'],
        fixedRGB=min(candidates,key=lambda r:r['fit']['initialSSE'])['id'],
        fittedRGB=min(candidates,key=lambda r:r['fit']['fittedSSE'])['id'])
    for row in candidates:
        row['fit']['deltaFittedSSE']=row['fit']['fittedSSE']-base['fit']['fittedSSE']
        row['fit']['deltaFixedSSE']=row['fit']['initialSSE']-base['fit']['initialSSE']
    result=dict(scope=recipe['scope'],recipeSha256=digest(recipe_path),recoverySha256=digest(recovery_path),
        cases=rows,selected=selected,outputHashes={str(root/f'{r["id"]}-normals.npz'):digest(root/f'{r["id"]}-normals.npz') for r in rows},
        allConverged=all(r['fit']['success'] for r in rows),seconds=time.perf_counter()-started,
        timingScope='recovery invocation only; inherited per-case timings retained; failed/paused work excluded')
    (root/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('COMPLETE RECOVERED',selected,flush=True)


if __name__=='__main__':main()
