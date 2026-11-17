#!/usr/bin/env python3
"""Measure the classical fixed-boundary-endpoint QEM control on frozen groups.

This is a control for partition QEM exhaustion, not a new simplification method.
It allows an interior vertex to collapse into an existing boundary vertex, but
keeps every original boundary vertex fixed and rejects any step that changes the
boundary edge set. All other QEM and local validity rules match the archived
geometry-only reference.
"""
import argparse
from collections import Counter
import hashlib
import heapq
import json
from pathlib import Path
import struct
import time

import numpy as np

from audit_obj_contract_floor import audit_partition, read_capture
from progressive_geometry_baseline import ProgressiveQEM


def boundary_edges(triangles):
    counts = Counter(tuple(sorted((int(tri[i]), int(tri[(i + 1) % 3]))))
                     for tri in triangles for i in range(3))
    return {edge for edge, uses in counts.items() if uses == 1}


class FixedBoundaryEndpointQEM(ProgressiveQEM):
    """QEM that can remove interior vertices into fixed boundary vertices."""

    def __init__(self, positions, triangles):
        triangles = np.asarray(triangles, dtype=int).reshape(-1, 3)
        counts = Counter(tuple(sorted((int(tri[i]), int(tri[(i + 1) % 3]))))
                         for tri in triangles for i in range(3))
        self.boundary_vertices = {v for edge, uses in counts.items() if uses == 1 for v in edge}
        self._building = True
        super().__init__(positions, triangles)
        self.other_locked = self.locked - self.boundary_vertices
        self._building = False
        self.heap = []
        edges = {tuple(sorted((int(tri[i]), int(tri[(i + 1) % 3]))))
                 for tri in triangles for i in range(3)}
        for u, v in sorted(edges):
            self.push(u, v)

    def push(self, u, v):
        if self._building:
            return
        u, v = int(u), int(v)
        if not self.inc[u] or not self.inc[v]:
            return
        u_boundary = u in self.boundary_vertices
        v_boundary = v in self.boundary_vertices
        if u_boundary and v_boundary:
            return
        if u_boundary or v_boundary:
            keep, remove = (u, v) if u_boundary else (v, u)
            if keep in self.other_locked or remove in self.other_locked:
                return
            target = self.p[keep].copy()
            quadric = self.q[keep] + self.q[remove]
            homogeneous = np.r_[target, 1.]
            cost = max(0., float(homogeneous @ quadric @ homogeneous))
            heapq.heappush(self.heap, (cost, keep, remove,
                                       int(self.versions[keep]), int(self.versions[remove]),
                                       0, tuple(target)))
            return
        if u in self.other_locked or v in self.other_locked:
            return
        super().push(u, v)

    def legal(self, u, v, target):
        u, v = int(u), int(v)
        fixed_boundary_target = u in self.boundary_vertices
        if fixed_boundary_target:
            if v in self.boundary_vertices or u in self.other_locked or v in self.other_locked:
                return False
            if not np.array_equal(np.asarray(target), self.p[u]):
                return False
        elif v in self.boundary_vertices or u in self.other_locked or v in self.other_locked:
            return False
        if not super().legal(u, v, target):
            return False
        if fixed_boundary_target:
            before = self.f[self.alive]
            simulated = before.copy()
            simulated[simulated == v] = u
            simulated = simulated[(simulated[:, 0] != simulated[:, 1]) &
                                  (simulated[:, 1] != simulated[:, 2]) &
                                  (simulated[:, 2] != simulated[:, 0])]
            if boundary_edges(before) != boundary_edges(simulated):
                return False
        return True


def run_group(world, source_faces, group):
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

    start = time.perf_counter()
    solver = FixedBoundaryEndpointQEM(world[ids], triangles)
    actual = solver.advance(0)
    elapsed = time.perf_counter() - start
    output = solver.f[solver.alive].copy()
    after = audit_partition([("group", tuple(map(int, tri))) for tri in output], False)
    old_boundary = boundary_edges(triangles)
    new_boundary = boundary_edges(output)
    pinned = sorted({v for edge in old_boundary for v in edge})
    boundary_positions_ok = np.array_equal(solver.p[pinned], world[np.asarray(ids)[pinned]])
    topology_ok = (after["complete"] and
                   sorted(c["chi"] for c in before["components"]) ==
                   sorted(c["chi"] for c in after["components"]))
    floor = group["floor"]
    floor_ok = floor is None or actual >= floor
    if not (old_boundary == new_boundary and boundary_positions_ok and topology_ok and floor_ok):
        raise ValueError("boundary endpoint control violated a frozen invariant")
    return dict(status="checked", input_triangles=len(triangles),
                baseline_triangles=group["actual"], actual=actual,
                extra_removed=group["actual"] - actual, floor=floor,
                applied=len(solver.actions), rejected=solver.rejected,
                heap_empty=not solver.heap, seconds=elapsed,
                boundary_edges=len(old_boundary), boundary_preserved=True,
                boundary_positions_preserved=True, topology_preserved=True,
                actions=solver.actions)


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
        groups = [run_group(world, source_faces, group) for group in partition["groups"]]
        checked = [group for group in groups if group["status"] == "checked"]
        baseline = sum(group["baseline_triangles"] for group in checked)
        actual = sum(group["actual"] for group in checked)
        asset_result = dict(path=asset["path"], capture_sha256=asset["sha256"],
                            capacity=args.capacity, input_triangles=partition["input_triangles"],
                            groups=len(groups), checked_groups=len(checked),
                            unsupported_groups=len(groups) - len(checked),
                            baseline_checked_triangles=baseline,
                            endpoint_checked_triangles=actual,
                            extra_removed=baseline - actual,
                            fraction_of_checked_baseline=(actual / baseline if baseline else None),
                            seconds=sum(group.get("seconds", 0.) for group in checked),
                            group_results=groups)
        captures.append(asset_result)
        print(Path(asset["path"]).stem, "capacity", args.capacity,
              "checked", len(checked), "/", len(groups), "triangles", baseline, "->", actual,
              "extra", baseline - actual, flush=True)
    result = dict(schema=1,
                  scope="fixed-boundary endpoint QEM control; geometry only; not a novelty claim",
                  partition_report_sha256=hashlib.sha256(args.partition_report.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  capacity=args.capacity, assets=captures,
                  total_solver_seconds=sum(a["seconds"] for a in captures),
                  wall_seconds=time.perf_counter() - start,
                  limitations=["archived initial Corner captures, not a fresh native build",
                               "geometry only; no UV/normal/material error, source-distance ceiling, or self-intersection check",
                               "unsupported input patches are reported and excluded from aggregate improvement",
                               "Python timings are not production construction-cost comparisons"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, separators=(",", ":"))
        stream.write("\n")
    print("wrote", args.out, "wall", round(result["wall_seconds"], 3), flush=True)


if __name__ == "__main__":
    main()
