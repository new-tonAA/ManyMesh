# Cluster Decoder Latent-Scale Probe

Date: 2026-11-22. Validation-only exploratory diagnostic of the frozen rank-8 fixed-topology polynomial residual control. The latent scale is an oracle variable; no scale predictor is proposed.

## Protocol

- 12 orthographic views per prepared asset, 256 x 256, 4 raster samples per pixel; grayscale flat shading.
- Metrics: PSNR, canonical SSIM, LDR-FLIP, SqueezeNet LPIPS, silhouette XOR, and coverage MAE. Confidence intervals resample assets, not views.
- Fixed mesh and face count across scales. Alpha 0 is the exact base mesh identity control. Test split was not loaded.
- Scale selection per asset uses the same validation renders being scored and is reported only as an oracle upper bound.

## Per-asset results

| Asset | Zero identity | Alpha 0 PSNR | Best alpha (oracle) | Best PSNR | Nonzero scales decoded |
|---:|:---:|---:|---:|---:|---:|
| 90431 | True | 19.402 dB | 0 | 19.402 dB | 4/4 |
| 263198 | True | 28.612 dB | 0 | 28.612 dB | 4/4 |
| 44710 | True | 32.467 dB | 0 | 32.467 dB | 4/4 |
| 191968 | None | — | — | — | — |
| 383021 | True | 42.836 dB | 0 | 42.836 dB | 4/4 |
| 100894 | True | 30.531 dB | 0 | 30.531 dB | 0/4 |
| 257594 | None | — | — | — | — |
| 94990 | None | — | — | — | — |

## Paired changes from alpha 0

Negative FLIP/LPIPS and positive PSNR/SSIM are favorable. The 95% intervals are asset bootstrap intervals.

| Alpha | Paired assets | PSNR dB | SSIM | FLIP | LPIPS | Silhouette XOR | Coverage MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | 4 | -0.05789 [-0.08749, -0.02829] | -0.00032 [-0.00048, -0.00011] | +0.00061 [+0.00014, +0.00108] | +0.00028 [+0.00009, +0.00048] | +0.00007 [+0.00002, +0.00012] | +0.00008 [+0.00003, +0.00013] |
| 0.5 | 4 | -0.11249 [-0.18750, -0.03748] | -0.00065 [-0.00105, -0.00020] | +0.00104 [+0.00028, +0.00180] | +0.00043 [+0.00013, +0.00071] | +0.00015 [+0.00004, +0.00024] | +0.00015 [+0.00005, +0.00024] |
| 0.75 | 4 | -0.22533 [-0.38443, -0.06622] | -0.00122 [-0.00180, -0.00047] | +0.00151 [+0.00046, +0.00257] | +0.00078 [+0.00025, +0.00136] | +0.00026 [+0.00010, +0.00040] | +0.00025 [+0.00009, +0.00038] |
| 1 | 4 | -0.36403 [-0.62410, -0.10395] | -0.00198 [-0.00299, -0.00070] | +0.00196 [+0.00065, +0.00327] | +0.00090 [+0.00021, +0.00172] | +0.00042 [+0.00014, +0.00068] | +0.00037 [+0.00015, +0.00057] |

## Result and limits

The scale sweep is a diagnostic, not an independent model comparison. Decoder rejects remain counted; the 100894 asset rejected every nonzero scale under the local topology/offset checks. Per-asset oracle gains cannot support a runtime policy or a generalization claim. Even if one global scale helps this validation split, it must be frozen and evaluated once on an untouched, licensed confirmation set before further investment.

PSNR, SSIM, FLIP, and LPIPS are complementary image metrics, not a universal perceptual-quality score. This geometry-only grayscale probe does not assess materials, animation, temporal stability, runtime rendering, mobile hardware, or user preference.

## Reproduction

The validation manifest and frozen rank-8 model must already exist at the paths below; the manifest and model hashes are recorded in the compact receipt. The command opens validation rows only.

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/image-quality-deps').Path + ';' + (Resolve-Path 'out/geometry-refinement-pilot/deps').Path
$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmtrain/probe_cluster_decoder_scale.py `
  --pairs out/cluster-decoder-pairs/validation/manifest.json `
  --fit out/cluster-decoder-fit/rank8 `
  --out out/cluster-decoder-scale-oracle/rank8 `
  --views 12 --size 256 --samples 2 `
  --summary-json tools/mmtrain/cluster_decoder_scale_oracle_20261122.json `
  --summary-md tools/mmtrain/CLUSTER_DECODER_SCALE_PROBE_20261122.md
```

Full per-view data are in the ignored `out/cluster-decoder-scale-oracle/rank8/report.json`. The compact [machine-readable summary](cluster_decoder_scale_oracle_20261122.json) records model, input, and renderer hashes.
