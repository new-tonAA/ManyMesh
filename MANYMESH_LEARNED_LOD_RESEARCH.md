# ManyMesh dynamic geometry: learned algorithms and research protocol

Research date: 2026-11-10; updated 2026-11-22. Sections 1-7 describe the original
research proposal; experiment results start at section 8. This is a historical
proposal and experiment record. The tested rank-8 decoder configurations are closed;
see [current research status](MANYMESH.md) and the [decoder study and prior-art audit](MANYMESH_CLUSTER_DECODER_STUDY.md).

## 1. Recommendation

The original proposed direction was reconstruction-residual-driven dynamic LOD:
retain geometry and hierarchy legality, predict the final-image error removed by
local refinement, and allocate budgets using switching risk, residency, and actual
execution costs. Ask how much additional geometry improves the final image in its
current context. Reconstruction must be optional and enabled only after measuring
net benefit.

Initially restrict scope to static meshes, moving cameras, and changing lighting.
Skinning and topology changes need separate bounds, deformation errors, and training
distributions; support cannot be assumed.

## 2. Existing repository components

- `libs/manymesh/src/Simplifier.cpp`, `AttributeSimplifier.cpp`, and
  `CornerSimplifier.cpp` provide geometry/attribute simplification and quality gates.
- `libs/manymesh/src/LodGraph.cpp` builds the hierarchy, accumulates errors, and
  maintains legal cuts. `selectLodGraphCut` selects by screen error;
  `selectLodGraphAtRatio` selects under a triangle budget with further refinement.
- `libs/manymesh/src/GeometryError.cpp` projects world errors into pixels, estimating
  sphere depth at the near side. This already exceeds a distance-only threshold.
- `libs/manymesh/src/GpuLodCutShaders.h` uses accumulated errors and one screen threshold.
- `libs/manymesh/src/Streaming.cpp` supplies page caches, asynchronous requests,
  and residency queries for joint scheduling.
- `tools/mmtrain/train.py` already contains Tiny/TinyUpsample reconstruction and
  error-map experiments; adding a CNN is not this study's contribution.

CPU reference algorithms, GPU selection, actual rendering submission, and device
performance are separate evidence. GPU data structures do not establish mobile gains.
Historical observations used for design, not reproduced for this proposal:

- `tools/mmtrain/README.md` reports about +1.88 dB reconstruction on training asset
  Dragon but only +0.15 dB on Monkey. Whole-image gain need not improve common coverage.
- Error-map gains change sign; adding a geometry-error channel need not help.
- Temporal experiments in [the history](MANYMESH_HISTORY.md) show negative history
  gains at low budgets. Small motion does not automatically justify aggressive reduction.

## 3. Related work and applicability

Descriptions come from author/institution pages or abstracts. Applicability is
project judgment; these external methods have not been reproduced here.

