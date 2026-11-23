#!/usr/bin/env python3
"""Tiny analytic screen for filtered depth events on an orthographic camera segment.

The scene has two overlapping affine-depth triangles whose visibility order swaps during
translation. The probe compares a piecewise envelope integral with dense direct sampling.
It is a mathematical unit experiment, not a mesh-simplification quality or performance result.
"""

import json
from pathlib import Path

import numpy as np


PATH = (-0.8, 0.8)
SAMPLE_Y = 0.0
FILTER_SAMPLES = ((-0.15, 0.25), (0.0, 0.50), (0.15, 0.25))
DEPTH_WEIGHT = 1.0


def triangle_interval_and_depth_line(vertices, sample_x):
    """Return path coverage interval and z(t) for x=sample_x+t, fixed sample y."""
    vertices = np.asarray(vertices, dtype=np.float64)
    intersections = []
    for a, b in ((vertices[0], vertices[1]),
                 (vertices[1], vertices[2]),
                 (vertices[2], vertices[0])):
        y0, y1 = float(a[1]), float(b[1])
        if (SAMPLE_Y - y0) * (SAMPLE_Y - y1) > 0.0 or abs(y1 - y0) < 1e-12:
            continue
        alpha = (SAMPLE_Y - y0) / (y1 - y0)
        if -1e-12 <= alpha <= 1.0 + 1e-12:
            intersections.append(float(a[0] + alpha * (b[0] - a[0])))
    if len(intersections) < 2:
        return None

    plane = np.column_stack((vertices[:, 0], vertices[:, 1], np.ones(3)))
    a_x, a_y, c = np.linalg.solve(plane, vertices[:, 2])
    x_lo, x_hi = min(intersections), max(intersections)
    lo = max(PATH[0], x_lo - sample_x)
    hi = min(PATH[1], x_hi - sample_x)
    if lo >= hi:
        return None
    return {
        "lo": lo,
        "hi": hi,
        "slope": float(a_x),
        "intercept": float(a_x * sample_x + a_y * SAMPLE_Y + c),
    }


def build_mesh(triangle_planes, sample_x):
    base_xy = ((-1.0, -1.0), (1.0, -1.0), (0.0, 1.0))
    result = []
    for slope_x, offset in triangle_planes:
        vertices = [(x, y, slope_x * x + offset) for x, y in base_xy]
        event = triangle_interval_and_depth_line(vertices, sample_x)
        if event:
            result.append(event)
    return result


def make_events(meshes, include_depth_crossings=True):
    events = {float(PATH[0]), float(PATH[1])}
    for mesh_list in meshes:
        for tri in mesh_list:
            events.add(float(tri["lo"]))
            events.add(float(tri["hi"]))
        if include_depth_crossings:
            for i, left in enumerate(mesh_list):
                for right in mesh_list[i + 1:]:
                    if abs(left["slope"] - right["slope"]) < 1e-12:
                        continue
                    cross = ((right["intercept"] - left["intercept"]) /
                             (left["slope"] - right["slope"]))
                    if (max(left["lo"], right["lo"]) < cross <
                            min(left["hi"], right["hi"])):
                        events.add(float(cross))
    return sorted(events)


def visible_line(mesh_list, time):
    active = [tri for tri in mesh_list if tri["lo"] < time < tri["hi"]]
    if not active:
        return None
    return max(active, key=lambda tri: tri["slope"] * time + tri["intercept"])


def integrate_square_line(slope, intercept, lo, hi):
    return (slope * slope * (hi ** 3 - lo ** 3) / 3.0 +
            slope * intercept * (hi ** 2 - lo ** 2) +
            intercept * intercept * (hi - lo))


def exact_filtered_energy(source_planes, candidate_planes, include_depth_crossings=True):
    sample_meshes = []
    for sample_x, weight in FILTER_SAMPLES:
        source = build_mesh(source_planes, sample_x)
        candidate = build_mesh(candidate_planes, sample_x)
        sample_meshes.append((weight, source, candidate))

    events = make_events([mesh for _, source, candidate in sample_meshes
                          for mesh in (source, candidate)], include_depth_crossings)
    energy = 0.0
    event_rows = []
    for lo, hi in zip(events, events[1:]):
        mid = 0.5 * (lo + hi)
        cov_diff = 0.0
        depth_slope = 0.0
        depth_intercept = 0.0
        visible_states = []
        for weight, source, candidate in sample_meshes:
            src = visible_line(source, mid)
            dst = visible_line(candidate, mid)
            cov_diff += weight * ((src is not None) - (dst is not None))
            if src is not None:
                depth_slope += weight * src["slope"]
                depth_intercept += weight * src["slope"] * 0.0 + weight * src["intercept"]
            if dst is not None:
                depth_slope -= weight * dst["slope"]
                depth_intercept -= weight * dst["intercept"]
            visible_states.append((src is not None, dst is not None,
                                   None if src is None else source.index(src),
                                   None if dst is None else candidate.index(dst)))
        interval_energy = ((hi - lo) * cov_diff * cov_diff * DEPTH_WEIGHT +
                           integrate_square_line(depth_slope, depth_intercept, lo, hi))
        energy += interval_energy
        event_rows.append({"interval": [lo, hi], "visibleStates": visible_states,
                           "filteredCoverageResidual": cov_diff,
                           "filteredDepthResidual": [depth_slope, depth_intercept],
                           "energy": interval_energy})
    return energy, events, event_rows


