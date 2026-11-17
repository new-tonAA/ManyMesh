"""Exhaustive two-group counterfactuals and work-budget policy screen; geometry only."""
import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from fixed_boundary_qem_control import FixedBoundaryQEM
from probe_partition_qem_exhaustion import boundary


def adjacency(source, groups):
    owner = {face: group for group, entry in enumerate(groups) for face in entry["source_faces"]}
    if sorted(owner) != list(range(len(source))) or sum(len(g["source_faces"]) for g in groups) != len(source):
        raise ValueError("invalid frozen partition")
    uses = defaultdict(set)
    for face, (material, triangle) in enumerate(source):
        for i in range(3):
            uses[material, tuple(sorted((triangle[i], triangle[(i + 1) % 3])))].add(owner[face])
    return Counter(pair for owners in uses.values() for pair in combinations(sorted(owners), 2))


def select(pairs, policy, work_limit):
    if policy == "shared_edges":
        key = lambda p: (-p["shared_edges"], p["pair"])
    elif policy == "normalized_shared_vertices":
        key = lambda p: (-p["normalized_shared_vertices"], p["pair"])
    elif policy == "oracle_gain_per_work":
        key = lambda p: (-(p["gain"] if p["eligible"] else 0) / p["work"], p["pair"])
    else:
        key = lambda p: p["pair"]
    spent, used, selected, queried = 0, set(), [], []
    for p in sorted(pairs, key=key):
        if used.intersection(p["pair"]) or spent + p["work"] > work_limit:
            continue
        spent += p["work"]
        queried.append(p["pair"])
        if p["eligible"] and p["gain"] > 0:
            used.update(p["pair"])
            selected.append(p["pair"])
    return dict(work=spent, queried=queried, selected=selected)


def assembled_audit(groups, pairs, selected):
    replacements = {tuple(p["pair"]): p for p in pairs}
    used = {g for pair in selected for g in pair}
    parts = [g for i, g in enumerate(groups) if i not in used]
    parts += [replacements[tuple(pair)] for pair in selected]
    lookup, triangles = {}, []
    for part in parts:
        ids = [lookup.setdefault(tuple(point), len(lookup)) for point in part["output_positions"]]
        triangles.extend(("assembled", tuple(ids[i] for i in t)) for t in part["output_triangles"])
    return audit_partition(triangles, False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    data = json.loads(args.baseline.read_text())
    root = Path(__file__).parent
    for name, digest in data["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("baseline source changed")
    report = dict(schema=1, scope="all adjacent pairs of capacity-32 BFS groups; geometry-only work proxy",
                  baseline_path=args.baseline.as_posix(), baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                  source_hashes={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
                                 (Path(__file__).name, "fixed_boundary_qem_control.py", "progressive_geometry_baseline.py",
                                  "audit_obj_contract_floor.py", "probe_partition_qem_exhaustion.py")}, assets=[])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for asset in data["assets"]:
        path = Path(asset["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("capture changed")
        source, _, _ = read_capture(path)
        lookup = {}
        for unit in json.loads(path.read_text())["units"]:
            for point in unit["positions"]:
                xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
                lookup.setdefault(xyz, len(lookup))
        world = (np.array(list(lookup)) - asset["center"]) / asset["radius"]
        original = next(r for r in asset["partitions"] if r["capacity"] == 32)
        groups = original["groups"]
        contacts = adjacency(source, groups)
        pairs = []
        start = time.perf_counter()
        for pi, ((a, b), shared_edges) in enumerate(sorted(contacts.items())):
            faces = sorted(groups[a]["source_faces"] + groups[b]["source_faces"])
            vertices = sorted(set(groups[a]["source_vertices"]) | set(groups[b]["source_vertices"]))
            remap = {v: i for i, v in enumerate(vertices)}
            triangles = np.array([[remap[v] for v in source[i][1]] for i in faces])
            before = audit_partition([("g", tuple(map(int, t))) for t in triangles], False)
            t0 = time.perf_counter()
            solver = FixedBoundaryQEM(world[vertices], triangles)
            actual = solver.advance(0)
            output = solver.f[solver.alive]
            after = audit_partition([("g", tuple(map(int, t))) for t in output], False)
            edges = boundary(triangles)
            pinned = sorted({v for edge in edges for v in edge})
            if edges != boundary(output) or not np.array_equal(solver.p[pinned], world[np.array(vertices)[pinned]]):
                raise ValueError("merged boundary changed")
            eligible = before["complete"] and after["complete"] and sorted(c["chi"] for c in before["components"]) == sorted(c["chi"] for c in after["components"])
            va, vb = set(groups[a]["source_vertices"]), set(groups[b]["source_vertices"])
            pair = dict(pair=[a, b], shared_edges=shared_edges, work=len(faces),
                        normalized_shared_vertices=len(va & vb) * (1 / math.sqrt(len(va)) + 1 / math.sqrt(len(vb))),
                        gain=groups[a]["actual"] + groups[b]["actual"] - actual, actual=actual,
                        eligible=eligible, input_audit=before, output_audit=after,
                        seconds=time.perf_counter() - t0, output_positions=solver.p.tolist(),
                        output_triangles=output.tolist())
            pairs.append(pair)
            if (pi + 1) % 250 == 0:
                print(path.stem, "pairs", pi + 1, "/", len(contacts), flush=True)
        measured = dict(path=asset["path"], sha256=asset["sha256"], baseline_faces=original["actual"],
                        input_triangles=len(source), pairs=pairs, total_seconds=time.perf_counter() - start,
                        total_work=sum(p["work"] for p in pairs), policies=[])
        initial_assembly = assembled_audit(groups, pairs, [])
        measured["baseline_assembly"] = initial_assembly
        for fraction in (.25, .5, 1.):
            for policy in ("pair_order", "shared_edges", "normalized_shared_vertices", "oracle_gain_per_work"):
                choice = select(pairs, policy, int(len(source) * fraction))
                selected_pairs = {tuple(p) for p in choice["selected"]}
                actual = original["actual"] - sum(p["gain"] for p in pairs if tuple(p["pair"]) in selected_pairs)
                audit = assembled_audit(groups, pairs, choice["selected"])
                if sum(c["triangles"] for c in audit["components"]) != actual:
                    raise ValueError("assembled face count mismatch")
                checked = initial_assembly["complete"] and audit["complete"] and sorted(c["chi"] for c in initial_assembly["components"]) == sorted(c["chi"] for c in audit["components"])
                measured["policies"].append(dict(policy=policy, budget_fraction=fraction, actual=actual,
                                                 assembled_topology_checked=checked, audit=audit, **choice))
                print(path.stem, fraction, policy, actual, "work", choice["work"], "assembly", checked, flush=True)
        report["assets"].append(measured)
        args.out.with_suffix(".partial.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream)
        stream.write("\n")


if __name__ == "__main__":
    main()
