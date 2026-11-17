# Held-Out Target-Budget Frontier Study (2026-11-16)

## Scope

This extension adds five repository meshes to the two-asset Pirate/Monkey control: camera, cloth, material_sphere, rounded_cube and shapes. All builds use a 55% target and the same group-size grid (2, 4, 8, 16, 32); each setting is built three times in randomized per-repeat order. The three repeated graph files, cut files, triangle counts and screen-error values were checked for determinism.

Visibility quality is audited only where candidate cuts have exactly the same triangle count. The CPU diagnostic is geometry-only filtered coverage plus normalized first-hit-depth SSE, averaged over 16 evenly spaced azimuths, one elevation, 256x256, 2x supersampling, Gaussian sigma 0.9. Pirate and Monkey reuse the earlier exact-budget audits. Among the five added meshes, cloth and material_sphere match exactly across all group sizes; shapes uses groups 2, 8, 16 and 32 at 40,550 triangles, while g4 is excluded because it has 40,551. Camera (320–350 triangles) and rounded_cube (552–660) are build-only: their cuts have materially different budgets and are not ranked by image error.

## Per-asset result

| Asset | Fastest group (median DAG build) | Best exact-budget raster group | Raster SSE at fastest | Raster SSE at best | Best quality vs fastest |
|---|---|---|---:|---:|---:|
| pirate | g2 (0.49s) | g2 | 50.430478 | 50.430478 | same group |
| monkey | g2 (1.18s) | g8 | 5.765862 | 2.804802 | 51.4% lower SSE at 4.68x build cost |
| cloth | g2 (4.78s) | g2 | 0.829442 | 0.829442 | same group |
| material_sphere | g2 (1.02s) | g32 | 7.040939 | 4.274621 | 39.3% lower SSE at 2.64x build cost |
| shapes | g2 (2.39s) | g16 | 0.003067 | 0.000095 | 96.9% lower SSE at 3.28x build cost |

| Build-only asset | Triangle range across groups | Fastest group / median DAG build |
|---|---:|---|
| camera | 320-350 | g2 / 0.06s |
| rounded_cube | 552-660 | g4 / 0.17s |

## Detailed build and quality table

### pirate

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 0.49 [0.49, 0.50] | 2,756 | 19.3397 | 50.43047751 |
| 4 | 1.63 [1.61, 1.64] | 2,756 | 21.1741 | 59.01859364 |
| 8 | 2.88 [2.88, 2.89] | 2,756 | 12.4154 | 53.19256369 |
| 16 | 3.05 [3.05, 3.06] | 2,756 | 20.4373 | 52.14915555 |
| 32 | 3.15 [3.15, 3.17] | 2,756 | 12.5229 | 53.08147414 |

### monkey

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 1.18 [1.17, 1.18] | 8,660 | 7.6473 | 5.76586153 |
| 4 | 3.77 [3.77, 3.80] | 8,660 | 8.1335 | 3.43508650 |
| 8 | 5.52 [5.49, 5.53] | 8,660 | 9.3627 | 2.80480178 |
| 16 | 4.82 [4.82, 4.87] | 8,660 | 10.6435 | 2.85475910 |
| 32 | 6.92 [6.88, 6.92] | 8,660 | 13.3245 | 4.92741304 |

### cloth

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 4.78 [4.73, 4.78] | 41,236 | 2.5350 | 0.82944177 |
| 4 | 9.06 [9.03, 9.25] | 41,236 | 2.7665 | 0.86454492 |
| 8 | 17.08 [16.78, 17.56] | 41,236 | 3.0919 | 0.86044923 |
| 16 | 29.89 [29.59, 30.06] | 41,236 | 3.3224 | 0.90053127 |
| 32 | 46.29 [46.08, 46.35] | 41,236 | 3.5289 | 0.89753499 |

### material_sphere

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 1.02 [1.01, 1.03] | 5,186 | 8.8553 | 7.04093919 |
| 4 | 2.13 [2.11, 2.14] | 5,186 | 8.7586 | 6.80859394 |
| 8 | 2.37 [2.37, 2.39] | 5,186 | 9.7990 | 5.85784132 |
| 16 | 1.98 [1.97, 1.98] | 5,186 | 11.0355 | 4.90069417 |
| 32 | 2.69 [2.67, 2.70] | 5,186 | 11.4940 | 4.27462082 |

