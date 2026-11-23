# Cluster decoder against meshoptimizer

Date: 2026-11-22. This development screen compares same-face geometry on the
existing Thingi10K train/validation subset. It does not use the held-out test
split and does not establish a publication result.

## Results

At each prepared asset's fast-simplification QEM face count, vendored
meshoptimizer 0.18.1 (`LockBorder`) was compared with the QEM mesh. On the five
paired validation assets, meshoptimizer improved every reported image metric:

| Metric | QEM | meshoptimizer | Paired change and 95% asset bootstrap interval |
|---|---:|---:|---:|
| PSNR (dB) | 30.77 | 40.49 | +9.72 [+6.48, +12.55] |
| SSIM | 0.9582 | 0.9888 | +0.0306 [+0.0116, +0.0582] |
| LDR-FLIP | 0.02530 | 0.00775 | -0.01755 [-0.03536, -0.00661] |
| LPIPS-SqueezeNet | 0.02386 | 0.00581 | -0.01805 [-0.03399, -0.00714] |
| Silhouette XOR | 0.715% | 0.0685% | -0.647 percentage points [-1.712, -0.074] |
| Sampled bidirectional Chamfer L1 | 0.01168 | 0.00836 | -0.00332 [-0.00776, -0.00037] |

The same rank-8 linear decoder was retrained on meshoptimizer bases. Its fixed
topology output exactly matches the baseline on all five validation assets for
the measured image metrics: the fitted displacements are effectively zero.
This is expected for this setup because the simplifier selects source vertices
and the nearest-surface residual labels therefore contain no useful displacement
signal. It shows that this rank-8 formulation cannot recover additional detail
from these bases; it is not a general result about learned decoders.

The per-asset changes below show the spread behind the validation averages.
Positive PSNR/SSIM changes are better; negative FLIP, LPIPS, silhouette XOR, and
Chamfer changes are better. Face counts are matched within each row.

| Validation asset ID | Faces | PSNR (dB) | SSIM | LDR-FLIP | LPIPS | Silhouette XOR (pp) | Sampled Chamfer L1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 90431 | 466 | +14.240 | +0.08254 | -0.05261 | -0.04947 | -2.7753 | -0.011904 |
| 263198 | 154 | +10.617 | +0.02280 | -0.00949 | -0.01346 | -0.2003 | -0.003082 |
| 44710 | 950 | +3.719 | +0.01543 | -0.00776 | -0.00805 | -0.1027 | -0.000220 |
| 383021 | 4,136 | +11.415 | +0.00408 | -0.00401 | -0.00349 | -0.0231 | +0.000001 |
| 100894 | 1,746 | +8.622 | +0.02818 | -0.01387 | -0.01576 | -0.1324 | -0.001412 |

The five image-metric directions agree on all five assets. Sampled Chamfer L1
improves on four and is effectively tied but slightly worse on asset 383021.
This is still only five of the eight validation assets: three were excluded by
the predeclared geometry checks. A follow-up source audit confirmed that all
three raw STL meshes pass the source topology check. The rejected geometries
were produced by the fast-simplification QEM preparation: two coarse outputs
contained duplicate geometric triangles and one contained a degenerate
triangle. They are simplifier-output failures, not malformed input assets.
Regenerating valid QEM bases with the same frozen implementation is required
before they can enter this paired comparison. The table does not turn the
remaining subset into broad generalization evidence.

The recheck verified the source hashes and repeated the original normalization
and source-topology validation for all eight validation STL files: 8/8 pass.
The three QEM preparation failures occur after source validation, when the
generated coarse mesh is checked. See the [machine-readable audit](cluster_decoder_validation_failure_audit_20261122.json)
and [reproduction script](audit_cluster_decoder_qem_failures.py).

The budgeted refinement branch split selected faces and was compared against
meshoptimizer simplified directly from the source to exactly the same final face
count. On four paired validation assets, the decoder refinement was worse on
each image metric:

| Metric | Decoder minus meshoptimizer | 95% paired asset bootstrap interval |
|---|---:|---:|
| PSNR (dB) | -2.015 | [-2.246, -1.784] |
| SSIM | -0.00480 | [-0.00991, -0.00148] |
| LDR-FLIP | +0.00278 | [+0.00116, +0.00489] |
| LPIPS-SqueezeNet | +0.00222 | [+0.00099, +0.00347] |
| Silhouette XOR | +0.0369 percentage points | [+0.0205, +0.0661] |

Sampled Chamfer L1 was also worse on all four paired validation assets
(+0.0000572; interval [+0.0000117, +0.0001027]). These intervals resample
assets, not the correlated camera views. The refinement comparison is small
and one otherwise valid case was rejected by the high-budget meshoptimizer
duplicate-face audit; the denominator is the four valid paired cases.

## Protocol and limits

Images use 12 orthographic, flat-shaded views per asset at 256x256 with 4x
box sampling, 8-bit sRGB, canonical Gaussian-window SSIM, NVIDIA LDR-FLIP at
67 pixels per degree, and calibrated LPIPS SqueezeNet v0.1. Surface values use
20,000 area-uniform samples in each direction and nearest sampled-point-cloud
distances. They are estimates, not exact Hausdorff bounds. These are geometry-only
STL comparisons; they do not evaluate authored attributes, materials, temporal
LOD popping, perceptual preference, runtime rendering, mobile devices, or
production compression.

The decoder refinement used reference-derived residuals to choose faces; it is
an offline source-aware encoding control, not an online predictor. The compared
storage numbers are prototype NPZ artifact sizes and are not production rate-
distortion measurements. No `.mmb` or renderer API changed.

The 24-row development manifests preserve preparation and method failures.
Nine train and five validation assets prepared for the same-face QEM comparison;
six train and five validation assets completed the decoder-base fitting/evaluation
path. The equal-final-face refinement comparison contains five train and four
validation pairs. No test assets were evaluated.

## Decision

Stop this rank-8 fixed-displacement and local-refinement configuration. Neither
passed the validation gate against a strong same-face meshoptimizer baseline.
This does not rule out other decoder architectures or objectives. Any new
configuration must be frozen on train/validation, include a fresh licensed
confirmation set for a paper claim, and pass the same image, surface, topology,
boundary, byte, and load-cost gates before production integration.

## Reproduction artifacts

- [Same-face baseline and fixed-decoder receipt](cluster_decoder_meshopt_screen_20261122.json)
- [Equal-final-face refinement receipt](cluster_decoder_refine_budget_20261122.json)
- [Baseline builder](cluster_decoder_meshopt_baseline.py)
- [Same-face quality evaluator](cluster_decoder_meshopt_quality.py)
- [Meshoptimizer-base label preparation](cluster_decoder_pairs_meshopt.py)
- [Equal-budget refinement evaluator](cluster_decoder_refine_budget_quality.py)
- [Validation QEM failure audit](audit_cluster_decoder_qem_failures.py) and [receipt](cluster_decoder_validation_failure_audit_20261122.json)
- [Vendored meshoptimizer JS/WASM driver](meshopt_simplify.cjs)

Full generated reports and image galleries are retained under ignored `out/`
directories named `cluster-decoder-meshopt-quality`,
`cluster-decoder-quality-meshopt`, and
`cluster-decoder-refine-budget-quality`.
