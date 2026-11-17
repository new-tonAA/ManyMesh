#!/usr/bin/env python3
"""Create a hash-bound topology-only baseline schedule for support audits."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load_module(name, filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


support = load_module("batch_schedule_support", "audit_projected_support_invalidation.py")
depth = load_module("batch_schedule_depth", "depth_candidate_pilot.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_schedule(capture_path, report_path, export_path, output_path, count=12):
    capture_path = Path(capture_path).resolve()
    report_path = Path(report_path).resolve()
    export_path = Path(export_path).resolve()
    output_path = Path(output_path).resolve()

    positions, faces, candidates = depth.load_capture(capture_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    _, _, _, export_rows = support.interaction.read_export(export_path)

    frames = []
    for frame in report["frames"]:
        frame_id = int(frame["frame"])
        rows = [row for row in export_rows if int(row["frame"]) == frame_id]
        ids = [int(row["id"]) for row in rows]
        if len(ids) != len(set(ids)) or set(ids) != {
                int(candidate["id"]) for candidate in frame["candidates"]}:
            raise ValueError(f"candidate IDs do not match in frame {frame_id}")

        supports = {
            cid: set(faces[np.asarray(candidates[cid]["affected"], dtype=np.int64)]
                     .reshape(-1).tolist())
            for cid in ids
        }
        selected = []
        for row in sorted(rows, key=lambda item: (float(item["inputSSE"]), int(item["id"]))):
            cid = int(row["id"])
            if all(supports[cid].isdisjoint(supports[prior]) for prior in selected):
                selected.append(cid)
                if len(selected) == count:
                    break
        if len(selected) != count:
            raise ValueError(f"only {len(selected)} topology-compatible candidates in frame {frame_id}")
        frames.append({
            "frame": frame_id,
            "schedules": [{
                "selector": "independent",
                "search": "greedy",
                "collapseCount": count,
                "candidateIds": selected,
            }],
        })

    result = {
        "scope": "topology-only independent-SSE greedy schedule for screen-support audit",
        "hashes": {
            str(capture_path): digest(capture_path),
            str(report_path): digest(report_path),
            str(export_path): digest(export_path),
        },
        "frames": frames,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()
    result = make_schedule(args.capture, args.candidate_report, args.export,
                           args.out, args.count)
    print(json.dumps({"output": str(args.out), "frames": len(result["frames"]),
                      "collapseCount": args.count}, indent=2))


if __name__ == "__main__":
    main()
