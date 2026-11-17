#!/usr/bin/env python3
"""Compare direct complementary construction with matched static placement search."""
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


single = load('direct_single', 'evaluate_raster_placement.py')
direct = load('direct_search', 'direct_complementary.py')
p = single.p
TEST = (-.037, .043)


def context(world, faces, candidate, angle, size, scale, sigma):
    transform = p.camera(world, angle, size)
    projected = p.project(world, transform)
    cp, cf, valid = p.edited_geometry(projected, faces, candidate, transform)
    seed = np.asarray(candidate['target'])
    allowance = max(np.linalg.norm(seed-world[i]) for i in (candidate['keep'], candidate['remove']))
    J = np.diag([size*.43, -size*.43, .5]) @ transform[2] / transform[1]
    # All eight static sweeps travel at most .46875 edge lengths from the seed;
    # either pair state travels at most .234375. Use .5 for a conservative bound.
    center = p.project([seed], transform)[0, :2]
    reach = .5*np.linalg.norm(world[candidate['keep']]-world[candidate['remove']])
    extent = reach*np.linalg.norm(J[:2], axis=1)
    points = np.concatenate((projected[faces[candidate['affected']].ravel(), :2],
                             [center-extent, center+extent]))
    halo = int(np.ceil(4*sigma))+2
    lo = np.maximum(0, np.floor(points.min(0)).astype(int)-halo)
    hi = np.minimum(size, np.ceil(points.max(0)).astype(int)+halo)
    rect = (int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1]))
    original, _ = p.raster(projected, faces, np.ones(len(faces), bool), rect, scale)
    unchanged = np.ones(len(faces), bool)
    unchanged[candidate['affected']] = False
    background, _ = p.raster(projected, faces, unchanged, rect, scale)
    background_depth = np.where(background[..., 0] > 0, background[..., 1], -np.inf)
    affected = np.zeros(len(faces), bool)
    affected[candidate['affected']] = True
    affected &= valid
    def evaluate(target):
        cp[candidate['keep']] = p.project([target], transform)[0]
        local, _ = p.raster(cp, cf, affected, rect, scale)
        cover = (local[..., 0] > 0) | (background[..., 0] > 0)
        depth = np.maximum(background_depth, np.where(local[..., 0] > 0, local[..., 1], -np.inf))
        raw = np.stack((cover.astype(float), np.where(cover, depth, 0.)), axis=-1)
        return p.filtered(raw-original, sigma, scale)
    def guard(target):
        return single.geometric_guard(world, cf, valid, candidate, target)
    return evaluate, guard


def serial_search(result, elapsed):
    return dict(targets=[t.tolist() for t in result['targets']], score=result['score'],
                bestSingle=result['bestSingle'], bestSingleTarget=result['bestSingleTarget'].tolist(),
                rasters=result['rasters'], rejected=result['rejected'],
                attempts=result['attempts'], seconds=elapsed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    world, faces, candidates = p.load_capture(args.capture)
    report = json.loads(args.report.read_text())
    size, scale, sigma = (report[k] for k in ('size', 'scale', 'sigma'))
    rows = []
    total_start = time.perf_counter()
    for frame in report['frames']:
        for obs in frame['candidates']:
            if not obs['baselineVisible']:
                continue
            c = candidates[obs['id']]
            start = time.perf_counter()
            evaluate, guard = context(world, faces, c, frame['angle'], size, scale, sigma)
            setup_seconds = time.perf_counter()-start
            edge = np.linalg.norm(world[c['keep']]-world[c['remove']])
            outputs = {}
            # Alternate search order across cases; sharing only reference context.
            for paired in ((False, True) if len(rows) % 2 == 0 else (True, False)):
                start = time.perf_counter()
                value = direct.search(c['target'], edge, evaluate, guard, paired)
                outputs['pair' if paired else 'static'] = (value, time.perf_counter()-start)
            pair, pair_seconds = outputs['pair']
            static, static_seconds = outputs['static']
            midpoint = np.mean(pair['targets'], axis=0)
            midpoint_valid = guard(midpoint)
            midpoint_error = float(np.square(evaluate(midpoint)).sum()) if midpoint_valid else None
            tests = []
            for offset in TEST:
                test_eval, test_guard = context(world, faces, c, frame['angle']+offset,
                                                size, scale, sigma)
                a, b = (test_eval(t) for t in pair['targets'])
                static_image = test_eval(static['targets'][0])
                best_image = test_eval(pair['bestSingleTarget'])
                tests.append(dict(offset=offset, pair=direct.pair_metrics(a, b),
                                  static=p.metrics(static_image), bestPairSingle=p.metrics(best_image),
                                  midpoint=p.metrics(test_eval(midpoint)) if midpoint_valid else None))
            rows.append(dict(frame=frame['frame'], id=obs['id'], setupSeconds=setup_seconds,
                             static=serial_search(static, static_seconds),
                             pair=serial_search(pair, pair_seconds),
                             pairMetrics=direct.pair_metrics(*pair['images']),
                             midpointError=midpoint_error, tests=tests))
        print(args.capture.stem, frame['frame'], 'cases', len(rows), flush=True)
    totals = dict(static=sum(r['static']['score'] for r in rows),
                  pair=sum(r['pair']['score'] for r in rows),
                  bestPairSingle=sum(r['pair']['bestSingle'] for r in rows),
                  pairBias=sum(r['pairMetrics']['bias'] for r in rows))
    tests = [t for r in rows for t in r['tests']]
    test_totals = dict(static=sum(t['static']['total'] for t in tests),
                       pair=sum(t['pair']['expected'] for t in tests),
                       bestPairSingle=sum(t['bestPairSingle']['total'] for t in tests),
                       pairBias=sum(t['pair']['bias'] for t in tests),
                       worseThanStatic=sum(t['pair']['expected'] > t['static']['total']+1e-14
                                           for t in tests),
                       coverageWorseThanStatic=sum(t['pair']['coverageExpected'] >
                                                  t['static']['coverage']+1e-14 for t in tests))
    passed = all(v['pair'] <= .9*v[k] for v in (totals, test_totals)
                 for k in ('static', 'bestPairSingle'))
    result = dict(scope='direct placement, development assets, geometry-only, fixed-camera IID oracle',
                  inputs={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in
                          (args.capture, args.report, Path(__file__), Path(direct.__file__),
                           Path(single.__file__), Path(p.__file__),
                           Path(__file__).with_name('DIRECT_COMPLEMENTARY_PROTOCOL.md'))},
                  testOffsets=TEST, cases=len(rows), totals=totals, testTotals=test_totals,
                  assetScreenPassed=passed, seconds=time.perf_counter()-total_start, rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'inputs')}, indent=2))


if __name__ == '__main__':
    main()
