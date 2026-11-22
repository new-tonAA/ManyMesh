#!/usr/bin/env python3
"""Audit the 13-asset silhouette-fusion receipts without GPU dependencies."""

import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools/mmtrain/silhouette_guide_fusion_720p_20261122.json"
REPEAT = ROOT / "tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json"
SOURCES = {
    "script_sha256": ROOT / "tools/mmtrain/bench_silhouette_guide_fusion.py",
    "parent_script_sha256": ROOT / "tools/mmtrain/bench_bevy_smaa.py",
    "raster_script_sha256": ROOT / "tools/mmtrain/bench_component_gpu.py",
}
METRICS = ("flip", "psnr_db", "ssim")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def median_time(row):
    return statistics.median(row["gpu_ms"])


def dominates(control, candidate):
    cq = control["quality"]
    q = candidate["quality"]
    return (
        cq["flip"] <= q["flip"]
        and cq["psnr_db"] >= q["psnr_db"]
        and cq["ssim"] >= q["ssim"]
        and any((cq[k] != q[k]) for k in METRICS)
    )


def main():
    old = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    new = json.loads(REPEAT.read_text(encoding="utf-8"))
    assert set(old["assets"]) == set(new["assets"])
    assert len(new["assets"]) == 13, len(new["assets"])
    assert old["manifest_sha256"] == new["manifest_sha256"]
    for field, path in SOURCES.items():
        actual = digest(path)
        assert new[field] == actual, (field, new[field], actual)
        print(f"{field}: {actual}")
    for asset in sorted(new["assets"]):
        before, after = old["assets"][asset], new["assets"][asset]
        assert set(before) == set(after), asset
        for mode in before:
            assert before[mode]["quality"] == after[mode]["quality"], (asset, mode)
            assert before[mode]["image_sha256"] == after[mode]["image_sha256"], (asset, mode)

    controls = [
        mode for mode in new["assets"][next(iter(new["assets"]))]
        if mode not in ("guide-copy", "guide-detail")
    ]
    for candidate_name in ("guide-copy", "guide-detail"):
        wins = 0
        dominated = 0
        msaa_dominated = 0
        for asset, rows in new["assets"].items():
            candidate = rows[candidate_name]
            eligible = [
                rows[mode] for mode in controls
                if median_time(rows[mode]) <= median_time(candidate)
            ]
            assert eligible, (asset, candidate_name, "no eligible controls")
            if all(
                candidate["quality"]["flip"] < row["quality"]["flip"]
                and candidate["quality"]["psnr_db"] > row["quality"]["psnr_db"]
                and candidate["quality"]["ssim"] > row["quality"]["ssim"]
                for row in eligible
            ):
                wins += 1
            dominators = [row for row in eligible if dominates(row, candidate)]
            if dominators:
                dominated += 1
            if any(dominates(row, candidate) for mode, row in rows.items()
                   if mode.endswith("msaa4") and row in eligible):
                msaa_dominated += 1
        print(f"{candidate_name}: strict wins vs every eligible control = {wins}/13")
        print(f"{candidate_name}: dominated by >=1 eligible control on all 3 metrics = {dominated}/13")
        print(f"{candidate_name}: dominated by an eligible MSAA mode on all 3 metrics = {msaa_dominated}/13")
        assert wins == 0
        assert dominated == 13
        assert msaa_dominated == 13

    print(f"quality records and image hashes identical across receipts: {len(new['assets'])} assets")
    print(f"repeat receipt SHA-256: {digest(REPEAT)}")
    print(f"verifier SHA-256: {digest(Path(__file__))}")


if __name__ == "__main__":
    main()
