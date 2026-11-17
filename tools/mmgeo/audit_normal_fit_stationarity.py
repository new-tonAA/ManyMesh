#!/usr/bin/env python3
"""Audit finite-fit stationarity near the actual two-sided shader's facing discontinuity."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('stationarity_fit',Path(__file__).with_name('normal_fit_control.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def facing(problem,x):
    normals,_=problem.normals(x);values=[]
    for view in problem.views:
        raw=np.einsum('ij,ijk->ik',view.weights,normals[view.ids]);n,_=m.normalized(raw)
        values.append(np.einsum('ij,j->i',n,view.forward))
    return values


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('directory',type=Path)
    args=ap.parse_args();root=args.directory;recipe_path=root/'proposals.json'
    recipe=json.loads(recipe_path.read_text())
    for path,sha in recipe['inputHashes'].items():
        if digest(path)!=sha:raise ValueError(f'changed input: {path}')
    data_path=root/'results.json'
    if not data_path.exists():data_path=root/'partial.json'
    data=json.loads(data_path.read_text());case=next(c for c in data['cases'] if c['id']=='current')
    if data['recipeSha256']!=digest(recipe_path):raise ValueError('recipe differs')
    source,source_faces,_=m.p.load_capture(Path(recipe['capture']));saved=np.load(recipe['checkpoint'])
    transforms=[m.p.camera(source,a,recipe['size']) for a in recipe['fitAngles']]
    source_normals=m.s.vertex_normals(source,source_faces);lighting=m.lights()
    targets=[m.View(source,source_faces,t).render(source_normals,lighting) for t in transforms]
    problem=m.Problem(saved['positions'],saved['triangles'],transforms,targets,lighting)
    x=np.array(case['fit']['parameters']);normals,_=problem.normals(x)
    normal_path=root/'current-normals.npz'
    np.testing.assert_allclose(normals,np.load(normal_path)['normals'],atol=1e-14,rtol=1e-14)
    value,gradient=problem.objective(x);np.testing.assert_allclose(value,case['fit']['fittedSSE'],atol=1e-12)
    direction=-gradient/np.linalg.norm(gradient);derivative=float(gradient@direction)
    before=facing(problem,x);rows=[]
    for eps in (1e-3,1e-5,1e-7,1e-9,1e-11):
        positive=x+eps*direction;negative=x-eps*direction
        if max(np.abs(positive).max(),np.abs(negative).max())>.5:raise ValueError('direction hits parameter bound')
        plus=problem.objective(positive)[0];minus=problem.objective(negative)[0]
        signs_plus=facing(problem,positive);signs_minus=facing(problem,negative)
        row=dict(step=eps,analyticDerivative=derivative,centralDerivative=(plus-minus)/(2*eps),
            plusDelta=plus-value,minusDelta=minus-value,
            plusFacingFlips=sum(int(np.sum((a<0)!=(b<0))) for a,b in zip(before,signs_plus)),
            minusFacingFlips=sum(int(np.sum((a<0)!=(b<0))) for a,b in zip(before,signs_minus)))
        rows.append(row);print(row,flush=True)
    report=dict(scope='current Torus local solve stationarity, diagnostic not a global optimizer',
        recipeSha256=digest(recipe_path),normalSha256=digest(normal_path),
        scriptSha256=digest(__file__),solver=case['fit'],objective=value,
        minimumAbsoluteFacing=[float(np.min(np.abs(v))) for v in before],directions=rows)
    (root/'stationarity-current.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
