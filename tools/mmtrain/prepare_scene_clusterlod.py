"""Export fixed scene geometry with the stock meshoptimizer cluster LOD demo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np

from bench_component_gpu import load_export


UPSTREAM = "9d9890c73011d75920af614485296d1e03e95448"
SCALE = 1 << 20


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oriented_faces(faces):
    start = np.argmin(faces, axis=1)[:, None]
    faces = np.take_along_axis(faces, (start + np.arange(3)) % 3, axis=1)
    return faces[np.lexsort(faces.T[::-1])]


def topology_counts(vertices, faces):
    _, weld = np.unique(vertices[:, :3], axis=0, return_inverse=True)
    welded = weld[faces]
    sorted_faces = np.sort(welded, axis=1)
    unique_faces = np.unique(sorted_faces, axis=0)
    edges = np.stack((welded, np.roll(welded, -1, axis=1)), axis=-1).reshape(-1, 2)
    undirected, incidence = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    return {"repeated_vertex_faces": int(np.any(np.diff(sorted_faces, axis=1) == 0, axis=1).sum()),
            "duplicate_faces": len(faces) - len(unique_faces),
            "nonmanifold_edges": int((incidence > 2).sum()),
            "boundary_edges": int(len(undirected[incidence == 1]))}


def dump(demo, obj, depth, out):
    env = dict(os.environ, DUMP=str(depth))
    env.pop("CLRT", None)
    start = time.perf_counter()
    cmd = subprocess.run([str(demo), "-n", str(obj)], env=env, capture_output=True,
                         text=True, check=True, timeout=120)
    ms = 1000 * (time.perf_counter() - start)
    (out / f"cluster-depth{depth}.log").write_text(cmd.stdout, encoding="utf-8")
    sections = {"v": [], "vn": [], "f": []}
    for line in cmd.stderr.splitlines():
        prefix, _, payload = line.partition(" ")
        if prefix in sections:
            sections[prefix].append(payload)
    positions = np.fromstring(" ".join(sections["v"]), count=-1, sep=" ", dtype=np.float32).reshape(-1, 3)
    normals = np.fromstring(" ".join(sections["vn"]), count=-1, sep=" ", dtype=np.float32).reshape(-1, 3)
    faces = np.array([[int(v.split("/")[0]) - 1 for v in face.split()] for face in sections["f"]],
                     dtype=np.int64).reshape(-1, 3)
    count = re.search(rf"^cut \(level {depth}\): (\d+) triangles", cmd.stdout, re.MULTILINE)
    if not count or not len(faces) or len(faces) != int(count.group(1)):
        raise ValueError(f"Invalid stock cluster cut for {obj.stem} at depth {depth}")
    return positions, normals, faces, ms


def export_asset(demo, out, mesh, manifest):
    interleaved, inds = load_export(mesh, manifest)
    interleaved = interleaved.reshape(-1, 6)
    faces = inds.reshape(-1, 3)
    out.mkdir(parents=True, exist_ok=True)
    obj = out / "input.obj"
    with obj.open("w", encoding="ascii", newline="\n") as stream:
        np.savetxt(stream, interleaved[:, :3] * SCALE, fmt="v %.9g %.9g %.9g")
        np.savetxt(stream, interleaved[:, 3:], fmt="vn %.9g %.9g %.9g")
        obj_indices = np.repeat(faces + 1, 2, axis=1)
        np.savetxt(stream, obj_indices, fmt="f %d//%d %d//%d %d//%d")
    expanded = np.ascontiguousarray(interleaved[inds])
    _, first, inverse = np.unique(expanded.view("V24").ravel(), return_index=True, return_inverse=True)
    order = np.argsort(first)
    vertices = expanded[first[order]]
    reference = np.argsort(order)[inverse].reshape(-1, 3)
    report = {"source_sha256": manifest["sha256"], "source_faces": len(faces),
              "source_topology": topology_counts(vertices, reference), "cuts": {}}
    for depth in (0, 1, 2):
        p, n, cut, elapsed = dump(demo, obj, depth, out)
        if (p.shape != vertices[:, :3].shape or n.shape != p.shape
                or not np.allclose(p, vertices[:, :3] * SCALE, rtol=1e-6, atol=1e-6)
                or not np.allclose(n, vertices[:, 3:], rtol=1e-6, atol=6e-7)
                or cut.min() < 0 or cut.max() >= len(vertices)):
            raise ValueError(f"Stock cut vertex correspondence failed for {out.name}, depth {depth}")
        if depth == 0:
            if not np.array_equal(oriented_faces(reference), oriented_faces(cut)):
                raise ValueError(f"Stock depth 0 differs from the source faces of {out.name}")
            continue
        index = cut.astype(np.uint32).ravel()
        npy = out / f"cluster-depth{depth}.npy"
        # Return input vertex IDs so storage and GPU shading use the same source floats.
        ids = inds[first[order]]
        np.save(npy, ids[index], allow_pickle=False)
        report["cuts"][f"cluster{depth}"] = {"count": len(cut), "sha256": sha(npy),
                                              "demo_wall_ms": elapsed,
                                              "topology": topology_counts(vertices, cut)}
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--meshes", required=True, type=Path)
    p.add_argument("--upstream", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--asset")
    args = p.parse_args()
    repo = args.upstream.resolve()
    if subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip() != UPSTREAM:
        p.error(f"Expected meshoptimizer {UPSTREAM}")
    if subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--"], text=True):
        p.error("Expected the stock upstream source")
    demo = repo / "meshoptdemo.exe"
    if not demo.is_file():
        p.error("Build the stock meshoptdemo.exe first")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [k for k in manifest["assets"] if args.asset is None or k == args.asset]
    if not assets:
        p.error("No matching assets")
    result = {"manifest_sha256": sha(args.manifest), "upstream_commit": UPSTREAM,
              "demo_sha256": sha(demo), "script_sha256": sha(Path(__file__)), "assets": {}}
    for asset in assets:
        row = manifest["assets"][asset]["exports"]["source"]
        result["assets"][asset] = export_asset(demo, args.out / asset, args.meshes / asset / "source.ply", row)
        print(asset, {k: v["count"] for k, v in result["assets"][asset]["cuts"].items()}, flush=True)
    (args.out / "cluster-cuts.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
