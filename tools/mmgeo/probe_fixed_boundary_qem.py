"""Frozen-group comparison to isolate the reference's locked-endpoint restriction."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from fixed_boundary_qem_control import FixedBoundaryQEM
from probe_partition_qem_exhaustion import boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    root = Path(__file__).parent
    baseline = json.loads(args.baseline.read_text())
    for name, digest in baseline["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("baseline source changed")
    names = (Path(__file__).name, "fixed_boundary_qem_control.py", "audit_obj_contract_floor.py",
             "progressive_geometry_baseline.py", "probe_partition_qem_exhaustion.py")
    report = dict(schema=1, scope="classical geometry-only fixed-boundary control, no novelty or production quality claim",
                  baseline_path=args.baseline.as_posix(),
                  baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                  source_hashes={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
                  numpy_version=np.__version__, assets=[])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for asset in baseline["assets"]:
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
        output_asset = dict(path=asset["path"], sha256=asset["sha256"],
                            center=asset["center"], radius=asset["radius"], partitions=[])
        for row in asset["partitions"]:
            groups = []
            for original in row["groups"]:
                ids = original["source_vertices"]
                remap = {v: i for i, v in enumerate(ids)}
                triangles = np.array([[remap[v] for v in source[i][1]] for i in original["source_faces"]])
                before = audit_partition([("g", tuple(map(int, t))) for t in triangles], False)
                start = time.perf_counter()
                solver = FixedBoundaryQEM(world[ids], triangles)
                actual = solver.advance(0)
                output = solver.f[solver.alive].copy()
                after = audit_partition([("g", tuple(map(int, t))) for t in output], False)
                pinned = sorted({v for edge in boundary(triangles) for v in edge})
                boundary_ok = boundary(triangles) == boundary(output)
                pinned_ok = np.array_equal(solver.p[pinned], world[np.array(ids)[pinned]])
                topology_ok = (before["complete"] and after["complete"] and
                               sorted(c["chi"] for c in before["components"]) ==
                               sorted(c["chi"] for c in after["components"]))
                floor = original["floor"]
                if not boundary_ok or not pinned_ok or (before["complete"] and not topology_ok):
                    raise ValueError("boundary or supported topology changed")
                if floor is not None and actual < floor:
                    raise ValueError("conditional floor violated")
                groups.append(dict(source_faces=original["source_faces"], source_vertices=ids,
                                   baseline_actual=original["actual"], actual=actual, floor=floor,
                                   seconds=time.perf_counter() - start, heap_empty=not solver.heap,
                                   topology_checked=topology_ok, boundary_preserved=boundary_ok,
                                   pinned_positions_preserved=pinned_ok,
                                   output_positions=solver.p.tolist(), output_triangles=output.tolist(),
                                   output_audit=after, actions=solver.actions))
            actual = sum(g["actual"] for g in groups)
            result = dict(capacity=row["capacity"], baseline_actual=row["actual"], actual=actual,
                          floor=row["floor"], input_triangles=row["input_triangles"],
                          fraction=actual / row["input_triangles"],
                          seconds=sum(g["seconds"] for g in groups),
                          topology_unverified_groups=sum(not g["topology_checked"] for g in groups),
                          groups=groups)
            output_asset["partitions"].append(result)
            print(path.stem, row["capacity"], "old", row["actual"], "fixed-target", actual,
                  "fraction", round(result["fraction"], 6), "seconds", round(result["seconds"], 2), flush=True)
        report["assets"].append(output_asset)
        args.out.with_suffix(".partial.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream)
        stream.write("\n")


if __name__ == "__main__":
    main()
