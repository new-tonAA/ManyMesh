#!/usr/bin/env python3
"""Compare exact-retention reference controls without selecting favorable views."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',type=Path,default=Path('out/progressive-baseline'))
    ap.add_argument('--control',type=Path,default=Path('out/source-contour-control'))
    args=ap.parse_args();rows=[];hashes={}
    fig,axes=plt.subplots(1,3,figsize=(12,3.8),constrained_layout=True)
    for ax,name in zip(axes,('torus','monkey','pirate')):
        paths=[root/name/'evaluation.json' for root in (args.baseline,args.control)]
        a,b=(json.loads(path.read_text()) for path in paths)
        for path in paths:hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        if a['captureSha256']!=b['captureSha256'] or a['rasterSha256']!=b['rasterSha256']:
            raise ValueError('source or raster implementation mismatch')
        asset=[]
        for ratio,control in b['levels'].items():
            baseline=a['levels'][ratio]
            if [r['angle'] for r in baseline['views']]!=[r['angle'] for r in control['views']]:
                raise ValueError('camera population mismatch')
            matched=baseline['topology']['triangles']==control['topology']['triangles']
            asset.append(dict(asset=name,requestedRatio=float(ratio),
                actualRatio=control['actualRatio'],matchedFaces=matched,
                baselineFaces=baseline['topology']['triangles'],controlFaces=control['topology']['triangles'],
                baselineSSE=baseline['sumSSE'],controlSSE=control['sumSSE'],
                relativeReduction=1-control['sumSSE']/baseline['sumSSE'] if matched and baseline['sumSSE'] else None,
                regressedViews=sum(y['total']>x['total']+1e-12 for x,y in
                                   zip(baseline['views'],control['views'])),
                topologyUnchanged={key:control['topology'][key]==b['source'][key] for key in
                    ('boundaryEdges','euler','nonmanifoldEdges','duplicateFaces','zeroAreaFaces')}))
        rows.extend(asset)
        for label,key in [('QEM','baselineSSE'),('Source contour','controlSSE')]:
            ordered=sorted(asset,key=lambda r:r['actualRatio'])
            ax.plot([r['actualRatio']*100 for r in ordered],[r[key]/12 for r in ordered],
                    'o-',label=label)
        ax.set(xlabel='Actual triangles retained (%)',ylabel='Mean two-channel SSE / view',title=name)
        ax.set_yscale('log');ax.grid(alpha=.25);ax.legend(fontsize=8)
    fig.suptitle('Classical controls on twelve development views; no material validation')
    fig.savefig(args.control/'comparison.png',dpi=160);plt.close(fig)
    result=dict(scope='same-source same-raster matched-actual-retention control comparison',
                inputHashes=hashes,scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),rows=rows)
    (args.control/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in rows:print(r['asset'],r['requestedRatio'],r['relativeReduction'],r['regressedViews'],flush=True)


if __name__=='__main__':main()
