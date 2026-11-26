# ManyMesh: SIGGRAPH Research Roadmap

Some older references are listed as repository paths. Their supporting files
were retained in development archives.

Updated 2026-11-27. The SIGGRAPH-level goal is **not achieved**: no candidate
has shown both a defensible novelty boundary and repeatable gains over strong
baselines. SIGGRAPH 2027 lists the submissions form/conflicts deadline as 21
January 2027 at 22:00 UTC and the paper deadline as 28 January at 22:00 UTC.
The English Review Service recommends completing Technical Papers submissions
by 5 January. See the [official dates](https://s2027.siggraph.org/program/technical-papers/),
[English Review Service](https://s2027.siggraph.org/english-review-service-for-submissions/),
[research direction](SIGGRAPH_2027_DIRECTION.md), and [next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md).
This page indexes the research; dated reports preserve protocols, numbers,
failures, and limitations.

The active method hypothesis is offline optimization of a cluster DAG, scored
after a specified AA or upscaling pipeline. Close prior art includes
Hasselgren's differentiable mesh fitting, LTM's post-decimation vertex
deformation and topology refinement, and image-guided adaptive per-triangle
micro-mesh subdivision. A cluster-DAG and post-reconstruction distinction
remains an untested comparison question, not a novelty claim. No positive
held-out result is established. The seven-asset contour-priority control showed +0.167 dB mean
PSNR but mixed FLIP and no reliable AA gain; fixed-topology contour fitting
regressed on two of three assets. These remain development controls, not a
reason to advance a custom DAG optimizer. See the [current evidence summary](MANYMESH.md#evidence-that-changes-the-decision)
and [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).
The post-hoc 21-model attribution also shows that silhouette-XOR pixels do not
contain a majority of squared grayscale error for any source group: the
ManyMesh group mean is 31.0% without AA and 16.3% with 4x MSAA. Therefore the
old single-view silhouette finding is not a general premise for the method.
On the same cohort, 4x MSAA removes 38.8% of ManyMesh's total squared error,
compared with 58.0% for QEM and 67.1% for meshoptimizer; the contour and
non-contour error reductions are both material. Paired group differences are
19.2 percentage points for QEM and 28.3 for meshoptimizer, with the QEM gap
almost entirely outside the XOR mask; the post-hoc intervals are unadjusted.
Use it only as a scoped diagnostic, and require any contour-specific claim to
beat equal-cost controls after AA. See the
[attribution report](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md).
The frozen two-asset, nvdiffmodeling-based fixed-topology placement control
remains gated on a CUDA-capable host; it is not a faithful Hasselgren
reproduction or an asset-generalization test. A local Deliot-style D3D12
fixed-topology fit used the non-CUDA ID path, but all updates were rejected
and the instrumented replay directly attributed all 40 candidate trials to
the normal-floor guard. The candidate lost to the exact-face meshoptimizer
control on one reused train asset. That configuration is closed; the failure
does not clear the CUDA gate or advance to the confirmation cohort. See the
[fit result](tools/mmtrain/DELIOT_MSAA_PER_PIXEL_FIT_DEV_20261127.md),
[rejection diagnostic](tools/mmtrain/DELIOT_FIT_REJECTION_DIAGNOSTIC_20261127.md),
[prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md), and
[next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md).

A local CPU selected-cut preflight rebuilt node ownership from MMLG v7 and
locked the 1,109 shared vertices across the 29 nodes of a 5,290-face ManyMesh
cut. The candidate improved its raw initializer, but the fitted exact-face
meshoptimizer control scored 1.617 dB higher PSNR and 0.000326 lower mean
LDR-FLIP on 24 views of the same reused train asset. The frozen gate failed;
there was no QEM arm, no asset-held-out evaluation, and no final AA/upscaler
test. Do not advance this one-cut configuration to the unscored confirmation
pool. See the [protocol](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_PROTOCOL_20261127.md),
[report](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_20261127.md), and
[raw receipt](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_20261127.json).

A follow-up jointly optimized one shared MMLG position field across the 21.6%,
50% and 75.0% cuts of the same DAG. It improved raw ManyMesh at the two lower
budgets, but lost to the fitted exact-face meshoptimizer control at both; at
75%, meshoptimizer failed topology eligibility before scoring and fitted QEM
was the eligible fallback, which the joint fit lost by 7.513 dB PSNR and
0.001694 LDR-FLIP. All three cuts passed candidate topology/boundary checks,
but the fit did not meet its frozen quality gate. This remains one reused train
asset, not confirmation data. A post-hoc D3D12 Iris Xe 4x MSAA recheck of the
already-fitted meshes preserved the negative ranking at all three budgets;
candidate PSNR was lower by 6.86, 5.72, and 2.71 dB, and FLIP was worse by
0.002449, 0.002105, and 0.001019. This does not test geometry optimized
through the final AA operator. See the CPU [protocol](tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_PROTOCOL_20261127.md),
[report](tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.md), and
[per-view receipt](tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json),
plus the hardware [MSAA protocol](tools/mmtrain/CLUSTER_DAG_MULTICUT_FINAL_MSAA_RECHECK_PROTOCOL_20261127.md),
[result](tools/mmtrain/CLUSTER_DAG_MULTICUT_FINAL_MSAA_RECHECK_20261127.md), and
[per-view metrics](tools/mmtrain/cluster_dag_multicut_final_msaa_quality_20261127.json).

The older cone-weighted selector is closed: silhouette-profile and guide screens
missed their quality/cost gates, and the later cone-risk screen produced no
eligible equal-face, geometry-distinct candidates.

The FSR1/TAA-upscaling harness change has now compiled and linked in the existing Windows Vulkan Release tree. The full dependency build was blocked when Windows Application Control refused to run shader/resource generators; direct launch of `mm_bench.exe --help` was blocked as well. There are no runtime or image measurements from these options. See the build record (`tools/mmtrain/RENDER_HARNESS_BUILD_20261123.md`).

## Current direction

One direct triangle-mesh precedent must be included in any hierarchy comparison: Zhang and Chen (2013) combine a coarse cluster hierarchy with per-cluster progressive vertex hierarchies and GPU-parallel view-dependent updates. This closes generic claims around dual hierarchies and fine-grained within-cluster refinement. Their objective is projected geometric error and rendering efficiency, not image optimization after AA/upscaling; that difference remains only a research question, not a novelty result. See the [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).

Perceptual LOD allocation also has direct prior art. A 2026 VR mesh study collected user ratings for 320 stimuli across eight animated meshes and found that common image- and geometry-based metrics correlated only modestly with MOS under its protocol. Its QoE model used a random stimulus split, so it does not establish unseen-asset transfer. A Web3D 2026 paper then used QoE prediction for LOD allocation under GPU-memory budgets. These are not post-AA cluster-DAG geometry optimization, but they rule out claiming QoE-aware allocation itself as new. For ManyMesh, keep technical metrics distinct from user preference and require asset-held-out validation before calling a score perceptual. See the [prior-art notes and source-access limits](docs/manymesh/siggraph-prior-art-screen-20261123.md).

The tested per-cluster latent/residual decoder ran once on the CPU during asset loading. Its rank-8/16/30 shared polynomial linear-subspace controls are closed: none beat same-face validation baselines, and higher ranks increased storage and decoding failures. A validation-only latent-scale probe also found every nonzero scale worse on four paired assets and topology/offset rejection on a fifth. Direct prior art further narrows this branch: render-space mesh simplification is established; NeCGS already compresses large geometry sets with shared decoder weights and per-model latents; Neural Progressive Meshes use per-face progressive residual features; and [Learned Localized Mesh Refinement](https://doi.org/10.1145/3829340.3842280) is a SIGGRAPH Asia 2026 Conference Paper whose presentation the authors list as deferred to SIGGRAPH 2027. It establishes learned local refinement and view-dependent budget allocation, but targets coarse-to-fine refinement rather than appearance-preserving simplification. See the [updated prior-art comparison](MANYMESH_LEARNED_LOD_RESEARCH.md), [research status](MANYMESH.md), same-face comparison (`tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md`), rank sweep (`tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md`), and scale probe (`tools/mmtrain/CLUSTER_DECODER_SCALE_PROBE_20261122.md`).

A dynamic LOD screen on 13 reused Khronos assets found that a per-asset profile's PSNR gain fell from +0.258 dB to +0.083 dB (95% asset-bootstrap CI [-0.019, +0.190]) under shared-profile leave-one-asset-out evaluation. SSIM is inconclusive and silhouette IoU significantly declines. A four-path follow-up found 3.8% lower foreground temporal finite-difference MAE for the shared profile (delta -0.000942, 95% asset-bootstrap CI [-0.001434, -0.000488]) and 2.08 fewer switch-bearing transitions per 48-frame path. This pixel diagnostic is not flow-compensated or perceptually calibrated and does not rescue the formulation. Cost-benefit LOD allocation and hysteresis have prior art; independent confirmation is also absent. See the per-asset screen (`tools/mmtrain/DYNAMIC_LOD_13ASSET_20261122.md`), leave-one-asset-out screen (`tools/mmtrain/DYNAMIC_LOD_LOAO_13ASSET_20261122.md`), and temporal diagnostic (`tools/mmtrain/DYNAMIC_LOD_TEMPORAL_DIAGNOSTIC_20261122.md`).

A silhouette-XOR training-objective follow-up selected the area ranker on all thirteen leave-one-asset-out folds. This means the measured framewise and temporal deltas are exactly zero: the altered objective did not change the policy. Treat this as a negative result for that profile configuration, not evidence for silhouette-aware geometry. See the screen and raw receipts (`tools/mmtrain/DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md`) and temporal diagnostic (`tools/mmtrain/DYNAMIC_LOD_SILHOUETTE_TEMPORAL_20261122.md`).

The source audit also confirms the current sidecar does not provide independent cluster decoding: the decoder reads all latents and rebuilds the whole mesh. Treat cluster-indexed storage as a data-layout choice until a partial-decode implementation and matched-cost result establish a real capability. Do not use it as the novelty boundary. Details are in the [learned-LOD research notes](MANYMESH_LEARNED_LOD_RESEARCH.md) and the archived matched-face decoder report (`tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md`).

The dynamic-LOD renderer now exports lossless FFV1 sequences with exact pixel round-trip checks. A CGVQM-5 screen on two paths across the 13 reused Khronos assets found a path-averaged selected-profile minus area mean of -0.0590 (95% asset-bootstrap CI [-0.1476, +0.0424]); four assets improved and nine regressed. The adapter used OpenCV FFmpeg decoding, not upstream PyAV. The interval crosses zero and does not establish a temporal-quality gain; the dynamic-profile formulation remains closed. See the CGVQM screen (`tools/mmmetrics/CGVQM_DYNAMIC_LOD_SCREEN_20261122.md`), temporal diagnostic (`tools/mmtrain/DYNAMIC_LOD_TEMPORAL_DIAGNOSTIC_20261122.md`), and protocol (`tools/mmmetrics/TEMPORAL_QUALITY_PROTOCOL.md`).

The existing 32-asset corpus uses a 16/8/8 train/validation/test split; the decoder held-out test split remains unused. On five of eight validation assets, meshoptimizer beats QEM at the same face count across image metrics; all eight source STLs pass topology, but three QEM coarse outputs fail the topology gate. The rank-8 fixed decoder leaves meshoptimizer unchanged, and its local refinement loses to meshoptimizer simplified directly from the source at the same final face count on four paired validation assets. These results close the tested configurations, not learned geometry decoding in general. See the comparison report (`tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md`), QEM failure audit (`tools/mmtrain/cluster_decoder_validation_failure_audit_20261122.json`), and its receipts (`tools/mmtrain/cluster_decoder_meshopt_screen_20261122.json`), refinement receipt (`tools/mmtrain/cluster_decoder_refine_budget_20261122.json`).

A separate 70%-retention baseline sweep now covers all eight validation assets with 12 rendered views per asset. It reports PSNR, SSIM, FLIP, silhouette, and sampled surface metrics; effect directions are mixed, and one meshoptimizer output fails topology. See the full report (`tools/mmtrain/CLUSTER_DECODER_BASELINE_70PCT_VALIDATION_20261122.md`) and per-view receipt (`tools/mmtrain/cluster_decoder_qem_meshopt_validation_70pct_20261122.json`).

The upstream cluster LOD screen (`tools/mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md`) compares the unmodified meshoptimizer v1.2 hierarchy against whole-mesh QEM. Across six valid exact-face pairs at its first coarser depth, it improves PSNR by 3.60 dB. The fixed-default current-source audit found no valid exact-face pair. A later fixed 48-build parameter grid found two legal exact-face pairs across two reused validation assets; both lost to stock on the reported image metrics. The saved-graph oracle and 44-cut reranking remain historical evidence: legal cuts improve geometric selection on two assets but still lose to stock on all five feasible assets. See the parameter sweep (`tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md`), fixed-default audit (`tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md`), cut audit (`tools/mmgeo/HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md`), and reranking screen (`tools/mmgeo/SAVED_CUT_VIEW_RERANK_20261122.md`).

Rendered reranking (`tools/mmgeo/SAVED_CUT_VIEW_RERANK_20261122.md`) scores 44 legal cuts under those same caps. Fit-view selection improves held-out LDR-FLIP on two assets. The best measured alternative for each of the five feasible assets still loses to upstream.

The eight-asset geometry codec screen (`tools/mmtrain/GEOMETRY_CODEC_RATE_DISTORTION_20261122.md`) adds Draco and meshoptimizer rate-distortion baselines for full and simplified geometry. It counts headers and streams, renders decoded geometry, and explicitly gates results on topology checks. It measures static whole-mesh payloads only; it does not measure partial-page streaming, network transfer, or time-to-quality.

The Draco grid origin experiment (`tools/mmtrain/QUANTIZATION_GRID_ORIGIN_20261122.md`) tests whether shifting a uniform grid reduces byte cost while preserving the source face structure. On the eight validation meshes the significant byte reductions each accompany worse LDR-FLIP. The tested grid search is closed.

The same protocol also covers the 16 training assets as a separate development screen. One QEM result is rejected; only 10/15 paired meshoptimizer outputs pass strict topology and boundary checks. The image-metric gains in this split are descriptive only and do not count as held-out evidence. See the training report (`tools/mmtrain/CLUSTER_DECODER_BASELINE_70PCT_TRAIN_20261122.md`) and receipt (`tools/mmtrain/cluster_decoder_qem_meshopt_train_70pct_20261122.json`).

A lower 50%-retention screen checked whether the historical Monkey silhouette-error fraction generalizes. With binary coverage XOR attribution, contour-mismatch pixels explain 27%-37% of squared image error on average, not the historical 68.3%; the result varies by model, simplifier and budget. Aggressive reduction also increases topology rejections. See the attribution report (`tools/mmtrain/SILHOUETTE_ERROR_ATTRIBUTION_20261122.md`) and the split-specific receipts (`tools/mmtrain/cluster_decoder_qem_meshopt_validation_50pct_20261122.json`), train (`tools/mmtrain/cluster_decoder_qem_meshopt_train_50pct_20261122.json`).

A three-asset, 16-instance Iris Xe screen adds 4x MSAA and half-resolution upscaling baselines at 1080p. A selected 20%-face ToyCar cut plus MSAA reaches 30.914 dB / 0.981750 SSIM at 0.956 ms median GPU time: about 3.15x faster than full-source native rendering at 1.77 dB lower PSNR, and 3.29x faster than full-source linear upscaling at 1.39 dB higher PSNR. Other assets have different quality-cost rankings. This is offscreen, fixed-view desktop data only; see the 1080p GPU report (`tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_1080_BASELINE_20261122.md`) and 720p repeat (`tools/mmtrain/CLUSTER_DECODER_GPU_MSAA_BASELINE_20261122.md`).

The 13-asset SMAA follow-up (`tools/mmtrain/GPU_SMAA_SILHOUETTE_BAND_SCREEN_20261122.md`) uses the Bevy port and an independent supersampled reference. Full-source SMAA has higher LDR-FLIP than MSAA on all assets. A perfect correction in a two-pixel coarse-outline band covers 3.43% of pixels and removes 71.0% of squared error on average. It adds three assets to the set that outperform existing measured controls at the cut's GPU budget, before correction cost.

The [half-resolution guide follow-up](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md) renders full source geometry at half resolution alongside a native-size component cut. Detail recovery lowers LDR-FLIP on 8/13 assets versus the cut alone, with a mean 1.358 ms GPU cost increase. Both fusion variants are dominated by an eligible control across LDR-FLIP, PSNR, and SSIM on every asset. Close the two tested variants.

The cached sparse native-resolution guide (`tools/mmtrain/SPARSE_SILHOUETTE_GUIDE_SCREEN_20261122.md`) retains 51.2% of source triangles on average and exactly reproduces the full guide within the outline band. Even with its fixed-view preparation amortized, it extends the measured FLIP frontier on 2/13 assets and misses the frozen gate. Close this cached two-pass configuration.

The million-triangle mixed-scene benchmark (`tools/mmtrain/MIXED_SCENE_BASELINES_20261122.md`) adds shared depth, distinct meshes, and two pinned meshoptimizer cluster cuts. Stock depth 2 with 4× MSAA beats the supplied QEM and component cuts on GPU p50 and FLIP in all nine views. The layout control (`tools/mmtrain/MIXED_SCENE_LAYOUT_CONTROL_20261122.md`) reverses the speed ranking on all views after applying common cache and fetch optimization, while depth 2 retains its quality advantage. Use both points in future baselines. The cuts submit different face counts, and stock depth 2 introduces nonmanifold edges on three meshes whose source exports had none.

The matched face-budget screen (`tools/mmtrain/MIXED_SCENE_FACE_BUDGETS_20261122.md`) keeps equal full-source fallbacks for ineligible assets. Stock has lower FLIP and higher PSNR/SSIM on all nine views at exact counts, within one face per asset, and in an edge-clean subset. Its exact-cohort paired medians are −0.00252 FLIP, +2.81 dB and +0.050 ms. Recomputing stock normals reduces its quality lead while keeping it ahead of QEM. Sampled surface distance is mixed. The same run remeasures optimized SMAA and both upscalers.

The whole-asset LOD allocation screen (`tools/mmtrain/MIXED_SCENE_LOD_ALLOCATION_20261122.md`) exhaustively scores 384 screened stock-depth assignments. Area allocation beats all GPU-time-eligible uniform controls in 9/9 views at each of three face caps. A profile fit on the other two scene views improves on area in only three view–cap pairs across 27, with zero median gain at the main cap. Close this fitted profile. Keep area selection with its archived coverage as a development comparator.

The per-instance comparison (`tools/mmtrain/MIXED_SCENE_INSTANCE_LOD_20261122.md`) finds a small positive static result for bounding-rectangle greedy allocation. It improves FLIP over whole-asset area in 9/9 views at the same triangle ceiling, using a median 102,125 more triangles. The completed [48-frame moving-camera follow-up](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md) found that instance-area improves image metrics only while using 2.8–12.3% more faces and 12.4–15.2% more GPU time. Under a per-frame matched face cap, the instance oracle is unchanged on two scenes and slightly better on one, but costs 2.00–5.13 ms GPU and 1.25–8.68 ms CPU selection time. This does not establish a practical equal-cost or independent result; keep it as a development control, not a contribution candidate.

Do not change the production format or rendering API until a frozen method improves the held-out quality/cost Pareto frontier over strong deterministic baselines, with topology and boundary constraints satisfied. A fresh licensed confirmation set is required for a publication claim. No mobile-device result or user study exists.

The Poly Haven confirmation set contains 30 eligible models across 25 slug-family groups and nine categories. Its inputs, camera split, renderer, metrics, and project-specific pass margins are frozen, but it remains unscored until a method configuration passes a development gate. This is not a quality result. See the [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md) and [pool report](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md).

The prior-art screen covers learned local refinement, split-and-rewire mesh generation, crack-free clustered HLOD boundaries, and GPU out-of-core rendering. See the updated prior-art table in [the learned-LOD research notes](MANYMESH_LEARNED_LOD_RESEARCH.md). No active method is presently supported by both a novelty gap and positive held-out results.

## Closed or unproven branches

- **Visibility proxies and shared traversal:** measured variants did not establish end-to-end gains over direct fine-mesh queries. Keep exactness checks distinct from a performance claim.
- **Partition repair and adjacent merges:** stronger controls and complete-work accounting left little or no robust improvement; these formulations are not current contribution candidates.
- **Image-filtered edge edits and camera-path scoring:** exact kernels and local checks exist, but quality advantage, total build cost, and novelty over prior image-driven simplification have not passed the gate. EdgeGrad already provides raster-loss gradients at mesh visibility edges; DiffSoup reconstructs budgeted triangle soups from multiview images. A rendered follow-up across four development units found mixed PSNR/SSIM/FLIP changes with asset-bootstrap intervals spanning zero, while construction took 4.5–15.1x QEM time (report (`tools/mmgeo/PATH_LOSS_RENDER_QUALITY_20261122.md`)). On Torus, allowing newly created edges improved the fitted view but increased held-out 13-view filtered error 65.68x at a 1.39% face reduction ([matched controls](tools/mmgeo/DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md)). The 4% Monkey cache replication also remains 3.82x slower than QEM and ties its held-out geometry-proxy quality. See the [filtered-boundary novelty update](MANYMESH_FILTER_AWARE_SIMPLIFICATION.md#2026-11-22-prior-art-update); this line is historical and is not the active implementation queue.
- **ReSTIR-LoD and ray-tracing combinations:** prior-art and feasibility screens did not produce a validated candidate. Wang et al.'s full SIGGRAPH 2026 paper now directly establishes UV-mapped temporal ReSTIR reuse across topology-changing LoD, under one LoD per object per frame. This further closes broad temporal-LOD claims; it remains a path-tracing method, separate from the active raster mesh-fitting question. See the [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md) and [detailed ReSTIR correction](tools/mmgeo/RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md). The current scope is rasterized mesh processing.
- **Learned image ranking and super-resolution:** the small learned configurations lost to their validation baselines; this does not rule out learned mesh refinement generally.
- **Dynamic LOD profile:** the shared profile improves the custom temporal finite-difference diagnostic but has no reliable framewise PSNR gain and regresses silhouette IoU. The two-path CGVQM-5 screen has a mean paired delta of -0.0590 (95% asset-bootstrap CI [-0.1476, +0.0424]), with 4/13 assets improved; it does not provide a reliable perceptual gain. These reused assets and the synthetic grayscale renderer do not validate a novel method. CGVQM screen (`tools/mmmetrics/CGVQM_DYNAMIC_LOD_SCREEN_20261122.md`) and temporal diagnostic (`tools/mmtrain/DYNAMIC_LOD_TEMPORAL_DIAGNOSTIC_20261122.md`).
- **Memory-bounded DAG construction:** generic external-memory continuous LOD hierarchy construction with an adjustable memory cap is established prior art. Derzapf et al. (VMV 2010) also cover file-backed view-dependent progressive updates and bounded per-frame transfer. A partial strict-gate cut remains only an untested engineering question and needs faithful construction and runtime-streaming baselines before further investment. Prior-art and experiment screen (`tools/mmgeo/ON_DEMAND_DAG_BUILD_MEMORY_SCREEN_20261118.md`).

## Dated experiment index

The links below preserve the detailed reports referenced by the earlier roadmap. Negative findings and failed cases are documented alongside successful checks.

### 2026-11-15: visibility, partition, and topology controls

- [Fused patch visibility cost gate](tools/mmgeo/FUSED_PATCH_VISIBILITY_COST_GATE.md)
- [Visibility-query BVH cost gate](tools/mmgeo/VISIBILITY_QUERY_BVH_COST_GATE.md)
- [Edit-derived visibility support preflight](tools/mmgeo/EDIT_VISIBILITY_SUPPORT_PREFLIGHT.md)
- [Proxy visibility cost gate](tools/mmgeo/PROXY_VISIBILITY_COST_GATE.md)
- [Mixed-LOD ReSTIR measure screen](tools/mmgeo/RESTIR_MIXED_LOD_MEASURE_SCREEN.md)
- [Seam-contract merge control](tools/mmgeo/SEAM_CONTRACT_MERGE_CONTROL.md)
- [Adjacent-merge counterfactual](tools/mmgeo/ADJACENT_MERGE_COUNTERFACTUAL.md)
- [Fixed-boundary QEM control](tools/mmgeo/FIXED_BOUNDARY_QEM_CONTROL.md)
- [Partition QEM exhaustion](tools/mmgeo/PARTITION_QEM_EXHAUSTION.md)
- [Partition boundary floor preflight](tools/mmgeo/PARTITION_BOUNDARY_FLOOR_PREFLIGHT.md)
- [OBJ contract floor audit](tools/mmgeo/OBJ_CONTRACT_FLOOR_AUDIT.md)
- [SIGGRAPH literature delta](tools/mmgeo/SIGGRAPH_2027_LITERATURE_DELTA_20261115.md)
- [Appearance compensation results](tools/mmgeo/APPEARANCE_COMPENSATION_RESULTS.md)
- [Camera-event certificate preflight](tools/mmgeo/CAMERA_EVENT_CERTIFICATE_PREFLIGHT.md)
- [Dynamic GPU related work](tools/mmgeo/RELATED_WORK_DYNAMIC_GPU.md)
- [Appearance compensation protocol](tools/mmgeo/APPEARANCE_COMPENSATION_PROTOCOL.md)
- [Appearance compensation v1 stop decision](tools/mmgeo/APPEARANCE_COMPENSATION_V1_STOP.md)
- [Normal-transfer attribution](tools/mmgeo/NORMAL_TRANSFER_ATTRIBUTION.md)
- [Appearance recoverability preflight](tools/mmgeo/APPEARANCE_RECOVERABILITY_PREFLIGHT.md)
- [Progressive image protocol](tools/mmgeo/PROGRESSIVE_IMAGE_PROTOCOL.md)
- [Shading controls](tools/mmgeo/SHADING_CONTROLS.md)
- [Normal-offset protocol](tools/mmgeo/NORMAL_OFFSET_PROTOCOL.md)
- [Contour-visibility ablation](tools/mmgeo/CONTOUR_VISIBILITY_ABLATION.md)
- [Source-contour control](tools/mmgeo/SOURCE_CONTOUR_CONTROL.md)
- [Progressive baseline](tools/mmgeo/PROGRESSIVE_BASELINE.md)
- [Real-candidate interactions](tools/mmgeo/REAL_CANDIDATE_INTERACTIONS.md)
- [Direct complementary results](tools/mmgeo/DIRECT_COMPLEMENTARY_RESULTS.md)
- [Complementary-geometry protocol](tools/mmgeo/COMPLEMENTARY_GEOMETRY_PROTOCOL.md)
- [Complementary-geometry results](tools/mmgeo/COMPLEMENTARY_GEOMETRY_RESULTS.md)
- [Raster-placement protocol](tools/mmgeo/RASTER_PLACEMENT_PROTOCOL.md)
- [Depth-candidate protocol](tools/mmgeo/DEPTH_CANDIDATE_PROTOCOL.md)
- [Depth-candidate results](tools/mmgeo/DEPTH_CANDIDATE_RESULTS.md)
- [Fragment-transaction results](tools/mmgeo/FRAGMENT_TRANSACTION_RESULTS.md)
- [Bounded-collapse protocol](tools/mmgeo/BOUNDED_COLLAPSE_PROTOCOL.md)
- [Discrete filter energy](tools/mmgeo/DISCRETE_FILTER_ENERGY.md)
- [Filtered-boundary experiment](tools/mmgeo/FILTERED_BOUNDARY_EXPERIMENT.md)
- [Filter-aware simplification overview](MANYMESH_FILTER_AWARE_SIMPLIFICATION.md)

### 2026-11-16: budget, dynamic recapture, and interaction screens

- [Target-budget frontier pilot](tools/mmgeo/TARGET_BUDGET_FRONTIER_PILOT_20261116.md)
- [Target-budget oracle control](tools/mmgeo/TARGET_BUDGET_ORACLE_SCREEN_CONTROL_20261116.md)
- [Target-budget resource oracle](tools/mmgeo/TARGET_BUDGET_RESOURCE_ORACLE_20261116.md)
- [Multi-collapse interaction audit](tools/mmgeo/MULTI_COLLAPSE_INTERACTION_AUDIT_20261116.md)
- [Dynamic recapture audit](tools/mmgeo/DYNAMIC_RECAPTURE_AUDIT_20261116.md)
- [Dynamic recapture full-pool audit](tools/mmgeo/DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md)
- [Tangent-frame PBR novelty audit](tools/mmgeo/TANGENT_FRAME_PBR_NOVELTY_AUDIT_20261116.md)
- [ReSTIR-LoD UV transport preflight](tools/mmgeo/RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md)
- [ReSTIR reuse-aware LOD hypothesis](tools/mmgeo/RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md)
- [Screen-batch support audit](tools/mmgeo/SCREEN_BATCH_SUPPORT_AUDIT_20261116.md)
- [Batch-support schedule builder](tools/mmgeo/make_batch_support_schedule.py)
- [Batch-support audit summarizer](tools/mmgeo/summarize_batch_support_audit.py)
- [Multi-collapse cross-asset audit](tools/mmgeo/MULTI_COLLAPSE_INTERACTION_CROSS_ASSET_20261116.md)
- [Shared-parent alternatives audit](tools/mmgeo/SHARED_PARENT_ALTERNATIVES_AUDIT_20261116.md)

### 2026-11-17: ReSTIR-LoD and mixed-cut novelty checks

- [ReSTIR overlap-matching preflight](tools/mmgeo/RESTIR_OVERLAP_MATCHING_PREFLIGHT_20261117.md)
- [ReSTIR visibility-matching screen](tools/mmgeo/RESTIR_VISIBILITY_MATCHING_SCREEN_20261117.md)
- [Mixed-group cut frontier](tools/mmgeo/MIXED_GROUP_CUT_FRONTIER_20261117.md)
- [Quality-gate partition novelty screen](tools/mmgeo/QUALITY_GATE_PARTITION_NOVELTY_SCREEN_20261117.md)
- [Per-ray LOD/ReSTIR novelty screen](tools/mmgeo/PER_RAY_LOD_RESTIR_NOVELTY_SCREEN_20261117.md)
- [ReSTIR mixed-cut prior-art correction](tools/mmgeo/RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md)
- [ReSTIR CPU weight screen](tools/mmgeo/RESTIR_CPU_WEIGHT_SCREEN_20261117.md)
- [ReSTIR CPU direct-visibility screen](tools/mmgeo/RESTIR_CPU_DIRECT_VISIBILITY_SCREEN_20261117.md)
- [ReSTIR nested-LOD geometry screen](tools/mmgeo/RESTIR_NESTED_LOD_GEOMETRY_SCREEN_20261117.md)
- [ReSTIR tail-risk LOD candidate](tools/mmgeo/RESTIR_TAIL_RISK_LOD_CANDIDATE_20261117.md)
- [ReSTIR reservoir risk-hook audit](tools/mmgeo/RESTIR_RESERVOIR_RISK_HOOK_AUDIT_20261117.md)
- [Research decision](tools/mmgeo/RESEARCH_DECISION_20261117.md)
- [Camera-orbit sampling summarizer](tools/mmgeo/summarize_camera_orbit_sampling.py)

### 2026-11-18 to 2026-11-19: camera paths and learned scheduling

- [Spatial-retry local frontier audit](tools/mmgeo/SPATIAL_RETRY_LOCAL_FRONTIER_AUDIT_20261118.md)
- [Adaptive camera-path ranking screen](tools/mmgeo/ADAPTIVE_CAMERA_PATH_RANKING_SCREEN_20261118.md)
- Filtered depth-envelope events (`tools/mmgeo/FILTERED_DEPTH_ENVELOPE_EVENTS_20261119.md`)
- Closed hybrid learned path-loss screen ([report](tools/mmgeo/HYBRID_LEARNED_PATH_LOSS_20261119.md),
  [audit script](tools/mmgeo/audit_path_loss_residual_hybrid.py))
- Exact strict cut-frontier oracle (`tools/mmgeo/EXACT_STRICT_CUT_FRONTIER_ORACLE_20261119.md`)
- Exact cut-frontier audit script (`tools/mmgeo/audit_exact_cut_frontier_oracle.py`)
- Memory-capped learned DAG synthesis (`tools/mmgeo/LEARNED_MEMORY_CAPPED_DAG_SYNTHESIS_20261119.md`)
- Oracle-guided DAG scheduler probe (`tools/mmgeo/probe_oracle_guided_dag_scheduler.py`)
- Slack-aware cut scheduler probe (`tools/mmgeo/probe_slack_aware_cut_scheduler.py`)

## Next gate

The shared-position CPU fit across three selected cuts also failed its frozen
quality gate against fitted exact-face controls. This does not make the broader
final-AA/upscaler hierarchy question a result: the screen used one reused train
asset, a CPU sampling proxy, and did not fit every legal cut or transition. The
confirmation set remains unscored, and all three CPU fitting configurations
tested so far have failed development gates.

Do not continue the tested rank-8/16/30 polynomial decoder configurations. The default current-source audit produced no legal exact-face stock pair. A follow-up 48-build parameter sweep recovered two exact-face, topology-valid pairs across two reused validation assets; both lost to stock cluster LOD on all reported image metrics. This is a small negative quality screen, not evidence that every parameterization loses. The saved-graph oracle found legal under-cap cuts on 5/8 assets, yet all scored legal cuts lost to stock; rendered reranking of 44 legal cuts improved geometric selection on two assets but both selected and pool-best cuts lost on all five feasible assets. A legality fix alone is insufficient. See the parameter sweep (`tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md`), fixed-default audit (`tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md`), historical cut audit (`tools/mmgeo/HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md`), and reranking report (`tools/mmgeo/SAVED_CUT_VIEW_RERANK_20261122.md`). The current cone-risk selector screen also failed to produce equal-face, geometry-distinct outputs; it is closed as a contribution candidate. The independent nvdiffmodeling placement baseline is the next research falsification only after suitable CUDA compute and cleared assets are available.
A separate same-face whole-mesh meshoptimizer control screen has three eligible under-cap pairs across two reused assets: two neighboring levels improve on one asset, while the second asset regresses on all image metrics. The only eligible QEM pair also regresses. This is mixed pilot evidence, not held-out generalization or a comparison with stock cluster cuts; see the matched-face report (`tools/mmtrain/CURRENT_SOURCE_MATCHED_FACE_CONTROLS_20261123.md`).

A current-source screen on previously used Stanford Lucy adds a negative development result: the DAG floor is 48.50% of source faces, so a requested 30% budget is infeasible, and the three reachable cuts lose to exact-face QEM and meshoptimizer on all listed static image metrics. Lucy is already contaminated for confirmation use. See the screen report (`tools/mmtrain/LUCY_CURRENT_SOURCE_QUALITY_SCREEN_20261123.md`) and asset reuse audit (`docs/manymesh/confirmation-asset-screen-20261123.md`). Do not count this as an independent test or a generalization result.

A current-source Monkey diagnostic now uses the original 15,744-face OBJ as reference rather than a DAG cut. Its three requested budgets measured 25.8%-34.8% silhouette-error share. Exact directed-edge matching flagged every cut, but a retrospective coordinate map matched all 168 oriented boundary edges within 0.52 float32 epsilon at unit radius; sampled curve deviation was at most 6.08e-8 and relative boundary-length error was 3.3e-9. Eligible exact-face controls beat the cuts on image metrics. This resolves the reference ambiguity for this diagnostic, but does not establish a preregistered boundary criterion or a held-out result. See the report (`tools/mmtrain/MONKEY_ORIGINAL_SOURCE_DIAGNOSTIC_20261123.md`), image-quality receipt (`tools/mmtrain/monkey_source_reference_diagnostic_20261123.json`), and curve audit (`tools/mmtrain/monkey_boundary_curve_audit_20261123.json`). The DamagedHelmet lead also failed the strict topology gate before image scoring; see the asset screen (`tools/mmtrain/DAMAGED_HELMET_TOPOLOGY_GATE_20261123.md`).

The node-level cone-risk selector has now been built and run on the 12 repository OBJ fixtures at requested ratios 0.3, 0.5, and 0.7. All 108 candidate PLY counts match their headers, but the screen found zero equal-face, geometry-distinct candidates; no AA image-quality metrics were scored, and Idea 3 is closed under this implementation. See the budget screen (`tools/mmgeo/CONTOUR_SELECTOR_BUDGET_SCREEN_20261123.md`) and raw receipt (`tools/mmgeo/contour_budget_screen_20261123.json`). The frozen nvdiffmodeling-based fixed-topology placement control remains unrun: the host has CPU-only PyTorch and no CUDA runtime. It is not a faithful reproduction of Hasselgren et al. or an asset-generalization test. Do not implement the constrained DAG optimizer until this control can run on hash-pinned, redistribution-cleared inputs. Test geomorphing only if moving-camera evidence shows a meaningful transition artifact; it is not a standalone novelty claim. Freeze assets, views, metrics, exclusion rules, and practical-effect margins in advance; the reused 32-asset test split is not assumed clean. See the [research direction](SIGGRAPH_2027_DIRECTION.md), cluster-LOD baseline screen (`tools/mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md`), cut-feasibility audit (`tools/mmgeo/HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md`), rendered reranking report (`tools/mmgeo/SAVED_CUT_VIEW_RERANK_20261122.md`), and prior-art review (`docs/manymesh/siggraph-prior-art-screen-20261123.md`). Production integration, mobile claims, and a perceptual claim each require separate evidence gates.
