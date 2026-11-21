# SIGGRAPH 2027 research gate (2026-11-21)

## Status

The SIGGRAPH-level algorithm goal is **not achieved**. No candidate has both a defensible novelty boundary and repeatable quality/performance gains over strong baselines. Keep this as an active research goal; do not present the work as submission-ready.

## Evidence reviewed

- The bounded Thingi10K pilot contains 32 licensed meshes with an asset-level 16/8/8 split. The learned tile ranker lost to image contrast on the held-out set. A 22,860-parameter image upsampler also lost to bicubic on validation and test PSNR/SSIM, and was about 4.1x slower on CPU at 640x360. See [pilot data](tools/mmtrain/THINGI10K_PILOT_DATA_20261120.md), [tile ranking](tools/mmtrain/THINGI10K_TILE_RANKING_SCREEN_20261121.md), and [super-resolution screen](tools/mmtrain/THINGI10K_SUPERRES_SCREEN_20261121.md). This closes these small model configurations, not learned mesh refinement in general.
- Fixed-budget repair, mixed group-size cuts, per-asset configuration, and scalar rejection-mask scheduling have been tested against finite oracles and controls. Current reports close those formulations as contribution candidates: [target-budget resource oracle](tools/mmgeo/TARGET_BUDGET_RESOURCE_ORACLE_20261116.md), [mixed cut frontier](tools/mmgeo/MIXED_GROUP_CUT_FRONTIER_20261117.md), and [spatial retry frontier](tools/mmgeo/SPATIAL_RETRY_LOCAL_FRONTIER_AUDIT_20261118.md).
- Exact filtered loss over an orthographic camera pan can evaluate visibility events and share local depth envelopes. It is faster than dense raster sampling on some candidate pools, but not others; in several cases the cheaper raster already chooses an effectively tied candidate. The higher-resolution Pirate sequence tied QEM on coverage, was 1.57% worse on flat-normal loss, and cost 16.2x as much CPU time. See [event expansion](tools/mmgeo/MATERIAL_SPHERE_EVENT_RASTER_EXPANSION_20261120.md) and [high-resolution Pirate audit](tools/mmgeo/PIRATE_HIRES_PATH_LOSS_AUDIT_20261120.md).
- The on-demand DAG reader bounds cache residency but does not incrementally build the hierarchy. An incremental, strict-gate builder under a hard memory cap remains an engineering/research question, but generic out-of-core simplification and streamed LOD are established prior art. See [memory screen](tools/mmgeo/ON_DEMAND_DAG_BUILD_MEMORY_SCREEN_20261118.md).

## Novelty boundary

Generic view-dependent simplification, continuous viewcell error bounds, and image-driven mesh simplification are established. For example, [Eisemann and Décoret (2007)](https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2007.01013.x) give exact error bounds over polygonal viewcells, while image-driven simplification predates this project. Therefore neither “continuous camera path,” “exact visibility,” nor “image-space mesh simplification” is a sufficient novelty claim.

The only currently defensible *hypothesis* in this line is a practical algorithm for ranking legal mesh edits by **antialiased source-versus-candidate image loss integrated over a continuous camera path**, using shared visibility-event structures and certified lower bounds to prune edits. Existing evidence establishes a kernel and local exactness checks, not a quality gain or a competitive end-to-end algorithm. The novelty search must compare this precise combination and objective against path/viewcell simplification, analytic rasterization, and kinetic visibility work before any claim is made.

## Next gate

Do not widen the learned branch or run another expensive mesh build until there is a frozen, reproducible comparison that can falsify this path-loss hypothesis. Use existing captures first. The gate is:

1. Fix candidate generation, camera trajectories, filter, raster resolution, and quality metric before scoring.
2. Compare QEM, dense path sampling, and the exact event scorer at identical final face counts on independent assets and held-out paths.
3. Report full pipeline wall time and peak process working set, not scorer-only time; cap RAM use and run assets serially.
4. Require a repeatable image-quality gain at matched build/scoring cost, or equal quality with a clear end-to-end speedup. If the result depends on a low-resolution proxy or one asset, close the branch.
5. Only after passing this gate, port the winning mechanism into the ManyMesh pipeline and compare against current strict-gate DAG construction and relevant published systems.

No production algorithm change or software tests were made for this research-status note. The next action is evidence-led algorithm work, not a claim that the SIGGRAPH goal is complete.
