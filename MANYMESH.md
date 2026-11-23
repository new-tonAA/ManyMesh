# ManyMesh research status

Updated 2026-11-23. **No SIGGRAPH-ready contribution is established.** ManyMesh
is a desktop research prototype with no validated mobile or user-preference
claim.

## Research question

Can offline appearance optimization improve a constrained triangle-mesh cluster
LOD hierarchy after antialiasing or upscaling, at equal geometry and complete
rendering cost? This is a hypothesis with substantial prior art, not a novelty
claim. See the [prior-art review](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md) and
[SIGGRAPH plan](SIGGRAPH_2027_SUBMISSION_PLAN.md).

## Evidence

- In a fixed-view 13-asset Iris Xe screen, calibrated component cuts plus 4x
  MSAA were faster than full-source native rendering on 4/13 assets and faster
  while improving both PSNR and SSIM on 2/13. The per-asset choices are not a
  deployable selection method. [Protocol and results](tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md)
- On original-source Monkey, three current DAG cuts lost to eligible exact-face
  QEM or meshoptimizer controls on every reported image metric. The geometric
  boundary tolerance was chosen after the first score; this is a one-asset
  development diagnostic. [Report](tools/mmtrain/MONKEY_ORIGINAL_SOURCE_DIAGNOSTIC_20261123.md)
- A seven-asset Khronos development screen compared current cuts against the
  original source meshes. Under a retrospective one-float32-ULP boundary rule,
  15 of 21 cuts were eligible. Across 18 eligible exact-face control pairs,
  ManyMesh lost all five image metrics in 15, won all five in two
  meshoptimizer comparisons on a 987-face GlassBrokenWindow, and had one mixed
  result; it did not beat any eligible QEM pair. The boundary rule was selected
  after an earlier run, and the data are reused development assets, not held-out
  confirmation. No timing, phone, or upscaler result was measured.
  [Report](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md) ·
  [compact metrics and hashes](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json)
  GlassBrokenWindow's border-preserving QEM returned 859 faces for all three
  requested cuts, so the two wins are against meshoptimizer alone.
- The contour-risk selector produced no useful equal-face alternatives in its
  12-asset screen. On reused Lucy, the DAG could not reach the requested 30%
  face budget and legal cuts lost to exact-face controls. [Selector report](tools/mmgeo/CONTOUR_SELECTOR_BUDGET_SCREEN_20261123.md) · [Lucy report](tools/mmtrain/LUCY_CURRENT_SOURCE_QUALITY_SCREEN_20261123.md)
- The independent Khronos source screen has one provisional geometry-pass asset
  (CommercialRefrigerator); CarConcept failed strict topology and contains
  separately licensed marks. There is still no clean pair or confirmation set.
  [Source, license, and topology receipts](docs/manymesh/confirmation-asset-screen-20261123.md)

Older fixed-view, AA, and draw-submission measurements remain in the
[dated history](MANYMESH_HISTORY.md) with their reference and provenance
limits; they are not current method evidence.

No phone test, user study, or independent licensed confirmation set exists.
The repository also contains negative decoder, temporal, and rate-distortion
screens; the [evidence ledger](MANYMESH_CLAIM_EVIDENCE.md) links their raw
receipts and limitations.

## Next gate

1. Keep the failed contour selector closed; do not start a custom differentiable
   DAG optimizer yet.
2. Run the matched-face differentiable simplification baseline on cleared
   assets with CUDA-capable compute. Freeze views and metrics, then evaluate on
   held-out assets. The current host lacks CUDA and there is no clean local
   confirmation-asset pair. See the [asset screen](MANYMESH_CONFIRMATION_ASSET_SCREEN.md)
   and [falsification protocol](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md#cheap-falsification-before-a-custom-method).
3. Continue only after repeatable held-out gains at matched face count. Then
   compare boundary treatment, real AA/upscalers, complete frame cost, and
   camera-motion stability. Mobile or preference claims require separate
   device measurements or a user study.

## Project documents

- [SIGGRAPH 2027 direction and closest prior art](SIGGRAPH_2027_DIRECTION.md)
- [SIGGRAPH 2027 submission plan](SIGGRAPH_2027_SUBMISSION_PLAN.md)
- [Prior-art review](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md)
- [Dated evidence history](MANYMESH_HISTORY.md)
- [Claim and provenance ledger](MANYMESH_CLAIM_EVIDENCE.md)
- [Filament documentation](filament/README.md)
