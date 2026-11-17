#!/usr/bin/env python3
"""Exhaustively audit a frozen collapse pool across a controlled camera orbit.

Offline oracle only. Candidate geometry and legality are frozen at the source state; this is not a
multi-collapse trajectory, certificate, runtime method, or novelty claim.
"""
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


def rank(values):
    order = np.argsort(np.asarray(values), kind='stable')
    result = np.empty(len(order), dtype=np.int64)
    result[order] = np.arange(len(order))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('candidate_report', type=Path,
                        help='fragment-transactions cost audit containing a frozen candidate pool')
    parser.add_argument('--pool-frame', type=int, default=0)
    parser.add_argument('--frames', type=int, default=6)
    parser.add_argument('--size', type=int, default=128)
    parser.add_argument('--scale', type=int, default=3)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.frames < 2:
        parser.error('--frames must be at least 2')

    p = load('camera_rank_pilot', 'depth_candidate_pilot.py')
    positions, triangles, candidates = p.load_capture(args.capture)
    candidate_report = json.loads(args.candidate_report.read_text())
    frames = candidate_report['frames']
    if not 0 <= args.pool_frame < len(frames):
        parser.error('--pool-frame is outside the candidate report')
    pool = frames[args.pool_frame]['candidates']
    ids = [int(row['id']) for row in pool]
    if len(set(ids)) != len(ids) or any(cid < 0 or cid >= len(candidates) for cid in ids):
        raise ValueError('candidate IDs must be unique and in range')

    sigma = .9
    angles = np.linspace(2.13, 2.48, args.frames)
    output = dict(
        scope='frozen legal initial candidates; exhaustive sampled depth/coverage oracle; no PBR',
        warning='no committed edits, no temporal update method, no speed or novelty claim',
        captureSha256=hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        candidateReportSha256=hashlib.sha256(args.candidate_report.read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        poolFrame=args.pool_frame, candidateIds=ids, size=args.size, scale=args.scale,
        sigma=sigma, angles=[float(x) for x in angles], views=[])
    score_matrix = []
    started = time.perf_counter()

    for frame, angle in enumerate(angles):
        transform = p.camera(positions, float(angle), args.size)
        projected = p.project(positions, transform)
        full = (0, 0, args.size, args.size)
        valid = np.ones(len(triangles), dtype=bool)
        base_raw, _ = p.raster(projected, triangles, valid, full, args.scale)
        base = p.filtered(base_raw, sigma, args.scale)
        rows = []
        scores = []
        view_start = time.perf_counter()
        for cid in ids:
            candidate = candidates[cid]
            rect = p.support(projected, triangles, candidate, transform, args.size,
                             int(np.ceil(4 * sigma)) + 2)
            if rect is None:
                score = 0.0
                errors = p.metrics(np.zeros((0, 0, 2)))
            else:
                changed, edited_triangles, alive = p.edited_geometry(
                    projected, triangles, candidate, transform)
                residual, _ = p.patch_residual(changed, edited_triangles, alive, rect,
                                               args.scale, sigma, base_raw)
                errors = p.metrics(residual)
                score = errors['total']
            scores.append(score)
            rows.append(dict(id=cid, rect=rect, errors=errors, total=score))

        order = np.argsort(scores, kind='stable')
        output['views'].append(dict(frame=frame, angle=float(angle),
            winner=ids[int(order[0])], winnerScore=float(scores[int(order[0])]),
            runnerUp=ids[int(order[1])], runnerUpScore=float(scores[int(order[1])]),
            rows=rows, seconds=time.perf_counter() - view_start))
        score_matrix.append(scores)
        print(f'frame {frame}: winner={ids[int(order[0])]} score={scores[int(order[0])]:.9g}',
              flush=True)

    score_matrix = np.asarray(score_matrix)
    ranks = np.stack([rank(scores) for scores in score_matrix])
    top_k = min(10, len(ids))
    comparisons = []
    for a in range(len(angles)):
        for b in range(a + 1, len(angles)):
            ra, rb = ranks[a], ranks[b]
            rho = float(np.corrcoef(ra, rb)[0, 1]) if len(ids) > 1 else 1.0
            top_a = set(np.argsort(score_matrix[a], kind='stable')[:top_k].tolist())
            top_b = set(np.argsort(score_matrix[b], kind='stable')[:top_k].tolist())
            comparisons.append(dict(frameA=a, frameB=b,
                winnerSame=ids[int(np.argmin(score_matrix[a]))] ==
                           ids[int(np.argmin(score_matrix[b]))],
                spearmanRankCorrelation=rho,
                topKIntersection=len(top_a & top_b), topK=top_k))
    output['summary'] = dict(
        winnerIds=[view['winner'] for view in output['views']],
        distinctWinners=len(set(view['winner'] for view in output['views'])),
        comparisons=comparisons,
        minSecondsPerView=min(view['seconds'] for view in output['views']),
        medianSecondsPerView=float(np.median([view['seconds'] for view in output['views']])),
        wallSeconds=time.perf_counter() - started,
        note='Timing is Python CPU and excludes startup; it is not a speed comparison.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + '\n')
    print(f"wrote {args.out}; distinct winners={output['summary']['distinctWinners']}; "
          f"median={output['summary']['medianSecondsPerView']:.3f}s/view")


if __name__ == '__main__':
    main()