### shapes

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 2.39 [2.38, 2.39] | 40,550 | 0.4837 | 0.00306709 |
| 4 | 5.39 [5.38, 5.49] | 40,551 | 0.5180 | not audited |
| 8 | 8.08 [8.06, 8.13] | 40,550 | 0.4857 | 0.00009715 |
| 16 | 7.84 [7.83, 7.95] | 40,550 | 0.5400 | 0.00009480 |
| 32 | 5.39 [5.38, 5.45] | 40,550 | 0.6013 | 0.00498297 |

### camera

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 0.06 [0.06, 0.09] | 350 | 31.3756 | not audited |
| 4 | 0.09 [0.09, 0.09] | 324 | 24.2800 | not audited |
| 8 | 0.07 [0.06, 0.07] | 320 | 24.2800 | not audited |
| 16 | 0.06 [0.06, 0.06] | 324 | 31.3756 | not audited |
| 32 | 0.06 [0.06, 0.06] | 324 | 31.3756 | not audited |

### rounded_cube

| Group | DAG build median [min, max] s | Target-cut triangles | Sphere error px | 16-view filtered coverage/depth SSE |
|---:|---:|---:|---:|---:|
| 2 | 0.18 [0.18, 0.20] | 658 | 9.5236 | not audited |
| 4 | 0.17 [0.17, 0.18] | 656 | 15.1983 | not audited |
| 8 | 0.18 [0.17, 0.18] | 660 | 20.2336 | not audited |
| 16 | 0.26 [0.26, 0.26] | 552 | 13.7365 | not audited |
| 32 | 0.27 [0.26, 0.27] | 552 | 13.7365 | not audited |

## What the result supports

Among five exact-budget audited assets, the fastest group-2 setting also gives the lowest raster SSE for Pirate and cloth. The best group is different for the other three: Monkey g8, material_sphere g32, shapes g16. On the latter two, group 2 is fastest but has respectively 39.3% and 96.9% higher raster SSE than the best measured group, at about 2.64x and 3.28x the build time for those best settings. These are finite-grid observations, not a universal policy. The results make a single fixed `--dag-group` choice implausible as a global quality/cost optimum for this sample.

The sphere-error proxy disagrees with the image-space diagnostic on several assets: Pirate's sphere-error minimum is g8 while its raster minimum is g2; Monkey's proxy minimum is g2 while raster minimum is g8; material_sphere's proxy minimum is g2 while raster minimum is g32; shapes' proxy minimum is g2 while raster minimum is g16. This is a metric-validation result, not a new quality metric. The visibility score remains an uncalibrated geometry-only proxy.

## Research status and next gate

This is not SIGGRAPH-ready evidence. It establishes a repeatable asset-dependent sweep on five exact-budget meshes and adds two build-only assets, but uses only seven repository models, a small group grid, one fixed 55% target, one CPU raster proxy, one camera elevation and no materials/textures/normals/PBR or user study. HLOD ASAP already simplifies neighboring cluster boundaries crack-free; DAG2 already uses shared-child split-and-reinsert; scene-level adaptive simplification-rate allocation is also prior art. No novelty claim follows from per-asset tuning.

Next, compute the exact best joint schedule over the measured finite group/retry configurations at matched total wall time and peak memory, then compare a marginal full-cut quality-gain-per-build-second scheduler against that upper bound on held-out meshes not used to choose thresholds. If the finite-grid oracle shows no substantial gain over the best fixed schedule, stop this direction. If it does, the candidate method still needs a distinct cut-frontier mechanism and gate-matched HLOD ASAP/DAG2/cluster-LOD comparisons, plus appearance-aware rendering and broader evaluation.

## Reproduction and artifacts

The 75 new builds are in `out/targetbudget-heldout-20261116/builds.json`; their timing/hash aggregation is `builds_summary.json`. Re-run them with `python -I tools/mmgeo/benchmark_target_budget_heldout.py` only after changing its output root, because it refuses to overwrite captured runs. The exact-budget audit manifest (including commands and excluded groups) is `visibility_manifest.json`; the aggregate JSON is `seven_asset_summary.json`. Build inputs and all audit graphs/cuts/raster scripts are SHA-256-bound in the JSON manifests. No C++ changed and no software tests were run.
