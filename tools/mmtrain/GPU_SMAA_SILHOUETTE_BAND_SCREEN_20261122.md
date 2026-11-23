# Desktop SMAA and silhouette correction screen

This experiment extends the [13-asset MSAA benchmark](CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md)
with a three-pass SMAA baseline and a bound on the squared image error that a
local silhouette correction can remove.

## Protocol

- Render the same 13 Khronos glTF development assets at 1280x720 on Intel Iris
  Xe, driver 31.0.101.4502, using D3D12 and wgpu 0.33.0. Use 16 tiled instances
  per draw, a fixed perspective camera, and the existing grayscale shading.
- Compare full geometry with native rasterization, MSAA 4x, SMAA 1x,
  and half-resolution rendering followed by linear or Catmull-Rom 2x
  reconstruction. The fixed QEM and calibrated component cuts share their
  face counts. Both are tested with MSAA and SMAA. Also measure a native
  component cut.
- Use the [Bevy v0.16.1 SMAA implementation](https://github.com/bevyengine/bevy/tree/v0.16.1/crates/bevy_core_pipeline/src/smaa)
  in its medium preset, with luma edge detection. Preserve the Bevy shader
  and compressed search and area textures. The adapter selects the shader
  definitions and reproduces Bevy's stencil restriction on the weight pass.
  The [SMAA reference project](https://www.iryoku.com/smaa/) describes the
  underlying algorithm.
- The shared reference renders the source mesh at 2560x1440 with MSAA 4x,
  then box averages each 2x2 pixel block in linear light. Convert the
  linear-light 8-bit targets to display sRGB before LDR-FLIP (67 pixels
  per degree), PSNR, and Gaussian SSIM.
- Take 240 GPU timestamp samples per mode across five interleaved batches.
  Precondition each mode for 16 frames and warm up eight frames per batch.
  Capture and compute quality after timing. Measure raster through the last
  pass, including all three SMAA passes where enabled. These timestamps
  exclude application CPU and display presentation.

## Ideal local correction protocol

Take the foreground mask of the component cut after MSAA 4x. Around its
boundary, form a band as the difference of binary dilation and erosion,
using a four-neighbor stencil with radius 1, 2, or 4 pixels. Replace only
the band with the corresponding reference pixels and rescore the image.
This requires reference colors and gives the exact squared error left
outside each band, which bounds the best PSNR of an algorithm limited to
that support. The scored LDR-FLIP is for the perfect-copy image. FLIP's
neighborhood filters make it different from a strict optimum of LDR-FLIP.

For each asset, list the strongest measured full-geometry or equal-face QEM
controls whose p50 GPU time fits within the uncorrected component MSAA 4x
time. Test whether the perfect-copy image exceeds those controls in quality.
This grants the correction zero added cost. It quantifies headroom for a
local correction while excluding any speed claim for that correction.

## SMAA results

Each entry compares SMAA with MSAA on the same geometry. Differences are
SMAA minus MSAA. The time comparison uses each asset's p50 GPU time.
Intervals are 95% percentile intervals from 20,000 paired asset resamples
with seed 20261122.

| Geometry | SMAA faster | SMAA lower LDR-FLIP | Both | Mean GPU delta, ms [95% interval] | Mean LDR-FLIP delta [95% interval] |
|---|---:|---:|---:|---:|---:|
| Full source | 7/13 | 0/13 | 0/13 | −0.0589 [−0.1293, +0.0020] | +0.002781 [+0.002003, +0.003627] |
| QEM cut | 5/13 | 1/13 | 0/13 | −0.0025 [−0.0539, +0.0388] | +0.001331 [+0.000959, +0.001694] |
| Component cut | 5/13 | 1/13 | 0/13 | −0.0059 [−0.0543, +0.0368] | +0.001516 [+0.001081, +0.001941] |

Six full-source speed wins hold in all five batch medians. For example,
StainedGlassLamp takes 0.780 ms with SMAA and 1.112 ms with MSAA. Its LDR-FLIP
rises from 0.006134 to 0.011861. The tested plain SMAA preset is a quality
and cost tradeoff on this workload. Timings vary across batches and the
asset intervals do not establish a speed gain.

## Ideal silhouette correction results

Each percentage averages the per-asset fractions over all 13 meshes.
ToyCar has no eligible full geometry or QEM control at the uncorrected
component cut's GPU time, leaving twelve fair budget comparisons.

| Band radius | Pixels in band | Squared error removed | Perfect-copy PSNR above all eligible controls | Perfect-copy LDR-FLIP below all eligible controls |
|---|---:|---:|---:|---:|
| 1 px | 1.79% | 63.0% | 11/12 | 5/12 |
| 2 px | 3.43% | 71.0% | 11/12 | 6/12 |
| 4 px | 6.44% | 79.5% | 12/12 | 9/12 |

Without correction, 3/12 component cuts already have lower LDR-FLIP than all
eligible controls. The 2 px perfect-copy image adds AntiqueCamera,
GlassVaseFlowers, and SheenCloth. The band works unevenly across assets.
At 2 px it captures 94.2% of squared error on GlassVaseFlowers and 36.2% on
CesiumMilkTruck. PSNR alone would give a substantially more optimistic view
of the same correction than LDR-FLIP.

This gives a measurable target for a narrow-band method that estimates missing
coverage or coarse shading from deployable inputs. The copy operation itself
has access to the full reference and has no measured execution budget. A
method must measure its own added cost and confirm the gain on independent
assets and motion paths.

The [half-resolution guide follow-up](SILHOUETTE_GUIDE_FUSION_20261122.md)
measures two renderable approximations on these development assets. Both
lose to time-eligible controls on all 13 assets.

See the [GPU receipt](bevy_smaa_720p_20261122.json) and
[band receipt](silhouette_band_oracle_720p_20261122.json) for per-asset timings,
quality, and the list of eligible controls.

## Reproduce

Use the [benchmark geometry and Python dependencies](CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md#scope-and-reproduction),
plus `zstandard`. Save Bevy v0.16.1's `smaa.wgsl`, `SMAAAreaLUT.ktx2`, and
`SMAASearchLUT.ktx2` under `out/deps/bevy-smaa`. Their hashes are verified
before use.

```powershell
python tools/mmtrain/bench_bevy_smaa.py --manifest out/geometry-refinement-pilot/motion-96.json --meshes out/geometry-refinement-pilot/motion-meshes --shader-root out/deps/bevy-smaa --out out/geometry-refinement-pilot/bevy-smaa-720p-repeat.json
python tools/mmtrain/audit_silhouette_band_oracle.py --benchmark out/geometry-refinement-pilot/bevy-smaa-720p-repeat.json --manifest out/geometry-refinement-pilot/motion-96.json --meshes out/geometry-refinement-pilot/motion-meshes --out out/geometry-refinement-pilot/silhouette-band-oracle-720p-repeat.json
```
