#!/usr/bin/env python3
"""Score the moving mixed-scene LOD clips with upstream CGVQM-5."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "mmmetrics" / "run_cgvqm.py"
POLICIES = ("group-area", "instance-area", "instance-matched")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bootstrap(values, seed, samples=20000):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95_percentile": [float(x) for x in np.quantile(means, (0.025, 0.975))],
        "positive_scene_count": int(np.count_nonzero(values > 0)),
        "negative_scene_count": int(np.count_nonzero(values < 0)),
        "scene_count": int(len(values)),
        "paired_differences": values.tolist(),
    }


def score_one(args, scene, policy, video, reference):
    if not video.is_file() or not reference.is_file():
        raise FileNotFoundError(video if not video.is_file() else reference)
    output = args.out_dir / scene / f"{policy}.json"
    command = [
        sys.executable, str(RUNNER),
        "--cgvqm-root", str(args.cgvqm_root.resolve()),
        "--distorted", str(video.resolve()),
        "--reference", str(reference.resolve()),
        "--out", str(output.resolve()),
        "--model", "CGVQM-5", "--device", "cpu",
        "--cpu-threads", str(args.cpu_threads),
        "--patch-pool", "mean", "--patch-scale", "4",
        "--torch-home", str(args.torch_home.resolve()),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"CGVQM failed for {scene}/{policy}:\n{result.stdout}\n{result.stderr}")
    report = json.loads(output.read_text(encoding="utf-8"))
    report["distorted"]["path"] = video.resolve().relative_to(ROOT).as_posix()
    report["distorted"]["sha256"] = sha256(video)
    report["reference"]["path"] = reference.resolve().relative_to(ROOT).as_posix()
    report["reference"]["sha256"] = sha256(reference)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--cgvqm-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--torch-home", type=Path, default=Path("out/deps/torch_home"))
    parser.add_argument("--cpu-threads", type=int, default=8)
    args = parser.parse_args()
    if args.cpu_threads < 1:
        parser.error("--cpu-threads must be positive")

    benchmark_path = args.benchmark.resolve()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    scenes = {}
    for scene, scene_data in benchmark["scenes"].items():
        reference = ROOT / scene_data["views"]["source"]["quality_sequence"]["reference_sequence"]["path"]
        scenes[scene] = {}
        for policy in POLICIES:
            sequence = scene_data["views"][policy]["quality_sequence"]
            if sequence["reference_rgb_sha256"] != scene_data["views"]["source"]["quality_sequence"]["reference_rgb_sha256"]:
                raise RuntimeError(f"Reference RGB hash differs for {scene}/{policy}")
            video = ROOT / sequence["candidate_sequence"]["path"]
            scenes[scene][policy] = score_one(args, scene, policy, video, reference)

    comparisons = {}
    for policy in ("instance-area", "instance-matched"):
        differences = [scenes[name][policy]["score"] - scenes[name]["group-area"]["score"]
                       for name in scenes]
        comparisons[f"{policy}_minus_group_area"] = bootstrap(differences, 20261123)
    report = {
        "metric": "CGVQM-5",
        "direction": "higher_is_better",
        "benchmark": benchmark_path.relative_to(ROOT).as_posix(),
        "benchmark_sha256": sha256(benchmark_path),
        "scene_unit": "three reused synthetic mixed scenes; bootstrap unit is scene, not frame",
        "camera_frames_per_scene": benchmark["frames"],
        "fps": benchmark["fps"],
        "device": "CPU",
        "decoder_note": "OpenCV FFmpeg RGB24 decoder; upstream PyAV reader replaced",
        "patch_pool": "mean",
        "patch_scale": 4,
        "scenes": scenes,
        "paired_comparisons": comparisons,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparisons, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
