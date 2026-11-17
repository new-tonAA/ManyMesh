#!/usr/bin/env python3
"""Compare real-mesh directional continuity at the saved v1 fitting cliff."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


old=load('continuity_old','normal_fit_control.py')
new=load('continuity_new','normal_fit_control_v2.py')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def problem(module,recipe,source,faces,snapshot):
    transforms=[module.p.camera(source,a,recipe['size']) for a in recipe['fitAngles']]
    source_normals=module.s.vertex_normals(source,faces);lighting=module.lights()
    targets=[module.View(source,faces,t).render(source_normals,lighting) for t in transforms]
    return module.Problem(snapshot['positions'],snapshot['triangles'],transforms,targets,lighting)


def main():
    root=Path('out/appearance-compensation-torus-v1');recipe_path=root/'proposals.json'
    recipe=json.loads(recipe_path.read_text());audit_path=root/'stationarity-current.json'
    audit=json.loads(audit_path.read_text())
    if audit['recipeSha256']!=digest(recipe_path):raise ValueError('audit recipe changed')
    for path,sha in recipe['inputHashes'].items():
        if digest(path)!=sha:raise ValueError(f'old input changed: {path}')
    source,faces,_=old.p.load_capture(Path(recipe['capture']));snapshot=np.load(recipe['checkpoint'])
    first=problem(old,recipe,source,faces,snapshot);second=problem(new,recipe,source,faces,snapshot)
    x=np.asarray(audit['solver']['parameters']);_,g=first.objective(x);direction=-g/np.linalg.norm(g)
    rows=[]
    for label,probe in (('shading-facing-v1',first),('geometry-facing-v2',second)):
        value,g=probe.objective(x);derivative=float(g@direction);steps=[]
        for eps in (1e-3,1e-5,1e-7,1e-9):
            positive=probe.objective(x+eps*direction)[0];negative=probe.objective(x-eps*direction)[0]
            central=(positive-negative)/(2*eps)
            steps.append(dict(step=eps,plusDelta=positive-value,minusDelta=negative-value,
                centralDerivative=central,analyticDerivative=derivative,derivativeError=abs(central-derivative)))
        rows.append(dict(renderer=label,ownReferenceObjective=value,steps=steps));print(rows[-1],flush=True)
    # At step1e-7 the old cliff is crossed, whereas the new actual renderer matches its derivative.
    before=rows[0]['steps'][2];after=rows[1]['steps'][2]
    if before['derivativeError']<1e3 or after['derivativeError']>1e-5:
        raise ValueError('real-mesh discontinuity/repair diagnostic not reproduced')
    report=dict(scope='same saved geometry/normal parameters and direction; separate renderer references',
        hashes={str(path):digest(path) for path in (recipe_path,audit_path,Path(__file__),
            Path(old.__file__),Path(new.__file__))},models=rows)
    target=Path('out/appearance-facing-diagnosis');target.mkdir(exist_ok=True)
    (target/'continuity.json').write_text(json.dumps(report,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(6.4,4.2),constrained_layout=True)
    for row in rows:
        ax.loglog([r['step'] for r in row['steps']],[max(r['derivativeError'],1e-12) for r in row['steps']],
            'o-',label=row['renderer'])
    ax.set(xlabel='Normal parameter step along the same direction',
        ylabel='Absolute directional derivative discrepancy',title='Real Torus: attribute-facing cliff and geometric-facing control')
    ax.grid(alpha=.25);ax.legend()
    fig.savefig(target/'continuity.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()
