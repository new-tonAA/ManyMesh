#!/usr/bin/env python3
"""Depth-aware legal-collapse diagnostic, not a production simplifier.

Fixed original-mesh normalization, orthographic continuous camera trajectory, two-sided
frontmost rasterization. Patch redraw includes unchanged occluders. Depth is bounded normalized
camera depth multiplied by coverage, with coverage reported separately. Low-resolution sketches
DO rasterize; full-resolution sketches are representation-only oracles, never claimed predictors.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


def load_capture(path):
    data = json.loads(path.read_text())
    positions, triangles, candidates = [], [], []
    vo = fo = 0
    for unit in data['units']:
        if not unit['triangles']:
            continue
        positions.extend(unit['positions'])
        triangles.extend(np.asarray(unit['triangles'], dtype=np.int64) + vo)
        for c in unit['candidates']:
            candidates.append(dict(c, remove=c['remove'] + vo, keep=c['keep'] + vo,
                                   affected=[t + fo for t in c['affected']]))
        vo += len(unit['positions'])
        fo += len(unit['triangles'])
    p = np.asarray(positions, dtype=float)
    t = np.asarray(triangles, dtype=np.int64)
    if not len(p) or not len(t) or not np.isfinite(p).all():
        raise ValueError('nonempty finite capture required')
    return p, t, candidates


def camera(positions, angle, size):
    center = (positions.min(0) + positions.max(0)) * .5
    radius = max(np.linalg.norm(positions - center, axis=1).max(), 1e-12)
    forward = np.array([math.sin(angle), .37, math.cos(angle)])
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0., 1., 0.]); right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return center, radius, np.stack((right, up, forward)), size


def project(positions, transform):
    center, radius, basis, size = transform
    q = ((np.asarray(positions) - center) / radius) @ basis.T
    # Larger depth is nearer; camera looks in -forward. All geometry lies in depth [0,1].
    return np.column_stack((size * (.5 + .43 * q[:, 0]),
                            size * (.5 - .43 * q[:, 1]), .5 + .5 * q[:, 2]))


def edited_geometry(p, triangles, candidate, transform):
    changed = p.copy()
    changed[candidate['keep']] = project(np.asarray([candidate['target']]), transform)[0]
    faces = triangles.copy()
    faces[faces == candidate['remove']] = candidate['keep']
    valid = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) &
             (faces[:, 2] != faces[:, 0]))
    # Keep original triangle IDs for tie-breaking and support validation.
    return changed, faces, valid


def support(p, triangles, c, transform, size, halo):
    affected = triangles[np.asarray(c['affected'], dtype=int)]
    if not len(affected):
        return None
    xy = np.concatenate((p[affected.reshape(-1), :2],
                         project(np.asarray([c['target']]), transform)[:, :2]))
    lo = np.floor(xy.min(0)).astype(int)
    hi = np.ceil(xy.max(0)).astype(int)
    # Test geometric support BEFORE adding filter halo.
    if hi[0] <= 0 or hi[1] <= 0 or lo[0] >= size or lo[1] >= size:
        return None
    lo = np.maximum(0, lo - halo)
    hi = np.minimum(size, hi + halo)
    return int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])


def raster(p, triangles, valid, rect, scale):
    x0, y0, x1, y1 = rect
    width, height = (x1-x0)*scale, (y1-y0)*scale
    z = np.full((height, width), -np.inf)
    owner = np.full((height, width), -1, dtype=np.int64)
    tri = p[triangles]
    lo = tri[:, :, :2].min(1)
    hi = tri[:, :, :2].max(1)
    active = np.flatnonzero(valid & (hi[:, 0] >= x0) & (lo[:, 0] <= x1) &
                            (hi[:, 1] >= y0) & (lo[:, 1] <= y1))
    for face in active:
        a, b, c = tri[face]
        area = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        if abs(area) < 1e-14:
            continue
        left = max(0, math.ceil((lo[face,0]-x0)*scale-.5))
        right = min(width, math.floor((hi[face,0]-x0)*scale-.5)+1)
        top = max(0, math.ceil((lo[face,1]-y0)*scale-.5))
        bottom = min(height, math.floor((hi[face,1]-y0)*scale-.5)+1)
        if left >= right or top >= bottom:
            continue
        yy, xx = np.mgrid[top:bottom, left:right]
        dx, dy = x0+(xx+.5)/scale-a[0], y0+(yy+.5)/scale-a[1]
        u = (dx*(c[1]-a[1])-dy*(c[0]-a[0]))/area
        v = ((b[0]-a[0])*dy-(b[1]-a[1])*dx)/area
        inside = (u >= -1e-10) & (v >= -1e-10) & (u+v <= 1+1e-10)
        depth = a[2] + u*(b[2]-a[2]) + v*(c[2]-a[2])
        old = z[top:bottom,left:right]
        wins = inside & (depth > old)
        old[wins] = depth[wins]
        owner[top:bottom,left:right][wins] = face
    cover = owner >= 0
    return np.stack((cover.astype(float), np.where(cover, z, 0.)), axis=-1), owner


def gaussian(sigma, scale):
    radius = math.ceil(4*sigma*scale)
    k = np.exp(-.5*(np.arange(-radius,radius+1)/(sigma*scale))**2)
    return k/k.sum()


def filtered(raw, sigma, scale):
    k = gaussian(sigma, scale)
    r = len(k)//2
    image = raw
    for axis in (0,1):
        pad = [(0,0)]*image.ndim; pad[axis] = (r,r)
        padded = np.pad(image,pad)
        result = np.zeros_like(image)
        for i,w in enumerate(k):
            sl = [slice(None)]*image.ndim
            sl[axis] = slice(i,i+image.shape[axis])
            result += w*padded[tuple(sl)]
        image = result
    h,w = image.shape[:2]
    return image.reshape(h//scale,scale,w//scale,scale,2).mean(axis=(1,3))


def dct_basis(height, width, dimensions=32):
    # Exactly dimensions real coefficients TOTAL across two channels, not per row/channel.
    modes = sorted(((x+y,y,x) for y in range(height) for x in range(width)))
    basis=[]; channels=[]
    yy=np.arange(height)+.5; xx=np.arange(width)+.5
    for _,v,u in modes:
        by=np.cos(np.pi*v*yy/height)*math.sqrt((1 if v==0 else 2)/height)
        bx=np.cos(np.pi*u*xx/width)*math.sqrt((1 if u==0 else 2)/width)
        b=by[:,None]*bx[None,:]
        for channel in range(2):
            basis.append(b); channels.append(channel)
            if len(basis)==dimensions:
                return np.asarray(basis),np.asarray(channels)
    return np.asarray(basis),np.asarray(channels)


def sketch(residual, basis):
    b,channels=basis
    return np.einsum('khw,hwk->k',b,residual[:,:,channels])


def metrics(residual):
    values=np.square(residual).sum(axis=(0,1))
    return dict(coverage=float(values[0]),depth=float(values[1]),total=float(values.sum()))


def patch_residual(p, triangles, valid, rect, scale, sigma, base_raw):
    start=time.perf_counter()
    changed,_=raster(p,triangles,valid,rect,scale)
    x0,y0,x1,y1=rect
    delta=changed-base_raw[y0*scale:y1*scale,x0*scale:x1*scale]
    residual=filtered(delta,sigma,scale)
    return residual,time.perf_counter()-start


def write_overlay(directory, p, changed, triangles, c, rect, base, image, residual, label):
    # Geometry rendering diagnostic, not a statistical chart. Fixed mapping, no per-image exposure.
    from PIL import Image, ImageDraw
    directory.mkdir(parents=True,exist_ok=True)
    rgb=np.repeat(np.clip(base[:,:,0,None],0,1),3,axis=2)
    overlay=Image.fromarray(np.uint8(rgb*180)).convert('RGB')
    draw=ImageDraw.Draw(overlay)
    affected=np.asarray(c['affected'],dtype=int)
    for face in triangles[affected]:
        pts=[tuple(p[i,:2]) for i in face]
        draw.line(pts+[pts[0]],fill=(255,120,40),width=1)
        indices=[c['keep'] if i==c['remove'] else i for i in face]
        if len(set(indices))<3: continue
        pts=[tuple(changed[i,:2]) for i in indices]
        draw.line(pts+[pts[0]],fill=(30,210,255),width=1)
    x,y=changed[c['keep'],:2]
    draw.ellipse((x-2,y-2,x+2,y+2),fill=(255,255,0))
    draw.rectangle(rect,outline=(150,150,150),width=1)
    overlay.resize((overlay.width*4,overlay.height*4),Image.Resampling.NEAREST).save(directory/(label+'-overlay.png'))
    for name,values in [('reference',base[:,:,1]),('candidate',image[:,:,1]),
                        ('error-32x',np.abs(residual[:,:,1])*32)]:
        Image.fromarray(np.uint8(np.clip(values,0,1)*255)).resize(
            (base.shape[1]*4,base.shape[0]*4),Image.Resampling.NEAREST).save(directory/(label+'-'+name+'.png'))


def run(args):
    positions,triangles,candidates=load_capture(args.capture)
    sigma=.9; scale=args.scale; size=args.size
    # New trajectory, distinct from the earlier 0.2,1.7,3.4 rad development views.
    angles=np.linspace(2.13,2.48,args.frames)
    report=dict(scope='real development assets; new contiguous orthographic trajectory; no PBR',
                representation='8/16/32 total real DCT coefficients of coverage+premultiplied depth',
                warning='coarse predictor uses rasterization; exact sketch is a representation oracle',
                captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                size=size,scale=scale,sigma=sigma,sourceTriangles=len(triangles),
                trajectoryFrozen=True,frames=[])
    previous={}
    for frame,angle in enumerate(angles):
        start=time.perf_counter()
        transform=camera(positions,float(angle),size)
        p=project(positions,transform)
        full=(0,0,size,size); valid=np.ones(len(triangles),dtype=bool)
        raw,owners=raster(p,triangles,valid,full,scale)
        coarse_raw,_=raster(p,triangles,valid,full,1)
        base=filtered(raw,sigma,scale)
        visible=set(np.unique(owners[owners>=0]).tolist())
        screen=dict(total=len(candidates),outside=0,visibleSupport=0,noBaselineVisibleFace=0)
        pool=[]
        for index,c in enumerate(candidates):
            rect=support(p,triangles,c,transform,size,math.ceil(4*sigma)+2)
            if rect is None:
                screen['outside']+=1; continue
            vis=bool(visible.intersection(c['affected']))
            screen['visibleSupport' if vis else 'noBaselineVisibleFace']+=1
            # Retain potentially disoccluding candidates: no baseline visibility is not proof of
            # no future effect. Stratify, rather than silently dropping this group.
            pool.append((not vis,c['priority'],index,rect))
        selected=[]
        for hidden in (False,True):
            group=sorted([x for x in pool if x[0]==hidden])
            count=min(len(group),args.candidates if not hidden else max(1,args.candidates//4))
            if count:
                selected += [group[i] for i in np.unique(np.linspace(0,len(group)-1,count).astype(int))]
        screen['sampled']=len(selected)
        screen['notSampled']=len(pool)-len(selected)
        record=dict(frame=frame,angle=float(angle),screening=screen,
                    setupSeconds=time.perf_counter()-start,candidates=[])
        saved=False
        for hidden,priority,index,rect in selected:
            c=candidates[index]
            begin=time.perf_counter()
            changed,faces,alive=edited_geometry(p,triangles,c,transform)
            preparation=time.perf_counter()-begin
            residual,reference_seconds=patch_residual(changed,faces,alive,rect,scale,sigma,raw)
            coarse,coarse_seconds=patch_residual(changed,faces,alive,rect,1,sigma,coarse_raw)
            begin=time.perf_counter(); basis=dct_basis(*residual.shape[:2]); basis_seconds=time.perf_counter()-begin
            begin=time.perf_counter(); coefficients=sketch(coarse,basis); feature_seconds=time.perf_counter()-begin
            begin=time.perf_counter(); exact_coefficients=sketch(residual,basis); exact_seconds=time.perf_counter()-begin
            errors=metrics(residual)
            row=dict(id=index,baselineVisible=not hidden,priority=priority,
                     triangles=int(alive.sum()),rect=rect,metrics=errors,
                     preparationSeconds=preparation,patchSeconds=reference_seconds,
                     coarseRasterSeconds=coarse_seconds,basisSeconds=basis_seconds,
                     encodeSeconds=feature_seconds,oracleEncodeSeconds=exact_seconds,
                     predictions=[dict(dimensions=k,error=float(np.square(coefficients[:k]).sum()),
                        oracleRepresentationError=float(np.square(exact_coefficients[:k]).sum()))
                        for k in (8,16,32)])
            if errors['total']<=1e-14:
                row['uninformativeAtThisSampling']=True
            if index in previous and previous[index][0] == frame-1:
                # Fixed global image coordinates, not motion-compensated flicker. Explicitly label.
                old=previous[index][1]
                global_residual=np.zeros_like(base)
                x0,y0,x1,y1=rect; global_residual[y0:y1,x0:x1]=residual
                row['screenResidualChange']=float(np.square(global_residual-old).sum())
            else:
                global_residual=np.zeros_like(base)
                x0,y0,x1,y1=rect; global_residual[y0:y1,x0:x1]=residual
            previous[index]=(frame,global_residual)
            # Verify every sampled candidate against an independently full-image redraw.
            check_raw,_=raster(changed,faces,alive,full,scale)
            check_image=filtered(check_raw,sigma,scale)
            difference=float(np.max(np.abs(check_image-base-global_residual)))
            row['patchFullMaxDifference']=difference
            if difference>1e-10:
                raise AssertionError(f'patch/full mismatch {difference}, candidate {index}')
            if not saved and errors['total']>1e-14:
                write_overlay(args.out.parent/'images',p,changed,triangles,c,rect,base,
                              check_image,global_residual,f'{args.capture.stem}-{frame}-{index}')
                saved=True
            record['candidates'].append(row)
        record['uninformativeSampled']=sum(r.get('uninformativeAtThisSampling',False) for r in record['candidates'])
        report['frames'].append(record)
        args.out.write_text(json.dumps(report,indent=2)+'\n')
        print(args.capture.stem,frame,'sampled',len(selected),'zero',record['uninformativeSampled'],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--size',type=int,default=128)
    parser.add_argument('--scale',type=int,default=3)
    parser.add_argument('--frames',type=int,default=6)
    parser.add_argument('--candidates',type=int,default=8)
    args=parser.parse_args()
    if min(args.size,args.scale,args.frames,args.candidates)<1:
        parser.error('positive parameters required')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    run(args)


if __name__=='__main__':
    main()
