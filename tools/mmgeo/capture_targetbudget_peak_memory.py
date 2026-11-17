#!/usr/bin/env python3
"""Measure process peak working set and commit for the held-out 25-build grid."""

import ctypes
import argparse
import hashlib
import json
import re
import subprocess
import time
from ctypes import wintypes
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "out/targetbudget-heldout-20261116/builds.json"
OUT_ROOT = ROOT / "out/targetbudget-heldout-20261116/peak-memory-v2"
OUTPUT = ROOT / "out/targetbudget-heldout-20261116/peak_memory_v2.json"
CHECKPOINT = OUT_ROOT / "checkpoint.json"
BUILD_PATTERN = re.compile(r"DAG built: (\d+) nodes, (\d+) levels \(([0-9.]+)s\)")


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_peak_memory(process):
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_info = psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCountersEx), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    handle = wintypes.HANDLE(process._handle)
    if not get_info(handle, ctypes.byref(counters), counters.cb):
        error = ctypes.get_last_error()
        raise OSError(error, "GetProcessMemoryInfo failed")
    return {
        "peakWorkingSetBytes": int(counters.PeakWorkingSetSize),
        "peakPagefileBytes": int(counters.PeakPagefileUsage),
        "finalWorkingSetBytes": int(counters.WorkingSetSize),
        "finalPrivateBytes": int(counters.PrivateUsage),
        "pageFaultCount": int(counters.PageFaultCount),
    }


def main():
    if not hasattr(ctypes, "WinDLL"):
        raise RuntimeError("this measurement requires Windows process memory counters")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-root", type=Path, default=OUT_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    checkpoint = args.output_root / "checkpoint.json"
    run_data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output_root.mkdir(parents=True, exist_ok=True)
    records = json.loads(checkpoint.read_text(encoding="utf-8"))["records"] \
            if checkpoint.exists() else []
    seen = {(row["asset"], row["groupSize"]) for row in records}
    source_exe = Path(run_data["provenance"]["executable"]["path"])
    for record in run_data["records"]:
        key = (record["asset"], record["groupSize"])
        if key in seen:
            continue
        base_dir = args.output_root / f"{record['asset']}-g{record['groupSize']}"
        output_dir = base_dir
        retry = 1
        while output_dir.exists():
            retry += 1
            output_dir = args.output_root / f"{record['asset']}-g{record['groupSize']}-retry{retry:02d}"
        output_dir.mkdir(parents=True)
        command = list(record["command"])
        out_index = command.index("--out")
        command[out_index + 1] = str(output_dir)
        started = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        stdout, stderr = process.communicate()
        wall_seconds = time.perf_counter() - started
        log_path = output_dir / "run.log"
        log_path.write_text(stdout + stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"mmgeo failed: {record['asset']} g{record['groupSize']}; {log_path}")
        memory = read_peak_memory(process)
        match = BUILD_PATTERN.search(stdout + stderr)
        if match is None:
            raise RuntimeError(f"missing DAG timing in {log_path}")
        measured = {
            "asset": record["asset"],
            "groupSize": record["groupSize"],
            "sourceSha256": record["sourceSha256"],
            "graphSha256": sha256(output_dir / "lod_graph.json"),
            "wallSeconds": wall_seconds,
            "dagBuildSeconds": float(match.group(3)),
            **memory,
        }
        records.append(measured)
        seen.add(key)
        checkpoint.write_text(json.dumps({
                "scope": "checkpointed per-run measurements; resume skips completed asset/group keys",
                "inputSha256": sha256(args.input),
                "measurementScriptSha256": sha256(Path(__file__)),
                "records": records,
        }, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(measured), flush=True)

    expected = {(row["asset"], row["groupSize"]) for row in run_data["records"]}
    if len(records) != len(expected) or seen != expected:
        raise ValueError(f"expected {len(expected)} unique asset/group builds, got {len(records)}")
    report = {
        "scope": "one serial build per each held-out asset/group combination; Windows process peak working set and peak pagefile/commit counters",
        "input": str(args.input.relative_to(ROOT)),
        "inputSha256": sha256(args.input),
        "provenance": {
            "executablePath": str(source_exe),
            "executableSha256": sha256(source_exe),
            "measurementScript": str(Path(__file__).relative_to(ROOT)),
            "measurementScriptSha256": sha256(Path(__file__)),
            "api": "psapi!GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)",
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
