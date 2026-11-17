# Finite-Grid Target-Budget Configuration Oracle (2026-11-16)

## Definition

This is an exact enumeration of the configurations already measured for the five meshes with exactly equal candidate triangle counts across group settings: Pirate, Monkey, Cloth, Material Sphere, and Shapes. It enumerates the Cartesian product of the per-asset group-size settings (Shapes g4 is excluded because its cut has one extra triangle). No new algorithm is claimed.

Quality is the equal-weight mean across assets of (candidate 16-view filtered coverage/depth SSE / that asset's g2 SSE), so the all-g2 schedule has quality score 1. This normalization prevents the large absolute Pirate error from dominating simply because its SSE has different scale. Lower is better; it is a study objective, not perceptual calibration.

Construction budget is the sum of per-asset median whole-process wall seconds from the randomized serial builds on one executable/machine. It assumes assets are built sequentially and omits peak-memory limits, combined-scene rendering, cache effects, and scheduling overhead. Each oracle row minimizes the quality score over every enumerated schedule whose cost is at most the matched fixed-group budget.

The exact search enumerated 2,500 schedules. Its unconstrained per-asset best schedule is `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}`, cost 21.76s, normalized mean SSE 0.6249.

## Matched-budget results

| Budget cap from uniform g | Cap (sum wall s) | Best fixed group under cap / score | Finite-grid oracle schedule | Oracle cost s | Oracle score | Marginal greedy schedule | Greedy cost s | Greedy score |
|---:|---:|---|---|---:|---:|---|---:|---:|
| 2 | 10.30 | g2 / 1.0000 | `{"cloth": 2, "material_sphere": 2, "monkey": 2, "pirate": 2, "shapes": 2}` | 10.30 | 1.0000 | `{"cloth": 2, "material_sphere": 2, "monkey": 2, "pirate": 2, "shapes": 2}` | 10.30 | 1.0000 |
| 8 | 36.36 | g8 / 0.6884 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 |
| 16 | 48.01 | g16 / 0.6684 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 |
| 32 | 64.88 | g16 / 0.6684 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 | `{"cloth": 2, "material_sphere": 32, "monkey": 8, "pirate": 2, "shapes": 16}` | 21.76 | 0.6249 |

The table omits uniform g4 because Shapes lacks an exactly matched cut at that setting. The oracle is exact only over this finite, already measured parameter grid; it does not search node-local repairs, new DAG structures, or continuous settings. The greedy control repeatedly takes the currently available one-asset switch with the largest normalized SSE reduction per added wall second, skipping switches that exceed the current cap. It is a deliberately simple baseline and is not represented as state of the art.

## Interpretation and next decision

Any oracle advantage over one global group size is an asset-configuration allocation baseline, not a novel result. The useful remaining question is whether construction effort can be allocated *within* an asset so as to create additional complete, strict-gate-valid cuts, beyond choosing among prebuilt fixed group sizes. That requires a distinct candidate-generation mechanism and gate-matched HLOD ASAP/DAG2/cluster-LOD comparisons.

At the four caps tested, the one-step marginal greedy schedule matches the finite-grid oracle exactly. That weakens the case for a sophisticated *per-asset group-size scheduler*: on these data, a trivial heuristic recovers the entire measured-grid frontier. Any remaining method must add value inside an asset by constructing new valid hierarchy alternatives. This still does not prove that such a mechanism is novel.
The experiment does not meet the full planned resource match because peak memory was not recorded. Repeating all grid configurations with process peak-working-set capture is required before saying the oracle is matched in both wall time and memory. The quality objective is based on five meshes, one target ratio, one elevation, and an uncalibrated geometry-only raster proxy; no result here establishes perceptual quality, generalization, novelty, or SIGGRAPH readiness.

Machine-readable input/output hashes and all individual settings: `out/targetbudget-heldout-20261116/config_oracle.json`.
