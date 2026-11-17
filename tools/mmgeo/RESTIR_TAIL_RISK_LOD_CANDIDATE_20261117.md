# Candidate: Tail-Risk-Aware LOD Construction for ReSTIR

**Status:** research hypothesis only. No novelty or SIGGRAPH-readiness claim.

## Candidate claim if future gates pass

Construct a nested mesh hierarchy that reduces the upper-tail risk of ReSTIR path-resampling error across LOD transitions, subject to matched triangle budgets, geometry/appearance quality, runtime, and memory. The specific target is rare catastrophic changes in path contributions after mapping a reservoir sample from one LOD to another. The contribution would be the collapse objective and its measurable quality-cost frontier, not UV mapping, per-ray LOD, or progressive nesting alone.

## Why this candidate emerged

The direct-light proxy currently shows:

- Glossy Torus L1->L2: the existing 486-triangle target has cross/same relative MSE ratios of 1.397 and 1.139 in two M=128 seeds. A 486-triangle position-QEM target simplified from L1 has ratios 0.997 and 0.993. Common-random paired changes in cross-minus-same delta are -0.558 (bootstrap 95% [-0.908, -0.273]) and -0.205 ([-0.312, -0.107]).
- Glossy Sphere L2->L3: the existing 2,214-triangle target has ratios 1.056 and 1.076. A nested 2,212-triangle target has ratios 1.023 and 1.027. Paired changes are -0.0457 ([-0.0887, -0.0043]) and -0.0659 ([-0.1231, -0.0178]).
- Glossy Monkey LOD0->LOD1 has no resolved cross-LOD penalty (1,024-batch ratio 0.998; family-wise paired interval [-0.0395, +0.0344]). The stronger LOD0->LOD2 transition has ratios 1.087 and 1.104 in two independent 4,096-batch seeds, with paired family-wise 95% intervals [+0.0184, +0.2085] and [+0.0547, +0.2148]. Both medians are slightly negative and the maxima are +139 and +107, so this small added mean error is also tail-driven. These remain existing ordinary LODs in a one-vertex direct-light proxy; no alternative collapse order was tested.
- On Monkey LOD0->LOD2, an ordinary direct-from-LOD0 position-QEM target at a matched 11,700-face budget produced paired changes in cross-minus-same penalty of -0.1335 and -0.0171 in two common-random seeds; both bootstrap intervals cross zero. The QEM target has better p95 displacement/normal error, worse maximum area Jacobian, and 14-16 sampled UV misses per 65,536 candidates. This does not show a robust ordinary-QEM advantage, much less a ReSTIR-aware gain; geometry-matched comparisons remain necessary.
- Across these screens, median paired changes are near or slightly above zero, while rare outliers dominate the mean. The Torus target's p95 displacement and normal-map metrics also improve, so geometry quality and nesting are confounded. Both alternative meshes were generated with the quality gate disabled.

These results only show that target geometry can affect a one-vertex direct-light estimator's tail. They do not show a full-path or image-quality gain, or that an estimator-aware collapse objective beats ordinary simplification.

### Construction-path control update (2026-11-17)

At 314 Torus faces, a direct-from-LOD0 position-QEM target and a sequentially nested target have indistinguishable paired direct-light penalties in two M=128 seeds: direct-minus-nested changes are -0.0827 (bootstrap 95% [-0.1790, +0.0118]) and -0.0053 ([-0.1082, +0.1018]). The direct target has lower p95 displacement and normal error, so this is not geometry matched; nevertheless, the data give no unique benefit to nesting. A 204-face nested target also has inconclusive paired intervals against the 486-face baseline. The candidate should remain a falsifiable research question, not be described as an observed nested-LOD gain. See [the construction-path control](RESTIR_NESTED_LOD_GEOMETRY_SCREEN_20261117.md).

## Technical direction to test

For each candidate collapse in a nested sequence, estimate the change in mapped ReSTIR path outcomes over representative cameras, materials, light configurations, and reservoir streams. Include the actual cross-LOD surface map and area Jacobian, visibility, BRDF contribution, and spatial/temporal reuse weights. Optimize a risk-sensitive objective such as

```text
J = mean full-image error
  + lambda * CVaR_alpha(positive cross-LOD estimator error)
  + mu * runtime
  + nu * memory
```

subject to fixed triangle/streaming budgets and explicit topology, UV-support, and geometric-quality constraints. Compare this against mean-error-only QEM, nested QEM, appearance/illumination-aware simplification, and the published ReSTIR-LoD mapping with modern reuse controls. Use common random numbers for paired comparisons and report bootstrap intervals for both mean error and tail risk.

The equation is only a proposal. Initially report image error, CVaR, mapping/path failures, reservoir statistics, temporal covariance, spatial covariance, runtime, and memory separately; align covariance definitions with the modern ReSTIR comparison (including lagged temporal and local spatial covariance) and plot the full error-correlation-cost Pareto frontier. Choose weights only after showing that the resulting collapse ranking predicts held-out outcomes. Full ReSTIR reuse introduces correlations across pixels and frames, so a local additive collapse score may fail. A practical method needs either a validated proxy or an efficient way to evaluate path-reservoir effects for candidate collapses.

## Prior-art boundary

