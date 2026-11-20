"""Test equal-count QEM alternatives on disjoint cameras and sample phases."""

import argparse
import json
from pathlib import Path
import time

import fast_simplification
import numpy as np

from make_refinement_pairs import load_geometry, verify_asset
from probe_contour_relocation import (
    FIT_PHASES, FIT_VIEWS, METRICS, TEST_PHASES, TEST_VIEWS, measure, targets,
)
from probe_filter_aware_cuts import shaded


POOL = (
    ("agg4", 4.0, (1.0, 1.0, 1.0)),
    ("agg9", 9.0, (1.0, 1.0, 1.0)),
    ("stretchX", 7.0, (2.0, 1.0, 1.0)),
    ("stretchY", 7.0, (1.0, 2.0, 1.0)),
    ("stretchZ", 7.0, (1.0, 1.0, 2.0)),
)


def qem(vertices, faces, target, aggressiveness, stretch, return_trace=False):
    metric = np.asarray(stretch)
    scaled, triangles, *trace = fast_simplification.simplify(
        vertices * metric, faces, target_count=target, agg=aggressiveness,
        return_collapses=return_trace)
    return (scaled / metric, triangles, *trace)


def experiment(path, size):
    start = time.perf_counter()
    vertices, faces = load_geometry(path)
    source = shaded(vertices, faces)
    positions, indices = qem(vertices, faces, max(8, round(len(faces) * 0.2)), 7.0, (1, 1, 1))
    budget = len(indices)
    if not budget:
        raise ValueError(f"QEM returned an empty mesh: {path}")
    meshes = {"qem": shaded(positions, indices)}
    rejected = {}
    for name, aggressiveness, stretch in POOL:
        positions, indices = qem(vertices, faces, budget, aggressiveness, stretch)
        if len(indices) == budget - 1 and budget + 1 < len(faces):
            positions, indices = qem(vertices, faces, budget + 1, aggressiveness, stretch)
        if len(indices) != budget:
            rejected[name] = len(indices)
            continue
        meshes[name] = shaded(positions, indices)
    fit = targets(source, size, FIT_VIEWS, FIT_PHASES)
    fit_losses = {name: measure(mesh, size, fit).tolist() for name, mesh in meshes.items()}
    baseline = fit_losses["qem"]
    qualified = [name for name, scores in fit_losses.items()
                 if scores[1] <= baseline[1] and scores[2] <= baseline[2]]
    selected = min(qualified, key=lambda name: fit_losses[name][0])
    selected_native = min(qualified, key=lambda name: fit_losses[name][3])
    fit_ms = 1000 * (time.perf_counter() - start)

    test = {}
    for test_size in (size, size + 32):
        references = targets(source, test_size, TEST_VIEWS, TEST_PHASES)
        measured = {name: measure(mesh, test_size, references).tolist()
                    for name, mesh in meshes.items()}
        # This comparison uses held-out images for the choice and is an offline bound.
        guarded_oracle = min((n for n, scores in measured.items()
                              if scores[1] <= measured["qem"][1] and scores[2] <= measured["qem"][2]),
                             key=lambda name: measured[name][0])
        test[str(test_size)] = {"losses": measured, "oracle": guarded_oracle}
    return {"sourceFaces": len(faces), "faces": budget, "fitMs": fit_ms,
            "rejectedFaceCounts": rejected, "fit": fit_losses, "selected": selected,
            "selectedNative": selected_native, "test": test}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_roots", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--size", type=int, choices=(64, 96, 128), default=96)
    args = parser.parse_args()
    assets = {}
    for root in args.asset_roots:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        for source in sources:
            name = source["name"]
            if name in assets:
                parser.error(f"Duplicate asset name: {name}")
            row = experiment(verify_asset(root, source), args.size)
            assets[name] = {**row, "source": source}
            test = row["test"][str(args.size)]
            base = test["losses"]["qem"][0]
            measures = [100 * (1 - test["losses"][policy][0] / base)
                        for policy in (row["selected"], test["oracle"])]
            print(f"{name}: {row['faces']} faces, {len(row['fit'])} candidates, "
                  f"{row['selected']} {measures[0]:+.2f}%, oracle {measures[1]:+.2f}%", flush=True)
    report = {"size": args.size, "metrics": METRICS, "fitViews": list(FIT_VIEWS),
              "testViews": list(TEST_VIEWS), "assets": assets}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
