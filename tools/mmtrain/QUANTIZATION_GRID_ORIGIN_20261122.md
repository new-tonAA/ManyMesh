# Grid origin search for Draco position quantization

The [codec baseline](GEOMETRY_CODEC_RATE_DISTORTION_20261122.md) found that a
low image error can accompany triangle degeneration. This experiment tests
whether moving a uniform position grid rescues some meshes at the same
precision. The hypothesis is that a small search over grid origins can reach a
lower geometry byte cost without raising decoded render error or changing the
mesh connectivity.

## Mechanism

Both policies quantize the full source mesh with the same grid spacing and
the same Draco Edgebreaker encoder. The fixed policy anchors the grid at the
rounded bounding-box minimum. The search tries four offsets per axis from
zero to three quarters of a grid cell, yielding 64 origins including the
fixed origin. For each bit depth, choose the passing origin with the smallest
mean squared vertex displacement. The search uses only source vertex positions
and triangle indices. The Draco stream already carries the quantization origin
and range.

A passing grid leaves every welded input vertex distinct and preserves the
positive dot product between every source and decoded face normal. The
experiment verifies the encoded round trip by comparing the exact oriented
triangle multiset to the predicted float32 result. These checks preserve the
welded combinatorial mesh and exclude local normal reversals. They do not certify
the absence of new self-intersections or agreement across separately encoded meshes.

## Evaluation

- Use 10, 12, 14, 16, 18, and 20 bits per coordinate on the 16 training assets
  for a geometry preflight and the eight validation assets for actual encoding
  and rendering. These are the reused [Thingi10K development splits](THINGI10K_PILOT_DATA_20261120.md).
- Use normalized positions multiplied by an exact power of two. Round the
  effective grid spacing up to a half unit and reserve one cell for possible
  offsets. This keeps grid parameters representable in Draco's decimal option
  parser. Compare policies at the same nominal depth and spacing per asset.
- Use actual standalone Draco geometry stream bytes. Measure the Python grid
  search and 11 warm Node.js/WASM CPU decodes on an Intel Core i7-13700H.
  Time the fixed-origin check separately. No production asset loading or GPU
  rendering runs inside either timer.
- Score decoded geometry against the full reference in eight 192x192
  orthographic views with 4x pixel sampling and flat shading. Report LDR-FLIP,
  PSNR from mean MSE, Gaussian-window SSIM, and geometric coverage errors.
- Compare the lowest passing precision under both policies on each asset.
  This is a frozen geometry-only selection rule. Report the actual byte and
  LDR-FLIP changes, plus comparisons at the same precision. Passing the geometry
  check alone does not establish a rate-distortion gain.

## Prior work

[Geometric Rounding and Feature Separation in Meshes](https://doi.org/10.1016/j.cad.2018.10.003)
changes the mesh to separate features sufficiently for topologically safe
rounding. [Adaptive Coarse-to-Fine Quantization](https://perso.liris.cnrs.fr/guillaume.lavoue/conference/VMV2009.pdf)
adapts quantization precision at each progressive resolution and applies a
discrete rotation. [Towards Practical Meshlet Compression](https://doi.org/10.2312/vmv.20241204)
uses a global quantization grid for crack-free local storage. The measured
question here is limited to adjusting the translation of a single grid while
retaining input connectivity and the standard Draco stream. A limited origin
search alone does not establish novelty over geometric rounding or quantization
optimization.

## Results

On the 16 training meshes, six reached a lower tested precision and two that
failed at every fixed origin passed at a searched origin with 18 bits.
All eight validation assets passed under both policies at some tested precision.
The table uses the first passing precision in each sweep.

| Thingi10K file | Bits, fixed → search | Draco bytes, fixed → search | Mean LDR-FLIP, fixed → search |
|---|---:|---:|---:|
| 90431 | 10 → 10 | 1,289 → 1,289 | 0.004944 → 0.005180 |
| 263198 | 14 → 14 | 1,052 → 1,052 | 0.000255 → 0.000251 |
| 44710 | 16 → 16 | 7,488 → 7,489 | 0.000139 → 0.000152 |
| 191968 | 20 → 14 | 3,964 → 2,827 | 0.000002 → 0.000617 |
| 383021 | 20 → 20 | 41,295 → 41,295 | 0.000010 → 0.000021 |
| 100894 | 12 → 12 | 8,033 → 8,033 | 0.002195 → 0.002195 |
| 257594 | 20 → 16 | 102,514 → 78,833 | 0.000034 → 0.000385 |
| 94990 | 16 → 16 | 42,695 → 42,721 | 0.000238 → 0.000224 |

Relative to the first passing fixed setting, search changed bytes by a mean
of **−6.46%** (95% paired asset-bootstrap interval **[−15.13%, +0.02%]**).
The mean LDR-FLIP change was **+0.000151 [ +0.000025, +0.000312 ]**.
Resampling used 20,000 replicates of the eight assets with seed 20261122.
Both assets that saved bytes worsened on LDR-FLIP. At equal tested precision,
four points across three assets used fewer bytes and had lower LDR-FLIP. Their
byte savings were 1–3 bytes per point. Summing the geometry checks through the
first passing precision gave a median of 332 ms for search and 6 ms for the
fixed check, before encoding.

Close this grid search as a contribution candidate. It can change the first
passing precision, but the resulting byte savings came with higher image
error and greater preprocessing cost. The result applies to six sampled
precisions, this uniform grid family, and a development set of static meshes.

The receipts retain all examined precision levels, passing phase counts,
encoded bytes, payload hashes, raw warm decode times, and per-view quality.
See the [training preflight](quantization_grid_origin_train_20261122.json)
and [validation experiment](quantization_grid_origin_validation_20261122.json).

## Reproduce

Use the same dependencies and manifest as the [codec baseline](GEOMETRY_CODEC_RATE_DISTORTION_20261122.md).

```powershell
python tools/mmtrain/bench_quantization_phases.py --manifest out/thingi10k-metadata/meshes/download_manifest.json --out out/geometry-codecs/phase-train.json --split train --preflight-only
python tools/mmtrain/bench_quantization_phases.py --manifest out/thingi10k-metadata/meshes/download_manifest.json --out out/geometry-codecs/phase-validation.json --split validation
```
