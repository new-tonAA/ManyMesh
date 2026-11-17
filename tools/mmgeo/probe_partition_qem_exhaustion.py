"""Run the existing geometry-only QEM on frozen BFS groups to test floor informativeness."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from progressive_geometry_baseline import ProgressiveQEM


def boundary(triangles):
    counts = Counter(tuple(sorted((int(t[i]), int(t[(i + 1) % 3]))))
                     for t in triangles for i in range(3))
    return {edge for edge, uses in counts.items() if uses == 1}


def run_group(world, source, group, expected_floor):
    ids = sorted({v for face in group for v in source[face][1]})
    remap = {v: i for i, v in enumerate(ids)}
    triangles = np.array([[remap[v] for v in source[face][1]] for face in group], dtype=int)
    before = audit_partition([("group", tuple(map(int, t))) for t in triangles], False)
    if before["conditional_floor"] != expected_floor:
        raise ValueError("frozen floor mismatch")
    start = time.perf_counter()
    solver = ProgressiveQEM(world[ids], triangles)
    actual = solver.advance(0)
    output = solver.f[solver.alive].copy()
    after = audit_partition([("group", tuple(map(int, t))) for t in output], False)
    old_boundary = boundary(triangles)
    boundary_ok = old_boundary == boundary(output)
    pinned = sorted({v for edge in old_boundary for v in edge})
    positions_ok = np.array_equal(solver.p[pinned], world[np.array(ids)[pinned]])
    topology_ok = (before["complete"] and after["complete"] and
                   sorted(c["chi"] for c in before["components"]) ==
                   sorted(c["chi"] for c in after["components"]))
    floor_ok = expected_floor is None or actual >= expected_floor
    if not (boundary_ok and positions_ok and floor_ok):
        raise ValueError("boundary lock or face-floor invariant failed")
    return dict(source_faces=group, source_vertices=ids, input_triangles=len(group),
                actual=actual, floor=expected_floor, heap_empty=not solver.heap,
                applied=len(solver.actions), rejected=solver.rejected,
                locked_vertices=len(solver.locked), seconds=time.perf_counter() - start,
                boundary_preserved=boundary_ok, boundary_positions_preserved=positions_ok,
                topology_checked=topology_ok, output_audit=after,
                output_positions=solver.p.tolist(), output_triangles=output.tolist())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("partition_report", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    root = Path(__file__).parent
    frozen = json.loads(args.partition_report.read_text())
    for name, digest in frozen["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("partition source changed")
    report = dict(schema=1, scope="geometry-only reference QEM exhaustion, no production gate or quality result",
                  partition_sha256=hashlib.sha256(args.partition_report.read_bytes()).hexdigest(),
                  source_hashes={name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                 for name in (Path(__file__).name, "progressive_geometry_baseline.py",
                                              "audit_obj_contract_floor.py")},
                  numpy_version=np.__version__, assets=[])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for asset in frozen["assets"]:
        path = Path(asset["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("capture changed")
        source, _, _ = read_capture(path)
        lookup = {}
        for unit in json.loads(path.read_text())["units"]:
            for point in unit["positions"]:
                xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
                lookup.setdefault(xyz, len(lookup))
        world = np.array(list(lookup), dtype=float)
        center = (world.min(0) + world.max(0)) * .5
        radius = max(float(np.linalg.norm(world - center, axis=1).max()), 1e-12)
        world = (world - center) / radius
        measured = dict(path=asset["path"], sha256=asset["sha256"], center=center.tolist(),
                        radius=radius, partitions=[])
        for partition in asset["partitions"]:
            groups = []
            for ids, audit in zip(partition["group_face_ids"], partition["group_audits"]):
                groups.append(run_group(world, source, ids, audit["conditional_floor"]))
            actual = sum(g["actual"] for g in groups)
            row = dict(capacity=partition["capacity"], input_triangles=len(source), actual=actual,
                       fraction=actual / len(source), floor=partition["conditional_floor"],
                       seconds=sum(g["seconds"] for g in groups),
                       topology_unverified_groups=sum(not g["topology_checked"] for g in groups),
                       groups=groups)
            measured["partitions"].append(row)
            print(path.stem, row["capacity"], actual, row["fraction"], "floor", row["floor"],
                  "seconds", round(row["seconds"], 3), "unchecked", row["topology_unverified_groups"], flush=True)
        report["assets"].append(measured)
        # Preserve completed assets if a later asset cannot finish. This is explicitly partial.
        args.out.with_suffix(".partial.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream)
        stream.write("\n")


if __name__ == "__main__":
    main()
