#!/usr/bin/env python3
"""Full-image check of the first direct-placement case in every development frame."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

spec = importlib.util.spec_from_file_location(
    'direct_audit', Path(__file__).with_name('evaluate_direct_complementary.py'))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
p = m.p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('source', type=Path)
    parser.add_argument('result', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    for path in (args.capture, args.source):
        if hashlib.sha256(path.read_bytes()).hexdigest() != result['inputs'][str(path)]:
            raise ValueError('input hash mismatch')
    source = json.loads(args.source.read_text())
    size, scale, sigma = (source[k] for k in ('size', 'scale', 'sigma'))
    world, faces, candidates = p.load_capture(args.capture)
    checks = []
    for frame in source['frames']:
        row = next(r for r in result['rows'] if r['frame'] == frame['frame'])
        c = candidates[row['id']]
        transform = p.camera(world, frame['angle'], size)
        projected = p.project(world, transform)
        rect = (0, 0, size, size)
        original, _ = p.raster(projected, faces, np.ones(len(faces), bool), rect, scale)
        cp, cf, valid = p.edited_geometry(projected, faces, c, transform)
        residuals = []
        targets = row['static']['targets'] + row['pair']['targets']
        for target in targets:
            cp[c['keep']] = p.project([target], transform)[0]
            raw, _ = p.raster(cp, cf, valid, rect, scale)
            residuals.append(p.filtered(raw-original, sigma, scale))
        actual_static = float(np.square(residuals[0]).sum())
        actual_pair = m.direct.pair_metrics(*residuals[1:])
        np.testing.assert_allclose(actual_static, row['static']['score'], rtol=1e-8, atol=1e-12)
        for key, value in actual_pair.items():
            np.testing.assert_allclose(value, row['pairMetrics'][key], rtol=1e-8, atol=1e-12)
        difference = max(abs(actual_static-row['static']['score']),
                         *(abs(value-row['pairMetrics'][key]) for key, value in actual_pair.items()))
        checks.append(dict(frame=frame['frame'], id=row['id'], maxDifference=difference,
                           removedTriangles=int(np.count_nonzero(~valid))))
        print(args.capture.stem, frame['frame'], 'full-image check passed', flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(scope='first case per frame; same rasterizer, full image',
        hashes={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in
                (args.capture, args.source, args.result, Path(__file__))}, checks=checks), indent=2)+'\n')


if __name__ == '__main__':
    main()
