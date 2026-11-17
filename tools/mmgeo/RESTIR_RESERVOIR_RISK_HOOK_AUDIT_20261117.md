# ReSTIR Reservoir-Risk Hook Audit (2026-11-17)

## Scope

This is a read-only source audit of the local SIGGRAPH 2026 ReSTIR-LoD/Falcor checkout at `out/research/restir-lod`. It identifies where a possible reservoir-specific simplification objective could be measured. It is not an implementation or a novelty claim. The checkout currently has no build output or cached Falcor dependency payload, so these hooks have not been executed locally.

## Existing mapping and estimator path

1. `Source/RenderPasses/ReservoirSplatting/ShiftMapping.slang:712` implements `geometricLoDShift`. It performs UV-ray queries against current and previous LODs, matches their UV hits, then returns the ratio of target and source UV-to-world area Jacobians. The same function is used when a primary or reconnection hit crosses an LOD change (`ShiftMapping.slang:500-507`).
2. `Source/Falcor/Scene/RaytracingInline.slang:419` implements `matchUVHitInfo`. It stores at most eight UV hits, greedily matches old/current hit triangles by closest world-space hit position, then accepts the pair whose source primitive matches the original hit. This is existing correspondence machinery. It does not provide a simplification objective.
3. `Source/RenderPasses/ReservoirSplatting/ScatterTemporalResampling.cs.slang:84-107,150-182` evaluates the shifted path and forms full path shift Jacobians from the geometric LOD Jacobian, second-hit geometric Jacobian, subpixel Jacobian, and secondary-path Jacobian. It uses old and shifted luminance/confidence in a generalized MIS weight before adding the sample to the destination reservoir.
4. `Source/RenderPasses/ReservoirSplatting/Reservoir.slang:75-90` defines the destination selection weight as `mis * pHat * other.computeUCW() * jacobian`; reservoir confidence is capped at 20. Thus the LOD-induced failure signal is not just UV coverage or geometric displacement: it can appear as invalid mapping, changed visibility/path radiance, a large path Jacobian, a changed MIS weight, and ultimately a different reservoir selection or estimator contribution.

The eight-hit storage cap was checked on Cloth LOD0->LOD1, the local transition with substantial sampled UV overlap. Of 20,000 source-UV-area samples, 62.6% had multiple target hits, but the observed multiplicity maximum was 4 and no sample exceeded 8. This finite diagnostic provides no evidence that the cap causes overflow on this transition; it is not a global-domain bound and does not emulate material alpha testing or the renderer ray query. Reproduction: `tools/mmgeo/audit_restir_uv_overlap_capacity.py`; manifest: `out/restir-alt-lod-screen-20261117/cloth-lod0-to-lod1-overlap-capacity.json`.

The source computes an explicit temporal MIS share. For the current-frame sample, `m_current = luminance(current.integrand) * current.confidence` and `m_shifted = luminance(shifted.radiance) * fullShiftJacobian * previous.confidence`, then `currentMIS = m_current / (m_current + m_shifted)`. The previous-frame sample uses the complementary share. A geometry candidate can change the shifted radiance, mapping validity, and Jacobian, thereby changing this share before the reservoir update. The candidate quantity worth testing is the change in this per-path MIS share, recorded alongside the actual destination estimator error; the share alone is not a quality metric and must predict held-out reuse outcomes to be useful.

## Candidate quantity to test

For each captured source reservoir/path `i` and a candidate target mesh `M`, replay the same source path through the existing shift/reconnection code and record a vector of outcomes:

```text
v_i(M) = [mapping-valid, shifted-radiance, full-shift-Jacobian,
          temporal-MIS-share, reservoir-selection-weight, final estimator contribution]
```

The first experiment should test whether temporal-MIS-share drift predicts held-out full-ReSTIR outcomes and whether a collapse score based on it beats geometry and illumination baselines. This share is not a novel estimator quantity: resampling-aware BPT weighting already handles proposal-probability changes caused by resampling, and variance/correlation-aware MIS already studies estimator weights. Also, HPG 2026 Compatibility-Guided Neighbor Selection (CGNS) uses geometric compatibility for spatial reuse, SIGGRAPH 2026 Multi-Layer Reservoir Splatting handles disocclusion histories, and SIGGRAPH Asia 2025 ReSTIR PG learns path guides from resampled samples. Treat these as required estimator-side controls where compatible with the renderer. The EGSR 2025 footprint-driven VCM paper is adjacent cost-allocation work: it disables low-value connections/merges based on path footprints, but does not change mesh geometry or ReSTIR LOD transport.

Report mean squared estimator change and upper-tail conditional value at risk of per-pixel/frame estimator error separately; also report temporal covariance and spatial covariance using metrics comparable to CGNS (including lagged temporal covariance and a local spatial neighborhood), mapping failure rate, visibility/reconnection changes, Jacobian tails, MIS-share drift, ESS, runtime, and memory. Compare the full error-correlation-cost Pareto frontier. Avoid collapsing these observables into a hand-tuned scalar until their predictive value has been measured.

A plausible offline method is to replay a fixed, representative reservoir-path corpus for each candidate collapse, estimate its incremental change to those outcomes, and rank collapses under a triangle budget with topology, UV, appearance, and geometric constraints. Recompute or refresh affected paths after accepted collapses. A fixed local additive score is only a hypothesis: path reconnection and reservoir selection make collapse effects interactive, so sequence-level replay must verify its ranking.

## Required comparison and kill gate

At matched face count and geometry/appearance quality, compare:

- ordinary position/attribute QEM and nested QEM;
- illumination/path-tracing-driven reduction, including Reich et al. 2015 and Bethe et al. 2020;
- variance-aware path guiding and variance/correlation-aware MIS controls, to distinguish a mesh-collapse effect from estimator-side variance improvements;
- the same ReSTIR-LoD renderer with its published mapping and reuse controls;
- current ReSTIR reuse improvements, especially CGNS for spatial reuse and Multi-Layer Reservoir Splatting for disocclusion, plus ReSTIR PG where its guiding changes initial path proposals;
- the proposed reservoir-risk ranking, with equal replay/build/render budgets.

Use held-out assets, views, materials, and path streams. The candidate fails if the risk score does not improve the full estimator/error/cost frontier, if its edge ranking does not predict held-out outcomes, or if the gain vanishes against illumination-driven simplification and modern reuse controls. This audit narrows an integration plan; it does not establish that the objective is novel. Primary references: [resampling-aware BPT weighting](https://doi.org/10.1145/3338994), [footprint-driven VCM](https://graphics.cg.uni-saarland.de/papers/yazici-2025-egsr-footprint.pdf), [CGNS](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/), [Multi-Layer Reservoir Splatting](https://research.nvidia.com/labs/rtr/publication/hong2026multilayer/), [ReSTIR PG](https://research.nvidia.com/labs/rtr/publication/zeng2025restirpg/).

## Current execution constraint

`out/research/restir-lod` contains the source and Git checkout, but no renderer executable, CMake cache/build tree, or `external/packman` dependency payload. The default Packman cache `E:\packman-repo` contains `packman-common` and Python only; the Falcor packages listed in `dependencies.xml` are absent. On 2026-11-17, the correctly targeted pull was retried after approval, including an escalated network attempt, but CloudFront again returned TLS EOF while retrieving the missing Python package. No Falcor payload was acquired and no renderer was built.
