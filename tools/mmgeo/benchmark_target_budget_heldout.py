#!/usr/bin/env python3
"""Repeated fixed-budget group-size controls on held-out repository meshes."""

import hashlib
import json
import random
import re
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTABLE = ROOT / "out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe"
ASSETS = {
    "camera": ROOT / "assets/models/camera/camera.obj",
    "cloth": ROOT / "assets/models/cloth/cloth.obj",
    "material_sphere": ROOT / "assets/models/material_sphere/material_sphere.obj",
    "rounded_cube": ROOT / "assets/models/rounded_cube/rounded_cube.obj",
    "shapes": ROOT / "assets/models/shapes/shapes.obj",
}
GROUPS = (2, 4, 8, 16, 32)
BUILD_PATTERN = re.compile(r"DAG built: (\d+) nodes, (\d+) levels \(([0-9.]+)s\)")
ERROR_PATTERN = re.compile(r"worst selected screen error: ([0-9.]+) px")
TRI_PATTERN = re.compile(r"drawn: (\d+) of (\d+) visible triangles")
OUT_ROOT = ROOT / "out/targetbudget-heldout-20261116"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    if not EXECUTABLE.is_file():
        raise FileNotFoundError(EXECUTABLE)
    if OUT_ROOT.exists():
        raise FileExistsError(f"refusing to reuse existing output directory: {OUT_ROOT}")
    for path in ASSETS.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    OUT_ROOT.mkdir(parents=True)

    rng = random.Random(20261116)
    schedule = []
    for repeat in range(1, 4):
        sweep = [(asset, group) for asset in ASSETS for group in GROUPS]
        rng.shuffle(sweep)
        schedule.extend((repeat, asset, group) for asset, group in sweep)

    records = []
    for repeat, asset, group in schedule:
        source = ASSETS[asset]
        output_dir = OUT_ROOT / f"rep-{repeat:02d}" / f"{asset}-g{group}"
        output_dir.mkdir(parents=True)
        command = [
            str(EXECUTABLE), str(source), "--out", str(output_dir),
            "--mode", "dag", "--levels", "7", "--ratio", "0.7",
            "--tier", "balanced", "--target-ratio", "0.55",
            "--target-ratio-cut", "0.55", "--dag-group", str(group),
            "--corner-seam", "1", "--corner-split-uv", "1",
            "--quality-gate", "1", "--dump-obj", "1", "--write-dag", "1",
        ]
        started = time.perf_counter()
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace")
        elapsed = time.perf_counter() - started
        log = process.stdout + process.stderr
        log_path = output_dir / "run.log"
        log_path.write_text(log, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"mmgeo failed for {asset} group {group}; see {log_path}")
        build_match = BUILD_PATTERN.search(log)
        error_match = ERROR_PATTERN.search(log)
        triangle_match = TRI_PATTERN.search(log)
        graph_path = output_dir / "lod_graph.json"
        cut_path = output_dir / "selected_ratio_0.55.ply"
        if not all((build_match, error_match, triangle_match,
                graph_path.is_file(), cut_path.is_file())):
            raise RuntimeError(f"missing measurement output for {asset} group {group}; see {log_path}")
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        record = {
            "repeat": repeat,
            "asset": asset,
            "source": str(source.relative_to(ROOT)).replace("\\", "/"),
            "groupSize": group,
            "command": command,
            "wallSeconds": elapsed,
            "dagBuildSeconds": float(build_match.group(3)),
            "nodes": int(build_match.group(1)),
            "levels": int(build_match.group(2)),
            "worstSelectedScreenErrorPx": float(error_match.group(1)),
            "selectedTriangles": int(triangle_match.group(1)),
            "baseTriangles": int(triangle_match.group(2)),
            "graphSha256": sha256(graph_path),
            "cutSha256": sha256(cut_path),
            "sourceSha256": sha256(source),
            "graphMetadataMatchesCommand": (
                graph["clustersPerNode"] == group and graph["targetRatio"] == 0.55
                and graph["source"].replace("\\", "/").endswith(
                    source.relative_to(ROOT).as_posix())),
        }
        if not record["graphMetadataMatchesCommand"]:
            raise ValueError(f"graph metadata mismatch: {asset} group {group}")
        records.append(record)
        print(json.dumps({key: record[key] for key in (
                "repeat", "asset", "groupSize", "dagBuildSeconds",
                "worstSelectedScreenErrorPx", "selectedTriangles")}), flush=True)

    report = {
        "scope": "held-out repository meshes; fixed 55% triangle budget; repeated single-asset DAG builds; no perceptual-quality claim",
        "settings": {"assets": list(ASSETS), "groups": GROUPS, "repeats": 3,
                "seed": 20261116, "ratio": 0.7, "targetRatio": 0.55,
                "levels": 7, "cornerSeam": True, "cornerSplitUv": True,
                "qualityGate": True},
        "provenance": {
            "executable": {"path": str(EXECUTABLE), "sha256": sha256(EXECUTABLE)},
            "lodGraphSource": {"path": str(ROOT / "libs/manymesh/src/LodGraph.cpp"),
                    "sha256": sha256(ROOT / "libs/manymesh/src/LodGraph.cpp")},
            "mmgeoSource": {"path": str(ROOT / "tools/mmgeo/src/main.cpp"),
                    "sha256": sha256(ROOT / "tools/mmgeo/src/main.cpp")},
            "driver": {"path": str(Path(__file__)), "sha256": sha256(Path(__file__))},
        },
        "records": records,
    }
    report_path = OUT_ROOT / "builds.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "runs": len(records)}, indent=2))


if __name__ == "__main__":
    main()
