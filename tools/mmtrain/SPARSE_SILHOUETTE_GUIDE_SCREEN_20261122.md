# Sparse native-resolution silhouette guide preflight

The [half-resolution guide](SILHOUETTE_GUIDE_FUSION_20261122.md) still rasterizes
the full source. This screen asks whether conservatively retaining source
triangles whose projected rectangles touch the coarse outline band can make a
native-resolution guide competitive with measured AA and reconstruction modes,
even when the band and draw indices are prepared once for a fixed view.

[Sander et al., Silhouette Clipping](https://hhoppe.com/silclip.pdf) already
compute an exact geometric silhouette and clip an enclosing coarse hull.
[Munkberg et al., A4](https://fileadmin.cs.lth.se/graphics/research/papers/2013/a4/a4.pdf)
already use a silhouette importance mask for sparse rasterization and
antialiasing. This screen measures a narrower budget question for an arbitrary
simplified base, native-resolution source color and the seed's existing
rasterization contract. It establishes no methodological novelty by itself.

## Frozen protocol

- Use all 13 development assets from the previous guide screen, the same
  desktop Iris Xe workload, 1280×720, 16 tiled instances, fixed camera,
  grayscale normals, and the same supersampled full-source reference.
- The coarse render is the calibrated component cut with 4× MSAA. Define
  the two-pixel L1 boundary band from the coarse resolved foreground. Build
  an integral image of the band. Retain a source triangle if its projected
  pixel rectangle touches the band for any instance. Expand the rectangle
  by one pixel for arithmetic and subpixel raster precision, keep faces in
  input order, and retain a conservatively unmatched clip-plane straddler.
- Render the retained source indices with native-size 4× MSAA. Copy their
  resolved intensity only inside the cached band, including background
  pixels. Verify the candidate's exact agreement with a full-source native
  4× MSAA copy inside the band and with the coarse render outside.
- Measure precomputation and upload separately. Remeasure GPU time for
  the full coarse pass, retained-source pass, and composite in one interval.
  The fixed-view index buffer and band texture are uploaded once per asset.
  This excludes dynamic mask generation, triangle selection and uploads from
  per-frame GPU time. Compare full-source native, 4× MSAA, Bevy SMAA, and
  half-resolution linear and Catmull–Rom reconstruction as well as matched
  QEM and component 4× MSAA and SMAA. Use three batches of 32 timed frames
  with reordered mode starts and isolated captures.
- Record retained triangle count, resident candidate buffers, prep and upload
  time, LDR-FLIP (primary), PSNR, SSIM, and resource-matched controls. For each
  asset the strongest eligible control has the lowest LDR-FLIP among controls
  with p50 GPU time at most the candidate's. Advance to a dynamic prototype
  only if the candidate extends that frontier on at least 7/13 assets, the
  paired mean LDR-FLIP gain has a 95% asset bootstrap interval above zero,
  and every pixel-equivalence check passes. Those thresholds warrant a new
  experiment, while independent assets and full dynamic cost are required for
  any contribution claim.

Before running the experiment, Windows application control refused the native
FLIP 1.7 Python extension. This run uses a grayscale CPU specialization of the
[LDR-FLIP equations](https://research.nvidia.com/publication/2020-07_FLIP) at
67 pixels per degree for every mode. It removes the chromatic channels for
neutral gray and retains a full-color normalization constant. Each remeasured
control must reproduce its archived image, PSNR, and SSIM exactly. The receipt
records the FLIP difference against the archived native score for each control
to check the specialization on these fixtures.

## Results

The selected indices reproduce the full-source native 4× MSAA guide inside
the correction band on all 13 assets. Outside that band the composite
reproduces the coarse image. The retained fraction averages 51.2% of source
triangles across assets and ranges from 28.7% to 96.6%. The two-pixel mask
contains 16,064–62,224 active pixels per asset, so a small pixel footprint
still needs many source triangles with conservative projected rectangles.

Relative to coarse 4× MSAA, the correction improves FLIP and PSNR on all 13
assets and SSIM on 12/13. It adds a mean of 0.682 ms to the per-asset p50
GPU time (95% paired asset bootstrap interval [0.546, 0.847] ms). Mean
FLIP changes by −0.004210 ([−0.007351, −0.001900]) and PSNR by +2.84 dB
([+1.57, +4.30]). Intervals use 20,000 paired resamples with seed 20261122.

At the candidate's measured time budget, it improves over the best control in
**2/13 assets for FLIP**, 2/13 for PSNR, and 1/13 for SSIM. The mean FLIP
gain, computed as the best eligible control's error minus the candidate's,
is −0.005004 (95% interval [−0.007547, −0.002533]). Every one of the other
11 assets has a control with less GPU time and better scores in all three
image metrics. ToyCar and SheenCloth are faster than full-source 4× MSAA and
improve on the best cheaper control in FLIP. Full-source 4× MSAA has lower
FLIP than the sparse guide on every asset. The first full run and the repeat
without the unused half-resolution allocations give the same 2/13 outcome.

| Asset | Retained source triangles | Component 4× MSAA p50 ms | Sparse p50 ms / FLIP | Best time-eligible FLIP control | Control p50 ms / FLIP |
|---|---:|---:|---:|---|---:|
| AntiqueCamera | 63.1% | 0.427 | 1.127 / 0.00976 | source-msaa4 | 0.595 / 0.00603 |
| Avocado | 51.9% | 0.267 | 0.711 / 0.01670 | source-msaa4 | 0.314 / 0.00259 |
| BarramundiFish | 62.7% | 0.228 | 0.640 / 0.00448 | source-msaa4 | 0.294 / 0.00188 |
| CesiumMilkTruck | 36.1% | 0.288 | 0.746 / 0.01496 | source-msaa4 | 0.362 / 0.00408 |
| Lantern | 96.6% | 0.241 | 0.658 / 0.00586 | source-msaa4 | 0.273 / 0.00480 |
| SheenChair | 51.0% | 0.502 | 1.204 / 0.00757 | source-msaa4 | 0.988 / 0.00468 |
| ToyCar | 30.3% | 0.853 | 2.270 / 0.00924 | qem-msaa4 | 0.950 / 0.01291 |
| WaterBottle | 47.3% | 0.328 | 0.769 / 0.01041 | source-msaa4 | 0.421 / 0.00317 |
| FlightHelmet | 36.7% | 0.935 | 1.754 / 0.01191 | source-msaa4 | 1.724 / 0.00542 |
| GlassVaseFlowers | 61.2% | 0.368 | 1.046 / 0.01093 | source-msaa4 | 0.584 / 0.00642 |
| IridescenceLamp | 30.6% | 0.467 | 1.045 / 0.00929 | source-msaa4 | 0.751 / 0.00363 |
| SheenCloth | 28.7% | 0.680 | 1.485 / 0.00413 | qem-msaa4 | 0.675 / 0.00438 |
| StainedGlassLamp | 68.8% | 0.636 | 1.636 / 0.01595 | source-msaa4 | 1.160 / 0.00613 |

All 117 shared control captures match the prior run byte for byte. PSNR and
SSIM match exactly, and the largest absolute difference from archived native
FLIP is 0.0000040. This agreement covers these neutral-gray controls. The
reported candidate comparisons use the same CPU scorer in every mode.

The candidate adds two RGBA8 resolve surfaces and one R8 full-frame mask
(7.91 MiB of logical texels total), plus 4.1–407.4 KiB of compacted indices.
It shares the source vertex buffer and existing multisample attachments.
These are logical buffer sizes. Driver allocation and peak host memory were
outside the measurement. The per-asset medians for the one-time coarse mask
capture, CPU band and index preparation, and upload including synchronization
are 19.9 ms, 50.9 ms, and 1.45 ms, respectively. These measurements are
separate from the per-frame GPU interval.

Close the cached two-pass configuration. It misses the frozen 7/13 gate
even with fixed-view preparation amortized. The two positive points motivate
measuring genuinely geometry-heavy scenes, where the balance between raster
cost and per-pixel overhead could differ. The current screen covers repeated
instances, fixed-view neutral-gray shading, and desktop hardware.

## Reproduce

Use the [SMAA setup](GPU_SMAA_SILHOUETTE_BAND_SCREEN_20261122.md#reproduce)
for the model exports, Python packages, and Bevy shader inputs. This run
uses NumPy, SciPy, scikit-image, wgpu, and zstandard. The hashes in the
[sparse-guide receipt](sparse_silhouette_guide_720p_20261122.json) describe
the scripts at measurement time. The earlier guide receipt records its own
revision, before timestamp code was shared and native metric import was
moved to the scoring call.

```powershell
python tools/mmtrain/bench_sparse_silhouette_guide.py --manifest out/geometry-refinement-pilot/motion-96.json --meshes out/geometry-refinement-pilot/motion-meshes --shader-root out/deps/bevy-smaa --baseline tools/mmtrain/silhouette_guide_fusion_720p_20261122.json --out out/geometry-refinement-pilot/sparse-guide-720p.json
```
