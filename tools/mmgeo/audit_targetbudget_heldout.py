#!/usr/bin/env python3
"""Run identical multi-view visibility audits on held-out meshes with matched face budgets."""

import json
import hashlib
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "out/targetbudget-heldout-20261116/builds_summary.json"
DRIVER = ROOT / "tools/mmgeo/audit_crossasset_visibility.py"
GROUPS = (2, 4, 8, 16, 32)


def main():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    build_data = json.loads((ROOT / "out/targetbudget-heldout-20261116/builds.json")
            .read_text(encoding="utf-8"))
    manifest = {"scope": "exact equal-triangle-count visibility audits; groups with a different cut face count are excluded per asset",
            "auditWrapper": {"path": str(Path(__file__).relative_to(ROOT)),
                    "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "assets": {}}
    for asset in summary["qualityAuditAssets"]:
        source = ROOT / next(row["source"] for row in build_data["records"]
                if row["asset"] == asset)
        summaries = {row["groupSize"]: row for row in summary["summaries"]
                if row["asset"] == asset}
        counts = {group: summaries[group]["selectedTriangles"] for group in GROUPS}
        common_count, _frequency = Counter(counts.values()).most_common(1)[0]
        audited_groups = [group for group in GROUPS if counts[group] == common_count]
        excluded_groups = [group for group in GROUPS if group not in audited_groups]
        cuts = [ROOT / f"out/targetbudget-heldout-20261116/rep-01/{asset}-g{group}/selected_ratio_0.55.ply"
                for group in audited_groups]
        output = ROOT / f"out/targetbudget-heldout-20261116/{asset}_visibility.json"
        command = [sys.executable, "-I", str(DRIVER), "--mesh", str(source),
                "--asset", asset, "--output", str(output)]
        for group, cut in zip(audited_groups, cuts):
            if not cut.is_file():
                raise FileNotFoundError(cut)
            command.extend(("--cut", f"g{group}={cut}"))
        reusable = False
        if output.is_file():
            prior = json.loads(output.read_text(encoding="utf-8"))
            expected_hashes = {f"g{group}": summaries[group]["graphSha256"]
                    for group in audited_groups}
            reusable = all(prior["hashes"]["graphs"].get(key) == value
                    for key, value in expected_hashes.items()) and set(
                    prior["meanViewMetrics"]) == {f"g{group}" for group in audited_groups}
        if not reusable:
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
            if process.returncode:
                print(process.stdout)
                print(process.stderr, file=sys.stderr)
                raise RuntimeError(f"visibility audit failed for {asset}")
        result = json.loads(output.read_text(encoding="utf-8"))
        if any(counts[group] != common_count for group in audited_groups):
            raise ValueError(f"visibility groups do not share one exact budget: {asset}")
        actual_faces = result["settings"]["candidateTriangles"]
        if actual_faces != common_count:
            raise ValueError(f"unexpected cut face count for {asset}: {actual_faces}")
        manifest["assets"][asset] = {
            "source": str(source.relative_to(ROOT)).replace("\\", "/"),
            "triangleCount": common_count,
            "auditedGroups": audited_groups,
            "excludedGroupsWithDifferentBudgets": excluded_groups,
            "auditSettings": result["settings"],
            "auditOutput": str(output.relative_to(ROOT)).replace("\\", "/"),
            "reusedExistingAudit": reusable,
            "command": command,
        }
        print(json.dumps({"asset": asset,
                "triangleCount": common_count,
                "auditedGroups": audited_groups,
                "excludedGroups": excluded_groups,
                "rankByFilteredTotalSse": result["rankByFilteredTotalSse"],
                "meanViewMetrics": result["meanViewMetrics"],
                "output": str(output)}, indent=2), flush=True)
    manifest_path = ROOT / "out/targetbudget-heldout-20261116/visibility_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
