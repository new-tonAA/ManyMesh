# Research decision memo (2026-11-17)

## Shared-parent alternatives: stop as a paper direction

The saved cut-substitution audit contains three native-cut substitutions: two reciprocal Shapes swaps and one Pirate swap. Only the Shapes group-2 to group-8 swap lowers local accumulated error (9.80%); its whole-cut screen-space maximum is unchanged because another selected node remains the bottleneck. The reciprocal Shapes swap raises local error, and the Pirate swap raises it by 7.8%. These are not enough independent regions to test a meaningful multi-swap policy. The candidate miner is useful as a control and regression tool, but the measured result does not support an equal-budget quality improvement or a SIGGRAPH contribution.

This conclusion also follows from prior art: Batched Multi-Triangulation already treats mesh descriptions as boundary-compatible fragments that can be selected from DAG cuts, and DAG2 already builds multiple parents for shared children. Adding more same-region alternatives, by itself, does not clear the novelty bar. Sources: [Batched Multi-Triangulation](https://vcg.isti.cnr.it/publication/2005/CGGMPS05/), [DAG2, HPG 2023](https://diglib.eg.org/bitstream/handle/10.1111/cgf14868/v42i8_04_14868.pdf).

## Narrow ReSTIR-aware collapse hypothesis

The remaining research hypothesis is narrower than “variance-aware simplification”: choose among legal edge collapses by estimating their counterfactual effect on paths that the target ReSTIR-LoD method actually reuses across topology changes. A candidate score would be trained or calibrated on frozen source paths, and would include the mapping/reconnection Jacobian and the change in the reused path's contribution after the collapse. The claim would be that this predicts and reduces the *upper tail of full-estimator error* at matched triangle count, geometric/attribute quality, and total build-plus-render cost, beyond ordinary QEM, illumination-driven reduction, and estimator-side reuse controls.

This is a hypothesis, not a novelty claim. ReSTIR-LoD already supplies UV-space surface mapping across changing topology; transport-driven reduction, variance-aware guiding/MIS, and correlated-sample handling are established. A targeted web search found no direct paper on collapse selection from ReSTIR-reuse counterfactuals, but it was not an exhaustive literature review. Relevant boundary sources: [ReSTIR-LoD (SIGGRAPH 2026)](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/), [path-transport-driven reduction (CGF 2020)](https://doi.org/10.1111/cgf.14008), [variance-aware path guiding (SIGGRAPH 2020)](https://graphics.cg.uni-saarland.de/publications/rath-2020-siggraph-guiding.html), and [correlation-aware MIS (CGF 2021)](https://doi.org/10.1111/cgf.142628).

## Falsifiable experiment and kill criteria

1. Freeze path/reservoir inputs from the ReSTIR-LoD renderer and produce paired counterfactual evaluations for legal candidate collapses. Keep the random streams, paths, camera, lighting, and source geometry fixed.
2. Measure whether the proposed local score ranks actual changes in full ReSTIR estimator error on held-out paths. Report rank correlation and top-tail calibration; do not use ESS or a one-vertex direct-light proxy as the target metric.
3. Construct LODs with the score and compare against ordinary QEM and transport-driven reduction at matched triangle budgets and matched geometry/attribute gates. Include ReSTIR-LoD's mapping and reuse controls.
4. Report full-frame error distribution (including p95/p99 and worst-tail behavior), runtime, memory, preprocessing, and quality. The mechanism only survives if held-out prediction is stable and the quality-cost Pareto frontier improves across multiple assets and views.

Kill the direction if the score does not predict held-out full-estimator error, if its gains disappear under matched geometry quality, or if the frontier gain is paid back in build, memory, or render cost. The current CPU proxy and unmatched QEM controls do not pass this gate. The local Falcor/ReSTIR-LoD renderer is still unavailable because Packman could not fetch its dependency after a network TLS EOF; a full-path experiment therefore remains unrun.

## Current decision

No candidate is currently at SIGGRAPH submission evidence level. The shared-parent alternative branch is closed as a contribution candidate. The ReSTIR-aware collapse hypothesis is the only active narrow lead, with full-path counterfactual replay as its first gate; if the renderer cannot be restored in time, the project needs a different experimentally tractable contribution rather than stronger claims from the current proxy.
