# ManyMesh

ManyMesh is a Filament-based research prototype for mesh level of detail
(LOD). It studies how geometry choices affect rendered image quality and cost.
**No new method or mobile-performance claim is established.**

SIGGRAPH 2027 is a research target, not a submission-ready result. Current tests
have not shown that ManyMesh geometry beats strong matched controls. The
upscaler-aware cluster-DAG idea remains a hypothesis with substantial prior art.
See the [research status](MANYMESH.md), [submission plan](SIGGRAPH_2027_SUBMISSION_PLAN.md),
and [prior-art review](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md).

![Khronos Suzanne at 3,936 and 982 triangles beside a silhouette-difference map.](docs/manymesh/suzanne-lod.png)

*Suzanne comparison: flat shaded, 384 x 384 pixels per panel, CPU reference render. Center: depth-2 cut from unmodified meshoptimizer v1.2. Right: binary coverage differences. Asset: UX3D / Norbert Nopper, CC0 1.0. [Figure receipt](docs/manymesh/suzanne-lod.json).*

## Current evidence

- **No joint quality win in the 13-asset silhouette-fusion screen.** Within
  the median GPU-time budget, neither prototype beat every qualified control
  on LDR-FLIP, PSNR, and SSIM on any asset (0/13). This was a fixed-view
  Iris Xe comparison with post-hoc control selection.
  [Report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- **No broad equal-cost win in a 13-asset desktop screen.** At 720p, component-selected cuts plus 4x MSAA were faster than full-source native rendering on 4/13 assets, and faster while improving both PSNR and SSIM on 2/13. The component choices were calibrated per asset, so this is not a deployable selection method. Test hardware: Intel Iris Xe, D3D12; one fixed camera and 16 identical instances per asset. [Protocol and results](tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_13ASSET_SCREEN_20261122.md)
- **Current geometry cuts lose to matched simplification controls.** Against the original 15,744-face Monkey source over eight views, the 30%, 50%, and 70% requested cuts lost to every eligible exact-face QEM or meshoptimizer control on all reported image metrics. A one-ULP boundary tolerance was chosen retrospectively; this remains a one-asset diagnostic. [Report](tools/mmtrain/MONKEY_ORIGINAL_SOURCE_DIAGNOSTIC_20261123.md) · [raw rescore](tools/mmtrain/monkey_source_float32_boundary_diagnostic_20261123.json)
- **The frozen 21-model near-50% cohort is negative for the current cut.** At exact matching face counts, the group-mean ManyMesh result was worse than border-preserving QEM and meshoptimizer on LDR-FLIP, PSNR, SSIM, and silhouette XOR in native and 4x MSAA modes. Paired 95% group-bootstrap intervals exclude zero across 16 source-collection groups. This is fixed-view Iris Xe image-quality evidence, not an equal-time or mobile result. [Protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) · [per-view metrics](tools/mmtrain/polyhaven_quality_metrics_20261124.json)
- **A seven-asset source-reference screen found one narrow exception.** Of 18 eligible equal-face comparisons under a retrospective one-ULP boundary rule, ManyMesh lost all five image metrics in 15, won all five in two meshoptimizer comparisons on the 987-face GlassBrokenWindow, and had one mixed result. No QEM comparison was beaten. This is reused development data, not held-out or equal-frame-time evidence. [Screen and limitations](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md) · [metrics and receipts](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json)
- The GlassBrokenWindow wins do not include QEM: the border-preserving QEM control returned 859 faces for all requested cuts (381/491/569), so none met the exact-face gate. Only the 491- and 569-face meshoptimizer comparisons were eligible; the requested 30% and 70% hierarchy cuts were missed.
- Four assets have legal equal-face geometry inputs around 50% retention.
  The 30% preflights found no complete sets. BarramundiFish and Corset are
  the first CUDA pair. [Matched inputs and scoring protocol](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
  A separate 50% projective fit worsened reserved-view mean FLIP on both
  development assets. [CPU fitting report](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md)
- The desktop contour priority comparison found mixed FLIP results under
  hardware MSAA, SMAA, and bicubic upscaling on seven development assets.
  [Desktop AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md)
- The [dated history](MANYMESH_HISTORY.md) retains older CNN, AA, and draw-submission experiments with their reference and provenance limits. They are not current method evidence.

| Works in the measured scope | Does not pass | Not measured |
|---|---|---|
| Desktop draw-range merging reduced CPU submission cost in a historical Iris Xe / OpenGL test. | No current ManyMesh geometry method has beaten strong matched controls; the tested contour selector did not produce a useful equal-face alternative. | Physical-phone performance, power, thermals, equal-time quality, LPIPS, temporal stability, user preference, and confirmation of a future optimized method. |

The historical draw-range result repairs a naive per-node submission path; its capture lacks a verified generating commit and is not a mobile result. [Details](MANYMESH_HISTORY.md#771-opengl-compute-fixes-and-draw-merging) · [Claim and provenance ledger](MANYMESH_CLAIM_EVIDENCE.md)

## Project documents

- [Current research status and next gate](MANYMESH.md)
- [SIGGRAPH 2027 direction and closest prior art](SIGGRAPH_2027_DIRECTION.md)
- [Research continuation prompt and evidence protocol](MANYMESH_RESEARCH_LOOP.md)
- [SIGGRAPH 2027 plan and stop gates](SIGGRAPH_2027_SUBMISSION_PLAN.md)
- [Prior-art review](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md)
- [Dated evidence history](MANYMESH_HISTORY.md)
- [Independent confirmation-asset screen](MANYMESH_CONFIRMATION_ASSET_SCREEN.md)
- [Filament documentation](filament/README.md)
