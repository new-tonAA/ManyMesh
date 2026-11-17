#!/usr/bin/env python3
"""Summarize hash-bound raster-scale and subpixel-phase event probes."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()

    reports = []
    common = None
    for path in args.reports:
        data = json.loads(path.read_text())
        identity = (data['captureSha256'], data['candidateReportSha256'],
                    data['sourceOracleSha256'], data['scriptSha256'])
        if common is None:
            common = identity
        elif identity != common:
            raise ValueError(f'input or probe-script hash mismatch in {path}')
        winners = []
        counts = []
        scores = []
        for sample in data['samples']:
            rows = {int(row['id']): row for row in sample['candidates']}
            winners.append(min(rows, key=lambda cid: rows[cid]['score']))
            if 1656 in rows:
                counts.append(int(rows[1656]['rawChangedSamples']))
                scores.append(float(rows[1656]['score']))
        winner_counts = {str(cid): winners.count(cid) for cid in sorted(set(winners))}
        transitions = []
        for event in data['localizedEvents']:
            if event['eventBracket'] is not None:
                transitions.append(dict(id=event['id'], bracket=event['eventBracket'],
                                        countLeft=event['countAtLeft'],
                                        countRight=event['countAtRight']))
        reports.append(dict(
            path=str(path),
            reportSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size=data['size'], scale=data['scale'], sigma=data['sigma'],
            subpixelPhasePixels=data.get('subpixelPhasePixels', [0.0, 0.0]),
            matchesSourceOracleParameters=data.get('matchesSourceOracleParameters', False),
            angleRange=data['interval'], sampleCount=len(data['samples']),
            winnerCounts=winner_counts,
            adjacentWinnerFlips=sum(a != b for a, b in zip(winners, winners[1:])),
            candidate1656RawCoverageCounts=sorted(set(counts)),
            candidate1656ScoreRange=([min(scores), max(scores)] if scores else None),
            localizedEvents=transitions))

    output = dict(
        scope='fixed Torus initial pool; frozen candidates 1656 and 2275; orthographic depth/coverage oracle',
        warning='scale/phase ablations are sampled diagnostics, not continuous certificates, performance claims, or novelty claims',
        captureSha256=common[0], candidateReportSha256=common[1],
        sourceOracleSha256=common[2], probeScriptSha256=common[3],
        summarizerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reports=reports)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + '\n')
    print(f'wrote {args.out}; reports={len(reports)}')


if __name__ == '__main__':
    main()
