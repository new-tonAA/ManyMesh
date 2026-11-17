# Complementary geometry states: preflight protocol

2026-11-14. Research hypothesis, not established novelty. Parameters below are fixed before
running the pilot. All assets are previously inspected development assets.

## Proposed research object

Construct several equal-face-count, topology-valid coarse states jointly, so their signed rendered
errors complement each other under temporal reconstruction. Use a residual bias certificate to
decide when temporal scheduling cannot meet an error target and geometric refinement is necessary.
The possible contribution must be the constrained geometric construction plus a cheap, conservative
runtime decision; mixing images, temporal dithering, Frank-Wolfe, and convex hulls are not new.

For fixed camera, linear filter, static appearance and residual vectors d_i of admissible states,
an ideal nonnegative normalized temporal average has residual D w, w >= 0, sum w = 1.
Its best achievable squared bias within this FINITE state set is

    B = min_{w in simplex} ||D w||^2.

For any feasible w, E = w^T G w and g = 2(E - min_i (G w)_i) give
max(0, E-g) <= B <= E (Frank-Wolfe primal/dual gap). A finite iteration result is not an exact
optimum. The bound does not apply to unenumerated placements, nonlinear TAA clamping, changing
visibility/cameras, signed reconstruction weights or arbitrary future geometry.

For independently sampled states with probabilities w, the T-sample mean has expected SSE
B_w + (sum_i w_i ||d_i||^2 - B_w)/T. This distinguishes bias from temporal variance.
Deterministic schedules can change variance; their transitions and flicker are still not free.

At an unfiltered binary coverage sample, all residuals relative to the binary reference have the
same sign. Therefore exact unbiased coverage needs every positive-weight state to reproduce that
sample. Temporal reuse alone cannot restore an always-missing opaque sample. Spatial filtering
can mix opposite-signed errors at different samples, so the filtered case needs actual measurement.

## Closest work and present evidence

- Cook et al., Stochastic Simplification of Aggregate Detail (SIGGRAPH 2007): stochastic selection
  and statistical alteration of aggregate primitives already exist. Publisher abstract and indexed
  paper text inspected; direct Pixar PDF now redirects. Not a full equivalence review.
  https://doi.org/10.1145/1276377.1276476
- Alexa and Kyprianidis, Error Diffusion on Meshes (2015): diffusion on surface graphs, quantization
  and vertex subset selection already exist. Author PDF inspected, especially introduction and
  application scope. No claim that geometric error diffusion is new.
  https://www.kyprianidis.com/p/smi2014/alexa-smi2014.pdf
- Wang et al., Real-Time Level-of-Detail Rendering with ReSTIR (SIGGRAPH 2026): surface-point
  mappings preserve reuse across topology-changing LoD. Thus cross-LOD history transport is not
  a standalone contribution. The proposed object changes the coarse representation to complement
  signed residuals, rather than only transporting samples across supplied LoDs; equivalence with
  the full wider literature remains unresolved.
  https://research.nvidia.com/labs/rtr/publication/wang2026levelOfDetail/wang2026levelOfDetail.pdf
- Image-driven simplification and appearance-driven optimization remain mandatory static baselines.
  An oracle mixing poor states is insufficient if optimizing one static state obtains the same gain.

## Frozen preflight experiment

- All 144 visible-support candidate/frame entries from the existing depth trajectory reports.
- Same capture, original camera, 128px, 3x sampling, sigma 0.9; use report values and record hashes.
- Each candidate keeps ONE collapse connectivity, hence equal triangle count across variants.
- Proposals: original Corner target, midpoint, both endpoints, and target +/- 0.25 edge length
  along each of the three world coordinate axes. No reference-image optimization generates these.
- Retain the seed; other states must pass the existing geometry-only endpoint-distance,
  orientation and triangle-quality guard. This is not full UV/material/Corner gate validation.
- Compare original seed, BEST static state in this exact pool, uniform mixture, and convex mixture.
- Report population sums, all one-state/zero-error cases, primal/dual gaps, 8/16-frame IID expected
  error, and measured offline evaluation cost. Save residual matrices and positions for reuse.
- This is an optimistic fixed-camera necessary-evidence check, not TAA or runtime performance.
- Continue to joint state construction only if at least two of three assets show >=10% aggregate
  bias reduction over best-static pool and >=10% of their candidates show >=10% reduction.
  These are research screening thresholds, not a publishability test. Failure stops THIS proposal
  generator; it cannot prove that all possible complementary meshes are useless.

If this passes, freeze new assets/cameras, compare joint construction against equal-budget static
optimization, and explicitly charge state updates and switching. If it fails, do not rename the
convex optimizer as an innovation or infer a deployment benefit from a selected positive example.
