#!/usr/bin/env python3
"""Separate phase-conditioned collapse opportunities from ordinary invisible-work culling."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    'phase_depth', Path(__file__).with_name('depth_candidate_pilot.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('phases', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.phases.read_text())
    if hashlib.sha256(args.capture.read_bytes()).hexdigest() != data['manifest']['captureSha256']:
        raise ValueError('capture hash mismatch')
    world, faces, candidates = p.load_capture(args.capture)
    scale = data['scale']
    rows = []
    # These are the exact frozen cameras/resolution used by export_raster_deltas.py.
    for frame, angle in enumerate(np.linspace(2.13, 2.48, 6)):
        transform = p.camera(world, float(angle), 128)
        projected = p.project(world, transform)
        _, owner = p.raster(projected, faces, np.ones(len(faces), bool), (0, 0, 128, 128), scale)
        counts = []
        for y in range(scale):
            for x in range(scale):
                values = owner[y::scale, x::scale].ravel()
                counts.append(np.bincount(values[values >= 0], minlength=len(faces)))
        counts = np.asarray(counts)
        for row in data['rows']:
            if row['frame'] != frame:
                continue
            c = candidates[row['id']]
            visible = counts[:, c['affected']].sum(axis=1)
            deleted = [f for f in c['affected'] if c['keep'] in faces[f] and c['remove'] in faces[f]]
            deleted_visible = counts[:, deleted].sum(axis=1) if deleted else np.zeros(scale*scale)
            rows.append(dict(row, visibleAffected=visible.tolist(), visibleDeleted=deleted_visible.tolist()))
        print(args.capture.stem, frame, 'visibility audited', flush=True)
    summaries = []
    for tolerance in (0., 1e-8, 1e-6, 1e-4):
        totals = dict(depthTolerance=tolerance, phaseSpecificOpportunities=0,
                      visibleAffectedOpportunities=0, visibleDeletedOpportunities=0,
                      candidateFramesWithVisibleOpportunity=0)
        for row in rows:
            mask = ((np.asarray(row['coverageMax']) == 0) &
                    (np.asarray(row['depthMax']) <= tolerance))
            if np.all(mask):
                continue
            totals['phaseSpecificOpportunities'] += int(mask.sum())
            meaningful = mask & (np.asarray(row['visibleAffected']) > 0)
            totals['visibleAffectedOpportunities'] += int(meaningful.sum())
            totals['visibleDeletedOpportunities'] += int(np.sum(mask & (np.asarray(row['visibleDeleted']) > 0)))
            totals['candidateFramesWithVisibleOpportunity'] += int(np.any(meaningful))
        summaries.append(totals)
    result = dict(scope='visibility audit only; visible samples do not imply a useful novel simplifier',
                  inputs={str(f): hashlib.sha256(f.read_bytes()).hexdigest()
                          for f in (args.capture, args.phases, Path(__file__), Path(p.__file__))},
                  summaries=summaries, rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
