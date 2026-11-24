# Next experiment gate: fixed-topology placement control

Updated 2026-11-25. **This is a falsification plan, not a contribution claim.**
The SIGGRAPH 2027 Technical Papers page lists 28 January 2027 as the paper
deadline and says detailed submission instructions are forthcoming. The
schedule does not relax the evidence gate. [Official dates](https://s2027.siggraph.org/program/technical-papers/)

## Candidate question

Can offline appearance optimization improve a constrained triangle-mesh cluster
LOD hierarchy when quality is measured after antialiasing or upscaling? Use one
comparison at matched face count and a separate comparison at matched complete
frame time. The frozen first experiment is a placement control adapted from
nvdiffmodeling; it is not a custom DAG optimizer or a faithful reproduction of
Hasselgren et al.'s training protocol.

Close prior art includes Hasselgren et al.'s differentiable mesh and shading
optimization for simplification and LOD. Their full paper uses MSAA during
optimization for its shape-and-appearance prefiltering application to improve
silhouette visibility gradients while matching a supersampled target; it does
not state that MSAA is used for every simplification experiment. Reported 1-spp
results are rendered without AA unless noted. Thus differentiable fitting,
scale-specific appearance fitting, and MSAA-assisted silhouette gradients are
already established. The remaining experiment question is whether fitting a
hierarchy for a specified final reconstruction operator improves quality over
applying that same operator to unoptimized geometry, while retaining legal
cluster-DAG cuts and boundaries. This is an untested question, not a novelty
claim. [Full paper](https://users.aalto.fi/~laines9/publications/hasselgren2021egsr_paper.pdf) |
[Luebke and Erikson](https://dl.acm.org/doi/10.1145/258734.258847) |
[Luebke's detailed dissertation treatment](https://www.luebke.us/publications/pdf/dissertation.pdf) |
[Sander et al.](https://hhoppe.com/silclip.pdf)

Dou et al.'s [Differentiable Micro-Mesh Construction (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.pdf)
is another close precedent. It optimizes displacement-based geometry against
multi-view image loss and selects adaptive per-triangle subdivision levels
from image-space improvement. Its representation and compact ray-tracing
target differ from a standard cluster-DAG triangle mesh, but differentiable
image-driven geometry fitting and adaptive LOD are not a novelty distinction.
Its evaluation holds out views of each optimized asset, not transfer to unseen
assets, and does not report fitting through final MSAA or temporal upscaling.
Any later comparison must state this overlap and test only the narrower
final-reconstruction-operator question.

DMesh++ (ICCV 2025) also reconstructs changing-topology meshes from multi-view
image loss and uses pixel-area antialiasing in a custom CUDA differentiable
renderer to obtain geometry visibility gradients. It reconstructs meshes from
observations rather than simplifying an authored mesh into a cluster-DAG LOD,
and does not evaluate its result through a separate final hardware MSAA or
upscaler pipeline. This rules out claiming topology-changing image optimization
or antialiasing-derived visibility gradients as new by themselves. See the
[paper](https://openaccess.thecvf.com/content/ICCV2025/html/Son_DMesh_An_Efficient_Differentiable_Mesh_for_Complex_Shapes_ICCV_2025_paper.html),
[supplement](https://openaccess.thecvf.com/content/ICCV2025/supplemental/Son_DMesh_An_Efficient_ICCV_2025_supplemental.pdf),
and [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).

Hierarchy-level fitting also overlaps conceptually with [V3DG (SIGGRAPH
2025)](https://arxiv.org/html/2505.06523), which differentiably fits cluster
levels in a Gaussian representation. Boundary simplification overlaps directly
with [HLOD ASAP (2026)](https://doi.org/10.1111/cgf.70380): its publisher
preview describes a binary progressive-mesh hierarchy with per-neighbor
boundary PMs and compares against Quick-VDR's locked-boundary construction.
The full methods and quantitative results remain unavailable in the reviewed
sources. Triangle-mesh controls must also address
[Quick-VDR](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content).
Adaptive HLOD construction, parent-child vertex interpolation, and crack- and
popping-free view-dependent transitions are also described by Li's SIGGRAPH
Asia 2022 poster and CVMP 2023 paper ([2022 poster abstract](https://www.siggraph.org/wp-content/uploads/2023/01/SA-22-SIGGRAPH-Asia-2022-Posters.html),
[2023 proceedings abstract](https://www.siggraph.org/wp-content/uploads/2023/12/CVMP-23-Proceedings-of-the-20th-ACM-SIGGRAPH-European-Conference-on-Visual-Media-Production.html)).
Li's related i3D 2023 poster paper is available in full and details grid
partitioning, octree-like merges, parent-child displacement bounds, and
viewpoint-dependent vertex blending ([paper](https://i3dsymposium.org/2023/posters/rui_li_paper.pdf)).
It reports 82.4M aggregate HLOD triangles for a 60.0M-triangle source and
170 fps on an integrated-GPU desktop; these are not equal-face comparisons.
The CVMP paper's ACM full text was inaccessible during this review; see the
[prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md) for
review scope. The remaining experiment question is narrow: does fitting a
triangle-mesh hierarchy to a specified final reconstruction operator improve
quality over using that same operator on unoptimized geometry, while retaining
legal cuts and boundaries? This is unproven and is not yet a novelty claim.
Production prior art already uses TAA to blend subpixel Nanite LOD changes,
and Unreal TSR accumulates coverage to stabilize thin geometry; the frozen
two-asset placement control does not test those systems. Any later method claim
must measure an optimization gain over the same actual reconstruction operator,
not over an unfiltered image alone. See the
[prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md).

## Gate 1: evaluate the frozen placement control

Use the frozen adapter built on NVIDIA's public
[nvdiffmodeling](https://github.com/NVlabs/nvdiffmodeling) source on two
hash-pinned, redistribution-cleared meshes. This is a constrained fixed-
topology control, not a reproduction of the paper: its training call disables
MSAA and uses 2x supersampling with nvdiffrast edge antialiasing. Hasselgren et
al. use MSAA for shape and appearance prefiltering; the paper does not state
that every simplification experiment uses MSAA. Freeze source
meshes, held-out views, lighting, renderer, face targets, AA conditions, and
metrics before scoring. Compare at identical final face counts against current
ManyMesh placement, QEM, and meshoptimizer. Render all arms against a common
reference, both without AA and with the same 4× MSAA. Report LDR-FLIP, PSNR,
SSIM, silhouette/coverage, sampled surface and normal error, topology failures,
preprocessing time, peak memory, and face count. Do not use CPU timing as a
substitute for the documented CUDA baseline.

The pinned training call renders at 2x resolution, enables nvdiffrast edge
antialiasing, disables its MSAA option, and box-averages to 128 x 128. Gate 1
is a differentiable placement baseline, not optimization through the final
hardware 4x MSAA or an upscaler. Gate 2 must separately fit and score against
the same final reconstruction operator before supporting that claim.

This two-asset reused-development screen tests the frozen configuration only;
its held-out views do not establish generalization across assets.

**Pass only** if the control produces repeatable improvement on reserved views
at equal face count without topology regressions. A pass justifies a new,
asset-held-out study. If it fails, close this configuration and do not advance
to a custom DAG optimizer; the result does not falsify differentiable mesh
fitting in general.

## Gate 2: test the cluster-DAG distinction

Only after Gate 1 passes, optimize geometry across topology-distinct DAG levels
for post-reconstruction image quality. First isolate vertex placement with
fixed topology, then compare boundary treatments that allow simplification
without cracks. Check parent/child consistency, legal mixed cuts, manifoldness,
UV/material seams, transition stability, and displacement bounds.

Compare with QEM, meshoptimizer cluster LOD, the frozen fixed-topology
placement control, and progressive-boundary cluster methods. Use both equal-face and
equal-complete-frame-time comparisons. Count optimization, loading, memory,
selection, rendering, AA, and upscaling costs. A differentiable surrogate must
predict outcomes under the actual non-differentiable render pipeline.
If TAA or temporal upscaling is the target operator, include a moving-camera
history sequence and compare against that same operator without geometry
optimization; Binary Opacity Grids already reports moving-camera TAA versus
SSAA for thin-geometry meshes. Static-frame or jitter-only scoring cannot
support a temporal-reconstruction claim.

Use a fresh, licensed, category-balanced confirmation set with at least 20
assets from five or more declared categories. A pre-score Poly Haven candidate
pool now has 30 exact-face eligible models across 25 slug-family groups and
nine categories. Its source and matched-face checks used no rendered images or
quality scores. This satisfies the candidate-count preflight only; it does not
freeze the final camera split, renderer, lighting, full-source reference,
metrics, exclusions, or practical-effect margins. Before scoring, reserve the
asset-level test split and keep every view and camera path from an asset in one
partition. Report paired uncertainty over family groups, not frames. A
development win is not held-out evidence. See the
[candidate-pool report](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md)
and [manifest](tools/mmtrain/polyhaven_confirmation_pool_20261125.json).

## Current blockers and stop conditions

BarramundiFish and Corset are frozen for input feasibility at the 50% request,
with 1,932 and 9,162 triangles per comparison arm. All three controls and the
full-source references have audited OBJ exports. The 30% grid supplied no
qualifying sets. [Matched inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
The reserved-view scorer passed an identity check on a separate development
asset in native sampling and hardware 4× MSAA. The training inputs and camera
schedule are frozen for the [placement-only CUDA control](tools/mmtrain/appearance_cuda_protocol_20261124.json).
Both inputs passed CPU preparation. The NVIDIA extension and full fit still
need a CUDA-capable host. These two assets screen this configuration only. A
[Earlier Poly Haven preflight](tools/mmtrain/POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md)
adds twelve source topology passes across five categories; three pass the
exact-face check at the 50% request. A subsequent catalog-only expansion
reserves 30 eligible models across nine categories, but the final confirmation
split and quality-scoring protocol remain pending. Details and exclusions are
in the [expanded-pool report](tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md).

A fresh `--prepare-only` repeat on 2026-11-25 reproduced both frozen per-asset
protocol files byte-for-byte and verified their input, script, scorer, and
upstream source hashes. It ran under the base Python environment (NumPy 2.5.4,
SciPy 1.15.3), which emitted SciPy's NumPy-version warning; rerun in the pinned
isolated environment for fitting. No CUDA rendering or quality scoring was
performed. See the [repeat receipt](tools/mmtrain/appearance_cuda_preflight_repeat_20261125.json).

Stop if the matched-face baseline loses, if a result depends on tuned views or
assets, if the surrogate fails to rank real-pipeline results, if boundary or
topology checks fail, or if total cost removes the quality gain. A mobile claim
requires a physical phone; a preference claim requires a user study. A benchmark
or silhouette analysis alone is not a SIGGRAPH main-track method contribution.

## Existing evidence

- [13-asset silhouette-fusion report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- [Repeat receipt](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json)
- [Moving-camera desktop screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
