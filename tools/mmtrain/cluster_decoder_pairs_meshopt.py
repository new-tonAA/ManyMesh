"""Prepare cluster-residual labels on the vendored meshoptimizer baseline."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cluster_decoder_pairs import prepare_geometry
from fit_cluster_decoder import load_pair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True,
                        help="Existing train/validation QEM pair manifests used as source geometry")
    parser.add_argument("--meshopt", type=Path, required=True,
                        help="Folder containing the equal-face meshoptimizer baseline manifest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cluster-faces", type=int, default=128)
    parser.add_argument("--max-candidates", type=int, default=20_000_000)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if min(args.cluster_faces, args.max_candidates) < 1 or args.limit < 0:
        parser.error("Invalid preparation budget")
    args.out.mkdir(parents=True, exist_ok=True)
    meshopt_manifest_path = args.meshopt / "manifest.json"
    meshopt_manifest = json.loads(meshopt_manifest_path.read_text(encoding="utf-8"))
    meshopt_rows = {(r["split"], r["file_id"]): r for r in meshopt_manifest["records"]}
    report = {
        "scope": "Residual targets on meshoptimizer coarse geometry; train/validation only",
        "configuration": {"cluster_faces": args.cluster_faces,
                          "max_candidates": args.max_candidates,
                          "base_method": "vendored meshoptimizer 0.18.1, LockBorder",
                          "meshopt_target_error": meshopt_manifest["target_error"]},
        "meshopt_manifest_sha256": hashlib.sha256(meshopt_manifest_path.read_bytes()).hexdigest(),
        "records": [],
    }
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(r["source"]["split"] not in ("train", "validation")
               for r in manifest["records"]):
            raise ValueError("Test geometry is refused by this preparation runner")
        rows = manifest["records"][:args.limit or None]
        report.setdefault("pair_manifest_sha256", {})[str(manifest_path)] = hashlib.sha256(
            manifest_path.read_bytes()).hexdigest()
        for row in rows:
            source = row["source"]
            key = (source["split"], source["file_id"])
            result = {"source": source, "source_pair_status": row["status"]}
            if row["status"] != "prepared":
                result.update({"status": "rejected", "reason": "Source pair preparation failed: " +
                               row["reason"]})
                report["records"].append(result)
                continue
            baseline = meshopt_rows.get(key, {})
            result["meshopt_status"] = baseline.get("status", "missing")
            if baseline.get("status") != "usable":
                result.update({"status": "rejected", "reason": "Meshoptimizer baseline unavailable: " +
                               baseline.get("reason", baseline.get("status", "missing"))})
                report["records"].append(result)
                continue
            if baseline.get("target_triangles") != row.get("coarse_faces"):
                result.update({"status": "rejected", "reason": "Meshoptimizer face count does not match QEM target"})
                report["records"].append(result)
                continue
            try:
                pair = load_pair(manifest_path.parent, row)
                meshopt_path = args.meshopt / f"{key[0]}-{key[1]}.npz"
                if hashlib.sha256(meshopt_path.read_bytes()).hexdigest() != baseline["output_sha256"]:
                    raise ValueError("Meshoptimizer geometry hash mismatch")
                with np.load(meshopt_path, allow_pickle=False) as archive:
                    coarse_positions = archive["positions"]
                    coarse_triangles = archive["triangles"]
                start = time.perf_counter()
                arrays, metrics = prepare_geometry(
                    pair["source_positions"], pair["source_triangles"],
                    coarse_positions, coarse_triangles, args.cluster_faces,
                    args.max_candidates,
                    source_topology_positions=pair["source_positions"].astype(np.float32).astype(np.float64),
                    source_to_unit_scale=float(row["source_to_unit_scale"]), started=start,
                    base_method="meshoptimizer_0.18.1_lock_border")
                target = args.out / f"{key[0]}-{key[1]}.npz"
                np.savez(target, **arrays)
                result.update({"status": "prepared", "file": target.name,
                               "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                               "source_pair_sha256": row["sha256"],
                               "meshopt_geometry_sha256": baseline["output_sha256"], **metrics})
            except (ValueError, OSError) as error:
                result.update({"status": "rejected", "reason": str(error)})
            report["records"].append(result)
            print(f"{key[0]} {key[1]}: {result['status']} "
                  f"{result.get('reason', result.get('queries'))}", flush=True)
            (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n",
                                                    encoding="utf-8")
    combined_path = args.out / "manifest.json"
    combined_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    combined_hash = hashlib.sha256(combined_path.read_bytes()).hexdigest()
    for split in ("train", "validation"):
        split_root = args.out / split
        split_root.mkdir(exist_ok=True)
        records = []
        for row in report["records"]:
            if row["source"]["split"] != split:
                continue
            item = dict(row)
            if item.get("status") == "prepared":
                item["file"] = "../" + item["file"]
            records.append(item)
        split_report = {key: value for key, value in report.items() if key != "records"}
        split_report.update({"parent_manifest_sha256": combined_hash, "records": records})
        (split_root / "manifest.json").write_text(json.dumps(split_report, indent=2) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
