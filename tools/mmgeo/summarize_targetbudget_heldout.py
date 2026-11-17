#!/usr/bin/env python3
"""Aggregate held-out target-budget build repeats and choose fair visibility audits."""

import hashlib
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "out/targetbudget-heldout-20261116/builds.json"
OUTPUT = ROOT / "out/targetbudget-heldout-20261116/builds_summary.json"
GROUPS = (2, 4, 8, 16, 32)
ASSETS = ("camera", "cloth", "material_sphere", "rounded_cube", "shapes")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    expected_runs = len(ASSETS) * len(GROUPS) * 3
    if len(data["records"]) != expected_runs:
        raise ValueError(f"expected {expected_runs} runs; found {len(data['records'])}")
    records = {}
    for row in data["records"]:
        records.setdefault((row["asset"], row["groupSize"]), []).append(row)

    summaries = []
    quality_eligible = []
    for asset in ASSETS:
        asset_triangle_counts = set()
        for group in GROUPS:
            rows = records[(asset, group)]
            if len(rows) != 3:
                raise ValueError(f"wrong repetition count for {asset} group {group}")
            for field in ("graphSha256", "cutSha256", "selectedTriangles",
                    "worstSelectedScreenErrorPx", "baseTriangles", "sourceSha256"):
                if len({row[field] for row in rows}) != 1:
                    raise ValueError(f"repeated output changed: {asset} group {group} field {field}")
            if not all(row["graphMetadataMatchesCommand"] for row in rows):
                raise ValueError(f"graph metadata mismatch: {asset} group {group}")
            asset_triangle_counts.add(rows[0]["selectedTriangles"])
            summaries.append({
                "asset": asset,
                "groupSize": group,
                "repeats": 3,
                "dagBuildMedianSeconds": statistics.median(
                        row["dagBuildSeconds"] for row in rows),
                "dagBuildMinSeconds": min(row["dagBuildSeconds"] for row in rows),
                "dagBuildMaxSeconds": max(row["dagBuildSeconds"] for row in rows),
                "wallMedianSeconds": statistics.median(row["wallSeconds"] for row in rows),
                "worstSelectedScreenErrorPx": rows[0]["worstSelectedScreenErrorPx"],
                "selectedTriangles": rows[0]["selectedTriangles"],
                "baseTriangles": rows[0]["baseTriangles"],
                "graphSha256": rows[0]["graphSha256"],
                "cutSha256": rows[0]["cutSha256"],
                "sourceSha256": rows[0]["sourceSha256"],
            })
        spread = max(asset_triangle_counts) - min(asset_triangle_counts)
        source_triangles = next(row["baseTriangles"] for row in data["records"]
                if row["asset"] == asset)
        eligible = spread <= max(1, round(source_triangles * 0.0001))
        if eligible:
            quality_eligible.append(asset)

    result = {
        "scope": "five additional repository meshes; 75 randomized/interleaved builds; repeated output determinism; no image-space claim yet",
        "input": str(INPUT.relative_to(ROOT)),
        "inputSha256": sha256(INPUT),
        "provenance": data["provenance"],
        "aggregationScript": {"path": str(Path(__file__).relative_to(ROOT)),
                "sha256": sha256(Path(__file__))},
        "qualityAuditEligibilityRule": "include only assets whose selected face counts vary by at most max(1, round(sourceTriangles * 0.0001)) across all tested group sizes; this avoids confounding materially different triangle budgets",
        "qualityAuditAssets": quality_eligible,
        "summaries": summaries,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "runs": len(data["records"]),
        "qualityAuditAssets": quality_eligible,
        "summary": str(OUTPUT),
        "table": [{"asset": row["asset"], "group": row["groupSize"],
                "buildMedianSeconds": row["dagBuildMedianSeconds"],
                "buildRangeSeconds": [row["dagBuildMinSeconds"], row["dagBuildMaxSeconds"]],
                "selectedTriangles": row["selectedTriangles"]}
                for row in summaries],
    }, indent=2))


if __name__ == "__main__":
    main()
