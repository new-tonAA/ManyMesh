# SIGGRAPH 2027 LOD research: literature delta and remaining test

Date: 2026-11-15  
Status: literature screen, not a novelty claim.

## Current screen: shared traversal also leaves little useful opportunity

The [fused-patch cost gate](FUSED_PATCH_VISIBILITY_COST_GATE.md) attaches contained fixed-boundary
proxies to existing source BVH nodes, avoiding the former independent support traversal. Across
three capacities and three assets, 1,737 reduced patch geometries and 258,048 reconstructed queries
pass independent checks. A free full-equivalence classifier with perfect local fine/proxy costs
saves at most 1.00%/3.33%/0.113% for Torus/Monkey/Pirate under explicit AABB=1, triangle=2 weights.
The actual reference has no reliable speedup after uniform scalar-cache and paired CPU/wall-time
audits. Stop expanding this combined-cone, fixed-cut implementation on the reused assets.

Further primary sources constrain novelty: [GPUOpen 2022](https://gpuopen.com/learn/why-multi-resolution-geometric-representation-bvh-ray-tracing/)
describes internal-node approximation and cites older RLOD plane proxies; [N-BVH, SIGGRAPH 2024](https://iliyan.com/publications/NeuralBVH/)
combines neural ray queries with classical BVH queries; [Bethe et al., CGF 2020](https://doi.org/10.1111/cgf.14008)
uses illumination, shadow-silhouette importance, and QEM to guide reduction. Generic node-local
substitution, local query representations, or shadow-aware mesh reduction are not new claims.
The N-BVH author abstract and GPUOpen article were accessible; their large PDFs exceeded tool
limits, so no exhaustive full-method comparison is asserted.

A standard oriented-chain argument permits weaker one-sided predicates: same-facing proxy
triangles certify a proxy hit, whereas same-facing source triangles certify a proxy miss. An
exact rational folded-fan/cap control verifies the distinction and its invalid converse. Structural
cone checks add 308 possible hit-certificate and 1,422 miss-certificate patch/view pairs out of
20,844; these are not weighted by actual queries or costs. No asymmetric runtime, acceleration,
robust floating-point proof, or novelty conclusion follows. It remains a specific unproven cost
question rather than a new algorithm claim. The SIGGRAPH objective remains unmet.

## Current decision: compact separate support queries fail the full-cost gate

The [complete-query cost experiment](VISIBILITY_QUERY_BVH_COST_GATE.md) supersedes the optimistic
support-only interpretation below. A compact edit-AABB/circular-cone SAH hierarchy reduces storage
but adds a separate traversal. Nine frozen pairs reproduce external raster targets and all 29,321
known disagreements route correctly; 331,776 serialized fine/coarse/hybrid queries independently
reproduce answers and counters. Yet all nine cases use more AABB tests, more triangle tests, and
additional cone tests than the ordinary fine BVH. Instrumented Python queries take 1.61--2.38x
the time; no native/GPU result is claimed. Close the current separate-support-tree prototype.

Two more precedents constrain the next claim. [Johnson and Cohen, I3D 2001](https://www2.cs.utah.edu/gdc/publications/papers/johnsonI3D2001.pdf)
already uses spatialized normal cone hierarchies for silhouettes and area-light shadow boundaries
(primary abstract accessible; full-PDF fetch timed out). [Silhouette Clipping, SIGGRAPH 2000](https://hhoppe.com/silclip.pdf)
uses progressive hulls, an anchored-cone edge search hierarchy, and stencil/alpha clipping of coarse
rendering to the fine exterior silhouette. It explicitly requires static closed/oriented meshes
and an exterior viewpoint, and leaves internal silhouettes polygonal. Those differences do not
make generic exact silhouette correction, cone queries, or progressive hulls new here. A fused
traversal is only an unimplemented question; it needs a specific mechanism and comparison rather
than a new name for old hierarchy machinery. The SIGGRAPH contribution remains unestablished.

## Latest test: orientation-filtered edit support merits a total-cost check

The [edit-support preflight](EDIT_VISIBILITY_SUPPORT_PREFLIGHT.md) replays 8,184 frozen collapses
and checks fixed oriented patch boundaries plus consistent projected face orientation. A separate
saved-mask validator confirms 324 hybrid/fine binary coverage comparisons exactly on the finite
grid. At roughly half faces, filtering changes fallback inside the source screen rectangle from
83.84% to 36.83% for Torus, 43.91% to 5.87% for Monkey, and 42.37% to 34.43% for Pirate.
History boxes alone are nearly the same as the endpoint-difference control. Pirate at roughly
quarter faces still falls back on 97.25% of fine hits, and flat hull vertex storage alone is about
six times the captured indexed source mesh at half faces. No net query-cost benefit is established.

The underlying tools have old precedents: [Simplification Envelopes, SIGGRAPH 1996](https://www.cs.umd.edu/~varshney/papers/simp_env.pdf)
and [Xia, El-Sana, and Varshney, TVCG 1997](https://www.cs.umd.edu/gvil/papers/av_vd.pdf), Sections
IV-C and V-A.1, combine merge hierarchies, normal cones, visibility, and silhouette refinement.
These exclude claims that normal-cone filtering or history by themselves are new. A concrete
composition for exact any-hit query acceleration still needs a distinct representation, prior-art
comparison, and total-cost measurements. Seven targeted tests include a finite-segment
counterexample: full projected coverage invariance does not preserve arbitrary clipped shadow
segments. Endpoint/box-span guards, an independent intersection kernel, compact query hierarchy,
and realistic ray costs remain work to do. This is a surviving narrow cost experiment, not an
established SIGGRAPH contribution.

## Current screen: unbiased geometry-proxy correction is direct prior art

The [proxy-visibility cost gate](PROXY_VISIBILITY_COST_GATE.md) records a direct EGSR 2014
predecessor for unbiased approximate-geometry visibility with stochastic exact/correction queries,
and the explicit time-times-variance objective in SIGGRAPH Asia 2024, Equations 29 and 33--35.
Generic unbiased proxy correction, adaptive correction probabilities, and a variance/cost objective
are not sufficient new claims. Occlusion-preserving geometric proxies also have a CGF 2014
predecessor, and cheap neural estimates plus unbiased residuals are established in CGF 2025.

Nine frozen QEM outputs were rerasterized against three archived source captures for all twelve
views (108 comparisons; all old raw disagreement counts reproduced). The new gate separates
per-pixel coverage-image variance from the much larger variance of a scalar area integral.
For constant-probability Bernoulli correction, quarter-face Torus/Pirate outputs cannot improve
the coverage-image variance/cost product even with a free proxy; half-face outputs need proxy
query costs below 19.62%/19.72% of fine cost before overhead. Monkey may remain feasible in the
finite coverage model, but no actual ray-query cost or lighting result exists. No discrete proxy
construction mechanism beyond prior art has been established. This is a further screen, not a
new renderer implementation or a completed SIGGRAPH contribution.

## Current correction: mixed-cut ReSTIR is not an established estimator gap

The later [measure screen](RESTIR_MIXED_LOD_MEASURE_SCREEN.md) supersedes the optimism of the
mixed-cut follow-up below. ReSTIR-LoD 2026 explicitly says its **formulation** is not restricted
to one LOD per object per frame; the restriction is implementation-specific. It already permits
partial bijections and includes area Jacobians. Exact rational enumeration of a finite mapped
sample model gives the correct integral for both full and partial maps using standard weights;
the deliberately missing-Jacobian and incomplete-support controls are biased. This is not a
real-ray/path-selector result, but it removes the currently asserted reason for a new estimator.
Generic mixed-cut/per-ray reuse is therefore downgraded as an active novelty claim pending a
specific counterexample and useful mechanism beyond that formulation. No separate renderer
integration is justified by the implementation restriction alone.

## Follow-up boundary: compatible parallel simplification is also established

[PaMO (Pacific Graphics / CGF 2025)](https://arxiv.org/html/2509.05595v1), Sections 5.1–5.3,
uses cost-propagation independent regions, link-condition checks, parallel triangle-intersection
detection, and repeated undo/recheck until conflicts are removed. Its pipeline remeshes the input
before simplification and later performs safe projection. Thus independent local edits, batch
validation, intersection detection, and reverting conflicting edits are not standalone new claims.
Its task differs from preserving an authored ManyMesh asset and constructing a mixed-cut DAG;
that difference still needs an algorithmic and measured result. No PaMO runtime comparison was
performed here, and a combinatorial assembly audit is not its intersection-free guarantee.

[US10043309B2, Maintaining consistent boundaries in parallel mesh simplification](https://patents.google.com/patent/US10043309B2/en)
also describes independently simplified component meshes, synchronized boundary simplification,
manifold verification, and geometry insertion when a boundary collapse would violate manifoldness.
The inspected publication records priority in 2015 and publication in 2018. This is another reason
not to promote generic boundary-compatible parallel decimation as new; no legal conclusion is made.

The current [seam-contract control](SEAM_CONTRACT_MERGE_CONTROL.md) reproduces an existing
ManyMesh shared-position/chord safeguard in the Python experiment. It does not constitute a new
compatibility certificate, a production-faithful complete simplifier, or a contribution established
by the earlier invalid combinations. The search now explicitly includes these methods before
considering any proposed relaxation of conservative seam locks.

## New work that changes our boundary

| Work | What it establishes | Consequence for ManyMesh |
|---|---|---|
| [Learned Localized Mesh Refinement, SIGGRAPH Asia 2026](https://doi.org/10.1145/3829340.3842280) | A progressive vertex-split forest plus local autoregressive model supports region-selective refinement, including view-dependent refinement under a face-count constraint. | Adaptive/local mesh refinement, view-dependent split selection, and “more detail where needed” are occupied claims. Its learned generative reconstruction task differs from simplification of a fixed Filament asset, but that difference needs a result, not wording. |
| [T²-Splat, arXiv:2611.06974, 2026-11-04](https://arxiv.org/abs/2611.06974) | Offline differentiable reconstruction alternates QEM-based edge collapse and gradient-driven vertex split, then optimizes appearance on fixed topology. | Collapse/split driven by image reconstruction quality and adaptive topology are no longer broad novelty claims. The paper's objective and deployment are not runtime LOD for an authored mesh. |
| [Construction of clustered HLOD with As-Simplified-As-Possible boundaries, CGF 2026](https://doi.org/10.1111/cgf.70380) | A clustered progressive-mesh hierarchy simplifies node boundaries while maintaining crack-free adjacency. | “Repair hierarchy by simplifying more boundary geometry” is not a safe claim. The paper changes boundary representation; ManyMesh's earlier split retry instead divides a failed merge group. |
| [PQ-Free HD, TOG 2026](https://doi.org/10.1145/3811324) | A GPU branch-and-bound method computes Hausdorff distance and demonstrates a strictly Hausdorff-bounded GPU mesh simplifier. | Strict Hausdorff-bounded simplification and GPU execution are occupied claims. |
| [Dynamic Mesh Processing on the GPU, SIGGRAPH 2025](https://doi.org/10.1145/3731162) | GPU patch structures and conflict processing support general dynamic triangle-mesh operations. | Generic GPU topology edits, patch updates, and dynamic edge collapse are not contributions by themselves. |

The first four works were checked from their paper records/abstracts and, for T²-Splat and Learned Localized Mesh Refinement, accessible paper text. This is not a complete prior-art search. “Different task” is a comparison boundary, not proof that the remaining problem is new.

## Narrow question still worth testing

ManyMesh has evidence that its current DAG can make a requested triangle budget unreachable: the selector cannot choose a cut finer than the root cut. For Pirate, the earlier group-size scan reached 56.09%, 59.04%, 56.33%, and 63.59% at the `--dag-group` settings 2, 4, 8, and 16, all above the 55% target. A later topology-base correction changed one previous 55% conclusion, so old reachability values must be read with the correction in the ledger.

An existing spatial split-retry experiment recursively bisected rejected groups (8→4→2). It improved same-budget error or reachability for Pirate and Lucy, but only on two small assets and at about 1.5–1.65× DAG construction time. That is a useful pilot, not a publishable result.

The remaining research question is deliberately narrower than “adaptive LOD”:

> Given a fixed asset contract and a build-time ceiling, can a target-budget-conditioned repair policy add only the hierarchy alternatives that increase the quality-valid reachable-cut frontier, and outperform blind recursive bisection at the same construction cost across unseen assets?

For asset `A`, current hierarchy `H`, repair `R`, and a requested budget `b`, let `C(H+R,b)` be the cuts that meet the face budget and all existing topology, attribute, and geometric gates. Measure (1) whether `C` is nonempty, (2) the best existing screen-space error among those cuts, (3) build time and peak memory, and (4) validity failures. Do not treat reaching an exact face count as sufficient if the quality gates fail.

## Next experiment gate

Before implementation beyond a prototype, freeze the following comparison:

1. **Methods:** current DAG; current blind split retry; a target-budget-conditioned repair policy. Include the 2026 clustered-HLOD method as a conceptual/implementation baseline where the authors' method or a faithful reproduction is available; otherwise document the limitation and do not imply a direct comparison.
2. **Budget:** compare methods at equal DAG build-time ceilings, not only with identical recursion depth. Report the repair-time/peak-memory frontier.
3. **Data split:** use multiple asset families and hold out complete assets from policy tuning. The two pilot positives (Pirate, Lucy) cannot be the only evidence.
4. **Quality:** evaluate identical frozen cameras plus continuous held-out trajectories; report every target ratio, failures, and error tails. Preserve all existing topology/attribute gates.
5. **Stop rule:** stop this candidate if targeted repair does not beat blind split retry at matched construction cost on held-out assets, or if gains require relaxing any asset contract. A result limited to “more nodes after more build time” is not enough.

## Current implementation and artifact audit

Read-only source inspection on 2026-11-15 found that `LodGraph.cpp` uses a longest-bounds-axis median split for every rejected multi-member group, to a fixed depth of two. `LodGraphOptions` has no requested target triangle budgets; target-ratio selection is downstream of graph construction. The partition-retry profile records gate rejection counts, but `LodGroupObservation` explicitly describes these as observations rather than causal labels. Therefore “split according to the failure cause” is not currently implementable from the recorded data without improving instrumentation; aggregate gate counters must not be treated as the reason a particular group failed.

An inventory of the current `out/**/lod_graph.json` files found 328 graph exports, 12 asset filename stems, and 133 distinct hashes of a limited structural signature. Torus and Monkey account for 240/328 files, and repeated configurations dominate. This is **not** a 328-asset benchmark: the JSON files do not bind source content hashes, source revision, or whether all quality gates were enabled. The structural signature does not hash mesh geometry. These exports can help locate candidate fixtures, but cannot establish cross-asset generalization or support an evaluation table. The next experiment needs fresh inputs and manifests binding exact source meshes, code revision, build flags, quality-gate configuration, candidate policy, and target budgets.

This audit weakens the immediate path: the only defensible first prototype is target-budget-aware partition selection using explicitly measured counterfactual outcomes, not a heuristic inferred from current aggregate rejection counters. Before changing production code, compare the target-conditioned problem to established rate-distortion hierarchy construction and budgeted LOD selection; a new API parameter or a frontier table by itself is not a paper contribution.

## Diagnostic instrumentation progress (2026-11-15)

Added an optional 32-bin histogram of the exact five-bit quality-gate rejection mask to each DAG group profile and the `--dag-diagnostics` JSON. The bins count rejected simplification candidates across backoff attempts; they do not label a unique causal failure or identify which simplification backend produced each candidate. Histogram storage is allocated only when DAG diagnostics are requested, avoiding a 256-byte histogram allocation for every cluster in normal builds. This is measurement infrastructure, not the proposed LOD algorithm.

The Windows Release CMake build compiled `manymesh`, `test_manymesh`, `mmgeo`, and `test_utils` successfully. The project-preferred `./build.sh -ip desktop debug` could not start because the configured WSL virtual disk is missing. The existing Visual Studio Debug build stopped during project-reference resolution without a source compilation diagnostic. `test_utils` reported 320 passed, 3 failed, and 1 skipped; the failures were `AllocatorTest.LeakDetectorWithLeaksOnRewind`, `JobSystem.JobSystemLostWakeupRace`, and `WinPathTest.Split`. Windows application-control policy blocked both `test_manymesh.exe` and `mmgeo.exe`, so the new JSON field has **not** been runtime-verified. No claim of experiment completion follows from the successful Release compile.

## Novelty status

No new algorithm has been established. No one has demonstrated that this exact problem is unstudied; that requires broader database, dissertation, patent, and implementation searches before a submission claim. The candidate advances only if a principled policy changes the quality-valid reachable frontier at equal construction cost and does so across held-out assets with a meaningful effect size. If that fails, abandon this branch and reopen the problem rather than relabeling the current split retry.

## Temporal reconstruction and topology changes: follow-up screen (2026-11-15)

The official [SIGGRAPH 2027 Technical Papers page](https://s2027.siggraph.org/program/technical-papers/) lists the paper deadline as **2027-01-28 22:00 GMT** (submission form/conflicts: Jan 21; upload: Jan 29). From this research checkpoint that is about ten and a half weeks away. Since no new algorithm or validated end-to-end result exists yet, SIGGRAPH 2027 is a high-risk target; the date is a schedule constraint, not evidence that the work is ready.

The first-pass idea “preserve temporal history when LOD topology changes” is already too broad. [Real-Time Level-of-Detail Rendering with ReSTIR (SIGGRAPH 2026)](https://doi.org/10.1145/3799902.3811100) explicitly maps surface points across different mesh topologies to preserve spatiotemporal sample reuse. Its target is ray-traced light-transport samples, not raster TAA color history, but topology-aware history transport alone cannot be claimed as new. Earlier image-space blending of discrete LOD transitions is also established by [Unpopping (2007)](https://www.cg.tuwien.ac.at/research/publications/2007/GIEGL-2007-UNP/). A narrower raster-TAA/mesh-collapse interaction is not established as novel by this search; the search is not exhaustive.

The local feasibility audit confirms that `samples/mm_bench` has a Filament TAA switch, a per-capture camera path (`--frames`, `--pan` / `--translate`, and `--camera-out`), and runtime DAG cut updates when its camera changes. The harness holds each pose for `--warmup + --measure` rendered frames, captures a PNG, then advances to the next pose; with `--warmup 0 --measure 1`, it can advance the camera once per rendered frame after startup. `preRender` updates the distance-based DAG cut on those camera changes. The sequence path is implemented but has not been validated as a continuous TAA/cut-transition experiment. `tools/mmtemporal` remains an offline reprojection/blending experiment; its output is not Filament's TAA history. There is no measured sequence that binds per-frame camera poses, actual cut changes, TAA output, reference frames, and per-frame timing. This is missing evidence, not missing camera-path code.

The remaining potentially testable question is narrower and explicitly tentative:

> For a fixed authored mesh and a continuous camera path, can a collapse-history-derived raster correspondence/confidence signal reduce TAA transition error while retaining more valid history than the renderer's ordinary rejection path, at equal image quality and frame cost?

This formulation still faces strong nearby prior art: surface correspondence across LOD in ReSTIR 2026, long-established progressive/view-dependent mesh updates, image-space LOD blending, and appearance-driven image-space simplification ([Hasselgren et al. 2021](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/)). The possible distinction is specifically a source-surface correspondence propagated through simplification and used to predict which raster history remains valid during a topology transition. It is not currently stored as a collapse log: `GeneratedVertex::positionSource` is one original-vertex anchor, and `FrameHistoryEntry::TemporalAA` stores color, projection, jitter, and frame ID but no prior depth or source correspondence. The TAA shader reprojects from current depth with the previous projection and clips history against a current-color neighborhood. Adding correspondence therefore has real per-vertex or per-fragment storage and propagation cost. It has no measured benefit yet and might reduce to ordinary history-clipping/reactive-mask engineering.

A first kill test can use the existing frame path: select an asset and camera sweep, set `--frames N --pan D --warmup 0 --measure 1 --taa --dag --distance-lod --camera-out ...`, then require the captured camera list to have one pose per output frame and the `dag: cameraCut` log to report actual cut changes. Compare native TAA with (a) one-frame cut reset, implementable by setting TAA feedback to 1 for the cut-change frame and restoring it afterward (the API permits feedback changes at runtime), and (b) the proposed correspondence-aware validation. Use a matched camera path for a high-sample reference, report transition-local image error, temporal flicker, accepted-history fraction, frame cost, and correspondence bytes. The reset baseline must be verified against Filament's actual TAA history, not assumed from toggling the enabled flag. If the path does not generate cut changes, reject the capture instead of interpreting it as a successful run. If correspondence fails to improve the quality/cost frontier over these controls, stop this idea.

Current candidate ordering after this screen:

1. **Raster TAA with source-surface correspondence:** best experimental fit to the existing Filament harness, but high novelty risk and no validated camera/cut sequence. Use the existing per-frame capture path to establish the baseline before implementing correspondence.
2. **Target-budget-conditioned DAG repair:** technically measurable, but the current target-budget reachability question is close to rate-distortion hierarchy construction, view-dependent refinement, and modern cluster-LOD selection. A policy that merely builds more alternatives is unlikely to clear the novelty bar.
3. **Filtered-boundary local collapse:** useful mathematical/engineering work, but the accurate interaction model removed its speed advantage in the pilot, while the fast approximation had material prediction error. It needs a new mechanism and a result before promotion.

### Follow-up: mixed-cut temporal reuse has a narrower opening, with direct prior art

The SIGGRAPH 2026 ReSTIR paper states that its implementation assumes one LOD per object per frame and lists per-ray LoD selection as future work (Section 6). ManyMesh's DAG cut can already select fine and coarse nodes in the same frame. That suggests a more specific systems/research question: can a reservoir path be shifted between two *spatially heterogeneous cuts* with valid mappings and estimator weights at every surface hit, including when the path crosses a cluster/LOD boundary?

This is not a claim of new per-ray or mixed LOD. The EPO publication [EP 4 571 656 A1](https://data.epo.org/publication-server/rest/v1.2/publication-dates/2025-06-18/patents/EP4571656NWA1/document.pdf), paragraphs 0414–0425, describes multi-LoD BVH nodes that select child geometry using a per-ray bitmask. NVIDIA's public [vk_lod_clusters](https://github.com/nvpro-samples/vk_lod_clusters) already traces rays against a per-instance spatially mixed cluster cut and builds acceleration structures from it. NVIDIA RTXMG documents the same cluster-DAG workflow and a path-tracing renderer. The [ReSTIR LoD reference implementation](https://github.com/elite-sheep/ReSTIR-LoD) confirms the SIGGRAPH 2026 paper's UV-based cross-LOD shift and object-level LOD selection workflow. These occupy generic intra-mesh/per-ray LoD and ray-traced cluster cuts.

The remaining distinction, if any, would be the *correct temporal reservoir mapping and weighting between heterogeneous cuts*, not how to select the cut or trace a ray. The 2026 ReSTIR paper's UV-based mapping provides a close baseline and explicitly discusses invertibility and mapping ambiguity. A credible result would need a proof or estimator-level derivation for partial/non-bijective cluster mappings, and a measured quality/cost win over its object-level-LOD baseline and the public cluster-LOD path. A superficial port is not sufficient.

Feasibility is poor in this repository: a source search found no ReSTIR or path-reservoir implementation under `libs`, `samples`, or `filament`. ManyMesh supplies the hierarchy and raster harness, but no ReSTIR path tracer or ray-tracing integration. Pursuing this direction means building or integrating a separate GPU path-tracing testbed, so it is not a near-term experiment on the present code path. Keep it as a literature lead, not the active claim, until an estimator-level gap survives full related-work review. This also downgrades the raster-TAA provenance idea: it is easier to measure locally, but its distinct contribution appears weaker.

The current `LodGraph` stores the cut DAG, node triangles, shared vertex indices, and a `GeneratedVertex::positionSource` used for seam/lock handling. It does **not** store a source-face/barycentric map for simplified triangle interiors or an edge-collapse sequence. Therefore an ancestry-based shift map is not already available. A candidate would need to create a piecewise map from each selected cut's surface patches to a canonical source-surface domain, then define partial forward/inverse maps between old and new mixed cuts. At each reusable path vertex it must (a) reject ambiguous or uncovered patches, (b) map the path vertex through the cut change, and (c) derive the area/Jacobian term required by GRIS instead of applying a heuristic confidence weight. UV correspondence from ReSTIR LoD is the strongest baseline; a source-face chart or collapse provenance map is only a candidate if it handles assets without compatible UVs and produces a measurable advantage.

The first decisive preflight is not a full path tracer: on frozen pairs of heterogeneous cuts, exhaustively measure correspondence coverage, injectivity failures, mapped position/normal error, and numerical Jacobians against a high-resolution surface-map oracle. Include UV overlap, material seams, thin structures, disconnected components, nonmanifold inputs, and cluster boundaries. Stop before GPU integration if mapping is not mostly partial-bijective or its failures require global remapping; stop the research direction if UV-based ReSTIR mapping already gives equivalent coverage/cost on supported assets. Only after passing should the path-shift estimator be derived and integrated into a public reference renderer.

None of these is presently at SIGGRAPH submission standard. The raster-TAA candidate is the only one that can be cheaply killed or validated in the project's real renderer. The mixed-cut ReSTIR question has the sharper algorithmic gap to investigate, but it needs a mapping preflight, a separate path-tracing testbed, and a demonstrable estimator-level gap before it can become the active research claim.

### Follow-up: source-surface mapping is established prior art

The follow-up screen rejects **collapse provenance as a novel source of bijective surface maps**. [MAPS (SIGGRAPH 1998)](https://doi.org/10.1145/280814.280828) constructs a bijective map through a simplification hierarchy, representing original points in coarse base triangles with barycentric coordinates. [Appearance-Preserving Simplification](https://citeseerx.ist.psu.edu/document?doi=176e17618d72c8d33b12bb45900d1e656bbe54bd&repid=rep1&type=pdf) describes bijective mappings through edge collapses. More recently, [Surface Simplification using Intrinsic Error Metrics (SIGGRAPH 2023)](https://doi.org/10.1145/3592403) explicitly produces a bijective fine/coarse map, and [BijectiveRemesh (arXiv, 2026)](https://arxiv.org/abs/2605.30744) composes local bijective atlases across edge collapses, splits, swaps, and smoothing. Thus adding face/barycentric provenance to ManyMesh may be useful engineering, but the map representation, collapse ancestry, or map composition is not a defensible standalone novelty claim.

This also weakens the proposed heterogeneous-cut ReSTIR gap. If each cut patch has a valid map to a shared canonical domain, the obvious old-cut-to-new-cut correspondence is the composition `phi_new^{-1} o phi_old`; its local area factor follows from the component map Jacobians. That is a direct construction from known mapping machinery, not yet a new estimator. It remains unresolved whether partial domains, seams, cluster boundaries, and many-to-one geometric approximations make this composition unusable or biased for the SIGGRAPH 2026 ReSTIR-LoD shift/reconnection estimator, which currently assumes one object LOD per frame and lists per-ray selection as future work ([paper and PDF](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/)).

**Revised novelty gate:** do not implement a full path tracer just to demonstrate that composed maps carry a Jacobian. First construct an offline cut-pair preflight and compare (a) the composed bijective-map baseline, (b) the published UV-based ReSTIR-LoD map, and (c) a conservative reject/no-reuse baseline on frozen heterogeneous cuts. Measure full-path shift validity, uncovered/ambiguous fraction, Jacobian stability, and estimator agreement against high-sample references. The only potentially paper-level opening is a concrete estimator or mapping treatment needed specifically because the cuts are spatially heterogeneous, with a proof or controlled bias characterization and a substantial result against these baselines. If ordinary map composition plus the published shift estimator works, close this branch as an application/integration, not a new algorithm. The current checkout lacks the path tracer required for even the later end-to-end test.

The novelty search is still incomplete; the evidence supports rejecting the broad map claim, not asserting that the remaining mixed-cut estimator problem has never been studied. No SIGGRAPH-level contribution or result has been established.

### Main ManyMesh line: target-budget hierarchy repair has closer prior art than the first screen showed

The current research ledger's main mesh-reduction candidate is build-time repair of hierarchy groups that cannot produce sufficiently coarse legal parents. This is distinct from selecting a cut in an already-built hierarchy, but the boundary must be stated carefully. The 2001 HLODs paper already targets a face budget at rendering time and greedily refines the node with the largest projected error until the budget is met; it also provides image-quality and target-frame-rate modes ([full paper](https://gamma-web.iacs.umd.edu/HLOD/paper/HLOD.pdf), especially Section 6). Earlier time-critical multiresolution rendering formulates scene LOD selection as maximizing quality under a timing constraint ([paper record](https://www.sciencedirect.com/science/article/pii/S0010448500000683)). Thus selecting budget-feasible cuts, optimizing quality under a runtime triangle/frame budget, and reporting cut error frontiers are established problem classes.

The 2026 clustered-HLOD paper is more directly adjacent to hierarchy construction: it represents a mesh as clustered progressive meshes and progressively simplifies shared cluster boundaries while keeping neighboring cuts crack-free, reporting a better-quality and/or coarser representation ([publisher abstract](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380)). The publisher provides the abstract and bibliographic record, but the full text did not load in this screen, so no detailed algorithmic comparison is claimed. This makes “split rejected groups until simplification succeeds,” “make boundaries simplifiable,” or “improve coarse cuts by adding hierarchy alternatives” individually weak novelty claims.

Patent screening found a closer budget-and-splitting precedent: [EP 4 481 689 A1](https://data.epo.org/publication-server/rest/v1.2/publication-dates/2024-12-25/patents/EP4481689NWA1/document.pdf), also published as [US 2024/0420417 A1](https://patents.google.com/patent/US20240420417A1/en), sets a per-node primitive budget, generates LODs until a representation fits, and splits over-budget nodes along the longest bounding-volume axis; crossing triangles are clipped and assigned to both resulting nodes (EPO claims 1–3 and description [0015]–[0020]). Therefore budget-conditioned spatial subdivision for HLOD is occupied prior art. The remaining candidate distinction is narrower: ManyMesh's repair is triggered by failure to produce a legal simplified parent under topology/attribute/geometric gates, and would choose among repairs under a **global construction** budget to improve quality-valid runtime cuts. The patent's stated budget concerns node data / resource allocation, not an equal-total-build-time optimization of quality-valid cut frontiers. This appears to be a task distinction only; it does not establish algorithmic novelty or patent clearance.

An earlier [US 2020/0302692 A1](https://patents.google.com/patent/US20200302692A1/en) also claims hierarchical mesh tiles grouped by material/perception, with per-tile vertex/triangle/material budgets; over-budget tiles can be represented by placeholders whose children partition the original data into individually in-budget tiles (notably claims and description around paragraphs 119–142, 168–189, 292–293). This further rules out claiming on-demand tile subdivision, material-aware hierarchy construction, or satisfying per-tile primitive budgets as the contribution. Its purpose is tile/data organization and rendering/streaming cost, whereas the remaining ManyMesh candidate would have to center on quality-gate-induced simplification failures and fixed global build cost.

The only remaining distinction worth testing is an **offline construction algorithm** that chooses *which* rejected group/partition to repair under a fixed build-time and memory budget, using measured counterfactual gains across a preregistered set of requested triangle budgets while preserving topology, attributes, and geometry gates. Its output would be a Pareto frontier over (build cost, memory, quality-valid reachable cuts), not a new runtime selector. Even that is currently a candidate formulation, not a novelty claim: it may reduce to a standard budgeted search/knapsack over known hierarchy alternatives. The required baselines are therefore current hierarchy, blind recursive split, exhaustive/greedy partition repair at matched build cost, independently rebuilt hierarchy, and the 2026 boundary-progressive HLOD method if a faithful implementation or author-provided output becomes available. Evaluate held-out complete assets and bind source hashes, code revision, build flags, gate settings, and every budget in the manifest.

**Decision:** do not expose a target-budget API or implement another production heuristic yet. First establish from frozen, content-hashed assets whether any repair policy changes the quality-valid frontier at equal construction cost, then test if its decisions outperform simple greedy marginal gain per build second. If the winner is the greedy baseline, or gains come only from spending more build time / relaxing asset gates, this candidate does not contain the sought contribution. Together with the ReSTIR mapping screen above, the current worktree has no surviving demonstrated SIGGRAPH algorithm; this is a continue-search decision, not a goal completion.

**Current execution check (2026-11-15):** the latest available `out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe` is present, but even `--help` was denied by Windows Application Control, including after an explicit elevated retry. No binary was copied, renamed, or run through another environment. Therefore this turn did not create fresh DAG measurements; archived `lod_graph.json` exports remain exploratory only because most do not bind the exact input mesh, source revision, build flags, and gates. The experiment is still actionable if this exact executable is permitted or a normal authorized build/runtime becomes available. The refusal is an execution constraint, not evidence against the algorithm.

For a reproducible rerun, I recorded the exact current inputs and executable without claiming they have been measured by this binary. Repository revision is `6836c6e48` with a dirty worktree; the relevant source files and executable have their own SHA-256 bindings. The CMake cache identifies the Visual Studio 17 2022 generator and Release flags `/O2 /Ob2 /DNDEBUG`.

| Role | Path | Bytes | SHA-256 |
|---|---|---:|---|
| Asset | `assets/models/torus/torus.obj` | 71,835 | `6A97E75507CAF5322D9C8BBA243304A880C08152AB76836D2C35AF02F87CB4EC` |
| Asset | `assets/models/monkey/monkey.obj` | 1,418,731 | `7B754119AA286FF618B9AC30038C8AA9A093E2820242913728C8B20D8000CA88` |
| Asset | `third_party/models/lucy/lucy.obj` | 2,520,205 | `689D7C8BC69F3D02D8B2A961B76CD40B154829719E4076FBCEA86D498685B42A` |
| Asset | `third_party/meshoptimizer/demo/pirate.obj` | 368,962 | `CF11EA6F1FAD6688123FBB80C5CA39AD5E48908CFA53D68E09A3F03F53C524A1` |
| Source | `libs/manymesh/src/LodGraph.cpp` | 73,180 | `9A5E5DAB0E12762803C74DB5B35BAB2756F6998A96E584EB32E40E14F2A5460E` |
| Source | `libs/manymesh/src/Simplifier.cpp` | 83,003 | `9C7DCFCE176DF66B10AAC6F4BCD35A6E71F53CBB4BB8B2612B4AF2F0C4523F5A` |
| Source | `tools/mmgeo/src/main.cpp` | 121,243 | `1CA3C71A1F514129778858782B80DDFA24EE65441A59D80D3B4C6B1E44486820` |
| Executable | `out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe` | 1,930,752 | `46B5AB1FE0CBF2AB9C2E1EB900FD94DFB7DF08665EDDCE955118849E96774900` |

### Follow-up prior art: variable-granularity progressive repair

A closer search found *Progressive Compression of Generic Surface Meshes* (CGI 2015).
It groups edge collapses into waves, automatically chooses each wave's size from a distortion
metric, and explicitly describes a distortion-aware collapse-clustering strategy for the
rate-distortion tradeoff ([author manuscript](https://perso.liris.cnrs.fr/guillaume.lavoue/conference/CGI2015.pdf),
abstract and §3.1). This occupies adaptive decimation granularity and progressive rate-distortion
control. The paper's target is generic non-manifold/polygonal progressive compression; it does not
establish the exact ManyMesh contract of authored materials, local topology/attribute gates, and
cluster-DAG budget reachability. That difference remains a boundary, not evidence of novelty.

The classic HLODs construction paper also partitions spatially large objects, simplifies
partitions independently, hierarchically regroups them, and notes that alternative HLOD
construction choices trade representation quality against computation cost ([Erikson et al.,
full paper](https://gamma-web.iacs.umd.edu/HLOD/paper/HLOD.pdf), §4). Together with the 2026
boundary-progressive HLOD paper and the 2024 per-node-budget subdivision patent above, this
means the remaining proposed global-build-budget choice among rejected groups is increasingly
likely to be an application of budgeted combinatorial search over known alternatives. It should
not be promoted as a contribution until a counterfactual study shows a nontrivial interaction
or quality-valid frontier gain that simple greedy marginal gain per build second cannot obtain.

**Updated next gate:** first compare on frozen instances the exact best possible repair selection
(offline oracle), greedy marginal frontier gain / measured build second, and the current blind
8→4→2 retry under the same build-time ceiling. If the offline oracle itself barely changes the
cut frontier, close the hierarchy-repair line. If the oracle helps but greedy matches it, the
current policy idea is not the contribution; only a mechanism that demonstrably handles
nonadditive parent/cut interactions better than knapsack-style baselines survives.

### Follow-up: image-space candidate invalidation is the only narrow dynamic opening found so far

The broad claims “image-space error for edge collapse,” “local rerendering,” and “dynamic mesh
updates” are already occupied. [Lindstrom and Turk, *Image-Driven Simplification* (TOG 2000)]
(https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf) rank collapses by the
change in multi-view image MSE, update rendered images locally, and use screen-space rectangles
around replacement patches to evaluate an operation. Their paper explicitly notes that a collapse
can alter the score of a topologically distant edge when the projected regions overlap. It then
chooses to refresh only topological neighbors, reporting an average selected-edge rank in the best
0.1% on the Bunny, and 5% with lazy evaluation. It did not use antialiased images while simplifying;
the final image evaluation was antialiased at twice the resolution and used a different camera set.
Thus neither filtered-image scoring nor local image deltas can be presented as new.

The [Pfeiffer 2001 thesis, *A Localized Approach to Image-Driven Simplification*]
(https://www.cs.uoregon.edu/frames/reports.php?report=MS-200106-Pfeiffer) goes further on local
evaluation: it computes collapse cost from image data local to the edge and avoids maintaining
full images of the original mesh. Screen-local candidate evaluation and simplification without a
full-scene render are therefore also prior art. [Feature-Preserving Mesh Decimation for Normal
Integration (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/papers/Heep_Feature-Preserving_Mesh_Decimation_for_Normal_Integration_CVPR_2025_paper.pdf)
uses screen-space quadrics together with local edge collapses, flips, and vertex updates in its
normal-integration domain. Separately, [Dynamic Mesh Processing on the GPU (SIGGRAPH 2025)]
(https://doi.org/10.1145/3731162) occupies generic dynamic topology edits and GPU execution.

One precise gap remains testable, but not cleared: maintain a **globally correct candidate-cost
queue** after each accepted local operation by indexing each candidate's projected influence
support in every evaluation view. When an operation changes filtered pixels in region `D`, mark dirty
every candidate whose score support intersects `D`; do not assume that only mesh-ring neighbors
are affected. For a fixed view set and a finite-support image filter, this should be exact if the
influence regions conservatively include old and replacement geometry, filter support, and all
visibility changes at those pixels. It requires correct hidden-fragment restoration and must rebuild
or refit the screen index when the camera, projection, or filter changes. The key question is whether
the extra nonlocal invalidations are rare enough that the index beats full candidate rescoring while
avoiding the ranking drift of topology-only invalidation. This may still reduce to a standard inverted
screen-space index plus the 2000 image-delta method; no novelty claim is justified yet.

For a fixed candidate image delta `delta_c`, current filtered image `I`, and reference `I_ref`, its
incremental squared-error cost is
`DeltaE_c = 2 <I - I_ref, delta_c> + ||delta_c||^2`. An accepted operation `a` changes the current
image by `delta_a`, so the cached score of `c` changes by `2 <delta_a, delta_c>` when `delta_c`
itself stays valid. Disjoint finite filter supports make this cross term exactly zero. If supports
overlap, visibility/depth ordering or local topology may change `delta_c`, so the conservative action
is to rerender and rescore that candidate rather than extrapolate the cross term. The equation is
standard quadratic-error algebra; the candidate contribution, if any, is the exact sparse dependency
maintenance and a demonstrated quality/work win, not the formula.

**Next kill gate:** on frozen real meshes and fixed multi-view cameras, compare (1) topology-neighbor
lazy invalidation, (2) projected-support invalidation, and (3) a full-rescore oracle using identical
candidate placements, renderer, filters, and topology gates. Record exact selected-edge rank,
cumulative filtered image error at matched triangle counts, candidates rescored per accepted
collapse, support-index maintenance time, patch rerender time, and total wall time. Include crowded
projections, thin geometry, occlusion reveal, and finite-support filters; separately quantify support
truncation if a Gaussian kernel is used. Stop if projected-support maintenance approaches full
rescoring, if it does not improve the quality/work frontier over topology-neighbor invalidation, or
if its benefit is only a faster implementation of the old image-driven objective. Until this passes
and survives a search for equivalent visibility/incremental-rendering indexes, this is a focused
research hypothesis rather than the SIGGRAPH contribution.

### Full-pool support selectivity preflight (2026-11-15)

Extended `audit_projected_support_invalidation.py` from 48 sampled candidates to every initially
legal captured Corner candidate for each sampled event. The data covers Torus (3,456 candidates),
Monkey (45,746), and Pirate (10,170), six fixed orthographic views per asset, and 48 sampled event
candidates per view. This is still an initial-state, fixed-pool preflight: it does not replay a
sequence of accepted collapses, regenerate newly legal candidates, or measure end-to-end queue time.

The baseline uses one conservative screen rectangle per operation. A tighter variant stores the
union of per-affected-face rectangles spanning both old and replacement triangles, expands each by
the same six-pixel finite-filter halo, and queries those fragments through an 8-pixel tile index.
Across the archived 48-candidate pools, the fragmented support missed zero of 1,762 measured
filtered-delta cross pairs above the 1e-14 absolute floor and zero of 1,759 above-floor ranking
reversals. These are finite sampled checks, not a proof over all geometry or candidate trajectories.

The tighter representation barely improves full-pool selectivity. Mean candidates dirtied per
event, including topology dependencies, changed from 1,166 to 1,141 for Torus (2.1% fewer),
11,179 to 11,127 for Monkey (0.5% fewer), and 3,384 to 3,374 for Pirate (0.3% fewer). Mean dirty
fractions for the fragmented variant are 33.0%, 24.3%, and 33.2%; the maximum per-view 95th
percentiles are 44.5%, 44.3%, and 70.1%. Thus empty space inside the single bounding box is not the
main source of invalidations. Candidate supports overlap densely in these projections.

The literature screen now includes Turk's dissertation, which states that distant edges can change
cost when close in a view, gives the condition under which a candidate cost stays unchanged, and
uses lazy evaluation rather than identifying all affected candidates; it reports a fivefold cost-
evaluation reduction with degradation in average selected-edge percentile from 0.05% to 5% for one
test case ([dissertation, Section 7.2.2.1](https://citeseerx.ist.psu.edu/document?doi=9ab25b00fa1e2888bb04cbb4af87f383427cfd71&repid=rep1&type=pdf)). The same thesis already presents local image updates, incremental metric evaluation, and screen-space bounds in Chapter 6. This makes a projected-support index plus exact dirty marking a narrow implementation hypothesis, not a novelty claim.

**Decision:** close the per-face-fragment refinement; it does not solve the observed selectivity problem. Retain exact screen-support invalidation only as an unproven systems question until an exact full-queue trajectory beats both topology-neighbor lazy evaluation and full rescoring on total work while preserving the oracle's selected sequence or demonstrating a quality/work frontier gain. No SIGGRAPH-level contribution is established.

### Corrected finite-pool queue replay (2026-11-16)

Added `simulate_projected_support_queue.py` and compared three policies on the same accepted
trajectory: a full current-state oracle, cached costs refreshed for candidates whose conservative
projected supports overlap the accepted edit, and initial costs left stale except for topological
conflicts removed from the fixed pool. The valid runs covered Torus/Pirate, 48 candidates sampled
from the archived frame-0 set or uniformly from the full initial legal capture, 2 or 6 views, and
4, 8, or 12 accepted operations. The full-orbit runs used six cameras spaced around 360 degrees.
Every accepted candidate was applied to the actual mesh; candidate scores were the exact measured
change in the archived renderer's finite-filtered coverage/depth squared error. A consistency check
is implicit in the logs: measured image-energy change equals the selected candidate's computed
delta to floating-point precision.

Across all **five valid runs**, screen-support refresh and stale-topology-only refresh selected the
same operation IDs as full rescoring at every step. Screen-support refresh reduced candidate score
evaluations by 37% (Torus, two views / four steps), 55% (Torus, six archived-arc views / 12 steps),
71% (Pirate, six archived-arc views / 12 steps), 15% (Torus, six full-orbit views / eight steps),
and 33% (Pirate, six full-orbit views / eight steps). The topology-only cached queue used only the
initial 48 scores and also matched the oracle sequence in every case. For example, on full-orbit
Torus, measured score time was 14.03 s for the oracle, 11.83 s for support refresh, and 2.34 s for
the stale queue; these are Python research-kernel timings, not native end-to-end measurements.
Full-orbit Pirate's final sampled image error was only 1.07e-10, so that trajectory contains little
quality signal despite covering all view directions.

An earlier replay output under `out/projected-support-queue-v1/` and `v2/` is invalid: the first
version scored the unchanged current faces instead of the proposed collapsed faces and reported
spurious zero deltas. Those JSONs are retained only for audit and are marked invalid in their output
directory. All conclusions above use the corrected `v3/` and `v5/` artifacts, whose manifests bind
the script, renderer, capture, report, candidate IDs, view angles, and settings.

Limitations remain decisive: only 48 candidates are considered; candidates sharing any affected
vertex are removed rather than regenerating the newly legal local operations; camera and raster
resolution are fixed during each replay; the sampled meshes are development assets; and the Python
kernel does not measure a production queue or an end-to-end simplifier. Even within this favorable
fixed-pool model, support invalidation did not improve the selected sequence or final image error
over topology-only stale keys. Combined with the 24%--33% mean full-pool dirty fractions and the
negligible (<2.2%) benefit from fragmented supports, this line has no demonstrated quality/work
frontier gain.

**Decision:** stop promoting projected-support invalidation as the SIGGRAPH candidate. Its exact
dirty-set argument remains a possible engineering refinement to established image-driven lazy
evaluation, but the current evidence shows no output advantage, and the literature already gives
screen-space support conditions and lazy-ranking tradeoffs (Turk dissertation, Section 7.2.2.1).
Reopen only if a complete candidate-generating trajectory on materially more views produces a
repeatable ordering or quality gain over lazy evaluation and a native end-to-end cost win over full
rescoring. The SIGGRAPH objective remains unmet.

### Literature and repository fit check (2026-11-16)

The textured-mesh pivot is not currently a viable contribution. [Liu, Zhang, and Yuksel, *Simplifying
Textured Triangle Meshes in the Wild*, TOG 2025](https://www.cemyuksel.com/research/papers/simplifying_meshes_in_the_wild.pdf)
already targets on-the-fly simplification of arbitrary, including non-manifold, textured triangle
meshes and builds source-to-output surface correspondence for texture transfer. Its stated open
issue is visibility during the output-to-input map: nearest local projections can sample an interior
layer. However, view-dependent per-pixel visibility for texture mapping is established by
[Porquet et al. (2005)](https://dpt-info.di.unistra.fr/~dischler/papers/graphite05.pdf),
view-independent visibility-weighted simplification by [Zhang and Turk (2002)](https://sites.cc.gatech.edu/gvu/people/faculty/greg.turk/vis_simp/vis_simp.html), and adaptive
correspondence plus texture regeneration for multi-chart meshes by [Zhang et al. (2022)](https://doi.org/10.1016/j.cag.2022.05.021). Combining these ideas for persistent atlas baking on
overlapping non-manifold layers is a possible application boundary, but no algorithmic gap or
advantage has been established.

Repository fit is weak: `mmgeo` imports positions, normals, UV coordinates, and material IDs, and
its optional bakes cover normal, height, and AO maps; its OBJ import path does not load source color
texture images for appearance-transfer experiments. `assets/models/monkey/` contains a set of PBR
images, but the model has no matching checked-in MTL file that binds those images into a reproducible
texture-transfer case. This direction would need a curated multi-layer textured dataset and a new
appearance-transfer evaluation path before it could be tested here. Do not start an implementation
from the paper's future-work sentence alone.

The broad “on-demand” and “time-bounded” simplification claim is also occupied. [Brodsky and Watson,
*Model Simplification Through Refinement*, Graphics Interface 2000](https://graphicsinterface.org/wp-content/uploads/gi2000-29.pdf)
works from a coarse mesh toward finer approximations, controls output size at each iteration, and
frames the method around a displayable result within a specified time limit. It also discusses
refining earlier output and extending the divide-and-conquer method to continuous LOD. The recent
direction of refining a coarse state on demand therefore needs a new quality or systems result beyond
reverse refinement and a time budget.

Two additional screens narrow geometry-only claims. [PaMO, Pacific Graphics 2025](https://seonghunn.github.io/pamo/) remeshes wild inputs and performs parallel GPU simplification
with explicit intersection checks and safe projection. Thus GPU speed, intersection-free reduction,
and projection back to input features are not individually new. The 2026 preprint [FA-QEM](https://arxiv.org/abs/2605.14029) combines geometry, boundary-curvature, and normal-consistency
terms for generated and real-world assets, so “feature-aware multi-term QEM for wild assets” is
also too broad. These papers differ from ManyMesh's material/chart gates and cluster-DAG output, but
that contract difference alone does not create a contribution.

**Current candidate status:** raster TAA across a live ManyMesh cut change is kept only as the
cheapest next falsification experiment, not as a SIGGRAPH contribution. ReSTIR-LoD 2026 is especially
close: it explicitly identifies topology-changing LOD as breaking triangle-ID/barycentric history
mapping and resetting temporal reuse, then introduces UV-space mappings across topology changes;
the paper also discusses the same issue for motion-vector calculation. The remaining task boundary
is raster color-history validation in a cluster-DAG renderer, but that may be an application-level
transfer of known correspondence machinery. A paper claim would require a specific raster estimator
or validity rule with a substantial quality/cost win over native TAA and a cut-reset baseline. The
capture path exists; it still needs a measured sequence with actual cut changes, TAA output,
reference frames, and per-frame timings. No SIGGRAPH-level contribution is established.

### Attempted falsification capture (2026-11-16): blocked before launch

Attempted the cheapest next experiment with the existing headless renderer and the monkey OBJ:

```text
mm_bench.exe --frames 9 --pan 80 --warmup 0 --measure 1 --taa --dag
  --screen-error 1.0 --auto-frame --no-shadows
  --out out/taa-cut-falsify-20261116/frame.png
  --camera-out out/taa-cut-falsify-20261116/cameras.txt
  assets/models/monkey/monkey.obj
```

Windows Application Control refused to start `out/cmake-vulkan/samples/Release/mm_bench.exe`
(`ApplicationFailedException`: Your organization used application control to block this file, exit code 1). The output directory
was created empty before launch; no camera list, PNGs, cut-change logs, or timings were produced.
This is neither a negative nor a positive result for TAA. The exact command and file hashes are
preserved in `out/taa-cut-falsify-20261116/blocked-run.md`. No rename, alternate executable, or
alternate runtime was used to work around the control.

Post-hoc audit also invalidated the older `out/runtime-lod-camera-check/orbit.*` sequence as a
candidate TAA dataset. Its camera list records `views 1`, `jitter 17`, with the eye fixed at
`(0,0,3.5)` while the target travels around a circle: this is a pan-away path, not an orbit around
the object. The log has eight `changed=1` entries, but ten of its 17 frames select zero triangles;
the corresponding PNGs are black. The frames do prove that a pan can change the distance-LOD cut,
but they do not form a continuous on-object LOD/TAA sequence. The correct orbit uses `--views 9
--frames 1` with no `--pan`. Also, `postRender` captures when `g_viewFrame >= warmup + measure`
before incrementing the counter, so `--warmup 0 --measure 1` captures the second rendered frame at
each pose. Capturing the first frame after each camera/cut change needs an explicit harness option
or other frame-capture mechanism; otherwise transition-local measurements are incomplete.

The literature check was tightened against primary pages for the closest adjacent work. The 2026
clustered-HLOD method already progressively simplifies shared boundaries while keeping neighboring
cuts crack-free ([Ladeuil et al., Computer Graphics Forum 2026](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380));
the SIGGRAPH 2025 GPU dynamic-mesh system already covers parallel decimation and generic topology
updates ([Mahmoud et al., TOG 2025](https://doi.org/10.1145/3731162)); and SIGGRAPH 2026 ReSTIR-LoD
already transfers temporal samples between different mesh topologies ([Wang et al., SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/)).
Earlier work already makes temporal LOD continuity a mature area: Hoppe's view-dependent progressive
meshes create runtime geomorphs for temporally smooth arbitrary-mesh LOD, and *Unpopping* blends
discrete LODs in image space ([Hoppe, Microsoft Research](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/svdlod.pdf),
[Giegl and Wimmer, Computer Graphics Forum 2007](https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2007.00943.x)).
An even closer raster precedent is [Scherzer and Wimmer, *Frame Sequential Interpolation for
Discrete Level-of-Detail Rendering* (Computer Graphics Forum 2008)](https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2008.01255.x):
it alternates adjacent LODs across frames, reprojects the older color/depth/object-ID buffer, and
combines it with the current LOD to create a smooth transition at near-discrete-LOD rendering cost.
That makes “reuse raster history across a topology-changing LOD switch” itself established prior
art, not the remaining gap. A modern TAA-specific extension might still be technically useful, but
it is too small and too close to this method plus ReSTIR-LoD to retain as the paper's main claim
without a distinct estimator and a substantial result.
These sources make boundary freedom, GPU collapse, and topology-aware temporal reuse unsuitable as
standalone claims. The only surviving TAA distinction is a raster-history estimator/validity rule
with a measured quality-cost win beyond geomorphing, image-space transition blending, and ReSTIR-LoD;
the targeted search did not establish that gap as novel. The renderer refusal leaves even the narrow
experiment unevaluated and does not revive any earlier killed candidate. Current status remains:
**no validated SIGGRAPH contribution**. A useful next experiment requires this exact executable to be
permitted by the normal application-control policy; until then, continue only with read-only
literature and archived-data analysis.

### Fixed-boundary endpoint QEM control (2026-11-16)

The [boundary-endpoint control](BOUNDARY_ENDPOINT_CONTROL_20261116.md) addresses the known
restriction in the archived Python `ProgressiveQEM`: it allowed no collapse if either endpoint was
locked. Allowing an interior vertex to collapse into a fixed boundary endpoint, while preserving
the exact boundary edge set and positions and retaining the reference local topology/orientation/
quality gates, reduces the 1,051 topology-supported capacity-32 groups from 14,752 to 13,228
triangles. This is 1,524 additional removals. Torus reaches its summed conditional floor in all 54
groups, Monkey in all 751, and Pirate in 241 of 246 supported groups; the five remaining Pirate
groups total only 16 faces above their floors. Three unsupported Pirate inputs remain excluded.

This substantially weakens the earlier hierarchy-repair interpretation: the locked-endpoint
reference, rather than the combinatorial partition floor, caused most observed exhaustion. It does
not show what production Corner does on these exact captures or prove a production-quality result.
The endpoint operation is established simplification behavior, so it is only a corrected classical
control. The SIGGRAPH contribution remains unestablished; the hierarchy-repair candidate should
not be revived without an equal-input production comparison and a different measured algorithmic
advantage.

### Boundary endpoint control meets the production source guard (2026-11-16)

A source-level call-path audit narrows the previous control. `CornerSimplifier.cpp` supports a
fixed placement at a border/locked keep vertex, but default `lockBorder=true` also rejects the
candidate when any face incident to the removed vertex does not contain that keep vertex. The
ManyMesh DAG builder uses the lock-border setting and enables paired seam collapse; `mmgeo` also
defaults corner simplification on. A replay of the 2,099 fixed-boundary endpoint actions from the
Python control found that **all 2,099 would be rejected by this fan precheck**. This shows the
production fixed-target path is narrower than the Python control's exact-boundary legal set; it does
not show whether relaxing the guard would pass the full production attribute and source-surface
gates. Reproduction and counts are in
`tools/mmgeo/audit_boundary_endpoint_actions.py` and
`out/boundary-endpoint-action-audit-20261116-v3/report.json`. A cross-group source-vertex-use proxy
for the production locked mask marks 2,030 actions as shared-boundary targets; 2,023 of those still
fail the locked-chord check. Only 76 recorded actions avoid both checks under this proxy. The frozen
BFS partition is not the exact production leaf/group structure, so this count is diagnostic rather
than a predicted production gain.

The broader operation is not new: the [CGAL surface-mesh simplification manual](https://doc.cgal.org/6.2/Surface_mesh_simplification/index.html)
describes halfedge collapse as pulling one endpoint into the other, and earlier work explicitly
classifies edge collapses by boundary conditions. More directly, the 2026 clustered-HLOD work
progressively simplifies shared cluster boundaries while preserving crack-free neighboring cuts
([Ladeuil et al.](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380)). A plausible engineering
experiment is to replace the blanket fan rejection with an incremental exact-boundary-edge
certificate, retaining the locked-chord and attribute checks. This is not a novelty claim: boundary
simplification is occupied, and it needs a full prior-art comparison plus matched production
quality/build-cost measurements before it can be considered for the paper.

The [shared-chord proxy control](BOUNDARY_ENDPOINT_CONTROL_20261116.md) adds one more falsification:
under a partition-derived shared-vertex lock proxy, the geometry-only solver reduces the checked
capacity-32 outputs from 14,752 to only 14,630 triangles, a gain of 122 faces (0.83%). It reaches
zero gain on Torus. This still omits production UV/normal, source-surface, and fan checks, so it is
not a prediction of production results. The boundary-guard relaxation is low priority on the current
corpus, and it is not a SIGGRAPH claim.

The adjacent corner/UV direction is also occupied more directly than the earlier broad search
showed. *Seamless* already derives seam-safe edge-collapse conditions and seam-aware shape/UV
handling ([Liu et al., SIGGRAPH Asia 2017](https://www.cs.toronto.edu/~jacobson/images/seamless-seam-erasure-and-seam-aware-decoupling-of-shape-from-mesh-resolution-siggraph-asia-2017-compressed-liu-et-al.pdf)).
*Progressive Compression of Arbitrary Textured Meshes* interpolates matched per-corner UVs and
accounts for texture seams ([Caillaud et al., Computer Graphics Forum 2016](https://perso.liris.cnrs.fr/guillaume.lavoue/revue/CGF16.pdf));
the 2022 multi-chart method adaptively updates correspondence and texture to relax chart-boundary
constraints ([Calabuig-Barbero et al.](https://doi.org/10.1016/j.cag.2022.05.021)). Thus generic
per-corner seam simplification, UV-preserving collapse, and avoiding seam locks are not safe
novelty claims. A ManyMesh paper would need a new certificate or measured advantage that survives
these methods and the repository's exact multi-unit seam contract.

### 2026-11-16: global quad reduction and local image-space collapse are direct precedents

The author-hosted SIGGRAPH 2026 paper *Global Discrete Optimization for Quad-Dominant Mesh
Reduction* formulates edge retention/removal as a global ILP, with poly-chord continuity and
QEM-derived geometric constraints. Its solver reaches the 180 s limit and does not guarantee
optimality in that budget. It is a direct precedent against broad novelty claims about global
discrete edge selection for mesh reduction; its stated target is quad-flow preservation, not a
view-specific filtered image objective or per-frame local edits. [Primary paper PDF](https://roy-zzz08.github.io/assets/pdf/Quad.pdf).

The publisher abstract for Ladeuil et al. 2026 confirms a clustered HLOD made from an internal
progressive mesh plus neighbor-corresponding progressive boundary portions, so boundaries can be
simplified while adjacent cuts remain crack-free. The full publisher text is currently unavailable;
do not infer finer implementation equivalence from the abstract. [Primary publisher page](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380).

Lindstrom and Turk 2000 already rank edge collapses by rendered multi-view pixel differences and
incrementally update local image regions using an object buffer or hardware redraw. Pfeiffer's
2001 thesis abstract goes further on localization, estimating a collapse from only nearby image
data without rendering the complete model. These close the generic claims “image-space collapse
cost,” “local rendering only,” and “incremental update” as new. [Lindstrom and Turk, primary
paper](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf), [Pfeiffer, University
of Oregon repository record](https://www.cs.uoregon.edu/frames/reports.php?report=MS-200106-Pfeiffer).

An additional search for globally optimized nested LODs found Balmelli, Vetterli, and Liebling's
rate-distortion / optimal-tree-pruning method, which constructs a multiresolution hierarchy with
global error on subdivision-connectivity meshes, as well as the earlier progressive-mesh sequence
representation. This does not settle arbitrary triangle-mesh or renderer-specific variants, but it
means “solve several target budgets together” is not by itself a safe novelty claim. [Balmelli et
al., Graphical Models 2002](https://www.sciencedirect.com/science/article/pii/S1524070302905783),
[Hoppe, Progressive Meshes](https://hhoppe.com/proj/pm/).

Implication: the analytic Gaussian-filtered step loss remains a mathematical model, not a
demonstrated differentiator. The current strip experiments have not established a general-mesh
accuracy/cost advantage over exact local redraw or production Corner. Keep the filtered-boundary
route below the SIGGRAPH contribution gate until a frozen real-candidate comparison shows a
substantial total-cost win and generalizes to unseen assets.

## Camera-motion raster events and collapse ranking (2026-11-16)

The new Torus localization experiment does not make edge/sample events a new mechanism. Popescu,
Sacks, Zhang, and Vazquez's *Complex VEs on All-In-One VR Headsets Through Continuous From-Segment
Visibility Computation* (TVCG 2025) computes, for each pixel center, translation intervals during
which a triangle covers it by solving edge-sidedness events, then depth-composites those intervals.
It is a linear camera-translation path and its goal is visibility-set extraction, rather than
filtered loss ranking among alternative collapses on a rotating orbit. Akenine-Möller, Munkberg,
and Hasselgren's *Stochastic Rasterization using Time-Continuous Triangles* (2007) also evaluates
time-dependent edge functions at spatiotemporal samples. These are close precedents for generic
event generation and rule out presenting pixel-edge event scheduling alone as the contribution.

Primary sources: [Popescu et al., full paper](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf),
[Akenine-Möller et al., full paper](https://fileadmin.cs.lth.se/graphics/research/papers/stoc2007/motion.pdf).

The only remaining candidate distinction is the specific object being maintained: a filtered
before/after image-loss ordering over a set of legal collapse alternatives as the camera follows a
rotating path. The experiment only found one Torus candidate/sample coverage-difference window, and
the winning collapse changed with raster scale: 1656 won every sampled angle at 1x/2x, while 2275
won every sampled angle at 4x/6x; at 3x the ranking flipped inside the localized interval. This is
not evidence of robustness or efficiency. At fixed 3x resolution, shifting projected geometry by
±0.10 pixels changed the result: three tested phases selected 2275 at every angle, while the fourth
selected 1656 for 20/25 angles after one coverage-difference interval ended. A next gate must
enumerate/build the intervals, measure their total work and memory against exact reranking, and
separate path correctness from sample-phase robustness. No dynamic implementation, performance
result, novelty conclusion, or SIGGRAPH-level result is established.

Two additional related works tighten the boundary. Eisemann and Décoret (CGF 2007) derive exact
view-dependent simplification error bounds for polygonal viewcells, including face-wide validity
regions that handle silhouettes and textures. Zhang and Turk (2002) combine a visibility measure
over a surrounding camera sphere with quadric error to guide edge collapses. Consequently, a generic
viewcell error bound or camera-space visibility-weighted collapse objective is not new.
[Eisemann and Décoret, author publication page and paper](https://publications.graphics.tudelft.nl/papers/724),
[Zhang and Turk, primary paper](https://faculty.cc.gatech.edu/~turk/my_papers/surfviz_vis2002.pdf).

### Target-budget DAG group-size control (2026-11-16)

With the same hashed Pirate input, executable, gate settings, and 55% target, `dag-group`
2/4/8/16/32 all selected 2,756/5,010 faces. Reported auto-camera screen errors were
19.3397/21.1741/12.4154/20.4373/12.5229 px at internal build times
0.51/1.64/2.90/3.05/3.17 s. The result is non-monotone: group 4 and 16 are dominated by
group 2 in this one run; group 8 has the lowest reported error but costs 5.69x the group-2
build time. This is a one-asset parameter control, not a reference-image quality measure
or a targeted-repair result. It does not advance a novelty claim. Full command, source and
binary hashes, output graph hashes, and limits are recorded in
`TARGET_BUDGET_FRONTIER_PILOT_20261116.md`.

### Additional prior art for on-demand reduction and incremental HLOD (2026-11-16)

The broad “reduce a mesh to a requested face count on demand” formulation is older than
the current project: time-critical multiresolution rendering includes dynamic
simplification to supply a requested triangle count, and progressive meshes support
continuous coarsening/refinement. HLODs for large static and dynamic environments also
select representations under image-quality or frame-rate targets. These are direct
reasons not to present a target face count, dynamic simplification, or runtime budget
selection as new. [Time-critical multiresolution rendering, publisher record](https://www.sciencedirect.com/science/article/pii/S0010448500000683),
[Hoppe, Progressive Meshes](https://hhoppe.com/proj/pm/),
[Erikson et al., HLODs](https://gamma-web.iacs.umd.edu/HLOD/paper/HLOD.pdf).

Recent systems narrow the remaining boundary further. UltraMeshRenderer (ACM TOG
2025) performs GPU out-of-core rendering with LOD selection under memory and coherence
constraints, reuses frame-resident geometry, and incrementally refines over later
frames. The NVIDIA `nv_cluster_lod_builder` reference code constructs a cluster DAG
for continuous LOD, selects clusters by screen-related error, and describes on-demand
streaming. Neither is the same as choosing failed simplification groups to repair under
a fixed *offline construction* budget, but runtime budgeted mesh selection, frame
coherence, continuous cluster LOD, and demand loading are already occupied.
[UltraMeshRenderer, author-hosted paper](https://aiichironakano.github.io/cs653/Zhang-UltraMeshRenderer-ACMTG25.pdf),
[NVIDIA cluster LOD builder](https://github.com/nvpro-samples/nv_cluster_lod_builder).

A 2025 *Proceedings of ISP RAS* paper gives a closer construction precedent than its
abstract alone suggests. It builds HLOD bottom-up, targets geometric error or a requested
vertex/face complexity, recommends selecting between QEM and vertex clustering according
to quality/speed needs, parallelizes independent clusters, removes hidden internal faces,
and regenerates stale clusters after local edits. Its experiments report up to an order of
magnitude build acceleration on civil-construction models. This directly occupies
context-dependent simplification choice, parallel cluster generation, visibility removal,
and incremental HLOD refresh. It does not appear to formulate the same fixed offline
construction-work allocation over rejected alternative regroupings, but that distinction
is only a hypothesis and the current Pirate cut screen shows no gain. The full primary
paper has now been reviewed: [Shutkin et al., full text](https://www.mathnet.ru/php/getFT.phtml?jrnid=tisp&option_lang=rus&paperid=1005&what=fullt),
[journal record](https://www.mathnet.ru/eng/tisp1005),
[publisher abstract](https://journals.rcsi.science/0132-3474/article/view/464759).

The broader “choose a representation under a quality/resource budget and generate it on
demand” premise is also established. Pasman and Jansen's Web3D 2002 framework maintains
hierarchical accuracy curves that encode image accuracy against resource load, combines
them through a scene graph, and lets the application choose the resource/accuracy point
before triggering LOD generation or update. This is not the same mesh-cluster repair
operator, but it rules out claiming target-budget scheduling or a hierarchical quality / cost
trade-off by itself. [Pasman and Jansen, full paper](https://ii.tudelft.nl/~wouter/publications/pasman02a.pdf),
[ACM record](https://doi.org/10.1145/504502.504510).

The surviving distinction is still only a question to test: can a principled policy
choose *which* rejected cluster simplifications to repair under a global offline
construction-time and memory ceiling, and improve legal cut quality on unseen assets
over current construction and blind retry? The target-budget group sweep above does not
answer this. No novelty claim or SIGGRAPH-level contribution is established.

One archived Pirate regroup-diagnostic pool also weakens the local-repair premise. Its
manifest binds a separate Linux executable and source revision; across 48 alternatives
to three local baselines (180, 176, and 1,174 triangles), every alternative consumed
more local faces. None reduced local error without spending extra faces, although some
did trade extra faces for lower local error. This is not a whole-cut oracle and is not
the same executable as the new parameter sweep. It suggests that any useful repair
policy must demonstrate cross-node budget reallocation, not merely rescue an individual
failed parent. The manifest and rows are in `out/regroup-diagnostics-cache-fix/`.

### Expanded projected-support queue audit (2026-11-16)

To avoid another all-zero random cohort, `simulate_projected_support_queue.py` gained an
opt-in `--report-union` sampler. It samples candidate IDs from the union of the six
archived frame reports (268 unique IDs, 256 with nonzero error in at least one stored
frame), then replays 96 IDs over the six archived camera angles for six accepted steps.
This is a priority-sampled development pool, not an unbiased sample or a complete
candidate-generating simplifier. The separate 128-ID uniform sample over three views
had zero image effect for every candidate and is retained as a sampling failure only.

On the informative pool, full rescoring and both cached policies selected the same six
IDs (`1684, 1093, 10133, 5142, 1627, 2081`) and produced the same final filtered error
(`5.62e-11`). Full rescoring used 544 score evaluations / 92.46 s; projected-support
refresh used 205 / 33.72 s; topology-only lazy caching used 96 / 16.21 s. The support
index and invalidation query add about 0.017 s, while each policy also spent about 7.7–7.9
s rerendering the state. A separate audit cost is excluded from those policy timings.
Thus support refresh reduced scoring work by 62.3% relative to the full oracle, but the
topology-only cache reached the identical sequence with less than half its scoring time.
The tiny final error and six accepted edits do not establish a meaningful quality result.
This closes the projected-support line under its present fixed-pool contract; reopening
requires a complete candidate-generating trajectory, a quality-bearing result, and a
native end-to-end advantage over topology-only lazy evaluation. JSON SHA-256:
`2ccc7678dbeab863e17828fa5458ef5f781336f7ca35ec9bf5d67bb1d8ea6f0b`.

### Temporal LOD / TAA prior-art recheck (2026-11-16)

A narrower search for temporal antialiasing, history validation, and changing mesh LOD
returned mature adjacent mechanisms: view-dependent progressive meshes use temporal
coherence and geomorphs; frame-sequential LOD interpolation reprojects and blends prior
color/depth/object-ID buffers; and view-dependent multiresolution methods already use
incremental frame-coherent refinement. FastMesh also directly covers view-dependent
simplification with screen-projection error controls. The [TAA survey](https://doi.org/10.1111/cgf.14018)
identifies history validation as a core TAA component. These sources further narrow the
possible contribution to a specific, measured raster-history validity estimator inside
a live cluster-DAG transition; the search did not establish that estimator as novel.
The renderer capture remains blocked by Windows Application Control, so no result exists
to justify implementation. Do not use another binary or launch route to evade that
policy. Relevant primary sources: [FastMesh](https://www.ifi.uzh.ch/dam/jcr%3Affffffff-82b7-d340-ffff-ffffa65fb649/FastMeshIEEE.pdf),
[parallel view-dependent progressive meshes](https://diglib.eg.org/bitstream/handle/10.2312/EGPGV.EGPGV10.053-062/053-062.pdf),
and [frame-sequential LOD interpolation](https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2008.01255.x).

### Same-budget cut headroom screen (2026-11-16)

The group-8 Pirate cut was also screened with the executable's existing `--oracle-swaps`
and `--oracle-composites` exporter. It produced three single swaps and 64 bounded
composite reallocations, all at 2,756 faces. Reconstructing each whole cut and applying
the same per-node projected sphere-error formula as selection gave a 12.4154 px baseline;
the best exported candidate was 17.6341 px and the composite median was 20.9101 px. Thus
none of these candidates improves the current worst-error proxy, despite choosing
reallocations by a local geometric score. This is a bounded negative screen, not an
exhaustive cut oracle and not a rendered-image measurement. It closes the present
group-8 Pirate repair pool; a broader repair claim survives only if a true offline upper
bound gives a material gain on a quality-valid full-cut metric across assets. Full command,
reconstruction formula, hashes, and limits are recorded in
[`TARGET_BUDGET_ORACLE_SCREEN_CONTROL_20261116.md`](TARGET_BUDGET_ORACLE_SCREEN_CONTROL_20261116.md)
and the analysis can be reproduced with [`analyze_budget_oracle_screen.py`](analyze_budget_oracle_screen.py).

### BinocMesher and RTX Mega Geometry 2.0: trajectory LOD and on-demand cluster LOD are occupied (2026-11-16)

Primary-source review closes two broad directions that could otherwise look open from
ManyMesh's current implementation. BinocMesher (SIGGRAPH Asia 2025) assumes a static
procedural occupancy function and a predefined long camera trajectory. It builds a
4D binary-octree, extracts a 4D dual-contouring mesh, and slices that mesh at timestamps;
its transition parameter trades memory for temporal consistency. This is a strong direct
precedent for trajectory-conditioned, temporally smooth mesh extraction, although it does
not take an arbitrary imported, attribute-bearing triangle mesh as input. That input
distinction is not itself a new algorithm. [Paper](https://arxiv.org/abs/2509.13306),
[author code](https://github.com/princeton-vl/BinocMesher).

NVIDIA RTX Mega Geometry 2.0 is even closer to the project's on-demand use case. Its
official SDK describes an offline-built continuous cluster-LOD hierarchy, per-frame GPU
selection by projected error, streaming of selected clusters into fixed VRAM pools,
and adaptive coarsening when pools run hot. The bake repeatedly decimates groups and
re-forms groups across previous borders; runtime selection and residency are then coupled
to those group records. This directly occupies the general system claim “build clustered
LODs and stream/coarsen them on demand under a memory budget.” The [NVIDIA developer
announcement](https://developer.nvidia.com/blog/whats-new-for-game-developers-dlss-5-with-3d-guided-neural-rendering-nvidia-ace-updates-and-new-rtx-kit-capabilities/),
[SDK overview](https://github.com/NVIDIA-RTX/RTXMG), and [Cluster LOD design and runtime
documentation](https://github.com/NVIDIA-RTX/RTXMG/blob/main/docs/ClusterLOD.md) are primary
sources. The docs describe a ray-tracing-focused reference renderer, fixed geometry/CLAS
pools, delayed residency requests, and group-level error selection. Differences in renderer,
API, or source-asset format do not establish a research contribution by themselves.

Local-code comparison: ManyMesh currently stores one `parent` per node and builds a
single-parent hierarchy; RTXMG explicitly re-forms groups across levels, yielding a DAG.
ManyMesh's generated-vertex sharing, canonical-position cut assembly, and strict quality
gates are implementation details that may matter to correctness, but the current ledger
contains no measured algorithmic advantage from them. They should not be promoted as a
paper contribution without a controlled comparison against this stronger system baseline.

Decision: close “camera-trajectory LOD,” “temporal stability,” “continuous cluster LOD,”
and “on-demand reduction under a fixed geometry-memory budget” as standalone novelty
claims. Do not pivot to ray-tracing versus rasterization as the novelty. The only remaining
hierarchy-repair question is still an unproven, narrow hypothesis: whether a new candidate
generation/selection mechanism can improve a quality-valid complete-cut frontier at equal
total construction work on held-out arbitrary meshes, beyond current construction, blind
retry, and greedy repair. Existing regroup and same-budget screens show no such result.
No SIGGRAPH-level contribution is established.

### Archived regroup diagnostics: rejection histograms are not causal labels (2026-11-16)

A read-only reanalysis of `out/regroup-diagnostics-cache-fix/` does not reveal a repair
mechanism. On Pirate, 114 of 152 production groups were not promoted across levels 4–8.
Across their 419 fallback attempts, the aggregate profile recorded 194 topology-gate hits,
80 geometry-gate hits, 334 attribute-gate hits, 12 locked-gate hits, and no boundary or
“not simplified” hits. These categories overlap: one attempt can fail multiple gates, and
the counters pool retries. They cannot identify which condition caused an individual
collapse or whether changing group membership would fix it. The 48 existing regroup trials
used 29,184 input-triangle work units (3.98 s in that run); none passed the local improvement
screen. This is artifact reanalysis, not a new executable run or causal experiment. It
reinforces the stop condition: no failure-aware candidate policy should be designed around
these counts until candidate-level rejection attribution is available.

Correction / stronger overlap: RTXMG's own Cluster LOD documentation says its implementation
uses a fork of meshoptimizer's `clusterlod.h` to build the LOD DAG, and exposes normal,
texcoord, and material-boundary weights in the simplification objective (defaults 0.5, 0.5,
and 32 respectively). It also quantizes per-cluster UVs for residency savings. Thus “we
preserve UVs/normals/material boundaries in an on-demand cluster hierarchy” is also too
broad as a novelty distinction. This does not establish that the exact ManyMesh quality
gates or cut assembly are identical; it means those exact differences need a matched,
measured advantage before they matter. [NVIDIA Cluster LOD documentation](https://github.com/NVIDIA-RTX/RTXMG/blob/main/docs/ClusterLOD.md).

### 2026-11-16 differentiable image losses do not by themselves reopen the collapse claim

Three primary-source checks further constrain the filter-aware image-simplification direction.

- [EdgeGrad (ECCV 2024)](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11059.pdf)
  computes rasterization loss gradients with respect to triangle vertices, including visibility
  discontinuities, occlusion/disocclusion, and intersecting geometry. It preserves the hard
  rasterized forward image and supports mask, depth, and normal outputs. This closes any broad claim
  that obtaining useful image-loss derivatives at raster visibility edges is itself new. Its
  operation is continuous vertex motion on the current rasterized geometry; it does not provide a
  legal progressive edge-collapse ordering or a finite collapse error certificate.
- [A Theory of Topological Derivatives for Inverse Rendering of Geometry (ICCV 2023)]
  (https://openaccess.thecvf.com/content/ICCV2023/papers/Mehta_A_Theory_of_Topological_Derivatives_for_Inverse_Rendering_of_Geometry_ICCV2023_paper.pdf)
  derives image-functional derivatives for hole/phase nucleation using level sets. This closes a
  broad “image gradients cannot guide topology change” claim, but does not solve fixed-source,
  connected triangle-mesh decimation under edge-collapse, attribute, and geometry gates.
- [DiffSoup (CVPR 2026)]
  (https://openaccess.thecvf.com/content/CVPR2026/papers/Tojo_DiffSoup_Direct_Differentiable_Rasterization_of_Triangle_Soup_for_Extreme_Radiance_CVPR_2026_paper.pdf)
  directly optimizes a small opaque triangle soup from multi-view radiance-field images and changes
  its primitive set during training: it splits long projected edges and prunes triangles with low
  pixel coverage to enforce a target count. That occupies generic image-guided primitive addition,
  removal, and budget control. Its unconnected, textured radiance-field representation is materially
  different from simplification of a supplied mesh while retaining connected topology, UV/normal
  contracts, and reversibility.

Together with [Appearance-Driven Automatic 3D Model Simplification (2021)]
(https://users.aalto.fi/~laines9/publications/hasselgren2021egsr_paper.pdf) and [Image-Driven
Simplification (2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf), these
works rule out the broad contribution “use differentiable / filtered image error to simplify a
mesh.” The remaining testable question is whether a finite *legal connected edge collapse* can be
ranked accurately by shared-render derivative computation plus a conservative correction for
faces that disappear, with lower total cost than exact local rerendering. This is only a possible
algorithmic boundary: the derivative methods are adjacent components, not evidence that this
combination is novel or efficient.

**Kill gate before implementation:** freeze complete legal candidate pools and reference views on
at least two meshes. Compare current QEM/Corner, exact local candidate rerendering, a first-order
EdgeGrad ranking, and a path-integrated derivative with the disappearing-face correction. Measure
full-pool rank correlation, selected collapse's exact filtered RGB/coverage/depth delta, error at
matched actual triangle counts, renderer calls, derivative/prefix cost, and total wall time. Include
occlusion changes, subpixel features, attribute seams, and candidates whose collapsed faces own the
dominant image support. Stop if the path correction needs roughly one render per candidate, if
rankings are unstable to sampling/filter phase, or if the quality/work frontier does not beat exact
local rerendering and established image-driven baselines. No new method or SIGGRAPH contribution is
established by this literature screen.

**Repository readiness:** existing `out/filter-real-candidates/` captures and the optional
`CornerCandidateCapture` API are not the required complete sequential pool. The API records the
current best legal placement per directed edge in the initial state; it does not enumerate all
placements or regenerate candidates after accepted operations. Its new tests are recorded as
syntax-checked only, not executed. Do not run the kill gate against these artifacts and describe it
as a complete candidate or trajectory experiment.

### 2026-11-16 direct on-demand simplification baselines: clusterlod and wild textured meshes

A source-level check of the public MIT [`meshoptimizer/demo/clusterlod.h`](https://github.com/zeux/meshoptimizer/blob/master/demo/clusterlod.h)
narrows the hierarchy-repair claim further. `clodBuild` repeatedly partitions/merges clusters,
targets a per-level simplification ratio, and marks a group terminal when its simplified result
misses the configured threshold. The simplifier can fall back to permissive or sloppy mode after
the regular attempt stalls; the default configuration already enables permissive simplification
and sloppy fallback, and multiplies the reported error for the sloppy result. The implementation
also protects selected attribute discontinuities with vertex lock bits. This is close to the
current ManyMesh retry pattern at the systems level: ManyMesh instead spatially bisects a failed
group up to two levels while reapplying its unchanged strict topology/attribute/geometry gates.
That difference is real, but “retry a stuck cluster,” “use fallback simplification,” or “recover
coarse hierarchy coverage” is not a defensible novelty claim. Any surviving claim must show a
material improvement in the complete quality-valid cut frontier at equal total build work, and
must use `clusterlod`/RTXMG-class systems as explicit baselines where their contracts can be
matched. The public code is an algorithmic baseline, not an assertion that its permissive modes
are equivalent to ManyMesh's gates.

The direct simplification baseline is also stronger than the earlier generic appearance-driven
comparison. [Simplifying Textured Triangle Meshes in the Wild (SIGGRAPH Asia 2025 / TOG 2025)]
(https://doi.org/10.1145/3763277) handles non-manifold, disconnected textured triangle meshes,
accepts target face counts, and tracks collapse history to transfer source appearance through
successive local projections. It combines physical and virtual edges with an area-aware quadric;
its paper reports arbitrary-mesh datasets and user studies. The authors' [paper PDF]
(https://www.dgp.toronto.edu/~hsuehtil/pdf/wild_mesh_paper_compressed.pdf) explicitly notes that
the mapping may sample interior rather than outermost layers and identifies visibility-aware
mapping as future work. An independent [public glTF implementation]
(https://github.com/illusioneering/textured-mesh-simplification) exposes target-face CLI operation
and bakes standard PBR slots. These sources occupy broad on-demand simplification of wild textured
assets and collapse-history texture transfer. Their use of a rebaked atlas/single simplified
result differs from ManyMesh's authored-attribute contract and hierarchical mixed cuts; those are
comparison constraints, not novelty evidence.

**Decision update:** close “on-demand target-face simplification of arbitrary textured meshes,”
“generic stuck-group retry,” and “collapse-history texture mapping” as contribution claims. Keep
the hierarchy line only as a falsifiable constrained-frontier question: under ManyMesh's fixed
strict gates, can a new repair policy improve quality-valid complete cuts at matched build time
over current partition retry and the strongest reproducible cluster-LOD fallback? The current
single-asset proxy screen is negative and insufficient. Before implementing a new selector, first
establish a matched baseline protocol and determine whether the required gates can even be
represented by a clusterlod/RTXMG baseline without weakening them. No new algorithm or
SIGGRAPH-level result is established.

Repository-pinned baseline detail: this checkout vendors meshoptimizer v0.18
(`third_party/meshoptimizer/src/meshoptimizer.h`), not the current upstream `clusterlod.h`.
Its [README](https://github.com/zeux/meshoptimizer/blob/v0.18/README.md#mesh-simplification)
says topology-preserving `meshopt_simplify` can get stuck on inconsistent topology or many seams;
the suggested shadow-index preprocessing discards attributes that can be rebuilt.
`meshopt_simplifySloppy` can continue across topologically disconnected features, but does not
preserve seams or borders. This makes ManyMesh's same-gate spatial retry a meaningful fixed-contract
failure mode, but not a novelty claim by itself. A numerical comparison requires pinning an
upstream clusterlod revision in a separate experimental build and validating every output against
the same ManyMesh gates; the default output contracts are not directly equivalent.

### Prior art correction: failed cluster merges already trigger split-and-reinsert

The HPG 2023 paper [Real-Time Ray Tracing of Micro-Poly Geometry with Hierarchical Level of Detail]
(https://doi.org/10.1111/cgf.14868) explicitly describes the closest missing precedent. When a
cluster merge cannot simplify enough (often because boundary edges dominate), it cuts the merged
cluster approximately in half while minimizing newly introduced boundary edges, creates two new
clusters that both retain the original input clusters as children, and puts both back into the
merge process. The result is a multi-parent binary DAG, and the paper reports that DAG2 reduces
the number of roots by up to 2x. Its authors identify this as the same general split response used
by Nanite, with different heuristics and stricter topology preservation. This directly closes
“split a failed simplification group to improve upper-level hierarchy coverage” as a standalone
idea.

The implementation gap is narrower than the prior-art gap: ManyMesh currently spatially bisects
the *child-member set* before a retry, assigns each member to at most one accepted parent
(`LodGraphNode::parent` is a single id), and reapplies the strict topology/geometry/attribute
gates. Benthin and Peters instead split the already merged cluster geometry into two alternative
parent patches, each with the same original children, requiring a multi-parent DAG and crack-free
cut rules. This is not an innovation claim. A defensible extension would need to establish a
specific new mechanism required by ManyMesh's strict attribute/quality gates and demonstrate a
better complete-cut quality/cost frontier than DAG2/Nanite-style split-and-reinsert, ASAP HLOD
boundaries, and current cluster LOD systems. No such result exists in this checkout.

#### HPG implementation trigger audit

The paper-level description says to split after a merge fails, but its public Embree HPG 2023
implementation at pinned commit [`fa6c1e22`](https://github.com/RenderKit/embree/tree/fa6c1e22e089d7c9b805db9165fc95f98b39f08d)
reveals a narrower trigger. `mergeSimplifyQuadMeshClusterDAG` uses
`meshopt_SimplifyLockBorder`, targets 50% triangles, relaxes the target and error until the result
is at most 80% of input, and returns failure if it cannot reach that reduction. It calls
`QuadMeshCluster::split` only after simplification succeeds but the resulting cluster exceeds the
128-quad or 256-vertex storage limit; `split` reorders with PLOC and halves the ordered quads.
See the exact [simplify/reduction code](https://github.com/RenderKit/embree/blob/fa6c1e22e089d7c9b805db9165fc95f98b39f08d/tutorials/micropoly/cluster_processing.cpp#L3168-L3280)
and [compression-triggered split](https://github.com/RenderKit/embree/blob/fa6c1e22e089d7c9b805db9165fc95f98b39f08d/tutorials/micropoly/cluster_processing.cpp#L3329-L3374).
Therefore the reproducible code baseline directly covers split-and-reinsert for cluster-cap
overflow, while the ManyMesh retry is triggered by failure of its strict topology/geometry/
attribute validation. The paper still establishes the broad DAG2 construction idea and boundary-
driven cluster splitting; the source distinction only narrows the exact trigger. It does not by
itself make “split after a ManyMesh quality-gate failure” novel.

The only plausible comparison now is a **strict-contract experiment**: apply a shared-children
DAG2 variant to groups rejected by ManyMesh's exact gates, retain both output patches only if they
pass the same gate and assemble to the same crack-free source region, then measure whole-cut
quality/reachability at equal total build work against (i) current single-parent spatial retry,
(ii) the published HPG split policy on its native storage constraints, and (iii) modern
clusterlod/RTXMG. This requires a multi-parent graph and cut-validity work absent from the current
single-parent `LodGraph`; it is not a small scoring change. Do not begin core implementation until
the benchmark defines an actually comparable contract and predicts enough reachable-cut headroom
to justify changing the graph representation.

### 2026-11-16 single-parent headroom preflight

Read-only analysis of the frozen Pirate group-8 artifact found 184 nodes, 29 roots, 75 leaves,
and 44 nodes in the 55% cut. Every one of the 184 nodes has exactly one parent; there is no
existing shared-child DAG2 alternative to mine from this graph. The selected-cut worst projected
error is concentrated at node 183 (level 8, 130 triangles, 12.4154 px), while the next selected
node is 11.7434 px. This confirms the tree representation and hotspot, but it does not predict
whether an alternate parent patch can pass ManyMesh's strict gates.

The existing 67 equal-face oracle exports are all reconfigurations of the current tree: 3 single
swaps and 64 bounded composites. Their best whole-cut proxy is 17.6341 px versus 12.4154 px for
the baseline. Thus the present candidate pool has negative headroom for this proxy, but it is not
a DAG2 feasibility test: `LodGraphNode` serializes one `parent`, and the cut reconstructor follows
that single-parent ancestry. A valid DAG2 test must first express overlapping child sets and prove
that each complete cut covers the source region exactly once without cracks, then rerun the strict
topology/geometry/attribute gates on both alternative patches. The existing tree oracle cannot
answer that question, so no DAG2 implementation or novelty claim is justified by these artifacts.

#### Exact optimum over the saved tree

An offline enumeration now removes the remaining uncertainty about ordinary cut choice. It scans
all 99 distinct node-error thresholds in the frozen group-8 graph. At each threshold, descending
only when a node exceeds the threshold is the minimum-triangle legal cut: the artifact validates a
single-parent forest and every parent has fewer triangles than its direct children combined. The
smallest threshold fitting 2,756 triangles is 12.4153843 px, and its 44 selected nodes exactly
match the stored selector output. Thus the current selector is already minimax-optimal for its
projected-sphere-error proxy over every cut of this tree. No equal-budget rearrangement of the same
tree can improve that objective. This says nothing about image error, other assets, or adding new
multi-parent patch candidates; that richer hierarchy still needs its own cut-validity and quality
experiment. Reproduction and source hashes are recorded in
[`TARGET_BUDGET_ORACLE_SCREEN_CONTROL_20261116.md`](TARGET_BUDGET_ORACLE_SCREEN_CONTROL_20261116.md)
and `out/target-budget-oracle-20261116/pirate-g8/tree_cut_optimum.json`.

### 2026-11-16 cross-asset controls and literature boundary

Three randomized/interleaved repetitions were completed for each of five `--dag-group`
settings on Pirate and Monkey. Within every asset/group, the three graph-file hashes match
each other, and the graph JSON matches the earlier visibility-sweep graph after normalizing
only the source path. Triangle count and the binary's screen-error value are stable. The
median DAG build ranges from 0.49 to 3.15 s for Pirate and 1.18 to 6.92 s for Monkey.

The 16-view geometry-only coverage/depth result is asset-dependent. Pirate group 2 is both
the fastest and lowest-SSE choice (0.49 s, 50.4305). Monkey group 2 is fastest but worst in
SSE (1.18 s, 5.7659); group 8 has the best SSE (2.8048) at 5.52 s. Group 32 is dominated
by group 8 on the two measured Monkey axes. Thus a single fixed group size does not win on
both examples, and the current single-camera sphere-error proxy fails to rank the Monkey
cuts the same way as the multi-view raster proxy. This is a two-asset diagnostic, not a
perceptual benchmark, generalization result, or algorithm contribution. Reproducible raw
data and hashes are in `out/targetbudget-repeat-control-20261116/build_repeats.json` and
`out/targetbudget-repeat-control-20261116/summary.json`; the synthesized report is
`TARGET_BUDGET_MULTI_ASSET_20261116.md`.

The closer prior-art boundary is now explicit. Ladeuil et al.'s 2026 Computer Graphics
Forum paper, [Construction of clustered HLOD with As-Simplified-As-Possible boundaries]
(https://doi.org/10.1111/cgf.70380), uses progressive internal meshes plus per-neighbor
progressive boundary portions to simplify cluster boundaries while keeping view-dependent
neighboring clusters crack-free. Therefore “free boundary simplification under crack-free
LOD” is not an open contribution. The primary abstract says this is intended to improve
quality/simplification and reduce popping. See the [publisher record]
(https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380?af=R).

Resource allocation is also established at adjacent levels. The 2026 paper [Efficient
Four-Level LOD Simplification for Single- and Multi-Mesh 3D Scenes]
(https://www.mdpi.com/2220-9964/15/2/61) constructs cumulative collapse-loss curves and
allocates per-model simplification rates to satisfy an aggregate scene reduction. That
does not by itself establish allocation of *hierarchy-construction work* among strict-gate
repair candidates, but it blocks a broad claim that heterogeneous LOD budgets across
assets/scenes are new.

RTX Mega Geometry is a relevant public systems baseline, not an equivalent gate-matched
simplifier. NVIDIA's [Cluster LOD docs]
(https://github.com/NVIDIA-RTX/RTXMG/blob/main/docs/ClusterLOD.md) describe bake-time
cluster/group sizes, simplification weights, error metric, node width, streaming and LOD
selection controls; its [quick start]
(https://github.com/NVIDIA-RTX/RTXMG/blob/main/docs/QuickStart.md) records bake time,
worker count and peak RAM. Its output is designed for streamed ray-tracing cluster LOD,
so a head-to-head result requires a declared common geometry/attribute validity contract.

**Current research decision:** no SIGGRAPH-ready innovation has been demonstrated. The
remaining candidate is much narrower than perceptual LOD or adaptive mesh simplification:
schedule extra candidate-generation work for regions only when it expands the full
quality-valid cut frontier at equal measured wall-clock and memory cost. First compute the
exact best schedule over the finite tested configuration grid and compare a simple
marginal-gain-per-second policy against it on held-out, diverse assets. Then compare with
HLOD ASAP, DAG2, and a current cluster-LOD implementation under a normalized validity
contract. If the finite-grid oracle has little headroom over fixed configurations, stop this
branch. Even an empirical win would require a wider literature/patent/implementation audit
before stating “no one has done this.”

The official [SIGGRAPH 2027 Technical Papers schedule]
(https://s2027.siggraph.org/program/technical-papers/) currently lists submissions-form /
conflicts for 21 January 2027 22:00 UTC, paper deadline 28 January 2027 22:00 UTC, and
upload deadline 29 January 2027 22:00 UTC; technical-paper submission details are still
coming soon. As of 16 November 2026 this leaves only about ten weeks to the paper deadline.
That schedule makes the first decisive experiment urgent: either the finite-configuration
oracle reveals a substantial strict-gate frontier gap quickly, or this hierarchy-repair
candidate should not be rushed into a novelty claim for SIGGRAPH 2027.

### 2026-11-16 expanded fixed-budget control

The follow-up used five more repository meshes (`camera`, `cloth`, `material_sphere`,
`rounded_cube`, `shapes`) and repeated all five group sizes three times: 75 additional
builds, bringing the two current controls to 105 measured runs. Graph and selected-cut
hashes were stable within all 15 held-out asset/group combinations. Multi-view raster
audits were restricted to exact equal-triangle cuts, giving five quality-audited assets
overall (Pirate, Monkey, Cloth, Material Sphere, Shapes). The small Camera and Rounded Cube
cuts were not image-ranked because their selected triangle counts changed substantially
across groups; Shapes g4 was excluded because it alone differed by one triangle.

Within those five exact-budget examples, the fastest g2 choice is also the lowest-raster-SSE
choice for Pirate and Cloth. The quality minima differ on Monkey (g8), Material Sphere
(g32), and Shapes (g16); relative to fastest g2, the best measured settings reduce the
proxy SSE by 51.4%, 39.3%, and 96.9%, at 4.68x, 2.64x, and 3.28x the build time. These are
finite five-setting results under an uncalibrated geometry-only CPU proxy. There is no
cross-asset aggregate perception measure and no held-out user/perceptual validation.

The rank reversal is a stronger warning about the chosen quality proxy: the binary's
single-camera projected-sphere minimum is g8 for Pirate, g2 for Monkey, g2 for Material
Sphere, and g2 for Shapes, whereas their raster minima are g2, g8, g32, and g16. Thus the
current screen proxy should not drive an adaptive construction policy without a better
validation criterion. It remains a diagnostic mismatch, not a new metric contribution.

Full tables and limitations are in
[`TARGET_BUDGET_HELDOUT_FRONTIER_20261116.md`](TARGET_BUDGET_HELDOUT_FRONTIER_20261116.md);
the 75-run records, exact-budget audit manifest, and hash-bound aggregate are under
`out/targetbudget-heldout-20261116/`. The finite-grid resource oracle and its result are
added below.

### 2026-11-16 time-and-memory oracle closes the per-asset scheduler gate

An exact enumeration of 2,500 schedules combines the five exact-budget assets' filtered
16-view SSE, median serial build time, peak resident working set, and peak process commit.
Memory measurements were hash-matched to each repeated graph, but each setting has only one
memory sample. Under resource caps defined by uniform g2, g8, g16, and g32 schedules, a
one-asset marginal-gain-per-second greedy starting at the cap-defining uniform schedule
matches the exact oracle schedule at all four caps. The oracle improves over the best
feasible fixed group by 0%, 8.1%, 3.9%, and 38.6%, respectively. The g32 result is a
memory-constrained comparison in which only fixed g32 remains feasible; it should not be
read as a general quality gain from group size 32.

This closes the current finite-grid gate: heterogeneous asset settings can help this small
sample, but neither the optimizer nor its scheduling policy is a research contribution.
Scene-level, model-specific simplification-rate allocation already appears in the 2026
four-level LOD paper, so the broad allocation framing is prior art as well. See the
[paper's method and abstract](https://www.mdpi.com/2220-9964/15/2/61) and the reproducible
[time-memory oracle report](TARGET_BUDGET_RESOURCE_ORACLE_20261116.md). Do not implement a
new per-asset scheduler on this evidence.

The only remaining candidate is now narrower: construct additional **within-mesh** parent
patch alternatives only when they expand the complete strict-gate-valid cut frontier under
an equal construction-work and memory budget. That formulation is not cleared as novel:
DAG2 already has shared-child multi-parent hierarchies, HLOD ASAP simplifies boundaries
while preserving crack-free transitions, and NVIDIA RTX Mega Geometry publicly documents
on-demand streamed cluster LOD with adaptive memory/quality control. The proposed
experiment must first implement a common validity contract and show measurable reachable
cut-frontier improvement against the current single-parent retry, DAG2-style split/reinsert,
HLOD ASAP, and a current cluster LOD implementation. Current artifacts do not demonstrate
this improvement, and no SIGGRAPH-readiness or novelty claim is warranted.

The [official SIGGRAPH 2027 Technical Papers schedule](https://s2027.siggraph.org/program/technical-papers/)
lists the paper deadline as 28 January 2027, 22:00 UTC. As of 16 November 2026, 73 days
remain; submission details are still listed as forthcoming. The remaining candidate needs a
fast falsification experiment before any large C++ implementation effort.

### 2026-11-16 raster boundary derivative recheck

The original [Image-Driven Simplification paper](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)
directly prices edge collapses by comparing rendered images of the original and simplified
model. Its abstract explicitly frames the method as edge-collapse simplification and uses image
differences to jointly account for geometry, normals, colors, and textures. This is the direct
baseline for any claim that an image-space objective changes mesh simplification decisions.

[EdgeGrad (ECCV 2024)](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11059.pdf)
constructs micro-edges to approximate rasterization gradients at visibility discontinuities,
including coverage, depth and normal outputs, while preserving the hard rasterized forward
image. It is a differentiable rendering method, not a decimator, but it blocks a broad claim that
handling raster boundary discontinuities with an edge-local derivative is itself new.

[Quadric-Based Silhouette Sampling for Differentiable Rendering (SIGGRAPH 2025)]
(https://mariasoroka.github.io/papers/Data/EdgeSamplingPaper/EdgeSampling1July2025.pdf)
uses dual-space bounds and dual quadrics to improve silhouette-edge sampling for shape derivatives
in path tracing. It does not rank mesh collapses or minimize filtered raster SSE; it is adjacent
prior art for data structures and estimators centered on silhouette derivatives.

Together these works further narrow the filter-aware line. The one-dimensional Gaussian boundary
loss and the exact sparse filter energy are not sufficient as contributions; the former is a
closed-form filtered step comparison, and the latter is standard quadratic filter algebra. The
only defensible experiment left is a cost-quality claim for discrete legal collapse sequences:
on real meshes and under the same candidate pool, does an analytic filtered-boundary predictor
preserve the output quality of exact local redraw while lowering total scoring and update cost?
Current evidence says no speed advantage after full row coupling, the discrete Gram scorer is
slower than sparse splatting, and the frozen Torus pool's independent and interaction-aware
selectors choose the same output from 2 through 12 collapses.
The dynamic strip executable has not run, and the real Corner capture is neither a complete
placement pool nor a regenerated sequence. This branch therefore remains pre-gate; do not call
it a SIGGRAPH contribution or spend core implementation effort until that falsification test has
a viable protocol and a predicted cost margin.

### 2026-11-16 multi-collapse interaction screen

To check whether the earlier two-collapse null result was only a tiny-budget artifact, the exact
same Torus candidate export was extended across six orthographic views. Each view has 48 frozen
initial-state legal geometry candidates; each removes two triangles. The independent finite-pool
oracle minimizes summed single-collapse filtered SSE, while the joint oracle adds all pairwise
filtered-residual cross terms. The k=2 and k=4 selectors are exhaustive over vertex-disjoint sets;
k=8 and k=12 use deterministic greedy prefixes. Every selected set was composed and fully
rerasterized.

At all four budgets the two selectors pick the same set in all six views, with 0% actual filtered
SSE difference. The largest absolute discrepancy between pairwise prediction and full composite
redraw is 2.8e-17. All 12 outputs per budget pass the checked torus topology invariants. The largest
tested budget removes 24/1,152 triangles (2.08%), still too small to support a substantial
reduction claim. Thus pairwise screen-space interaction did not change a selected output for this
asset and frozen pool, even when the budget grows to twelve collapses.

This does not close regenerated candidate sequences, other meshes, authored attributes, or larger
reductions; the current capture only records initial-state best placements. It does close the
planned multi-operation screen for the current Torus pool. The next decisive experiment must
regenerate legal candidates after each accepted operation and compare against exact local redraw
at a meaningful reduction. If the full scoring/update cost does not improve, stop this branch.
Reproducible inputs, topology checks, timing and hashes are in
[`MULTI_COLLAPSE_INTERACTION_AUDIT_20261116.md`](MULTI_COLLAPSE_INTERACTION_AUDIT_20261116.md)
and `out/multi-collapse-interactions-20261116/torus.json`.

### 2026-11-16 regenerated-candidate image-error screen

To test the frozen-pool caveat, a local capture utility was run again on the OBJ after each
accepted Torus collapse. A 32-candidate visible-only initial sample was compared with a policy that
recaptured and resampled 32 current candidates per step. Both make eight topology-valid collapses
and remove 16/1,152 faces. At 96² with 2x supersampling, the dynamic output has 99.885% lower
fitted-view filtered coverage/depth SSE; a 13-view final audit at 128²/3x has 99.082% lower summed
SSE. However, the fixed sampled queue falls from 32 to 11 compatible choices, the dynamic policy
uses about 1.96x total selection/redraw time, and the reduction is only 1.39%. This shows that a
small frozen sample is a weak long-sequence control; it is not a matched comparison to a complete
production queue.

An initial hidden-candidate run was rejected as evidence: all eight selected edits had zero visible
affected triangles and therefore zero fitted-view error, exactly the established view-dependent
behavior. [Lindstrom and Turk, *Image-Driven Simplification* (TOG 2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)
already compares current and original images to greedily rank successive edge collapses, updates
only local image regions, discusses arbitrary projected interactions and lazy candidate reevaluation,
and demonstrates aggressive simplification of hidden surfaces. The present dynamic-recapture result
does not create a distinct mechanism beyond that formulation.

**Decision:** close dynamic recapture plus filtered image error as a standalone claim. Existing
projected-support queue replays also match the exact full-rescore sequence on their finite samples,
while doing more score work than topology-lazy refresh and showing no observed quality gain. The
overall SIGGRAPH contribution remains unmet; the next direction must begin with a distinct, falsifiable
mechanism and a total-work comparison against the image-driven and production baselines. Full results
and reproduction details are in
[`DYNAMIC_RECAPTURE_AUDIT_20261116.md`](DYNAMIC_RECAPTURE_AUDIT_20261116.md).

The complete-pool and matched edge-frontier follow-up strengthens that decision. Recapturing all
current placements lowered Torus fitted-view SSE by 99.503% against a frozen initial pool, but its
13-view SSE was 11.82x higher; that pool comparison also restricted overlapping frozen operations.
In the matched ablation, both policies recaptured placements and allowed adjacent collapses. New
edges lowered fitted-view SSE by 92.611% at nearly equal work, but raised 13-view SSE by 65.68x.
The result is a one-view overfit at 1.39% reduction, not a contribution. See
[`DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md`](DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md)
and its machine-readable reports.

### 2026-11-16 corner-domain attribute handling is not a broad novelty claim

The current `CornerSimplifier` carries UV/normal/AO data per triangle corner, interpolates each
corner through a collapse, and can split generated render vertices when UV values diverge. That
is a useful implementation contract for authored meshes, but “per-corner attributes let a mesh
collapse across attribute seams” is already close to established representations. Hoppe's *New
Quadric Metric for Simplifying Meshes with Appearance Attributes* (1999) uses wedge-based mesh
data: one geometric vertex has multiple attribute vectors assigned to face corners, and compatible
wedges are unified during edge collapse. [*Seamless* (SIGGRAPH Asia 2017)](https://cragl.cs.gmu.edu/seamless/)
formulates seam-preserving collapse conditions and seam-aware simplification, under its seam-free
signal assumptions. Zhang et al. (2022) decouple geometry, UV parameterization and texture, then
regenerate a texture to prevent chart artifacts. Liu et al. (TOG 2025) instead transfer texture
appearance for arbitrary textured meshes through successive source/output surface mapping.

The narrow implementation difference still worth checking is the combination of exact authored
UV/material delivery, hard local normal/UV/AO gates, and collapse through arbitrary discontinuous
corners without atlas rebaking. That contract difference alone is not a contribution. Before any
paper claim, compare a faithful wedge-QEM control, a seam-constrained control, and the current
Corner path at matched triangle budgets on held-out authored PBR assets. Measure rendered color,
normal-map response, seam bleed, attribute validity, topology, and total build work. If the result
only says the current per-corner representation stores wedges conveniently, stop; the algorithmic
distinction is not yet established.

Primary sources: [Hoppe 1999 author page and PDF](https://hhoppe.com/proj/newqem/),
[*Seamless* SIGGRAPH Asia 2017](https://cragl.cs.gmu.edu/seamless/),
[Zhang et al. 2022](https://www.sciencedirect.com/science/article/pii/S0097849322000930),
[Liu et al. TOG 2025](https://www.cemyuksel.com/research/papers/simplifying_meshes_in_the_wild.pdf).
This is the next comparator gate, not an accepted novelty hypothesis.

### Follow-up: tangent-frame normal-map scoring is also established

The remaining fixed-UV/no-rebake PBR question was narrowed to tangent-space normal maps. That
does identify a validation gap in `CornerSimplifier`: it carries corner UVs and shading normals,
but not the tangent frame consumed by a normal map. It does not establish novelty. Cohen et al.
(SIGGRAPH 1998) bound surface-mapping distortion affecting texture and normal-map lighting;
Williams et al. (SI3D 2003) simplify lit textured meshes under dynamic diffuse/specular lighting
with per-pixel normal-map support; Hasselgren et al. (TOG 2021) jointly optimize shape and tangent-
space normal maps, derive/update tangent frames from positions and UVs, and demonstrate PBR examples.
The latter is a direct precedent for considering frame changes in appearance-driven simplification.

Therefore close “add a tangent-frame angular penalty or hard gate while keeping an authored normal
map fixed” as a standalone contribution. Reopening would require a distinct certified image-error
bound or a cheaper dynamic update that beats image-driven simplification and faithful rebaking at
matched quality and total cost. The workspace has no held-out authored PBR asset set, and no such
mechanism has been implemented or measured. *Simplifying Textured Triangle Meshes in the Wild*
(TOG 2025) is adjacent texture-transfer prior art, not evidence of normal-map-specific handling.
See [the audit](TANGENT_FRAME_PBR_NOVELTY_AUDIT_20261116.md) for source-by-source scope and the
repository call-path inspection.

### Follow-up: ReSTIR reuse-aware LOD construction is a hypothesis, not a claim

The next narrow question is whether a progressive simplifier can select collapses to preserve the
statistical usefulness of cross-LOD ReSTIR path transport: valid mapped-path support, the exact
reuse-weight distribution / effective sample size, and ultimately independent-run estimator variance
and temporal covariance at fixed triangle and geometry-error budgets. This is not the same claim as
preserving UVs, adding a normal penalty, optimizing rendered image error, or implementing per-ray LOD.

The prior-art boundary is already crowded. SIGGRAPH 2026 ReSTIR-LoD supplies the UV-based partial
bijection and area Jacobian and reports quality loss from distorted or degenerate UVs. Progressive
Meshes preserve collapse correspondences; appearance-driven simplification optimizes rendered images;
illumination-driven mesh reduction uses light-transport importance; ReSTIR MCMC mutation and HPG 2026
compatibility-guided neighbor selection directly target reuse quality/correlation at runtime. A
targeted search did not find collapse order optimized for the cross-LOD reservoir-weight objective,
but this is only an unverified literature gap. The coupling must outperform the strongest runtime
reuse controls and direct simplification baselines on held-out scenes at equal total cost.

Repository feasibility is mixed: the formal mmgeo chain OBJ export does preserve UVs, although some
older candidate-capture OBJ files discard them. A four-asset UV-area preflight found full sampled
support and pointwise nearest-map round trips for all nine tested LOD transitions, including a highly
overlapping Cloth atlas. Thus “repair UV map support” is not a promising standalone mechanism on this
population; the remaining hypothesis is path-weight efficiency, which this preflight cannot test.
The exposed LOD graph is not a persistent surface map, but ReSTIR-LoD reconstructs its map from common
UVs. A public ReSTIR-LoD implementation on Falcor 8.0 includes headless Python render drivers, so it
could provide the baseline without a new renderer port; its README says its Chessboard scene must be
downloaded separately. This machine exposes only Intel Iris Xe and no Vulkan ray-tracing pipeline,
acceleration-structure, or ray-query extensions, so no local GPU ReSTIR variance test is available.
Do not change production simplification from this hypothesis alone. See
[`RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md`](RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md)
for the proposed weight/ESS measures, holdout protocol, required baselines, and explicit kill gate;
the map-support pilot is recorded in
[`RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md`](RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md).
SIGGRAPH 2027 currently lists a 2027-01-28 22:00 GMT paper deadline; 2027-01-21 is the submissions
form/conflicts deadline, and 2027-01-29 is the upload deadline. The earlier Jan 21 paper-deadline
statement was incorrect. No renderer experiment or novelty result has been established.
