#!/usr/bin/env python3
"""Reference geometry-only progressive QEM with regenerated current-mesh candidates.

Standard baseline, no novelty claim. Separate capture units, boundary/nonmanifold locks,
edge link condition, duplicate-face rejection and local orientation/quality checks.
No UV/normal attributes, global surface-distance or self-intersection guarantee.
"""
import argparse
import hashlib
import heapq
import json
from pathlib import Path
import time

import numpy as np


class ProgressiveQEM:
    def __init__(self, positions, triangles, contour_directions=(), contour_strength=1.,
                 contour_weights=None):
        self.p=np.asarray(positions,dtype=float).reshape(-1,3).copy()
        self.f=np.asarray(triangles,dtype=int).reshape(-1,3).copy()
        if not np.isfinite(self.p).all():raise ValueError('finite positions required')
        if len(self.f) and (self.f.min()<0 or self.f.max()>=len(self.p)):
            raise ValueError('invalid index')
        self.alive=np.ones(len(self.f),bool)
        self.face_count=len(self.f)
        self.inc=[set() for _ in self.p]
        self.q=np.zeros((len(self.p),4,4))
        self.versions=np.zeros(len(self.p),dtype=int)
        self.locked=set();self.heap=[];self.actions=[];self.rejected=0
        edges={};seen=set();edge_faces={};normals=[]
        for fi,tri in enumerate(self.f):
            key=tuple(sorted(tri))
            if len(set(tri))!=3 or key in seen:raise ValueError('degenerate/duplicate input face')
            seen.add(key)
            a,b,c=self.p[tri];n=np.cross(b-a,c-a);length=np.linalg.norm(n)
            if length<=1e-15:raise ValueError('zero-area input face')
            n/=length;plane=np.r_[n,-np.dot(n,a)]
            normals.append(n.copy())
            quad=np.outer(plane,plane)*(length*.5)
            for v in tri:self.inc[v].add(fi);self.q[v]+=quad
            for u,v in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
                edge=tuple(sorted((int(u),int(v))));edges[edge]=edges.get(edge,0)+1
                edge_faces.setdefault(edge,[]).append(fi)
        self.contour_constraints=0
        self.contour_active_constraints=0
        directions=np.asarray(contour_directions,dtype=float).reshape(-1,3)
        if not np.isfinite(contour_strength) or contour_strength<0:
            raise ValueError('finite nonnegative contour strength required')
        if len(directions):
            if not np.isfinite(directions).all() or np.any(np.linalg.norm(directions,axis=1)==0):
                raise ValueError('finite nonzero view directions required')
            directions=directions/np.linalg.norm(directions,axis=1)[:,None]
            normals=np.asarray(normals)
            # Average source edge length makes edge-length weights comparable to face-area
            # weights. This is a fixed source-contour quadric control, not actual visibility.
            mean_edge=np.mean([np.linalg.norm(self.p[u]-self.p[v]) for u,v in edges])
            for (u,v),incident in sorted(edge_faces.items()):
                if len(incident)!=2:continue
                edge=self.p[v]-self.p[u];length=np.linalg.norm(edge)
                for di,direction in enumerate(directions):
                    signs=normals[incident]@direction
                    if signs[0]*signs[1]>=0:continue
                    normal=np.cross(edge,direction);scale=np.linalg.norm(normal)
                    if scale<=1e-15:continue
                    normal/=scale;plane=np.r_[normal,-np.dot(normal,self.p[u])]
                    visibility=1. if contour_weights is None else contour_weights[f'{u},{v},{di}']
                    if not np.isfinite(visibility) or not 0<=visibility<=1:
                        raise ValueError('contour weights must be in [0,1]')
                    quad=np.outer(plane,plane)*length*mean_edge*contour_strength*visibility/len(directions)
                    self.q[u]+=quad;self.q[v]+=quad;self.contour_constraints+=1
                    self.contour_active_constraints+=int(visibility*contour_strength>0)
        for edge,count in edges.items():
            if count!=2:self.locked.update(edge)
        # Bow-tie vertices can have two faces per edge but disconnected incident fans.
        for v,incident in enumerate(self.inc):
            if not incident:continue
            remaining=set(incident);stack=[remaining.pop()]
            while stack:
                fi=stack.pop();neighbors=set(self.f[fi])-{v}
                linked=[fj for fj in remaining if neighbors.intersection(self.f[fj])]
                for fj in linked:remaining.remove(fj);stack.append(fj)
            if remaining:self.locked.add(v)
        for u,v in sorted(edges):self.push(u,v)

    def neighbors(self,v):
        return set(int(i) for fi in self.inc[v] for i in self.f[fi])-{v}

    def placement_costs(self, u, v):
        quadric = self.q[u] + self.q[v]
        points = [self.p[u], self.p[v], (self.p[u] + self.p[v]) * .5]
        linear = quadric[:3, :3]
        if np.linalg.cond(linear) < 1e10:
            target = np.linalg.solve(linear, -quadric[:3, 3])
            if np.isfinite(target).all():
                points.append(target)
        for index, point in enumerate(points):
            h = np.r_[point, 1.]
            yield max(0.0, float(h @ quadric @ h)), index, tuple(point)

    def push(self,u,v):
        u,v=sorted((int(u),int(v)))
        if u in self.locked or v in self.locked or not self.inc[u] or not self.inc[v]:return
        # Each placement has its own queue entry. If the optimal placement fails a gate,
        # its next alternative competes at its own QEM cost rather than being hidden.
        for cost,index,point in self.placement_costs(u, v):
            heapq.heappush(self.heap,(cost,u,v,int(self.versions[u]),int(self.versions[v]),
                                      index,point))

    def legal_placements(self, entry):
        """Enumerate distinct legal placements for an edge from the current shortlist."""
        _, u, v, vu, vv, _, first = entry
        yield entry
        seen = {first}
        for cost, index, point in sorted(self.placement_costs(u, v)):
            if point not in seen and self.legal(u, v, np.asarray(point)):
                yield cost, u, v, vu, vv, index, point
                seen.add(point)

    def legal(self,u,v,target):
        shared=self.inc[u]&self.inc[v]
        if len(shared)!=2:return False
        opposite=set(int(x) for fi in shared for x in self.f[fi])-{u,v}
        if self.neighbors(u)&self.neighbors(v)!=opposite:return False
        affected=self.inc[u]|self.inc[v];keys=set()
        for fi in affected-shared:
            old=self.p[self.f[fi]]
            tri=self.f[fi].copy();tri[tri==v]=u
            key=tuple(sorted(tri))
            if key in keys:return False
            keys.add(key)
            new=self.p[tri].copy();new[tri==u]=target
            before=np.cross(old[1]-old[0],old[2]-old[0])
            after=np.cross(new[1]-new[0],new[2]-new[0])
            lb,la=np.linalg.norm(before),np.linalg.norm(after)
            if la<=1e-15 or np.dot(before,after)<.1*lb*la:return False
            def quality(x,length):
                return 2*np.sqrt(3)*length/np.square(x-np.roll(x,1,axis=0)).sum()
            if quality(new,la)<min(.02,quality(old,lb))-1e-12:return False
        return True

    def shortlist(self, limit):
        """Peek at distinct live edges, keeping each edge's cheapest legal placement."""
        chosen = []
        retained = []
        seen = set()
        while len(chosen) < limit and self.heap:
            entry = heapq.heappop(self.heap)
            _, u, v, vu, vv, _, point = entry
            if vu != self.versions[u] or vv != self.versions[v]:
                continue
            if not self.inc[u] or not self.inc[v]:
                continue
            edge = (u, v)
            if edge in seen:
                retained.append(entry)
                continue
            if not self.legal(u, v, np.asarray(point)):
                self.rejected += 1
                continue
            seen.add(edge)
            retained.append(entry)
            chosen.append(entry)
        for entry in retained:
            heapq.heappush(self.heap, entry)
        return chosen

    def accept(self, entry):
        """Apply a placement returned by shortlist at the current mesh epoch."""
        cost, u, v, vu, vv, _, point = entry
        if vu != self.versions[u] or vv != self.versions[v]:
            raise ValueError("cannot accept a stale QEM placement")
        affected = self.inc[u] | self.inc[v]
        touched = {int(i) for fi in affected for i in self.f[fi]}
        old_u, old_v = self.p[u].tolist(), self.p[v].tolist()
        for fi in affected:
            for vertex in self.f[fi]:
                self.inc[vertex].discard(fi)
            self.f[fi][self.f[fi] == v] = u
            if len(set(self.f[fi])) < 3:
                self.alive[fi] = False
                self.face_count -= 1
            else:
                for vertex in self.f[fi]:
                    self.inc[vertex].add(fi)
        self.p[u] = point
        self.q[u] += self.q[v]
        self.q[v] = 0
        for vertex in touched:
            self.versions[vertex] += 1
        self.actions.append(dict(keep=u, remove=v, target=list(point), qem=cost,
                                 oldKeep=old_u, oldRemove=old_v, faces=self.face_count))
        # Link and normal tests can change on edges with stationary endpoints.
        edges = {tuple(sorted((vertex, neighbor)))
                 for vertex in touched for neighbor in self.neighbors(vertex)}
        for a, b in sorted(edges):
            self.push(a, b)
        if len(self.heap) > max(10000, self.face_count * 40):
            self.heap = [e for e in self.heap if e[3] == self.versions[e[1]] and
                         e[4] == self.versions[e[2]]]
            heapq.heapify(self.heap)

    def advance(self, target_triangles):
        while self.face_count > target_triangles:
            shortlist = self.shortlist(1)
            if not shortlist:
                break
            self.accept(shortlist[0])
        return self.face_count


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture',type=Path);ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--policy',choices=('qem','source-contour'),default='qem')
    ap.add_argument('--contour-filter',choices=('all','visible','strength-matched'),default='all')
    ap.add_argument('--visibility-json',type=Path)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    source=json.loads(args.capture.read_text());ratios=(.75,.5,.25)
    visibility=None
    if args.contour_filter!='all':
        if args.policy!='source-contour' or not args.visibility_json:
            ap.error('visibility filtering requires source-contour and visibility-json')
        visibility=json.loads(args.visibility_json.read_text())
        if visibility['captureSha256']!=hashlib.sha256(args.capture.read_bytes()).hexdigest():
            raise ValueError('visibility source hash mismatch')
    units=[];snapshots={ratio:[] for ratio in ratios};start=time.perf_counter()
    for ui,unit in enumerate(source['units']):
        if not unit['triangles']:continue
        # Normalize once per source unit, never renormalize levels; avoid scale-dependent gates.
        raw=np.asarray(unit['positions'],float);center=(raw.min(0)+raw.max(0))*.5
        radius=max(float(np.linalg.norm(raw-center,axis=1).max()),1e-12)
        fit_angles=.13+2*np.pi*np.arange(8)/8
        directions=[[np.sin(angle),.37,np.cos(angle)] for angle in fit_angles]
        if visibility is not None and visibility['angles']!=fit_angles.tolist():
            raise ValueError('visibility construction views differ')
        weights=visibility['units'][ui]['weights'] if args.contour_filter=='visible' else None
        strength=visibility['units'][ui]['matchedStrength'] if args.contour_filter=='strength-matched' else 1.
        solver=ProgressiveQEM((raw-center)/radius,unit['triangles'],
                              directions if args.policy=='source-contour' else (),strength,weights);n=len(solver.f)
        levels=[]
        for ratio in ratios:
            target=max(4,int(n*ratio));actual=solver.advance(target)
            positions=solver.p*radius+center;faces=solver.f[solver.alive].copy()
            snapshots[ratio].append((positions.copy(),faces))
            levels.append(dict(ratio=ratio,target=target,actual=actual,applied=len(solver.actions),
                               rejected=solver.rejected,reached=actual<=target,
                               exhausted=not bool(solver.heap)))
            print(args.capture.stem,ui,ratio,actual,'/',target,flush=True)
        units.append(dict(unit=ui,sourceTriangles=n,lockedVertices=len(solver.locked),
                          levels=levels,normalizationRadius=radius,actions=solver.actions,
                          contourConstraints=solver.contour_constraints,
                          activeContourConstraints=solver.contour_active_constraints,
                          contourStrength=strength))
    artifacts={}
    for ratio,parts in snapshots.items():
        positions=[];faces=[];offset=0
        for ps,fs in parts:positions.extend(ps);faces.extend(fs+offset);offset+=len(ps)
        path=args.out/f'ratio-{ratio}.npz'
        np.savez_compressed(path,positions=positions,triangles=faces)
        artifacts[str(ratio)]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   triangles=len(faces))
    result=dict(scope='standard regenerated QEM baseline, geometry only; not production Corner',
                policy=args.policy,
                contourFitAngles=fit_angles.tolist() if args.policy=='source-contour' else [],
                contourStrength=1.,
                contourFilter=args.contour_filter,
                visibilitySha256=hashlib.sha256(args.visibility_json.read_bytes()).hexdigest()
                    if visibility is not None else None,
                captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                units=units,artifacts=artifacts,seconds=time.perf_counter()-start)
    (args.out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
