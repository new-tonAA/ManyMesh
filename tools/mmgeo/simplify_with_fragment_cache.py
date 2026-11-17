#!/usr/bin/env python3
"""Execute real captured collapses using cumulative image error, not independent scalar scores.

Conservative conflict rule invalidates candidates whose original one-ring vertices intersect an
already modified one-ring. Fixed camera per sequence; every trajectory frame starts from source.
This is a limited batch simplifier, NOT unrestricted online progressive mesh or a novelty claim.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m

p=load('depth_reference','depth_candidate_pilot.py')
r=load('transaction_cache','transactional_raster.py')
b=load('bounded_error','bounded_candidate_error.py')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--steps',type=int,default=6)
    parser.add_argument('--bounded',action='store_true')
    parser.add_argument('--block-size',type=int,default=8)
    parser.add_argument('--lazy-fragments',action='store_true')
    args=parser.parse_args()
    report=json.loads(args.report.read_text())
    vertices,faces,candidates=p.load_capture(args.capture)
    size=128; scale=3; sigma=.9
    result=dict(scope='real asset conservative batch simplification; fixed camera per sequence',
                warning='not dynamic temporal LOD; geometry-only; no global self-intersection proof',
                frames=[])
    supports=[set(faces[np.asarray(c['affected'])].ravel().tolist()) for c in candidates]
    for frame in report['frames']:
        angle=np.linspace(2.13,2.48,6)[frame['frame']]
        transform=p.camera(vertices,float(angle),size)
        original=p.project(vertices,transform)
        # Identical pre-existing measured candidate set for both policies, no oracle filtering.
        pool=[item['id'] for item in frame['candidates']]
        output=[]
        policies=('corner','cumulative','bounded') if args.bounded else ('corner','cumulative')
        for policy in policies:
            start=time.perf_counter()
            positions=original.copy(); current_faces=faces.copy(); alive=np.ones(len(faces),bool)
            cache=r.FragmentCache(original,faces,size,scale)
            base_raw=cache.resolve((0,0,size,size)); base_image=p.filtered(base_raw,sigma,scale)
            residual=np.zeros_like(base_image); changed_vertices=set(); actions=[]
            evaluations=0; pruned=0; evaluated_blocks=0; all_blocks=0
            for step in range(args.steps):
                choices=[]; incumbent=float('inf')
                for cid in sorted(pool,key=lambda i:(candidates[i]['priority'],i)):
                    if supports[cid].intersection(changed_vertices): continue
                    c=candidates[cid]
                    new_position=p.project([c['target']],transform)[0]
                    replacement_faces={}; deleted=[]
                    for f in c['affected']:
                        ids=current_faces[f].copy(); ids[ids==c['remove']]=c['keep']
                        if len(set(ids))<3:
                            deleted.append(f); continue
                        tri=positions[ids].copy(); tri[ids==c['keep']]=new_position
                        replacement_faces[f]=tri
                    # Fixed equal reduction per action; do not compare boundary vs interior cost.
                    if len(deleted)!=2: continue
                    rect=p.support(positions,current_faces,c,transform,size,6)
                    if rect is None: continue
                    if policy=='corner':
                        choices.append((c['priority'],cid,None,rect,replacement_faces,deleted,new_position))
                        continue
                    lazy=policy=='bounded' and args.lazy_fragments
                    transaction=None if lazy else cache.propose(c['affected'],replacement_faces)
                    if policy=='bounded':
                        bound=b.evaluate(cache,transaction,residual,rect,sigma,scale,p.filtered,
                                         incumbent=incumbent,block_size=args.block_size,
                                         edit=(c['affected'],replacement_faces) if lazy else None)
                        evaluated_blocks+=bound['blocks']; all_blocks+=bound['totalBlocks']
                        evaluations+=1
                        if bound['pruned']:
                            pruned+=1; continue
                        gain=bound['score']
                    else:
                        before=cache.resolve(rect); after=cache.resolve(rect,transaction)
                        delta=p.filtered(after-before,sigma,scale)
                        x0,y0,x1,y1=rect; old=residual[y0:y1,x0:x1]
                        gain=float((2*old*delta+delta*delta).sum())
                        evaluations+=1
                    incumbent=min(incumbent,gain)
                    choices.append((gain,cid,transaction,rect,replacement_faces,deleted,new_position))
                if not choices: break
                _,cid,transaction,rect,replacements,deleted,new_position=min(choices,key=lambda x:(x[0],x[1]))
                c=candidates[cid]
                if transaction is None: transaction=cache.propose(c['affected'],replacements)
                before=cache.resolve(rect); after=cache.resolve(rect,transaction)
                delta=p.filtered(after-before,sigma,scale)
                x0,y0,x1,y1=rect; residual[y0:y1,x0:x1]+=delta
                cache.commit(transaction)
                positions[c['keep']]=new_position
                for f in c['affected']:
                    current_faces[f][current_faces[f]==c['remove']]=c['keep']
                alive[deleted]=False
                changed_vertices.update(supports[cid])
                actions.append(cid)
            elapsed=time.perf_counter()-start
            # Independent complete rerasterization validates actual committed geometry.
            full,_=p.raster(positions,current_faces,alive,(0,0,size,size),scale)
            np.testing.assert_allclose(full,cache.resolve((0,0,size,size)),atol=1e-12)
            actual=p.filtered(full,sigma,scale)-base_image
            np.testing.assert_allclose(actual,residual,atol=1e-12)
            entry=dict(policy=policy,steps=len(actions),triangles=int(alive.sum()),actions=actions,
                       metrics=p.metrics(actual),totalSeconds=elapsed,evaluations=evaluations,
                       prunedCandidates=pruned,evaluatedBlocks=evaluated_blocks,totalBlocks=all_blocks,
                       maxAccumulationDifference=float(np.max(np.abs(actual-residual))))
            # Deliver actual geometry, not just candidate ranking statistics.
            args.out.parent.mkdir(parents=True,exist_ok=True)
            path=args.out.parent/f'{args.capture.stem}-{frame["frame"]}-{policy}.obj'
            world=vertices.copy()
            for cid in actions: world[candidates[cid]['keep']]=candidates[cid]['target']
            with path.open('w') as mesh:
                for v in world: mesh.write('v '+' '.join(format(x,'.17g') for x in v)+'\n')
                for tri in current_faces[alive]: mesh.write('f '+' '.join(str(int(x)+1) for x in tri)+'\n')
            output.append(entry)
        if args.bounded and output[1]['actions']!=output[2]['actions']:
            raise AssertionError('bounded and exhaustive policies choose different operations')
        result['frames'].append(dict(frame=frame['frame'],angle=float(angle),policies=output,
                                    equalBudget=output[0]['triangles']==output[1]['triangles']))
        args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(args.capture.stem,frame['frame'],[(x['policy'],x['steps'],x['metrics']['total']) for x in output],flush=True)


if __name__=='__main__': main()
