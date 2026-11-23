#!/usr/bin/env python3
"""Summarize a multi-asset offscreen MSAA/upscaling comparison."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np


def percentile_pair(row):
    return np.percentile(row["gpuMs"], [50, 95])


def paired_summary(assets, candidate, baseline, seed):
    names = sorted(assets)
    psnr = np.asarray([
        assets[name][candidate]["psnr_db_vs_source_msaa4"]
        - assets[name][baseline]["psnr_db_vs_source_msaa4"]
        for name in names
    ])
    ssim = np.asarray([
        assets[name][candidate]["ssim_vs_source_msaa4"]
        - assets[name][baseline]["ssim_vs_source_msaa4"]
        for name in names
    ])
    speed_ratio = np.asarray([
        np.median(assets[name][baseline]["gpuMs"])
        / np.median(assets[name][candidate]["gpuMs"])
        for name in names
    ])
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(names), size=(100_000, len(names)))
    psnr_interval = np.quantile(psnr[samples].mean(axis=1), [0.025, 0.975])
    ssim_interval = np.quantile(ssim[samples].mean(axis=1), [0.025, 0.975])
    both = (psnr > 0) & (ssim > 0)
    dominates = both & (speed_ratio > 1)
    return {
        "psnr_mean": float(psnr.mean()),
        "psnr_interval": psnr_interval.tolist(),
        "psnr_wins": int(np.count_nonzero(psnr > 0)),
        "ssim_mean": float(ssim.mean()),
        "ssim_interval": ssim_interval.tolist(),
        "ssim_wins": int(np.count_nonzero(ssim > 0)),
        "both_wins": int(np.count_nonzero(both)),
        "median_speed_ratio": float(np.median(speed_ratio)),
        "candidate_faster": int(np.count_nonzero(speed_ratio > 1)),
        "pareto_wins": int(np.count_nonzero(dominates)),
        "candidate_p50": float(np.median([
            np.median(assets[name][candidate]["gpuMs"]) for name in names
        ])),
        "baseline_p50": float(np.median([
            np.median(assets[name][baseline]["gpuMs"]) for name in names
        ])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261122)
    args = parser.parse_args()

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    assets = receipt["assets"]
    if len(assets) < 10:
        raise ValueError("The broad screen requires at least ten assets")
    if receipt["size"] != [1280, 720] or receipt["instances"] != 16:
        raise ValueError("Expected the frozen 1280x720, 16-instance screen")

    against_linear = paired_summary(
        assets, "parts-msaa4", "source-linear", args.seed
    )
    against_native = paired_summary(
        assets, "parts-msaa4", "source-native", args.seed
    )
    face_fractions = np.asarray([
        assets[name]["parts-native"]["faces"]
        / assets[name]["source-native"]["faces"]
        for name in assets
    ])
    provenance = receipt.get("assetProvenance", {})
    license_counts = Counter(
        item["license"] for item in provenance.values() if "license" in item
    )
    license_summary = ", ".join(
        f"{count} {license_id}" for license_id, count in sorted(license_counts.items())
    ) or "not recorded in the receipt"
    source_revision = next((
        item["source"].split("/Models/", 1)[0].rsplit("/", 1)[-1]
        for item in provenance.values() if "/Models/" in item.get("source", "")
    ), "not recorded in the receipt")

    rows = []
    for name in sorted(assets):
        modes = assets[name]
        source_faces = modes["source-native"]["faces"]
        cut_faces = modes["parts-native"]["faces"]
        upscale = modes["source-linear"]
        cut_msaa = modes["parts-msaa4"]
        up_p50, up_p95 = percentile_pair(upscale)
        msaa_p50, msaa_p95 = percentile_pair(cut_msaa)
        speed_ratio = up_p50 / msaa_p50
        psnr_delta = (cut_msaa["psnr_db_vs_source_msaa4"]
                      - upscale["psnr_db_vs_source_msaa4"])
        ssim_delta = (cut_msaa["ssim_vs_source_msaa4"]
                      - upscale["ssim_vs_source_msaa4"])
        pareto = speed_ratio > 1 and psnr_delta > 0 and ssim_delta > 0
        rows.append(
            f"| {name} | {source_faces:,} / {cut_faces:,} "
            f"({cut_faces / source_faces:.1%}) | "
            f"{up_p50:.3f} / {up_p95:.3f}; "
            f"{upscale['psnr_db_vs_source_msaa4']:.2f} / "
            f"{upscale['ssim_vs_source_msaa4']:.4f} | "
            f"{msaa_p50:.3f} / {msaa_p95:.3f}; "
            f"{cut_msaa['psnr_db_vs_source_msaa4']:.2f} / "
            f"{cut_msaa['ssim_vs_source_msaa4']:.4f} | "
            f"{speed_ratio:.2f}x | "
            f"{psnr_delta:+.2f} / {ssim_delta:+.4f} | "
            f"{'Yes' if pareto else 'No'} |"
        )

    def summary_line(label, summary):
        return (
            f"| {label} | {summary['candidate_p50']:.3f} / "
            f"{summary['baseline_p50']:.3f} | "
            f"{summary['psnr_mean']:+.2f} "
            f"[{summary['psnr_interval'][0]:+.2f}, "
            f"{summary['psnr_interval'][1]:+.2f}] "
            f"({summary['psnr_wins']}/{len(assets)} assets) | "
            f"{summary['ssim_mean']:+.5f} "
            f"[{summary['ssim_interval'][0]:+.5f}, "
            f"{summary['ssim_interval'][1]:+.5f}] "
            f"({summary['ssim_wins']}/{len(assets)} assets) | "
            f"{summary['median_speed_ratio']:.2f}x "
            f"({summary['candidate_faster']}/{len(assets)} faster) | "
            f"{summary['pareto_wins']}/{len(assets)} |"
        )

    report = f"""# Multi-Asset GPU Image-Quality and MSAA Screen

