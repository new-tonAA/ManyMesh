# Tiny image reconstruction on Thingi10K (2026-11-21)

## Question and setup

Can a small learned upsampler restore image detail lost when a mesh is simplified, on meshes that
were not present during training? This is the image-reconstruction half of the proposed mesh plus
super-resolution route. It does not output a mesh and does not establish novelty.

The 32-mesh corpus is split by Thing ID: 16 train, 8 validation, 8 test. For each mesh, a CPU
software rasterizer generated 12 grayscale directional-shading views. The low input is a native
96x96 render from the QEM mesh retaining 20% of the source faces. The target is the source mesh
rendered at 384x384 and box filtered to 192x192. The network receives the actual 96x96 input and
upsamples by 2. Training and validation contain 192 and 96 views respectively; test contains 96
views from eight held-out Things.

The candidate is the existing four-convolution `TinyUpsample`: 22,860 parameters, 32 channels,
one CPU thread, 1,500 iterations, 64x64 target patches, batch 8, learning rate 1e-3, edge-gradient
weight 0.1. The trainer retains the checkpoint with the best validation PSNR; that occurred at
iteration 300. Bicubic uses the same low raster and target. No test view was used for training or
validation selection.

A validation-only follow-up lowered the learning rate to 3e-4 and removed the edge-gradient term,
with the same 1,500-iteration cap. Its best validation PSNR was 26.61 dB at iteration 300, still
below bicubic at 26.96 dB; SSIM was 0.9321 versus 0.9391. This checkpoint was not evaluated on the
test set and was not selected for the reported held-out result.

## Quality result

| Split | Bicubic PSNR / SSIM | TinyUpsample PSNR / SSIM | Difference |
|---|---:|---:|---:|
| Validation | 26.96 dB / 0.9391 | 26.18 dB / 0.9336 | -0.78 dB / -0.0055 |
| Held-out test | 29.19 dB / 0.9530 | 27.89 dB / 0.9439 | -1.30 dB / -0.0091 |

On the eight test Things, the model improved median per-view PSNR on only two assets, by small
margins; the other six lost. This configuration therefore fails the cross-asset quality gate.
The result closes this exact small CNN/training recipe for this grayscale task, not other model
families or textured rendering.

Image-space mesh and appearance optimization is established by [Appearance-Driven Automatic 3D
Model Simplification (EGSR 2021)](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc),
and lightweight image super-resolution is a mature field. The experiment therefore asks only
whether this particular mesh-rendered training signal transfers across independent Thingiverse
assets and meets the laptop cost target; it does not claim a new reconstruction architecture.

## CPU cost

Using PyTorch 2.7.1+cpu, single-threaded, with 8 warmups and 50 timed calls on this machine:

| Input -> output | TinyUpsample median / p95 | Bicubic median / p95 | Relative median cost |
|---|---:|---:|---:|
| 96x96 -> 192x192 | 6.75 / 7.53 ms | 1.60 / 1.78 ms | 4.2x |
| 320x180 -> 640x360 | 43.05 / 54.12 ms | 10.55 / 12.71 ms | 4.1x |

The process used one CPU thread. During training, the observed Python process working set was about
470 MiB at one sample; this is not a recorded peak. The current model adds CPU time while reducing
quality, so it is not suitable for the proposed real-time path in this configuration.

## Reproduction

All meshes, generated images, results, and weights remain in ignored `out/thingi10k-metadata/`.
The package target under `out/geometry-refinement-pilot/deps` supplies NumPy 2.2.6, trimesh 5.2.1,
and fast-simplification 0.2.0; Numba, Pillow, and PyTorch come from the local Python environment.

```powershell
python tools/mmtrain/index_thingi10k_assets.py `
  out/thingi10k-metadata/meshes/download_manifest.json `
  --out out/thingi10k-metadata/asset-index/sources.json
$env:PYTHONPATH = (Resolve-Path out/geometry-refinement-pilot/deps).Path
$env:NUMBA_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmtrain/make_refinement_pairs.py `
  out/thingi10k-metadata/asset-index `
  --out out/thingi10k-metadata/pairs-96 `
  --views 12 --size 96
python tools/mmtrain/export_thingi_sr_pairs.py `
  out/thingi10k-metadata/pairs-96 `
  --out out/thingi10k-metadata/sr-pairs
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
python tools/mmtrain/train.py `
  --data out/thingi10k-metadata/sr-pairs/train `
  --val-data out/thingi10k-metadata/sr-pairs/validation `
  --model tiny_up --scale 2 --iterations 1500 --patch 64 --batch 8 `
  --channels 32 --gradient-weight 0.1 --no-error-map --seed 2027 `
  --out out/thingi10k-metadata/sr-results/thingi-tiny-up
python tools/mmtrain/train.py `
  --data out/thingi10k-metadata/sr-pairs/train `
  --val-data out/thingi10k-metadata/sr-pairs/validation `
  --model tiny_up --scale 2 --iterations 1500 --patch 64 --batch 8 `
  --channels 32 --lr 0.0003 --gradient-weight 0 --no-error-map --seed 2027 `
  --out out/thingi10k-metadata/sr-results/thingi-tiny-up-lr3e4-nograd
python tools/mmtrain/train.py `
  --data out/thingi10k-metadata/sr-pairs/train `
  --val-data out/thingi10k-metadata/sr-pairs/validation `
  --model bicubic --scale 2 --no-error-map `
  --out out/thingi10k-metadata/sr-results/bicubic-val.json
python tools/mmtrain/train.py `
  --data out/thingi10k-metadata/sr-pairs/train `
  --val-data out/thingi10k-metadata/sr-pairs/test `
  --model bicubic --scale 2 --no-error-map `
  --out out/thingi10k-metadata/sr-results/bicubic-test.json
python tools/mmtrain/train.py `
  --data out/thingi10k-metadata/sr-pairs/train `
  --val-data out/thingi10k-metadata/sr-pairs/test `
  --model tiny_up --scale 2 --no-error-map `
  --eval-only out/thingi10k-metadata/sr-results/thingi-tiny-up.pt `
  --out out/thingi10k-metadata/sr-results/tiny-test.json
python tools/mmtrain/bench_thingi_sr_inference.py `
  --checkpoint out/thingi10k-metadata/sr-results/thingi-tiny-up.pt `
  --input out/thingi10k-metadata/sr-pairs/test/lr_v0000.png `
  --out out/thingi10k-metadata/sr-results/runtime.json
```

Reproduction hashes:

- Image-pair manifest: `5bdab00b4523118e7682c47de4d69cdb6b1ed9ca17abbd2e64a89f6e23d69548`
- Model checkpoint: `49d9747f127be857029ba73ea6cd01ba3f3614179fb7b50c803dcb3e3833460f`
- Held-out test metrics: `244e22f4dfd71646e802c20dca7c7e0f327b5200629fe9c2ede83cebd54424a0`
- Runtime capture: `6ec9b1fdd32b63c438f0a901483998a8aa587d6f97b386adefa65e323db67d30`
- Validation-only lower-learning-rate run: `aca7db798de891103569843e70d2872969b92136a9b7c1995469ba78a17dbb6f`
