"""Run identity sidecar smoke checks on training-only STL pilot assets.

This does not simplify, train, or measure reconstruction quality. It verifies the
mesh/sidecar/load contract before any learned quality experiment is attempted.
"""

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

from cluster_decoder import FEATURES, Mesh, Model, decode, write_sidecar


def read_binary_stl(path):
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError("Truncated binary STL")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count or count == 0:
        raise ValueError("This smoke reader requires an exact-length binary STL")
    dtype = np.dtype({"names": ["vertices"], "formats": [("<f4", (3, 3))],
                      "offsets": [12], "itemsize": 50})
    soup = np.frombuffer(data, dtype=dtype, count=count, offset=84)["vertices"]
    positions, inverse = np.unique(soup.reshape(-1, 3), axis=0, return_inverse=True)
    return positions.astype(np.float64), inverse.reshape(-1, 3)


def read_stl(path):
    data = Path(path).read_bytes()
    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        return read_binary_stl(path)
    lines = [line.split() for line in data.decode("ascii").splitlines() if line.strip()]
    if not lines or lines[0][0] != "solid" or lines[-1][0] != "endsolid":
        raise ValueError("Neither exact binary STL nor a complete ASCII solid")
    vertices, state, count = [], "facet", 0
    for tokens in lines[1:-1]:
        if state == "facet" and len(tokens) == 5 and tokens[:2] == ["facet", "normal"]:
            if not np.isfinite([float(x) for x in tokens[2:]]).all():
                raise ValueError("Invalid ASCII facet normal")
            state = "loop"
        elif state == "loop" and tokens == ["outer", "loop"]:
            state, count = "vertex", 0
        elif state == "vertex" and len(tokens) == 4 and tokens[0] == "vertex" and count < 3:
            vertices.append([float(x) for x in tokens[1:]])
            count += 1
        elif state == "vertex" and count == 3 and tokens == ["endloop"]:
            state = "endfacet"
        elif state == "endfacet" and tokens == ["endfacet"]:
            state = "facet"
        else:
            raise ValueError("Malformed ASCII STL facet")
    if state != "facet" or not vertices or not np.isfinite(vertices).all():
        raise ValueError("Incomplete or nonfinite ASCII STL")
    positions, inverse = np.unique(np.asarray(vertices, dtype=np.float64), axis=0,
                                   return_inverse=True)
    return positions, inverse.reshape(-1, 3)


def partition_faces(triangles, cluster_faces):
    if cluster_faces < 1:
        raise ValueError("Cluster size must be positive")
    incidence = {}
    adjacency = [[] for _ in triangles]
    for face_id, face in enumerate(triangles):
        for u, v in zip(face, np.roll(face, -1)):
            incidence.setdefault(tuple(sorted((int(u), int(v)))), []).append(face_id)
    for faces in incidence.values():
        if len(faces) > 2:
            raise ValueError("Nonmanifold STL edge")
        if len(faces) == 2:
            a, b = faces
            adjacency[a].append(b)
            adjacency[b].append(a)
    groups = np.full(len(triangles), -1, dtype=np.int64)
    group = 0
    # Assign when popped, so an interrupted frontier remains available to later groups.
    for seed in range(len(triangles)):
        if groups[seed] != -1:
            continue
        queue, queued, size = deque([seed]), {seed}, 0
        while queue and size < cluster_faces:
            face = queue.popleft()
            if groups[face] != -1:
                continue
            groups[face] = group
            size += 1
            for neighbor in sorted(adjacency[face]):
                if groups[neighbor] == -1 and neighbor not in queued:
                    queued.add(neighbor)
                    queue.append(neighbor)
        group += 1
    return groups


def polynomial_control():
    weights = np.zeros((FEATURES, FEATURES * 3, 3), dtype=np.float32)
    for feature in range(FEATURES):
        for axis in range(3):
            weights[feature, feature * 3 + axis, axis] = 1
    return Model(weights)


def peak_process_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_working", "working", "peak_paged", "paged",
                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters),
                                              wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters),
                                          counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.peak_working)
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cluster-faces", type=int, default=128)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--refine-count", type=int, default=8)
    args = parser.parse_args()
    if args.limit < 1 or args.refine_count < 0 or args.cluster_faces < 1:
        parser.error("Invalid asset, refinement, or cluster count")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sources = [row for row in manifest["files"] if row["split"] == "train"][:args.limit]
    if not sources:
        raise ValueError("No training assets; test assets will not be substituted")
    args.out.mkdir(parents=True, exist_ok=True)
    model = polynomial_control()
    model_path = args.out / "polynomial-control.npz"
    np.savez(model_path, weights=model.weights, max_offset=np.array(model.max_offset))
    # Exercise loading persisted shared weights, not just the in-memory object.
    with np.load(model_path, allow_pickle=False) as saved:
        model = Model(saved["weights"], float(saved["max_offset"]))
    records = []
    for row in sources:
        path = args.manifest.parent / row["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Input hash mismatch: {path}")
        positions, triangles = read_stl(path)
        if len(triangles) != row["faces"]:
            raise ValueError("Input face count differs from license-audited manifest")
        groups = partition_faces(triangles, args.cluster_faces)
        mesh = Mesh(positions, triangles, groups).checked()
        folder = args.out / f"train-{row['file_id']}"
        folder.mkdir(exist_ok=True)
        np.savez(folder / "base.npz", positions=positions, triangles=triangles,
                 face_clusters=groups)
        with np.load(folder / "base.npz", allow_pickle=False) as saved:
            mesh = Mesh(saved["positions"], saved["triangles"], saved["face_clusters"])
        latent = np.zeros((int(groups.max()) + 1, model.weights.shape[1]), dtype=np.float32)
        record = {"source": row, "mesh_sha256": mesh.checked().digest(),
                  "clusters": len(latent), "variants": {}}
        for mode, refine in (("fixed", ()), ("refine", tuple(range(min(args.refine_count,
                                                                 len(triangles)))))):
            sidecar = folder / f"{mode}.sidecar"
            write_sidecar(sidecar, mesh, model, latent, refine)
            result, report = decode(mesh, model, sidecar, len(triangles) + 2 * len(refine))
            if not np.array_equal(result.positions[:len(positions)], positions):
                raise ValueError("Identity decoder changed source positions")
            if mode == "fixed" and not np.array_equal(result.triangles, triangles):
                raise ValueError("Identity decoder changed fixed topology")
            np.savez(folder / f"{mode}-decoded.npz", positions=result.positions,
                     triangles=result.triangles, face_clusters=result.face_clusters)
            report.update({"model_file_bytes": model_path.stat().st_size,
                           "base_file_bytes": (folder / "base.npz").stat().st_size,
                           "process_peak_bytes": peak_process_bytes(),
                           "timing_scope": "mesh/model validation, sidecar load, decode, local audit",
                           "quality_evaluated": False})
            record["variants"][mode] = report
        records.append(record)
        print(f"train {row['file_id']}: {len(triangles)} triangles, {len(latent)} clusters", flush=True)
    report = {"scope": "Training-only identity smoke check; no learned result or quality gain",
              "records": records}
    (args.out / "report.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
