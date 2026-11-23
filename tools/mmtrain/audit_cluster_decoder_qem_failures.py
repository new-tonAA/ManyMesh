"""Recheck source topology for validation assets rejected during QEM pair prep."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from cluster_decoder import Mesh, topology
from cluster_decoder_pilot import read_stl


SOURCE_REJECTIONS = {
    "Duplicate geometric triangle",
    "Degenerate triangle",
    "Nonmanifold or inconsistently oriented edge",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, required=True,
                        help="Thingi10K download manifest")
    parser.add_argument("--pairs", type=Path, required=True,
                        help="QEM validation-pair preparation manifest")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    downloads = json.loads(args.downloads.read_text(encoding="utf-8"))
    download_rows = {row["file_id"]: row for row in downloads["files"]}
    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
    records = []
    for row in pairs["records"]:
        source = row["source"]
        if source["split"] != "validation":
            continue
        file_id = source["file_id"]
        download = download_rows[file_id]
        path = args.downloads.parent / download["path"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError(f"Source hash mismatch for validation asset {file_id}")

        positions, triangles = read_stl(path)
        origin = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
        scale = np.linalg.norm(positions - origin, axis=1).max()
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"Invalid normalization scale for asset {file_id}")
        normalized = (positions - origin) / scale
        mesh = Mesh(normalized, triangles,
                    np.zeros(len(triangles), dtype=np.int64)).checked()
        _, boundaries, _ = topology(mesh)

        reason = row.get("reason")
        failure_stage = None
        if row["status"] != "prepared":
            failure_stage = ("qem_coarse_output_validation"
                             if reason in SOURCE_REJECTIONS else "pair_preparation")
        records.append({
            "file_id": file_id,
            "source_sha256": source["sha256"],
            "source_faces": len(triangles),
            "source_topology": "valid",
            "source_boundary_edges": len(boundaries),
            "pair_status": row["status"],
            "pair_failure_reason": reason,
            "failure_stage": failure_stage,
        })

    result = {
        "schema": "manymesh-qem-source-failure-audit-v1",
        "scope": "Validation source-topology recheck; does not regenerate QEM outputs or quality metrics",
        "downloads_manifest_sha256": hashlib.sha256(args.downloads.read_bytes()).hexdigest(),
        "pairs_manifest_sha256": hashlib.sha256(args.pairs.read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "validation_assets": len(records),
        "source_topology_valid": sum(row["source_topology"] == "valid" for row in records),
        "qem_pair_prepared": sum(row["pair_status"] == "prepared" for row in records),
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Validated raw source topology: {result['source_topology_valid']}/{len(records)}")
    print(f"QEM pairs prepared: {result['qem_pair_prepared']}/{len(records)}")
    for row in records:
        if row["pair_status"] != "prepared":
            print(f"{row['file_id']}: source valid; {row['failure_stage']}: "
                  f"{row['pair_failure_reason']}")


if __name__ == "__main__":
    main()
