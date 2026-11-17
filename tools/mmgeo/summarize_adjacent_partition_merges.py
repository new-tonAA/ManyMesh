"""Check pair geometry/selection accounting and summarize the frozen merge screen."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

from audit_obj_contract_floor import read_capture
from probe_adjacent_partition_merges import adjacency, assembled_audit
from probe_partition_qem_exhaustion import boundary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads(args.report.read_text())
    root = Path(__file__).parent
    for name, digest in data["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("experiment source changed")
    baseline_path = Path(data["baseline_path"])
    if hashlib.sha256(baseline_path.read_bytes()).hexdigest() != data["baseline_sha256"]:
        raise ValueError("baseline changed")
    baseline = json.loads(baseline_path.read_text())
    summary = dict(report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                   summarizer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), assets=[])
    for asset, original in zip(data["assets"], baseline["assets"]):
        if asset["path"] != original["path"]:
            raise ValueError("asset order mismatch")
        path = Path(asset["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("capture changed")
        source, _, _ = read_capture(path)
        groups = next(r for r in original["partitions"] if r["capacity"] == 32)["groups"]
        expected = adjacency(source, groups)
        pairs = {tuple(p["pair"]): p for p in asset["pairs"]}
        if len(pairs) != len(asset["pairs"]) or set(pairs) != set(expected):
            raise ValueError("counterfactual population mismatch")
        lookup = {}
        for unit in json.loads(path.read_text())["units"]:
            for point in unit["positions"]:
                xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
                lookup.setdefault(xyz, len(lookup))
        world = (np.array(list(lookup)) - original["center"]) / original["radius"]
        for (a, b), p in pairs.items():
            ids = sorted(set(groups[a]["source_vertices"]) | set(groups[b]["source_vertices"]))
            remap = {v: i for i, v in enumerate(ids)}
            faces = groups[a]["source_faces"] + groups[b]["source_faces"]
            triangles = [[remap[v] for v in source[i][1]] for i in faces]
            if p["work"] != len(faces) or p["actual"] != len(p["output_triangles"]):
                raise ValueError("pair work/count mismatch")
            if p["gain"] != groups[a]["actual"] + groups[b]["actual"] - p["actual"]:
                raise ValueError("pair gain mismatch")
            edges = boundary(triangles)
            pinned = sorted({v for edge in edges for v in edge})
            if boundary(p["output_triangles"]) != edges or not np.array_equal(np.array(p["output_positions"])[pinned], world[np.array(ids)[pinned]]):
                raise ValueError("pair boundary changed")
        for policy in asset["policies"]:
            queried = [tuple(p) for p in policy["queried"]]
            selected = [tuple(p) for p in policy["selected"]]
            if len(set(queried)) != len(queried) or not set(selected) <= set(queried):
                raise ValueError("query/selection population mismatch")
            if policy["work"] != sum(pairs[p]["work"] for p in queried) or policy["work"] > int(len(source) * policy["budget_fraction"]):
                raise ValueError("work budget mismatch")
            used = [g for p in selected for g in p]
            if len(used) != len(set(used)) or any(not pairs[p]["eligible"] or pairs[p]["gain"] <= 0 for p in selected):
                raise ValueError("incompatible or invalid selection")
            if policy["actual"] != asset["baseline_faces"] - sum(pairs[p]["gain"] for p in selected):
                raise ValueError("policy count mismatch")
            if assembled_audit(groups, asset["pairs"], policy["selected"]) != policy["audit"]:
                raise ValueError("assembly audit mismatch")
        item = dict(asset=path.stem, pairs=len(pairs), baseline_faces=asset["baseline_faces"],
                    source_faces=len(source), total_work=asset["total_work"], seconds=asset["total_seconds"],
                    ineligible=sum(not p["eligible"] for p in pairs.values()),
                    negative_gain=sum(p["gain"] < 0 for p in pairs.values()),
                    policy_rows=[{k: p[k] for k in ("policy", "budget_fraction", "actual", "work", "assembled_topology_checked")} for p in asset["policies"]])
        summary["assets"].append(item)
        print(item, flush=True)
    if len(data["assets"]) != len(baseline["assets"]):
        raise ValueError("partial population")
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
