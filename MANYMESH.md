# ManyMesh research status

Updated 2026-11-26. **No SIGGRAPH-ready contribution is established.** The 21-model matched-face screen found ManyMesh worse than QEM and meshoptimizer. No optimization has established an asset-held-out win.

## Evidence

- Matched-quality protocol and results, post-hoc LPIPS, and multiplicity audit: [screen](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) · [LPIPS](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md) · [audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).
- Tested residual decoders, budgeted refinement, and contour controls did not beat their controls: [decoder study](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md) · [contour study](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md).
- A CPU projective silhouette fit lowered training loss on two reused assets, but LDR-FLIP worsened on both reserved-view sets; PSNR changed by +0.043 dB on one asset and −0.092 dB on the other. This is not asset-generalization evidence: [report](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md).
- The corrected CPU full-RGB screen completed for both reused assets and uploaded raw result artifacts. Their metrics have not been audited into the repo, so no quality conclusion is recorded. A local D-drive WSL rerun stopped at dependency preflight: pinned Python packages are absent and network requests were reset; no fit or render ran: [protocol and run history](tools/mmtrain/PROJECTIVE_RGB_CPU_PROTOCOL_20261125.md) · [latest run](https://github.com/new-tonAA/ManyMesh/actions/runs/45640186280).
- Silhouette attribution revises the old 68.3% Monkey result, which used a DAG cut rather than the source mesh as reference: [attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md) · [reference audit](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- The 10,000-instance desktop screen found coarser meshoptimizer rasterizing faster; it did not establish a ManyMesh, full-frame, or mobile win: [report](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next gate

The distinct frozen two-asset placement fit requires CUDA and has not run. Full [DiffSimp](https://arxiv.org/abs/2611.31018) review closes differentiable optimization through QEM collapses as a standalone contribution; any remaining cluster-DAG constraint hypothesis is untested. The 30-model confirmation pool remains unscored until it passes. Its frozen camera samples are not region-held-out, so a superseding view manifest is required before Gate 2: [experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md) · [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

On this laptop, the D-drive WSL2 Clang build ran `test_manymesh` (94 passed, 1 skipped) and Vulkan `compute_test` (7/7 passed on CPU llvmpipe). Software OpenGL aborted in 3 tests; the Iris Xe D3D12 OpenGL route skipped all 7 compute tests because it exposes only Filament feature level 1. This does not qualify the hardware GPU compute path. Native Windows execution remains blocked by Smart App Control. [Local verification report](tools/mmtrain/LOCAL_WORKSTATION_VERIFICATION_20261126.md) · [hosted Windows/MSVC CI](https://github.com/new-tonAA/ManyMesh/actions/runs/45622515351).

## Claims not established

No asset-held-out optimization win, equal-frame-time quality win, on-device result, temporal-quality gain, compression result, or user study. Desktop results do not establish mobile performance.

## Research index

[SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md) · [Roadmap](MANYMESH_RESEARCH_ROADMAP.md) · [Prior art](docs/manymesh/siggraph-prior-art-screen-20261123.md) · [History](MANYMESH_HISTORY.md) · [Learned LOD](MANYMESH_LEARNED_LOD_RESEARCH.md) · [Filament docs](filament/README.md)
