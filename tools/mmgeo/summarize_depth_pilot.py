#!/usr/bin/env python3
"""Summarize matched-triangle choices; no plots and no learned/test-set claims."""
import argparse
import json
from pathlib import Path
import statistics


def summarize(path):
    data=json.loads(path.read_text())
    rows=[c for f in data['frames'] for c in f['candidates']]
    screening={key:sum(f['screening'][key] for f in data['frames'])
               for key in data['frames'][0]['screening']}
    groups=[]
    for frame in data['frames']:
        strata=sorted(set((c['triangles'],c['baselineVisible']) for c in frame['candidates']))
        for count,visible in strata:
            candidates=[c for c in frame['candidates'] if c['triangles']==count and
                        c['baselineVisible']==visible]
            base=min(candidates,key=lambda c:(c['priority'],c['id']))
            oracle=min(candidates,key=lambda c:(c['metrics']['total'],c['priority'],c['id']))
            entry=dict(frame=frame['frame'],triangles=count,baselineVisible=visible,count=len(candidates),
                       baseline=base['metrics'],oracle=oracle['metrics'],predictions=[])
            for i,k in enumerate((8,16,32)):
                chosen=min(candidates,key=lambda c:(c['predictions'][i]['error'],c['priority'],c['id']))
                represent=min(candidates,key=lambda c:(c['predictions'][i]['oracleRepresentationError'],
                                                        c['priority'],c['id']))
                entry['predictions'].append(dict(dimensions=k,id=chosen['id'],metrics=chosen['metrics'],
                        baselineId=base['id'],oracleId=oracle['id'],representationId=represent['id'],
                        representationMetrics=represent['metrics']))
            groups.append(entry)
    result=dict(asset=path.stem,scope=data['scope'],screening=screening,
                sampled=len(rows),zeroAtReference=sum(c['metrics']['total']<=1e-14 for c in rows),
                nonzeroDepth=sum(c['metrics']['depth']>1e-14 for c in rows),
                patchFullMaxDifference=max(c['patchFullMaxDifference'] for c in rows),
                medianPatchMs=1000*statistics.median(c['patchSeconds'] for c in rows),
                medianCoarseEncodeMs=1000*statistics.median(c['coarseRasterSeconds']+
                    c['basisSeconds']+c['encodeSeconds'] for c in rows),
                medianReferenceOverCoarse=statistics.median(c['patchSeconds']/max(
                    c['coarseRasterSeconds']+c['basisSeconds']+c['encodeSeconds'],1e-30) for c in rows),
                fixedCandidateAdjacentEdges=sum('screenResidualChange' in c for c in rows),
                groups=groups,policies=[])
    # Primary comparison stays within visible-support stratum; hidden controls would otherwise
    # trivially win by changing no visible pixel and conceal ranking failures on active geometry.
    groups=[g for g in groups if g['baselineVisible']]
    for i,k in enumerate((8,16,32)):
        changes=[g['predictions'][i]['metrics']['total']-g['baseline']['total'] for g in groups]
        result['policies'].append(dict(dimensions=k,matchedBudgetGroups=len(groups),
            improved=sum(d < -1e-12 for d in changes),regressed=sum(d > 1e-12 for d in changes),
            baselineSSE=sum(g['baseline']['total'] for g in groups),
            selectedSSE=sum(g['predictions'][i]['metrics']['total'] for g in groups),
            oracleSSE=sum(g['oracle']['total'] for g in groups),
            representationOracleSSE=sum(g['predictions'][i]['representationMetrics']['total'] for g in groups),
            selectedCoverageSSE=sum(g['predictions'][i]['metrics']['coverage'] for g in groups),
            selectedDepthSSE=sum(g['predictions'][i]['metrics']['depth'] for g in groups)))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports',nargs='+',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    reports=[summarize(path) for path in args.reports]
    args.out.write_text(json.dumps(reports,indent=2)+'\n')
    for r in reports:
        print(r['asset'],'sampled',r['sampled'],'depth nonzero',r['nonzeroDepth'],
              'patch ms',r['medianPatchMs'],'coarse ms',r['medianCoarseEncodeMs'])
        for p in r['policies']:
            print(' ',p)


if __name__=='__main__':
    main()
