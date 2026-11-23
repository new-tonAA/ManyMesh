# Contour-aware triangle budgeting after antialiasing

Updated 2026-11-23. **Status: research-only selector built and screened for budget feasibility; screen failed.** `tools/mmgeo` has optional contour-risk cut export flags, kept out of the renderer and public ManyMesh API. Across 12 repository OBJ fixtures and requested ratios 0.3/0.5/0.7, it produced zero equal-face, geometry-distinct candidates. Every exact face match exported the same geometry as the uniform cut. No image-quality comparison or selector-only timing was run. See the [screen report](tools/mmgeo/CONTOUR_SELECTOR_BUDGET_SCREEN_20261123.md) and [raw JSON](tools/mmgeo/contour_budget_screen_20261123.json).

## Research question

At equal geometry budget, does spending refinements on regions predicted to retain image error after antialiasing improve rendered quality over a uniform screen-error cut with the same AA? The candidate is a cheap normal-cone heuristic, not yet a perceptual model:

1. For each visible DAG node, let `a` be its world-space normal-cone axis and let `theta = acos(clamp(cutoff, -1, 1))` be its half-angle. Let `v` point from the node bounds center toward the camera. Set `thetaEff = min(theta + margin, pi/2)` and mark the node contour-prone when `abs(dot(a, v)) <= sin(thetaEff)`. The margin covers view-direction spread and numerical conservatism. This is a conservative orientation test, not visibility or a screen-space error estimate.
2. Use a shared threshold scale `s`. A first development parameterization is `Tcontour = s` and `Tinterior = k*s`, with `k` in `{3, 4, 5}`. A node refines when its projected geometric error exceeds its applicable threshold. Binary-search `s` to meet a fixed face budget; if the discrete DAG cannot hit the budget, report actual faces and compare only within a predeclared tolerance. Tune `k` and `margin` on training/validation assets, then freeze them.
3. Hold 4× MSAA, camera, shading, resolution and source-reference render fixed across the uniform and candidate cuts. The test is whether the contour-aware cut improves quality at the same face count while including selector cost. Do not use the reference image to make runtime choices.

The cone rule indicates *where a silhouette could occur*. It cannot tell whether a contour is visible, whether an occluder hides it, whether the AA pipeline has already removed the error, or whether a nearby material/depth boundary is important. It can also over-select highly curved or broad cones. A later learned per-cluster predictor is deferred; if tested, it must predict measured filtered-error reduction per added triangle using training data only and pass the identical held-out gate.

### Cone correctness audit

The former parent-cone merge averaged axes and retained the smaller child cutoff, which is not generally a conservative enclosing cone. The current branch replaces that merge with `mergeNormalCones` in `Clusterizer.cpp` and adds adversarial unit coverage in `test_manymesh.cpp`. The changed C++ translation units and `test_manymesh` Debug target compiled with MSVC, but Windows Application Control blocked launching the test binary. This is therefore an implemented fix with runtime verification still outstanding, not a validated property of the full generated DAG. The helper's angular cap does not by itself prove that the cone apex encloses child spatial extents. Any future selector still needs descendant-normal audits on real hierarchy outputs and must treat invalid/uncertain cones conservatively.

The `mmgeo` prototype uses each node's cone axis/cutoff and camera direction, with invalid cones treated as contour-prone. It selects a hierarchy cut by a weighted screen-error threshold and binary-searches the scale to approach the uniform selector's actual face count. On the 12-fixture, three-budget screen, every exact-face match was byte-identical to the uniform output; at 0.7, two assets produced multiplier-dependent geometry, but neither yielded an exact-face alternative. This implementation therefore stops before image scoring. The normal cones and duplicated frustum math still need correctness audits on generated graphs.

## What is already known

- Historical Monkey results motivate looking at silhouettes but are not a general law: the 68.3% squared-error share came from 0.11% coverage-mismatch pixels against an 11,250-triangle DAG cut, not the 15,744-triangle source.
- Across 13 reused Khronos assets, a silhouette-XOR profile selected the existing area ranker on all 13 leave-one-asset-out folds. This is a negative result for that asset-level profile, not for this node-level cone heuristic. [Report](tools/mmtrain/DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md)
- A perfect two-pixel silhouette-band copy from the full reference removed 71.0% of squared error on average. This is a zero-cost upper bound with oracle access to reference pixels, not an implementable correction. [Protocol and results](tools/mmtrain/GPU_SMAA_SILHOUETTE_BAND_SCREEN_20261122.md)
- The two rendered silhouette-guide prototypes did not beat all eligible controls on all three of LDR-FLIP, PSNR and SSIM on any of the 13 development assets. [Report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)

These data support a targeted experiment; they do not show that it will beat MSAA or SMAA.

The node-level contour-risk implementation has now had a separate 12-fixture, three-budget screen. It did not produce an equal-face, geometry-distinct pair for quality scoring and is closed as a candidate under the current implementation. This does not test the differentiable DAG hypothesis. See the [budget screen](tools/mmgeo/CONTOUR_SELECTOR_BUDGET_SCREEN_20261123.md).

## Prior art and novelty boundary