| Work | Established contribution | Implication and limits |
|---|---|---|
| [Adaptive Display Algorithm, SIGGRAPH 1993](https://pixl.cs.princeton.edu/pubs/Funkhouser_1993_ADA/index.php) | Benefit/cost allocation of LOD and rendering algorithms under a frame budget. | Budget optimization is established; test whether reconstruction meaningfully changes equal-face edit rankings. |
| [Neural Mesh Simplification, CVPR 2022](https://www.ploumpis.com/publication/neural_simp/) | Learned vertex sampling, sparse-attention triangle proposals, and triangle selection. | Direct neural reduction baseline; validate materials, UVs, topology, scale, and our frame costs separately. |
| [Appearance-Driven Automatic 3D Model Simplification, EGSR 2021](https://research.nvidia.com/publication/2021-04_appearance-driven-automatic-3d-model-simplification) | Differentiable joint mesh/shading optimization against reference appearance. | Useful offline LOD/material optimization; not automatically a generalizing runtime network. |
| [Neural Compression for 3D Geometry Sets, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.html) ([code](https://github.com/rsy6318/NeCGS)) | Shared quantization-aware auto-decoder, per-model embedded features, entropy coding, and TSDF-Def/deformable-marching-cubes mesh reconstruction; evaluated on up to 1,000 Thingi10K models. | Direct learned set-compression neighbor. A cluster-latent decoder must distinguish independent access, source-topology/attribute guarantees, or a measured rate-distortion and total-cost advantage; those are not established by the current prototype. |
| [Neural Progressive Meshes, SIGGRAPH 2023](https://arxiv.org/abs/2308.05741) | Learned subdivision encoding/decoding with progressive residual features. | Relevant compression/streaming neighbor that changes representation and decoding. |
| [Gaze-Contingent Perceptual LOD Prediction](https://www.pdf.inf.usi.ch/projects/GazeContingentPerceptualLOD/) | Silhouette/surface distortion and temporal visibility of switching. | Perception and temporal stability have precedents; screen center is not measured gaze. |
| [VertexRegen, ICCV 2025](https://vertexregen.github.io/) | Learned reverse collapses/vertex splits, stoppable generation of complete meshes at different detail. | Generative continuous LOD differs from faithful runtime selection for an input asset. |
| [Learned Localized Mesh Refinement, SIGGRAPH Asia 2026 paper deferred to SIGGRAPH 2027](https://adg.csail.mit.edu/?page_id=13) ([paper](https://arxiv.org/abs/2609.31946), [code](https://github.com/seanxzhan/learned-localized-mesh-refinement)) | Autoregressive regional refinement with topology/geometry updates and view-dependent applications. | Direct overlap with the local-refinement branch; region selection alone is insufficient novelty. |
| [Perceptually Guided 3DGS Streaming and Rendering for Mixed Reality, institutional introduction April 2026](https://sonyinteractive.com/en/news/blog/perceptually-guided-3dgs-streaming-and-rendering-for-mixed-reality/) | Distilled spatiotemporal perceptual metrics and budget-driven streaming LOD. | Gaussian rather than triangle representation, but perceptual learning plus budgets already has a close precedent. |

Do not begin with per-frame mesh generation or global reinforcement learning.
Start with verifiable local decisions, bounded execution, and existing legal
hierarchies. Generative methods could later supply offline candidates.

## 4. Proposed algorithm

Working name: reconstruction-residual-driven budget LOD. This is a hypothesis,
not a published algorithm.

### 4.1 Supervision from rendering interventions

Render a legal cut C and C', which replaces only one node with its children, using
identical camera, lighting, materials, resolution, and history state:

`D(C) = distance(F(render(C), auxiliary, history), reference)`

F is a frozen reconstructor or identity when disabled. Reference uses full-detail
geometry under identical settings. Freeze resolution, AA, and compensation to
isolate geometry. The label `G(C -> C') = D(C) - D(C')` is contextual marginal gain,
not an intrinsic node error. Allow negative G: extra triangles can worsen network output.

Report image, silhouette, depth/normal, and temporal errors separately, even if
training combines them. Separate common coverage and silhouette XOR to prevent
background dilution or metric weights concealing regressions.

### 4.2 Small gain predictor

Start with tabular features and a small MLP; an offline GNN is a later comparison
and should deploy only if gains exceed costs. Candidate inputs:

- Geometry: screen error, area, normal change, thin-structure/contour risk, parent-child face difference.
- Appearance: roughness, texture frequency, available compensation, reconstructor version.
- Time: camera angular speed, predicted screen displacement, valid-history fraction,
  recent switches, disocclusion fraction.
- Context: neighboring LOD, current budget, viewing direction. Costs/page state may
  use separate analytic models.

Predict gain and uncertainty. Compare linear models, tables, and MLPs before claiming
nonlinear learning is necessary. Evaluate actionable nodes near the current cut,
cache static features, filter cheaply, and infer in batches. Count feature extraction,
transfers, and synchronization; avoid a large per-frame network over all source vertices.

### 4.3 Budgets and legality

`min D_final(C_t) + lambda_t * temporal_error(C_t, C_(t-1)) + lambda_s * streaming_stall(C_t)`

Constrain hierarchy legality and complete coverage, executable residency, memory/
transfer budgets, and full frame time including selection/reconstruction. Runtime
uses bounded local split/merge search rather than exact combinatorial optimization.
Rank conservative gain against incremental cost. `G - kappa*U` is a possible
uncertainty-aware score requiring calibration, not a quality guarantee.

GPU time is not linear in triangle count. Isolate the algorithm with triangle
budgets, then fit measured device costs including materials, overdraw, draws, and
reconstruction. Treat zero/negative incremental costs separately from ratios.

Do not draw parents and children together. Commit complete replacements; keep a
valid resident cut and request prefetch when refinement is unavailable. Charge shared
pages as sets rather than repeatedly per node. Explicitly report infeasibility when
the coarsest legal cut exceeds budget or quality-required detail is absent; use an
executable fallback instead of promising all constraints simultaneously.

### 4.4 Time and risk

Use hysteresis, minimum residence time, and a per-frame replacement cap. Invalidate
history after camera jumps and become more conservative. Short camera prediction is
for prefetch/risk, not knowledge of future visibility. Low confidence falls back to
existing screen-error selection. Retain topology, seam, and quality gates; sampled
geometry errors do not imply strict mathematical bounds.

Switches change depth, normals, and historical correspondence, so training must cover
these changes. Hold history equal in single-switch tests; continuous runs maintain
each method's own history rather than borrowing reference history.

### 4.5 Candidate geometry

A separate offline direction learns priorities for legal collapses from multiview
render residuals while retaining topology/attribute checks. Score legal candidates
before attempting arbitrary topology generation. Fix the hierarchy when testing
selection; separately ablate candidate generation and runtime policy to avoid confounding.

## 5. Candidate contribution and claim limits

The proposed combination uses local post-reconstruction intervention labels to learn
marginal hierarchy-replacement benefit and combines history validity, switching risk,
and residency in a deployable selector. Compare prediction before and after
reconstruction. Without a stable difference, no independent reconstruction-aware
value is established; retain the reconstruction-free selection control.

Perceptual LOD, neural simplification, neural progressive meshes, scheduling, and
temporal stability all have precedents. Full papers, strong implementations, recent
literature, and independent gains are needed to establish novelty. Networks cannot
promise recovery of deleted silhouettes, occlusion, or thin rods.

## 6. Validation and stopping rules

1. Freeze the hierarchy and record approach/recede, orbit, fast turn, disocclusion,
   and lighting trajectories. Initially use static geometry with dynamic LOD.
2. Capture paired split/merge renders and an offline reference-image oracle as a
   potential bound, not a deployable policy.
3. If the oracle cannot improve equal-face quality, revisit hierarchy/labels before
   increasing model complexity.
4. Distill with supervised regression/ranking before sequence policies or complex RL.
5. Verify CPU legality/quality before GPU/mobile deployment. Repeated editor threshold
   searches are not automatically a per-frame algorithm.

Baselines: distance LOD, current screen-error/budget selectors, strong contour/material
weights with hysteresis and identical residency, learned selection without reconstruction,
existing selection with the same reconstructor, the full method, and same-data linear/table
models. Compare equal triangles, equal final quality, and equal end-to-end time. Report
actual faces, draws, CPU/GPU times, P50/P95/P99 frame times, memory, transfers, page
misses, inference, quality, switching/flicker, and failures. Measure warm-up and sustained
runs; fix mobile resolution and report thermal throttling.

Split by asset and scene rather than adjacent views. Test unseen materials, rods,
holes, metal highlights, and camera jumps. Report per-asset fine-tuning separately.
Ablate post-reconstruction labels, temporal terms, uncertainty, streaming, and MLP
versus linear prediction. Use paired trajectories, repeats, and intervals. Proceed only
if gains survive strong manual baselines on unseen assets, inference/scheduling do not
consume savings, and average quality does not hide silhouette/flicker regressions.

## 7. Suggested code locations

- `tools/mmtrain/`: intervention capture and gain prediction, separate from image reconstruction.
- `samples/mm_bench.cpp`: paired cut renders, trajectories, timing.
- Near `libs/manymesh/src/LodGraph.cpp`: a policy reusing hierarchy/legal replacement
  rules, retaining the original selector as baseline/fallback.
- `Streaming`: page costs, residency, cancellable prefetch priorities.
- GPU phase: separate feature/score buffers before changing node layouts or formats.

## 8. First equal-face experiment

`mmgeo --oracle-swaps` exports local exchanges: refine one node and merge another
sibling set, then require exactly the baseline triangle count after assembly,
clipping, and deduplication. `tools/mmtrain/lod_oracle.py` captures hierarchy/camera
hashes and evaluates errors before/after reconstruction. Commands:
[mmtrain experiments](tools/mmtrain/README.md).

Two oracles use the same pool. The raw-image oracle selects by directly rendered
coarse error; the reconstruction oracle selects by frozen reconstructed error.
Evaluate both choices after reconstruction to separate redistribution benefit from
the extra benefit of considering reconstruction.

Monkey, Cloth, and Torus each use four views at a 60% face target, Filament desktop
OpenGL, 640x360, same-resolution reconstruction. There are 136 equal-face candidates
and 24 baseline/reference renders. Use Dragon-trained `out/m3/models/tiny_s1_no.pt`,
without history, shadows, or textures. Repeated baseline renders match RGB exactly
on all three assets.

| Asset | Faces per cut | Candidates | Raw oracle median PSNR gain | Reconstructed oracle median gain | Maximum extra reconstruction-aware gain |
|---|---:|---:|---:|---:|---:|
| Monkey | 9,446 | 64 | +0.1885 dB | +0.1508 dB | 0 dB |
| Cloth | 44,986 | 64 | +0.0035 dB | +0.0015 dB | +0.00013 dB |
| Torus | 692 | 8 | +0.4555 dB | +0.4206 dB | 0 dB |

The two oracles choose the same candidate in 11/12 views. Only one Cloth view changes,
by 0.00013 dB. One Torus frame gains 1.315 dB at equal faces; another view's silhouette
XOR worsens from 0.743% to 0.925%. Report RGB and silhouettes together. With identity
reconstruction both oracles have identical selection gains.

Local redistribution merits investigation, especially visible screen impact. In this
reconstructor/asset/pool configuration, post-reconstruction reranking adds almost
nothing. Three assets and at most 16 single-step exchanges per view cannot establish
behavior under other reconstructors, materials, or continuous motion. Further
reconstruction-aware experiments must predefine assets/budgets, vary reconstruction
strength, coverage, and camera paths, and check silhouettes and temporal stability.
Stable extra ranking gain is a prerequisite for training that selector.

Per-candidate results, cameras, hashes, and identity controls:
`out/lod-oracle-pilot/score.json`, `capture.json`, `identity.json`.
Mesa llvmpipe provided quality captures; these are not device performance results.

## 9. Camera-trajectory experiment

Compare 55% and 75% targets on Monkey, Cloth, Torus, Sphere, and Rounded Cube.
Each eight-frame trajectory starts at azimuth 32 degrees, rotates 21 degrees, and
approaches the model, at 384x216. Total: 80 frame positions, 400 equal-face candidates,
160 baseline/reference renders. Budgets share cameras and graph hashes; candidate
counts exactly match each frame's baseline. Torus has no exchange candidates in any
55% frame but remains in the results.

Compute candidate RGB residuals against full-detail frames. Temporal error is mean
squared change of screen-space residual between adjacent frames. Triangle switching
is symmetric difference divided by union of adjacent cuts' triangle sets. Temporal
error detects changing image residual but also residual motion; it neither aligns
surface points nor simulates renderer history.

A dynamic-programming sequence oracle minimizes summed frame RGB MSE over captured
paths. Image-constrained paths permit no frame RGB/silhouette regression and no
adjacent temporal-error regression. Strict paths also constrain triangle switching.
They use complete trajectories and references, so are offline feasibility bounds.
DP matched exhaustive enumeration on 100 small controls.

| Selection | Median PSNR gain, 80 frames | Frames above +0.01 dB | Worse silhouettes | Worse temporal edges | Increased triangle-switch edges |
|---|---:|---:|---:|---:|---:|
| Geometry score | 0 dB | 10 | 11 | 22 | 3 |
| Per-frame RGB oracle | +0.0052 dB | 31 | 2 | 1 | 24 |
| Image-constrained path | +0.0048 dB | 30 | 0 | 0 | 22 |
| Strict path | 0 dB | 20 | 0 | 0 | 0 |

Monkey at 55%, 8,660 faces/frame, is the clearest positive case: one exchange improves
all eight frames, median +0.425 dB, range +0.313 to +0.691 dB, zero triangle switching,
and about 2.7% lower mean temporal error. Rounded Cube's 75% strict path switches only
in the final two frames, gaining +8.42 and +8.57 dB. Its baseline is already about
55 dB; median gain over the trajectory remains zero.

Scale the same frozen Tiny RGB residual by 0, 0.5, 1.0, and 1.5. At each strength,
compare reconstruction-aware and raw-image choices, both scored at that strength:

| Residual strength | Changed selections | Median extra PSNR | Maximum extra PSNR | Extra gain above 0.01 dB |
|---|---:|---:|---:|---:|
| 0 | 0 | 0 dB | 0 dB | 0 |
| 0.5 | 14 | 0 dB | +0.0275 dB | 3 |
| 1.0 | 20 | 0 dB | +0.0609 dB | 4 |
| 1.5 | 23 | 0 dB | +0.0877 dB | 2 |

Stable equal-budget exchanges exist but are unevenly distributed. Amplifying one
network changes more rankings while extra gains remain concentrated in few frames.
Five static meshes, eight samples/trajectory, and limited single-step pools do not
establish cross-asset generalization, temporal reconstruction, or real-time speedup.
[Reproduction](tools/mmtrain/README.md#camera-trajectory-experiment);
paths, counts, transitions, and strength controls: `out/lod-sequence-results/summary.json`.

## 10. Causal prediction with whole-asset holdout

Add opposite-view trajectories starting at 212 degrees, retaining the 21-degree arc,
approach, and 55%/75% budgets. Total: five assets, 20 trajectories, 160 frames, 800
equal-face candidates. Each fold holds out an entire asset, both trajectories and
budgets. Normalize features and fit ridge regression/16-unit MLP on only the other
four assets.

Inputs include split/merge projected errors and bounding-sphere radii, exchanged-face
fraction, budget, and geometry score. Target is RGB PSNR gain minus silhouette
regression penalty, clipped to +/-1 dB. The causal policy computes switching from
the current candidate and previously committed cut, accepts only switching no greater
than falling back to the current baseline, subtracts switching cost, and requires a
0.02 dB acceptance margin. Replay scores/selections use geometry and committed history only.

| Policy | Frames improved >0.01 dB | Frames degraded >0.01 dB | Worse silhouettes | Worse temporal edges | Mean triangle switching |
|---|---:|---:|---:|---:|---:|
| Existing budget selection | 0 | 0 | 0 | 0 | 1.054% |
| Per-frame geometry | 21 | 12 | 11 | 24 | 1.504% |
| Causal geometry | 10 | 14 | 12 | 25 | 1.114% |
| Causal ridge | 15 | 45 | 24 | 56 | 1.075% |
| Per-frame MLP | 12 | 25 | 12 | 48 | 1.721% |
| Causal MLP | 9 | 24 | 12 | 45 | 1.138% |
| Causal true-gain control | 29 | 1 | 0 | 3 | 1.556% |
| Full-trajectory strict oracle | 42 | 0 | 0 | 0 | 1.032% |

Causality reduces MLP switching but whole-asset quality remains weaker than geometry
scoring. Substituting true gain into the same causal rule changes improvements 9->29
and regressions 24->1, identifying prediction as one bottleneck. The strict-oracle gap
also includes future information, objectives, and constraints, not just switching.
Both learned models remain offline.

Monkey's original 55% trajectory supports one stable eight-frame exchange; on the
opposite path even the per-frame oracle gains at most about 0.002 dB. Investigate
coverage, silhouette ownership, and visibility change before further unseen-asset tests.

Replay checked equal faces, whole-asset splits, and causal prefix consistency.
The preceding sequence report reproduces byte-for-byte. Full captures use the then
current development geometry build, with graph/binary hashes in metadata. A clean
parent-commit build separately verified mmgeo, one-frame capture/scoring, and ManyMesh
tests (76 passed, one skipped). Clean-build candidates may differ; numeric results
refer to the saved experimental corpus. Fold weights and frame reports:
`out/lod-predictor-results/held-out.json`.
[Reproduction](tools/mmtrain/README.md#predicting-stable-swaps).

## 11. Visibility features and geometric silhouette labels

Add geometry-derived visibility features on the same 160 frames/800 candidates.
One software depth raster generates baseline fragments. Candidates reuse unchanged
triangles and project only added triangles. Features cover visible/occluded fractions
of added/deleted faces, silhouette changes, affected-region contact with the contour,
and relative depth. Candidate/baseline vertex spaces and face counts match. Inputs
use only current camera and geometry.

Ten incremental depth buffers exactly match full software rasterization. Compared
with Filament unlit coverage masks, baseline median IoU is 99.98%, minimum 99.90%.
Earlier black-background RGB masks misclassified dark surfaces. Among 800 candidates,
RGB and geometric masks disagree on whether silhouette error worsens in 71 cases:
54 detected only geometrically, 17 only by RGB. Interpret sections 8-10 silhouettes
as RGB proxies.

Cross two inputs and two labels using identical holdouts, network, and parameters.
Full-detail independent geometric masks supply supervision/evaluation only. Feature
files match byte-for-byte before/after labeling; disabling visibility/geometric labels
also reproduces the earlier geometry control byte-for-byte.

| Silhouette label | MLP input | Per-frame improved/degraded | Causal improved/degraded | Causal mean switching |
|---|---|---:|---:|---:|
| RGB mask | Geometry | 12 / 25 | 9 / 24 | 1.138% |
| RGB mask | With visibility | 24 / 22 | 17 / 32 | 1.885% |
| Geometric mask | Geometry | 24 / 18 | 14 / 9 | 1.109% |
| Geometric mask | With visibility | 13 / 23 | 7 / 21 | 1.391% |

Counts use +/-0.01 dB versus the existing budget selector. All four overall medians
are zero. Under geometric labels these visibility features hurt both MLP policies.
Geometry-only causal MLP with new labels improves 14 and degrades 9 frames but worsens
17 silhouettes, versus 9 for causal geometry scoring. Retain geometric labels for
evaluation; visibility remains an offline ablation. Same assets/paths make this a
paired ablation, not independent testing; runtime overhead needs separate measurement.
[Commands](tools/mmtrain/README.md#visibility-feature-ablation); reports/weights:
`out/lod-visibility-results/{geometry-control,held-out,geometry-silhouette,visibility-silhouette}.json`.

## 12. Equal-face exchanges scored with local refinement references

Budgeted view-dependent LOD dates to Funkhouser/Sequin 1993. Lindstrom/Turk 2000 use
pixel differences for offline simplification and discuss multilayer fragments/local
redraw for collapses. Charalambos 2006 includes visible pixels in HLOD refinement.
NVIDIA 2021 uses differentiable rendering to generate appearance-preserving assets.
Budget, visibility, and image error already have clear precedents:
[Adaptive Display](https://pixl.cs.princeton.edu/pubs/Funkhouser_1993_ADA/index.php),
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf),
[Coherent HLOD Refinement](https://diglib.eg.org/server/api/core/bitstreams/ad004952-4a0b-4a6e-a99c-6ed56d9a2c4a/content),
[Appearance-Driven Simplification](https://research.nvidia.com/publication/2021-04_appearance-driven-automatic-3d-model-simplification).

Epic's SIGGRAPH 2021 Nanite material notes that scalar object-space error lacks
direction and projected surface angle, potentially overallocating at grazing angles.
This study redistributes within an existing hierarchy and inherits its partitions.
Aggregate foliage coverage/overdraw is separate; Epic's 5.8 documentation includes
Preserve Area and voxel Nanite Foliage:
[Nanite Deep Dive, Glancing Angle Surfaces](https://advances.realtimerendering.com/s2021/Karis_Nanite_SIGGRAPH_Advances_2021_final.pdf),
[Working with Nanite](https://dev.epicgames.com/documentation/unreal-engine/working-with-naniteenabled-content),
[Nanite Foliage](https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-foliage).

Construct one shared reference for all current equal-face exchanges: refine touched
baseline nodes by one or two levels and keep other baseline geometry for occlusion.
Score candidate silhouette/relative-depth improvement against this reference, sharing
fragments for common triangles. Scoring reads only current camera/hierarchy; full
references and geometric masks independently measure selected paths. Hypothesis:
a small number of extra hierarchy nodes provides useful directional/occlusion information.

Use identical candidates, faces, causal switching, and frame logs. Compare one/two
reference levels and silhouette-only versus silhouette+depth. Causal choices use
current scores and the previously selected cut. Proxy references may favor refined
nodes, especially where matching a candidate's refinement; judge via independent full
references. Software raster uses two-sided geometry/single samples as in section 11.
Production GPU selection, streaming, and material costs are unmeasured.

First replay five development assets, two budgets, two starts: 20 paths, 160 frames,
800 candidates. With +/-0.01 dB thresholds and identical causal constraints, geometry
improves/degrades 10/14 frames, silhouette-only proxy 11/1, silhouette+depth 30/5.
The last averages +0.256 dB, median zero, zero geometric-silhouette regressions,
six worse temporal edges. These are development assets, not independent evidence.

One/two levels choose identical paths. Candidate frames average 5.56 exchanges.
Median shared raster size is 6,765 triangles versus 54,872 summed across independently
rasterized cuts. One-level reference adds a median 117 triangles beyond the candidate
union. Python median scoring is 116 ms including both reference levels and all
candidates; no real-time claim follows.

New Pirate, Shader Ball, and Lucy captures use start 118 degrees and 42-degree arcs,
24 frames. Pirate has no single exchange in eight frames. Shader Ball/Lucy each have
eight frames and 96 candidates. Geometry has no changes beyond +/-0.01 dB. Silhouette-only
proxy improves/degrades 2/1 frames; adding depth gives 3/2, mean +0.103 dB, median zero.
Lucy path mean is +0.323 dB, Shader Ball -0.016 dB; its two regressions are -0.075 and
-0.051 dB. Depth paths have zero silhouette regressions and two worse temporal edges.
Full-reference per-frame strict selection improves 11 frames without regressions,
showing remaining opportunity.

On new candidate frames, shared median raster size is 33,589 versus 469,484 summed
independent triangles; median scoring is about 631 ms. Reports:
`out/lod-proxy-results/pilot.json`, `out/lod-proxy-results/unseen.json`. Both reference
depths again select the same paths. Useful directional/occlusion signals coexist
with missing equal-face pairs, material effects, and high cost. No network is trained
here and no production selector reaches real time.

Pirate at 55% selects 46 DAG roots, 2,822/5,010 triangles, already its coarsest cut.
The hierarchy floor, not simply absent paired exchanges, prevents further reduction.
Audit hierarchy compressibility separately from runtime allocation.

FastMesh and Hoppe already provide view-dependent multiresolution/refinement;
appearance-driven simplification already optimizes image appearance/materials.
Local render error, viewwise complexity, normals, and materials are not firsts.
The narrow question is shared local references for legal hierarchical redistribution
under a hard triangle budget, cross-frame costs, and limited GPU work. Section 12
only tests single exchanges; section 13 explores combinations:
[FastMesh](https://escholarship.org/uc/item/9s30k0b0),
[View-Dependent Refinement](https://hhoppe.com/proj/vdrpm/),
[Appearance-Driven Simplification](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/).

## 13. Composite candidates, interactions, and learned screening

`--oracle-composites N` exports one/two refinements with one/two ancestor merges
from a legal cut, balancing face changes and revalidating selected nodes and final
faces after assembly, clipping, and deduplication. A separate switch preserves
single-exchange captures. Proxy scoring reads selected nodes and identifies all
current descendants covered by ancestor merges. The five-asset controls retain old
data; new captures below are exploratory.

At 75%, four Lucy and four Shader Ball views each sample four single/eight composite
candidates: eight frames, 96 candidates. Full-render winners are composite in five
frames: Lucy adds +0.097/+0.494 dB beyond sampled single winners; Shader Ball adds
+0.750/+0.591/+0.408 dB. Unequal sample counts mean opportunity, not equal-search-cost
superiority. Causal geometry/proxy replay both retain the baseline no-op.

For 64 composites, build each constituent refinement/merge separately and use the
same local reference with fixed whole-image denominator for coverage/depth loss.
Maximum absolute composite gain minus summed individual gains is 3.4e-21, floating-point
noise. No measurable nonadditive occlusion appears in this sample; it cannot support
necessary joint interaction modeling. This covers current cameras, two-sided single-sample
masks; materials and temporal response remain separate.

Causal local-reference Lucy mean is +0.126 dB (two frames above +0.01, one below -0.01);
Shader Ball mean +0.007 dB (one improvement, zero regressions). Geometry never exceeds
+/-0.01 dB. Python median costs for all candidates are 1.56 s Lucy/3.08 s Shader Ball.
Sparse pixel recomputation exactly matches full depth in two real scenes, but costs
531 versus 539 ms and 136 versus 119 ms; no reliable speedup, so it did not replace scoring.

Whole-asset-held-out MLP replay over the old five plus these two assets retains baseline
on all four Lucy frames and loses about -0.008 dB on one Shader Ball frame. With reference
images used only to measure screening potential, top-eight MLP candidates recover four
of eight full-pool winners; geometry recovers six. This MLP is unsuitable for pruning
expensive scoring. Reference-based final selection is an upper bound, not runtime policy.

Scores, paths, interactions, and screening: `out/lod-composites-075/score.json` and
`out/lod-composites-results/`. Single and at-most-two-edit sampled pools constrain scope
by assets, views, materials, resolution, and counts. Next experiments should jointly
measure pool coverage, material/normal error, and actual GPU scoring cost.

## 14. Fixed DAG group size and budget reachability

Rebuild Pirate with `--dag-group` 2, 4, 8, 16, otherwise fixed input/options/budget.
Its 5,010 baseline triangles yield 168/159/158/156 nodes, 58/50/46/60 roots, and selected
2,810/2,958/2,822/3,186 triangles (56.09%/59.04%/56.33%/63.59%). All are root cuts;
55% was unreachable in these historical builds. Larger groups do not consistently
lower the floor; 16 is substantially worse.

Lucy group 2/8 builds 957/810 nodes and 97/75 roots. Both select 18,396/33,446 faces,
55.00%. Group 8 worst selected screen error is 6.07 px versus group 2's 4.90 px.
Fewer hierarchy nodes changes structure/error without necessarily changing budget faces.

This rejects simply enlarging fixed groups to solve the floor; no one parameter is
supported. Pirate is a reachability failure, Lucy is a counterexample to universality.
A possible next comparison builds multiple legal parents under identical offline work,
forming root-face/error/build-cost Pareto frontiers against fixed groups. Every parent
still passes topology/attribute/geometry gates. Acceptable cross-asset gains remain
unverified. Compare progressively refined meshes, FastMesh, and Nanite explicitly;
hard budgets/multiple candidates alone establish no novelty.

Outputs: `out/dag-group-audit-{2,4,8,16}/lod_graph.json`,
`out/dag-group-lucy-{2,8}/lod_graph.json`. Inputs are repository meshoptimizer demo
Pirate/Lucy, default view/screen/gates/program settings. This is one deterministic
two-mesh sweep, without broader cameras/assets, memory, or runtime measurements.

## 15. Same-material grouping across submeshes

Test whether submesh labels overconstrain same-material adjacency by removing only
`submeshId` equality, retaining shared-vertex adjacency and all geometric/topological/
normal/UV gates. Pirate and Lucy at group 8 match baseline field-for-field:
158/7/46 and 810/7/75 nodes/levels/roots; 2,822/5,010 and 18,396/33,446 selected faces;
unchanged maximum selected errors. Neither produces cross-submesh candidates, so the
code change was discarded. It does not explain Pirate's floor. This excludes one
simple hypothesis on two meshes, not universal usefulness; real future candidates
need material, interface-continuity, and node-output semantic checks.

## 16. Budget, view error, and coherence precedents

Gobbetti/Bouvier optimize per-frame quality of multiple multiresolution triangle meshes
under rendering time constraints, covering core budget allocation:
[Time-Critical Multiresolution Rendering](https://doi.org/10.1016/S0010-4485(00)00068-3).
Hoppe supports continuous arbitrary-mesh resolution, view-frustum/orientation/screen-error
refinement, and temporal coherence:
[Progressive Meshes](https://hhoppe.com/proj/pm/),
[View-Dependent Refinement](https://hhoppe.com/proj/vdrpm/).
[FastMesh](https://escholarship.org/uc/item/9s30k0b0) supplies real-time view-dependent
arbitrary triangle updates with conservative bounds.
[NVIDIA appearance-driven simplification](https://research.nvidia.com/publication/2021-04_appearance-driven-automatic-3d-model-simplification)
jointly optimizes mesh and shading with differentiable image losses, including LOD.

Hard faces, per-view allocation, coherence, and image error are not independent novel
claims. A still-unestablished combination is current-frame bounded image evaluation
plus measured runtime costs for stable strict-budget cuts of an existing quality-valid
ManyMesh DAG, explicitly declaring infeasible hierarchy floors. Compare representation,
candidates, error, cost, and scope through implementations and equal-budget baselines.
Slow proxies, absent measured nonadditivity, weak learned screening, and hierarchy
floors currently prevent a SIGGRAPH-level claim.

## 17. More direct budget-plus-image-quality precedents

Jehaes et al., GRAPP 2008, use objective image quality, progressive-mesh quality/cost
Pareto curves, and frame budgets to select better representations:
[Objective Quality Selection for Hybrid LOD Models](https://www.scitepress.org/Papers/2008/10991/).
[US patent 12,008,716](https://patents.justia.com/patent/12008716) describes submesh-group
hierarchies, budget-specific LODs, compound child LODs, and per-frame triangle-budget
fidelity benefit/cost selection. Patent text is not a substitute for academic review,
but composite pools, Pareto choice, and benefit/cost alone are insufficient.

Do not list fixed-DAG image-aware redistribution as a SIGGRAPH contribution without
structural differences and reproducible gains. A more falsifiable question might be
reachability certificates and offline strict-topology hierarchy repair without worse
build cost/screen error, but it had no supporting implementation/result at this point.

> Correction, 2026-11-13: section 14 Pirate results predate `candidateTopologyWelded`.
> That fix compares group baselines using the candidate's own topology measurement.
> At the same defaults the root cut becomes 2,756/5,010 = 55.01%, making the 55%
> target reachable under the selector's budget criterion. The larger-group conclusion
> remains; the old claim that Pirate cannot reach that target no longer holds.

## 18. Spatial bisection retry after group failure

Test multiple legal parents without exhaustive Pareto search: spatially split a
quality-rejected multimember group, recursively retry halves (8->4->2), retaining
all topology/attribute/geometry/boundary gates. Extra work occurs only on failed groups.
Same-machine Release, default `--split-charts 1`, `--dag-group 8`, `--target-ratio`:

| Asset/target | Topology-baseline fix only | With bisection | DAG build |
|---|---|---|---|
| Pirate 55% | 2,756 faces (55.01%), worst 19.62 px, 45 roots | 2,756 faces, worst 11.93 px, 29 roots | 1.20 -> 1.98 s |
| Pirate 30% | 2,658 faces (53.05%), 22.32 px | 2,552 faces (50.94%), 22.32 px | 1.16 -> 1.95 s |
| Lucy 55% | 18,396 faces (55.00%), 5.89 px, 52 roots | 18,396 faces, 5.38 px, 18 roots | 5.91 -> 9.06 s |
| Lucy 30% | 16,560 faces (49.51%), 14.35 px | 16,044 faces (47.97%), 12.04 px | 5.98 -> 9.06 s |
| Monkey / Torus / Sphere | -- | Bit-identical nodes, faces, errors | -- |

Retries add intermediate parents on two failure-heavy assets, improve same-budget
screen error, and lower the 30%-target face floors by 2.1% Pirate/3.1% Lucy. Assets
with only 1-3 roots are bit-identical. Failure-heavy builds cost about 1.5-1.65x.
Selected boundary/non-manifold/duplicate/degenerate/flipped counts remain unchanged.

This supports possible offline repair gains without relaxed gates, but covers two
small assets, one camera/parameter set, no large scenes/material/memory/device costs.
Reproduce with `mmgeo <mesh> --mode dag --dag-group 8 --target-ratio 0.55` and inspect
`budget reached / unreachable`. Historical ManyMesh suite: 82 cases, 81 passed,
one skipped (the old wording counted all cases as passed).

## 19. Laptop proxy costs and visual review

Only Python experiment tools changed in this round. Reuse section 12's eight assets,
23 paths, 184 historical frames with equal submitted candidate faces; no new independent
test set. Machine: current Windows/Intel laptop, NumPy 2.5.4, CPU PyTorch 2.7.1.

Shared-depth scoring resolves the common intersection of candidates, two reference
levels, and optional interaction cuts once, then takes maximum depth with each
remainder. Common triangles are already projected once; this removes repeated depth
reduction. Duplicate cuts share read-only results. All 184 paths, frame quality, and
switching metrics match the old implementation, as do eight composite-frame paths and
interaction differences. Random occlusion controls include equal depth, empty fragments,
no common triangles, and occluders shared by candidates but absent from references.
Without candidates both reference levels equal baseline, so an independently tested
early return skips rasterization but retains input reading/validation.

Separate full runs reduce total scoring 14.47->13.17 s but increase median 28.67->32.74 ms;
these opposite trends do not show universal speedup. Same-process warmed alternating
order, three measurements, on the first frame:

| Asset | Independent resolve median ms | Shared resolve median ms |
|---|---:|---:|
| Monkey | 42.09 | 34.66 |
| Cloth | 219.02 | 170.98 |
| Torus | 10.26 | 10.30 |
| Pirate, no candidates | 6.84 | 12.35 |
| Shader Ball | 215.78 | 163.31 |
| Lucy | 117.59 | 126.48 |

These precede the final no-candidate early return. Pirate reflects old prototype
overhead; both current paths return immediately. Shared resolve can still regress,
so `--shared-depth` remains opt-in. Timings include proxy construction, software
raster, and scoring, excluding OBJ loading, validation, and Filament rendering.
No phone frame times, power, or GPU implementation were measured.

Reduce proxy raster 384x216->192x108 while retaining original independent reference
images/geometric labels. For `proxy1_surface_causal`, with +/-0.01 dB thresholds:

| Raster/resolve | Median scoring ms | Improved frames | Degraded frames | Worse silhouettes | Worse temporal edges |
|---|---:|---:|---:|---:|---:|
| 384x216 / original | 28.67 | 33 | 7 | 0 | 8 |
| 384x216 / shared | 32.74 | 33 | 7 | 0 | 8 |
| 192x108 / shared | 16.68 | 37 | 14 | 12 | 17 |

Lower resolution misses small contour differences. Mean PSNR gain falls +0.236->+0.195 dB;
both medians remain zero. `--proxy-height` stays an ablation, not a speedup replacing
quality evidence.

Visual review selects each asset's best/worst frame over all paths, including no-ops.
Keep original frames and uniform 4x exposure, common crops, 2x nearest-neighbor display,
full detail/baseline/selected, and 8x absolute RGB error. Monkey +0.662 dB reduces eye-region
error; opposite-view -0.481 dB worsens crown highlights without changing silhouettes.
Shader Ball -0.075 dB mainly changes local shading with small whole-image visual difference.
Cloth folds/hem have no obvious new damage in these small images. Lucy's dark surfaces
are near black, preventing reliable detail judgments; it does not pass visual review.
These 216-pixel-high debug images cannot replace high-resolution, multilighting,
continuous publication video. Application control blocked attempts to capture new
high-resolution renderer evidence.

Saved [frame results/summary](tools/mmtrain/results/proxy-grid-20261113/summary.json),
[alternating timings](tools/mmtrain/results/proxy-grid-20261113/paired.json),
[Monkey positive/negative panels](tools/mmtrain/results/proxy-grid-20261113/monkey-7b754119.png).
Hashes identify retained historical captures/reports; commands are in `tools/mmtrain/README.md`.

### Learned-method tradeoffs and paper positioning

Three external directions remain comparisons; deployment judgments are not local benchmarks:

- [MeshCNN, SIGGRAPH 2019](https://ranahanocka.github.io/MeshCNN/) uses learned edge-collapse
  pooling for analysis. Edge features may help, but analysis success does not prove
  rendered appearance or our UV/boundary/streaming contracts.
- [Neural Mesh Simplification supplementary material, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/supplemental/Potamias_Neural_Mesh_Simplification_CVPR_2022_supplemental.pdf)
  uses a lightweight 64-dimensional representation and discusses collision/intersection/
  overlap losses. It is an offline baseline; topology, attributes, and million-face
  time/memory need testing. A paper's lightweight label does not establish phone suitability.
- [Appearance-Driven Simplification, EGSR 2021](https://research.nvidia.com/publication/2021-04_appearance-driven-automatic-3d-model-simplification)
  jointly optimizes geometry/materials and emits ordinary meshes/textures. Separate
  offline optimization from device rendering and cost both; differentiable optimization
  is not itself lightweight mobile inference.

Whole-asset regressions of this repository's 16-unit MLP appear in sections 10-11;
there is no evidence to enable it by default. This round establishes proxy cost
tradeoffs and small-raster failure boundaries, engineering/ablation evidence rather
than SIGGRAPH novelty. Shared fragments, image error, and LOD have precedents in
sections 12/17. The historical next hypothesis required frozen, unseen, large-scene,
multimaterial strict-hierarchy-repair comparisons with build/render/memory costs and
visual failures. Adding deep learning alone is not a contribution. Current research
direction is tracked separately in [MANYMESH.md](MANYMESH.md).
