# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready method is established.** The tested
ManyMesh cut loses to matched-face controls, and no optimized method has a
positive held-out result.

## What the evidence says

- In a frozen 21-model screen, ManyMesh lost to border-preserving QEM and
  meshoptimizer on LDR-FLIP, PSNR, SSIM, and silhouette XOR, with native
  sampling and 4x MSAA. A familywise max-t audit across the 16 primary
  comparisons leaves all 95% simultaneous intervals favoring the controls.
  [Protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) ·
  [Multiplicity audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).
- A post-hoc LPIPS supplement re-rendered the same 21 models. ManyMesh scored
  worse than both controls in native and 4x MSAA: the ManyMesh-minus-control
  deltas are +0.00127 to +0.00267, and all four paired 95% group intervals
  exclude zero. This reuses the previously examined cohort and is descriptive,
  not independent confirmation. [Protocol and results](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md).
- Silhouette error depends on view and reference. The historical 68.3% used a
  DAG cut, not the source mesh; a source-referenced Monkey diagnostic measured
  25.84%-34.75% at three budgets on one asset. This is not a general result.
  [Diagnostic](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- Prior contour-priority and contour-guided fixed-topology fitting screens
  showed no repeatable quality gain; the separate frozen appearance-placement
  control remains unrun. [Contour](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md) ·
  [AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md) ·
  [fit report](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md).
- A 10,000-instance desktop screen shows a raster-time reduction from coarse
  geometry, but not a ManyMesh method win, complete-frame result, or mobile
  result. [Protocol and limits](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next experiment

Run the frozen fixed-topology placement control on BarramundiFish and Corset at
1,932 and 9,162 faces. CPU preparation passed; fitting and scoring have not run
because the available host has CPU-only PyTorch. Do not treat preparation as a
fit result. The pinned nvdiffmodeling adapter is not a faithful Hasselgren
reproduction and does not optimize through final hardware MSAA or an upscaler.
A failure on reserved views closes this configuration. A pass only opens a
separate asset-held-out cluster-DAG study; it proves neither generalization nor
novelty.

- [Frozen protocol and inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
- [Protocol JSON](tools/mmtrain/appearance_cuda_protocol_20261124.json) ·
  [CPU preflight receipt](tools/mmtrain/appearance_cuda_preflight_repeat_20261125.json)
- [SIGGRAPH direction and prior-art limits](SIGGRAPH_2027_DIRECTION.md)

## Evidence gaps

No physical-phone test, equal-complete-frame-time comparison, user study, or
positive held-out optimized-method result is available. A separate three-scene
moving-camera screen measured LPIPS and temporal metrics but did not establish
an equal-time quality gain. The newer 30-model Poly Haven pool is unscored and
is not a frozen test split ([pool report](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md)).
See the [moving-camera LPIPS and temporal screen](tools/mmmetrics/MOVING_SCENE_EDGE_QUALITY_20261124.md).
Desktop results do not support mobile claims.

## Research index

- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md) ·
  [Roadmap](MANYMESH_RESEARCH_ROADMAP.md) ·
  [Dated experiment history](MANYMESH_HISTORY.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md) ·
  [Filament documentation](filament/README.md)
