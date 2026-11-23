# SIGGRAPH 2027 prior-art screen

Updated 2026-11-23. This is a bounded lead list, not a systematic review,
novelty opinion, or legal assessment. Sources were checked at their publisher,
author, or project pages; only entries marked **paper text inspected** were
checked beyond an abstract or project summary. Read the full closest papers,
their references, and citing work before making a novelty claim. Failure to find
a paper is not evidence that none exists.

## Directly relevant geometry and LOD work

| Work | What the primary source establishes | Review status and consequence |
|---|---|---|
| Hasselgren et al., [Appearance-Driven Automatic 3D Model Simplification](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc), EGSR 2021 | Differentiable image-space optimization jointly fits triangle meshes and shading models; listed uses include mesh decimation and LOD generation. | **Paper text inspected, not line-by-line.** This is the closest prior work to offline render-matched LOD placement. A cluster hierarchy or scale-matched loss alone is not a contribution. Reproduce it at matched face counts before adding ManyMesh-specific constraints. |
| Luebke and Erikson, [View-Dependent Simplification of Arbitrary Polygonal Environments](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf), SIGGRAPH 1997 | View-dependent simplification explicitly treats silhouette quality. | **Primary paper link identified; full paper not reviewed in this pass.** Silhouette-aware refinement is established prior art. |
| Sander et al., [Silhouette Clipping](https://hhoppe.com/silclip.pdf), SIGGRAPH 2000 | The method clips coarse rendering against a representation of the original silhouette. | **Primary paper link identified; full paper not reviewed in this pass.** Generic silhouette correction is not a safe novelty claim. |
| Funkhouser and Séquin, [Adaptive Display Algorithm for Interactive Frame Rates During Visualization of Complex Virtual Environments](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/funkhouser93.pdf), SIGGRAPH 1993 | Chooses object representations under a frame-rate constraint. | **Primary paper link identified; full paper not reviewed in this pass.** Budgeted LOD selection is established. |
| Mason and Blake, [Automatic Hierarchical Level of Detail Optimization in Computer Animation](https://doi.org/10.1111/1467-8659.16.3conferenceissue.21), Eurographics 1997 | Predictive optimization of hierarchical LOD is used for real-time rendering. | **Bibliographic record identified; full text not reviewed.** Do not claim predictive or budgeted selection as new. |
| Yoon et al., [Quick-VDR: Interactive View-Dependent Rendering of Massive Models](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content), 2004 | Uses a clustered hierarchy of progressive meshes, cluster selection, local refinement, and dependency constraints for crack-free refinement. | **Paper text inspected.** Clustered view-dependent refinement and crack-free dependency mechanisms are established. |
| Knodt and Gao, [Construction of Clustered HLOD with As-Simplified-As-Possible Boundaries](https://doi.org/10.1111/cgf.70380), CGF 2026 | The record describes clustered HLOD construction with simplified, crack-free neighboring boundaries. | **Record and abstract checked; full text not reviewed.** This narrows boundary-simplification claims; compare the full method and results. |
| Potamias et al., [Neural Mesh Simplification](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html), CVPR 2022 | Uses learned methods for mesh simplification. | **Publisher page checked; full paper not reviewed here.** Learned topology reduction is established; a task distinction needs algorithmic evidence. |
| Zhan et al., [Learned Localized Mesh Refinement](https://arxiv.org/abs/2609.31946), 2026 preprint | A learned autoregressive method adds detail selectively to mesh regions and describes view-dependent refinement. | **Abstract checked; full paper not reviewed.** Local learned refinement and view-dependent allocation are occupied neighboring directions. Verify publication status and method details against the proceedings. |
| Dou et al., [Differentiable Micro-Mesh Construction](https://openaccess.thecvf.com/content/CVPR2024/html/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.html), CVPR 2024 | Image-guided differentiable mesh subdivision with watertightness constraints. | **Publisher page checked; full paper not reviewed here.** Differentiable topology creation and watertightness are not broad novelty claims. |

## Adjacent methods that constrain broader claims

| Work | Relevance | Review status |
|---|---|---|
| Cardoso et al., [Training and Predicting Visual Error for Real-Time Applications](https://www.cg.tuwien.ac.at/research/publications/2022/cardoso-2022-rtpercept/), 2022 | Learns visual-error estimates from G-buffer information for shading reuse and variable-rate shading; it does not predict geometry error or choose mesh topology. | Author record and abstract checked. It is adjacent error prediction, not a geometry baseline. |
| [N-GLOD](https://research.nvidia.com/labs/toronto-ai/nglod/), CVPR 2021 | Neural octree feature volumes and multilevel SDF reconstruction. | Project page checked. Neural level-of-detail is broad prior art, but the representation and task differ. |
| [Neural Progressive Meshes](https://vovakim.com/papers_small/23_SIGGRAPHConference_NPM.pdf), SIGGRAPH 2023 | Progressive per-face features and residuals trade transmission rate against reconstruction quality. | Paper link identified; full paper not reviewed in this pass. Learned residual geometry and progressive neural mesh coding are not safe broad novelty claims. |
| [Arm Neural Super Sampling](https://www.arm.com/products/silicon-ip-multimedia/gpu/mali-g2-ultra-nx) | Reconstructs higher-resolution images from lower-resolution renders on Mali G2-Ultra NX hardware. | Current product page checked. This establishes mobile neural upscaling, not a baseline or result on unrelated devices. |
| Arm, [Nanite on Mali](https://developer.arm.com/community/arm-community-blogs/b/mobile-graphics-and-gaming-blog/posts/mori-to-nanite-billions-of-triangles-on-mobile) | Demonstrates a Nanite-based Unreal scene on a Mali phone. | Project report identified; independent replication and full cost comparison not reviewed. Mobile Nanite-like rendering is not itself a novel claim. |

## Candidate gap and required test

The working hypothesis is narrowly phrased as **offline optimization of a
triangle-mesh cluster DAG for quality after a specified antialiasing or
upscaling pipeline, while respecting legal cuts and shared-boundary constraints**.
No novelty is established. “LOD for upscalers,” “silhouette aware,”
“differentiable LOD,” “cluster hierarchy optimization,” and “temporal
stability” are not novelty claims by themselves.

Before investing in a custom method:

1. Read Hasselgren et al. in full and reproduce its mesh-placement baseline
   against QEM, ManyMesh placement, and meshoptimizer at identical face counts.
2. Verify the full methods in Sander et al., Quick-VDR, HLOD ASAP, Neural Mesh
   Simplification, and Learned Localized Mesh Refinement; inspect references and
   citing work for additional mesh-level predecessors.
3. If the matched-face baseline has a held-out signal, test whether the
   cluster-DAG constraints add a repeatable benefit after actual MSAA or an
   available upscaler, at both matched faces and matched complete frame time.
4. Treat any unlocated prior art as unresolved. Update this screen with full
   citations, exact sections compared, implementation differences, and negative
   results; do not turn a search gap into a novelty statement.

The research decision and stop gates are in
[`SIGGRAPH_2027_DIRECTION.md`](../../SIGGRAPH_2027_DIRECTION.md). This page is
an index to verify, not a substitute for reading the papers.
