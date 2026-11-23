"""Compare an existing ManyMesh DAG build against measured upstream cuts."""

import argparse
import json
import importlib.metadata
import platform
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

from bench_upstream_clusterlod import (
    OBJ_SCALE, assess, boundary, compact, digest, qem_simplify,
)
from cluster_decoder_pilot import read_stl
from compare_qem_meshopt_validation_70pct import meshopt_simplify_raw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmgeo"))
from audit_target_budget_visibility import load_obj


def load_position_ply(path):
    with path.open("rb") as stream:
        header = []
        for raw in stream:
            line = raw.decode("ascii").strip()
            if line == "end_header":
                break
            header.append(line)
        vertices = int(next(line.split()[-1] for line in header if line.startswith("element vertex ")))
        faces = int(next(line.split()[-1] for line in header if line.startswith("element face ")))
        expected = [
            "ply", "format binary_little_endian 1.0", f"element vertex {vertices}",
            "property float x", "property float y", "property float z", f"element face {faces}",
            "property list uchar int vertex_indices", "property uint material_id",
            "property uint submesh_id",
        ]
        if header != expected:
            raise ValueError(f"Unexpected position-only PLY layout: {path}")
        points = np.frombuffer(stream.read(vertices * 12), dtype="<f4").reshape(vertices, 3)
        record = np.dtype([("count", "u1"), ("index", "<i4", (3,)), ("tags", "<u4", (2,))])
        records = np.frombuffer(stream.read(), dtype=record)
        if len(records) != faces or np.any(records["count"] != 3):
            raise ValueError(f"Invalid face records: {path}")
        triangles = records["index"].astype(np.int64)
        if len(triangles) and (triangles.min() < 0 or triangles.max() >= len(points)):
            raise ValueError(f"Invalid face indices: {path}")
    return points.astype(np.float64), triangles


