# SIGGRAPH 2027 research direction

Updated 2026-11-25. This is a research plan, not a paper draft or novelty claim.
The differentiable candidate remains untested; the cited work is a bounded map
for verification, and a search that finds no paper is not evidence that none exists.

## SIGGRAPH 2027 submission constraints

The official schedule now lists the submission form and author list for 21
January 2027 at 22:00 UTC, the paper and supplemental-material deadline for 28
January at 22:00 UTC, and the checksum-based file upload, conflicts, expertise,
and author review-commitment deadline for 29 January at 22:00 UTC. Peer-reviewed
papers published after 14 December 2026 generally will not trigger a missing-
comparison rejection, but work that influenced the submission must still be
cited. Recheck the official call for changes
before preparing a submission. [Technical Papers call](https://s2027.siggraph.org/program/technical-papers/)

SIGGRAPH uses one Technical Papers submission track, with Journal or Conference
acceptance decisions. A Conference Paper must contain an important new idea,
fit within nine pages excluding references, and is considered after rebuttal
when the main weakness is validation or comparisons. It is not a lower-novelty
fallback. [Review process and paper types](https://s2027.siggraph.org/program/technical-papers/)

The double-blind review period starts 14 January 2027 and continues until
conditional acceptance or rejection. The current public ManyMesh repository
identifies its owner, so it must not be linked as the submission's code/data
repository. Submit anonymized code and data as supplementary material (up to
500 MB) when possible. Only if an external link is necessary, prepare a
separately anonymous, timestamped repository before the deadline and keep it
unchanged after submission. Do not publicly list or promote the submission
during the review period. A direct identity-revealing link in the paper or
supplement can cause desk rejection. [Official anonymity policy](https://s2027.siggraph.org/anonymity-policy/)
and [reviewer instructions](https://s2027.siggraph.org/technical-papers-reviewer-instructions-ethics/).

Treat 13 January as the internal submission-readiness decision: proceed only
if there is a defensible contribution and completed supporting evidence; if
not, do not submit a plan or benchmark-only report as a method paper. Any later
public-repository or publicity step during review must follow the anonymity
policy.

## Candidate and decision

The only current method hypothesis is **offline optimization of a triangle-mesh
cluster hierarchy for its final antialiased or upscaled image**. Fit geometry at
the screen scale where each level is used, model jittered sample accumulation
and resolve during optimization, and preserve the hierarchy's legal cuts,
shared boundaries, and transitions. The result must beat strong alternatives
after real reconstruction, not only its differentiable surrogate.

The frozen experiment is a fixed-topology placement control built on
nvdiffmodeling, not a faithful reproduction of Hasselgren et al.'s protocol. It
uses a 2x supersampled nvdiffrast render with edge antialiasing enabled and
MSAA disabled, unlike Hasselgren et al.'s MSAA-assisted shape and appearance
prefiltering setup. Their paper does not state that MSAA is used in every
simplification experiment. The control also does not optimize through the final
hardware 4x MSAA or an upscaler. A
result on two reused assets can accept or reject this configuration only; it
cannot establish asset generalization or falsify differentiable fitting more
broadly.

The unoptimized 50%-retention ManyMesh cut has now been screened on 21 unique
Poly Haven meshes across six classes, at exact face counts against
border-preserving QEM and meshoptimizer LockBorder. It loses on LDR-FLIP, PSNR,
SSIM, and silhouette XOR in both native and 4x MSAA modes; paired 95% intervals
over 16 source-collection groups exclude zero. This is a strong negative result
for the current cut and a necessary control for any optimization. It does not
test the differentiable hypothesis. The scored cohort is no longer available
as an untouched test set for a method developed in response to this result.
See the [full protocol and per-model results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md).

This combination has substantial prior art. Hasselgren et al. already optimize
mesh shape and appearance from image-space references for simplification and
LOD. For their shape-and-appearance prefiltering application, they use MSAA
during optimization to improve silhouette visibility gradients while fitting
a supersampled reference; the paper does not state that every simplification
experiment uses MSAA. Their final 1-spp images are un-antialiased unless stated
otherwise. Therefore neither differentiable image-space simplification,
scale-specific fitting, nor MSAA-assisted silhouette optimization is a
contribution here. A viable distinction would need to show
that optimizing for a specified *final reconstruction operator* (for example,
temporal accumulation or an upscaler) gives a repeatable gain over the same
operator used as a baseline, while preserving legal DAG cuts and boundaries.
This remains untested and may not be novel.
([EGSR 2021 full paper](https://users.aalto.fi/~laines9/publications/hasselgren2021egsr_paper.pdf),
[NVIDIA project page](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/)).
de La Gorce et al. had already derived image-loss gradients that account for
changing visibility at triangle-mesh occlusion boundaries, using antialiased
residuals and occlusion forces for articulated mesh tracking. The CPU C-based
[DEODR renderer](https://github.com/martinResearch/DEODR) exposes this family
of vertex-image gradients through PyTorch. This closes silhouette-gradient or
CPU differentiable mesh fitting as novelty claims; it is only a possible
exploratory backend, not the frozen Filament/PBR/MSAA comparison. Its documented
limits include no GPU, multiple lights, Phong shading, or shadows. See the
[PAMI 2011 paper](https://www.cs.toronto.edu/~fleet/research/Papers/handTrackerPAMI.pdf)
and the [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).
Dou et al.'s [Differentiable Micro-Mesh Construction (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.pdf)
is another direct precedent: it optimizes displacement-based micro-mesh geometry
against multi-view image loss and uses image-space improvement to select
per-triangle adaptive subdivision levels. Its representation is not a standard
cluster-DAG triangle mesh, its evaluation holds out views rather than assets,
and it does not report fitting through final MSAA or temporal upscaling. This
leaves only a narrow comparison question; it does not establish novelty.
DMesh++ further narrows broad claims about image-driven mesh optimization: it
reconstructs changing-topology meshes from multi-view image loss and uses
pixel-area antialiasing in a custom CUDA renderer for geometry visibility
gradients. It does not simplify a given authored mesh into a cluster-DAG LOD or
evaluate an output through a separate final MSAA/upscaler pipeline, but any
ManyMesh method must be distinguished from this reconstruction formulation
([ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/html/Son_DMesh_An_Efficient_Differentiable_Mesh_for_Complex_Shapes_ICCV_2025_paper.html),
[supplement](https://openaccess.thecvf.com/content/ICCV2025/supplemental/Son_DMesh_An_Efficient_ICCV_2025_supplemental.pdf)).
Choi et al.'s [LTM (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Choi_LTM_Lightweight_Textured_Mesh_Extraction_and_Refinement_of_Large_Unbounded_CVPR_2024_paper.pdf)
is a closer simplification-to-rendering precedent than reconstruction-only
methods. After vertex-clustering and geometry-aware QSlim decimation, LTM uses
nvdiffrast to optimize per-vertex deformation and a neural appearance field
through image loss, with Laplacian, normal-consistency, and high-resolution
normal regularizers. It also subdivides high-displacement faces and re-decimates
during training. LTM targets meshes extracted from captured unbounded scenes,
not a supplied authored mesh hierarchy, and does not optimize through a
specified final MSAA or upscaler. Its 1080p browser result is 212 FPS / 115 MB
on a 2020 MacBook Pro M1, not a phone result. This closes broad claims to
render-guided simplification, vertex optimization, and refinement after
simplification. Any ManyMesh distinction must be narrower than those operations
and be tested against an LTM-style fixed-LOD control; a cluster DAG and
post-reconstruction operator are comparison questions, not novelty by
themselves. See the [full prior-art audit](docs/manymesh/siggraph-prior-art-screen-20261123.md).
V3DG already fits each level of a clustered hierarchy differentiably, although
it uses 3D Gaussian primitives ([SIGGRAPH 2025 paper](https://arxiv.org/html/2505.06523)).
HLOD ASAP's abstract and publisher preview describe a binary progressive-mesh
hierarchy with an internal PM and neighbor-indexed boundary PMs per node,
built by edge collapses and recursive node merges. It compares against
Quick-VDR's locked boundaries and claims better triangle distribution and
reduced popping ([publisher article page](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380),
[publisher preview](https://www.researchgate.net/publication/403799777_Construction_of_clustered_HLOD_with_As-Simplified-As-Possible_boundaries),
[Eurographics record](https://doi.org/10.1111/cgf.70380)). The preview does not
expose full methods, tables, or quantitative results. This is direct prior art
for simplified, crack-free cluster boundaries, so boundary consistency and a
binary-tree-to-DAG change alone are not a distinction. Quick-VDR
already provides clustered progressive meshes and dependency-constrained,
crack-free refinement ([full paper](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content)).
Li's SIGGRAPH Asia 2022 poster already describes parent-child vertex
interpolation for crack- and popping-free adaptive multiresolution rendering
([official poster abstract](https://www.siggraph.org/wp-content/uploads/2023/01/SA-22-SIGGRAPH-Asia-2022-Posters.html)).
His i3D 2023 poster paper gives a detailed public account: Euclidean grid
partitioning, octree-like neighbor merges, parent-child displacement bounds,
viewpoint-dependent LOD selection, and continuous parent-child vertex blending
([full poster paper](https://i3dsymposium.org/2023/posters/rui_li_paper.pdf),
Sections 2–4). Its table reports a 60.0-million-triangle temple source and
82.4 million triangles across the resulting hierarchy, constructed in 35 s;
the paper separately reports 170 fps on an integrated-GPU desktop. These are
hierarchy-storage and desktop viewer results, not equal-face simplification
results.
Li's CVMP 2023 paper describes view-dependent adaptive HLOD construction by
grid partition, neighboring-node merges and simplification, child-parent vertex
relations, and coarse-to-fine traversal with interpolated crack-/popping-free
transitions ([official proceedings abstract](https://www.siggraph.org/wp-content/uploads/2023/12/CVMP-23-Proceedings-of-the-20th-ACM-SIGGRAPH-European-Conference-on-Visual-Media-Production.html),
[author-associated implementation repository](https://github.com/BigRayLee/3DViewer)).
The ACM full paper returned HTTP 403 during this review, so these method details
are from the official abstract and conference brochure; the related i3D poster
is not substituted for the CVMP paper. Repository-to-paper implementation
correspondence has not been audited. Together with
Quick-VDR and HLOD ASAP, this closes hierarchy construction, parent-child
mapping, view-dependent selection, crack-free boundaries, and transition
stability as standalone contributions. Hierarchy fitting, per-level
differentiable fitting, and scale-aware appearance likewise are not contributions
on their own. Novelty is not established.

The remaining experiment question is whether fitting a hierarchy to a specified
final reconstruction operator gives a measurable advantage over applying the
same operator to unoptimized geometry, beyond the MSAA-assisted optimization
already used by Hasselgren. DMesh++ also optimizes changing mesh topology from
multi-view image losses and uses a CUDA pixel-coverage antialiasing renderer to
provide geometry visibility gradients. It reconstructs meshes from observations,
not a given authored asset's cluster-DAG simplification, and does not test a
final hardware MSAA/upscaler output. A useful ManyMesh method would still need to
retain legal cuts and boundaries and beat that broader family of image-driven
mesh optimization methods in the narrower existing-asset LOD task. This is an
untested comparison, not a located research gap or novelty claim. It is much
narrower than “LOD for upscalers”: classic silhouette-aware simplification,
silhouette clipping, budgeted/predictive LOD selection, perceptual silhouette
and transition models, and neural prediction of image error for shading-rate
control have direct precedents. The [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
records the initial sources, what was checked, and what still requires full-paper
review; it is not an exhaustive literature search.

| Priority | Direction | Current disposition |
|---|---|---|
| 1 | **A+B: reconstruction-conditioned hierarchy optimization** | Weak, untested hypothesis. First evaluate the frozen nvdiffmodeling-based placement control; if it passes on reserved views, run an asset-held-out study before any custom DAG optimizer. The control is not a reproduction of Hasselgren et al.'s MSAA-assisted protocol. |
| 2 | **C: tile-GPU cost model and selection** | Systems-analysis fallback if a physical tile-based device and profiling counters are available. A screen-tile count alone is only a proxy. |
| 3 | **D: rate-aware DAG construction** | Parked. Meshlet compression is crowded; reopen only with full-stream byte and decode comparisons against meshoptimizer, Draco, Kuth et al., and AMD DGF. |

The existing silhouette controls do not justify reopening silhouette-weighted
geometry as the main method. A 64-view contour-priority QEM control showed
+0.167 dB mean PSNR on seven reused development assets, but mixed FLIP and no
reliable gain after AA; fixed-topology contour fitting regressed on two of
three assets. See the [CPU screen](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md),
[AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md), and
[fixed-topology fit](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md).

A separate Mitsuba CPU projective-silhouette fit lowered training loss on two
reused Khronos assets, but LDR-FLIP worsened on both 24-pair reserved-view
sets. PSNR changed by +0.0429 dB for the candle holder and -0.0920 dB for the
shoe. This is mixed evidence from a silhouette-only objective, not an asset-
held-out or final-AA result; it does not establish a silhouette method. See the
[full report](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md) and
[pinned CPU workflow](.github/workflows/manymesh-projective-cpu.yml).

A post-hoc attribution on the already-scored 21-model cohort further weakens a
silhouette-dominance premise: the XOR region contains 31.0% of ManyMesh squared
grayscale error without AA (95% source-group bootstrap CI 27.4%-34.8%) and
16.3% after 4x MSAA (13.7%-19.1%); none of the 16 groups exceeds 50% in either
mode. 4x MSAA removes 38.8% of ManyMesh's native squared error, versus 58.0%
for QEM and 67.1% for meshoptimizer; for ManyMesh the reduction splits into
20.7 percentage points inside the XOR mask and 18.1 points outside. This
diagnostic's paired group contrast finds 19.2 pp more total error removed for
QEM than ManyMesh (95% unadjusted CI 14.3-23.7) and 28.3 pp more for
meshoptimizer (23.1-33.0). The QEM difference is almost entirely outside the
XOR region: -0.3 pp inside (-1.5 to +1.0), +19.5 pp outside (14.8-23.6).
These are post-hoc results on the same flat-grayscale fixed-view cohort, not
independent confirmation or a perceptual metric. The historical 68.3% single-
view Monkey value used a DAG cut as reference. Do not motivate a paper with a
universal claim that silhouette pixels dominate error. Any method should target
whole-image quality after AA and beat these controls. See the full
[21-model attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md).

Silhouette-aware LOD and clipping have direct precedents in
[Luebke–Erikson (1997)](https://dl.acm.org/doi/10.1145/258734.258847)
and [Sander et al. (2000)](https://hhoppe.com/silclip.pdf). Luebke's [1998
dissertation](https://www.luebke.us/publications/pdf/dissertation.pdf) details
the 1997 view-dependent method: it uses a cone-of-normals/view-cone test to
identify possible silhouette nodes, assigns them a tighter screen-space
threshold than interior nodes, collapses back-facing nodes, and also describes
minimizing screen-space error under a triangle budget. This directly closes
silhouette-weighted budgeting as a novelty claim. Image-driven
simplification also predates this project ([Lindstrom–Turk (2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)).
Budgeted LOD selection also predates this project: see
[Funkhouser–Séquin (1993)](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/funkhouser93.pdf)
and [Mason–Blake (1997)](https://doi.org/10.1111/1467-8659.16.3conferenceissue.21).
Funkhouser–Séquin optimize scene-level representation and rendering choices
under a target frame time. Mason–Blake formulate hierarchical LOD selection
with shared representations and a resource budget. The authors' [corrected
1999 technical report](https://people.cs.uct.ac.za/~edwin/MyBib/1999-mason.pdf)
formulates this as a hierarchical multiple-choice knapsack problem and targets
predicted frame time while maximizing estimated perceptual benefit; it also
states that it corrects an important error in the 1997 paper. The prior-art
screen records which primary texts were read and which claims still rely on
abstracts or previews.
Learned perceptual-error prediction exists for shading-rate selection, not mesh
topology ([Cardoso et al.](https://doi.org/10.1145/3522625)). Arm documents
Neural Super Sampling for the Mali G2-Ultra NX
([Arm product page](https://www.arm.com/products/silicon-ip-multimedia/gpu/mali-g2-ultra-nx));
this is not a baseline for unrelated phone hardware. Arm has also demonstrated
Nanite on a Mali-G925 phone, so “Nanite-like geometry on mobile” is not a
novelty claim ([device and test details](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/mori-to-nanite-billions-of-triangles-on-mobile)).
Meshlet compression has direct published baselines, including
[Kuth et al.](https://gpuopen.com/download/Towards_Practical_Meshlet_Compression_paper.pdf)
and [AMD DGF](https://gpuopen.com/learn/amd-dgf-an-open-geometry-compression-standard/).

Other close work limits broader claims: differentiable topology reduction is
studied by [Neural Mesh Simplification (CVPR 2022)](https://openaccess.thecvf.com/content/CVPR2022/papers/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.pdf);
image-guided adaptive subdivision with watertightness constraints by
[Differentiable Micro-Mesh Construction (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.pdf);
and local learned topology refinement by
[Learned Localized Mesh Refinement](https://doi.org/10.1145/3829340.3842280), accepted as a
SIGGRAPH Asia 2026 Conference Paper; the authors' institutional publication
list says its presentation is deferred to SIGGRAPH 2027
([full arXiv paper](https://arxiv.org/html/2609.31946),
[publication list](https://adg.csail.mit.edu/?page_id=13)). It builds a
progressive vertex-split forest and a locally conditioned autoregressive model
for geometry and topology updates. It demonstrates view-dependent local
upsampling under a face budget. Its task is refinement of coarse meshes, not
render-matched simplification of a fixed authored asset; the paper reports
mesh-distribution and triangle-quality metrics plus a ship-drag application,
not post-MSAA or post-upscaler image quality. This closes local refinement and
view-dependent budget allocation as standalone novelty claims. It does not
answer the narrower, untested question of optimizing an authored hierarchy for
a specified final reconstruction operator. That task distinction is a
comparison to test, not proof of novelty.
[HLoD (Eurographics 2026)](https://diglib.eg.org/items/429b6aa4-7897-4217-b297-272992d745ae) jointly optimizes a hierarchy for 3D Gaussian Splatting. Its official abstract
supports broad hierarchy-optimization claims, but the full paper was not
available in this review. [T²-Splat (arXiv v1, 2026-11-04)](https://arxiv.org/abs/2611.06974)
combines QEM edge collapse, gradient-driven vertex splits, multi-view image
supervision, and scale-adaptive per-face mip-textures that reduce aliasing and
flicker. It reconstructs scenes from images; it does not create a cluster DAG
for an authored asset or evaluate a separate final hardware MSAA/upscaler. This
closes broad claims to differentiable adaptive mesh topology and scale-aware
appearance filtering; the narrower authored-hierarchy/post-reconstruction
comparison remains untested and is not a novelty claim.
Reiser et al.'s [Binary Opacity Grids (SIGGRAPH 2024)](https://www.cvlibs.net/publications/Reiser2024SIGGRAPH.pdf)
extracts and chunk-simplifies a mesh from multi-view images, then uses TAA to
render thin and subpixel geometry. Its moving-camera TAA result is close to
16x SSAA in image metrics, and it reports a Pixel 8 Pro measurement. This
establishes thin-geometry reconstruction plus temporal AA as prior art, but it
does not optimize an authored cluster LOD against TAA; its TAA comparison should
be included if ManyMesh selects a temporal operator.
Nanite's [SIGGRAPH 2021 course](https://advances.realtimerendering.com/s2021/Karis_Nanite_SIGGRAPH_Advances_2021_final.pdf)
selects clusters below one pixel of projected error and relies on TAA to blend
subpixel LOD changes. Unreal's current [TSR thin-geometry system](https://dev.epicgames.com/documentation/en-us/unreal-engine/thin-geometry-detection-with-temporal-super-resolution)
accumulates coverage over time and relaxes history rejection for geometry-driven
flicker, at the cost of additional passes. This is direct production practice
for coupling mesh LOD and temporal reconstruction; it narrows any claim that
LOD decisions ignore temporal reconstruction in general. It does not establish
offline optimization of mesh geometry against the final TSR operator.
Loubet and Neyret's [hybrid mesh-volume LoDs](https://doi.org/10.1111/cgf.13138)
also simplify above-resolution surfaces and prefilter their appearance while
representing sub-resolution details volumetrically. The publisher abstract was
inspected, not the full paper; this is prior art for scale-aware mesh/appearance
prefiltering, with a different representation and rendering pipeline.
Neural level-of-detail and progressive geometry compression are also established:
[N-GLOD (CVPR 2021)](https://research.nvidia.com/labs/toronto-ai/nglod/) uses
an octree feature volume with multilevel SDF interpolation, and
[Neural Progressive Meshes (SIGGRAPH 2023)](https://vovakim.com/papers_small/23_SIGGRAPHConference_NPM.pdf)
transmits per-face features and progressive residuals to trade bandwidth for
reconstruction quality. Weier et al.'s [Neural Prefiltering for
Correlation-Aware Levels of Detail (TOG 2023)](https://doi.org/10.1145/3592443)
learns appearance transport and visibility across a multilevel voxel grid for
physically based rendering. Its full paper is now inspected; it closes broad
claims to neural appearance LOD and multiscale appearance preservation, but it
does not simplify triangle meshes or optimize them for raster AA/upscaling.
Zhou et al.'s [Appearance-Preserving Scene Aggregation for Level-of-Detail
Rendering (TOG 2025)](https://doi.org/10.1145/3708343) independently provides
multiscale voxel scene LOD and discusses differentiable raster mesh fitting;
its future-work section proposes combining scene aggregation with gradient-
based optimization. This is a strong conceptual neighbor, even though it does
not optimize a triangle-mesh cluster DAG for a specified post-AA/upscaler
operator.
Together, these methods use different representations
and tasks, but rule out broad “neural LOD,” “latent mesh compression,” “learned
residual geometry,” hierarchy optimization, learned refinement, or scale-aware
image-fitting novelty claims, and LTM specifically rules out broad render-guided
mesh simplification or post-simplification geometry refinement claims. They do
not establish a result for a constrained triangle-mesh cluster DAG optimized
for actual post-AA/upscaler quality. The
HLoD record exposes the paper and supplement, but their full contents were not
available in this review. For user-preference claims, perceptual
silhouette and transition modeling has also been tested against observers in
[Gaze-Contingent Perceptual LoD Prediction (EGSR 2023)](https://doi.org/10.2312/sr.20231130),
which also reports a desktop Nanite comparison. This is prior art, not a
ManyMesh result or mobile measurement.

## Cheapest falsification and pass criteria

The latest seven-asset source-reference screen is only development evidence. It
found two all-metric wins over meshoptimizer on a 987-face GlassBrokenWindow,
no win over eligible QEM pairs, and losses on most eligible comparisons. Its
one-float32-ULP boundary rule was chosen retrospectively. See the
[screen report](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md)
and its [metrics and hashes](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json).
For that asset, the border-preserving fast-simplification QEM control returned
859 faces at all three requested cut targets (381, 491, and 569), so the two
eligible wins are meshoptimizer-only; the QEM scores are not equal-face results.
This result does not test differentiable fitting or post-upscaler quality.

1. The frozen two-asset input gate uses legal matched geometry at 50%
   retention; lower targets failed eligibility. The current host has a CPU
   build of PyTorch. The placement control requires a CUDA workstation before
   the candidate fit and scoring can run. The separate 30-model confirmation
   cameras are frozen, but scoring stays disabled until a method passes this gate.
   [Input preflight](tools/mmtrain/APPEARANCE_INPUT_PREFLIGHT_20261123.md)
2. Compare the nvdiffmodeling-based placement control against QEM, current
   ManyMesh placement, and meshoptimizer at identical face counts. Freeze
   training and reserved views before scoring; include no-AA and equal 4x MSAA
   arms. Do not describe this as a reproduction of Hasselgren et al.
3. If this two-asset reserved-view control has a signal, test it on a fresh
   asset-held-out cohort before asking whether cluster-DAG constraints add a
   repeatable benefit after actual MSAA or an available upscaler, at both
   matched faces and matched complete frame time. A pre-score candidate pool
   now contains 30 exact-face eligible Poly Haven models across 25 family
   groups and nine categories. Its asset inputs, camera split, renderer,
   metrics, and project-specific pass margins are frozen; quality scoring is
   disabled until a method configuration passes Gate 1. See the
   [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md)
   and [pool provenance](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md).
4. Report LDR-FLIP, PSNR, SSIM, silhouette/coverage error, sampled surface and
   normal deviation, topology/boundary failures, and camera-motion transitions.
   Treat objective metrics as complementary; a “perceptual” claim needs ratings
   or a predictor validated against ratings on held-out assets. The paper
   protocol calls for at least 20 newly cleared models across five or more
   predeclared shape categories, with uncertainty estimated across assets.
   Keep all views and paths for each source model in the same asset split.
5. Report quality first at matched face count, then at matched complete frame
   time. Also report an equal-quality cost point when interpolation is
   supported. Include offline time, asset bytes, load/decode time, memory, CPU
   selection and GPU time. Mobile performance requires measurements on a real
   phone; desktop timings do not establish it.

Stop if this frozen control fails on reserved views, the surrogate misranks
real reconstruction results, the candidate loses to matched controls, or legal
boundary/topology constraints fail. Do not change the public `.mmb` format or
rendering API before this gate passes. For concise status, see [MANYMESH.md](MANYMESH.md)
and the [next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md).
