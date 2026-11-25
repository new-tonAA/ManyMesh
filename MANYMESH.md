# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready method is established.** The current
ManyMesh geometry has not beaten matched conventional controls, and no tested
optimization has produced a positive held-out result.

## Decision-relevant evidence

- A frozen 21-model, six-metric screen found ManyMesh worse than matched-face,
  border-preserving QEM and meshoptimizer, both natively and with 4x MSAA.
  Post-hoc LPIPS on the same cohort agrees; it is not independent confirmation.
  [Quality results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md),
  [multiplicity audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md),
  [LPIPS supplement](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md).
- Tested rank-8/16/30 residual decoders, budgeted refinement, and contour-aware
  variants failed against their matched controls. These results close only the
  tested configurations. [Decoder studies](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md),
  [contour study](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md).
- On that same 21-model cohort, silhouette-XOR regions account for 31.0% of
  ManyMesh squared grayscale error without AA and 16.3% with 4x MSAA. Silhouette
  error is overrepresented, but is not the majority. The old 68.3% Monkey result
  used a DAG cut rather than the source mesh as reference. These post-hoc
  measurements are protocol-specific, not independent confirmation.
  [Attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md),
  [source-reference audit](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- A 10,000-instance desktop screen found faster rasterization with coarser
  meshoptimizer geometry, but no ManyMesh, complete-frame, or mobile win.
  [Instance screen](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next experiment and local gate

The frozen fixed-topology placement control covers BarramundiFish and Corset.
Its current adapter uses CUDA-only nvdiffrast; fitting and quality scoring have
not run. A CPU renderer would be a separate, unimplemented protocol, not an
equivalent rerun. The local Python research suite passes 4/4 tests; Windows
Smart App Control blocks the unsigned native test binaries, so native test
status remains unverified. [Matched inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md),
[experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md),
[environment record](tools/mmtrain/CUDA_ENVIRONMENT_RECHECK_20261125.md).

The 30-model Poly Haven confirmation pool is frozen and unscored. It remains
reserved until a method passes the development gate.
[Pool](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md),
[protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

## Claims not established

No held-out optimized-method win, equal-complete-frame-time quality win,
on-device mobile result, supported temporal-quality gain, or user study exists.
Desktop measurements do not establish mobile performance.

## Research index

- [SIGGRAPH 2027 direction and evidence gate](SIGGRAPH_2027_DIRECTION.md)
- [Research roadmap](MANYMESH_RESEARCH_ROADMAP.md)
- [Dated experimental history](MANYMESH_HISTORY.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Learned LOD research](MANYMESH_LEARNED_LOD_RESEARCH.md)
- [Filament documentation](filament/README.md)
