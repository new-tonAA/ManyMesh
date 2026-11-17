#!/usr/bin/env python3
"""Bounded-pool progressive image-driven reference, standard method family.

Regenerates topology after every edit and measures cumulative, not standalone, error.
No novelty, production attribute, global intersection or real-time claim.
"""
import argparse
import hashlib
import heapq
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

q=load('image_qem','progressive_geometry_baseline.py')
p=load('image_depth','depth_candidate_pilot.py')
r=load('image_fragments','transactional_raster.py')


class Scene:
    def __init__(self,world,faces,size=128,scale=3,sigma=.9):
        self.world=world.copy();self.faces=faces.copy();self.valid=np.ones(len(faces),bool)
        self.size=size;self.scale=scale;self.sigma=sigma;self.views=[];self.evaluations=0
        self.score_seconds=0.;self.commit_seconds=0.;self.check_seconds=0.
        started=time.perf_counter()
        for angle in .13+2*np.pi*np.arange(3)/3:
            transform=p.camera(world,float(angle),size);projected=p.project(world,transform)
            cache=r.FragmentCache(projected,faces,size,scale)
            original=cache.resolve((0,0,size,size))
            self.views.append(dict(angle=float(angle),transform=transform,cache=cache,original=original,
                                   residual=np.zeros((size,size,2))))
        self.setup_seconds=time.perf_counter()-started

    def proposal(self,solver,vo,fo,center,radius,u,v,point):
        start=time.perf_counter();bundles=[];score=0.
        affected=sorted(solver.inc[u]|solver.inc[v])
        for view in self.views:
            triangles={};xy=[]
            target=p.project([center+radius*np.array(point)],view['transform'])[0]
            for fi in affected:
                before=p.project(solver.p[solver.f[fi]]*radius+center,view['transform'])
                xy.extend(before[:,:2])
                tri=solver.f[fi].copy();tri[tri==v]=u
                if len(set(tri))<3:continue
                after=p.project(solver.p[tri]*radius+center,view['transform']);after[tri==u]=target
                triangles[fo+fi]=after;xy.extend(after[:,:2])
            xy=np.asarray(xy);halo=int(np.ceil(4*self.sigma))+2
            lo=np.maximum(0,np.floor(xy.min(0)).astype(int)-halo)
            hi=np.minimum(self.size,np.ceil(xy.max(0)).astype(int)+halo)
            if np.any(hi<=lo):
                bundles.append(None);continue
            rect=(int(lo[0]),int(lo[1]),int(hi[0]),int(hi[1]))
            cache=view['cache'];global_faces=[fo+fi for fi in affected]
            before=cache.resolve(rect)
            after=cache.resolve_edit(rect,global_faces,triangles)
            delta=p.filtered(after-before,self.sigma,self.scale)
            x0,y0,x1,y1=rect;old=view['residual'][y0:y1,x0:x1]
            score+=float(np.square(old+delta).sum()-np.square(old).sum())
            bundles.append(dict(rect=rect,delta=delta,affected=global_faces,replacements=triangles))
        self.evaluations+=1;self.score_seconds+=time.perf_counter()-start
        return score,bundles

    def commit(self,bundles):
        start=time.perf_counter()
        for view,b in zip(self.views,bundles):
            if b is None:continue
            cache=view['cache'];transaction=cache.propose(b['affected'],b['replacements']);cache.commit(transaction)
            x0,y0,x1,y1=b['rect'];view['residual'][y0:y1,x0:x1]+=b['delta']
        self.commit_seconds+=time.perf_counter()-start

    def verify(self):
        start=time.perf_counter();errors=[]
        for view in self.views:
            projected=p.project(self.world,view['transform'])
            actual,_=p.raster(projected,self.faces,self.valid,(0,0,self.size,self.size),self.scale)
            cached=view['cache'].resolve((0,0,self.size,self.size))
            np.testing.assert_allclose(actual,cached,rtol=1e-10,atol=1e-12)
            residual=p.filtered(actual-view['original'],self.sigma,self.scale)
            np.testing.assert_allclose(residual,view['residual'],rtol=1e-8,atol=1e-11)
            errors.append(p.metrics(residual))
        self.check_seconds+=time.perf_counter()-start
        return errors


