# Half-resolution silhouette guide screen

This screen turns the earlier ideal silhouette-band correction analysis
into a renderable fixed-view prototype. Adding coarse detail recovers some image
quality, but neither fusion extends the measured GPU time–quality frontier on
any of the 13 development assets.

## Protocol

- Render 16 instances of each reused Khronos glTF asset at 1280×720, with the
  same fixed perspective view and gray geometry shading as the previous screen.
  Use an Intel Iris Xe integrated GPU, driver 31.0.101.4502, with D3D12 and
  wgpu 0.33.0. The component and QEM cuts match face counts per asset
  (135–23,039 faces), and the source meshes range from 682 to 115,200 faces.
- Render the component cut at 1280×720 with 4× MSAA and the source mesh at
  640×360 with 4× MSAA. Upsample the source guide with bilinear interpolation.
  Use a two-pixel Manhattan-distance band where the resolved component
  foreground changes between zero and positive intensity.
- `guide-copy` copies guide intensity inside the band. `guide-detail` adds the
  coarse pixel minus its 2×2 box-averaged and bilinearly reconstructed value,
  then clamps the result. Outside the band both forward the resolved coarse
  pixel. Both use a full-screen composite and draw the full source mesh every
  frame. `guide-only` measures the half-resolution 4× MSAA source and bilinear
  pass on their own.
- Remeasure native full-source rendering, 4× MSAA, Bevy SMAA Medium luma, and
  native half-resolution linear or Catmull–Rom upscaling. Remeasure 4× MSAA and
  SMAA on the matching QEM and component cuts. Include guide-only among the
  controls for frontier comparisons.
- Render the quality reference independently at 2560×1440 from the full
  source with 4× MSAA, average 2×2 blocks in linear light, and convert to
  display sRGB. Report LDR-FLIP at 67 pixels per degree, PSNR, and Gaussian SSIM
  using the same implementation as the earlier screen. The nine common
  control images per asset match the earlier run byte for byte.
- Take 96 GPU timestamp samples per asset and mode, in three reordered
  batches of 32 after preconditioning, with eight warm-up frames per batch.
  The timed interval spans the first raster pass through the final output
  pass. It includes the two raster passes and composite for fusion. Quality
  capture follows timing, and application CPU and display presentation are
  outside the GPU interval.

## Matched comparisons

Deltas are fusion minus the named control. Each timing is the per-asset p50.
Intervals are 95% percentile intervals on the paired mean with 20,000
asset-level bootstrap resamples (seed 20261122). Smaller LDR-FLIP and GPU
time are better. The interval summarizes this reused development set.

| Compared modes | GPU delta in ms [95% interval] | LDR-FLIP delta [95% interval] | Lower LDR-FLIP |
|---|---:|---:|---:|
| Copy vs. component 4× MSAA | +1.361 [+1.001, +1.827] | +0.00417 [+0.00181, +0.00646] | 2/13 |
| Detail vs. component 4× MSAA | +1.358 [+1.022, +1.818] | −0.00178 [−0.00400, −0.00007] | 8/13 |
| Copy vs. guide only | +1.013 [+0.877, +1.162] | +0.00253 [+0.00072, +0.00460] | 2/13 |
| Detail vs. guide only | +1.010 [+0.909, +1.127] | −0.00341 [−0.00594, −0.00070] | 10/13 |
| Detail vs. full-source 4× MSAA | +0.874 [+0.662, +1.036] | +0.00820 [+0.00594, +0.01061] | 0/13 |

The detail variant gains 0.135 dB versus the component cut (95% interval
[−0.757, +1.107]) and its SSIM changes by −0.00072 ([−0.00255, +0.00185]).
Both intervals span zero. Against guide-only it gains 4.885 dB on average
([+3.626, +6.096]), with a 1.010 ms mean increase in GPU time.

## Quality at the measured GPU budget

For each model, a control is eligible when its p50 GPU time is at most
the fusion variant's p50. Neither variant is better on all three metrics than every eligible control in
**0/13 assets**. This does not mean that it loses every metric comparison. On
each asset, the table shows one cheaper control that dominates both variants
simultaneously on LDR-FLIP, PSNR, and SSIM. The control was selected after
seeing results, so this is an exploratory screen, not a pre-registered test.

