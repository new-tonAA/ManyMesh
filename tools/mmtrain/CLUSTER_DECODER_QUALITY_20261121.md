# Cluster residual decoder: multi-asset quality screen

Date: 2026-11-21. Status: **negative result for the rank-8 linear subspace control**.
This is a geometry/render diagnostic, not a neural model, production renderer,
final test evaluation, or SIGGRAPH contribution.

## Corpus, fitting, and failures

The existing Thingi10K development splits supply 16 training and 8 validation Things.
No test geometry is loaded. QEM requests 30% retention with preserve_border enabled;
coarse output must pass the prototype's edge/duplicate/degeneracy checks and preserve
source boundary positions/edges before labels are generated. Partition size is at
most 128 faces. All preparation failures remain in the denominator:

| Split | Attempted | Prepared | QEM topology failures | Query-work cap failures |
|---|---:|---:|---:|---:|
| Train | 16 | 9 | 5 | 2 |
| Validation | 8 | 5 | 3 | 0 |

Training failures 59494/84030/148292 have duplicate geometric faces; 53581/96074
have nonmanifold/inconsistent edges. Rechecks identify coarse-output validation as
the failing call. 97859/741525 exceed 80 million centroid-radius checks. Validation
191968/257594 have duplicate coarse faces; 94990 has a degenerate coarse face.
No source is silently repaired or replaced.

Nearest-surface labels project onto reference triangles after conservative centroid
ball tests, capped at 20 million exact triangle evaluations and 80 million radius
checks per asset. Adding individual triangle radii preserves all arrays exactly on
the seven previously prepared assets and permits two additional training assets.
This is floating-point geometric computation, not an interval certificate.

Fit per-cluster polynomial coefficients, then learn a shared uncentered rank-8 SVD
basis from training coefficients with equal asset weighting. Per-asset encoding
uses reference residuals and ridge 1e-5. Each fixed/refinement model file is 1,488
bytes. Refinement selects the largest source-centroid residuals offline for 10% of
base faces and splits each selected face into three. It is a source-aware encoder,
not a runtime refinement policy. Direct float32 offsets use the same query positions,
selected faces, offset cap, and boundary/local-flip checks.

The shared weights are frozen before validation encoding. Optimizing a validation
asset's transmitted latent is compression encoding, not training shared weights.
Fixed controls decode 7/9 prepared training assets and 4/5 validation; refinement
decodes 5/9 and 3/5. Failures are retained rather than replaced by identity output.
The direct control also rejects outputs. Global intersections, vertex-link manifoldness,
and authored attributes remain unchecked, so successful local audits are insufficient
for the full topology gate.

## Image protocol and standard metrics

All 14 prepared assets render 12 deterministic orthographic views, yielding 168
reference frames and 612 candidate/control frames. Resolution is 256x256 with 2x2
box-filtered raster samples per output pixel, shared framing, light, exposure, and
background. Shading is grayscale flat-normal Lambert-like illumination; images are
converted from linear values to 8-bit sRGB. This is not textured/PBR/Filament evidence.
Masks come from raster depth rather than black-pixel thresholds. Centroid-only
retriangulation is tested to preserve both images and coverage.

