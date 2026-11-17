# ReSTIR-Reuse-Aware LOD Construction: Research Hypothesis

Date: 2026-11-16. This is a candidate for a decisive prior-art and feasibility screen, not a
novelty claim or a SIGGRAPH-ready result.

The official [SIGGRAPH 2027 Technical Papers page](https://s2027.siggraph.org/program/technical-papers/)
currently lists **2027-01-28 22:00 GMT** as the paper deadline, **2027-01-21 22:00 GMT** for
the submission form/conflicts, and **2027-01-29 22:00 GMT** for upload. Submission details are
still forthcoming. As of 2026-11-17, 72 days remain to the paper deadline; this is a hard feasibility
constraint, not an assumed future runway.

## Candidate question

Can a progressive mesh simplifier choose collapses that preserve the *statistical usefulness* of
cross-LOD path reuse, rather than only surface shape, texture mapping, or rendered appearance?

For held-out paths transported between adjacent LODs, record these diagnostics for each candidate
collapse and LOD pair:

- mapped-path support / shift-validity rate;
- effective sample size of the exact reuse weights, `(sum w)^2 / sum(w^2)`, before reservoir caps;
- path-contribution agreement after the shift;
- independent-run image error/variance and relative frame autocovariance at a declared lag after
  the actual reservoir pipeline; report spatial covariance separately.

These are diagnostics, not the optimization target. The exact finite single-merge RIS variance
depends on both shift weights and shifted contributions (derived below); even that conditional
variance does not include correlation from multiple reuse passes. A candidate objective must
therefore be checked against independent-run image variance and relative frame autocovariance from
the full renderer. A held-out path stream is required to detect probe overfitting. Because path
visibility and downstream intersections can change nonlocally after a collapse, local patch-only
updates are an unproven speed assumption and must be measured against full or correctly bounded
re-evaluation.

## Prior art boundary found so far

The SIGGRAPH 2026 ReSTIR-LoD paper already supplies the cross-topology surface map through
consistent UVs, requires partial bijectivity, derives the area Jacobian, and reports that distorted
or degenerate UV maps can reduce reuse effectiveness. Its formulation does not require one LOD per
frame, although its implementation uses one; per-ray LOD is explicitly future work. Therefore
cross-LOD mapping, Jacobian weighting, UV preservation, or implementing per-ray selection are not
the candidate contribution.

Progressive Meshes already preserve mappings through edge-collapse sequences. Appearance-preserving
and later texture-aware simplification methods preserve attributes or surface correspondence.
Appearance-Driven Automatic 3D Model Simplification directly optimizes image-space rendering error.
Illumination-driven mesh reduction already accumulates per-triangle importance from camera/light
paths and steers edge-collapse reduction; its path-tracing extension adds shadow-silhouette
importance and combines path importance with QEM. This establishes path-aware simplification as
prior art. The paper also says a closed-form global-illumination mesh-reduction error is unavailable
and uses local path metrics because full-render RMSE is expensive and noisy. ReSTIR work separately
optimizes path compatibility, candidate generation, sample mutation, and reuse correlation at
runtime. Thus a UV penalty, normal penalty, rendered-error term, illumination weight, or generic
reuse-compatibility score alone is not enough.

The SIGGRAPH 2026 ReSTIR-LoD paper reports that the remaining quality loss after its cross-LOD reuse
is partly due to UV-map imprecision and normal differences. That motivates measuring whether LOD
construction can reduce transport mismatch, but UV/normal-aware collapse alone is already crowded
prior art. The paper's formulation supplies the mapping and Jacobian; its experiments treat LoDs as
available representations and the paper does not introduce a collapse-order objective. The public
repository README documents temporal mapping, LOD selection, and render drivers, and says the
Chessboard scene must be downloaded separately; it does not document an LOD-generation pipeline.
These checked materials do not prove that no supplementary or external tool generates their assets.

The narrow hypothesis is the *coupling*: an offline collapse sequence that improves the full
ReSTIR error-correlation-cost Pareto frontier at a fixed geometry/triangle budget, with the exact
ReSTIR-LoD transport and modern runtime reuse controls in the comparison. The target is not to
minimize covariance monotonically: effective reuse can lower image error while increasing some
correlations, and the useful operating point depends on temporal stability and denoising. Directly
maximizing ESS is rejected as an objective. A targeted search did not find a paper directly
optimizing mesh collapse order for this full estimator objective, but that is not evidence of
absence. A wider search over rendering-aware simplification, path-space metrics, and ReSTIR asset
construction is still required before claiming novelty.

The HPG 2026 Compatibility-Guided Neighbor Selection implementation is a particularly close
runtime baseline: it draws candidate pixels from a disk, scores primary-hit position and normal
compatibility, then uses weighted reservoir sampling to select spatial neighbors. The published
work optimizes runtime spatial reuse, not the offline geometry-collapse sequence or temporal
cross-LOD mapping. This distinction narrows the candidate but does not itself establish novelty.
See the [paper](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/) and
[reference implementation](https://github.com/orion-junkins/ReSTIR-CGNS).

Primary sources:

- Wang et al., [Real-Time Level-of-Detail Rendering with ReSTIR, SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/).
- Hoppe, [Progressive Meshes, SIGGRAPH 1996](https://doi.org/10.1145/237170.237216).
- Zhang et al., [Seamless simplification of multi-chart textured meshes with adaptively updated correspondence, 2022](https://www.sciencedirect.com/science/article/pii/S0097849322000930).
- Hasselgren et al., [Appearance-Driven Automatic 3D Model Simplification, TOG 2021](https://arxiv.org/abs/2104.03989).
- [Preserving Shadow Silhouettes in Illumination-Driven Mesh Reduction, 2020](https://doi.org/10.1111/cgf.14008).
- Sawhney et al., [Decorrelating ReSTIR Samplers via MCMC Mutations, TOG 2024](https://doi.org/10.1145/3629166).
- Junkins et al., [Compatibility-Guided Neighbor Selection for ReSTIR, HPG 2026](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/).
- Lin et al., [ReSTIR PT Enhanced: Algorithmic Advances for Faster and More Robust ReSTIR Path Tracing, I3D 2026](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/).
- [ReSTIR PG: Path Guiding with Spatiotemporally Resampled Paths, SIGGRAPH Asia 2025](https://doi.org/10.1145/3757377.3763813).
- [Public ReSTIR-LoD implementation](https://github.com/elite-sheep/ReSTIR-LoD), built on Falcor 8.0; benchmark scenes are not bundled.

## Decisive experiment

Use a ReSTIR path-tracing implementation with the published LoD mapping and Jacobian. Generate LOD
sequences at matched face budgets and geometric error using:

1. geometry-only QEM;
2. the current ManyMesh Corner simplifier with its existing UV/normal gates;
3. an appearance-driven simplification baseline;
4. the proposed reuse-weight objective.

Then compare baseline ReSTIR-LoD and the strongest compatible modern runtime controls: at minimum
Compatibility-Guided Neighbor Selection and MCMC mutation, plus ReSTIR PT Enhanced's reciprocal
neighbor selection, footprint-based shift criteria, and duplication maps where the ReSTIR-LoD
renderer can support them. ReSTIR Path Guiding is another relevant candidate-generation control.
These controls come from separate systems and cannot simply be assumed to compose; document which
are integrated and compare each at equal total cost. Use the same scenes, camera/light/animation sequences,
ray budget, reservoir parameters, and independent random seeds. Report actual estimator variance,
SMAPE/RelMSE to a declared reference, relative temporal autocovariance at a stated frame lag,
spatial covariance at a stated radius, valid reuse fraction, reuse-weight ESS, GPU time, LOD build
time, peak memory, and total cost. Report the error-correlation-cost Pareto curve rather than a
single covariance optimum. Separate objective-tuning paths from held-out evaluation paths and assets.

The experiment only supports a paper direction if the method expands the quality-versus-total-cost
Pareto frontier across a diverse held-out set, while satisfying the same geometric and triangle
budgets. If its benefit disappears under the runtime reuse controls, only appears in the proxy ESS,
or costs more in path tracing/build work than it saves, stop the branch. Any estimator change would
need its own support/Jacobian proof; this candidate does not propose one.

For reproducibility, report the HPG 2026 CGNS correlation definitions alongside image error: over
`N` independent video sequences, relative frame autocovariance uses normalized luminance residuals
at a declared lag (their default is `T=3` frames), while spatial covariance averages relative
covariance inside an 8-pixel-radius disk. These are diagnostics to place each method on a frontier;
neither scalar is a universal monotonic objective. Also report dynamic LOD-transition frames
separately from steady-state frames, because the SIGGRAPH 2026 ReSTIR-LoD result focuses its
evaluation on just before/after LOD changes.

## Objective correction: ESS is a diagnostic, not the optimization target

The actual single-merge RIS output already shows why maximizing weight ESS is not sufficient.
For a fixed set of shifted candidates, let `w_i` be the exact GRIS resampling weight,
`W = sum_i w_i`, and `g_i = f(T_i(X_i)) / p_hat(T_i(X_i))`. Candidate `i` is selected with
probability `w_i / W`; the estimator output is `W * g_i`. Its conditional variance is

```text
V_cond = W * sum_i(w_i * g_i^2) - (sum_i(w_i * g_i))^2.
```

By contrast, weight ESS is `W^2 / sum_i(w_i^2)` and does not use `g_i`. The ranking can therefore
reverse even for two positive-weight candidates and the same expected integral:

| Candidate set | weights `w` | values `g` | ESS | possible estimator outputs | mean | variance |
|---|---|---|---:|---|---:|---:|
| A | `(1, 1)` | `(0, 2)` | 2.0 | `(0, 4)` with equal probability | 2 | 4 |
| B | `(1, 3)` | `(0.5, 0.5)` | 1.6 | `(2, 2)` | 2 | 0 |

This is an exact finite RIS calculation, not a rendering result. It falsifies `maximize ESS` as a
standalone simplification objective. ESS, support, and weight tails can remain diagnostics, but a
candidate collapse objective must include shifted path contributions and be checked against the
actual multi-pass renderer. Even `V_cond` is insufficient for iterative ReSTIR: GRIS identifies
correlation from repeated reuse, while Compatibility-Guided Neighbor Selection directly studies the
error-correlation tradeoff and reports a stronger runtime control. These are hard
baselines, not just related work ([GRIS foundations](https://research.nvidia.com/publication/2022-07_generalized-resampled-importance-sampling-foundations-restir),
[Compatibility-Guided Neighbor Selection](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/),
[MCMC mutation](https://doi.org/10.1145/3629166)).

The surviving research question was whether an *offline collapse order* could improve the full
quality/cost/covariance Pareto frontier after the same LoD-aware GRIS reuse and runtime controls.
The direct search did not find this exact mesh-construction objective, but search incompleteness
prevents a novelty claim. Per the user's instruction on 2026-11-17, this ray-tracing line is no
longer active. Its CPU proxies still do not provide full image-quality evidence and must not be
presented as mesh-quality gains.

## Repository feasibility

ManyMesh source assets include UVs. The formal `mmgeo` chain OBJ export writes UVs at every LOD;
some older candidate-capture OBJ files discard them, but they are not required for this path.
`CornerSimplifier` tracks per-corner UVs and normals, and `LodGraph` stores generated attribute
vertices. Its exposed graph has no persistent fine-to-coarse point map, but ReSTIR-LoD reconstructs
surface correspondence from common UVs, so persistent provenance is not inherently required. A
four-asset UV preflight sampled nine transitions: all 90,000 forward samples found target support
and all pointwise nearest-map round trips returned to the source branch, including Cloth with
roughly 63% overlapping UV hits. This finite uniform-UV-area probe closes “fill map support” as a
candidate mechanism for these assets; it says nothing about path-weight efficiency. See
[`RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md`](RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md).

ManyMesh itself has no ReSTIR path tracer, but a public [ReSTIR-LoD implementation](https://github.com/elite-sheep/ReSTIR-LoD)
exists: it is built on Falcor 8.0, includes headless Python render drivers, and can potentially serve
as the renderer/baseline rather than requiring a renderer to be written from scratch. Its README
says the Chessboard scene is not included and must be downloaded separately. The visible repo
license is NVIDIA's permissive source/binary license, with separate terms for linked components;
review those before incorporating code. This machine's `vulkaninfo --summary` reports only Intel
Iris Xe integrated graphics and no Vulkan ray-tracing pipeline/acceleration-structure/ray-query
extensions. No ReSTIR-LoD checkout, Falcor build, or scene import has been done. A GPU ReSTIR
variance experiment is not currently available in this environment; remote/other GPU access remains
a prerequisite to validate the remaining path-statistics hypothesis.

## Decision

Keep this as a low-confidence hypothesis for one more prior-art/feasibility gate. Do not change the
production simplifier, start a GPU renderer port, or claim novelty until a contribution-aware
offline objective predicts real independent-run variance and covariance better than the direct
runtime controls, and can be evaluated at tolerable total cost.

## Targeted prior-art delta (2026-11-17)

Three targeted searches used the phrases “collapse ReSTIR mesh simplification,” “path reuse mesh
simplification LOD path tracing,” and “temporal covariance mesh simplification level of detail.”
They did not return a direct publication on optimizing a mesh collapse sequence for the full
ReSTIR estimator's image-error/correlation/cost frontier. This is only a bounded search result;
it does not establish that no such work exists.

The closest confirmed boundaries remain substantial. ReSTIR-LoD already provides cross-topology
surface mapping, temporal/spatial path reuse, and the mapping Jacobian; it demonstrates quality
changes specifically around LOD transitions. ReSTIR PT Enhanced adds reciprocal neighbor selection,
footprint-based shift criteria, and duplication maps, so those are required runtime controls.
Appearance-Driven Automatic 3D Model Simplification already optimizes rendered image-space
appearance with a differentiable renderer. Consequently the candidate distinction is only the
offline collapse-order objective evaluated under the complete reuse estimator and modern runtime
controls. Neither the 1,000-sample CPU visibility proxy nor the UV-fiber census evaluates that
objective.

## ReSTIR-LoD discussion-section audit (2026-11-17)

The primary paper's evaluation concentrates on frames immediately before and after an LoD switch.
It attributes the remaining quality loss partly to UV-map imprecision and partly to normal
differences between LoDs. Its stated future directions are robust vertex mappings for other
changing surface representations and per-ray LoD selection. The candidate here must stay separate
from both: it holds the published mapping and object/frame LoD policy fixed, and asks whether the
*mesh collapse sequence* changes the full estimator's transition error/correlation/cost frontier
at matched geometry budgets. A UV- or normal-preserving collapse score alone would remain crowded
and would not establish this distinction.

This sharpens the first renderer experiment: compare transition frames and steady-state frames
separately, with independent sequences and matched triangle/geometry budgets; use ReSTIR-LoD's
mapping unchanged, and include ReSTIR PT Enhanced controls at equal total cost. It still does not
specify a novel collapse algorithm or show a positive effect. The missing renderer experiment is
decisive, not a formality.

Primary sources: [SIGGRAPH 2027 schedule](https://s2027.siggraph.org/program/technical-papers/),
[ReSTIR-LoD, SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/),
[ReSTIR PT Enhanced, I3D 2026](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/),
and [Appearance-Driven Simplification](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/).

## WARP renderer feasibility attempt (2026-11-17)

The public ReSTIR-LoD repository was shallow-cloned at commit `37d13d9b1f3e76be88aa79109d24b0fe6e4ef6a9` to `out/research/restir-lod`; all six declared Git submodules initialized successfully. It contains the Falcor source tree and the ReSTIR pass, so this did not require a renderer port. Its Python `common.py` hardcodes `gpu=0`; Falcor's Python `Testbed` accepts a GPU index, and its `Device` code enumerates adapters and creates the selected adapter by LUID. At the time, no adapter list had been obtained.

This initial Packman attempt failed twice while fetching the first 20.39 MB packaged Python dependency with `SSLEOFError`. That blocker was later resolved by using Packman's supported external-Python setting and a local package cache; the full manifest succeeded. Falcor was then configured and built, including its Python extension. A subsequent import was denied by Windows Application Control, including an elevated retry. Consequently no adapter list, DXR dispatch, ReSTIR frame, or estimator measurement was obtained. The current blocker is binary execution policy rather than dependency acquisition.

The branch remains a research hypothesis, not a SIGGRAPH contribution. Falcor's official build documentation lists an NVIDIA DXR GPU and NVIDIA driver as prerequisites; WARP is software and, even if a later build renders, can only support small correctness/variance pilots, not performance claims. The decisive measured gap remains unchanged: a reuse-aware collapse objective must beat the published mapping with modern runtime reuse controls on independent sequences and held-out assets at equal total cost. See the [ReSTIR-LoD implementation](https://github.com/elite-sheep/ReSTIR-LoD) and [Falcor build requirements](https://github.com/NVIDIAGameWorks/Falcor#prerequisites).

## CPU single-vertex GRIS weight screen (2026-11-17)

A paired CPU preflight now evaluates exact single-merge RGB covariance on five existing Torus/Sphere LOD transitions. With a source-luminance proposal and 5% uniform directional support, glossy Torus L1→L2 has a 2.178× relative total-MSE ratio (family-wise paired-difference interval +0.525 to +2.997); Sphere L2→L3 has 1.053× (+0.017 to +0.124). An independent seed reproduces positive intervals for both. Raising the uniform support floor to 0.25 and 0.50 leaves both intervals positive, although effect size varies and cross-LOD ESS falls. The strongest Torus decomposition points to between-candidate-set variance after mapping, not just the conditional reservoir selection term.

This is a synthetic one-vertex result on the existing chain, not a path tracer and not evidence that a contribution-aware collapse order helps. It omits visibility, camera/path domains, real materials, iterative ReSTIR history and temporal covariance; no alternate collapse order was tested. The exact settings, tables, hashes, limitations and next gate are in [the CPU weight screen](RESTIR_CPU_WEIGHT_SCREEN_20261117.md). Keep the hypothesis low-confidence until a real renderer shows a matched-cost full-estimator frontier gain over ReSTIR-LoD and current reuse controls.