def direct_filtered_energy(source_planes, candidate_planes, samples=400_000):
    times = np.linspace(PATH[0], PATH[1], samples, endpoint=False) + (
        PATH[1] - PATH[0]) / (2 * samples)
    filtered_cov = np.zeros_like(times)
    filtered_depth = np.zeros_like(times)
    for sample_x, weight in FILTER_SAMPLES:
        source = build_mesh(source_planes, sample_x)
        candidate = build_mesh(candidate_planes, sample_x)
        src_depth = np.zeros_like(times)
        dst_depth = np.zeros_like(times)
        src_cov = np.zeros_like(times)
        dst_cov = np.zeros_like(times)
        for tri in source:
            active = (times > tri["lo"]) & (times < tri["hi"])
            depth = tri["slope"] * times + tri["intercept"]
            update = active & ((src_cov == 0.0) | (depth > src_depth))
            src_cov[active] = 1.0
            src_depth[update] = depth[update]
        for tri in candidate:
            active = (times > tri["lo"]) & (times < tri["hi"])
            depth = tri["slope"] * times + tri["intercept"]
            update = active & ((dst_cov == 0.0) | (depth > dst_depth))
            dst_cov[active] = 1.0
            dst_depth[update] = depth[update]
        filtered_cov += weight * (src_cov - dst_cov)
        filtered_depth += weight * (src_depth - dst_depth)
    energy = (PATH[1] - PATH[0]) / samples * float(np.sum(
        filtered_cov * filtered_cov + filtered_depth * filtered_depth))
    return energy


def random_envelope_screen(case_count=12, dense_samples=50_000):
    rng = np.random.default_rng(20261119)
    rows = []
    for case in range(case_count):
        count = int(rng.integers(2, 7))
        source = tuple((float(rng.uniform(-0.55, 0.55)),
                        float(rng.uniform(0.1, 0.9))) for _ in range(count))
        keep = sorted(set([int(rng.integers(0, count))] +
                          [i for i in range(count) if rng.random() < 0.45]))
        candidate = tuple(source[i] for i in keep)
        exact, _, _ = exact_filtered_energy(source, candidate)
        direct = direct_filtered_energy(source, candidate, samples=dense_samples)
        rel = abs(exact - direct) / max(abs(exact), 1e-12)
        rows.append({"case": case, "sourcePlaneCount": count,
                     "candidatePlaneCount": len(candidate),
                     "exactEnergy": exact, "denseEnergy": direct,
                     "relativeDifference": rel})
    return rows


def main():
    source = ((0.25, 0.4), (-0.25, 0.4))
    candidate = ((0.25, 0.4),)
    exact, events, rows = exact_filtered_energy(source, candidate)
    no_depth_exact, no_depth_events, _ = exact_filtered_energy(
        source, candidate, include_depth_crossings=False)
    direct = direct_filtered_energy(source, candidate)
    random_rows = random_envelope_screen()
    relative_error = abs(exact - direct) / max(abs(exact), 1e-12)
    result = {
        "scope": "synthetic orthographic translation; filtered depth + coverage residual",
        "sourcePlanes": source,
        "candidatePlanes": candidate,
        "filterSamples": FILTER_SAMPLES,
        "cameraPath": PATH,
        "eventTimes": events,
        "exactFilteredPathEnergy": exact,
        "denseMidpointEnergy": direct,
        "relativeDifference": relative_error,
        "coverageEventsOnlyEnergy": no_depth_exact,
        "coverageEventsOnlyTimes": no_depth_events,
        "coverageOnlyRelativeError": abs(no_depth_exact - direct) / max(abs(direct), 1e-12),
        "randomCases": random_rows,
        "randomCaseWorstRelativeDifference": max(
            row["relativeDifference"] for row in random_rows),
        "intervals": rows,
        "claimBoundary": "verifies this finite piecewise-affine envelope calculation only; "
                         "not a contribution or runtime benefit",
    }
    output = Path("out/filtered-depth-envelope-events-20261119.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"eventTimes": events,
                      "exactEnergy": exact,
                      "denseEnergy": direct,
                      "relativeDifference": relative_error,
                      "coverageOnlyEnergy": no_depth_exact,
                      "coverageOnlyRelativeError": abs(no_depth_exact - direct) /
                                                   max(abs(direct), 1e-12),
                      "randomCases": len(random_rows),
                      "randomCaseWorstRelativeDifference": max(
                          row["relativeDifference"] for row in random_rows),
                      "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
