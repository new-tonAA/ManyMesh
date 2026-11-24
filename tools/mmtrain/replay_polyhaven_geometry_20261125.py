#!/usr/bin/env python3
"""Replay archived Poly Haven ManyMesh cuts from the pinned mmgeo binary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MM_GEO_SHA256 = (
    "8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e"
)
TOPOLOGY = ROOT / "tools/mmtrain/polyhaven_expansion_topology_20261124.json"
MATCHED = ROOT / "tools/mmtrain/polyhaven_matched_face_expansion_20261124.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ply_counts(path: Path) -> tuple[int | None, int | None]:
    header = path.read_bytes().split(b"end_header", 1)[0].decode("ascii")
    counts = {}
    for line in header.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "element":
            counts[fields[1]] = int(fields[2])
    return counts.get("vertex"), counts.get("face")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8",
                    newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmgeo", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    binary = args.mmgeo.resolve()
    output_root = args.out_dir.resolve()
    report_path = args.report.resolve()
    binary_hash = digest(binary)
    if binary_hash != EXPECTED_MM_GEO_SHA256:
        raise SystemExit("mmgeo binary SHA-256 does not match the archived receipt")

    topology = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    matched = json.loads(MATCHED.read_text(encoding="utf-8"))
    topology_by_asset = {row["asset"]: row for row in topology["assets"]}
    candidates = [row for row in matched["assets"]
                  if row.get("eligibility", {}).get("matched_inputs_ready")]

    report = {
        "schema": 1,
        "status": "running",
        "binary_sha256": binary_hash,
        "topology_report_sha256": digest(TOPOLOGY),
        "matched_geometry_receipt_sha256": digest(MATCHED),
        "script_sha256": digest(Path(__file__)),
        "command_template": [
            "<mmgeo>", "<source.obj>", "--out", "<asset-output-dir>",
            "--mode", "dag", "--levels", "8", "--ratio", "0.5",
            "--target-ratio", "0.5", "--target-ratio-cut", "0.5",
            "--quality-gate", "1", "--cluster-tris", "128",
            "--dag-group", "4", "--dump-format", "ply",
            "--visibility", "0", "--write-dag", "0"
        ],
        "protocol": {
            "assets": len(candidates),
            "face_budget": "fixed to the original matched ManyMesh candidate",
            "image_quality_scored": False
        },
        "assets": []
    }
    output_root.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(candidates, 1):
        asset = row["asset"]
        topology_row = topology_by_asset[asset]
        source = ROOT / topology_row["local_asset_directory"] / "geometry.obj"
        prior = ROOT / "out/polyhaven-matched-face-expansion-20261124" / asset / "selected_ratio_0.5.ply"
        output_dir = output_root / asset
        output = output_dir / "selected_ratio_0.5.ply"
        output_dir.mkdir(parents=True, exist_ok=True)
        eligibility = row["eligibility"]
        item = {
            "asset": asset,
            "source_sha256_expected": topology_row["extraction"]["obj_sha256"],
            "source_sha256_actual": digest(source) if source.is_file() else None,
            "archived_candidate": prior.relative_to(ROOT).as_posix(),
            "archived_candidate_sha256_observed": digest(prior) if prior.is_file() else None,
            "face_count_expected": eligibility["manymesh"]["faces"],
            "command": [],
        }
        if item["source_sha256_actual"] != item["source_sha256_expected"]:
            item["status"] = "source_hash_mismatch"
        elif not prior.is_file():
            item["status"] = "archived_candidate_missing"
        elif output.exists():
            item["status"] = "output_already_exists_refusing_to_reuse"
        else:
            command = [
                str(binary), str(source), "--out", str(output_dir),
                "--mode", "dag", "--levels", "8", "--ratio", "0.5",
                "--target-ratio", "0.5", "--target-ratio-cut", "0.5",
                "--quality-gate", "1", "--cluster-tris", "128",
                "--dag-group", "4", "--dump-format", "ply",
                "--visibility", "0", "--write-dag", "0"
            ]
            item["command"] = command
            start = time.perf_counter()
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    text=True, timeout=900)
            item["elapsed_ms"] = (time.perf_counter() - start) * 1000
            log = (result.stdout or "") + (result.stderr or "")
            (output_dir / "mmgeo.log").write_text(log, encoding="utf-8")
            item["returncode"] = result.returncode
            if result.returncode != 0 or not output.is_file():
                item["status"] = "mmgeo_failed"
            else:
                item["replayed_candidate"] = output.relative_to(ROOT).as_posix()
                item["replayed_candidate_sha256"] = digest(output)
                item["archived_candidate_sha256"] = digest(prior)
                item["byte_for_byte_match"] = output.read_bytes() == prior.read_bytes()
                item["byte_count"] = output.stat().st_size
                item["vertex_count"], item["face_count"] = ply_counts(output)
                item["face_count_matches"] = item["face_count"] == item["face_count_expected"]
                item["status"] = (
                    "byte_for_byte_match" if item["byte_for_byte_match"]
                    and item["face_count_matches"] else "geometry_bytes_differ"
                )
        report["assets"].append(item)
        report["completed_assets"] = index
        write_json(report_path, report)
        print(index, asset, item["status"], flush=True)

    statuses = [item["status"] for item in report["assets"]]
    report["summary"] = {
        "asset_count": len(report["assets"]),
        "byte_for_byte_matches": sum(
            item.get("byte_for_byte_match") is True for item in report["assets"]
        ),
        "face_count_matches": sum(
            item.get("face_count_matches") is True for item in report["assets"]
        ),
        "failed_or_different": sum(
            item["status"] != "byte_for_byte_match" for item in report["assets"]
        ),
        "total_replay_ms": round(
            sum(item.get("elapsed_ms", 0) for item in report["assets"]), 3
        )
    }
    report["status"] = ("all_archived_candidates_reproduced_byte_for_byte"
                        if statuses and all(s == "byte_for_byte_match" for s in statuses)
                        else "one_or_more_candidates_not_reproduced")
    write_json(report_path, report)
    print("Receipt:", report_path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
