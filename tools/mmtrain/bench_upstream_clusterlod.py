"""Score cuts exported by the unmodified meshoptimizer clusterlod demo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np

from cluster_decoder import Mesh, topology
from cluster_decoder_pilot import read_stl
from cluster_decoder_surface_quality import surface_metrics
from compare_qem_meshopt_validation_70pct import qem_simplify, render_metrics


UPSTREAM_COMMIT = "9d9890c73011d75920af614485296d1e03e95448"
OBJ_SCALE = 1 << 20


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_obj(path, positions, triangles):
    with path.open("w", encoding="ascii", newline="\n") as output:
        np.savetxt(output, positions, fmt="v %.9g %.9g %.9g")
        np.savetxt(output, triangles + 1, fmt="f %d %d %d")


def run_demo(demo, source, level, directory):
    env = dict(os.environ, DUMP=str(level))
    env.pop("CLRT", None)
    start = time.perf_counter()
    completed = subprocess.run([str(demo), "-n", str(source)], env=env,
                               capture_output=True, text=True, check=True, timeout=120)
    elapsed_ms = (time.perf_counter() - start) * 1000
    (directory / f"cut-{level}.log").write_text(completed.stdout, encoding="utf-8")
    (directory / f"cut-{level}.obj").write_text(completed.stderr, encoding="utf-8")
    count = re.search(r"^cut \([^\n]*\): (\d+) triangles", completed.stdout, re.MULTILINE)
    if not count:
        raise ValueError(f"Upstream demo did not report a cut for {source}")
    positions = []
    faces = []
    clusters = []
    for line in completed.stderr.splitlines():
        if line.startswith("v "):
            positions.append([float(x) for x in line.split()[1:]])
        elif line.startswith("o cluster"):
            clusters.append(0)
        elif line.startswith("f "):
            faces.append([int(x.split("/")[0]) - 1 for x in line.split()[1:]])
            clusters[-1] += 1
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if int(count.group(1)) != len(faces):
        raise ValueError("Upstream reported face count differs from OBJ")
    return (np.asarray(positions, dtype=np.float32), faces, clusters,
            elapsed_ms, completed.stdout)


def canonical_faces(faces):
    starts = np.argmin(faces, axis=1)
    oriented = faces[np.arange(len(faces))[:, None],
                     (starts[:, None] + np.arange(3)) % 3]
    return oriented[np.lexsort(oriented.T[::-1])]


def restore_indices(dump_positions, dump_faces, exact_positions, first_use_order):
    expected = exact_positions[first_use_order]
    # OBJ parsing/printing in the demo can round coordinates. Its indices still
    # refer to the original vertex buffer, so restore the verified input floats.
    tolerance = np.abs(np.spacing(expected)) * 4.0 + 1e-6
    if (dump_positions.shape != expected.shape or not np.isfinite(dump_positions).all()
            or np.any(np.abs(dump_positions - expected) > tolerance)):
        raise ValueError("Upstream dump did not preserve the expected first-use vertex order")
    if len(dump_faces) and (dump_faces.min() < 0 or dump_faces.max() >= len(expected)):
        raise ValueError("Upstream OBJ has invalid vertex indices")
    return first_use_order[dump_faces]


def compact(positions, triangles):
    used, inverse = np.unique(triangles, return_inverse=True)
    return positions[used], inverse.reshape(-1, 3)


def boundary(positions, triangles):
    mesh = Mesh(positions, triangles, np.zeros(len(triangles), dtype=np.int64)).checked()
    return topology(mesh)[1]


def assess(reference, candidate, reference_boundary, views, resolution, seed):
    vertices, triangles = candidate
    try:
        topology_error = None
        boundary_preserved = boundary(vertices, triangles) == reference_boundary
    except ValueError as error:
        topology_error = str(error)
        boundary_preserved = False
    means, per_view = render_metrics(reference, candidate, views, resolution, 2, 67.)
    return {
        "faces": len(triangles), "vertices": len(vertices),
        "topology_error": topology_error, "source_directed_boundary_preserved": boundary_preserved,
        "image": means, "per_view": per_view,
        "surface": surface_metrics(reference, candidate, 10000, seed) if not topology_error else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True,
                        help="Pinned upstream checkout containing meshoptdemo.exe")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset", type=int, help="Optional single validation asset")
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--size", type=int, default=192)
    args = parser.parse_args()
    if args.views < 2 or args.size < 32:
        parser.error("Use at least two views at a resolution of at least 32 pixels")
    upstream = args.upstream.resolve()
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                                       text=True).strip()
    if revision != UPSTREAM_COMMIT:
        parser.error(f"Expected upstream meshoptimizer {UPSTREAM_COMMIT}")
    if subprocess.check_output(["git", "-C", str(upstream), "diff", "HEAD", "--"], text=True):
        parser.error("The upstream checkout has tracked modifications")
    demo = upstream / "meshoptdemo.exe"
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [asset for asset in manifest["files"] if asset["split"] == "validation"
              and (args.asset is None or args.asset == asset["file_id"])]
    if not assets:
        parser.error("No matching validation assets")
    report = {
        "upstream_commit": revision, "demo_sha256": digest(demo),
        "script_sha256": digest(Path(__file__)),
        "manifest_sha256": digest(args.manifest),
        "protocol": {"native_cuts": [1, 2, -1], "views": args.views, "size": args.size,
                     "samples_per_pixel": 4, "flip_ppd": 67, "surface_samples": 10000},
        "assets": [],
    }
    for asset in assets:
        key = asset["file_id"]
        source = args.manifest.parent / asset["path"]
        if digest(source) != asset["sha256"]:
            raise ValueError(f"Source hash mismatch for {key}")
        positions, faces = read_stl(source)
        center = (positions.min(axis=0) + positions.max(axis=0)) * .5
        radius = np.linalg.norm(positions - center, axis=1).max()
        positions = ((positions - center) / radius).astype(np.float32).astype(np.float64)
        reference = (positions, faces)
        reference_boundary = boundary(*reference)
        scaled = (positions * OBJ_SCALE).astype(np.float32)
        vertices, first_indices = np.unique(faces, return_index=True)
        first_use = vertices[np.argsort(first_indices)]
        directory = args.out / str(key)
        directory.mkdir(exist_ok=True)
        file = directory / "source.obj"
        write_obj(file, scaled, faces)
        p0, f0, clusters0, ms, log = run_demo(demo, file, 0, directory)
        restored = restore_indices(p0, f0, scaled, first_use)
        if not np.array_equal(canonical_faces(restored), canonical_faces(faces)):
            raise ValueError(f"Level 0 did not cover the exact source triangles for {key}")
        native_depths = [int(s) for s in re.findall(r"^lod (\d+):", log, re.MULTILINE)]
        entry = {
            "asset": key, "source_sha256": asset["sha256"], "source_faces": len(faces),
            "native_levels": native_depths, "level0_clusters": len(clusters0),
            "level0_command_ms": ms, "cuts": [],
        }
        for level in (1, 2, -1):
            if level >= 0 and level not in native_depths:
                entry["cuts"].append({"cut": level, "status": "level_absent"})
                continue
            dump_positions, dump_faces, clusters, elapsed, _ = run_demo(
                demo, file, level, directory)
            restored = restore_indices(dump_positions, dump_faces, scaled, first_use)
            if not len(restored):
                entry["cuts"].append({"cut": level, "status": "empty_cut"})
                continue
            cluster_geometry = compact(positions, restored)
            result = {
                "cut": level, "status": "measured", "clusters": len(clusters),
                "native_command_ms": elapsed,
                "clusterlod": assess(reference, cluster_geometry, reference_boundary,
                                      args.views, args.size, key),
            }
            start = time.perf_counter()
            try:
                if len(restored) == len(faces):
                    control = reference
                else:
                    qem = qem_simplify(*reference, len(restored))
                    control = (qem.positions, qem.triangles)
            except ValueError as error:
                result["qem_error"] = str(error)
            else:
                result["qem_simplify_ms"] = (time.perf_counter() - start) * 1000
                result["qem"] = assess(reference, control, reference_boundary, args.views,
                                       args.size, key)
                result["exact_face_match"] = len(control[1]) == len(restored)
            entry["cuts"].append(result)
        report["assets"].append(entry)
        print(key, len(faces), [(cut["cut"], cut["status"],
                                cut.get("clusterlod", {}).get("faces"))
                               for cut in entry["cuts"]], flush=True)
    (args.out / "receipt.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
