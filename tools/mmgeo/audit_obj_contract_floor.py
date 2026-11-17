"""Conditional combinatorial floors; source OBJ audit, not an Assimp/LOD reproduction."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct


def read_obj(path):
    positions, canonical, lookup, faces = [], [], {}, []
    material = "__default__"
    polygon_sizes = Counter()
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if fields[0] == "v":
            if len(fields) not in (4, 5) or (len(fields) == 5 and float(fields[4]) != 1):
                raise ValueError(f"{path}:{line_number}: unsupported vertex record")
            xyz = tuple(struct.unpack("f", struct.pack("f", float(x)))[0] for x in fields[1:4])
            if not all(math.isfinite(x) for x in xyz):
                raise ValueError("nonfinite position")
            canonical.append(lookup.setdefault(xyz, len(lookup)))
            positions.append(xyz)
        elif fields[0] == "usemtl":
            material = " ".join(fields[1:])
        elif fields[0] == "f":
            ids = []
            for token in fields[1:]:
                index = int(token.split("/", 1)[0])
                offset = index - 1 if index > 0 else len(positions) + index
                if index == 0 or not 0 <= offset < len(positions):
                    raise ValueError(f"{path}:{line_number}: invalid position index")
                ids.append(canonical[offset])
            if len(ids) < 3:
                raise ValueError("face has fewer than three corners")
            polygon_sizes[len(ids)] += 1
            # A fan is an abstract triangulation only; it need not match Assimp geometry.
            for i in range(1, len(ids) - 1):
                faces.append((material, (ids[0], ids[i], ids[i + 1])))
    if not faces:
        raise ValueError("empty mesh")
    return faces, dict(polygon_sizes), len(lookup)


def read_capture(path):
    """Read archived Corner initial geometry; its source/binary provenance is not implied."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not data.get("units"):
        raise ValueError("unsupported capture schema")
    lookup, faces = {}, []
    for unit in data["units"]:
        ids = []
        for point in unit["positions"]:
            if len(point) != 3 or not all(math.isfinite(x) for x in point):
                raise ValueError("invalid capture position")
            xyz = tuple(struct.unpack("f", struct.pack("f", x))[0] for x in point)
            ids.append(lookup.setdefault(xyz, len(lookup)))
        for triangle in unit["triangles"]:
            if len(triangle) != 3 or any(type(i) is not int or not 0 <= i < len(ids) for i in triangle):
                raise ValueError("invalid capture triangle")
            faces.append((str(unit["material"]), tuple(ids[i] for i in triangle)))
    if not faces:
        raise ValueError("empty capture")
    return faces, {3: len(faces)}, len(lookup)


