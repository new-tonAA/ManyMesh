# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready contribution is established.** The 21-model matched-face screen found ManyMesh worse than QEM and meshoptimizer, and no tested optimization has a held-out win.

## Evidence

- Matched-quality protocol and results, post-hoc LPIPS, and multiplicity audit: [screen](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) · [LPIPS](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md) · [audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).
- Tested residual decoders, budgeted refinement, and contour controls did not beat their controls: [decoder study](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md) · [contour study](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md).
- Silhouette attribution revises the old 68.3% Monkey result, which used a DAG cut rather than the source mesh as reference: [attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md) · [reference audit](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- The 10,000-instance desktop screen found coarser meshoptimizer rasterizing faster; it did not establish a ManyMesh, full-frame, or mobile win: [report](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next gate

The frozen two-asset placement fit requires CUDA and has not run. The 30-model confirmation pool remains unscored until it passes: [experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md) · [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

Hosted Windows/MSVC CI ran `test_manymesh.exe` (94 passed, 1 skipped). Smart App Control still blocks the unsigned binary on this laptop; GPU `compute_test` and CUDA fitting remain unrun. [CI run](https://github.com/new-tonAA/ManyMesh/actions/runs/45622515351).

## Claims not established

No held-out optimization win, equal-frame-time quality win, on-device result, temporal-quality gain, compression result, or user study. Desktop results do not establish mobile performance.

## Research index

[SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md) · [Roadmap](MANYMESH_RESEARCH_ROADMAP.md) · [Prior art](docs/manymesh/siggraph-prior-art-screen-20261123.md) · [History](MANYMESH_HISTORY.md) · [Learned LOD](MANYMESH_LEARNED_LOD_RESEARCH.md) · [Filament docs](filament/README.md)
