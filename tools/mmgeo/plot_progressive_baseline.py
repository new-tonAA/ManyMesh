#!/usr/bin/env python3
"""Export research baseline figures using fixed camera and shared image scales."""
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

spec=importlib.util.spec_from_file_location('figure_depth',Path(__file__).with_name('depth_candidate_pilot.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

root=Path('out/progressive-baseline')
fig,axes=plt.subplots(3,4,figsize=(12,8),constrained_layout=True)
for row,name in enumerate(('torus','monkey','pirate')):
    world,source,_=p.load_capture(Path(f'out/filter-real-candidates/{name}.json'))
    transform=p.camera(world,.52,128)
    variants=[('Source',world,source)]
    for ratio in ('.75','.5','.25'):
        data=np.load(root/name/f'ratio-{float(ratio)}.npz')
        variants.append((f"{100*len(data['triangles'])/len(source):.1f}% faces",data['positions'],data['triangles']))
    for col,(label,ps,fs) in enumerate(variants):
        image,_=p.raster(p.project(ps,transform),fs,np.ones(len(fs),bool),(0,0,128,128),3)
        # Premultiplied normalized camera depth, with one fixed grayscale mapping for all panels.
        image=p.filtered(image,.9,3)
        gray=np.clip(image[...,1],0,1)
        axes[row,col].imshow(gray,cmap='gray',vmin=0,vmax=1)
        axes[row,col].set_title(f'{name}: {label}\n{len(fs):,} triangles',fontsize=10)
        axes[row,col].axis('off')
fig.suptitle('Standard progressive QEM: fixed source normalization, coverage/depth only')
fig.savefig(root/'geometry-comparison.png',dpi=150)
plt.close(fig)

fig,axes=plt.subplots(1,3,figsize=(12,3.5),constrained_layout=True)
for ax,name in zip(axes,('torus','monkey','pirate')):
    report=json.loads((root/name/'evaluation.json').read_text())
    rows=sorted(report['levels'].values(),key=lambda x:x['actualRatio'])
    ax.plot([r['actualRatio']*100 for r in rows],[r['sumSSE']/12 for r in rows],'o-')
    ax.set(xlabel='Actual source triangles retained (%)',ylabel='Mean filtered SSE / view',title=name)
    ax.grid(alpha=.3)
fig.suptitle('12-view static orbit; different assets have separate error scales')
fig.savefig(root/'baseline-error-curves.png',dpi=160)
plt.close(fig)
