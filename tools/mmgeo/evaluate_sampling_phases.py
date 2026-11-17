#!/usr/bin/env python3
"""Measure phase-specific collapse opportunities using exact archived raster deltas.

No new placement, no mesh selection/commit, no speed or novelty claim. A scale x scale
supersampling lattice is partitioned into scale**2 single-sample-per-pixel jitter phases.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def phase_errors(events, scale):
    coverage = np.zeros(scale*scale)
    depth = np.zeros(scale*scale)
    for x, y, dc, dz in events:
        phase = int(y) % scale*scale + int(x) % scale
        coverage[phase] = max(coverage[phase], abs(dc))
        depth[phase] = max(depth[phase], abs(dz))
    return coverage, depth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.export.with_suffix('.manifest.json').read_text())
    digest = hashlib.sha256(args.export.read_bytes()).hexdigest()
    if digest != manifest['exportSha256']:
        raise ValueError('export does not match archived manifest')
    rows = []
    with args.export.open() as source:
        width, height, scale, sigma, count = source.readline().split()
        width, height, scale, count = map(int, (width, height, scale, count))
        for _ in range(count):
            frame, cid, n, energy, seconds = source.readline().split()
            events = np.array([list(map(float, source.readline().split()))
                               for _ in range(int(n))]).reshape(-1, 4)
            if not np.isfinite(events).all():
                raise ValueError('nonfinite events')
            if len(events) and (np.any(events[:, :2] != np.floor(events[:, :2])) or
                               np.any(events[:, :2] < 0) or
                               np.any(events[:, 0] >= width*scale) or
                               np.any(events[:, 1] >= height*scale)):
                raise ValueError('invalid sample coordinates')
            coverage, depth = phase_errors(events, scale)
            rows.append(dict(frame=int(frame), id=int(cid), events=int(n),
                             coverageMax=coverage.tolist(), depthMax=depth.tolist()))
        if source.read().strip():
            raise ValueError('unexpected extra input')
    summaries = []
    # Fixed sensitivity sweep, all thresholds reported; no selection by favorable outcome.
    for tolerance in (0., 1e-8, 1e-6, 1e-4):
        masks = [((np.array(r['coverageMax']) == 0) &
                  (np.array(r['depthMax']) <= tolerance)) for r in rows]
        all_safe = sum(bool(np.all(mask)) for mask in masks)
        specific = sum(bool(np.any(mask) and not np.all(mask)) for mask in masks)
        extra = sum(int(mask.sum()) for mask in masks if not np.all(mask))
        summaries.append(dict(depthTolerance=tolerance, allPhaseSafe=all_safe,
                              phaseSpecificCandidates=specific, additionalPhaseOpportunities=extra,
                              candidatePhaseCases=len(rows)*scale*scale,
                              safePerPhase=np.sum(masks, axis=0).tolist()))
    result = dict(scope='individual-candidate opportunity only; no batch correctness or runtime claim',
                  exportSha256=digest,
                  scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  manifest=manifest, cases=len(rows), scale=scale, summaries=summaries, rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'manifest')}, indent=2))


if __name__ == '__main__':
    main()
