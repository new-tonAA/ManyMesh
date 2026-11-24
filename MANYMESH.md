# ManyMesh research status

Updated 2026-11-24. **No SIGGRAPH-ready contribution is established.** ManyMesh
is a desktop research prototype with no validated mobile or user-preference
claim.

## Research question

Can offline appearance optimization improve a constrained triangle-mesh cluster
LOD hierarchy after antialiasing or upscaling, at equal geometry and complete
rendering cost? This is a hypothesis with substantial prior art, not a novelty
claim. See the [prior-art review](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md) and
[SIGGRAPH plan](SIGGRAPH_2027_SUBMISSION_PLAN.md).

## Evidence

- At matched 720p 4x MSAA, the contour neighborhood carries 57.09%-86.33% of
  squared error in three reused desktop scenes. LPIPS supports no
  equal-cost allocation win. [Scene replay](tools/mmmetrics/MOVING_SCENE_EDGE_QUALITY_20261124.md)
- Near 50% retention, 21 preselected Poly Haven assets across six classes had
  legal, exact-face ManyMesh, QEM, and meshoptimizer controls. On the fixed
  Iris Xe image-quality screen, group-mean ManyMesh quality was worse than both
  controls on FLIP, PSNR, SSIM, and silhouette XOR in native and 4x MSAA modes.
  The paired 95% intervals exclude zero across 16 source groups. This closes the
  tested ManyMesh cut as a quality-improving method. [Protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md)
  · [all per-view metrics](tools/mmtrain/polyhaven_quality_metrics_20261124.json)
- The expanded source screen yielded 18 additional exact-face eligible assets;
  28 of 46 topology-valid candidates failed at least one matched-face or
  boundary gate. [Source and eligibility report](tools/mmtrain/POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md)

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
- The earlier Khronos source screen had one provisional geometry-pass asset
  (CommercialRefrigerator); CarConcept failed strict topology and contains
  separately licensed marks. That screen predates the Poly Haven matched-face
  cohort reported above.
  [Source, license, and topology receipts](docs/manymesh/confirmation-asset-screen-20261123.md)
- CommercialRefrigerator and ScatterPlant supplied zero complete sets of legal
  meshes near 30% retention for the appearance fitting baseline. The preflight
  caught boundary, topology, and face count failures before scoring images.
  [Report and receipts](tools/mmtrain/APPEARANCE_INPUT_PREFLIGHT_20261123.md)
- A 64-view source contour priority raised mean PSNR by 0.167 dB over the
  same unweighted QEM on seven development assets at equal faces. FLIP
  was mixed. [Contour priority report](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md)
- On Iris Xe, the same seven mesh pairs showed no consistent FLIP gain
  with hardware MSAA, SMAA, or bicubic upscaling. Native FLIP worsened
  on all seven. [Desktop AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md)
- A local fixed topology fit improved training coverage on three assets.
  Reserved-view FLIP improved slightly on one. A separate Mitsuba projective
  fit worsened reserved-view FLIP on both development assets.
  [Projective fit](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md) and
  [local fit](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md)

Older fixed-view, AA, and draw-submission measurements remain in the
[dated history](MANYMESH_HISTORY.md) with their reference and provenance
limits; they are not current method evidence.

No phone test, equal-frame-time image-quality comparison, or user study exists.
The repository also contains negative decoder, temporal, and rate-distortion
screens; the [evidence ledger](MANYMESH_CLAIM_EVIDENCE.md) links their raw
receipts and limitations.

## Next gate

1. Keep the failed contour selector closed; do not start a custom differentiable
   DAG optimizer yet.
2. Run the matched-face differentiable baseline on CUDA with the frozen
   BarramundiFish and Corset development inputs. The training schedule and
   reserved-view scorer are pinned. The 21-model Poly Haven cohort has now been
   used for the fixed-baseline evaluation; any method developed from this result
   needs a separate untouched confirmation cohort.
   [Matched inputs and scoring protocol](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
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
