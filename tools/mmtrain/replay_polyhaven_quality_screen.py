"""Replay image scoring for the frozen Poly Haven geometry cohort."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_FILES = ("reference.obj", "manymesh.obj", "qem_preserve_border.obj",
                  "meshoptimizer_lock_border.obj", "neutral.mtl")
COMPARE_FIELDS = ("source_sha256", "source_faces", "control_faces", "adapter",
                  "packages", "reference", "surface", "views", "summary")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(left, right, path=""):
    differences = []
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return [(path, "key mismatch")]
        for key in left:
            differences.extend(compare(left[key], right[key], f"{path}/{key}"))
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [(path, "length mismatch")]
        for index, (a, b) in enumerate(zip(left, right)):
            differences.extend(compare(a, b, f"{path}/{index}"))
    elif left != right:
        differences.append((path, left, right))
    return differences


def package_versions():
    return {name: importlib.metadata.version(name)
            for name in ("wgpu", "numpy", "scikit-image", "flip-evaluator")}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--original-receipt", type=Path, required=True)
    parser.add_argument("--original-raw-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--asset", action="append", help="Optional frozen asset subset")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    original_receipt_path = args.original_receipt.resolve()
    raw_dir = args.original_raw_dir.resolve()
    output_dir = args.out_dir.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_receipt = json.loads(original_receipt_path.read_text(encoding="utf-8"))
    manifest_sha = digest(manifest_path)
    if original_receipt.get("status") != "complete":
        raise ValueError("Original scoring receipt is not complete")
    if original_receipt.get("manifest_sha256") != manifest_sha:
        raise ValueError("Original scoring receipt uses a different manifest")
    if original_receipt.get("scorer_sha256") != digest(ROOT / "tools/mmtrain/bench_appearance_controls.py"):
        raise ValueError("Current scorer differs from the original scoring receipt")
    if original_receipt.get("runner_sha256") != digest(ROOT / "tools/mmtrain/score_polyhaven_quality_cohort.py"):
        raise ValueError("Original cohort runner hash does not match the checked-in source")

    original_rows = {row["asset"]: row for row in original_receipt["assets"]}
    selected = list(manifest["assets"])
    if args.asset:
        requested = set(args.asset)
        selected = [slug for slug in selected if slug in requested]
        if set(selected) != requested:
            raise ValueError("Requested asset is absent from the frozen manifest")
    for slug in selected:
        row = original_rows.get(slug)
        if not row or row.get("status") != "scored":
            raise ValueError(f"Original asset score is missing: {slug}")
        old_raw = ROOT / row["raw_receipt"]
        expected_raw = raw_dir / slug / "quality.json"
        if old_raw.resolve() != expected_raw.resolve():
            raise ValueError(f"Original raw receipt is outside the declared raw directory: {slug}")
        if not old_raw.is_file() or digest(old_raw) != row.get("raw_sha256"):
            raise ValueError(f"Original raw receipt hash mismatch: {slug}")
        frozen = manifest["assets"][slug]
        geometry_dir = ROOT / frozen["geometry_dir"]
        expected_files = frozen.get("frozen_exports", {}).get("obj_exports_sha256", {})
        for name in GEOMETRY_FILES:
            source = geometry_dir / name
            if not source.is_file() or digest(source) != expected_files.get(name):
                raise ValueError(f"Frozen geometry input hash mismatch: {slug}/{name}")

    scorer = ROOT / "tools/mmtrain/bench_appearance_controls.py"
    script_sha = digest(Path(__file__))
    versions = package_versions()
    receipt_path = output_dir / "replay_receipt.json"
    receipt = {
        "schema": 1,
        "status": "running",
        "scope": "image-scoring replay only; no geometry regeneration",
        "manifest_sha256": manifest_sha,
        "original_receipt_sha256": digest(original_receipt_path),
        "replay_script_sha256": script_sha,
        "scorer_sha256": digest(scorer),
        "python_version": platform.python_version(),
        "packages": versions,
        "assets": [],
    }
    completed = {}
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        for key in ("manifest_sha256", "original_receipt_sha256", "replay_script_sha256",
                    "scorer_sha256", "python_version", "packages"):
            if previous.get(key) != receipt[key]:
                raise ValueError(f"Existing replay receipt differs in {key}; use a new output path")
        completed = {row["asset"]: row for row in previous.get("assets", [])
                     if row.get("status") == "exact_match"}
        receipt["assets"] = list(previous.get("assets", []))

    env = dict(os.environ)
    extra_paths = [ROOT / "out/manymesh-research-pydeps-20261123",
                   ROOT / "out/geometry-refinement-pilot/deps",
                   ROOT / "out/geometry-refinement-pilot/deps/wgpu"]
    env["PYTHONPATH"] = os.pathsep.join(str(path.resolve()) for path in extra_paths) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    for index, slug in enumerate(selected, 1):
        if slug in completed:
            print(index, slug, "exact_match (resumed)", flush=True)
            continue
        asset = manifest["assets"][slug]
        geometry_dir = ROOT / asset["geometry_dir"]
        output = output_dir / slug / "quality.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(scorer), "--manifest", str(manifest_path),
                   "--asset", slug, "--geometry-dir", str(geometry_dir),
                   "--out", str(output), "--adapter", "Intel(R) Iris(R) Xe Graphics",
                   "--backend", "D3D12"]
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=3600)
        row = {"asset": slug, "command": command,
               "elapsed_seconds": time.perf_counter() - started,
               "status": "failed" if result.returncode else "scored",
               "stdout": result.stdout[-3000:], "stderr": result.stderr[-5000:]}
        if result.returncode:
            receipt["assets"] = [item for item in receipt["assets"]
                                 if item["asset"] != slug] + [row]
            write_json(receipt_path, receipt)
            raise RuntimeError(f"Scorer failed for {slug}; details saved in {receipt_path}")

        replay = json.loads(output.read_text(encoding="utf-8"))
        original_row = original_rows[slug]
        original_raw_path = ROOT / original_row["raw_receipt"]
        original = json.loads(original_raw_path.read_text(encoding="utf-8"))
        field_differences = {}
        for field in COMPARE_FIELDS:
            if field in original or field in replay:
                diffs = compare(original.get(field), replay.get(field), field)
                if diffs:
                    field_differences[field] = diffs[:30]
        same_environment = (replay.get("adapter") == original.get("adapter") and
                            replay.get("packages") == original.get("packages") and
                            replay.get("script_sha256") == original.get("script_sha256") and
                            replay.get("manifest_sha256") == manifest_sha)
        row.update({"status": "exact_match" if not field_differences and same_environment
                    else "mismatch", "raw_receipt": output.relative_to(ROOT).as_posix(),
                    "raw_sha256": digest(output), "original_raw_sha256": digest(original_raw_path),
                    "same_environment": same_environment,
                    "field_differences": field_differences})
        receipt["assets"] = [item for item in receipt["assets"]
                             if item["asset"] != slug] + [row]
        receipt["assets"].sort(key=lambda item: selected.index(item["asset"]))
        write_json(receipt_path, receipt)
        print(index, slug, row["status"], f"{row['elapsed_seconds']:.1f}s", flush=True)
        if row["status"] != "exact_match":
            raise RuntimeError(f"Scoring replay mismatch for {slug}; see {receipt_path}")

    receipt["status"] = "complete" if all(slug in completed or any(
        row["asset"] == slug and row["status"] == "exact_match" for row in receipt["assets"])
        for slug in selected) else "partial"
    receipt["exact_match_assets"] = sorted(row["asset"] for row in receipt["assets"]
                                           if row["status"] == "exact_match")
    write_json(receipt_path, receipt)
    print(receipt["status"], len(receipt["exact_match_assets"]), "assets", flush=True)


if __name__ == "__main__":
    main()
