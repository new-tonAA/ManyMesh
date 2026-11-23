# 1080p GPU Image-Quality and MSAA Baseline

This fixed-view desktop diagnostic compares reduced geometry, 4x MSAA, and
half-resolution reconstruction. It is not a ManyMesh decoder result, a full
Filament frame measurement, or a mobile performance claim.

## Protocol

- Windows 11, Intel Iris Xe Graphics (driver 31.0.101.4502), D3D12 via
  `wgpu 0.32.0`; 1920 x 1080 output.
- Three assets are rendered as 16 instances in a 4 x 4 grid with one indexed
  instanced draw. The camera and grayscale directional shading are fixed;
  authored materials, textures, shadows, and motion are absent.
- The selected component cut retains about 20% of source faces. Source and cut
  triangle totals for each asset are recorded in the JSON receipt.
- Modes include source and reduced geometry at native resolution, 4x MSAA,
  and half-resolution rendering with linear or cubic 2x reconstruction.
- The shared quality reference is the full source mesh rendered at the same
  camera with 4x MSAA. The offscreen capture is linear-light `rgba8unorm`;
  grayscale captures are converted to 8-bit display-referred sRGB using the
  IEC 61966-2-1 transfer before computing PSNR and SSIM. GPU timings include
  rasterization and applicable resolve/reconstruction passes, not full frame
  time. Each mode has three rotated batches of 48 timestamp samples after eight
  warmups per batch. Tables show median and 95th percentile.

## Results

Each quality pair is PSNR in dB / SSIM against the shared reference. The source
4x MSAA row is the reference. Measurements and hashes are preserved in the
[machine-readable receipt](cluster_decoder_gpu_msaa_1080_20261122.json).

### StainedGlassLamp

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 0.580 / 2.893 | 29.754 / 0.989169 |
| Selected component cut, native | 0.318 / 0.319 | 25.258 / 0.965987 |
| Source, 4x MSAA | 1.417 / 1.440 | Reference |
| Selected component cut, 4x MSAA | 0.805 / 0.813 | 27.865 / 0.973785 |
| Source, half-resolution + linear 2x | 0.558 / 0.646 | 26.567 / 0.967843 |
| Source, half-resolution + cubic 2x | 0.724 / 1.130 | 26.677 / 0.969612 |
| Component cut, half-resolution + cubic 2x | 0.485 / 0.490 | 25.312 / 0.958097 |

### GlassVaseFlowers

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 0.354 / 1.354 | 29.162 / 0.985656 |
| Selected component cut, native | 0.195 / 0.204 | 22.661 / 0.960598 |
| Source, 4x MSAA | 0.819 / 1.890 | Reference |
| Selected component cut, 4x MSAA | 0.530 / 0.681 | 24.046 / 0.969951 |
| Source, half-resolution + linear 2x | 0.323 / 0.420 | 26.133 / 0.966435 |
| Source, half-resolution + cubic 2x | 0.634 / 0.640 | 26.506 / 0.968841 |
| Component cut, half-resolution + cubic 2x | 0.515 / 0.519 | 23.797 / 0.958629 |

### ToyCar

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 3.014 / 3.126 | 32.685 / 0.990573 |
| Selected component cut, native | 0.578 / 0.643 | 28.819 / 0.975562 |
| Source, 4x MSAA | 3.355 / 3.620 | Reference |
| Selected component cut, 4x MSAA | 0.956 / 1.211 | 30.914 / 0.981750 |
| Source, half-resolution + linear 2x | 3.142 / 3.994 | 29.521 / 0.976297 |
| Source, half-resolution + cubic 2x | 3.573 / 4.045 | 29.940 / 0.977606 |
| Component cut, half-resolution + cubic 2x | 0.876 / 1.146 | 28.799 / 0.968048 |

## Interpretation and limits

The 20%-face ToyCar cut with 4x MSAA reaches 30.914 dB / 0.981750 SSIM at
0.956 ms median GPU time. Full-source native rendering measures 32.685 dB /
0.990573 at 3.014 ms; full-source half-resolution linear reconstruction measures
29.521 dB / 0.976297 at 3.142 ms. In this one fixed view, the cut plus MSAA is
about 3.15x faster than source native and 1.77 dB lower in PSNR; against source
linear reconstruction it is about 3.29x faster and +1.39 dB. GlassVaseFlowers
favors full-source upscaling. The ranking is asset-dependent and does not
establish a general policy.

This screen covers three fixed cameras on one desktop integrated GPU, with
synthetic grayscale shading. It does not measure application CPU cost, power,
thermals, temporal stability, SMAA, FLIP, LPIPS, or user preference. The JSON
receipt records all timestamp samples, hashes, environment, and benchmark source
hash.

Reproduce from PowerShell with the cached dependencies:

```powershell
$gpuDeps = (Resolve-Path 'out\geometry-refinement-pilot\gpu-deps').Path
$geometryDeps = (Resolve-Path 'out\geometry-refinement-pilot\deps').Path
$imageDeps = (Resolve-Path 'out\image-quality-deps').Path
$env:PYTHONPATH = "$gpuDeps;$geometryDeps;$imageDeps"
python tools/mmtrain/bench_component_gpu.py `
  out/geometry-refinement-pilot/motion-meshes `
  --motion-reference out/geometry-refinement-pilot/motion-96.json `
  --asset StainedGlassLamp GlassVaseFlowers ToyCar `
  --size 1920x1080 --frames 48 --repeats 3 --grid 4 `
  --out out/geometry-refinement-pilot/wgpu-msaa-1080-grid4.json
```
