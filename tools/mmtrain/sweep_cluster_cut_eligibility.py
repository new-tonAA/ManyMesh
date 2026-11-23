"""Screen fixed cluster/DAG build settings for exact legal stock-cut matches.

This is a geometry-eligibility experiment only. It deliberately does not score
image quality, and every setting in the fixed grid is retained in the receipt.
"""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import subprocess
import time

import numpy as np

from bench_upstream_clusterlod import OBJ_SCALE, boundary, compact, digest
from cluster_decoder import Mesh
from cluster_decoder_pilot import read_stl
from compare_manymesh_clusterlod import load_position_ply
from audit_target_budget_visibility import load_obj


CLUSTER_TRIANGLES = (64, 128, 256)
DAG_GROUPS = (4, 8)


def assess_eligibility(reference_boundary, geometry):
    vertices, triangles = geometry
    try:
        candidate_boundary = boundary(vertices, triangles)
        topology_error = None
    except ValueError as error:
        candidate_boundary = None
        topology_error = str(error)
    return {
        "topology_error": topology_error,
        "source_directed_boundary_preserved": (
            topology_error is None and candidate_boundary == reference_boundary
        ),
    }


def run_build(binary, source_obj, out_dir, ratios, cluster_triangles, dag_group):
    out_dir.mkdir(parents=True, exist_ok=True)
    ratio_text = {depth: format(faces / ratios["source_faces"], ".6g")
                  for depth, faces in ratios["stock_faces"].items()}
    unique_ratios = list(dict.fromkeys(ratio_text.values()))
    command = [
        str(binary), str(source_obj), "--out", str(out_dir), "--mode", "dag",
        "--levels", "8", "--ratio", "0.5", "--target-ratio", ratio_text[min(ratio_text)],
        "--target-ratio-cut", ",".join(unique_ratios), "--quality-gate", "1",
        "--cluster-tris", str(cluster_triangles), "--dag-group", str(dag_group),
        "--dump-format", "ply", "--visibility", "0", "--write-dag", "0",
    ]
    start = time.perf_counter()
    run = subprocess.run(command, capture_output=True, text=True, timeout=900)
    elapsed_ms = (time.perf_counter() - start) * 1000
    (out_dir / "build.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    result = {"command": command, "returncode": run.returncode,
              "elapsed_ms": elapsed_ms, "cuts": []}
    if run.returncode:
        result["status"] = "command_failed"
        result["stderr_tail"] = run.stderr[-4000:]
        return result
    loaded = re.search(r"loaded: (\d+) vertices, (\d+) triangles", run.stdout)
    if not loaded or int(loaded.group(2)) != ratios["source_faces"]:
        raise ValueError(f"Source face count mismatch in {source_obj}")
    result["status"] = "measured"
    result["reported_build_seconds"] = (
        float(re.search(r"DAG built: \d+ nodes, \d+ levels \(([0-9.]+)s\)",
                        run.stdout).group(1))
        if re.search(r"DAG built: \d+ nodes, \d+ levels \(([0-9.]+)s\)", run.stdout)
        else None
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--upstream-receipt", type=Path, required=True)
    parser.add_argument("--upstream-cut-dir", type=Path, required=True)
    parser.add_argument("--mmgeo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset", type=int, help="Run one validation asset as a preflight")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    upstream = json.loads(args.upstream_receipt.read_text(encoding="utf-8"))
    by_id = {row["file_id"]: row for row in manifest["files"]
             if row["split"] == "validation"}
    binary = args.mmgeo.resolve()
    cut_root = args.upstream_cut_dir.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = {
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "worktree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], text=True).strip()),
        "manifest_sha256": digest(args.manifest),
        "upstream_receipt_sha256": digest(args.upstream_receipt),
        "mmgeo_sha256": digest(binary),
        "mmgeo_source_sha256": digest(Path("tools/mmgeo/src/main.cpp")),
        "script_sha256": digest(Path(__file__)),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "protocol": {
            "cluster_triangles": list(CLUSTER_TRIANGLES),
            "dag_group": list(DAG_GROUPS),
            "levels": 8,
            "quality_gate": 1,
            "other_build_parameters": "mmgeo defaults",
            "eligibility": "exact stock face count, strict closed topology, source directed boundary",
            "quality_scoring": False,
        },
        "assets": [],
    }

    selected_assets = [row for row in upstream["assets"]
                       if args.asset is None or row["asset"] == args.asset]
    if not selected_assets:
        parser.error("No validation asset matches --asset")
    for stock_asset in selected_assets:
        asset_id = stock_asset["asset"]
        input_record = by_id[asset_id]
        source_stl = args.manifest.parent / input_record["path"]
        if digest(source_stl) != stock_asset["source_sha256"]:
            raise ValueError(f"Source hash mismatch for asset {asset_id}")
        positions, faces = read_stl(source_stl)
        center = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
        radius = np.linalg.norm(positions - center, axis=1).max()
        positions = ((positions - center) / radius).astype(np.float32).astype(np.float64)
        source_geometry = (positions, faces)
        source_boundary = boundary(*source_geometry)
        source_obj = cut_root / str(asset_id) / "source.obj"
        staged_positions, staged_faces = load_obj(source_obj)
        if (not np.array_equal(staged_positions.astype(np.float32), positions * OBJ_SCALE)
                or not np.array_equal(staged_faces, faces)):
            raise ValueError(f"Staged source OBJ differs from source asset {asset_id}")

        stock_faces = {row["cut"]: row["clusterlod"]["faces"]
                       for row in stock_asset["cuts"]
                       if row["status"] == "measured" and row["cut"] in (1, 2)}
        asset_result = {
            "asset": asset_id,
            "source_sha256": stock_asset["source_sha256"],
            "source_faces": len(faces),
            "stock_faces": stock_faces,
            "settings": [],
        }
        for cluster_triangles in CLUSTER_TRIANGLES:
            for dag_group in DAG_GROUPS:
                setting_dir = args.out / str(asset_id) / f"ct{cluster_triangles}_dg{dag_group}"
                target_config = {"source_faces": len(faces), "stock_faces": stock_faces}
                build = run_build(binary, source_obj, setting_dir, target_config,
                                  cluster_triangles, dag_group)
                setting_result = {
                    "cluster_triangles": cluster_triangles,
                    "dag_group": dag_group,
                    **build,
                }
                if build["status"] == "measured":
                    for depth, target_faces in stock_faces.items():
                        ratio = format(target_faces / len(faces), ".6g")
                        ply = setting_dir / f"selected_ratio_{ratio}.ply"
                        row = {"stock_depth": depth, "target_faces": target_faces,
                               "ply_exists": ply.is_file()}
                        if ply.is_file():
                            candidate_positions, candidate_faces = load_position_ply(ply)
                            candidate = compact(candidate_positions / OBJ_SCALE, candidate_faces)
                            row["faces"] = len(candidate_faces)
                            row["under_stock_cap"] = len(candidate_faces) <= target_faces
                            row["exact_face_count"] = len(candidate_faces) == target_faces
                            row["ply_sha256"] = digest(ply)
                            row.update(assess_eligibility(source_boundary, candidate))
                            row["eligible_exact_face"] = (
                                row["exact_face_count"]
                                and row["topology_error"] is None
                                and row["source_directed_boundary_preserved"]
                            )
                        setting_result["cuts"].append(row)
                asset_result["settings"].append(setting_result)
                summary = [(r.get("stock_depth"), r.get("faces"),
                            r.get("eligible_exact_face")) for r in setting_result["cuts"]]
                print(asset_id, cluster_triangles, dag_group, summary, flush=True)
        receipt["assets"].append(asset_result)

    receipt_path = args.out / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                            encoding="utf-8")
    print(f"receipt: {receipt_path}", flush=True)


if __name__ == "__main__":
    main()
