# Finite-Grid Target-Budget Resource Oracle (2026-11-16)

## Definition and resource evidence

This exact enumeration covers 2,500 schedules over Pirate, Monkey, Cloth, Material Sphere and Shapes. Shapes g4 is excluded because it has one extra triangle. Quality is the equal-weight mean of each mesh's 16-view filtered coverage/depth SSE normalized by its own g2 SSE. The serial wall budget is the sum of per-asset median full-process wall times from three randomized builds. The peak-memory cap is the maximum single-process peak across the sequence, not a sum.

Peak working set and peak process commit were captured once per group setting through Windows `GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)`. Microsoft documents `PeakWorkingSetSize` as peak resident working set and `PeakPagefileUsage` as peak commit charge. See the [official structure documentation](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex). Each memory run's graph/source hashes were checked against the repeated build manifests. These are single memory samples per configuration; timing has three repetitions, memory does not.

## Matched time and memory results

| Cap source | Wall cap s | Peak WS cap MiB | Peak commit cap MiB | Best feasible fixed group / score | Exact oracle schedule / score | Oracle cost s | Oracle peak WS MiB | Oracle gain over fixed | Greedy score / schedule | Greedy gap to oracle |
|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|
| 2 | 10.30 | 138.1 | 163.8 | g2 / 1.0000 | `{"cloth": 2, "material_sphere": 2, "monkey": 2, "pirate": 2, "shapes": 2}` / 1.0000 | 10.30 | 138.1 | 0.0% | 1.0000 / `{"cloth": 2, "material_sphere": 2, "monkey": 2, "pirate": 2, "shapes": 2}` | 0.000% |
| 8 | 36.36 | 142.6 | 160.9 | g8 / 0.6884 | `{"cloth": 8, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` / 0.6324 | 34.05 | 142.6 | 8.1% | 0.6324 / `{"cloth": 8, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 0.000% |
| 16 | 48.01 | 136.9 | 158.4 | g16 / 0.6684 | `{"cloth": 16, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` / 0.6420 | 46.86 | 136.9 | 3.9% | 0.6420 / `{"cloth": 16, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 0.000% |
| 32 | 64.88 | 147.9 | 156.1 | g32 / 1.0442 | `{"cloth": 32, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` / 0.6413 | 63.26 | 147.9 | 38.6% | 0.6413 / `{"cloth": 32, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 0.000% |

The g4 fixed baseline is omitted: Shapes has no exact-budget g4 quality metric. The marginal greedy starts from the uniform schedule that defines the current time and peak-memory caps, then repeatedly chooses the feasible one-asset switch with the highest normalized SSE gain per added wall second while preserving both memory caps.

Unconstrained per-asset quality minima: `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}`; score 0.6249, serial wall 21.76s, peak WS 138.1 MiB, peak commit 163.8 MiB.

## Interpretation

This oracle is exact only over the measured finite group-size grid. It answers whether per-asset group selection provides headroom over a globally fixed group under measured serial wall and process-memory caps. It does not evaluate node-local candidate generation, new hierarchy structures, scene rendering, material quality, or a perceptual metric. The greedy control is not a proposed contribution.

The exact heterogeneous schedule improves over the best feasible fixed group by g2: 0.0%, g8: 8.1%, g16: 3.9%, g32: 38.6%. The marginal greedy matches the exact oracle schedule at all four caps in this measured grid. That confirms the headroom is ordinary per-asset allocation, not a new scheduling mechanism; scene-level model-specific simplification-rate allocation is already published. Memory is one sample per setting and outputs differ in `--dump-obj` mode between the core Pirate/Monkey and held-out asset sweeps, so this is a controlled within-asset comparison but not a production-wide memory claim.

Per-asset allocation is closed as a contribution candidate. The only remaining hierarchy question is whether a new within-mesh patch-generation mechanism expands the complete strict-gate-valid cut frontier beyond the measured configuration oracle. A small offline prototype would have to beat that oracle and its matching greedy at equal measured work and memory on held-out models, then beat DAG2/HLOD ASAP/current cluster LOD under one validity contract before core implementation is justified. No novelty or SIGGRAPH readiness is established.

Machine-readable records and all source/config hashes: `out/targetbudget-heldout-20261116/resource_oracle.json`.
