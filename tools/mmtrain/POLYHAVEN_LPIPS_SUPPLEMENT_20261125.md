# Poly Haven matched-face LPIPS supplement

Protocol frozen 2026-11-25, before scoring LPIPS. This is a post-hoc metric
addition to the already published 21-model screen, not a new or independent
test set. No method or threshold will be selected from these results.

## Question and comparison

Does calibrated SqueezeNet LPIPS rank the frozen ManyMesh cuts differently
from the matched-face QEM and meshoptimizer controls under the original fixed
rendering protocol? Re-render the same 21 CC0 Poly Haven models, original
source references, 24 view-distance pairs per model, and exact-face candidate
meshes. Compare native rasterization and 4x MSAA. Preserve the original
640x360 Iris Xe / D3D12 renderer, 2x supersampled 4x-MSAA reference, and linear
box resolve. Do not alter geometry, cameras, materials, lighting, or sampling.

Use LPIPS 0.1.4, calibrated SqueezeNet v0.1, RGB copies of the grayscale
renders, and the same 8-bit sRGB inputs used by the other image metrics. Lower
LPIPS is better. Report per-view and per-asset values, plus ManyMesh-minus-
control deltas against both QEM and meshoptimizer. Average views within each
asset, average assets within each of the 16 source-collection groups, then
bootstrap those paired group means 10,000 times with seed `20261125` for a
percentile 95% interval. Do not interpret LPIPS alone as human preference.

## Integrity and decision limits

Before rendering, verify every geometry hash against the frozen cohort and
every raw baseline receipt against its recorded hash. For each re-rendered
view, compare PSNR, SSIM, LDR-FLIP, and silhouette XOR with the original raw
receipt. Accept the LPIPS supplement only if every value reproduces within
`1e-6`; otherwise stop and report the replay mismatch without aggregating
LPIPS. Record the renderer adapter, software versions, scorer and input hashes,
LPIPS backbone and calibration hashes, commands, and all per-view data.

This cohort has already been examined using other metrics. Treat any LPIPS
result as descriptive metric-sensitivity evidence, not confirmatory held-out
evidence. A different LPIPS ranking would not reopen the tested ManyMesh cut or
advance the CUDA placement control. A matching negative result would add a
learned feature-space measure to the documented comparison, but would not
establish perceptual preference or a novel method.

## Reproduction

The renderer dependencies are in the ignored research environment. The
published raw geometry and score receipts remain local under `out/`; the
checked-in manifest and hashes identify the required inputs. Run one asset
first to check the replay audit, then run the full cohort with the same script
hash and a fresh output directory.

```powershell
$env:PYTHONPATH = 'out/manymesh-research-pydeps-20261123;out/geometry-refinement-pilot/deps;out/geometry-refinement-pilot/deps/wgpu;out/image-quality-deps'
python tools/mmtrain/score_polyhaven_lpips_supplement.py `
  --manifest tools/mmtrain/polyhaven_quality_cohort_20261124.json `
  --cohort-receipt tools/mmtrain/polyhaven_quality_screen_20261124.json `
  --metrics tools/mmtrain/polyhaven_quality_metrics_20261124.json `
  --raw-dir out/polyhaven-quality-screen-20261124 `
  --torch-hub out/moving-scene-metrics-20261124/torch-hub `
  --out-dir out/polyhaven-lpips-supplement-verified-20261125
```