def measure(asset, reference, binary, upstream_dir, directory, protocol, write_dag):
    directory.mkdir(parents=True, exist_ok=True)
    key = asset["asset"]
    source = upstream_dir / str(key) / "source.obj"
    positions, faces = reference
    input_points, input_faces = load_obj(source)
    if (not np.array_equal(input_points.astype(np.float32), positions * OBJ_SCALE)
            or not np.array_equal(input_faces, faces)):
        raise ValueError(f"Upstream staging OBJ differs from reference for asset {key}")
    ref_boundary = boundary(*reference)
    desired = {cut["cut"]: cut["clusterlod"]["faces"] for cut in asset["cuts"]
               if cut["status"] == "measured" and cut["cut"] in (1, 2)}
    if not desired:
        return {"asset": key, "status": "no_upstream_level"}
    ratios = {level: format(target / len(faces), ".6g") for level, target in desired.items()}
    command = [
        str(binary), str(source), "--out", str(directory), "--mode", "dag", "--levels", "8",
        "--ratio", "0.5", "--target-ratio", ratios[min(ratios)], "--target-ratio-cut",
        ",".join(dict.fromkeys(ratios.values())), "--quality-gate", "1", "--dump-format", "ply",
        "--visibility", "0", "--write-dag", str(int(write_dag)),
    ]
    start = time.perf_counter()
    run = subprocess.run(command, capture_output=True, text=True, timeout=900)
    command_ms = (time.perf_counter() - start) * 1000
    (directory / "build.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    result = {"asset": key, "status": "measured", "command": command,
              "command_ms": command_ms, "returncode": run.returncode, "cuts": []}
    if run.returncode:
        result["status"] = "command_failed"
        return result
    loaded = re.search(r"loaded: (\d+) vertices, (\d+) triangles", run.stdout)
    if not loaded or tuple(map(int, loaded.groups())) != (len(positions), len(faces)):
        raise ValueError(f"ManyMesh input counts do not match source asset {key}")
    build = re.search(r"DAG built: (\d+) nodes, (\d+) levels \(([0-9.]+)s\)", run.stdout)
    if build:
        result.update(nodes=int(build[1]), hierarchy_levels=int(build[2]),
                      reported_build_seconds=float(build[3]))
    for level, target in desired.items():
        ply = directory / f"selected_ratio_{ratios[level]}.ply"
        record = {"upstream_cut": level, "target_faces": target, "requested_ratio": ratios[level]}
        if ply.is_file():
            points, triangles = load_position_ply(ply)
            if len(triangles):
                candidate = compact(points / OBJ_SCALE, triangles)
                candidate_metrics = assess(reference, candidate, ref_boundary,
                                           protocol["views"], protocol["size"], key)
                record.update(candidate_metrics)
                record["under_face_cap"] = len(triangles) <= target
                record["ply_sha256"] = digest(ply)
                legal_candidate = (
                    candidate_metrics["topology_error"] is None
                    and candidate_metrics["source_directed_boundary_preserved"]
                )
                if legal_candidate:
                    qem_record = {"target_faces": len(triangles)}
                    try:
                        qem_start = time.perf_counter()
                        qem = qem_simplify(positions, faces, len(triangles))
                        qem_record["elapsed_ms"] = (time.perf_counter() - qem_start) * 1000
                        qem_geometry = (qem.positions, qem.triangles)
                        qem_metrics = assess(reference, qem_geometry, ref_boundary,
                                             protocol["views"], protocol["size"], key)
                        qem_record.update(qem_metrics)
                        qem_record["exact_face_count"] = len(qem.triangles) == len(triangles)
                        qem_legal = (
                            qem_metrics["topology_error"] is None
                            and qem_metrics["source_directed_boundary_preserved"]
                        )
                        qem_record["eligible"] = (
                            qem_record["exact_face_count"] and qem_legal
                        )
                        if qem_record["eligible"]:
                            image_keys = (
                                "flip", "psnr_db", "ssim", "silhouette_xor_fraction",
                                "coverage_mae",
                            )
                            qem_record["candidateMinusQem"] = {
                                metric: candidate_metrics["image"][metric]
                                - qem_metrics["image"][metric]
                                for metric in image_keys
                            }
                    except ValueError as error:
                        qem_record.update({"eligible": False, "error": str(error)})
                    record["qemAtCandidateFaceCount"] = qem_record

                    meshopt_record = {"target_faces": len(triangles), "flags": ["LockBorder"]}
                    try:
                        meshopt_start = time.perf_counter()
                        meshopt_positions, meshopt_faces, meshopt_meta = meshopt_simplify_raw(
                            positions, faces, len(triangles), directory
                        )
                        meshopt_record["elapsed_ms"] = (
                            time.perf_counter() - meshopt_start
                        ) * 1000
                        meshopt_record["reported_error"] = meshopt_meta.get("error")
                        meshopt_geometry = (meshopt_positions, meshopt_faces)
                        meshopt_metrics = assess(reference, meshopt_geometry, ref_boundary,
                                                protocol["views"], protocol["size"], key)
                        meshopt_record.update(meshopt_metrics)
                        meshopt_record["exact_face_count"] = (
                            len(meshopt_faces) == len(triangles)
                        )
                        meshopt_legal = (
                            meshopt_metrics["topology_error"] is None
                            and meshopt_metrics["source_directed_boundary_preserved"]
                        )
                        meshopt_record["eligible"] = (
                            meshopt_record["exact_face_count"] and meshopt_legal
                        )
                        if meshopt_record["eligible"]:
                            image_keys = (
                                "flip", "psnr_db", "ssim", "silhouette_xor_fraction",
                                "coverage_mae",
                            )
                            meshopt_record["candidateMinusMeshoptimizer"] = {
                                metric: candidate_metrics["image"][metric]
                                - meshopt_metrics["image"][metric]
                                for metric in image_keys
                            }
                    except (OSError, subprocess.CalledProcessError, ValueError) as error:
                        meshopt_record.update({"eligible": False, "error": str(error)})
                    record["meshoptimizerAtCandidateFaceCount"] = meshopt_record
        result["cuts"].append(record)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--upstream-receipt", required=True, type=Path)
    parser.add_argument("--upstream-cut-dir", required=True, type=Path,
                        help="Directory containing one <asset>/source.obj per receipt asset")
    parser.add_argument("--mmgeo", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset", type=int)
    parser.add_argument("--write-dag", action="store_true",
                        help="Save graph geometry for offline assembled-cut audits")
    args = parser.parse_args()
    reference_receipt = json.loads(args.upstream_receipt.read_text(encoding="utf-8"))
    protocol = reference_receipt["protocol"]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_index = {asset["file_id"]: asset for asset in manifest["files"]
                    if asset["split"] == "validation"}
    if digest(args.manifest) != reference_receipt["manifest_sha256"]:
        raise ValueError("The source manifest differs from the upstream experiment")
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.mmgeo.resolve()
    cut_root = args.upstream_cut_dir.resolve()
    receipt = {
        "manifest_sha256": digest(args.manifest),
        "upstream_receipt_sha256": digest(args.upstream_receipt),
        "upstream_cut_dir": str(cut_root),
        "mmgeo_sha256": digest(binary),
        "mmgeo_source_sha256": digest(Path("tools/mmgeo/src/main.cpp")),
        "script_sha256": digest(Path(__file__)),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "fast_simplification_version": importlib.metadata.version("fast-simplification"),
        "meshoptimizer_helper_sha256": digest(Path("tools/mmtrain/meshopt_simplify.cjs")),
        "meshoptimizer_module_sha256": digest(
            Path("third_party/meshoptimizer/js/meshopt_simplifier.js")
        ),
        "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "protocol": protocol,
        "assets": [],
    }
    for asset in reference_receipt["assets"]:
        if args.asset is not None and args.asset != asset["asset"]:
            continue
        source = args.manifest.parent / source_index[asset["asset"]]["path"]
        if digest(source) != asset["source_sha256"]:
            raise ValueError(f"Source hash mismatch for {asset['asset']}")
        positions, faces = read_stl(source)
        center = (positions.min(axis=0) + positions.max(axis=0)) * .5
        radius = np.linalg.norm(positions - center, axis=1).max()
        positions = ((positions - center) / radius).astype(np.float32).astype(np.float64)
        result = measure(asset, (positions, faces), binary, args.upstream_cut_dir.resolve(),
                         args.out / str(asset["asset"]), protocol, args.write_dag)
        receipt["assets"].append(result)
        print(result["asset"], result["status"],
              [(row["target_faces"], row.get("faces")) for row in result.get("cuts", [])],
              flush=True)
    if not receipt["assets"]:
        parser.error("No matching upstream assets")
    (args.out / "receipt.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
