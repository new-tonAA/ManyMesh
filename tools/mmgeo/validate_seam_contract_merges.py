"""Validate saved masks, exact seam geometry, complete pair population and policy assembly."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

from audit_obj_contract_floor import read_capture
from probe_adjacent_partition_merges import adjacency, assembled_audit
from probe_partition_qem_exhaustion import boundary
from seam_contract_qem_control import edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = json.loads(args.report.read_text())
    for name, digest in report["source_hashes"].items():
        if hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("experiment source changed")
    for prefix in ("previous", "baseline"):
        if hashlib.sha256(Path(report[prefix + "_path"]).read_bytes()).hexdigest() != report[prefix + "_sha256"]:
            raise ValueError("previous evidence changed")
    baseline = json.loads(Path(report["baseline_path"]).read_text())
    if len(report["assets"]) != len(baseline["assets"]):
        raise ValueError("partial asset population")
    summary = dict(report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                   validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), units_checked=0, assets=[])
    for asset in report["assets"]:
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
        owners = defaultdict(set)
        groups = asset["groups"]
        for i, group in enumerate(groups):
            for v in group["source_vertices"]:
                owners[v].add(i)
        contacts = adjacency(source, groups)
        pairs = {tuple(p["pair"]): p for p in asset["pairs"]}
        if len(pairs) != len(asset["pairs"]) or set(pairs) != set(contacts):
            raise ValueError("pair population mismatch")
        for members, unit in [([i], g) for i, g in enumerate(groups)] + [(list(k), p) for k, p in pairs.items()]:
            faces = sorted(i for m in members for i in groups[m]["source_faces"])
            ids = sorted({v for i in faces for v in source[i][1]})
            remap = {v: i for i, v in enumerate(ids)}
            mask = [remap[v] for v in ids if owners[v] - set(members)]
            if faces != unit["source_faces"] or ids != unit["source_vertices"] or mask != unit["seam_locked"]:
                raise ValueError("source unit or outside-owner mask mismatch")
            triangles = [[remap[v] for v in source[i][1]] for i in faces]
            output = unit["output_triangles"]
            points = np.array(unit["output_positions"])
            locked_points = {tuple(world[ids[v]]) for v in mask}
            source_edges = {tuple(sorted((tuple(world[ids[a]]), tuple(world[ids[b]])))) for a, b in edges(triangles)}
            new_locked = {tuple(sorted((tuple(points[a]), tuple(points[b])))) for a, b in edges(output)
                          if tuple(points[a]) in locked_points and tuple(points[b]) in locked_points}
            if not new_locked <= source_edges or not locked_points <= {tuple(points[v]) for t in output for v in t}:
                raise ValueError("new seam chord or missing seam position")
            fixed = sorted(set(mask) | {v for e in boundary(triangles) for v in e})
            if boundary(triangles) != boundary(output) or not np.array_equal(points[fixed], world[np.array(ids)[fixed]]):
                raise ValueError("fixed geometry changed")
            if len(output) != unit["actual"] or unit["work"] != len(faces) or not unit["heap_empty"]:
                raise ValueError("unit count or exhaustion mismatch")
            summary["units_checked"] += 1
        if sum(g["actual"] for g in groups) != asset["baseline_faces"]:
            raise ValueError("baseline count mismatch")
        for p in pairs.values():
            a, b = p["pair"]
            if p["gain"] != groups[a]["actual"] + groups[b]["actual"] - p["actual"]:
                raise ValueError("gain mismatch")
        for p in asset["policies"]:
            queried = [tuple(q) for q in p["queried"]]
            selected = [tuple(q) for q in p["selected"]]
            used = [v for q in selected for v in q]
            if len(used) != len(set(used)) or not set(selected) <= set(queried):
                raise ValueError("invalid disjoint selection")
            if sum(pairs[q]["work"] for q in queried) != p["work"] or p["work"] > int(asset["input_triangles"] * p["budget_fraction"]):
                raise ValueError("query work mismatch")
            if any(not pairs[q]["eligible"] or pairs[q]["gain"] <= 0 for q in selected):
                raise ValueError("ineligible selected pair")
            if p["actual"] != asset["baseline_faces"] - sum(pairs[q]["gain"] for q in selected):
                raise ValueError("policy face count mismatch")
            if assembled_audit(groups, asset["pairs"], p["selected"]) != p["audit"]:
                raise ValueError("assembly mismatch")
        result = dict(asset=path.stem, baseline_faces=asset["baseline_faces"], pairs=len(pairs),
                      negative_gain=sum(p["gain"] < 0 for p in pairs.values()),
                      baseline_seconds=asset["baseline_seconds"], pair_seconds=asset["pair_seconds"],
                      policies=[{k: p[k] for k in ("policy", "budget_fraction", "actual", "work", "assembled_topology_checked")} for p in asset["policies"]])
        summary["assets"].append(result)
        print(result, flush=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print("units checked", summary["units_checked"], flush=True)


if __name__ == "__main__":
    main()