The proposed combination is directly anticipated by Luebke and Erikson's [view-dependent simplification (SIGGRAPH 1997)](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf): their method uses a conservative normal cone to classify potential silhouettes, applies a tighter screen-space threshold near silhouettes than in interior regions, and includes a triangle-budget criterion. Hoppe's [view-dependent refinement of progressive meshes (SIGGRAPH 1997)](https://doi.org/10.1145/258734.258843) is also directly relevant. Therefore close the proposed normal-cone + looser-interior-threshold + fixed-triangle-budget selector as a novelty candidate. Its node-level implementation has not been evaluated in this repository, but that does not revive its novelty. The 2026 clustered-HLOD paper remains adjacent construction work; no detailed comparison is claimed until its full text is read.

The [2026 clustered HLOD boundary paper](https://doi.org/10.1111/cgf.70380) builds a binary cluster hierarchy of progressive meshes with separate internal and neighbor-matched boundary portions. Its target is to simplify cluster boundaries at each level while keeping neighboring LODs crack-free, reducing boundary over-preservation and popping. It addresses hierarchy construction and boundary representation, not an AA-aware runtime triangle allocator. This is direct neighboring work that any future cluster-hierarchy claim must cite and distinguish. The publisher's abstract and preview were available during this review, but its full text was not; read the full paper before making a detailed novelty claim.

Mobile Nanite is also an engineering precedent. Arm reports a **modified Unreal Engine 5.5.2 desktop renderer**, using Vulkan Shader Model 5 on a Vivo X200 Pro with Mali-G925 Immortalis MC12. Its June 2026 Mori demo article reports about 15.75 FPS initially and about 27 FPS after disabling world-position-offset animation. This rules out “Nanite-like geometry on phones” as a novelty claim; it does not establish stock Unreal mobile-renderer support or a general mobile performance result. [Arm article](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/mori-to-nanite-billions-of-triangles-on-mobile)

The possible distinction is limited to a measurable interaction among (a) AA-filtered image-error benefit, (b) cluster-DAG refinement decisions and (c) a target-device cost model. It is not established that this interaction is new or useful. A literature review must also cover image-driven simplification, silhouette clipping, perceptual mesh metrics, foveated/visibility-aware LOD, and current cluster-LOD methods before a contribution claim.

## Frozen development experiment

### Arms

1. Uniform screen-error cut with 4× MSAA.
2. Cone-weighted cut with the same MSAA and the same actual face count (or the predeclared nearest feasible count).
3. No-AA and full-source with MSAA as diagnostic/reference arms, not equal-cost winners selected after results.
4. Existing QEM/CornerSimplifier and unmodified meshoptimizer cluster LOD at matched face count where the selected cut is not already one of those methods.

Do not add SMAA, dynamic resolution, jittered accumulation, and learned ranking to this first mechanism screen. Once it shows a development-set Pareto gain, compare the frozen candidate with uniform-cut MSAA, SMAA and dynamic resolution at the same complete frame-time target on a physical phone.

### Assets, views, measures

- Start with licensed development assets and freeze train/validation/test by source identity, not by rendered views. The existing 32 Thingi10K assets have a 16/8/8 split, but verify their current manifests and licenses before reuse; do not tune on the 8 test meshes. Expand to at least 20 independently licensed confirmation assets across at least five geometry categories before publication.
- Use fixed stills first to isolate the selector, then held-out moving camera paths with translation, rotation, occlusion changes and view-dependent contour motion. Preserve a shared supersampled full-source reference and identical color transforms for every arm.
- Primary image endpoints: LDR-FLIP and silhouette/coverage error. Also report PSNR, SSIM, sampled surface distance, normal deviation, topology, cracks and duplicate faces. For sequences report a validated full-reference temporal metric such as CGVQM-5 and switch-local diagnostics; do not label a custom frame-difference diagnostic “perceptual.”
- Aggregate views within each asset, then bootstrap paired effects over assets. Report every asset, confidence interval, regression count, actual faces and infeasible budgets. Freeze practical-effect margins from repeated baseline measurements before candidate scoring.

### Resource accounting

Report selector CPU p50/p95, complete CPU update/submission cost, GPU p50/p95, draw calls, faces, sidecar/geometry bytes, peak memory and reference/render resolution. A rough binning proxy may count the screen-space tiles touched by each projected triangle, but that is not an actual GPU counter and is sensitive to triangle shape, clipping and tile size. On-device cost must use vendor profiling counters or stage timings where available; do not infer a phone win from Iris Xe or from the proxy alone.

For the physical-device phase, freeze device/GPU/driver, OS, renderer commit, output resolution, refresh target, thermal policy and complete-frame budget. Compare against 4× MSAA, SMAA and the renderer's existing dynamic-resolution/upscaling path at that same frame budget. Report frame misses, thermal drift and power if measurement support exists. Meta's [tiled-rendering guide](https://developers.meta.com/vr/documentation/unreal/gpu-tiled/) explains that its devices bin triangles into tiles before pixel shading; Arm likewise describes binning overhead in its [mobile GPU profiling article](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/finding-and-fixing-hidden-performance-problems-in-mobile-games-with-arm-performance-studio). These are architecture examples, not evidence that every GPU has the same per-triangle cost.

## Reject or advance

Advance only if the frozen selector yields a repeatable held-out quality–cost Pareto improvement over the qualified deterministic cuts at equal faces, respects cluster-boundary and topology constraints, and survives moving paths without unacceptable popping. Then perform the equal-frame-time phone comparison against AA and dynamic-resolution controls. If the improvement disappears after full selection/render cost, depends on one asset, or fails to beat strong controls, close the branch. The user-proposed week-four stop is a hard time-box, not a prediction of success.

No code or public render API change is authorized by this protocol. Keep any prototype in research tooling until it passes the gate. No phone is currently connected and the local Android SDK/adb path was previously unavailable; mobile measurements remain blocked on actual device access.

## Reproduction links

- [Silhouette objective screen](tools/mmtrain/DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md)
- [SMAA and perfect silhouette-band oracle](tools/mmtrain/GPU_SMAA_SILHOUETTE_BAND_SCREEN_20261122.md)
- [Silhouette guide fusion and repeat receipt](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- [Moving-camera per-instance LOD](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- [Four-week device and quality gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
