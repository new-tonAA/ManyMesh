"""Repeat the frozen adjacent-pair screen with explicit outside-group seam masks."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from probe_adjacent_partition_merges import adjacency, assembled_audit, select
from probe_partition_qem_exhaustion import boundary
from seam_contract_qem_control import SeamContractQEM


def simplify_unit(world, source, groups, members, owners):
    faces = sorted(i for m in members for i in groups[m]["source_faces"])
    vertices = sorted({v for i in faces for v in source[i][1]})
    remap = {v: i for i, v in enumerate(vertices)}
    triangles = np.array([[remap[v] for v in source[i][1]] for i in faces])
    mask = [remap[v] for v in vertices if owners[v] - set(members)]
    before = audit_partition([("g", tuple(map(int, t))) for t in triangles], False)
    start = time.perf_counter()
    solver = SeamContractQEM(world[vertices], triangles, mask)
    actual = solver.advance(0)
    output = solver.f[solver.alive]
    after = audit_partition([("g", tuple(map(int, t))) for t in output], False)
    edges = boundary(triangles)
    pinned = sorted({v for e in edges for v in e} | set(mask))
    if boundary(output) != edges or not np.array_equal(solver.p[pinned], world[np.array(vertices)[pinned]]) or not solver.check_seams():
        raise ValueError("boundary/shared-position contract violated")
    eligible = before["complete"] and after["complete"] and sorted(c["chi"] for c in before["components"]) == sorted(c["chi"] for c in after["components"])
    return dict(source_faces=faces, source_vertices=vertices, seam_locked=mask,
                actual=actual, eligible=eligible, input_audit=before, output_audit=after,
                work=len(faces), seconds=time.perf_counter() - start,
                heap_empty=not solver.heap, output_positions=solver.p.tolist(),
                output_triangles=output.tolist())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("previous", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    previous = json.loads(args.previous.read_text())
    baseline_path = Path(previous["baseline_path"])
    if hashlib.sha256(baseline_path.read_bytes()).hexdigest() != previous["baseline_sha256"]:
        raise ValueError("previous baseline changed")
    baseline = json.loads(baseline_path.read_text())
    root = Path(__file__).parent
    for name, digest in previous["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("previous source changed")
    names = (Path(__file__).name, "seam_contract_qem_control.py", "fixed_boundary_qem_control.py",
             "progressive_geometry_baseline.py", "audit_obj_contract_floor.py",
             "probe_partition_qem_exhaustion.py", "probe_adjacent_partition_merges.py")
    report = dict(schema=1, scope="geometry-only seam-contract control, no production attribute/distance gates",
                  previous_path=args.previous.as_posix(), previous_sha256=hashlib.sha256(args.previous.read_bytes()).hexdigest(),
                  baseline_path=baseline_path.as_posix(), baseline_sha256=previous["baseline_sha256"],
                  source_hashes={n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}, assets=[])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for old_asset, asset in zip(previous["assets"], baseline["assets"]):
        path = Path(asset["path"])
        if old_asset["path"] != asset["path"] or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("capture changed")
        source, _, _ = read_capture(path)
        lookup = {}
        for unit in json.loads(path.read_text())["units"]:
            for point in unit["positions"]:
                xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
                lookup.setdefault(xyz, len(lookup))
        world = (np.array(list(lookup)) - asset["center"]) / asset["radius"]
        groups = next(r for r in asset["partitions"] if r["capacity"] == 32)["groups"]
        owners = defaultdict(set)
        for i, group in enumerate(groups):
            for vertex in group["source_vertices"]:
                owners[vertex].add(i)
        fresh = [simplify_unit(world, source, groups, [i], owners) for i in range(len(groups))]
        initial_audit = assembled_audit(fresh, [], [])
        baseline_faces = sum(g["actual"] for g in fresh)
        print(path.stem, "seam-contract baseline", baseline_faces, "assembly", initial_audit["complete"], flush=True)
        contacts = adjacency(source, groups)
        if set(contacts) != {tuple(p["pair"]) for p in old_asset["pairs"]}:
            raise ValueError("adjacency population changed")
        pairs, start = [], time.perf_counter()
        for pi, p in enumerate(old_asset["pairs"]):
            a, b = p["pair"]
            result = simplify_unit(world, source, groups, [a, b], owners)
            result.update(pair=[a, b], shared_edges=p["shared_edges"],
                          normalized_shared_vertices=p["normalized_shared_vertices"],
                          gain=fresh[a]["actual"] + fresh[b]["actual"] - result["actual"])
            pairs.append(result)
            if (pi + 1) % 250 == 0:
                print(path.stem, "pairs", pi + 1, "/", len(contacts), flush=True)
        measured = dict(path=asset["path"], sha256=asset["sha256"], center=asset["center"], radius=asset["radius"],
                        baseline_faces=baseline_faces, baseline_assembly=initial_audit, groups=fresh, pairs=pairs,
                        total_work=sum(p["work"] for p in pairs), pair_seconds=time.perf_counter() - start,
                        baseline_seconds=sum(g["seconds"] for g in fresh), input_triangles=len(source), policies=[])
        for fraction in (.25, .5, 1.):
            for policy in ("pair_order", "shared_edges", "normalized_shared_vertices", "oracle_gain_per_work"):
                choice = select(pairs, policy, int(len(source) * fraction))
                selected = {tuple(p) for p in choice["selected"]}
                actual = baseline_faces - sum(p["gain"] for p in pairs if tuple(p["pair"]) in selected)
                audit = assembled_audit(fresh, pairs, choice["selected"])
                checked = initial_audit["complete"] and audit["complete"] and sorted(c["chi"] for c in initial_audit["components"]) == sorted(c["chi"] for c in audit["components"])
                if sum(c["triangles"] for c in audit["components"]) != actual:
                    raise ValueError("assembled count mismatch")
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
