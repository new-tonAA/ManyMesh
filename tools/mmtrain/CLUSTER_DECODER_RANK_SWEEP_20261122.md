# Cluster Decoder Rank Sweep

Date: 2026-11-22. This development screen tests whether the negative
rank-8 result was caused by too little shared-basis capacity. It varies only
the rank of the existing shared polynomial linear-subspace decoder. This is
not a neural decoder, a new algorithm, or a publication result.

## Protocol

- Train-only basis fitting uses the same 9 prepared assets from the 16-asset
  training split, ridge `1e-5`, and either fixed-topology displacement or
  10%-face budgeted centroid refinement. Ranks 8, 16, and the maximum allowed
  rank 30 are compared. Three training QEM outputs failed preparation.
- Validation has 5 prepared assets out of 8; three QEM bases failed strict
  preparation. No failed asset was repaired, dropped silently, or replaced.
  No test manifest or test geometry was loaded.
- Quality uses 12 orthographic views at 256 x 256, four raster samples per
  pixel, flat grayscale shading, PSNR, SSIM, LDR-FLIP, calibrated SqueezeNet
  LPIPS, silhouette XOR, and coverage MAE. Intervals resample assets, not views.
- The fixed decoder is compared with its QEM base at identical face count.
  Refinement adds faces and is not an equal-face comparison. Sidecar bytes
  exclude the separately reported shared model file.

## Validation results

Deltas are decoder minus the same per-asset QEM base. Negative PSNR/SSIM
and positive FLIP/LPIPS/silhouette/coverage deltas are worse. Intervals are
95% paired asset-bootstrap intervals from 2,000 resamples (seed
`20261121`).

| Rank | Shared fixed/refine model bytes | Fixed decoded | Fixed sidecar mean B | Fixed PSNR dB | Fixed SSIM | Fixed FLIP | Fixed LPIPS | Refine decoded | Refine sidecar mean B |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 1488 / 1488 | 4/5 | 1829 | -0.364 [-0.624, -0.104] | -0.00198 [-0.00299, -0.00070] | +0.00196 [+0.00065, +0.00327] | +0.00090 [+0.00021, +0.00172] | 3/5 | 3018 |
| 16 | 2448 / 2448 | 4/5 | 2680 | -0.427 [-0.697, -0.156] | -0.00269 [-0.00411, -0.00089] | +0.00247 [+0.00079, +0.00415] | +0.00104 [+0.00040, +0.00158] | 3/5 | 3869 |
| 30 | 4128 / 4128 | 3/5 | 4170 | -0.422 [-0.774, -0.173] | -0.00243 [-0.00441, -0.00004] | +0.00215 [+0.00011, +0.00486] | +0.00086 [+0.00008, +0.00186] | 2/5 | 5359 |

### Fixed-topology metric details

| Rank | Paired validation assets | PSNR delta dB | SSIM delta | FLIP delta | LPIPS delta | Silhouette XOR delta | Coverage MAE delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 4/5 | -0.364 [-0.624, -0.104] | -0.00198 [-0.00299, -0.00070] | +0.00196 [+0.00065, +0.00327] | +0.00090 [+0.00021, +0.00172] | +0.00042 [+0.00014, +0.00068] | +0.00037 [+0.00015, +0.00057] |
| 16 | 4/5 | -0.427 [-0.697, -0.156] | -0.00269 [-0.00411, -0.00089] | +0.00247 [+0.00079, +0.00415] | +0.00104 [+0.00040, +0.00158] | +0.00066 [+0.00023, +0.00105] | +0.00059 [+0.00017, +0.00104] |
| 30 | 3/5 | -0.422 [-0.774, -0.173] | -0.00243 [-0.00441, -0.00004] | +0.00215 [+0.00011, +0.00486] | +0.00086 [+0.00008, +0.00186] | +0.00067 [+0.00003, +0.00140] | +0.00066 [+0.00003, +0.00139] |

## Interpretation

Increasing rank did not rescue the fixed decoder. Every rank is worse than
QEM on every reported fixed-topology metric over its valid paired assets.
Ranks 8 and 16 share the same four valid pairs; rank 16 has larger deltas in
the wrong direction and larger shared weights and sidecars. Rank 30 decodes
only three validation meshes, so its smaller paired set cannot be compared
directly with the four-asset estimates. It is still worse on all metrics and
has two fixed-decoder validation failures. Refinement decodes on 3/5
validation assets at ranks 8 and 16 and 2/5 at rank 30; it does not
provide an equal-face result.

Decision: close the tested polynomial ranks 8, 16, and 30. This does not
rule out other learned decoders, but the current linear residual target and
basis do not translate lower pointwise fitting error into better rendered
quality. Do not use the test split to tune this family. A future method needs
a new mechanism and a fresh licensed confirmation set.

## Reproduction

Use the pinned local dependencies described in the [rank-8 protocol](CLUSTER_DECODER_QUALITY_20261121.md).
Run each rank independently from the same frozen training pairs:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/image-quality-deps').Path + ';' + (Resolve-Path 'out/geometry-refinement-pilot/deps').Path
$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')
$env:OPENBLAS_NUM_THREADS = '1'
foreach ($rank in 8,16,30) {
  $fit = "out/cluster-decoder-fit/rank$rank"
  $quality = "out/cluster-decoder-quality/rank$rank"
  python tools/mmtrain/fit_cluster_decoder.py out/cluster-decoder-pairs/train-pruned/manifest.json --out $fit --rank $rank
  python tools/mmtrain/cluster_decoder_quality.py --pairs out/cluster-decoder-pairs/train-pruned/manifest.json --pairs out/cluster-decoder-pairs/validation/manifest.json --fit $fit --out $quality --views 12 --size 256 --samples 2
  python tools/mmmetrics/summarize_decoder_quality.py "$quality/report.json" --out "$quality/summary.json"
}
python tools/mmtrain/summarize_cluster_decoder_rank_sweep.py --report-out tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md --json-out tools/mmtrain/cluster_decoder_rank_sweep_20261122.json
```

The [machine-readable receipt](cluster_decoder_rank_sweep_20261122.json) binds
the manifests, model artifacts, quality reports, and source hashes. Full per-view
renders and summaries remain under the ignored `out/cluster-decoder-*` folders.
