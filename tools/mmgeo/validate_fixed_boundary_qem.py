"""Replay every committed collapse independently of the QEM queue/evaluator."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

from audit_obj_contract_floor import read_capture


def edge_boundary(triangles):
    triangles = np.asarray(triangles, dtype=int).reshape(-1, 3)
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]))
    edges.sort(axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return {tuple(map(int, edge)) for edge in unique[counts == 1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.report.read_text())
    for name, digest in data["source_hashes"].items():
        if hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("experiment source changed")
    baseline = Path(data["baseline_path"])
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != data["baseline_sha256"]:
        raise ValueError("baseline changed")
    summary = dict(report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                   validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   replayed_actions=0, rows=[])
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
        for row in asset["partitions"]:
            covered = []
            for group in row["groups"]:
                covered.extend(group["source_faces"])
                remap = {v: i for i, v in enumerate(group["source_vertices"])}
                faces = np.array([[remap[v] for v in source[i][1]] for i in group["source_faces"]])
                positions = world[group["source_vertices"]].copy()
                initial_boundary = edge_boundary(faces)
                pinned = sorted({v for edge in initial_boundary for v in edge})
                pinned_positions = positions[pinned].copy()
                for action in group["actions"]:
                    keep, remove = action["keep"], action["remove"]
                    if not np.array_equal(positions[keep], action["oldKeep"]) or not np.array_equal(positions[remove], action["oldRemove"]):
                        raise ValueError("replay prestate mismatch")
                    if remove in pinned or (keep in pinned and not np.array_equal(positions[keep], action["target"])):
                        raise ValueError("pinned endpoint changed")
                    faces[faces == remove] = keep
                    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 0] != faces[:, 2]) &
                                  (faces[:, 1] != faces[:, 2])]
                    positions[keep] = action["target"]
                    if len(faces) != action["faces"] or edge_boundary(faces) != initial_boundary:
                        raise ValueError("intermediate boundary or face count changed")
                    if not np.array_equal(positions[pinned], pinned_positions):
                        raise ValueError("intermediate boundary position changed")
                    summary["replayed_actions"] += 1
                if len(faces) != group["actual"] or not np.array_equal(faces, group["output_triangles"]) or not np.array_equal(positions, group["output_positions"]):
                    raise ValueError("final geometry replay mismatch")
                if not group["heap_empty"]:
                    raise ValueError("unfinished exhaustion")
            if sorted(covered) != list(range(row["input_triangles"])):
                raise ValueError("partition coverage mismatch")
            if sum(g["actual"] for g in row["groups"]) != row["actual"]:
                raise ValueError("aggregate face mismatch")
            item = {k: row[k] for k in ("capacity", "baseline_actual", "actual", "floor", "seconds", "topology_unverified_groups")}
            item["asset"] = path.stem
            item["worse_groups"] = sum(g["actual"] > g["baseline_actual"] for g in row["groups"])
            summary["rows"].append(item)
            print(item, flush=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print("replayed actions", summary["replayed_actions"], flush=True)


if __name__ == "__main__":
    main()
