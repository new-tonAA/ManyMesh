# ManyMesh research status

Updated 2026-11-24. **No SIGGRAPH-ready contribution is established.** The
project has no validated mobile-performance or user-preference claim.

## Current question

Can offline geometry optimization improve a cluster LOD hierarchy when judged
after a specified final reconstruction pipeline, at matched face count and
complete runtime cost? This is an untested hypothesis, not a novelty claim.
Hasselgren et al. already optimize mesh appearance with image-space losses and
use MSAA during fitting to improve silhouette gradients. See the
[prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md) and
[SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md).

## Evidence

- **21-model matched-face screen:** Near 50% retention, the tested ManyMesh cut
  scored worse than border-preserving QEM and meshoptimizer on LDR-FLIP, PSNR,
  SSIM, and silhouette XOR, with native sampling and 4x MSAA. Paired 95%
  intervals exclude zero across 16 source groups. This closes the tested cut,
  not every possible geometry method. It is fixed-view desktop evidence, not an
  equal-time or mobile result. Source provenance remains unresolved: the
  Poly Haven and Khronos receipts pin the same executable hash but record
  different `main.cpp` hashes. See the [provenance audit](tools/mmtrain/mmgeo_source_provenance_audit_20261124.json).
  [Protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) ·
  [per-view metrics](tools/mmtrain/polyhaven_quality_metrics_20261124.json) ·
  [21/21 exact score replay](tools/mmtrain/POLYHAVEN_SCORE_REPLAY_AUDIT_20261124.md)
- **Expanded eligibility screen:** 18 additional exact-face eligible assets
  were found; 28 of 46 topology-valid candidates failed a face-count or
  boundary gate. [Report](tools/mmtrain/POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md)
- **Seven-asset Khronos screen:** Under a retrospective one-ULP boundary rule,
  15 of 21 cuts were eligible. ManyMesh lost all five image metrics in 15 of
  18 exact-face pairs, won all five in two meshoptimizer comparisons on one
  asset, and had one mixed result. No eligible QEM pair was beaten. These are
  reused development assets, not independent confirmation.
  [Report](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md) ·
  [metrics](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json)
- **Differentiable placement controls:** A local fixed-topology fit produced
  one tiny reserved-view FLIP gain across three reused assets. A separate
  projective silhouette fit worsened mean reserved-view FLIP on both tested
  assets. Neither establishes generalization or a new method.
  [Local fit](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md) ·
  [projective fit](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md)

Older results and their provenance limits remain in the
[dated history](MANYMESH_HISTORY.md). No physical-phone test, equal-frame-time
quality comparison, LPIPS evaluation, moving-camera temporal evaluation, user
study, or positive held-out optimized method is available.

## Next gate

Do not reopen the failed contour selector or build a custom DAG optimizer yet.
First run the frozen placement-only differentiable baseline on CUDA with
BarramundiFish and Corset. The inputs, matched controls, scorer, and camera
protocol are frozen in the [input report](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
and [protocol receipt](tools/mmtrain/appearance_cuda_protocol_20261124.json).
This is a baseline replication, not an operator-matched fit: training renders
at 2x supersampling with nvdiffrast edge antialiasing and its MSAA option off.
It does not optimize through the final hardware 4x MSAA or an upscaler.
This host has PyTorch 2.7.1+CPU and no CUDA runtime, so that experiment cannot
run here. The earlier CPU projective fit is a separate negative control, not a
substitute. If the CUDA baseline does not show repeatable held-out gains at
matched face count, stop this geometry-optimization direction.

## Project documents

- [SIGGRAPH 2027 direction](SIGGRAPH_2027_DIRECTION.md)
- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Filament documentation](filament/README.md)
