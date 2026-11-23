"""Run the vendored meshoptimizer simplifier at the QEM pilot face counts."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import time

import numpy as np

from cluster_decoder import Mesh, topology
from fit_cluster_decoder import load_pair


HELPER = Path(__file__).with_name("meshopt_simplify.cjs")


def simplify_pair(pair, target_triangles, helper=HELPER, node="node", target_error=1e6):
    """Call the pinned WASM simplifier and audit the returned geometry."""
    positions = np.asarray(pair["source_positions"], dtype=np.float32)
    source_triangles = np.asarray(pair["source_triangles"], dtype=np.int64)
    if not np.isfinite(positions).all() or not len(source_triangles):
        raise ValueError("Invalid source mesh")
    if not 1 <= target_triangles < len(source_triangles):
        raise ValueError("Target triangle count must be below source count")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mm-meshopt-") as temporary:
        input_path = Path(temporary) / "input.json"
        output_path = Path(temporary) / "output.json"
        input_path.write_text(json.dumps({
            "positions": positions.tolist(),
            "triangles": source_triangles.tolist(),
            "targetTriangles": int(target_triangles),
            "targetError": float(target_error),
        }), encoding="utf-8")
        completed = subprocess.run(
            [node, str(helper), str(input_path), str(output_path)],
            check=False, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0:
            raise ValueError("meshoptimizer failed: " + completed.stderr.strip()[-1200:])
        result = json.loads(output_path.read_text(encoding="utf-8"))
    indices = np.asarray(result["indices"], dtype=np.int64)
    if not len(indices) or len(indices) % 3 or indices.min() < 0 or indices.max() >= len(positions):
        raise ValueError("meshoptimizer returned invalid indices")
    used, compact = np.unique(indices, return_inverse=True)
    triangles = compact.reshape(-1, 3)
    compact_positions = positions[used].astype(np.float64)
    clusters = np.zeros(len(triangles), dtype=np.int64)
    source = Mesh(positions.astype(np.float64), source_triangles,
                  np.zeros(len(source_triangles), dtype=np.int64)).checked()
    candidate = Mesh(compact_positions, triangles, clusters).checked()
    source_boundary = topology(source)[1]
    candidate_boundary = topology(candidate)[1]
    if source_boundary != candidate_boundary:
        raise ValueError("meshoptimizer changed the directed source boundary")
    result["boundary_preserved"] = True
    result["topology_valid"] = True
    result["decode_seconds"] = time.perf_counter() - started
    return {"positions": compact_positions, "triangles": triangles}, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--target-error", type=float, default=1e6)
    parser.add_argument("--target-map", type=Path,
                        help="JSON object mapping 'split:file_id' to an explicit face budget")
    parser.add_argument("--limit", type=int, default=0,
                        help="optional per-manifest record limit; zero means all records")
    args = parser.parse_args()
    if not np.isfinite(args.target_error) or args.target_error <= 0 or args.limit < 0:
        parser.error("Invalid simplification limits")
    target_map = json.loads(args.target_map.read_text(encoding="utf-8")) if args.target_map else None
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "Vendored meshoptimizer WASM geometry baseline; no final test assets",
        "implementation": "meshoptimizer 0.18.1 vendored JS/WASM; simplify with LockBorder",
        "target_error": args.target_error,
        "target_policy": "per-asset explicit target map" if target_map is not None else "QEM pilot target faces",
        "target_map_sha256": hashlib.sha256(args.target_map.read_bytes()).hexdigest() if args.target_map else None,
        "node": args.node,
        "python": platform.python_version(),
        "helper_sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
        "records": [],
    }
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(r["source"]["split"] not in ("train", "validation")
               for r in manifest["records"]):
            raise ValueError("Test geometry is refused by this baseline runner")
        rows = manifest["records"][:args.limit or None]
        for row in rows:
            source = row["source"]
            key = (source["split"], source["file_id"])
            record = {"split": source["split"], "file_id": source["file_id"],
                      "source_sha256": source["sha256"],
                      "preparation_status": row["status"]}
            if row["status"] != "prepared":
                record["status"] = "input_rejected"
                record["reason"] = row["reason"]
                report["records"].append(record)
                continue
            target_key = f"{key[0]}:{key[1]}"
            if target_map is not None and target_key not in target_map:
                record.update({"status": "target_missing", "reason": "No requested refinement budget"})
                report["records"].append(record)
                continue
            try:
                pair = load_pair(manifest_path.parent, row)
                target_triangles = (int(target_map[target_key])
                                    if target_map is not None else len(pair["triangles"]))
                geometry, result = simplify_pair(pair, target_triangles,
                                                 node=args.node, target_error=args.target_error)
                target = args.out / f"{source['split']}-{source['file_id']}.npz"
                np.savez(target, **geometry)
                result.update({"output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                               "target_triangles": target_triangles,
                               "triangle_count_match": len(geometry["triangles"]) == target_triangles})
                record.update(result)
                record["status"] = "usable" if result["triangle_count_match"] else "count_mismatch"
            except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                record["status"] = "rejected"
                record["reason"] = str(error)
            report["records"].append(record)
            print(f"{source['split']} {source['file_id']}: {record['status']} "
                  f"{record.get('outputTriangles', record.get('reason', ''))}", flush=True)
            (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n",
                                                    encoding="utf-8")
    (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n",
                                            encoding="utf-8")


if __name__ == "__main__":
    main()