def component_floor(triangles):
    vertices, edges, links = set(), defaultdict(list), defaultdict(list)
    edge_faces = defaultdict(list)
    seen, duplicate, degenerate = set(), 0, 0
    for face_id, triangle in enumerate(triangles):
        if len(set(triangle)) != 3:
            degenerate += 1
        key = tuple(sorted(triangle))
        duplicate += key in seen
        seen.add(key)
        vertices.update(triangle)
        for i in range(3):
            a, b = triangle[i], triangle[(i + 1) % 3]
            edges[min(a, b), max(a, b)].append(1 if a < b else -1)
            edge_faces[min(a, b), max(a, b)].append((face_id, a < b))
            links[a].append((b, triangle[(i + 2) % 3]))
    boundary = [edge for edge, uses in edges.items() if len(uses) == 1]
    boundary_vertices = set(v for edge in boundary for v in edge)
    bad_links = 0
    for vertex, pairs in links.items():
        adjacency = defaultdict(list)
        for a, b in pairs:
            adjacency[a].append(b)
            adjacency[b].append(a)
        reached, pending = set(), [next(iter(adjacency))]
        while pending:
            node = pending.pop()
            if node not in reached:
                reached.add(node)
                pending.extend(adjacency[node])
        degrees = Counter(len(neighbors) for neighbors in adjacency.values())
        expected_ends = 2 if vertex in boundary_vertices else 0
        if (len(reached) != len(adjacency) or degrees.get(1, 0) != expected_ends
                or any(degree not in (1, 2) for degree in degrees)):
            bad_links += 1
    nonmanifold = sum(len(uses) > 2 for uses in edges.values())
    orientation_conflicts = sum(len(uses) == 2 and uses[0] == uses[1] for uses in edges.values())
    chi = len(vertices) - len(edges) + len(triangles)
    supported = not (duplicate or degenerate or bad_links or nonmanifold)
    # Euler/incidence bounds do not depend on winding or orientability. Track those
    # separately: same-direction edge uses may be repairable by face flips.
    dual = defaultdict(list)
    for uses in edge_faces.values():
        if len(uses) == 2:
            (first, forward), (second, other_forward) = uses
            parity = int(forward == other_forward)
            dual[first].append((second, parity))
            dual[second].append((first, parity))
    flips, consistent, flip_count = {}, True, 0
    for seed in range(len(triangles)):
        if seed in flips:
            continue
        flips[seed] = 0
        pending, region = [seed], []
        while pending:
            face = pending.pop()
            region.append(face)
            for neighbor, parity in dual[face]:
                expected = flips[face] ^ parity
                if neighbor in flips:
                    consistent = consistent and flips[neighbor] == expected
                else:
                    flips[neighbor] = expected
                    pending.append(neighbor)
        ones = sum(flips[face] for face in region)
        flip_count += min(ones, len(region) - ones)
    # 3F=2E-B and chi=V-E+F => F=2V-B-2chi.
    # Fixed boundary edges imply V>=B on a manifold boundary; closed simplicial
    # 2-manifolds need at least four vertices. This is a necessary, loose bound.
    floor = max(1, len(boundary) - 2 * chi) if boundary else max(4, 8 - 2 * chi)
    if supported and (len(boundary_vertices) != len(boundary) or floor > len(triangles)):
        raise ValueError("inconsistent manifold floor")
    return dict(triangles=len(triangles), vertices=len(vertices), edges=len(edges), chi=chi,
                boundary_edges=len(boundary), supported=supported,
                duplicate_faces=duplicate, degenerate_faces=degenerate, bad_vertex_links=bad_links,
                nonmanifold_edges=nonmanifold, orientation_conflicts=orientation_conflicts,
                orientable=consistent if supported else None,
                winding_flip_count=flip_count if supported and consistent else None,
                conditional_floor=floor if supported else None)


def audit_partition(faces, by_material):
    parent = list(range(len(faces)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owners = {}
    for i, (material, triangle) in enumerate(faces):
        for vertex in triangle:
            key = (material if by_material else None, vertex)
            if key in owners:
                parent[root(i)] = root(owners[key])
            else:
                owners[key] = i
    groups = defaultdict(list)
    for i, (material, triangle) in enumerate(faces):
        groups[root(i)].append(triangle)
    components = [component_floor(group) for group in groups.values()]
    supported_floor = sum(c["conditional_floor"] or 0 for c in components)
    complete = all(c["supported"] for c in components)
    return dict(component_count=len(components), unsupported_components=sum(not c["supported"] for c in components),
                supported_components_floor=supported_floor, complete=complete,
                conditional_floor=supported_floor if complete else None, components=components)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--format", choices=("obj", "capture"), default="obj")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = dict(schema=2, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  assumptions=["float32 exact-position welding",
                               "abstract polygon fan triangulation" if args.format == "obj" else
                               "archived Corner initial triangles; no fresh import or executable provenance",
                               "each supported component and its Euler characteristic survive",
                               "all partition boundary edges survive unchanged",
                               "material partition is conditional; Assimp submeshes not reproduced",
                               "no geometric, attribute, Hausdorff or self-intersection guarantee"], assets=[])
    report["input_format"] = args.format
    for path in args.inputs:
        faces, sizes, vertices = (read_obj if args.format == "obj" else read_capture)(path)
        asset = dict(path=path.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     position_count=vertices, fan_triangles=len(faces), polygon_sizes=sizes,
                     material_count=len(set(m for m, _ in faces)),
                     global_partition=audit_partition(faces, False),
                     material_partition=audit_partition(faces, True))
        report["assets"].append(asset)
        for mode in ("global_partition", "material_partition"):
            summary = asset[mode]
            print(path, mode, "components", summary["component_count"], "unsupported",
                  summary["unsupported_components"], "floor", summary["conditional_floor"],
                  "triangles", len(faces))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite {args.out}")
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
