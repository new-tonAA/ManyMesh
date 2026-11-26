# QEM-initialized projective RGB fit: development protocol

Frozen before scoring on 2026-11-27. This is a two-asset development screen,
not a confirmation study or novelty claim.

## Question and comparison

Does the existing fixed-topology projective RGB fit improve a border-preserving
QEM mesh when both use the same exact 50% face budget? For each of the same two
reused development assets, use the QEM mesh already scored in the exact-face
QEM control as the fit initializer, preserve that QEM topology, and lock its
open-boundary vertices. Compare the resulting fit directly with that QEM mesh.

The source OBJ, normalized source geometry, training cameras, 24 held-out
cameras, 96 x 96 resolution, Mitsuba 3.9.0 `llvm_ad_rgb` renderer, neutral
material, lighting, seeds, 8 fit iterations, 0.012 maximum displacement, 4
training samples per pixel, and 16 held-out samples per pixel remain those of
the [CPU RGB protocol](PROJECTIVE_RGB_CPU_PROTOCOL_20261125.md). No camera,
asset, metric, or threshold is selected after observing this run.

## Eligibility and decision gate

Score image quality only if the candidate has the exact target face count,
uses exactly the QEM faces (fixed topology), passes the source-boundary audit,
and preserves the initial QEM face orientation constraint used by the fit.
Report per-view and aggregate PSNR, SSIM, and LDR-FLIP; lower FLIP is better.
Also record accepted optimizer steps, wall time, peak memory if available, and
geometry archive size.

Reuse the fit's existing per-asset acceptance thresholds against the QEM
initializer: at least one accepted optimizer step, mean LDR-FLIP strictly
lower than QEM, pooled PSNR no worse than 0.1 dB below QEM, and mean SSIM no
worse than 0.001 below QEM. Both assets must satisfy all conditions for this
configuration to pass the development screen. Any ineligible asset or failed
asset closes this QEM-initialized configuration; do not score the reserved
30-model pool. Passing on these reused assets only justifies separately frozen
confirmation, not an asset-generalization claim.

The fit and QEM use the same face count but different fitted vertex positions;
all optimization is offline. This protocol makes no GPU, mobile, frame-time,
MSAA, upscaler, temporal, or perceptual-preference claim.

## Strong-baseline amendment before the final local scoring pass

The initial frozen screen compared the QEM-initialized fit only with raw QEM and
met that narrow gate on both reused assets. Before deciding to advance, the
existing CI artifact was inspected and shown to contain the meshoptimizer
initializer and its fitted result at the same face count and on the same views.
That is a necessary stronger control. This amendment is frozen before the
same-host four-candidate rerender; it adds no assets or threshold tuning.

Score raw QEM, QEM-initialized fit, raw meshoptimizer, and the existing
meshoptimizer-initialized fit in one local render pass. The QEM-initialized fit
must satisfy the already stated thresholds against both raw QEM and
meshoptimizer-initialized fit on each asset. A missing arm, eligibility failure,
or failed per-asset comparison closes this configuration; a pass remains only
a development signal. The earlier two-arm QEM-only result stays reported as
such and is not overwritten.