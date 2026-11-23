# 70% Retention QEM / Meshoptimizer Screen: Training Split

This is a development-only, split-labelled extension of the matching validation
screen. It compares deterministic QEM with meshoptimizer on the 16 training
assets, at approximately 70% of source faces. It does not measure a learned
decoder and must not be combined with validation intervals or used as evidence
of generalization. Earlier experiments also used this training corpus.

## Protocol

- Frozen Thingi10K manifest and input hashes; 16 train entries were selected.
- Twelve orthographic views per asset, 256 x 256 pixels, 4x box sampling,
  untextured geometry, 8-bit sRGB output, and LDR-FLIP at 67 pixels per degree.
- QEM uses `fast-simplification 0.2.0`; meshoptimizer uses 0.18.1 with
  `LockBorder`. Both methods target the same face count. Actual output face
  counts are checked before image and surface comparison.
- Per-asset image results average the 12 views. Uncertainty intervals use 10,000
  paired bootstrap resamples over assets; views are not treated as independent
  samples. PSNR pairs with an infinite value for a perfect image match are
  omitted from its finite-difference interval and identified in the receipt.
- Surface estimates use 20,000 area samples in each direction on normalized
  geometry. Zero-area/sub-threshold and duplicate meshoptimizer faces are
  omitted only for surface sampling when necessary. Raw output is retained for
  image metrics, with strict topology status reported separately.

## Results

One QEM output was rejected for a duplicate geometric triangle, leaving 15
matched pairs. All 16 source meshes passed input topology checks. Meshoptimizer
passed both topology and directed-boundary checks on 10 of the 15 paired raw
outputs. The strict-valid subset therefore contains only ten assets.

| Metric (meshoptimizer minus QEM) | Raw outputs, N=15 | Strict-valid outputs, N=10 |
|---|---:|---:|
| PSNR, dB (higher is better) | +4.10 [ +1.16, +7.52 ], N=14 finite pairs | +3.43 [ +0.49, +6.87 ], N=9 finite pairs |
| SSIM (higher is better) | +0.00137 [ +0.00016, +0.00314 ] | +0.00187 [ +0.00006, +0.00445 ] |
| LDR-FLIP (lower is better) | -0.00085 [ -0.00196, -0.00005 ] | -0.00097 [ -0.00262, +0.00015 ] |
| Silhouette XOR fraction (lower is better) | -0.000137 [ -0.000331, -0.000003 ] | -0.000189 [ -0.000452, +0.000008 ] |
| Bidirectional Chamfer L1 (lower is better) | -0.000030 [ -0.000087, +0.000013 ] | -0.000044 [ -0.000123, +0.000023 ] |
| Normal consistency, absolute dot (higher is better) | +0.00035 [ -0.00036, +0.00125 ] | +0.00035 [ -0.00065, +0.00167 ] |

Brackets are 95% asset-bootstrap percentile intervals. The strict-valid subset
is selected by output validity and is not a substitute for an independent
comparison. The screen suggests QEM is a weak baseline on this development
corpus: image metrics often favor meshoptimizer, but sampled surface metrics
are mixed and many meshoptimizer outputs fail strict topology. It says nothing
about decoder quality, runtime cost, materials, temporal stability, user
preference, or mobile hardware. LPIPS and timings were not measured here.

The independent eight-asset validation result is in the
[validation report](CLUSTER_DECODER_BASELINE_70PCT_VALIDATION_20261122.md).
Machine-readable per-asset, per-view data, simplifier failures, and input/code
hashes are in the
[training receipt](cluster_decoder_qem_meshopt_train_70pct_20261122.json).
The [reproduction script](compare_qem_meshopt_validation_70pct.py) accepts only
`train` or `validation`; it refuses the final test split.
