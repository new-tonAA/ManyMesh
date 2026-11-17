# Depth-aware real-mesh trajectory results

Date: 2026-11-14. This completes the five-part diagnostic experiment, NOT the SIGGRAPH 2027
research objective. No quality/speed improvement is established for a production mesh algorithm.

Protocol: [DEPTH_CANDIDATE_PROTOCOL.md](DEPTH_CANDIDATE_PROTOCOL.md).
Artifacts: `out/depth-candidate-trajectory/{torus,monkey,pirate,summary}.json` and
`out/depth-candidate-trajectory/worst/audit.json`. All three input assets were used in development.
The six-frame camera path is new relative to the earlier pilot; do not label the assets unseen.

## 1. Screening and information content

Counts below are candidate-frame incidences across six frames, NOT unique candidates.

| Asset | All | Outside viewport | Baseline-visible support | No visible affected face | Evaluated | Not sampled | Zero reference error |
|---|---:|---:|---:|---:|---:|---:|---:|
| Torus | 20,736 | 0 | 13,404 | 7,332 | 60 | 20,676 | 12 |
| Monkey | 274,476 | 0 | 60,782 | 213,694 | 60 | 274,416 | 12 |
| Pirate | 61,020 | 0 | 21,850 | 39,170 | 60 | 60,960 | 15 |

Each frame samples eight visible-support candidates and two baseline-hidden controls by frozen
priority quantiles. Not sampled does NOT mean uninformative. Hidden candidates are not discarded
as zero, because movement/disocclusion can make them visible. Reference-zero cases remain in JSON.
Primary ranking comparisons are stratified by visible support and actual submitted triangle count,
so hidden no-op candidates cannot trivially conceal bad choices on visible geometry.

## 2. Frontmost depth-aware reference

180 candidates were evaluated; respectively 48, 48 and 45 had nonzero depth-channel error.
All 180 patch redraws were verified against independent full-frame redraws; maximum absolute
per-pixel discrepancies were 4.99e-16, 3.95e-16 and 3.58e-16. Unchanged geometry participates in
z-resolution, including occluders outside the affected topological neighborhood.

This reference is still sampled, two-sided, orthographic coverage plus normalized premultiplied
depth. It is not a full shaded renderer or a continuous error bound. 3x supersampling is not
certified ground truth for arbitrarily small changes.

## 3. 8/16/32-dimensional comparison: negative result

The tested predictor uses 1x patch rasterization, filtering, and exactly 8/16/32 TOTAL real DCT
coefficients across the two channels. It is not the earlier per-scanline Fourier strip algorithm.
It is not an analytic no-raster predictor. Applying the same representation to the reference is
reported separately as a representation oracle and includes reference-rendering cost.

For these 18 visible-support matched-budget groups, 8/16/32 dimensions selected the same paths.

| Asset | Improved / worse / unchanged frames vs Corner priority | Baseline total SSE | Predicted-choice true SSE | Reference oracle SSE |
|---|---:|---:|---:|---:|
| Torus | 2 / 4 / 0 | 0.0000671548 | 0.0210195 | 0.0000567901 |
| Monkey | 3 / 3 / 0 | 0.000000125970 | 0.00137814 | 0.0000000535127 |
| Pirate | 3 / 1 / 2 | 0.000000000829135 | 0.00460162 | 0.000000000333245 |

These are sums of coverage+depth SSE over the six selected frames, not RGB PSNR. Large relative
regressions can coexist with tiny visual changes because the baseline error is near zero. The
result nevertheless rejects the current coarse-raster predictor as a safe replacement.

Worst cases expose sampling loss BEFORE encoding:

- Monkey frame 1 / candidate 22582: 32-D predicts exactly zero, reference total 0.00120366.
  Encoding the reference residual instead gives 0.000454037, so representation dimension is not
  the main cause of this zero prediction.
- Pirate frame 3 / candidate 1012: predicts about 2.7e-33, reference 0.00460162.
- Torus frame 0 / candidate 3288: predicts 9.59e-8, reference 0.0115063.

These comparisons support coarse sampling as a failure mechanism at the tested sample grid.
They do not establish continuous-image truth or rule out every other approximation error.

## 4. Cost: no deployable acceleration claim

| Asset | Median reference patch ms | Median coarse raster + basis + encoding ms | Median per-case reference/predictor ratio |
|---|---:|---:|---:|
| Torus | 11.46 | 10.92 | 1.20x |
| Monkey | 98.14 | 64.24 | 1.60x |
| Pirate | 113.45 | 67.20 | 1.44x |

Python single-pass CPU timings, no confidence interval. The coarse timing computes 32 coefficients
once, with 8/16 from prefixes; do not claim independently measured per-dimension timings.
Preparation, frame setup, candidate capture, full-frame validation and output are separate; the
above are not total frame times. Quality fails, so these ratios are not a successful quality-time
tradeoff and must not be presented as GPU speedups.

## 5. Overlays and temporal scope

Worst-case selection is by largest measured regression, not manually picked imagery. The audit
reprojects the entire edited vertex buffer under the frozen camera independently of singleton
target projection, and re-renders the saved true error. Both checks passed for all three assets.

Inspected Torus normal-case overlay plus Monkey and Pirate worst-case overlays. Marked edits lie
near the visible lower boundary/notch on Monkey and the lower leg/foot on Pirate. Patch rectangles
cover those edits. The 32x Monkey depth residual remains faint and local. This supports a subpixel
coverage/depth issue, not a visually dramatic break. These low-resolution diagnostic images do not
prove perceptually improved geometry.

There are 29/20/19 adjacent fixed-candidate screen-residual comparisons on the new six-frame
trajectories. They are not motion-compensated flicker or runtime LOD switching tests. No synthetic
strip result is mixed into this real-asset report.

## Decision and next hypothesis

Do NOT enable the coarse-raster low-dimensional predictor in the production simplifier.
Do NOT infer that increasing sketch dimension will repair samples absent from the raster.

The user's mesh/rasterization coupling suggestion suggests a testable next direction: cache a
shared visibility/coverage representation, cheaply score stable interiors, and use geometric
coverage/depth-event checks to trigger localized accurate work. The trigger must be evaluated
without reference error (avoid oracle leakage), and its full extraction/maintenance cost must be
included. Existing image-driven simplification, analytic rasterization and visibility reuse are
strong prior work; such a coupling is a hypothesis, not an established new contribution.

## Validation state

- Seven Python reference/projection/sketch tests passed; Python scripts compile.
- Most recent C++ ManyMesh suite: 91 passed, one HTTP environment skip; candidate exporter builds.
- `git diff --check` passed before final report documentation.
- Mandatory full desktop Debug re-attempt still fails because prebuilt-tools cache selects GNU,
  rejected by repository CMake. No claim of full desktop build success.
- Earlier utils test failure (333 pass / 1 JobPool exhaustion fail) remains unresolved.
- No commit or push performed.
