#!/usr/bin/env python3
"""Report query, setup-inclusive batch costs and matched-budget choices separately."""
import argparse
import json
from pathlib import Path
import statistics


def summarize(path):
    data=json.loads(path.read_text())
    frames=data['frames']; rows=[c for f in frames for c in f['candidates']]
    breaks=[f['breakEvenCandidates'] for f in frames if f['breakEvenCandidates'] is not None]
    return dict(asset=path.stem,frames=len(frames),queries=len(rows),
        maxDifference=max(c['maxDifference'] for c in rows),
        querySpeedMedian=statistics.median(c['redrawSeconds']/c['transactionSeconds'] for c in rows),
        totalBatchSpeed=sum(f['batchRedrawSeconds'] for f in frames)/
                        sum(f['batchTransactionSeconds'] for f in frames),
        medianCacheSetupMs=1000*statistics.median(f['cacheSetupSeconds'] for f in frames),
        medianQueryMs=1000*statistics.median(c['transactionSeconds'] for c in rows),
        medianRedrawMs=1000*statistics.median(c['redrawSeconds'] for c in rows),
        medianCommitMs=1000*statistics.median(c['commitSeconds'] for c in rows),
        medianUndoMs=1000*statistics.median(c['undoSeconds'] for c in rows),
        medianArrayMiB=statistics.median(f['cacheArrayBytes']/2**20 for f in frames),
        maxTransientArrayMiB=max(c['transientArrayBytes']/2**20 for c in rows),
        fromScratchSpeed=(sum(f['fromScratchRedrawSeconds'] for f in frames)/
                          sum(f['fromScratchTransactionSeconds'] for f in frames)
                          if all('fromScratchRedrawSeconds' in f for f in frames) else None),
        initialResolveIncluded=all('resolveSetupSeconds' in f for f in frames),
        memoryCaveat='arrays only; excludes Python objects, raster temporaries and multiple retained edits',
        breakEvenMedian=statistics.median(breaks) if breaks else None,
        breakEvenUnreachableFrames=len(frames)-len(breaks),
        costCaveat='batch totals include setup+queries; commit/undo separate; not whole renderer frame time')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports',nargs='+',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=[summarize(path) for path in args.reports]
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    for row in result: print(json.dumps(row))


if __name__=='__main__': main()
