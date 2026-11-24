"""Run the frozen multi-asset image-quality screen without tuning parameters."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--asset", action="append", help="Optional frozen asset subset")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("quality_scored") or manifest.get("status") != "frozen before image scoring":
        raise ValueError("The quality cohort is not in its frozen, unscored state")
    manifest_hash = digest(manifest_path)
    selected = list(manifest["assets"])
    if args.asset:
        selected = [slug for slug in selected if slug in set(args.asset)]
        if set(selected) != set(args.asset):
            raise ValueError("Requested assets do not all occur in the frozen cohort")

    receipt_path = args.receipt.resolve()
    receipt = {
        "schema": 1,
        "manifest_sha256": manifest_hash,
        "runner_sha256": digest(Path(__file__)),
        "scorer_sha256": digest(ROOT / "tools/mmtrain/bench_appearance_controls.py"),
        "python_version": platform.python_version(),
        "status": "running",
        "assets": [],
    }
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        if previous.get("manifest_sha256") != manifest_hash:
            raise ValueError("An existing receipt belongs to a different frozen cohort")
        receipt = previous
    completed = {row["asset"] for row in receipt["assets"]
                 if row.get("status") == "scored"}

    env = dict(os.environ)
    paths = [ROOT / "out/manymesh-research-pydeps-20261123",
             ROOT / "out/geometry-refinement-pilot/deps",
             ROOT / "out/geometry-refinement-pilot/deps/wgpu"]
    env["PYTHONPATH"] = os.pathsep.join(str(path.resolve()) for path in paths) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    for index, slug in enumerate(selected, 1):
        if slug in completed:
            print(index, slug, "already_scored", flush=True)
            continue
        asset = manifest["assets"][slug]
        geometry_dir = (ROOT / asset["geometry_dir"]).resolve()
        output = (args.raw_dir / slug / "quality.json").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "tools/mmtrain/bench_appearance_controls.py",
                   "--manifest", str(manifest_path), "--asset", slug,
                   "--geometry-dir", str(geometry_dir), "--out", str(output),
                   "--adapter", "Intel(R) Iris(R) Xe Graphics", "--backend", "D3D12"]
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=3600)
        elapsed_ms = (time.perf_counter() - started) * 1000
        row = {"asset": slug, "status": "scored" if result.returncode == 0 else "failed",
               "command": command, "elapsed_ms": elapsed_ms,
               "stdout": result.stdout[-3000:], "stderr": result.stderr[-5000:]}
        if result.returncode == 0 and output.is_file():
            raw = json.loads(output.read_text(encoding="utf-8"))
            if raw.get("manifest_sha256") != manifest_hash:
                raise ValueError(f"Scorer used an unexpected manifest: {slug}")
            row.update({"raw_receipt": str(output.relative_to(ROOT)).replace("\\", "/"),
                        "raw_sha256": digest(output), "summary": raw["summary"],
                        "source_faces": raw["source_faces"],
                        "control_faces": raw["control_faces"],
                        "adapter": raw["adapter"], "packages": raw["packages"]})
            completed.add(slug)
        receipt["assets"] = [item for item in receipt["assets"] if item["asset"] != slug]
        receipt["assets"].append(row)
        receipt["assets"].sort(key=lambda item: list(manifest["assets"]).index(item["asset"]))
        receipt["status"] = "running"
        write_json(receipt_path, receipt)
        print(index, slug, row["status"], f"{elapsed_ms / 1000:.1f}s", flush=True)
        if result.returncode != 0:
            raise RuntimeError(f"Quality scorer failed for {slug}; raw error recorded")

    receipt["status"] = "complete" if len(completed) == len(manifest["assets"]) else "partial"
    receipt["complete_assets"] = sorted(completed)
    write_json(receipt_path, receipt)
    print(receipt["status"], len(completed), "assets", flush=True)


if __name__ == "__main__":
    main()
