# SIGGRAPH 2027 research direction

Updated 2026-11-23. This is a research plan, not a paper draft or novelty claim.
The candidate remains untested; the cited work is a bounded map for verification,
and a search that finds no paper is not evidence that none exists.

## Candidate and decision

The only current method hypothesis is **offline optimization of a triangle-mesh
cluster hierarchy for its final antialiased or upscaled image**. Fit geometry at
the screen scale where each level is used, model jittered sample accumulation
and resolve during optimization, and preserve the hierarchy's legal cuts,
shared boundaries, and transitions. The result must beat strong alternatives
after real reconstruction, not only its differentiable surrogate.

This combination has substantial prior art. Hasselgren et al. already optimize
mesh shape and appearance from image-space references for simplification and
LOD, including resolution-specific filtering and MSAA-assisted visibility
gradients ([EGSR 2021 paper](https://users.aalto.fi/~laines9/publications/hasselgren2021egsr_paper.pdf)).
V3DG already fits each level of a clustered hierarchy differentiably, although
it uses 3D Gaussian primitives ([SIGGRAPH 2025 paper](https://arxiv.org/html/2505.06523)).
HLOD ASAP's abstract and first-page preview describe progressive interior and
neighbor-paired boundary meshes that simplify cluster interfaces while keeping
mixed cuts crack-free ([Eurographics record](https://doi.org/10.1111/cgf.70380),
[publisher preview](https://www.researchgate.net/publication/403799777_Construction_of_clustered_HLOD_with_As-Simplified-As-Possible_boundaries)).
Its full text and quantitative results were unavailable in this review, so that
comparison is incomplete. Quick-VDR already provides clustered progressive
meshes and dependency-constrained crack-free refinement
([full paper](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content)).
Therefore hierarchy fitting, per-level differentiable fitting, scale-aware
appearance, boundary consistency, and transition stability are not contributions
on their own. Novelty is not established.

The only plausible distinction to test is a measurable advantage from fitting
the hierarchy to a specified post-reconstruction image while retaining the
cluster DAG's legal-cut and boundary constraints. That claim is still much
narrower than “LOD for upscalers”: classic silhouette-aware simplification,
silhouette clipping, budgeted/predictive LOD selection, perceptual silhouette
and transition models, and neural prediction of image error for shading-rate
control have direct precedents. The [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
records the initial sources, what was checked, and what still requires full-paper
review; it is not an exhaustive literature search.

| Priority | Direction | Current disposition |
|---|---|---|
| 1 | **A+B: post-reconstruction-aware hierarchy optimization** | Keep as a falsifiable hypothesis. First reproduce a matched-face differentiable simplification baseline; only then test the cluster-DAG constraints. |
| 2 | **C: tile-GPU cost model and selection** | Systems-analysis fallback if a physical tile-based device and profiling counters are available. A screen-tile count alone is only a proxy. |
| 3 | **D: rate-aware DAG construction** | Parked. Meshlet compression is crowded; reopen only with full-stream byte and decode comparisons against meshoptimizer, Draco, Kuth et al., and AMD DGF. |

Silhouette-aware LOD and clipping have direct precedents in
[Luebke–Erikson (1997)](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf)
and [Sander et al. (2000)](https://hhoppe.com/silclip.pdf). Image-driven
simplification also predates this project ([Lindstrom–Turk (2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)).
Budgeted and hierarchical LOD optimization also predate this project: see
[Funkhouser–Séquin (1993)](https://www.cs.princeton.edu/courses/archive/spr01/cs598b/papers/funkhouser93.pdf)
and [Mason–Blake (1997)](https://doi.org/10.1111/1467-8659.00156).
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
[Learned Localized Mesh Refinement](https://arxiv.org/html/2609.31946), a SIGGRAPH Asia 2026 paper
on adaptive learned upsampling of coarse input meshes. It is close prior art for
view-dependent local refinement, but its task is not render-matched simplification
of an authored asset. [HLoD (Eurographics 2026)](https://diglib.eg.org/items/429b6aa4-7897-4217-b297-272992d745ae)
jointly optimizes a hierarchy for 3D Gaussian Splatting, and
[T²-Splat](https://arxiv.org/html/2611.06974) combines adaptive triangle topology,
image supervision, and scale-aware residual filtering for scene reconstruction.
Neural level-of-detail and progressive geometry compression are also established:
[N-GLOD (CVPR 2021)](https://research.nvidia.com/labs/toronto-ai/nglod/) uses
an octree feature volume with multilevel SDF interpolation, and
[Neural Progressive Meshes (SIGGRAPH 2023)](https://vovakim.com/papers_small/23_SIGGRAPHConference_NPM.pdf)
transmits per-face features and progressive residuals to trade bandwidth for
reconstruction quality. Together, these methods use different representations
and tasks, but rule out broad “neural LOD,” “latent mesh compression,” “learned
residual geometry,” hierarchy optimization, learned refinement, or scale-aware
image-fitting novelty claims. They do not establish a result for a constrained
triangle-mesh cluster DAG optimized for actual post-AA/upscaler quality. The
HLoD record exposes the paper and supplement, but their full contents were not
available in this review. For user-preference claims, perceptual
silhouette and transition modeling has also been tested against observers in
[Gaze-Contingent Perceptual LoD Prediction (EGSR 2023)](https://doi.org/10.2312/sr.20231130),
which also reports a desktop Nanite comparison. This is prior art, not a
ManyMesh result or mobile measurement.

## Cheapest falsification and pass criteria

1. Secure two hash-pinned, redistribution-cleared assets and a CUDA-capable
   system. The current checkout has a local Monkey development mesh but no
   provenance record for it, no local Dragon mesh, and no CUDA build or GPU, so
   the proposed replication cannot be claimed as run. Two assets are only a
   cheap falsification screen, not paper-level evidence.
2. Compare nvdiffmodeling/Hasselgren placement against QEM, current ManyMesh
   placement, and meshoptimizer at identical face counts. Freeze training and
   held-out views before scoring; include no-AA and equal 4x MSAA arms.
3. If that baseline has a repeatable held-out signal, test DAG-level fitting
   against legal mixed-cut and progressive-boundary controls. Evaluate real AA
   and available upscalers, not only the training surrogate.
4. Report LDR-FLIP, PSNR, SSIM, silhouette/coverage error, sampled surface and
   normal deviation, topology/boundary failures, and camera-motion transitions.
   Treat objective metrics as complementary; a “perceptual” claim needs ratings
   or a predictor validated against ratings on held-out assets. A paper-level
   cross-asset result requires at least 20 newly cleared models across five or
   more predeclared shape categories, split by source asset, with multiple
   held-out views and asset-level uncertainty. Keep all views and camera paths
   from one model within a single data split.
5. Report quality first at matched face count, then at matched complete frame
   time. Also report an equal-quality cost point when interpolation is
   supported. Include offline time, asset bytes, load/decode time, memory, CPU
   selection and GPU time. Mobile performance requires measurements on a real
   phone; desktop timings do not establish it.

Stop if the baseline fails on held-out views, the surrogate misranks real
reconstruction results, the candidate loses to matched controls, or legal
boundary/topology constraints fail. Do not change the public `.mmb` format or
rendering API before this gate passes. For concise status, see [MANYMESH.md](MANYMESH.md)
and the [next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md).
