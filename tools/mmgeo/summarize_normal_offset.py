#!/usr/bin/env python3
"""Verify exact zero-offset fallbacks and bind their existing evaluation provenance."""
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows=[]
    for asset in ('torus','monkey','pirate'):
        root=Path(f'out/normal-offset-control-v2/{asset}')
        base=Path(f'out/progressive-baseline/{asset}')
        fit=json.loads((root/'fit.json').read_text())
        manifest=json.loads((root/'manifest.json').read_text())
        original=json.loads((base/'manifest.json').read_text())
        ratio=fit['ratio'];reference=Path(original['artifacts'][ratio]['path'])
        result=Path(manifest['artifacts'][ratio]['path'])
        if sha(reference)!=original['artifacts'][ratio]['sha256'] or sha(result)!=manifest['artifacts'][ratio]['sha256']:
            raise ValueError('mesh hash mismatch')
        if sha(base/'manifest.json')!=fit['hashes'][str(base/'manifest.json')]:
            raise ValueError('baseline manifest differs from fitting input')
        if sha(root/'fit.json')!=manifest['fitReportSha256']:raise ValueError('fit report differs')
        if fit['selectedAlpha']!=0:raise ValueError('nonzero correction requires a fresh full-view evaluation')
        before=np.load(reference);after=np.load(result)
        for key in ('positions','triangles'):np.testing.assert_array_equal(before[key],after[key])
        evaluation=json.loads((base/'evaluation.json').read_text())
        if evaluation['manifestSha256']!=sha(base/'manifest.json'):raise ValueError('old evaluation is stale')
        rows.append(dict(asset=asset,selectedAlpha=fit['selectedAlpha'],bitIdenticalToQEM=True,
            geometryRejected=fit['geometryRejected'],fitSeconds=fit['seconds'],
            fitLosses=[dict(alpha=r['alpha'],total=r['total']) for r in fit['fit']],
            unchangedMeasurementSSE=evaluation['levels'][ratio]['sumSSE'],
            inputHashes={str(path):sha(path) for path in
                         (root/'fit.json',root/'manifest.json',base/'manifest.json',base/'evaluation.json',reference,result)},
            measurement='Bit-identical geometry; reuse existing baseline evaluation with provenance, no new test rerender.'))
    output=Path('out/normal-offset-control-v2/summary.json')
    output.write_text(json.dumps(dict(scope='verified zero-offset fallbacks only',
        scriptSha256=sha(Path(__file__)),rows=rows),indent=2)+'\n')
    for row in rows:print(row['asset'],'verified identical; selected alpha',row['selectedAlpha'])


if __name__=='__main__':main()
