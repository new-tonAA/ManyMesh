#!/usr/bin/env python3
"""Run reproducible repeated ManyMesh target-budget DAG construction controls."""

import argparse
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
    "pirate": ROOT / "third_party/meshoptimizer/demo/pirate.obj",
    "monkey": ROOT / "assets/models/monkey/monkey.obj",
}
BUILD_PATTERN = re.compile(r"DAG built: (\d+) nodes, (\d+) levels \(([0-9.]+)s\)")
ERROR_PATTERN = re.compile(r"worst selected screen error: ([0-9.]+) px")
TRI_PATTERN = re.compile(r"drawn: (\d+) of (\d+) visible triangles")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", choices=sorted(ASSETS),
            default=["pirate", "monkey"])
    parser.add_argument("--groups", nargs="+", type=int, default=[2, 4, 8, 16, 32])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--out-root", type=Path,
            default=ROOT / "out/targetbudget-repeat-control-20261116")
    args = parser.parse_args()
    if args.repeats < 1 or any(group < 2 for group in args.groups):
        raise ValueError("repeats must be positive and every group size must be at least two")
    if not EXECUTABLE.is_file():
        raise FileNotFoundError(EXECUTABLE)
    if args.out_root.exists():
        raise FileExistsError(f"refusing to reuse existing output directory: {args.out_root}")

    args.out_root.mkdir(parents=True)
    rng = random.Random(args.seed)
    schedules = []
    for repeat in range(args.repeats):
        schedule = [(asset, group) for asset in args.assets for group in args.groups]
        rng.shuffle(schedule)
        schedules.extend((repeat + 1, asset, group) for asset, group in schedule)

    records = []
    for repeat, asset, group in schedules:
        source = ASSETS[asset]
        output_dir = args.out_root / f"rep-{repeat:02d}" / f"{asset}-g{group}"
        output_dir.mkdir(parents=True)
        command = [
            str(EXECUTABLE), str(source), "--out", str(output_dir),
            "--mode", "dag", "--levels", "7", "--ratio", "0.7",
            "--tier", "balanced", "--target-ratio", "0.55",
            "--dag-group", str(group), "--corner-seam", "1",
            "--corner-split-uv", "1", "--quality-gate", "1",
            "--dump-obj", "0", "--write-dag", "1",
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
        if not all((build_match, error_match, triangle_match, graph_path.is_file())):
            raise RuntimeError(f"missing measurement output for {asset} group {group}; see {log_path}")
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        record = {
            "repeat": repeat,
            "asset": asset,
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
            "logSha256": sha256(log_path),
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
        "scope": "repeated single-asset DAG builds at a fixed 55% target; one CPU and executable; no image-quality claim",
        "settings": {"assets": args.assets, "groups": args.groups,
                "repeats": args.repeats, "seed": args.seed,
                "ratio": 0.7, "targetRatio": 0.55, "levels": 7,
                "cornerSeam": True, "cornerSplitUv": True, "qualityGate": True},
        "provenance": {
            "executable": {"path": str(EXECUTABLE), "sha256": sha256(EXECUTABLE)},
            "lodGraphSource": {"path": str(ROOT / "libs/manymesh/src/LodGraph.cpp"),
                    "sha256": sha256(ROOT / "libs/manymesh/src/LodGraph.cpp")},
            "mmgeoSource": {"path": str(ROOT / "tools/mmgeo/src/main.cpp"),
                    "sha256": sha256(ROOT / "tools/mmgeo/src/main.cpp")},
            "analysisScript": {"path": str(Path(__file__)), "sha256": sha256(Path(__file__))},
        },
        "records": records,
    }
    report_path = args.out_root / "build_repeats.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "runs": len(records)}, indent=2))


if __name__ == "__main__":
    main()