- SIGGRAPH 2026 ReSTIR-LoD provides cross-topology UV surface mapping and area Jacobians. Its paper says ray-footprint/depth selection is possible but uses one LOD for all rays in each frame.
- Per-ray adaptive geometry LOD predates this work. It cannot be claimed as the innovation.
- Progressive/nested meshes, appearance-driven simplification, and illumination-aware mesh reduction are established. Nesting itself is not the novelty.
- Illumination-driven mesh reduction already uses light-transport paths to preserve radiometrically important geometry, and later work formulates path-tracing-based reduction with shadow-silhouette preservation plus error quadrics. Generic path- or radiance-driven simplification is also prior art; a ReSTIR-specific claim must measure a reservoir-specific quantity and beat those objectives at equal geometry and total cost.
- Variance-aware path guiding already derives target densities that account for nested-estimator variance; variance-aware MIS and correlation-aware MIS already address estimator variance and correlated path reuse. Neither CVaR, variance weighting, nor correlation awareness is novel by itself. The distinguishing question has to be whether a geometry-collapse objective predicts and improves the *ReSTIR reservoir update* under LOD mapping, beyond those estimator-side methods.
- Resampling-aware MIS for BPT with multiple light sub-paths already derives weights that account for probability changes caused by resampling. Measuring a temporal MIS-share change is therefore only a diagnostic, not a contribution. The EGSR 2025 footprint-driven VCM heuristic also skips low-value connections and merges from path-footprint signals; it is adjacent cost-allocation prior art, although it does not simplify geometry or transport ReSTIR reservoirs across LODs.
- Recent ReSTIR controls make a geometry-only reuse claim especially weak: Compatibility-Guided Neighbor Selection (HPG 2026) selects spatial neighbors using geometric compatibility; Multi-Layer Reservoir Splatting (SIGGRAPH 2026) recovers histories across disocclusion; and ReSTIR PG (SIGGRAPH Asia 2025) learns guiding distributions from resampled paths. Any surviving claim must show a mesh-construction gain with these reuse controls enabled, not merely improve a weaker baseline.
- ReSTIR PT Enhanced and related work already improve runtime correlation, robustness, and reuse. A new method must beat these controls.
- A bounded search has not established that estimator-tail-aware collapse optimization is absent from all prior work. Search this exact coupling more broadly before any novelty claim.

Primary references: [ReSTIR-LoD, SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/); [Compatibility-Guided Neighbor Selection for ReSTIR, HPG 2026](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/); [Multi-Layer Reservoir Splatting, SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/hong2026multilayer/); [ReSTIR PG, SIGGRAPH Asia 2025](https://research.nvidia.com/labs/rtr/publication/zeng2025restirpg/); [ReSTIR PT Enhanced, I3D 2026](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/); [Resampling-aware Weighting Functions for BPT, SIGGRAPH 2020](https://doi.org/10.1145/3338994); [Footprint-driven cost reduction for bidirectional rendering, EGSR 2025](https://graphics.cg.uni-saarland.de/papers/yazici-2025-egsr-footprint.pdf); [Locally-Adaptive LOD for Hardware-Accelerated Ray Tracing, SIGGRAPH Asia 2023](https://graphics.cs.utah.edu/research/projects/ray-tracing-hw-adaptive-lod/); [Illumination-driven Mesh Reduction for Accelerating Light Transport Simulations, EGSR 2015](https://doi.org/10.1111/cgf.12688); [Preserving Shadow Silhouettes in Illumination-Driven Mesh Reduction, CGF 2020](https://doi.org/10.1111/cgf.14008); [Variance-Aware Path Guiding, SIGGRAPH 2020](https://graphics.cg.uni-saarland.de/publications/rath-2020-siggraph-guiding.html); [Variance-Aware MIS, SIGGRAPH Asia 2019](https://iliyan.com/publications/VarianceAwareMIS/); [Correlation-Aware MIS for Bidirectional Rendering, CGF 2021](https://doi.org/10.1111/cgf.142628); [Appearance-Driven Automatic 3D Model Simplification](https://arxiv.org/abs/2104.03989); [Progressive Meshes, SIGGRAPH 1996](https://doi.org/10.1145/237170.237216).

## Kill gates

1. Reproduce the nested-target effect on more held-out assets and materially distinct path domains; include independent references and validate the heavy-tail convergence.
2. Match geometry/appearance quality and exact triangle count closely enough that gains cannot be explained by a simply better mesh.
3. Implement the candidate objective and show a full ReSTIR path-tracing error/correlation/cost frontier improvement over QEM, nested QEM, illumination/path-tracing-driven reduction, appearance-aware reduction, variance/correlation-aware estimator controls, and current ReSTIR controls.
4. Verify the gain on held-out assets, cameras, materials, and LOD transitions. Stop if it depends on the Torus proxy, disappears under full-path controls, or costs more than it saves.

The local Falcor/ReSTIR-LoD source checkout exists at `out/research/restir-lod`, but it has no build directory or renderer executable, and its `external/packman` dependency payload is absent. On 2026-11-17, the correctly targeted Packman pull was retried after approval, including an escalated network attempt; both failed with CloudFront TLS EOF while retrieving the missing Python package. No Falcor dependencies were installed and no renderer was built. Until the full-render gate is open and passed, this remains a low-confidence candidate, not a submission-ready contribution.

The source-level insertion points and proposed observables are documented in [the reservoir-risk hook audit](RESTIR_RESERVOIR_RISK_HOOK_AUDIT_20261117.md). Drift in the temporal MIS share of a mapped path is only an early diagnostic: resampling-aware MIS already studies probability changes after resampling, and CGNS already uses geometry compatibility for spatial reuse. Test whether a collapse ranking predicts held-out estimator outcomes and improves the quality-cost frontier with current reuse controls enabled, or stop the candidate. This is a testable hypothesis, not a novelty claim. No shader or renderer code has been changed.
