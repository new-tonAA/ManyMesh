"""Validate final outputs and measure the stronger bound of the locked-endpoint reference."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from audit_obj_contract_floor import read_capture


def endpoint_bound(triangles):
    counts = Counter(tuple(sorted((t[i], t[(i + 1) % 3]))) for t in triangles for i in range(3))
    locked = {v for edge, count in counts.items() if count != 2 for v in edge}
    interior = {v for t in triangles for v in t} - locked
    adjacent = defaultdict(set)
    for a, b in counts:
        if a in interior and b in interior:
            adjacent[a].add(b)
            adjacent[b].add(a)
    remaining = set(interior)
    components = 0
    while remaining:
        components += 1
        pending = [remaining.pop()]
        while pending:
            v = pending.pop()
            new = adjacent[v] & remaining
            remaining.difference_update(new)
            pending.extend(new)
    # Every contraction joins two initially interior vertices; the remaining
    # interior graph cannot lose its last vertex in any initial component.
    # Each legal closed-edge contraction removes two triangles.
    return len(triangles) - 2 * (len(interior) - components)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    for name, digest in report["source_hashes"].items():
        if hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("experiment source changed")
    result = dict(report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                  summary_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), rows=[])
    for asset in report["assets"]:
        path = Path(asset["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("capture changed")
        faces, _, _ = read_capture(path)
        for row in asset["partitions"]:
            covered, stronger, supported = [], 0, 0
            for group in row["groups"]:
                covered.extend(group["source_faces"])
                if len(group["output_triangles"]) != group["actual"] or not group["heap_empty"]:
                    raise ValueError("incomplete exhaustion")
                remap = {v: i for i, v in enumerate(group["source_vertices"])}
                triangles = [tuple(remap[v] for v in faces[i][1]) for i in group["source_faces"]]
                bound = endpoint_bound(triangles)
                if group["topology_checked"]:
                    if group["actual"] < bound:
                        raise ValueError("locked-endpoint component bound violated")
                    stronger += bound
                    supported += 1
            if sorted(covered) != list(range(len(faces))):
                raise ValueError("partition coverage mismatch")
            item = dict(asset=path.stem, capacity=row["capacity"], actual=row["actual"],
                        fraction=row["fraction"], floor=row["floor"], seconds=row["seconds"],
                        supported_groups=supported, groups=len(row["groups"]),
                        endpoint_floor=stronger if supported == len(row["groups"]) else None,
                        topology_unverified_groups=row["topology_unverified_groups"])
            if sum(g["actual"] for g in row["groups"]) != row["actual"]:
                raise ValueError("aggregate count mismatch")
            result["rows"].append(item)
            print(item, flush=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