class ImageQEM(q.ProgressiveQEM):
    def __init__(self,positions,triangles,scene,vo,fo,center,radius,pool_edges=4):
        super().__init__(positions,triangles)
        self.scene=scene;self.vo=vo;self.fo=fo;self.center=center;self.radius=radius
        self.pool_edges=pool_edges

    def select(self):
        pool=[];restore=[];seen=set()
        while self.heap and len(pool)<self.pool_edges:
            entry=heapq.heappop(self.heap)
            cost,u,v,vu,vv,index,point=entry
            if vu!=self.versions[u] or vv!=self.versions[v] or not self.inc[u] or not self.inc[v]:continue
            if (u,v) in seen:restore.append(entry);continue
            if not self.legal(u,v,np.array(point)):self.rejected+=1;continue
            seen.add((u,v));pool.append(entry)
        if not pool:return None
        best=None
        for entry in pool:
            score,bundle=self.scene.proposal(self,self.vo,self.fo,self.center,self.radius,
                                             entry[1],entry[2],entry[6])
            if best is None or score<best[0]-1e-14:best=(score,entry,bundle)
        for entry in restore+pool:
            if entry!=best[1]:heapq.heappush(self.heap,entry)
        return best

    def advance(self,target_triangles):
        count=int(self.alive.sum())
        while count>target_triangles and self.heap:
            selected=self.select()
            if selected is None:break
            score,entry,bundle=selected
            cost,u,v,vu,vv,index,point=entry;target=np.array(point)
            affected=set(self.inc[u]|self.inc[v])
            touched=set(int(i) for fi in affected for i in self.f[fi])
            old_u=self.p[u].copy();old_v=self.p[v].copy()
            for fi in affected:
                for vertex in self.f[fi]:self.inc[vertex].discard(fi)
                self.f[fi][self.f[fi]==v]=u
                if len(set(self.f[fi]))<3:self.alive[fi]=False;count-=1
                else:
                    for vertex in self.f[fi]:self.inc[vertex].add(fi)
                self.scene.faces[self.fo+fi]=self.f[fi]+self.vo
                self.scene.valid[self.fo+fi]=self.alive[fi]
            self.p[u]=target;self.q[u]+=self.q[v];self.q[v]=0
            self.scene.world[self.vo+u]=self.center+self.radius*target
            self.scene.commit(bundle)
            for vertex in touched:self.versions[vertex]+=1
            self.actions.append(dict(keep=u,remove=v,target=list(point),qem=cost,
                imageDelta=score,oldKeep=old_u.tolist(),oldRemove=old_v.tolist(),faces=count))
            edges=set()
            for vertex in touched:
                for neighbor in self.neighbors(vertex):edges.add(tuple(sorted((vertex,neighbor))))
            for a,b in sorted(edges):self.push(a,b)
            if len(self.heap)>max(10000,count*40):
                self.heap=[e for e in self.heap if e[3]==self.versions[e[1]] and e[4]==self.versions[e[2]]]
                heapq.heapify(self.heap)
            if len(self.actions)%100==0:print('applied',len(self.actions),'remaining',count,flush=True)
        return count


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--pool-edges',type=int,default=4)
    args=ap.parse_args()
    if args.pool_edges<1:ap.error('positive edge pool required')
    args.out.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    world,faces,_=p.load_capture(args.capture);source=json.loads(args.capture.read_text())
    scene=Scene(world,faces);units=[];solvers=[];vo=fo=0
    for ui,unit in enumerate(source['units']):
        if not unit['triangles']:continue
        raw=np.asarray(unit['positions'],float);fs=np.asarray(unit['triangles'],int)
        center=(raw.min(0)+raw.max(0))*.5;radius=max(float(np.linalg.norm(raw-center,axis=1).max()),1e-12)
        solver=ImageQEM((raw-center)/radius,fs,scene,vo,fo,center,radius,args.pool_edges)
        solvers.append((ui,solver,center,radius));vo+=len(raw);fo+=len(fs)
    artifacts={};checks=[]
    # All units advance one level before writing a scene checkpoint; keep each unit's own locks.
    for ratio in (.75,.5,.25):
        levels=[]
        for ui,solver,center,radius in solvers:
            target=max(4,int(len(solver.f)*ratio));actual=solver.advance(target)
            levels.append(dict(unit=ui,target=target,actual=actual,reached=actual<=target,applied=len(solver.actions)))
        errors=scene.verify();checks.append(dict(ratio=ratio,levels=levels,fitErrors=errors))
        path=args.out/f'ratio-{ratio}.npz'
        np.savez_compressed(path,positions=scene.world,triangles=scene.faces[scene.valid])
        artifacts[str(ratio)]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   triangles=int(scene.valid.sum()))
        print(args.capture.stem,ratio,'actual faces',int(scene.valid.sum()),'fit SSE',sum(e['total'] for e in errors),flush=True)
    result=dict(scope='bounded-pool cumulative image-driven baseline; no original algorithm claim',
        poolEdges=args.pool_edges,fitAngles=[v['angle'] for v in scene.views],
        sourceHashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                      (args.capture,Path(__file__),Path(q.__file__),Path(p.__file__),Path(r.__file__))},
        captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),artifacts=artifacts,checkpoints=checks,
        units=[dict(unit=ui,actions=s.actions,rejected=s.rejected) for ui,s,_,_ in solvers],
        timing=dict(totalSeconds=time.perf_counter()-started,setupSeconds=scene.setup_seconds,
                    scoreSeconds=scene.score_seconds,commitSeconds=scene.commit_seconds,
                    validationSeconds=scene.check_seconds,candidateEvaluations=scene.evaluations))
    (args.out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
