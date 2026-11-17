#!/usr/bin/env python3
"""Early rejection with a nonnegative partial sum, not heuristic image-error prediction.

For current residual r and a candidate's filtered change d supported on R:
  E_after - E_before = sum_R (r+d)^2 - sum_R r^2.
After evaluating disjoint output blocks B, a lower bound is
  sum_B (r+d)^2 - sum_R r^2.
The -sum_R r^2 term is ESSENTIAL after multiple collapses. Blocks include a filter halo before
cropping; no coarse sample is assumed representative. Exactness is relative to the existing
sampled renderer. Floating comparisons use an explicit margin, not a formal interval arithmetic
certificate. Branch-and-bound and partial-distance elimination are established techniques.
"""
import math
import numpy as np


def evaluate(cache, transaction, residual, rect, sigma, scale, filter_fn,
             incumbent=math.inf, block_size=8, margin=1e-12, edit=None):
    if block_size<1 or margin<0:
        raise ValueError('positive block size and nonnegative margin required')
    x0,y0,x1,y1=rect
    old=residual[y0:y1,x0:x1]
    removed_energy=float(np.square(old).sum())
    lower=-removed_energy
    blocks=[(x,y,min(x+block_size,x1),min(y+block_size,y1))
            for y in range(y0,y1,block_size) for x in range(x0,x1,block_size)]
    # Fixed center-first order; no use of reference future candidate loss.
    cx,cy=(x0+x1)*.5,(y0+y1)*.5
    blocks.sort(key=lambda b:((b[0]+b[2])*.5-cx)**2+((b[1]+b[3])*.5-cy)**2)
    halo=math.ceil(math.ceil(4*sigma*scale)/scale)
    count=0; resolved_samples=0; new_energy=0.
    for bx0,by0,bx1,by1 in blocks:
        hx0=max(0,bx0-halo); hy0=max(0,by0-halo)
        hx1=min(cache.size,bx1+halo); hy1=min(cache.size,by1+halo)
        expanded=(hx0,hy0,hx1,hy1)
        before=cache.resolve(expanded)
        after=(cache.resolve_edit(expanded,*edit) if edit is not None
               else cache.resolve(expanded,transaction))
        filtered=filter_fn(after-before,sigma,scale)
        delta=filtered[by0-hy0:by1-hy0,bx0-hx0:bx1-hx0]
        values=residual[by0:by1,bx0:bx1]+delta
        new_energy+=float(np.square(values).sum())
        lower=new_energy-removed_energy
        count+=1; resolved_samples+=(hx1-hx0)*(hy1-hy0)*scale*scale
        if lower>incumbent+margin and count<len(blocks):
            return dict(score=math.inf,lower=lower,pruned=True,blocks=count,
                        totalBlocks=len(blocks),resolvedSamples=resolved_samples)
    return dict(score=lower,lower=lower,pruned=False,blocks=count,
                totalBlocks=len(blocks),resolvedSamples=resolved_samples)
