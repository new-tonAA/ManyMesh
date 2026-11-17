#!/usr/bin/env python3
"""Audit frozen placement outputs without fitting, selecting or reverting positions.

Include unchanged fallbacks in held-out aggregate denominators. Check accepted
placements against full-image redraws, independent of patch bounds (same rasterizer).
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

spec = importlib.util.spec_from_file_location(
    'placement_audit_depth', Path(__file__).with_name('depth_candidate_pilot.py'))
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(rows):
    seed = sum(r['seed']['total'] for r in rows)
    result = sum(r['result']['total'] for r in rows)
    return dict(cases=len(rows), seedTotal=seed, resultTotal=result,
                relativeReduction=(seed-result)/seed if seed else None,
                improved=sum(r['result']['total'] < r['seed']['total']-1e-14 for r in rows),
                regressed=sum(r['result']['total'] > r['seed']['total']+1e-14 for r in rows),
                coverageRegressed=sum(r['result']['coverage'] > r['seed']['coverage']+1e-14
                                      for r in rows))


def audit(capture_path, source_path, placement_path):
    start = time.perf_counter()
    world, faces, candidates = p.load_capture(capture_path)
    source = json.loads(source_path.read_text())
    placement = json.loads(placement_path.read_text())
    if sha(capture_path) != placement['hashes']['capture']:
        raise ValueError('capture differs from frozen placement input')
    evaluator = Path(__file__).with_name('evaluate_multiview_placement.py')
    if sha(evaluator) != placement['hashes']['script']:
        raise ValueError('evaluator differs from recorded version')
    size, scale, sigma = (source[k] for k in ('size', 'scale', 'sigma'))
    full = (0, 0, size, size)
    halo = int(np.ceil(4*sigma))+2
    rows = []
    max_difference = 0.
    fit_seed = fit_result = 0.
    timings = []
    accepted_count = 0
    for frame, source_frame in zip(placement['frames'], source['frames'], strict=True):
        expected = [r['id'] for r in source_frame['candidates'] if r['baselineVisible']]
        if ([r['id'] for r in frame['candidates']] != expected or
                frame['angle'] != source_frame['angle']):
            raise ValueError('candidate population or camera differs from source')
        for r in frame['candidates']:
            fit_seed += r['seedFitError']
            fit_result += r['resultFitError']
            timings.append(r['fittingSeconds'])
            accepted_count += int(r['accepted'])
        for offset in placement['testOffsets']:
            transform = p.camera(world, frame['angle']+offset, size)
            projected = p.project(world, transform)
            original, _ = p.raster(projected, faces, np.ones(len(faces), bool), full, scale)
            for row in frame['candidates']:
                c = candidates[row['id']]
                changed, cf, valid = p.edited_geometry(projected, faces, c, transform)
                rect = p.support(projected, faces, c, transform, size, halo)
                x0, y0, x1, y1 = rect
                raw, _ = p.raster(changed, cf, valid, rect, scale)
                seed = p.metrics(p.filtered(
                    raw-original[y0*scale:y1*scale, x0*scale:x1*scale], sigma, scale))
                result = seed
                if row['accepted']:
                    # Re-render the complete image for both placements; no patch support assumption.
                    raw, _ = p.raster(changed, cf, valid, full, scale)
                    full_seed = p.metrics(p.filtered(raw-original, sigma, scale))
                    changed[c['keep']] = p.project([row['target']], transform)[0]
                    raw, _ = p.raster(changed, cf, valid, full, scale)
                    result = p.metrics(p.filtered(raw-original, sigma, scale))
                    recorded = next(t for t in row['tests'] if t['offset'] == offset)
                    for actual, expected_metrics in ((full_seed, seed), (full_seed, recorded['seed']),
                                                     (result, recorded['result'])):
                        for ch in ('coverage', 'depth', 'total'):
                            max_difference = max(max_difference, abs(actual[ch]-expected_metrics[ch]))
                            np.testing.assert_allclose(actual[ch], expected_metrics[ch],
                                                       rtol=1e-8, atol=1e-12)
                    seed = full_seed
                else:
                    np.testing.assert_array_equal(row['target'], c['target'])
                    if row['tests'] or not row['fallbackUntestedViewsIdentical']:
                        raise ValueError('invalid fallback bookkeeping')
                rows.append(dict(frame=frame['frame'], id=row['id'], offset=offset,
                                 accepted=row['accepted'], seed=seed, result=result))
        print(capture_path.stem, 'audited frame', frame['frame'], flush=True)
    accepted = [r for r in rows if r['accepted']]
    return dict(scope='frozen development assets, geometry/depth only; no refitting',
                hashes={str(path): sha(path) for path in
                        (capture_path, source_path, placement_path, Path(__file__),
                         Path(p.__file__), evaluator)},
                candidates=len(timings), accepted=accepted_count,
                fit=dict(seedTotal=fit_seed, resultTotal=fit_result,
                         relativeReduction=(fit_seed-fit_result)/fit_seed if fit_seed else None),
                fittingMilliseconds=dict(median=float(np.median(timings))*1000,
                                         p95=float(np.percentile(timings, 95))*1000),
                allHeldOut=summarize(rows), acceptedHeldOut=summarize(accepted),
                maxPatchFullDifference=max_difference,
                auditSeconds=time.perf_counter()-start, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('source', type=Path)
    parser.add_argument('placement', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.capture, args.source, args.placement)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
