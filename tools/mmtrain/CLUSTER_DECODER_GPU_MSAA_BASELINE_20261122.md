# 720p GPU Image-Quality and MSAA Baseline

This fixed-view desktop diagnostic compares reduced geometry, 4x MSAA, and
half-resolution reconstruction. It is not a ManyMesh decoder result, a full
Filament frame measurement, or a mobile performance claim.

## Protocol

- Windows 11, Intel Iris Xe Graphics (driver 31.0.101.4502), D3D12 via
  `wgpu 0.32.0`; 1280 x 720 output.
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
[machine-readable receipt](cluster_decoder_gpu_msaa_20261122.json).

### StainedGlassLamp

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 0.510 / 1.413 | 27.691 / 0.984184 |
| Selected component cut, native | 0.262 / 0.328 | 24.828 / 0.965493 |
| Source, 4x MSAA | 1.146 / 1.246 | Reference |
| Selected component cut, 4x MSAA | 0.637 / 0.639 | 27.920 / 0.976794 |
| Source, half-resolution + linear 2x | 0.564 / 0.565 | 25.070 / 0.958909 |
| Source, half-resolution + cubic 2x | 0.653 / 0.654 | 25.035 / 0.960704 |
| Component cut, half-resolution + cubic 2x | 0.314 / 0.316 | 24.462 / 0.953132 |

### GlassVaseFlowers

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 0.221 / 0.950 | 27.481 / 0.981314 |
| Selected component cut, native | 0.118 / 0.140 | 22.395 / 0.956614 |
| Source, 4x MSAA | 0.588 / 0.690 | Reference |
| Selected component cut, 4x MSAA | 0.343 / 0.345 | 24.344 / 0.971021 |
| Source, half-resolution + linear 2x | 0.282 / 0.284 | 24.875 / 0.957626 |
| Source, half-resolution + cubic 2x | 0.369 / 0.400 | 25.193 / 0.960492 |
| Component cut, half-resolution + cubic 2x | 0.244 / 0.246 | 23.943 / 0.955894 |

### ToyCar

| Mode | GPU p50 / p95 (ms) | PSNR / SSIM |
|---|---:|---:|
| Source, native | 3.043 / 3.105 | 30.718 / 0.986671 |
| Selected component cut, native | 0.569 / 0.571 | 28.053 / 0.973984 |
| Source, 4x MSAA | 3.143 / 3.328 | Reference |
| Selected component cut, 4x MSAA | 0.732 / 0.776 | 31.120 / 0.983302 |
| Source, half-resolution + linear 2x | 3.050 / 3.170 | 27.825 / 0.968288 |
| Source, half-resolution + cubic 2x | 3.129 / 3.241 | 28.247 / 0.970410 |
| Component cut, half-resolution + cubic 2x | 0.700 / 0.709 | 27.825 / 0.963427 |

## Interpretation and limits

Results vary by asset and metric; neither the selected cut nor upscaling wins
universally. The ToyCar scene contains 1,742,976 source triangles across its 16
instances. See the 1080p report for the corresponding high-resolution comparison
when this is the 720p report.

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
  --size 1280x720 --frames 48 --repeats 3 --grid 4 `
  --out out/geometry-refinement-pilot/wgpu-msaa-720-grid4.json
```
