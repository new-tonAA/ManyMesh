# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready contribution is established.** No
physical-phone performance, user preference, or positive held-out method result
has been measured.

## Research question

Can offline geometry optimization improve a cluster LOD after the same
antialiasing or upscaling pipeline, against strong controls at matched face
count and full cost? This remains an untested hypothesis with close prior art;
it is not a novelty claim. DMesh++ already combines multi-view image losses,
changing topology, and antialiasing-derived visibility gradients for mesh
reconstruction. See the [SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md)
and [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).

## Evidence that sets the direction

- The eligible 21-model screen found the current ManyMesh cuts worse than
  border-preserving QEM and meshoptimizer on LDR-FLIP, PSNR, SSIM, and silhouette
  XOR, both with native sampling and 4x MSAA. The tested cut is closed as a
  quality-improving method. See the [protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md)
  and [per-view metrics](tools/mmtrain/polyhaven_quality_metrics_20261124.json).
- A source-referenced Monkey diagnostic found silhouette XOR accounted for
  25.84%-34.75% of squared error across three tested budgets, not the historical
  68.3%. The candidate also lost to eligible exact-face controls. This is a
  single-asset diagnostic, not a general silhouette result. See the
  [report](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- Earlier contour-priority and fixed-topology fitting screens did not show a
  repeatable quality gain. The 64-view contour control's +0.167 dB development
  PSNR result had mixed FLIP and no reliable AA follow-up gain. See the
  [contour screen](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md),
  [AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md), and
  [fit report](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md).
- A 10,000-instance BarramundiFish desktop diagnostic reduced GPU raster p50
  from 26.15 ms to 6.66 ms (3.93x), with small image-metric regressions. It is
  one asset and one view at unequal face counts; it does not establish a
  ManyMesh method result. See the [protocol and limits](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).
- A fresh candidate pool now contains 30 unscored models across 25 source
  families and nine categories. Each has topology- and boundary-eligible
  ManyMesh, QEM, and meshoptimizer outputs at the same face count. This is a
  pre-score cohort, not held-out quality evidence. See the
  [pool report](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md) and
  [manifest](tools/mmtrain/polyhaven_confirmation_pool_20261125.json).

## Next decision

Run the frozen fixed-topology placement control on CUDA for BarramundiFish and
Corset. Both inputs pass CPU preparation at 1,932 and 9,162 faces, but the
current host has CPU-only PyTorch and no CUDA runtime. No fit or quality scoring
has run. A fresh CPU-only preparation repeat produced byte-identical protocols
for both assets, but the base Python environment emitted a NumPy/SciPy version
warning; use the pinned isolated environment for the CUDA run. See the
[repeat receipt](tools/mmtrain/appearance_cuda_preflight_repeat_20261125.json).
The control uses a pinned nvdiffmodeling adapter; it is not a faithful
reproduction of Hasselgren et al. and does not optimize through final hardware
MSAA or an upscaler. If it fails to improve reserved-view quality at matched
faces without topology regressions, close this configuration. Only a pass
opens a frozen, asset-held-out study of the cluster-DAG distinction. See the
[Gate 1 protocol](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md) and
[machine-readable receipt](tools/mmtrain/appearance_cuda_protocol_20261124.json).

## Measurement gaps

No physical-phone test, equal-complete-frame-time quality comparison, LPIPS,
moving-camera temporal quality, user study, or positive held-out optimized
method result is available. Desktop timings do not support mobile claims.

## Project documents

- [SIGGRAPH 2027 direction](SIGGRAPH_2027_DIRECTION.md)
- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Research roadmap](MANYMESH_RESEARCH_ROADMAP.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Filament documentation](filament/README.md)
