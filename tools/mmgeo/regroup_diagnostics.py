#!/usr/bin/env python3
"""Reproduce the first-stage regroup screening; no claim of causal attribution.

Uses only the Python standard library. All assets in this pilot are development
assets, including the procedural controls. Parameters are frozen below.
"""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time


def control(path, kind, n=20):
    """Same triangulation: smooth surface, thin sheet, crease, or split UV charts."""
    vertices, uvs, faces = [], [], []
    for y in range(n + 1):
        for x in range(n + 1):
            u, v = x / n, y / n
            z = 0.15 * math.sin(u * math.pi) * math.sin(v * math.pi)
            if kind == 'thin':
                v *= 0.02
                z = 0
            elif kind == 'crease':
                z = abs(u - 0.5) * 0.6
            vertices.append((u, v, z))
            uvs.extend(((u * 0.4, v * 0.4), (0.6 + u * 0.4, v * 0.4)))
    for y in range(n):
        for x in range(n):
            a = y * (n + 1) + x + 1
            for tri in ((a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)):
                chart = int(kind == 'uv' and x >= n // 2)
                faces.append('f ' + ' '.join(f'{i}/{2*i-1+chart}' for i in tri))
    path.write_text('\n'.join(
        ['v ' + ' '.join(map(str, p)) for p in vertices] +
        ['vt ' + ' '.join(map(str, uv)) for uv in uvs] + faces) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mmgeo', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path('out/regroup-diagnostics'))
    parser.add_argument('--work', type=int, default=50000)
    args = parser.parse_args()
    if args.work < 0:
        parser.error('--work must be nonnegative')
    root = Path(__file__).resolve().parents[2]
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for kind in ('smooth', 'thin', 'crease', 'uv'):
        path = output / f'{kind}.obj'
        control(path, kind)
        assets.append((kind, path))
    assets.extend((name, root / path) for name, path in (
        ('pirate', 'third_party/meshoptimizer/demo/pirate.obj'),
        ('monkey', 'assets/models/monkey/monkey.obj'),
        ('torus', 'assets/models/torus/torus.obj')))
    summary = []
    for name, path in assets:
        for threads in (1, 4):
            target = output / f'{name}-{threads}'
            target.mkdir(exist_ok=True)
            ledger = target / 'diagnostics.json'
            command = [str(args.mmgeo.resolve()), '--mode', 'dag', '--levels', '5',
                       '--ratio', '0.7', '--dag-group', '8', '--corner-seam', '1',
                       '--quality-gate', '1', '--dump-obj', '0', '--write-dag', '0',
                       '--out', str(target), '--dag-diagnostics', str(ledger),
                       '--dag-diagnostic-work', str(args.work), str(path)]
            env = dict(os.environ, MANYMESH_BUILD_THREADS=str(threads))
            start = time.perf_counter()
            with (target / 'run.log').open('w') as log:
                subprocess.run(command, cwd=root, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=300)
            data = json.loads(ledger.read_text())
            trials = data['trials']
            production = [g for g in data['groups'] if g['trial'] == 0]
            row = dict(asset=name, threads=threads, seconds=time.perf_counter() - start,
                       groups=len(production), failed=sum(not g['promoted'] for g in production),
                       trials=len(trials), improves=sum(t['improves'] for t in trials),
                       work=data['trialInputTriangles'], trialSeconds=data['trialSeconds'])
            assert row['work'] <= args.work
            if threads == 1:
                serial = data
            else:
                assert data['groups'] == serial['groups'], f'{name}: ledger changed with threads'
                assert trials == serial['trials'], f'{name}: trials changed with threads'
            summary.append(row)
            print(json.dumps(row), flush=True)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
