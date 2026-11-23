# Multi-Asset GPU Image-Quality and MSAA Screen

This exploratory fixed-view comparison broadens the earlier three-asset GPU
diagnostic to all 13 available Khronos glTF Sample Assets in the local
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
  `f0920f5b32d172a30efe3f9257e965918831e6ea`; licenses in the receipt are 3 CC-BY-4.0, 10 CC0-1.0.
- Geometry modes use the frozen full source and equal-face-count `qem`, `whole`,
  and `parts` exports. The `parts` export is the per-asset component selection
  from an earlier calibration run. This report does not train or validate a
  general selection policy; treat that mesh as a calibrated candidate, not a
  deployable algorithm. Cut ratios range from 19.8% to
  30.6% of source faces (median 20.0%).
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
| AntiqueCamera | 20,053 / 4,011 (20.0%) | 0.371 / 0.392; 25.97 / 0.9539 | 0.419 / 0.441; 32.91 / 0.9874 | 0.89x | +6.94 / +0.0335 | No |
| Avocado | 682 / 135 (19.8%) | 0.213 / 0.218; 29.79 / 0.9784 | 0.356 / 0.359; 29.15 / 0.9750 | 0.60x | -0.64 / -0.0034 | No |
| BarramundiFish | 3,864 / 772 (20.0%) | 0.182 / 0.185; 31.32 / 0.9874 | 0.248 / 0.249; 38.52 / 0.9963 | 0.74x | +7.20 / +0.0089 | No |
| CesiumMilkTruck | 3,624 / 778 (21.5%) | 0.168 / 0.184; 29.32 / 0.9642 | 0.279 / 0.313; 29.42 / 0.9754 | 0.60x | +0.10 / +0.0112 | No |
| FlightHelmet | 94,722 / 18,943 (20.0%) | 1.109 / 1.113; 27.28 / 0.9568 | 0.783 / 0.793; 33.43 / 0.9818 | 1.42x | +6.14 / +0.0250 | Yes |
| GlassVaseFlowers | 14,036 / 2,806 (20.0%) | 0.285 / 0.295; 24.88 / 0.9576 | 0.344 / 0.358; 24.34 / 0.9710 | 0.83x | -0.53 / +0.0134 | No |
| IridescenceLamp | 18,866 / 3,772 (20.0%) | 0.322 / 0.335; 29.91 / 0.9808 | 0.424 / 0.458; 37.59 / 0.9901 | 0.76x | +7.68 / +0.0093 | No |
| Lantern | 5,394 / 1,650 (30.6%) | 0.227 / 0.229; 27.51 / 0.9720 | 0.289 / 0.292; 34.32 / 0.9956 | 0.79x | +6.82 / +0.0236 | No |
| SheenChair | 39,936 / 7,987 (20.0%) | 0.523 / 0.528; 26.20 / 0.9663 | 0.414 / 0.442; 39.75 / 0.9962 | 1.26x | +13.55 / +0.0300 | Yes |
| SheenCloth | 115,200 / 23,039 (20.0%) | 1.328 / 1.475; 28.48 / 0.9735 | 0.588 / 0.650; 41.50 / 0.9977 | 2.26x | +13.02 / +0.0242 | Yes |
| StainedGlassLamp | 35,132 / 7,026 (20.0%) | 0.472 / 0.476; 25.07 / 0.9589 | 0.538 / 0.544; 27.92 / 0.9768 | 0.88x | +2.85 / +0.0179 | No |
| ToyCar | 108,936 / 21,787 (20.0%) | 3.164 / 3.303; 27.83 / 0.9683 | 0.758 / 0.763; 31.12 / 0.9833 | 4.17x | +3.29 / +0.0150 | Yes |
| WaterBottle | 4,510 / 901 (20.0%) | 0.166 / 0.187; 30.37 / 0.9757 | 0.297 / 0.333; 37.53 / 0.9867 | 0.56x | +7.16 / +0.0110 | No |

## Asset-level summary

Intervals are 95% percentile bootstrap intervals for the mean paired asset
difference, with 100,000 resamples and seed `20261122`. Assets are the sampling
unit; frames within a timing batch are not treated as independent models. This
curated 13-asset set is not a random sample of all production meshes, so the
intervals describe this screen and do not establish population generalization.

| Cut + MSAA versus | Median GPU p50, candidate / baseline (ms) | Mean PSNR delta, 95% interval (wins) | Mean SSIM delta, 95% interval (wins) | Median speed ratio (faster assets) | Faster and better on both |
|---|---:|---:|---:|---:|---:|
| full-source linear 2x | 0.414 / 0.322 | +5.66 [+3.31, +8.08] (11/13 assets) | +0.01689 [+0.01157, +0.02210] (12/13 assets) | 0.83x (4/13 faster) | 4/13 |
| full-source native | 0.414 / 0.292 | +2.27 [+0.14, +4.41] (10/13 assets) | -0.00228 [-0.00650, +0.00173] (5/13 assets) | 0.70x (4/13 faster) | 2/13 |

Against the full-source linear 2x baseline, the calibrated cut plus MSAA has
higher mean PSNR and SSIM on this set, but is faster on only
4/13 assets and faster while improving
both metrics on 4/13. Thus the quality
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
$gpuDeps = (Resolve-Path 'out\geometry-refinement-pilot\gpu-deps').Path
$geometryDeps = (Resolve-Path 'out\geometry-refinement-pilot\deps').Path
$imageDeps = (Resolve-Path 'out\image-quality-deps').Path
$env:PYTHONPATH = "$gpuDeps;$geometryDeps;$imageDeps"
python tools/mmtrain/probe_component_motion.py `
  "$pilotRoot/assets" "$pilotRoot/holdout-assets" `
  --whole-reference "$pilotRoot/qem-pool-control-96.json" `
  --component-reference "$pilotRoot/components-selected-96.json" `
  --mesh-out "$pilotRoot/motion-meshes" --out "$pilotRoot/motion-96.json"
python tools/mmtrain/bench_component_gpu.py `
  "$pilotRoot/motion-meshes" `
  --motion-reference "$pilotRoot/motion-96.json" `
  --asset AntiqueCamera Avocado BarramundiFish CesiumMilkTruck FlightHelmet GlassVaseFlowers IridescenceLamp Lantern SheenChair SheenCloth StainedGlassLamp ToyCar WaterBottle `
  --size 1280x720 --frames 48 --repeats 3 --grid 4 `
  --out out/geometry-refinement-pilot/wgpu-msaa-720-grid4-13assets.json
python tools/mmtrain/summarize_gpu_msaa_screen.py `
  out/geometry-refinement-pilot/wgpu-msaa-720-grid4-13assets.json `
  --out tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md
```
