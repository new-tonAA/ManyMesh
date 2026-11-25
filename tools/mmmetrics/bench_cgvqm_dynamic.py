#!/usr/bin/env python3
"""Score paired captured dynamic-LOD clips with the upstream CGVQM implementation."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "mmmetrics" / "run_cgvqm.py"


def bootstrap_mean(values, seed=20261122, count=20000):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(count, len(values)), replace=True).mean(axis=1)
    return {"mean": float(values.mean()),
            "ci95": [float(x) for x in np.quantile(samples, (0.025, 0.975))],
            "assetsAboveZero": int(np.count_nonzero(values > 0)),
            "assetsBelowZero": int(np.count_nonzero(values < 0)),
            "assetCount": int(len(values))}


def score_job(job, receipt_path, args):
    command = [sys.executable, str(RUNNER),
               "--cgvqm-root", str(args.cgvqm_root.resolve()),
               "--distorted", str(Path(job["distorted"]).resolve()),
               "--reference", str(Path(job["reference"]).resolve()),
               "--out", str(receipt_path.resolve()),
               "--model", args.model,
               "--device", "cpu",
               "--cpu-threads", str(args.cpu_threads),
               "--patch-pool", args.patch_pool,
               "--patch-scale", str(args.patch_scale),
               "--torch-home", str(args.torch_home.resolve())]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"CGVQM failed for {job['asset']}/{job['policy']}:\n"
                           f"{result.stdout}\n{result.stderr}")
    return json.loads(receipt_path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True,
                        help="Dynamic LOD receipt that contains lossless sequenceFiles")
    parser.add_argument("--cgvqm-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-markdown", type=Path)
    parser.add_argument("--path", type=int, required=True,
                        help="Camera path ID from the benchmark receipt")
    parser.add_argument("--asset", nargs="+",
                        help="Optional asset subset for a smoke run; default is every asset")
    parser.add_argument("--model", choices=("CGVQM-2", "CGVQM-5"), default="CGVQM-5")
    parser.add_argument("--cpu-threads", type=int, default=8)
    parser.add_argument("--patch-pool", choices=("max", "mean"), default="mean")
    parser.add_argument("--patch-scale", type=int, default=4)
    parser.add_argument("--torch-home", type=Path, default=Path("out/deps/torch_home"))
    args = parser.parse_args()
    if args.cpu_threads < 1 or args.patch_scale < 1:
        parser.error("--cpu-threads and --patch-scale must be positive")

    benchmark_path = args.benchmark.resolve()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if args.path not in benchmark["testPaths"]:
        parser.error(f"path {args.path} not in benchmark test paths {benchmark['testPaths']}")
    path_position = benchmark["testPaths"].index(args.path)
    if args.asset and any(asset not in benchmark["assets"] for asset in args.asset):
        parser.error("requested asset is absent from the benchmark receipt")
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = []
    for asset, data in benchmark["assets"].items():
        if args.asset and asset not in args.asset:
            continue
        ranker = data["calibratedRanker"]
        path_quality = data["temporalDifferenceQuality"][path_position]
        area_files = path_quality["area-hysteresis"].get("sequenceFiles")
        selected_key = f"{ranker}-hysteresis"
        selected_files = path_quality[selected_key].get("sequenceFiles")
        if area_files is None or selected_files is None:
            raise ValueError(f"Missing lossless sequence capture for {asset} path {args.path}")

        jobs = {"area": {"asset": asset, "policy": "area-hysteresis",
                          "distorted": str((ROOT / area_files["candidate"]["path"]).resolve()),
                          "reference": str((ROOT / area_files["reference"]["path"]).resolve())}}
        if selected_key != "area-hysteresis":
            jobs["selected"] = {
                "asset": asset, "policy": selected_key,
                "distorted": str((ROOT / selected_files["candidate"]["path"]).resolve()),
                "reference": str((ROOT / selected_files["reference"]["path"]).resolve())}
        receipts = {}
        for label, job in jobs.items():
            receipt_path = out_dir / asset / f"{label}.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            if receipt_path.exists():
                cached = json.loads(receipt_path.read_text(encoding="utf-8"))
                if (cached.get("distorted", {}).get("sha256") == hashlib.sha256(
                        Path(job["distorted"]).read_bytes()).hexdigest() and
                        cached.get("reference", {}).get("sha256") == hashlib.sha256(
                        Path(job["reference"]).read_bytes()).hexdigest() and
                        cached.get("metric") == args.model and
                        cached.get("patchPool") == args.patch_pool and
                        cached.get("patchScale") == args.patch_scale):
                    receipts[label] = cached
                    print(f"reuse {asset} {label}: {cached['score']:.4f}", flush=True)
                    continue
            receipts[label] = score_job(job, receipt_path, args)
            print(f"scored {asset} {label}: {receipts[label]['score']:.4f}", flush=True)
        area_score = receipts["area"]["score"]
        selected_score = receipts.get("selected", receipts["area"])["score"]
        assets.append({"asset": asset, "ranker": ranker,
                       "areaScore": area_score, "selectedScore": selected_score,
                       "deltaSelectedMinusArea": selected_score - area_score,
                       "areaReceipt": str((out_dir / asset / "area.json").relative_to(ROOT)),
                       "selectedReceipt": str((out_dir / asset /
                                               ("selected.json" if "selected" in receipts else "area.json"))
                                              .relative_to(ROOT))})

    report = {
        "metric": args.model,
        "benchmark": str(benchmark_path.relative_to(ROOT)),
        "benchmarkSha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        "path": args.path,
        "resolution": benchmark["size"],
        "frameCount": benchmark["framesPerPath"],
        "fps": benchmark.get("sequenceFps"),
        "renderer": {"adapter": benchmark.get("adapter"),
                     "wgpuVersion": benchmark.get("wgpuVersion")},
        "profileObjective": benchmark.get("profileObjective"),
        "patchPool": args.patch_pool,
        "patchScale": args.patch_scale,
        "cpuThreads": args.cpu_threads,
        "scoreDirection": "higher_is_better",
        "pairedAssetBootstrap": bootstrap_mean(
            [row["deltaSelectedMinusArea"] for row in assets]),
        "assets": assets,
        "interpretation": "Development screen on reused Khronos assets; not independent confirmation or a method novelty result.",
    }
    output_path = out_dir / "summary.json"
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.out_markdown is not None:
        ci = report["pairedAssetBootstrap"]["ci95"]
        width, height = report["resolution"]
        lines = [
            f"# {args.model} dynamic LOD sequence screen",
            "",
            "This is a research screen on reused development assets, not an independent confirmation or a SIGGRAPH result.",
            "",
            "## Protocol",
            "",
            f"- {len(assets)} Khronos glTF assets; camera path {args.path}; {width}x{height}; "
            f"{report['frameCount']} frames at {report['fps']} fps.",
            "- Each frame contains sixteen non-overlapping instances (four source meshes and twelve component meshes); "
            f"both policies use the same per-asset face budget. Rendering ran offscreen on "
            f"{report['renderer']['adapter'].get('device', 'unknown GPU')} / "
            f"{report['renderer']['adapter'].get('backend_type', 'unknown backend')} "
            f"with wgpu {report['renderer']['wgpuVersion'] or 'version not recorded'}.",
            f"- Compare each asset's cross-validated direction/scale ranker plus hysteresis against area ranking "
            "plus hysteresis, at the same face count. The ranker was fit without the held-out asset.",
            f"- The LOD profile objective is `{report['profileObjective']}`. Quality scoring uses `{args.model}`, "
            f"mean patch pooling, patch scale {args.patch_scale}, and CPU inference with {args.cpu_threads} threads.",
            "- The upstream model and calibration weights are used with OpenCV's FFmpeg decoder adapter. "
            "Videos are RGB grayscale renders encoded as lossless FFV1; frame count, dimensions, frame rate, "
            "and exact decoded pixels were checked before scoring.",
            "- Scores are paired within asset. The 95% percentile interval bootstraps assets, not frames.",
            "- Assets and component meshes are reused development data; the renderer is isolated and flat-shaded. "
            "This screen does not cover authored materials, user ratings, or mobile devices.",
            "",
            "## Results",
            "",
            "Higher CGVQM scores indicate higher predicted quality. Positive deltas favor the selected ranker.",
            "",
            "| Asset | Selected ranker | Area score | Selected score | Selected minus area |",
            "|---|---|---:|---:|---:|",
        ]
        for row in assets:
            lines.append(f"| {row['asset']} | {row['ranker']} | {row['areaScore']:.4f} | "
                         f"{row['selectedScore']:.4f} | {row['deltaSelectedMinusArea']:+.4f} |")
        lines.extend([
            "",
            f"Paired asset-bootstrap mean delta: **{report['pairedAssetBootstrap']['mean']:+.4f}** "
            f"(95% CI [{ci[0]:+.4f}, {ci[1]:+.4f}]); "
            f"{report['pairedAssetBootstrap']['assetsAboveZero']} assets favor the selected ranker and "
            f"{report['pairedAssetBootstrap']['assetsBelowZero']} favor area.",
            "",
            "## Limits",
            "",
            "CGVQM-5 is a published computer-graphics video metric, not a universal or ISO-standard score. "
            "This evaluation uses the upstream model and calibration but OpenCV FFmpeg decoding because PyAV "
            "is unavailable in this Python environment; absolute values should not be treated as a canonical "
            "reproduction of the paper's examples. Within-pair comparisons use identical decoding and settings.",
            "One held-out path per asset is scored here. The reused asset corpus, synthetic renderer, and single "
            "path do not establish general temporal perceptual quality. The profile formulation remains closed "
            "unless a distinct novelty claim and repeatable quality-cost gain emerge on fresh licensed assets.",
            "No user preference or mobile performance claim is measured.",
            "",
            f"Raw JSON receipt: `{output_path.relative_to(ROOT).as_posix()}`. Per-policy CGVQM receipts are in "
            f"`{out_dir.relative_to(ROOT).as_posix()}/<asset>/`.",
            "",
            "References: [CGVQM paper](https://doi.org/10.1111/cgf.70221), "
            "[official implementation](https://github.com/IntelLabs/cgvqm).",
            "",
        ])
        markdown_path = args.out_markdown.resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {markdown_path}", flush=True)
    print(f"wrote {output_path}", flush=True)


if __name__ == "__main__":
    main()
