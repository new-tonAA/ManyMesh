# SIGGRAPH 2027 prior-art screen

Updated 2026-11-25. This is a bounded lead list, not a systematic review,
novelty opinion, or legal assessment. Sources were checked at their publisher,
author, project, or explicitly identified preview pages; only entries marked
**paper text inspected** were checked beyond an abstract or summary. Read the full closest papers,
their references, and citing work before making a novelty claim. Failure to find
a paper is not evidence that none exists.

## Directly relevant geometry and LOD work

| Work | What the primary source establishes | Review status and consequence |
|---|---|---|
| Hasselgren et al., [Appearance-Driven Automatic 3D Model Simplification](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc), EGSR 2021 | Differentiable image-space optimization jointly fits mesh vertex positions and materials; uses include appearance-preserving decimation and LOD. It fits a fixed initial topology and samples randomized views and lights. For its shape-and-appearance prefiltering application (Sections 4.2 and 5.2), it uses MSAA during training to improve silhouette visibility gradients; the paper does not state that every simplification experiment uses MSAA. Final 1-spp results are un-antialiased unless stated otherwise. | **Full paper text inspected.** This is the closest prior work to render-matched mesh placement and scale-aware prefiltering. It does not build/optimize a cluster DAG, alter topology during fitting, or train through a temporal upscaler. Those differences define a comparison, not novelty. The paper reports 2048², batch 8, 10k steps, about 30 minutes on an A6000 for final results; the local CPU-only host cannot reproduce that setup. |
| Luebke and Erikson, [View-Dependent Simplification of Arbitrary Polygonal Environments](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf), SIGGRAPH 1997 | View-dependent simplification explicitly treats silhouette quality. | **Primary paper link identified; full paper not reviewed in this pass.** Silhouette-aware refinement is established prior art. |
| Sander et al., [Silhouette Clipping](https://hhoppe.com/silclip.pdf), SIGGRAPH 2000 | Uses nested progressive hulls, a hierarchical anchored-cone silhouette search, and stencil/alpha clipping to restore the original exterior silhouette over coarse geometry. | **Full paper text inspected.** Its limits include static closed oriented manifolds, exterior viewpoints, and polygonal internal silhouettes. Generic silhouette correction is not a safe novelty claim. |
| Funkhouser and Séquin, [Adaptive Display Algorithm for Interactive Frame Rates During Visualization of Complex Virtual Environments](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/funkhouser93.pdf), SIGGRAPH 1993 | Chooses object representations under a frame-rate constraint. | **Primary paper link identified; full paper not reviewed in this pass.** Budgeted LOD selection is established. |
| Mason and Blake, [Automatic Hierarchical Level of Detail Optimization in Computer Animation](https://doi.org/10.1111/1467-8659.16.3conferenceissue.21), Eurographics 1997 | Predictive optimization of hierarchical LOD is used for real-time rendering. | **Bibliographic record identified; full text not reviewed.** Do not claim predictive or budgeted selection as new. |
| Lindstrom and Turk, [Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf), TOG 2000 | Uses rendered image differences from multiple camera views to guide edge-collapse costs; discusses silhouette, hidden geometry, shading, and texture effects. | **Full paper text inspected.** Image-driven mesh simplification is direct prior art. The paper uses a fixed set of views and image-difference costs; differentiability or a cluster-DAG application would need measured algorithmic differences beyond replacing its objective. |
| Yoon et al., [Quick-VDR: Interactive View-Dependent Rendering of Massive Models](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content), 2004 | Uses a clustered hierarchy of progressive meshes, cluster selection, local refinement, and dependency constraints for crack-free refinement. | **Paper text inspected.** Clustered view-dependent refinement and crack-free dependency mechanisms are established. |
| Ladeuil et al., [Construction of Clustered HLOD with As-Simplified-As-Possible Boundaries](https://doi.org/10.1111/cgf.70380), CGF 2026 | Builds a binary hierarchy of progressive meshes with separate progressive interior and neighbor-paired boundary portions. The goal is to simplify interfaces while retaining consistent, crack-free mixed cuts and reducing boundary-driven popping. | **Publisher record, abstract, and first-page preview hosted on ResearchGate checked; full methods and quantitative results remain unavailable.** Boundary simplification and crack-free neighboring cuts are direct prior art. Do not treat the remainder as an established distinction until the full paper is compared. |
| Potamias et al., [Neural Mesh Simplification](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html), CVPR 2022 | A learned one-pass method samples input vertices, predicts candidate triangles from graph connectivity, and classifies output faces. It is differentiable and reports up to 10× faster simplification than traditional methods. | **Full paper text inspected.** Learned topology simplification is established. Its objective is geometric/structural (Chamfer, normal, Laplacian, curvature), not rendered appearance; it does not build a multilevel cluster DAG. The authors note QEM gives smoother watertight surfaces and their learned topology/manifold losses do not guarantee those properties. |
| Zhan et al., [Learned Localized Mesh Refinement](https://arxiv.org/html/2609.31946), SIGGRAPH Asia 2026 | Builds a progressive vertex-split forest and trains a locally conditioned autoregressive model for adaptive upsampling. It demonstrates view-dependent refinement with a face-count budget; the paper reports training on eight B200 GPUs. | **Full arXiv HTML paper inspected.** This is learned refinement of coarse inputs toward higher-detail shapes, not simplification of a fixed authored asset to preserve its rendered appearance. It occupies local learned refinement and view-dependent allocation; the task difference alone does not establish novelty. |
| Surace et al., [Gaze-Contingent Perceptual LoD Prediction](https://doi.org/10.2312/sr.20231130), EGSR 2023 | Calibrates spatial silhouette/body distortion and temporal LOD-switch visibility models with observer studies, then predicts gaze-contingent mesh LOD. It reports up to 33% extra speedup over Nanite at 2K in its desktop test. | **Full paper text inspected.** This already combines perceptual LOD selection, temporal transition modeling, gaze-contingent geometry, and a Nanite comparison. Its test uses 15 participants for spatial calibration, five for temporal calibration, and an RTX 3090 scene with 2,184 Suzanne or Dragon instances; it is not a mobile result or a post-upscaler geometry-optimization method. |
| Dou et al., [Differentiable Micro-Mesh Construction](https://openaccess.thecvf.com/content/CVPR2024/html/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.html), CVPR 2024 | Image-guided differentiable mesh subdivision with watertightness constraints. | **Publisher page checked; full paper not reviewed here.** Differentiable topology creation and watertightness are not broad novelty claims. |

## Adjacent methods that constrain broader claims

| Work | Relevance | Review status |
|---|---|---|
| Cardoso et al., [Training and Predicting Visual Error for Real-Time Applications](https://www.cg.tuwien.ac.at/research/publications/2022/cardoso-2022-rtpercept/), 2022 | Learns visual-error estimates from G-buffer information for shading reuse and variable-rate shading; it does not predict geometry error or choose mesh topology. | Author record and abstract checked. It is adjacent error prediction, not a geometry baseline. |
| [N-GLOD](https://research.nvidia.com/labs/toronto-ai/nglod/), CVPR 2021 | Neural octree feature volumes and multilevel SDF reconstruction. | Project page checked. Neural level-of-detail is broad prior art, but the representation and task differ. |
| [Neural Progressive Meshes](https://vovakim.com/papers_small/23_SIGGRAPHConference_NPM.pdf), SIGGRAPH 2023 | Progressive per-face features and residuals trade transmission rate against reconstruction quality. | Paper link identified; full paper not reviewed in this pass. Learned residual geometry and progressive neural mesh coding are not safe broad novelty claims. |
| Kuth et al., [Real-Time Meshlet Decompression](https://doi.org/10.1016/j.cag.2025.104292), Computers & Graphics 2025, and [AMD DGF](https://gpuopen.com/learn/problem_increasing_triangle_density/) | Kuth et al. report about 5.9 bits per triangle for meshlet index data and a faster 9.5-bit mode, using generalized triangle strips for mesh-shader decode. AMD DGF quantizes geometry while preserving connectivity and exposes precision/size controls. | Publisher abstract/snippets and AMD’s official format overview checked; Kuth’s full paper not reviewed. The 5.9 BPT figure is index-buffer data, not a complete asset stream. Any compression claim needs full payload bytes, quality, and decode comparisons against these systems, Draco, and meshoptimizer. |
| [Arm Neural Super Sampling](https://www.arm.com/products/silicon-ip-multimedia/gpu/mali-g2-ultra-nx) | Reconstructs higher-resolution images from lower-resolution renders on Mali G2-Ultra NX hardware. | Current product page checked. This establishes mobile neural upscaling, not a baseline or result on unrelated devices. |
| Arm, [Nanite on Mali](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/mori-to-nanite-billions-of-triangles-on-mobile) | Reports a Nanite-enabled Unreal 5.5.2 Mori scene on a Vivo X200 Pro with Mali-G925 Immortalis MC12. Arm reports about 15.75 FPS before disabling world-position-offset animation. | **Arm project report checked; independent replication not reviewed.** It establishes that Nanite-like rendering has been demonstrated on mobile, not that it meets a target frame rate or that ManyMesh works on phones. |

## Systems and reconstruction context

| Topic | What the primary source establishes | Review status and consequence |
|---|---|---|
| Tile-based GPU geometry cost | Meta's developer documentation explains that mobile tiled renderers run a position-only vertex pass for binning and then rerun vertex work for triangles in each touched tile. It also describes tile timelines in RenderDoc Meta Fork. | **Official developer documentation checked.** This supports measuring triangle-to-tile work and GPU time on a real device. It is not itself a quantitative predictive model for cluster selection. No such model has been established as absent; a broader proceedings and citation search is required before making a gap claim. |
| Mobile neural upscaling | Arm documents Neural Super Sampling on Mali G2-Ultra NX and its system-level neural graphics pipeline. | **Official product and developer material checked.** It is a relevant device-specific reconstruction baseline if accessible; it cannot stand in for unavailable phone hardware or unrelated upscalers. |
| Upscaler-facing LOD practice | BeamNG's temporal-upscaling documentation discusses texture mip bias so texture detail is sampled for the display resolution. | **Documentation located; geometry-LOD behavior not established.** This source cannot support the broader claim that engines generally scale geometric LOD thresholds using display resolution. Treat geometry LOD response to reconstruction as an open measurement question, not a literature gap, until a specific engine implementation is inspected. |

## Candidate gap and required test

The working hypothesis is narrowly phrased as **offline optimization of a
triangle-mesh cluster DAG for quality after a specified antialiasing or
upscaling pipeline, while respecting legal cuts and shared-boundary constraints**.
No novelty is established. “LOD for upscalers,” “silhouette aware,”
“differentiable LOD,” “cluster hierarchy optimization,” and “temporal
stability” are not novelty claims by themselves.

Before investing in a custom method:

1. Reproduce Hasselgren et al.'s fixed-topology mesh-placement baseline against
   QEM, ManyMesh placement, and meshoptimizer at identical face counts.
2. Verify the full methods in Luebke–Erikson, Funkhouser–Séquin, Mason–Blake,
   Quick-VDR, and HLOD ASAP; inspect references and citing work for additional
   mesh-level predecessors.
3. If the matched-face baseline has a held-out signal, test whether the
   cluster-DAG constraints add a repeatable benefit after actual MSAA or an
   available upscaler, at both matched faces and matched complete frame time.
4. Treat any unlocated prior art as unresolved. Update this screen with full
   citations, exact sections compared, implementation differences, and negative
   results; do not turn a search gap into a novelty statement.

The research decision and stop gates are in
[`SIGGRAPH_2027_DIRECTION.md`](../../SIGGRAPH_2027_DIRECTION.md). This page is
an index to verify, not a substitute for reading the papers.