This exploratory fixed-view comparison broadens the earlier three-asset GPU
diagnostic to all {len(assets)} available Khronos glTF Sample Assets in the local
motion pilot. It is an AA/upscaling baseline screen, not a learned-decoder result
or a general performance claim.

## Protocol

- Windows 11, Intel Iris Xe Graphics, driver 31.0.101.4502, D3D12 through
  `wgpu 0.32.0`; 1280 x 720 output.
- Each asset is rendered as 16 identical instances in a 4 x 4 grid in one
  indexed instanced draw. One fixed perspective camera and grayscale directional
  light are used. Materials, textures, shadows, animation, and camera motion are
  absent.
- The source meshes are pinned to Khronos glTF Sample Assets revision
  `{source_revision}`; licenses in the receipt are {license_summary}.
- Geometry modes use the frozen full source and equal-face-count `qem`, `whole`,
  and `parts` exports. The `parts` export is the per-asset component selection
  from an earlier calibration run. This report does not train or validate a
  general selection policy; treat that mesh as a calibrated candidate, not a
  deployable algorithm. Cut ratios range from {face_fractions.min():.1%} to
  {face_fractions.max():.1%} of source faces (median {np.median(face_fractions):.1%}).
- The candidate comparison is the `parts` cut at native resolution with 4x MSAA
  versus the full source at half width and height followed by linear 2x
  reconstruction. Other modes remain in the receipt. Every quality value uses
  the full source rendered at the same camera with 4x MSAA as reference.
- Captures are linear-light `rgba8unorm`; grayscale images are converted to
  display-referred 8-bit sRGB using IEC 61966-2-1 before PSNR and SSIM. Timing
  is GPU raster plus resolve/reconstruction, not full frame time. Each mode has
  144 timestamp samples (three batches of 48) after eight warmups per batch.
  Tables show p50/p95. Quality comes from one fixed capture per asset and mode.
