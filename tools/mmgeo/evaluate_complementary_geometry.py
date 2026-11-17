#!/usr/bin/env python3
"""Frozen same-connectivity geometry ensemble preflight; reference-image oracle only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


single = load('ensemble_single', 'evaluate_raster_placement.py')
bias = load('ensemble_bias', 'complementary_geometry.py')
p = single.p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    world, faces, candidates = p.load_capture(args.capture)
    report = json.loads(args.report.read_text())
    size, scale, sigma = (report[k] for k in ('size', 'scale', 'sigma'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = args.out.with_suffix('')
    artifact_dir.mkdir(exist_ok=True)
    rows = []
    start = time.perf_counter()
    for frame in report['frames']:
        transform = p.camera(world, frame['angle'], size)
        projected = p.project(world, transform)
        for obs in frame['candidates']:
            if not obs['baselineVisible']:
                continue
            begin = time.perf_counter()
            c = candidates[obs['id']]
            cp, cf, valid = p.edited_geometry(projected, faces, c, transform)
            seed = np.asarray(c['target'])
            a, b = world[[c['keep'], c['remove']]]
            radius = .25*np.linalg.norm(a-b)
            proposals = [seed, (a+b)/2, a, b]
            proposals.extend(seed+sign*radius*axis for axis in np.eye(3) for sign in (-1, 1))
            targets = [seed]
            for target in proposals[1:]:
                if any(np.array_equal(target, old) for old in targets):
                    continue
                if single.geometric_guard(world, cf, valid, c, target):
                    targets.append(target)
            rects = [p.support(projected, faces, dict(c, target=t.tolist()), transform,
                               size, int(np.ceil(4*sigma))+2) for t in targets]
            rect = (min(r[0] for r in rects), min(r[1] for r in rects),
                    max(r[2] for r in rects), max(r[3] for r in rects))
            original, _ = p.raster(projected, faces, np.ones(len(faces), bool), rect, scale)
            residuals = []
            for target in targets:
                cp[c['keep']] = p.project([target], transform)[0]
                image, _ = p.raster(cp, cf, valid, rect, scale)
                residuals.append(p.filtered(image-original, sigma, scale).reshape(-1))
            residuals = np.asarray(residuals)
            solved = bias.solve_bias(residuals)
            weights = solved.pop('weights')
            archive = artifact_dir / f"f{frame['frame']}-c{obs['id']}.npz"
            np.savez_compressed(archive, residuals=residuals, targets=targets, weights=weights,
                                rect=rect)
            rows.append(dict(frame=frame['frame'], id=obs['id'], states=len(targets),
                             removedTriangles=int(np.count_nonzero(~valid)),
                             seed=float(np.square(residuals[0]).sum()), **solved,
                             weights=weights.tolist(), seconds=time.perf_counter()-begin,
                             archive=str(archive)))
        print(args.capture.stem, frame['frame'], 'cases', len(rows), flush=True)
    totals = {k: sum(r[k] for r in rows) for k in
              ('seed', 'bestStatic', 'uniform', 'energy', 'lower', 'gap', 'iid8', 'iid16')}
    meaningful = sum(r['bestStatic'] > 1e-14 and r['energy'] <= .9*r['bestStatic'] for r in rows)
    reduction = 1-totals['energy']/totals['bestStatic'] if totals['bestStatic'] else 0.
    result = dict(scope='finite-pool static-camera bias oracle; no temporal renderer or full attribute gates',
                  inputs={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in
                          (args.capture, args.report, Path(__file__), Path(bias.__file__),
                           Path(single.__file__), Path(p.__file__),
                           Path(__file__).with_name('COMPLEMENTARY_GEOMETRY_PROTOCOL.md'))},
                  size=size, scale=scale, sigma=sigma, cases=len(rows),
                  multistate=sum(r['states'] > 1 for r in rows),
                  candidatesWithTenPercentGain=meaningful, totals=totals,
                  reductionOverBestStatic=reduction,
                  assetScreenPassed=reduction >= .1 and meaningful >= .1*len(rows),
                  wallSeconds=time.perf_counter()-start, rows=rows)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'inputs')}, indent=2))


if __name__ == '__main__':
    main()
