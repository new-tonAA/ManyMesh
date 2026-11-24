# Next experiment gate: differentiable LOD baseline

Updated 2026-11-23. **This is a falsification plan, not a contribution claim.**
The SIGGRAPH 2027 Technical Papers page lists 28 January 2027 as the paper
deadline and says detailed submission instructions are forthcoming. The
schedule does not relax the evidence gate. [Official dates](https://s2027.siggraph.org/program/technical-papers/)

## Candidate question

Can offline appearance optimization improve a constrained triangle-mesh cluster
LOD hierarchy when quality is measured after antialiasing or upscaling? Use one
comparison at matched face count and a separate comparison at matched complete
frame time. The first candidate is an existing differentiable simplification
baseline, not a custom DAG optimizer.

Close prior art includes Hasselgren et al.'s differentiable mesh and shading
optimization for simplification and LOD, silhouette-sensitive view-dependent
simplification, and exact coarse-mesh silhouette clipping. These ideas alone do
not establish novelty. [Hasselgren et al.](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc) · [Luebke and Erikson](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf) · [Sander et al.](https://hhoppe.com/silclip.pdf)

Hierarchy-level fitting also overlaps conceptually with [V3DG (SIGGRAPH
2025)](https://arxiv.org/html/2505.06523), which differentiably fits cluster
levels in a Gaussian representation, and boundary handling overlaps directly
with [HLOD ASAP (2026)](https://doi.org/10.1111/cgf.70380), which progressively
simplifies cluster interfaces. HLOD ASAP's full text and quantitative results
remain to be verified. Triangle-mesh controls must also address
[Quick-VDR](https://diglib.eg.org/server/api/core/bitstreams/c7622379-a7d8-4af9-ae6e-977df7a26ea3/content).
The possible distinction is narrow: a measured algorithmic gain for legal
triangle-mesh DAG cuts under real reconstruction operators. It is unproven.

## Gate 1: reproduce a strong baseline

Use NVIDIA's public [nvdiffmodeling](https://github.com/NVlabs/nvdiffmodeling)
workflow on two hash-pinned, redistribution-cleared meshes. Freeze source
meshes, held-out views, lighting, renderer, face targets, AA conditions, and
metrics before scoring. Compare at identical final face counts against current
ManyMesh placement, QEM, and meshoptimizer. Render all arms against a common
reference, both without AA and with the same 4× MSAA. Report LDR-FLIP, PSNR,
SSIM, silhouette/coverage, sampled surface and normal error, topology failures,
preprocessing time, peak memory, and face count. Do not use CPU timing as a
substitute for the documented CUDA baseline.

**Pass only** if the baseline produces repeatable improvement on held-out views
at equal face count without topology regressions. If it does not, stop the
differentiable-geometry branch before building a custom optimizer.

## Gate 2: test the cluster-DAG distinction

Only after Gate 1 passes, optimize geometry across topology-distinct DAG levels
for post-reconstruction image quality. First isolate vertex placement with
fixed topology, then compare boundary treatments that allow simplification
without cracks. Check parent/child consistency, legal mixed cuts, manifoldness,
UV/material seams, transition stability, and displacement bounds.

Compare with QEM, meshoptimizer cluster LOD, the reproduced differentiable
baseline, and progressive-boundary cluster methods. Use both equal-face and
equal-complete-frame-time comparisons. Count optimization, loading, memory,
selection, rendering, AA, and upscaling costs. A differentiable surrogate must
predict outcomes under the actual non-differentiable render pipeline.

Use a fresh, licensed, category-balanced confirmation set with at least 20
assets from five or more declared categories. Split by asset; keep every view
and camera path from an asset in the same partition. Freeze practical-effect
margins and exclusions before the final test. Report paired uncertainty over
assets, not frames. A development win is not held-out evidence.

## Current blockers and stop conditions

BarramundiFish and Corset are frozen for input feasibility at the 50% request,
with 1,932 and 9,162 triangles per comparison arm. All three controls and the
full-source references have audited OBJ exports. The 30% grid supplied no
qualifying sets. [Matched inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md)
The reserved-view scorer passed an identity check on a separate development
asset in native sampling and hardware 4× MSAA. The training inputs and camera
schedule are frozen for the [placement-only CUDA control](tools/mmtrain/appearance_cuda_protocol_20261124.json).
Both inputs passed CPU preparation. The NVIDIA extension and full fit still
need a CUDA-capable host. These two assets are a falsification pair. A
[Poly Haven preflight](tools/mmtrain/POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md)
adds twelve source topology passes across five categories to the provisional
pool. Three pass the exact-face check at the 50% request. The final
confirmation split remains pending.

Stop if the matched-face baseline loses, if a result depends on tuned views or
assets, if the surrogate fails to rank real-pipeline results, if boundary or
topology checks fail, or if total cost removes the quality gain. A mobile claim
requires a physical phone; a preference claim requires a user study. A benchmark
or silhouette analysis alone is not a SIGGRAPH main-track method contribution.

## Existing evidence

- [13-asset silhouette-fusion report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- [Repeat receipt](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json)
- [Moving-camera desktop screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
