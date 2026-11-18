#!/usr/bin/env python3
"""Replay visible coverage toggles with local Gaussian-energy updates."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load_pilot():
    path = Path(__file__).with_name("depth_candidate_pilot.py")
    spec = importlib.util.spec_from_file_location("incremental_coverage_pilot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_raw_residual(pilot, positions, triangles, candidate, angle, size, scale):
    transform = pilot.camera(positions, angle, size)
    projected = pilot.project(positions, transform)
    full = (0, 0, size, size)
    valid = np.ones(len(triangles), dtype=bool)
    source, _ = pilot.raster(projected, triangles, valid, full, scale)
    changed, edited_triangles, alive = pilot.edited_geometry(
        projected, triangles, candidate, transform)
    collapsed, _ = pilot.raster(changed, edited_triangles, alive, full, scale)
    return source[:, :, 0] - collapsed[:, :, 0]


def reduced_axis_response(sample, output_size, scale, kernel):
    radius = len(kernel) // 2
    block_starts = np.arange(output_size, dtype=np.int64) * scale
    response = np.zeros(output_size, dtype=np.float64)
    for offset in range(scale):
        indices = block_starts + offset - sample + radius
        valid = (indices >= 0) & (indices < len(kernel))
        response[valid] += kernel[indices[valid]] / scale
    nonzero = np.flatnonzero(response)
    if not len(nonzero):
        return 0, 0, response[:0]
    lo, hi = int(nonzero[0]), int(nonzero[-1]) + 1
    return lo, hi, response[lo:hi]


def apply_toggle(filtered_image, energy, x, y, delta, kernel, scale):
    y0, y1, ky = reduced_axis_response(y, filtered_image.shape[0], scale, kernel)
    x0, x1, kx = reduced_axis_response(x, filtered_image.shape[1], scale, kernel)
    if y0 == y1 or x0 == x1:
        return energy
    weights = ky[:, None] * kx[None, :]
    patch = filtered_image[y0:y1, x0:x1]
    energy += float(np.sum(2 * delta * patch * weights + delta * delta * weights * weights))
    patch += delta * weights
    return energy


def direct_energy(pilot, raw, sigma, scale):
    channels = np.zeros(raw.shape + (2,), dtype=np.float64)
    channels[:, :, 0] = raw
    filtered = pilot.filtered(channels, sigma, scale)[:, :, 0]
    return float(np.square(filtered).sum()), filtered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("heldout_report", type=Path)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--sigma", type=float, default=.9)
    parser.add_argument("--uniform-checks", type=int, default=0,
                        help="also compare against direct raster measurements at this many angles")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pilot = load_pilot()
    positions, triangles, candidates = pilot.load_capture(args.capture)
    events_report = json.loads(args.events.read_text(encoding="utf-8"))
    heldout = json.loads(args.heldout_report.read_text(encoding="utf-8"))
    asset = next(row for row in events_report["assets"]
                 if row["candidateId"] == args.candidate_id)
    camera = events_report["camera"]
    size, scale = int(camera["size"]), int(camera["scale"])
    start, end = float(camera["start"]), float(camera["end"])
    candidate = candidates[args.candidate_id]
    transitions = sorted(asset["residualTransitions"], key=lambda row: row["angle"])

    start_angle = start + 1e-7
    raw = build_raw_residual(pilot, positions, triangles, candidate, start_angle, size, scale)
    energy, filtered_image = direct_energy(pilot, raw, args.sigma, scale)
    initial_energy = energy
    kernel = pilot.gaussian(args.sigma, scale)
    integral = 0.0
    current_angle = start_angle
    views = [(float(row["angle"]), row) for row in heldout["views"]]
    if args.uniform_checks:
        if args.uniform_checks < 2:
            parser.error("--uniform-checks must be 0 or at least 2")
        dense_angles = np.linspace(start_angle, end - 1e-7, args.uniform_checks)
        views.extend((float(theta), None) for theta in dense_angles)
    views.sort(key=lambda row: row[0])
    measurements = {}
    transition_index = 0
    for theta, view in views:
        while transition_index < len(transitions) and transitions[transition_index]["angle"] < theta:
            angle = float(transitions[transition_index]["angle"])
            integral += energy * max(0.0, angle - current_angle)
            current_angle = angle
            while (transition_index < len(transitions) and
                   abs(float(transitions[transition_index]["angle"]) - angle) < 1e-9):
                transition = transitions[transition_index]
                energy = apply_toggle(filtered_image, energy, int(transition["sampleX"]),
                                      int(transition["sampleY"]), int(transition["delta"]),
                                      kernel, scale)
                transition_index += 1
        prediction = float(energy)
        if view is None:
            check_raw = build_raw_residual(pilot, positions, triangles, candidate, theta,
                                           size, scale)
            measured, _ = direct_energy(pilot, check_raw, args.sigma, scale)
        else:
            score_row = next(row for row in view["rows"] if row["id"] == args.candidate_id)
            measured = float(score_row["errors"]["coverage"])
        measurements[str(theta)] = {"predicted": prediction, "measured": measured,
                                    "absoluteError": abs(prediction - measured)}

    while transition_index < len(transitions):
        angle = float(transitions[transition_index]["angle"])
        integral += energy * max(0.0, angle - current_angle)
        current_angle = angle
        while (transition_index < len(transitions) and
               abs(float(transitions[transition_index]["angle"]) - angle) < 1e-9):
            transition = transitions[transition_index]
            energy = apply_toggle(filtered_image, energy, int(transition["sampleX"]),
                                  int(transition["sampleY"]), int(transition["delta"]),
                                  kernel, scale)
            transition_index += 1
    integral += energy * max(0.0, end - current_angle)

    errors = [row["absoluteError"] for row in measurements.values()]
    output = {
        "scope": "coverage-channel event replay compared with independent direct raster measurements",
        "limitations": [
            "transition list is candidate-local and may omit events from unchanged geometry",
            "integrated value is exact only if the event list is complete",
            "depth and full RGB loss are not integrated",
        ],
        "captureSha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
        "eventsSha256": hashlib.sha256(args.events.read_bytes()).hexdigest(),
        "heldoutReportSha256": hashlib.sha256(args.heldout_report.read_bytes()).hexdigest(),
        "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidateId": args.candidate_id,
        "sigma": args.sigma,
        "scale": scale,
        "startEnergy": initial_energy,
        "transitionCount": len(transitions),
        "uniformCheckCount": args.uniform_checks,
        "measurementCount": len(measurements),
        "integratedCoverageLoss": integral / (end - start),
        "heldoutMeasurements": measurements,
        "maxHeldoutAbsoluteError": max(errors, default=0.0),
        "medianHeldoutAbsoluteError": float(np.median(errors)) if errors else 0.0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"candidate={args.candidate_id}: toggles={len(transitions)} "
          f"integratedCoverage={output['integratedCoverageLoss']:.9g} "
          f"maxHeldoutError={output['maxHeldoutAbsoluteError']:.4g}; wrote {args.out}")


if __name__ == "__main__":
    main()
