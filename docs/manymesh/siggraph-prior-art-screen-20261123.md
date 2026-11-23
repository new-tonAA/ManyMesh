# SIGGRAPH 2027 prior-art screen

Updated 2026-11-23. This is a bounded literature map, not a systematic review,
novelty verdict, or patent assessment. Full-text status is stated per work. A
missing paper in this list is not evidence that none exists.

## Closest precedents

| Work | What is already established | Review status and consequence |
|---|---|---|
| Hasselgren et al., [Appearance-Driven Automatic 3D Model Simplification](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc), EGSR 2021 | Differentiable image-space fitting of mesh positions and appearance for decimation and LOD; resolution-specific optimization and MSAA-assisted visibility gradients. | **Full paper inspected.** Their optimized topology is fixed. This is the closest baseline for render-matched placement and scale-aware filtering, but it does not optimize a cluster DAG or train through a temporal upscaler. Those differences still need an experimental benefit. |
| Lindstrom and Turk, [Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf), TOG 2000 | Rendered image differences from multiple views guide edge-collapse costs; silhouette, shading, hidden geometry, and texture effects are discussed. | **Full paper inspected.** Image-driven mesh simplification predates differentiable rendering. Replacing its objective or applying it to a hierarchy is not sufficient novelty. |
| Luebke and Erikson, [View-Dependent Simplification of Arbitrary Polygonal Environments](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf), SIGGRAPH 1997; Hoppe, [View-Dependent Refinement of Progressive Meshes](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/hoppe97.pdf), SIGGRAPH 1997 | View-dependent refinement, silhouette-sensitive error, triangle budgets, and progressive-mesh transitions. | **Full papers inspected.** Contour-aware thresholds, silhouette priority, fixed-budget selection, and geomorphing are established ideas. |
| Sander et al., [Silhouette Clipping](https://hhoppe.com/silclip.pdf), SIGGRAPH 2000 | Progressive hulls and anchored cones recover a coarse mesh's exterior silhouette through clipping. | **Full paper inspected.** Generic silhouette reconstruction is not a safe novelty claim; the method also has assumptions such as static closed oriented meshes and exterior viewpoints. |
| Funkhouser and Séquin, [Adaptive Display Algorithm](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/funkhouser93.pdf), SIGGRAPH 1993; Mason and Blake, [Automatic Hierarchical Level of Detail Optimization](https://doi.org/10.1111/1467-8659.16.3conferenceissue.21), Eurographics 1997 | Frame-rate-constrained representation choice and hierarchical/predictive LOD allocation. | **Funkhouser–Séquin full paper inspected.** Mason–Blake bibliographic record found; full text not reviewed. Budgeted and predictive LOD are not new in general. |
| Yoon et al., [Quick-VDR](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content), IEEE Visualization 2004; Zhang and Chen, [Constructing and Rendering of Multiresolution Representation for Massive Meshes](https://www.jsoftware.us/vol8/jsw0808-20.pdf), 2013 | Clustered progressive meshes, local refinement, dependency-constrained crack-free cuts, and fine-grained refinement within a cluster hierarchy. | **Full papers inspected.** Cluster hierarchies, mixed-cut legality, and within-cluster progressive refinement are direct mesh-hierarchy precedents. |
| Surace et al., [Gaze-Contingent Perceptual LoD Prediction](https://doi.org/10.2312/sr.20231130), EGSR 2023 | Observer-calibrated spatial silhouette and temporal LOD-switch models, gaze-contingent mesh selection, and a Nanite comparison. The paper reports up to 33% additional speedup over Nanite at 2K in its desktop experiment. | **Full paper inspected.** This is desktop evidence on an RTX 3090, not a ManyMesh or phone result. Perceptual LOD, transition visibility, and a Nanite comparison are prior art. |
| Potamias et al., [Neural Mesh Simplification](https://openaccess.thecvf.com/content/CVPR2022/papers/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.pdf), CVPR 2022; Zhan et al., [Learned Localized Mesh Refinement](https://arxiv.org/html/2609.31946), SIGGRAPH Asia 2026 | Learned topology simplification and learned local adaptive upsampling of coarse meshes. | **Full texts inspected.** The former targets simplified topology with geometric/structural losses; the latter predicts local refinement toward higher-detail shapes. Neither alone establishes the proposed post-reconstruction cluster-DAG result. Learned simplification and local refinement are not broad novelty claims. |
| Ladeuil et al., [Construction of Clustered HLOD with As-Simplified-As-Possible Boundaries](https://doi.org/10.1111/cgf.70380), CGF 2026 | The abstract and publisher preview describe progressive interior and neighbor-paired boundary meshes for crack-free mixed cuts and less restrictive cluster interfaces. | **Abstract and first-page preview checked; full methods and quantitative results unavailable.** This is a direct boundary-treatment precedent. Do not claim a distinction from it until the full paper is compared. |

## Adjacent work that narrows broader claims

| Work | Relevance and review limit |
|---|---|
| [V3DG](https://arxiv.org/html/2505.06523), SIGGRAPH 2025 | **Full paper and supplement inspected.** Differentiably fits clustered 3D Gaussian levels and selects them by screen footprint. It is not a triangle mesh, but hierarchy fitting and per-level differentiable optimization are established. |
| Tang et al., [T²-Splat](https://arxiv.org/html/2611.06974), 2026 preprint | **Full preprint and supplement inspected.** Combines adaptive triangle topology, image supervision, and scale-aware residual filtering for scene reconstruction. A reusable constrained asset DAG and real AA/upscaler comparison are different tasks, not proof of novelty. |
| [HLoD](https://diglib.eg.org/items/429b6aa4-7897-4217-b297-272992d745ae), Eurographics 2026 | Publisher record lists the paper and supplement, but their full contents were unavailable in this review. Joint Gaussian-hierarchy optimization is adjacent; detailed comparison remains open. |
| Weier et al., [Neural Prefiltering for Correlation-Aware Levels of Detail](https://weiphil.s3.eu-central-1.amazonaws.com/neural_lod.pdf), SIGGRAPH 2023; Zhou et al., [Appearance-Preserving Scene Aggregation](https://cse.ucsd.edu/~ravir/yangzhou.pdf), TOG 2025 | **Full papers inspected.** Learned appearance prefiltering and pixel-scale, multisampled appearance-preserving LOD exist for volumetric/path-traced representations. They are not triangle-mesh DAG methods, but broad scale-aware appearance LOD is not new. |
| Dou et al., [Differentiable Micro-Mesh Construction](https://openaccess.thecvf.com/content/CVPR2024/papers/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.pdf), CVPR 2024; Choi et al., [LTM](https://openaccess.thecvf.com/content/CVPR2024/papers/Choi_LTM_Lightweight_Textured_Mesh_Extraction_and_Refinement_of_Large_Unbounded_CVPR_2024_paper.pdf), CVPR 2024 | **Full papers inspected.** Image-guided adaptive subdivision with watertightness constraints and joint image-space optimization of simplified mesh geometry and appearance are established in their respective representations. |
| Kuth et al., [Real-Time Meshlet Decompression](https://doi.org/10.1016/j.cag.2025.104292), Computers & Graphics 2025 ([2024 preprint](https://arxiv.org/abs/2404.06359)); [AMD DGF](https://gpuopen.com/learn/amd-dgf-an-open-geometry-compression-standard/) | Kuth et al. report about **5.9 bits per triangle for the meshlet index stream**, with a faster 9.5-bit mode. That is not a complete asset rate. AMD DGF is a separate compressed geometry format. | **Kuth preprint inspected in full; journal record/abstract and AMD's official overview checked.** Compression claims require full-stream bytes, quality, and decode/load comparisons against these systems, Draco, and meshoptimizer. |
| [N-GLOD](https://research.nvidia.com/labs/toronto-ai/nglod/), CVPR 2021; [Neural Progressive Meshes](https://vovakim.com/papers_small/23_SIGGRAPHConference_NPM.pdf), SIGGRAPH 2023 | Neural octree feature volumes with multilevel SDFs and progressive learned face features/residuals. | N-GLOD project page checked; Neural Progressive Meshes full paper not reviewed. Neural LOD, latent geometry, and progressive residual coding are occupied broad areas. |
| Arm, [Neural Super Sampling on Mali G2-Ultra NX](https://www.arm.com/products/silicon-ip-multimedia/gpu/mali-g2-ultra-nx); Arm, [Nanite on Mali](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/mori-to-nanite-billions-of-triangles-on-mobile) | Arm documents mobile neural upscaling on G2-Ultra NX and reports a Nanite-enabled Unreal 5.5.2 Mori scene on a Vivo X200 Pro/Mali-G925. The report gives about 15.75 FPS before disabling WPO animation. | **Vendor documentation and project report inspected; independent replication unavailable.** This rules out “Nanite-like geometry on phones” as a broad novelty claim, but establishes no ManyMesh phone performance. NSS is a baseline only on supported hardware. |
| Cardoso et al., [Training and Predicting Visual Error for Real-Time Applications](https://doi.org/10.1145/3522625), 2022 | Learned image-error prediction from G-buffer features for shading reuse and variable-rate shading, not mesh topology selection. | Author record and abstract checked. Adjacent learned error prediction does not replace a geometry baseline. |

## Candidate and next test

The only active question is whether **offline optimization of a triangle-mesh
cluster DAG for quality after a specified real antialiasing or upscaling
pipeline** can beat strong alternatives at matched face count and matched full
frame cost while satisfying shared-boundary, legal-cut, and transition
constraints. The question is untested; no novelty is established. “Silhouette
aware,” “differentiable LOD,” “hierarchy optimization,” “perceptual LOD,”
“temporal stability,” “neural geometry,” and “compression” are not novelty
claims by themselves.

Before a custom optimizer, reproduce the Hasselgren/nvdiffmodeling placement
baseline against QEM, current ManyMesh placement, and meshoptimizer at identical
face counts, using cleared assets and frozen held-out views. Only if that has a
repeatable asset-held-out signal should the study test whether DAG-specific
constraints add value after real MSAA/SMAA/upscaling. Include LDR-FLIP, PSNR,
SSIM, silhouette/coverage error, surface/normal deviation, temporal transition
quality, complete runtime, bytes, and memory. A user-preference claim requires
human validation or a predictor demonstrated to generalize to held-out assets.
Mobile claims require measurements on a physical device.

The current workspace has not passed the asset/compute gate for this test. The
[research direction](../../SIGGRAPH_2027_DIRECTION.md) and
[current status](../../MANYMESH.md) state the stop conditions. Read references
and citing papers before making a paper-level novelty claim; this first-pass
map is not exhaustive.
