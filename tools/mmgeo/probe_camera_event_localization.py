#!/usr/bin/env python3
"""Localize sampled raster events behind one frozen-pool camera-ranking flip.

This is an offline diagnostic over the same orthographic depth/coverage raster oracle as
audit_camera_rank_stability.py. It does not claim a continuous certificate or runtime benefit.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def barycentric_at(projected, face_vertices, sample_center):
    a, b, c = projected[face_vertices]
    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    dx, dy = sample_center[0] - a[0], sample_center[1] - a[1]
    u = (dx * (c[1] - a[1]) - dy * (c[0] - a[0])) / area
    v = ((b[0] - a[0]) * dy - (b[1] - a[1]) * dx) / area
    return [float(1 - u - v), float(u), float(v)]


def evaluate(p, positions, triangles, candidates, candidate_id, angle, size, scale, sigma,
             track_sample, phase):
    transform = p.camera(positions, angle, size)
    projected_original = p.project(positions, transform)
    projected = projected_original.copy()
    projected[:, :2] += phase
    valid = np.ones(len(triangles), dtype=bool)
    full = (0, 0, size, size)
    base_raw, base_owners = p.raster(projected, triangles, valid, full, scale)
    track_y, track_x = track_sample
    track_center = [(track_x + .5) / scale, (track_y + .5) / scale]
    candidate = candidates[candidate_id]
    rect = p.support(projected, triangles, candidate, transform, size,
                     int(np.ceil(4 * sigma)) + 2)
    if rect is None:
        return dict(id=candidate_id, rect=None, score=0.0, rawChangedSamples=0,
                    coverageAppearSamples=0, coverageDisappearSamples=0,
                    rawCoverageSquared=0.0, trackedSample=None)
    changed, edited_triangles, alive = p.edited_geometry(
        projected_original, triangles, candidate, transform)
    changed[:, :2] += phase
    edited_raw, edited_owners = p.raster(changed, edited_triangles, alive, rect, scale)
    x0, y0, x1, y1 = rect
    baseline_patch = base_raw[y0 * scale:y1 * scale, x0 * scale:x1 * scale]
    raw_delta = edited_raw - baseline_patch
    local_y, local_x = track_y - y0 * scale, track_x - x0 * scale
    if 0 <= local_y < edited_raw.shape[0] and 0 <= local_x < edited_raw.shape[1]:
        base_owner = int(base_owners[track_y, track_x])
        edited_owner = int(edited_owners[local_y, local_x])
        tracked_sample = dict(
            sampleYX=[track_y, track_x], sampleCenterXY=track_center,
            baselineCovered=bool(base_raw[track_y, track_x, 0]),
            baselineOwner=base_owner,
            baselineBarycentric=(barycentric_at(projected, triangles[base_owner], track_center)
                                 if base_owner >= 0 else None),
            editedCovered=bool(edited_raw[local_y, local_x, 0]),
            editedOwner=edited_owner,
            editedBarycentric=(barycentric_at(changed, edited_triangles[edited_owner], track_center)
                               if edited_owner >= 0 else None))
    else:
        tracked_sample = None
    residual = p.filtered(raw_delta, sigma, scale)
    coverage_delta = raw_delta[:, :, 0]
    changed_mask = coverage_delta != 0
    event_y, event_x = np.nonzero(changed_mask)
    raw_events = []
    for local_y, local_x in zip(event_y[:16], event_x[:16]):
        sample_y, sample_x = y0 * scale + int(local_y), x0 * scale + int(local_x)
        edited_owner = int(edited_owners[local_y, local_x])
        face_vertices = edited_triangles[edited_owner] if edited_owner >= 0 else None
        barycentric = None
        near_zero_weight = None
        sample_center = [(sample_x + .5) / scale, (sample_y + .5) / scale]
        if face_vertices is not None:
            barycentric = barycentric_at(changed, face_vertices, sample_center)
            near_zero_weight = int(np.argmin(np.abs(barycentric)))
        raw_events.append(dict(
            sampleYX=[sample_y, sample_x],
            sampleCenterXY=sample_center,
            beforeCovered=bool(base_raw[sample_y, sample_x, 0]),
            afterCovered=bool(edited_raw[local_y, local_x, 0]),
            beforeOwner=int(base_owners[sample_y, sample_x]),
            afterOwner=edited_owner,
            editedFaceVertexIds=face_vertices.tolist() if face_vertices is not None else None,
            barycentricWeights=barycentric,
            nearZeroWeightIndex=near_zero_weight,
            oppositeVertexId=(int(face_vertices[near_zero_weight])
                              if face_vertices is not None else None),
            coverageDelta=float(coverage_delta[local_y, local_x])))
    return dict(
        id=candidate_id,
        rect=list(rect),
        score=p.metrics(residual)['total'],
        rawChangedSamples=int(np.count_nonzero(changed_mask)),
        coverageAppearSamples=int(np.count_nonzero(coverage_delta > 0)),
        coverageDisappearSamples=int(np.count_nonzero(coverage_delta < 0)),
        rawCoverageSquared=float(np.square(coverage_delta).sum()),
        rawCoverageEvents=raw_events,
        trackedSample=tracked_sample)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('candidate_report', type=Path)
    parser.add_argument('--lo', type=float, default=2.2993548387096774)
    parser.add_argument('--hi', type=float, default=2.3106451612903225)
    parser.add_argument('--steps', type=int, default=49)
    parser.add_argument('--ids', type=int, nargs='+', default=[1656, 2275])
    parser.add_argument('--track-sample', type=int, nargs=2, default=None,
                        metavar=('Y', 'X'))
    parser.add_argument('--phase-x', type=float, default=0.0,
                        help='subpixel screen-space phase shift in pixels')
    parser.add_argument('--phase-y', type=float, default=0.0,
                        help='subpixel screen-space phase shift in pixels')
    parser.add_argument('--size', type=int, default=128)
    parser.add_argument('--scale', type=int, default=3)
    parser.add_argument('--sigma', type=float, default=.9)
    parser.add_argument('--allow-raster-override', action='store_true',
                        help='run a raster-resolution/filter sensitivity ablation')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.steps < 2 or args.hi <= args.lo:
        parser.error('require --steps >= 2 and --hi > --lo')

    pilot = load('camera_event_depth_pilot', 'depth_candidate_pilot.py')
    positions, triangles, candidates = pilot.load_capture(args.capture)
    report = json.loads(args.candidate_report.read_text())
    source = json.loads(Path('out/camera-rank-stability/torus-pool0-32.json').read_text())
    capture_hash = hashlib.sha256(args.capture.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(args.candidate_report.read_bytes()).hexdigest()
    if source['captureSha256'] != capture_hash or source['candidateReportSha256'] != report_hash:
        raise ValueError('inputs do not match the frozen Torus rank-stability oracle')
    phase = np.asarray([args.phase_x, args.phase_y], dtype=float)
    matches_oracle_parameters = (args.size == source['size'] and args.scale == source['scale']
                                 and args.sigma == source['sigma'] and
                                 np.array_equal(phase, np.zeros(2)))
    if not matches_oracle_parameters and not args.allow_raster_override:
        raise ValueError('raster parameters must match the frozen oracle')
    if args.track_sample is None:
        # Follow the same physical image location as the original 3x sample (190, 110).
        args.track_sample = [round(63.5 * args.scale - .5),
                             round((110.5 / 3) * args.scale - .5)]
    pool_ids = {int(row['id']) for row in report['frames'][source['poolFrame']]['candidates']}
    if any(cid not in pool_ids or cid >= len(candidates) for cid in args.ids):
        raise ValueError('every candidate ID must belong to the frozen pool')

    angles = np.linspace(args.lo, args.hi, args.steps)
    samples = []
    for index, angle in enumerate(angles):
        rows = [evaluate(pilot, positions, triangles, candidates, cid, float(angle),
                         args.size, args.scale, args.sigma, args.track_sample, phase)
                for cid in args.ids]
        samples.append(dict(index=index, angle=float(angle), candidates=rows))
        print(f"sample {index + 1}/{len(angles)} angle={angle:.12f} " +
              ' '.join(f"id{row['id']}={row['score']:.9g}/cov{row['rawChangedSamples']}"
                       for row in rows), flush=True)

    localized = []
    # Bisect the first sampled-coverage onset for each candidate in this interval.
    for cid in args.ids:
        def evaluate_count(angle):
            return evaluate(pilot, positions, triangles, candidates, cid, angle,
                            args.size, args.scale, args.sigma, args.track_sample, phase)

        values = [next(row['rawChangedSamples'] for row in sample['candidates']
                       if row['id'] == cid) for sample in samples]
        bracket = next(((float(angles[i]), float(angles[i + 1]), values[i], values[i + 1])
                        for i in range(len(angles) - 1)
                        if (values[i] == 0) != (values[i + 1] == 0)), None)
        if bracket is None:
            localized.append(dict(id=cid, eventBracket=None,
                                  note='no zero/nonzero raw coverage transition sampled'))
            continue
        left, right, left_count, right_count = bracket
        left_result = evaluate_count(left)
        right_result = evaluate_count(right)
        for _ in range(32):
            middle = (left + right) * .5
            result = evaluate_count(middle)
            count = result['rawChangedSamples']
            if (count == 0) == (left_count == 0):
                left, left_count, left_result = middle, count, result
            else:
                right, right_count, right_result = middle, count, result
        localized.append(dict(id=cid, eventBracket=[left, right],
                              countAtLeft=left_count, countAtRight=right_count,
                              leftEvaluation=left_result, rightEvaluation=right_result,
                              bracketWidth=right-left,
                              note='bisection localizes an event of this sampled raster oracle only'))

    output = dict(
        scope='localized frozen-pool Torus audit; orthographic depth/coverage raster; no PBR',
        warning='discrete sample event evidence is not a continuous camera certificate or a novelty claim',
        captureSha256=capture_hash,
        candidateReportSha256=report_hash,
        sourceOracleSha256=hashlib.sha256(Path('out/camera-rank-stability/torus-pool0-32.json').read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        size=args.size, scale=args.scale, sigma=args.sigma,
        matchesSourceOracleParameters=matches_oracle_parameters,
        ids=args.ids, trackSampleYX=args.track_sample,
        subpixelPhasePixels=phase.tolist(),
        interval=[args.lo, args.hi], samples=samples, localizedEvents=localized)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + '\n')
    print(f"wrote {args.out}")


if __name__ == '__main__':
    main()
