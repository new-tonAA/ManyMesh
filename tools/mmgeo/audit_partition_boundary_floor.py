"""Controlled partition-size sensitivity on archived geometry, not ManyMesh clustering."""
import argparse
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path

from audit_obj_contract_floor import audit_partition, read_capture


def partition(faces, capacity):
    if capacity < 1:
        raise ValueError("positive capacity required")
    uses = defaultdict(list)
    for face, (material, triangle) in enumerate(faces):
        for i in range(3):
            edge = tuple(sorted((triangle[i], triangle[(i + 1) % 3])))
            uses[material, edge].append(face)
    adjacent = [set() for _ in faces]
    for incident in uses.values():
        for face in incident:
            adjacent[face].update(other for other in incident if other != face)
    remaining = set(range(len(faces)))
    groups = []
    for seed in range(len(faces)):
        if seed not in remaining:
            continue
        queue, queued, selected = deque([seed]), {seed}, []
        while queue and len(selected) < capacity:
            face = queue.popleft()
            if face not in remaining:
                continue
            remaining.remove(face)
            selected.append(face)
            for neighbor in sorted(adjacent[face]):
                if neighbor in remaining and neighbor not in queued:
                    queue.append(neighbor)
                    queued.add(neighbor)
        groups.append(selected)
    if sorted(face for group in groups for face in group) != list(range(len(faces))):
        raise ValueError("partition does not cover input exactly once")
    return groups


def evaluate(faces, capacity):
    groups = partition(faces, capacity)
    rows = [audit_partition([faces[i] for i in group], False) for group in groups]
    complete = all(row["complete"] for row in rows)
    floor = sum(row["supported_components_floor"] for row in rows)
    return dict(capacity=capacity, groups=len(groups), input_triangles=len(faces),
                unsupported_components=sum(row["unsupported_components"] for row in rows),
                complete=complete, conditional_floor=floor if complete else None,
                supported_components_floor=floor,
                fraction=floor / len(faces) if complete else None,
                group_face_ids=groups, group_audits=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    root = Path(__file__).parent
    report = dict(schema=1, method="deterministic material-preserving face-adjacency BFS",
                  source_hashes={name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                 for name in (Path(__file__).name, "audit_obj_contract_floor.py")},
                  limitations=["not ManyMesh leaf clusters or HLOD repair",
                               "boundary edges and component Euler characteristics assumed fixed",
                               "unsupported components have no whole-population floor",
                               "archived captures lack current binary provenance",
                               "no simplification, gate, image-quality or timing result"], assets=[])
    for path in args.captures:
        faces, _, _ = read_capture(path)
        asset = dict(path=path.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     material_merged=audit_partition(faces, True), partitions=[])
        for capacity in (32, 64, 128, 256, 512):
            row = evaluate(faces, capacity)
            asset["partitions"].append(row)
            print(path.stem, capacity, row["groups"], row["conditional_floor"], row["fraction"],
                  "unsupported", row["unsupported_components"], flush=True)
        report["assets"].append(asset)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
