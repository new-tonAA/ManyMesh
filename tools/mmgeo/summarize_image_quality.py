#!/usr/bin/env python3
"""Hash-bound policy quality summary; requires all requested assets to be complete."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--assets',nargs='+',default=['torus','monkey','pirate'])
    args=ap.parse_args();hashes={};rows=[];progressive=[]
    policies=('progressive-baseline','source-contour-control','visible-contour-control','progressive-image-control')
    fig,axes=plt.subplots(1,len(args.assets),figsize=(4.2*len(args.assets),3.8),squeeze=False,constrained_layout=True)
    for ax,name in zip(axes[0],args.assets):
        rgb_path=Path(f'out/shading-controls/{name}.json');rgb=json.loads(rgb_path.read_text())
        hashes[str(rgb_path)]=hashlib.sha256(rgb_path.read_bytes()).hexdigest()
        geometry={}
        for policy in policies:
            root=Path('out')/policy/name;path=root/'evaluation.json'
            evaluation=json.loads(path.read_text())
            hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            if hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()!=evaluation['manifestSha256']:
                raise ValueError('stale geometry evaluation')
            digest=rgb['inputHashes'].get(str(root/'manifest.json'))
            if digest!=evaluation['manifestSha256']:
                raise ValueError('RGB and geometry use different manifests')
            if rgb['inputHashes'][str(Path(f'out/filter-real-candidates/{name}.json'))]!=evaluation['captureSha256']:
                raise ValueError('RGB and geometry use different sources')
            if not any(Path(k).name=='depth_candidate_pilot.py' and digest==evaluation['rasterSha256']
                       for k,digest in rgb['inputHashes'].items()):
                raise ValueError('RGB and geometry use different raster versions')
            geometry[policy]=evaluation
        base=geometry['progressive-baseline']['levels'][rgb['ratio']]
        base_rgb=rgb['policies'][str(Path('out')/'progressive-baseline'/name)]
        for policy in policies:
            geom=geometry[policy]['levels'][rgb['ratio']]
            shade=rgb['policies'][str(Path('out')/policy/name)]
            if [v['angle'] for v in geom['views']]!=[v['angle'] for v in shade['views']]:
                raise ValueError('geometry/RGB camera populations differ')
            if [v['angle'] for v in base['views']]!=[v['angle'] for v in shade['views']]:
                raise ValueError('policy camera populations differ')
            if geom['topology']['triangles']!=base['topology']['triangles'] or shade['triangles']!=base_rgb['triangles']:
                raise ValueError('actual face budgets differ')
            x=geom['sumSSE']/base['sumSSE'];y=shade['sumRgbSSE']/base_rgb['sumRgbSSE']
            row=dict(asset=name,policy=policy,triangles=shade['triangles'],
                geometryReduction=1-x,rgbReduction=1-y,
                rgbRegressedViews=sum(v['rgbSSE']>b['rgbSSE']+1e-12 for v,b in zip(shade['views'],base_rgb['views'])))
            rows.append(row);ax.scatter(x,y,label=policy.replace('progressive-','').replace('-control',''))
        ax.axvline(1,color='gray',ls='--',lw=.8);ax.axhline(1,color='gray',ls='--',lw=.8)
        ax.set(title=name,xlabel='Coverage/depth SSE / QEM',ylabel='Controlled RGB SSE / QEM')
        ax.legend(fontsize=7);ax.grid(alpha=.2)
        im=geometry['progressive-image-control'];qem=geometry['progressive-baseline']
        manifest=json.loads(Path(f'out/progressive-image-control/{name}/manifest.json').read_text())
        for ratio,g in im['levels'].items():
            b=qem['levels'][ratio];matched=g['topology']['triangles']==b['topology']['triangles']
            progressive.append(dict(asset=name,ratio=ratio,triangles=g['topology']['triangles'],matched=matched,
                geometryReduction=1-g['sumSSE']/b['sumSSE'] if matched else None,
                worseViews=sum(v['total']>r['total']+1e-12 for v,r in zip(g['views'],b['views']))))
        print(name,'image timing',manifest['timing'],flush=True)
    fig.suptitle('Fixed actual face count; development scenes; derived normals, no textures')
    target=Path('out/shading-controls');fig.savefig(target/'quality-proxy-tradeoff.png',dpi=160);plt.close(fig)
    result=dict(scope='completed requested assets only; controlled shading not full appearance',assets=args.assets,
        hashes=hashes,scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shading=rows,progressiveGeometry=progressive)
    (target/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