- PSNR uses image-wide mean squared error over the 8-bit sRGB grayscale values.
  SSIM uses `skimage.metrics.structural_similarity` 0.25.2 with `data_range=255`
  and its default 7 x 7 local window and uniform weighting.

## Paired results

The ratio is full-source baseline p50 divided by cut-plus-MSAA p50; values above
1 mean the cut-plus-MSAA mode is faster. PSNR and SSIM deltas are against the
same full-source MSAA reference.

| Asset | Source / cut faces (cut ratio) | Full source, linear 2x: p50/p95 ms; PSNR/SSIM | Parts cut + 4x MSAA: p50/p95 ms; PSNR/SSIM | Speed ratio | Delta PSNR / SSIM | Faster and better on both? |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## Asset-level summary

Intervals are 95% percentile bootstrap intervals for the mean paired asset
difference, with 100,000 resamples and seed `{args.seed}`. Assets are the sampling
unit; frames within a timing batch are not treated as independent models. This
curated 13-asset set is not a random sample of all production meshes, so the
intervals describe this screen and do not establish population generalization.

| Cut + MSAA versus | Median GPU p50, candidate / baseline (ms) | Mean PSNR delta, 95% interval (wins) | Mean SSIM delta, 95% interval (wins) | Median speed ratio (faster assets) | Faster and better on both |
|---|---:|---:|---:|---:|---:|
{summary_line('full-source linear 2x', against_linear)}
{summary_line('full-source native', against_native)}

Against the full-source linear 2x baseline, the calibrated cut plus MSAA has
higher mean PSNR and SSIM on this set, but is faster on only
{against_linear['candidate_faster']}/{len(assets)} assets and faster while improving
both metrics on {against_linear['pareto_wins']}/{len(assets)}. Thus the quality
advantage does not translate into a broad equal-cost win. Asset complexity changes
the timing ranking substantially. Against source-native rendering, the SSIM
interval includes zero.

## Scope and reproduction

These results do not include FLIP, LPIPS, surface distance, temporal flicker,
authored materials, application CPU cost, power, thermals, SMAA, or mobile hardware.
The frozen source/cut meshes and capture hashes are recorded in the
[machine-readable receipt](cluster_decoder_gpu_msaa_720_13assets_20261122.json).
The benchmark source hash and environment are also recorded there. The analysis
script is [summarize_gpu_msaa_screen.py](summarize_gpu_msaa_screen.py).

Reproduce the GPU run from PowerShell with the cached dependencies:

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
$gpuDeps = (Resolve-Path 'out\\geometry-refinement-pilot\\gpu-deps').Path
$geometryDeps = (Resolve-Path 'out\\geometry-refinement-pilot\\deps').Path
$imageDeps = (Resolve-Path 'out\\image-quality-deps').Path
$env:PYTHONPATH = "$gpuDeps;$geometryDeps;$imageDeps"
python tools/mmtrain/probe_component_motion.py `
  "$pilotRoot/assets" "$pilotRoot/holdout-assets" `
  --whole-reference "$pilotRoot/qem-pool-control-96.json" `
  --component-reference "$pilotRoot/components-selected-96.json" `
  --mesh-out "$pilotRoot/motion-meshes" --out "$pilotRoot/motion-96.json"
python tools/mmtrain/bench_component_gpu.py `
  "$pilotRoot/motion-meshes" `
  --motion-reference "$pilotRoot/motion-96.json" `
  --asset {' '.join(sorted(assets))} `
  --size 1280x720 --frames 48 --repeats 3 --grid 4 `
  --out out/geometry-refinement-pilot/wgpu-msaa-720-grid4-13assets.json
python tools/mmtrain/summarize_gpu_msaa_screen.py `
  out/geometry-refinement-pilot/wgpu-msaa-720-grid4-13assets.json `
  --out tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md
```
"""

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    print("parts-msaa4 versus source-linear:", against_linear)
    print("parts-msaa4 versus source-native:", against_native)


if __name__ == "__main__":
    main()
