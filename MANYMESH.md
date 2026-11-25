# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready method is established.** The current
ManyMesh cut has not beaten matched conventional controls; no optimized
candidate has a positive held-out result.

## Evidence that changes the decision

- **Matched quality:** a frozen 21-model screen found ManyMesh worse than
  border-preserving QEM and meshoptimizer on LDR-FLIP, PSNR, SSIM, and silhouette
  XOR, both natively and with 4x MSAA. Familywise 95% intervals favor controls
  in all 16 primary comparisons. [Results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md),
  [multiplicity audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).
- **Perceptual metric:** post-hoc LPIPS on the same cohort also favors both
  controls; it is not independent confirmation. [Report](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md).
- **Learned geometry:** rank-8/16/30 residual decoders lost to matched-face QEM;
  budgeted refinement lost to same-face meshoptimizer on four assets. These
  close only the tested settings. [Rank sweep](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md),
  [baseline comparison](tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md).
- **Silhouettes:** contour-priority and contour-guided fitting showed no
  repeatable gain; half-resolution guide fusion lost to a cheaper control on
  three image metrics across 13 reused assets. [Contour](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md),
  [guide fusion](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md),
  [fitting](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md).
- The 68.3% silhouette-error figure used a DAG cut as reference. A source-mesh
  Monkey diagnostic measured 25.84%-34.75% at three budgets on one asset; neither
  supports a universal share. [Diagnostic](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- A 10,000-instance desktop screen found raster-time savings from coarser
  geometry, but no ManyMesh, complete-frame, or mobile win. [Report](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Active gate

The only active test is a frozen fixed-topology appearance-placement control on
BarramundiFish and Corset at 1,932 and 9,162 faces. CPU preparation passed;
fitting and scoring have not run because CUDA and the renderer extension are
unavailable locally. A pass opens a cluster-DAG study; it proves neither
generalization nor novelty. [Inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md),
[gate](MANYMESH_NEXT_EXPERIMENT_GATE.md), [CUDA preflight](tools/mmtrain/CUDA_ENVIRONMENT_RECHECK_20261125.md).

The fresh 30-model Poly Haven confirmation pool is frozen but unscored. It tests
per-asset fitting on unseen assets, not transfer of a learned model, and is
reserved until a method is frozen. [Pool](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md),
[protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

## Claims not established

No on-device mobile measurement, equal-complete-frame-time quality win,
positive held-out result, or user study exists. A reused-data moving-camera
screen found no supported temporal-quality gain. [Report](tools/mmmetrics/MOVING_SCENE_EDGE_QUALITY_20261124.md).

## Research index

- [SIGGRAPH direction and evidence gate](SIGGRAPH_2027_DIRECTION.md)
- [Research roadmap](MANYMESH_RESEARCH_ROADMAP.md)
- [Dated experimental history](MANYMESH_HISTORY.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Learned LOD prior art](MANYMESH_LEARNED_LOD_RESEARCH.md)
- [Filament documentation](filament/README.md)
