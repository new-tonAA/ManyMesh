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
- The rank-8, rank-16, and rank-30 fixed-topology residual decoders all lost
  to matched-face QEM on their reported validation image metrics; the
  budgeted-refinement variant lost to same-face meshoptimizer on four paired
  assets. This closes the tested configurations, not learned decoders in general.
  [Rank sweep](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md) and
  [baseline comparison](tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md).
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
  control remains unrun. A post-hoc GPU-budget screen found a cheaper control
  dominating both half-resolution silhouette-guide fusion variants on LDR-FLIP,
  PSNR, and SSIM for all 13 reused assets; this is exploratory, not confirmation.
  [Guide-fusion report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md) ·
  [Contour](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md) ·
  [AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md) ·
  [fit report](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md).
- A 10,000-instance desktop screen shows a raster-time reduction from coarse
  geometry, but not a ManyMesh method win, complete-frame result, or mobile
  result. [Protocol and limits](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next experiment

Run the frozen fixed-topology placement control on BarramundiFish and Corset at
1,932 and 9,162 faces. CPU preparation passed; fitting and scoring have not run.
The default Python has CPU-only PyTorch. A secondary Conda environment contains
CUDA 11.7 packages, but PyTorch import is blocked by Windows application
control; this environment cannot currently verify a CUDA device or compile the
renderer extension. Do not treat preparation as a fit result. The pinned
nvdiffmodeling adapter is not a faithful Hasselgren reproduction and does not
optimize through final hardware MSAA or an upscaler.
A failure on reserved views closes this configuration. A pass only opens a
separate asset-held-out cluster-DAG study; it proves neither generalization nor
novelty.
The DEODR CPU fallback could not be built because Cython and source access are
unavailable on this host; no fitting or scoring occurred. [CPU-backend preflight](tools/mmtrain/DEODR_CPU_BACKEND_PREFLIGHT_20261125.md).
[CUDA environment recheck](tools/mmtrain/CUDA_ENVIRONMENT_RECHECK_20261125.md).

- [Frozen protocol and inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
- [Protocol JSON](tools/mmtrain/appearance_cuda_protocol_20261124.json) ·
  [CPU preflight receipt](tools/mmtrain/appearance_cuda_preflight_repeat_20261125.json)
- [SIGGRAPH direction and prior-art limits](SIGGRAPH_2027_DIRECTION.md)

## Evidence gaps

No physical-phone test, equal-complete-frame-time comparison, user study, or
positive held-out optimized-method result is available. A 13-asset moving-camera
screen scored with CGVQM-5 found a selected-profile minus area-policy mean of
-0.0590 (95% asset-bootstrap CI [-0.1476, +0.0424]); 4 assets improved and 9
regressed. This reused-data, flat-shaded desktop screen did not establish a
temporal-quality gain. A separate three-scene screen measured LPIPS and
temporal metrics without establishing an equal-time quality gain. The fresh
30-model Poly Haven set now has frozen
inputs and a scoring protocol, but remains unscored until the method
configuration is frozen. It evaluates a fixed per-asset procedure on unseen
assets; it does not test cross-asset neural-model transfer. See the
[confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md),
[pool provenance](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md), and
[moving-camera LPIPS and temporal screen](tools/mmmetrics/MOVING_SCENE_EDGE_QUALITY_20261124.md).
Desktop results do not support mobile claims.

## Research index

- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md) ·
  [Roadmap](MANYMESH_RESEARCH_ROADMAP.md) ·
  [Dated experiment history](MANYMESH_HISTORY.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md) ·
  [Filament documentation](filament/README.md)
