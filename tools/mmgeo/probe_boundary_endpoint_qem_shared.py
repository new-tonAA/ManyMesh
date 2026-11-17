#!/usr/bin/env python3
"""Bound fixed-boundary endpoint QEM with a frozen shared-vertex chord proxy.

This diagnostic is geometry-only and not production-faithful. It inherits the exact boundary-edge
and pinned-position checks from probe_boundary_endpoint_qem.py, and adds the source Corner locked-
target chord precheck using vertices shared by the frozen BFS groups as a proxy for the production
locked mask.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from probe_boundary_endpoint_qem import FixedBoundaryEndpointQEM, boundary_edges


class SharedChordEndpointQEM(FixedBoundaryEndpointQEM):
    def __init__(self, positions, triangles, shared_vertices):
        self.shared_vertices = set(shared_vertices)
        super().__init__(positions, triangles)

    def push(self, u, v):
        if self._building:
            return
        u, v = int(u), int(v)
        u_boundary = u in self.boundary_vertices
        v_boundary = v in self.boundary_vertices
        if u_boundary and v_boundary:
            return
        if u_boundary or v_boundary:
            keep, remove = (u, v) if u_boundary else (v, u)
            if remove in self.shared_vertices:
                return
            return super().push(keep, remove)
        if u in self.shared_vertices or v in self.shared_vertices:
            return
        return super().push(u, v)

    def legal(self, u, v, target):
        u, v = int(u), int(v)
        if v in self.shared_vertices:
            return False
        if u in self.shared_vertices:
            # Match CornerSimplifier's locked-target chord guard on the current one-ring.
            for fi in self.inc[v]:
                face = self.f[fi]
                if u not in face and any(int(w) in self.shared_vertices for w in face
                                         if int(w) not in (u, v)):
                    return False
        return super().legal(u, v, target)


def run_group(world, source_faces, group, shared_sources):
    ids = sorted({v for face in group["source_faces"] for v in source_faces[face][1]})
    if ids != group["source_vertices"]:
        raise ValueError("frozen source-vertex list does not match source faces")
    remap = {v: i for i, v in enumerate(ids)}
    triangles = np.array([[remap[v] for v in source_faces[face][1]]
                          for face in group["source_faces"]], dtype=int)
    before = audit_partition([("group", tuple(map(int, tri))) for tri in triangles], False)
    if not before["complete"]:
        return dict(status="unsupported-input", input_triangles=len(triangles),
                    baseline_triangles=group["actual"])
    local_shared = {remap[v] for v in ids if v in shared_sources}
    start = time.perf_counter()
    solver = SharedChordEndpointQEM(world[ids], triangles, local_shared)
    actual = solver.advance(0)
    elapsed = time.perf_counter() - start
    output = solver.f[solver.alive].copy()
    after = audit_partition([("group", tuple(map(int, tri))) for tri in output], False)
    edges_before = boundary_edges(triangles)
    edges_after = boundary_edges(output)
    pinned = sorted({v for edge in edges_before for v in edge})
    positions_ok = np.array_equal(solver.p[pinned], world[np.asarray(ids)[pinned]])
    topology_ok = (after["complete"] and
                   sorted(c["chi"] for c in before["components"]) ==
                   sorted(c["chi"] for c in after["components"]))
    if not (edges_before == edges_after and positions_ok and topology_ok and actual >= group["floor"]):
        raise ValueError("shared-chord control violated a frozen invariant")
    return dict(status="checked", baseline_triangles=group["actual"], actual=actual,
                floor=group["floor"], extra_removed=group["actual"] - actual,
                applied=len(solver.actions), rejected=solver.rejected,
                boundary_preserved=True, pinned_positions_preserved=True,
                topology_preserved=True, seconds=elapsed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("partition_report", type=Path)
    parser.add_argument("--capacity", type=int, default=32)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    root = Path(__file__).resolve().parents[2]
    frozen = json.loads(args.partition_report.read_text(encoding="utf-8"))
    captures = []
    start = time.perf_counter()
    for asset in frozen["assets"]:
        capture_path = root / asset["path"]
        if hashlib.sha256(capture_path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("frozen capture hash mismatch")
        source_faces, _, vertex_count = read_capture(capture_path)
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        lookup = {}
        for unit in capture["units"]:
            for point in unit["positions"]:
                xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
                lookup.setdefault(xyz, len(lookup))
        if len(lookup) != vertex_count:
            raise ValueError("capture welded-vertex count mismatch")
        world = np.asarray(list(lookup), dtype=float)
        center = (world.min(0) + world.max(0)) * .5
        radius = max(float(np.linalg.norm(world - center, axis=1).max()), 1e-12)
        world = (world - center) / radius
        partition = next((item for item in asset["partitions"]
                          if item["capacity"] == args.capacity), None)
        if partition is None:
            raise ValueError(f"missing capacity {args.capacity} for {asset['path']}")
        uses = Counter(v for group in partition["groups"] for v in set(group["source_vertices"]))
        shared = {v for v, count in uses.items() if count > 1}
        groups = [run_group(world, source_faces, group, shared) for group in partition["groups"]]
        checked = [group for group in groups if group["status"] == "checked"]
        baseline = sum(group["baseline_triangles"] for group in checked)
        actual = sum(group["actual"] for group in checked)
        row = dict(path=asset["path"], capture_sha256=asset["sha256"], capacity=args.capacity,
                   shared_source_vertices=len(shared), groups=len(groups), checked_groups=len(checked),
                   unsupported_groups=len(groups) - len(checked),
                   baseline_checked_triangles=baseline, actual_triangles=actual,
                   extra_removed=baseline - actual,
                   fraction_of_checked_baseline=actual / baseline if baseline else None,
                   solver_seconds=sum(group.get("seconds", 0.) for group in checked),
                   group_results=groups)
        captures.append(row)
        print(Path(asset["path"]).stem, len(checked), "/", len(groups),
              "triangles", baseline, "->", actual, "extra", baseline - actual, flush=True)
    result = dict(schema=1,
                  scope="geometry-only fixed-boundary QEM with shared-vertex chord proxy; not production",
                  partition_report_sha256=hashlib.sha256(args.partition_report.read_bytes()).hexdigest(),
                  code_hashes={name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                               for name in (Path(__file__).name, "probe_boundary_endpoint_qem.py",
                                            "progressive_geometry_baseline.py",
                                            "audit_obj_contract_floor.py")},
                  capacity=args.capacity, assets=captures,
                  total_solver_seconds=sum(a["solver_seconds"] for a in captures),
                  wall_seconds=time.perf_counter() - start,
                  limitations=["cross-group source-vertex reuse is only a proxy for production locked vertices",
                               "geometry-only; no UV/normal, source-distance, or self-intersection gate",
                               "does not reproduce Corner's local fan precheck or complete quality gate",
                               "Python timings are not production build-cost comparisons"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, separators=(",", ":"))
        stream.write("\n")
    print("wrote", args.out, "wall", round(result["wall_seconds"], 3), flush=True)


if __name__ == "__main__":
    main()
