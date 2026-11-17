# Multi-Asset Target-Budget LOD Control (2026-11-16)

## Question and scope

Does the same fixed `--dag-group` choice give a stable construction-cost / visible-geometry tradeoff across assets? This is a small falsification control for the proposed adaptive-construction direction; it is not an algorithm comparison or a novelty claim.

The fresh Monkey sweep and the earlier Pirate sweep both target 55% of source triangles. All candidate cuts have a fixed triangle count within each asset. Build cost is measured by the binary's reported DAG build time and repeated three times in randomized interleaved order. The quality proxy is the separate CPU raster diagnostic: mean filtered coverage plus normalized first-hit-depth SSE over 16 evenly spaced azimuths at one elevation, 256x256, 2x supersampling, Gaussian sigma 0.9.

## Results

| Asset | Group | DAG build median [min, max] s | Total wall median s | Auto-camera sphere error px | 16-view coverage/depth SSE | Graph reproducible and matches initial sweep |
|---|---:|---:|---:|---:|---:|---|
| Pirate | 2 | 0.49 [0.49, 0.50] | 0.51 | 19.3397 | 50.4305 | yes |
| Pirate | 4 | 1.63 [1.61, 1.64] | 1.65 | 21.1741 | 59.0186 | yes |
| Pirate | 8 | 2.88 [2.88, 2.89] | 2.91 | 12.4154 | 53.1926 | yes |
| Pirate | 16 | 3.05 [3.05, 3.06] | 3.08 | 20.4373 | 52.1492 | yes |
| Pirate | 32 | 3.15 [3.15, 3.17] | 3.18 | 12.5229 | 53.0815 | yes |
| Monkey | 2 | 1.18 [1.17, 1.18] | 1.22 | 7.6473 | 5.7659 | yes |
| Monkey | 4 | 3.77 [3.77, 3.80] | 3.81 | 8.1335 | 3.4351 | yes |
| Monkey | 8 | 5.52 [5.49, 5.53] | 5.56 | 9.3627 | 2.8048 | yes |
| Monkey | 16 | 4.82 [4.82, 4.87] | 4.87 | 10.6435 | 2.8548 | yes |
| Monkey | 32 | 6.92 [6.88, 6.92] | 6.96 | 13.3245 | 4.9274 | yes |

For each asset/group, all three raw graph-file SHA-256 values agree. The canonical graph object (normalizing only the absolute-versus-relative input path) also matches the earlier visibility sweep exactly. Triangle counts and the reported screen-error value remain identical across repetitions. Timing ranges are reported rather than treated as exact costs.

The same fixed parameter does not give a consistent ranking across these two meshes. Pirate group 2 has both the shortest median build (0.49s) and lowest raster SSE (50.4305). Monkey group 2 is fastest (1.18s) but has the highest SSE (5.7659); group 8 has the lowest Monkey SSE (2.8048) at a build median of 5.52s. Group 32 is dominated by group 8 for Monkey on these two measured axes. The two examples therefore show asset-dependent choices, not a universal best group size.

The auto-camera sphere-error proxy ranks the groups differently from the multi-view raster SSE on Monkey. This confirms that the current proxy is not a substitute for rendered-image validation. With only two meshes, one elevation, and one raster/filter setup, this cannot establish a general law.

## Literature boundary

A fixed group-size sweep is not a contribution. Perceptual and appearance-aware mesh simplification, view-dependent LOD selection, and construction-time/resource tuning are established themes. In particular, Ladeuil et al. (Computer Graphics Forum 2026) already construct clustered HLOD using progressive internal and boundary meshes, allowing crack-free boundary simplification across neighboring clusters. This rules out presenting adaptive boundary simplification or freeing locked boundaries as the new idea. Benthin and Peters' HPG 2023 DAG2 already use split-and-reinsert to improve cluster merging, so multi-parent alternatives alone are also insufficient.

RTX Mega Geometry is a relevant systems baseline rather than a directly equivalent simplifier: its public implementation exposes baked cluster/group sizes, LOD-node width, simplification weights, error metric and meshoptimizer settings, and records bake time, worker count and peak RAM. It targets streaming/ray-tracing cluster LOD at much larger scale; its output and gate contract must be normalized before a matched quality/cost comparison.

## Research decision

Do not claim SIGGRAPH readiness or novelty from these controls. The evidence supports only this narrower observation: the hierarchy builder's quality/cost ranking is asset-dependent under a geometry visibility proxy, and its current single-camera sphere-error score can disagree with that proxy. That is a motivation to test a stronger hypothesis, not the hypothesis itself.

A viable next gate is an offline budgeted hierarchy-construction policy that schedules additional simplification attempts only when they enlarge the complete, crack-free, attribute-valid cut frontier under a declared multi-view image-space objective. Its scope must stay distinct from per-mesh LOD-rate allocation, perceptual cut selection, progressive boundary simplification and DAG2 splitting, all established directions. It must beat (1) the best fixed group/retry schedule, (2) the exact best schedule over the tested finite configuration grid under the same wall-clock and peak-memory budget, and (3) HLOD ASAP / DAG2 / current cluster-LOD baselines when their outputs can satisfy the same strict gate. First measure whether this finite-grid oracle improves the frontier across a held-out, diverse asset set; then compare a simple marginal-gain-per-build-second scheduler against that oracle. If the oracle has no material headroom, abandon this direction. Even positive headroom would not establish novelty without a wider literature and implementation search.

## Reproduction and limitations

Build repetitions: `python -I tools/mmgeo/benchmark_target_budget_builds.py` (the run data is already captured; the driver refuses to overwrite the output folder). Aggregate and validate hashes with `python -I tools/mmgeo/summarize_targetbudget_repeats.py`. Recreate the Pirate visibility diagnostic with `python -I tools/mmgeo/audit_target_budget_visibility.py` (defaults are the frozen Pirate sweep and 16-view settings). Recreate Monkey with `python -I tools/mmgeo/audit_crossasset_visibility.py --mesh assets/models/monkey/monkey.obj --asset monkey --cut g2=out/targetbudget-crossasset-20261116/monkey-g2/selected_ratio_0.55.ply --cut g4=out/targetbudget-crossasset-20261116/monkey-g4/selected_ratio_0.55.ply --cut g8=out/targetbudget-crossasset-20261116/monkey-g8/selected_ratio_0.55.ply --cut g16=out/targetbudget-crossasset-20261116/monkey-g16/selected_ratio_0.55.ply --cut g32=out/targetbudget-crossasset-20261116/monkey-g32/selected_ratio_0.55.ply --output out/targetbudget-crossasset-20261116/monkey_visibility_audit.json`.

This is geometry-only binary coverage and normalized first-hit depth; no materials, normals, textures, PBR, animation, user study or camera distribution beyond one orbit are included. Two models are not enough for generalization. The CPU raster score is a proxy and has not been calibrated to perception. Build timing was measured on one executable/machine; three repetitions quantify local timing variation only. No C++ was changed and no software tests were run.

Machine-readable aggregate with source, executable, graph and visibility hashes: `out/targetbudget-repeat-control-20261116/summary.json`.