- PSNR measures sRGB pixel MSE; per-asset PSNR pools the 12 view MSEs before log conversion.
- SSIM uses Gaussian sigma 1.5 and population covariance through scikit-image.
- [Official LDR-FLIP](https://github.com/NVlabs/flip), version 1.7, uses 67 pixels
  per degree and sRGB input. Lower error is better.
- [Official calibrated LPIPS](https://github.com/richzhang/PerceptualSimilarity),
  package 0.1.4, metric version 0.1/SqueezeNet, uses pretrained weights and RGB [-1,1].
  Lower distance is better. It is not interchangeable with AlexNet LPIPS values.
- Silhouette XOR and fractional coverage MAE measure projected geometry separately.
  Foreground-only PSNR is also retained per view to expose background dilution.

Identity/corruption controls check all metric backends, and 2,000 bootstrap resamples
pair **assets**, not correlated views. These small, conditioned development samples
do not establish population-level perceptual effects or replace user studies.

## Fixed topology versus equal-face QEM

Means below pair only assets with valid decoded output and their own QEM baselines;
do not compare different paired subsets directly. Every reference is the original
high-detail mesh under identical rendering conditions.

| Split / paired assets | Method | PSNR up | SSIM up | FLIP down | LPIPS down |
|---|---|---:|---:|---:|---:|
| Train / 7 | QEM | 33.4533 | 0.969319 | 0.021728 | 0.028600 |
| Train / 7 | Rank-8 decoder | 33.2775 | 0.968793 | 0.022258 | 0.028747 |
| Validation / 4 | QEM | 30.8292 | 0.957592 | 0.026165 | 0.023881 |
| Validation / 4 | Rank-8 decoder | 30.4651 | 0.955616 | 0.028124 | 0.024781 |

Validation candidate-minus-QEM mean PSNR delta is -0.3640 dB, exploratory paired
bootstrap interval [-0.6241,-0.1040]. FLIP delta is +0.001959,
interval [+0.000651,+0.003267]; all four paired assets worsen on FLIP. LPIPS delta
is +0.000900, interval [+0.000211,+0.001716]. Silhouette XOR rises from 0.8502% to
0.8922% of pixels. Thus lower training residual-label SSE does not translate into
better rendered quality, even before charging load cost/sidecar bytes.

Refinement also fails to establish a gain. On three valid validation assets it
changes QEM PSNR 34.6383->34.5844 and FLIP 0.011926->0.012519 while adding faces.
This comparison is **not equal-face**; a proper refined-budget QEM/Corner baseline
is still required before any benefit could be claimed. Only two validation assets
permit paired refinement/direct comparison, with no reliable advantage established.
The complete per-view report also includes direct-offset controls and failures.

## Artifacts and reproduction

[The retained receipt](cluster_decoder_quality_20261121.json) stores versions,
hashes, all-asset results, failures, and asset-paired summaries. Images stay under
ignored out/ until their source/material attribution is checked for publication:

- `out/cluster-decoder-quality/rank8/all-assets.png`: all 14 prepared assets,
  reference/QEM/fixed/refinement at view zero, with rejected columns labeled.
- `out/cluster-decoder-quality/rank8/validation-errors.png`: four paired validation
  assets, view zero, reference/QEM/fixed and official FLIP error maps. Gallery
  generation verifies that saved images reproduce recorded FLIP means.
- `report.json` and `summary.json` in that folder: full per-view and paired results.

Use the existing isolated geometry dependencies (NumPy 2.2.6, SciPy 1.15.3,
fast-simplification 0.2.0) and install official metric packages into a workspace target:

```powershell
python -m pip install --target out/image-quality-deps --no-deps flip-evaluator==1.7 lpips==0.1.4
$env:PYTHONPATH = (Resolve-Path out/image-quality-deps).Path + ';' + (Resolve-Path out/geometry-refinement-pilot/deps).Path
$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmtrain/cluster_decoder_pairs.py out/thingi10k-metadata/meshes/download_manifest.json --out out/cluster-decoder-pairs/train-pruned --split train --limit 16
python tools/mmtrain/cluster_decoder_pairs.py out/thingi10k-metadata/meshes/download_manifest.json --out out/cluster-decoder-pairs/validation --split validation --limit 8
python tools/mmtrain/fit_cluster_decoder.py out/cluster-decoder-pairs/train-pruned/manifest.json --out out/cluster-decoder-fit/rank8 --rank 8
python tools/mmtrain/cluster_decoder_quality.py --pairs out/cluster-decoder-pairs/train-pruned/manifest.json --pairs out/cluster-decoder-pairs/validation/manifest.json --fit out/cluster-decoder-fit/rank8 --out out/cluster-decoder-quality/rank8 --views 12 --size 256 --samples 2
python tools/mmmetrics/summarize_decoder_quality.py out/cluster-decoder-quality/rank8/report.json --out out/cluster-decoder-quality/rank8/summary.json
python tools/mmmetrics/build_decoder_quality_gallery.py out/cluster-decoder-quality/rank8/report.json --out out/cluster-decoder-quality/rank8/validation-errors.png
```

The local proxy was unavailable during package acquisition; removing proxy variables
for that process allowed direct downloads. No persistent proxy setting was changed.
LPIPS downloaded SqueezeNet weights into the workspace TORCH_HOME. Metric execution
uses existing CPU PyTorch 2.7.1 / torchvision 0.22.1. A default-environment test first
warned about NumPy 2.5.4/SciPy compatibility; actual data preparation and quality
evaluation use the compatible pinned NumPy 2.2.6 environment.

## Decision

Retain rank-8 SVD as a negative linear control; do not promote this unconstrained
nearest-surface regression as the decoder method or consume the final test set.
Any next mechanism must address visible appearance and feasible geometry updates,
not merely lower pointwise encoder residuals. Strong Corner/meshoptimizer baselines,
matched bytes/load costs, textured PBR, independent surface metrics, moving-camera
stability, and fresh final assets remain required before a SIGGRAPH claim.