| Asset | Component 4× MSAA | Guide only | Copy | Detail | Eligible control |
|---|---:|---:|---:|---:|---:|
| AntiqueCamera | 0.567 / 0.01247 | 0.655 / 0.01939 | 2.217 / 0.02036 | 1.578 / 0.01286 | 0.552 / 0.00603 |
| Avocado | 0.223 / 0.02511 | 0.292 / 0.01239 | 0.998 / 0.02373 | 1.066 / 0.01997 | 0.252 / 0.00259 |
| BarramundiFish | 0.203 / 0.00563 | 0.242 / 0.00733 | 0.987 / 0.00864 | 1.114 / 0.00540 | 0.279 / 0.00188 |
| CesiumMilkTruck | 0.327 / 0.01805 | 0.314 / 0.01518 | 1.068 / 0.02084 | 1.201 / 0.01665 | 0.349 / 0.00408 |
| Lantern | 0.274 / 0.00748 | 0.294 / 0.01567 | 1.011 / 0.01471 | 1.070 / 0.00758 | 0.251 / 0.00480 |
| SheenChair | 0.452 / 0.00855 | 0.691 / 0.02102 | 1.676 / 0.02139 | 1.761 / 0.01012 | 0.452 / 0.00855 |
| ToyCar | 0.722 / 0.01292 | 3.006 / 0.01577 | 4.321 / 0.01635 | 4.366 / 0.01133 | 3.054 / 0.00406 |
| WaterBottle | 0.310 / 0.01235 | 0.338 / 0.01228 | 1.343 / 0.01719 | 1.420 / 0.01170 | 0.374 / 0.00317 |
| FlightHelmet | 0.794 / 0.01357 | 1.178 / 0.01840 | 2.595 / 0.02005 | 2.608 / 0.01412 | 1.494 / 0.00542 |
| GlassVaseFlowers | 0.332 / 0.03021 | 0.479 / 0.02577 | 1.351 / 0.02579 | 1.325 / 0.01800 | 0.523 / 0.00642 |
| IridescenceLamp | 0.453 / 0.01038 | 0.515 / 0.01160 | 1.454 / 0.01508 | 1.503 / 0.00993 | 0.641 / 0.00363 |
| SheenCloth | 0.634 / 0.00438 | 1.746 / 0.01326 | 2.768 / 0.01065 | 2.689 / 0.00558 | 1.437 / 0.00333 |
| StainedGlassLamp | 0.554 / 0.02480 | 0.616 / 0.01908 | 1.745 / 0.02528 | 1.803 / 0.01952 | 0.994 / 0.00613 |

Entries are p50 GPU ms / LDR-FLIP. The eligible control is full-source 4× MSAA
except for SheenChair, which uses component 4× MSAA. These per-asset choices
are retrospective comparisons against the measured mode set.

Close these two implementations as contribution candidates. The tested
full-screen composite still draws all of the fine geometry at half resolution.
The result covers a desktop fixed-view gray workload on reused assets.
Independent assets, camera motion, authored materials, and mobile hardware
remain outside this measurement.

## Reproduce

The screen uses pinned Bevy v0.16.1 shaders/LUTs and Khronos model exports.
The [original receipt](silhouette_guide_fusion_720p_20261122.json) and
[repeat receipt](silhouette_guide_fusion_720p_repeat_20261123.json) include
per-frame samples, image hashes, face counts, and script and input hashes.
Prepared meshes and Python dependencies were in ignored local `out/` data;
this repository snapshot does not fully reproduce GPU timing.
An initial full run stopped on an invalid GPU timestamp batch. The complete
rerun validates and records retries of invalid batches. It required zero retries.
Independent CPU pixel checks on Avocado, GlassVaseFlowers, and SheenCloth
reproduce the copy output exactly and the detail output within one 8-bit
intensity level. Both outputs preserve all pixels outside the band.

```powershell
python tools/mmtrain/bench_silhouette_guide_fusion.py --manifest out/geometry-refinement-pilot/motion-96.json --meshes out/geometry-refinement-pilot/motion-meshes --shader-root out/deps/bevy-smaa --out out/geometry-refinement-pilot/guide-fusion-720p.json
```


## Repeat and evidence audit

The [repeat receipt](silhouette_guide_fusion_720p_repeat_20261123.json) reran
all 13 assets with the current [benchmark source](bench_silhouette_guide_fusion.py).
Every per-mode image-quality record and image hash matches the first receipt. Both
runs use wgpu 0.33.0. The repeat also records Python 3.12.3, NumPy 2.2.6,
scikit-image 0.25.2, and zstandard 0.23.0; the original receipt did not record
all of these versions. Median per-asset GPU p50 changed by -13.5% to +12.1%
across six modes; the two fusion candidates changed by +2.8% and +4.6%. The
13/13 MSAA dominance finding persists, but the desktop timing is run-state
sensitive and is not a mobile or full-frame performance result. The [verification script](verify_silhouette_guide_fusion.py) recalculates the
0/13 strict-win and 13/13 MSAA-dominance counts and confirms the quality records
match. Run it with `python tools/mmtrain/verify_silhouette_guide_fusion.py`. The repeat receipt
records SHA-256 `be191a76e404959b1a5f585f6655e3940a2a008015aebd22c3f51f9844fc4b70`
for the benchmark, `6e5b7fbccd135ac29cf87cd601fa24d891a9ae3981ddef575cd7280b8d8143a6`
for its SMAA parent, `4dc3634e24429f408e4a22d0a0d4c87ca562ddbf6b5bf68423d512ddd829305e`
for its raster dependency, and
`328f1efeecfb5b6e0221a2f0665aed1a7e180f50b000f3da5f44a609563ea825` for the
input manifest. The original receipt records a different benchmark digest,
`851cf521fbcf0cf83c874331d7c9a0d5afbbcd38854bd4facea77bf4c6b26ac4`, which does
not match the current source. The current repeat receipt SHA-256 is
`cacd6468ab1a35f5b706a583998f8c54ab628db022f4b40b3d7d18d666f458d8`; the
CPU-only verifier SHA-256 is
`aecea9b5adea23475e586b7d66a71f0f77cad881be8ea88962253ff75276d1f6`. Prepared meshes and frame
captures remain under ignored local `out/` and are not included in this bundle.
The run is therefore auditable from its hashes but not standalone reproducible
from this repository snapshot alone.
