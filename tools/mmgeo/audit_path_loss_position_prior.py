#!/usr/bin/env python3
"""Compare cell orders on frozen exact path losses, holding out mesh and pan."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean


def exact_cells(capture):
    rows = capture["candidateExactCellLosses"]
    if not rows or any(not row.get("complete", True) for row in rows):
        raise ValueError("expected full exact cell labels")
    cells = {row["candidateId"]: row["cells"] for row in rows}
    if set(cells) != set(capture["candidateIds"]):
        raise ValueError("exact cells do not match the candidate pool")
    grid = set(next(iter(cells.values())))
    if any(set(row) != grid or any(not math.isfinite(v) or v < 0 for v in row.values())
           for row in cells.values()):
        raise ValueError("inconsistent grid or invalid cell loss")
    return cells


def replay(capture, prior):
    exact = exact_cells(capture)
    grid = sorted(next(iter(exact.values())))
    step = min(map(int, capture["denseRasterResults"]))
    raster = {row["candidateId"]: {c: row["cells"][f"{step}:{c}"] for c in grid}
              for row in capture["candidateRasterCellLosses"]}
    order = sorted(capture["candidateIds"], key=lambda cid: math.fsum(raster[cid].values()))
    policies = {
        "fixed": lambda cheap, c: c,
        "raster": lambda cheap, c: (-cheap[c], c),
        "position": lambda cheap, c: (-prior[c], c),
        "rasterThenPosition": lambda cheap, c: (-cheap[c], -prior[c], c),
    }
    full_minimum = min(math.fsum(values.values()) for values in exact.values())
    counts = {}
    for name, priority in policies.items():
        incumbent = math.inf
        visited = 0
        for cid in order:
            partial = 0.0
            for cell in sorted(grid, key=lambda c: priority(raster[cid], c)):
                partial += exact[cid][cell]
                visited += 1
                if partial >= incumbent:
                    break
            incumbent = min(incumbent, partial)
        if not math.isclose(incumbent, full_minimum, rel_tol=1e-12):
            raise ValueError(f"{name}: winner loss differs from full integration")
        counts[name] = visited
    return {"panAngle": capture["panAngle"], "rasterSteps": step, "visited": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", nargs=2, type=Path, required=True,
                        help="two full captures of one mesh, in the same pan order for all meshes")
    pairs = parser.parse_args().pair
    data = [[json.loads(path.read_text(encoding="utf-8")) for path in pair] for pair in pairs]
    if len(data) < 2:
        parser.error("at least two meshes are required")
    hashes = [pair[0]["captureSha256"] for pair in data]
    pans = [capture["panAngle"] for capture in data[0]]
    if (len(set(hashes)) != len(data) or len(set(pans)) != 2 or
            any(pair[0]["captureSha256"] != pair[1]["captureSha256"] or
                [capture["panAngle"] for capture in pair] != pans for pair in data)):
        parser.error("pairs must use distinct meshes and the same two pan directions")

    for held, pair in enumerate(data):
        for pan_index, capture in enumerate(pair):
            shares = []
            grid = set(next(iter(exact_cells(capture).values())))
            for i, train_pair in enumerate(data):
                if i == held:
                    continue
                for cells in exact_cells(train_pair[1 - pan_index]).values():
                    if set(cells) != grid:
                        parser.error("training and evaluation grids must match")
                    total = math.fsum(cells.values())
                    if total > 1e-20:
                        shares.append({cell: loss / total for cell, loss in cells.items()})
            if not shares:
                parser.error("no informative training candidates for this split")
            prior = {cell: mean(row[cell] for row in shares) for cell in grid}
            print(json.dumps({"capture": str(pairs[held][pan_index]), **replay(capture, prior)}))


if __name__ == "__main__":
    main()
