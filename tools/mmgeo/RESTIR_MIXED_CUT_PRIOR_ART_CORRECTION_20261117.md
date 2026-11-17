# ReSTIR with mixed cluster cuts: prior-art correction

Date: 2026-11-17. This corrects the earlier per-ray framing and records a low-confidence
representation hypothesis. It is not a novelty claim or a SIGGRAPH-ready result.

## Correction: the current ManyMesh selector is not per-ray LOD

`selectLodGraphCut` selects one camera-dependent cut for the frame. That cut can contain nodes at
different hierarchy levels, but every ray traces the same selected geometry. It is a spatially
mixed, frame-frozen scene representation, not a rule that changes the mesh after inspecting each
ray's footprint or path history. Calling this “per-ray LOD” was inaccurate for the current
ManyMesh code path.

This distinction matters because the SIGGRAPH 2026 ReSTIR-LoD paper assumes one LOD per object per
frame in its implementation, explicitly equating that choice with every ray seeing the same scene.
Its discussion says the formulation does not require the single-LOD restriction and lists per-ray
LOD selection as future implementation work. It already maps reused surface vertices through UVs,
uses partial bijections for ambiguous charts, and multiplies the path-shift Jacobian by each mapped
vertex's area Jacobian. Therefore “use ReSTIR on a mixed cut,” “add per-ray LOD,” and “multiply
per-vertex Jacobians” are not defensible contributions on their own.

## Strong systems prior art

NVIDIA's public [`vk_lod_clusters`](https://github.com/nvpro-samples/vk_lod_clusters) sample has
continuous cluster LOD, RAM-to-VRAM geometry streaming, a multi-bounce path-tracing mode, and builds
the ray-tracing acceleration structure from the selected streamed cut. Its November 11, 2026
changelog adds hit-based streaming: closest-hit feedback and ray-cone width affect which cluster
groups stay resident and, optionally, their selected LOD. The official
[hit-based streaming design](https://github.com/nvpro-samples/vk_lod_clusters/blob/main/docs/hitbased_streaming.md)
records resident cluster-group hits and uses them to load, unload, and select detail. This closes
generic “ray-guided cluster streaming” as a new direction.

The [RTX Mega Geometry SDK](https://github.com/NVIDIA-RTX/RTXMG) ports that cluster-LOD path to
DX12/Vulkan and provides an HLSL path-tracing sample. Its published README does not document a
ReSTIR integration. Separately, a recent
[public hobby-renderer demonstration](https://www.reddit.com/r/gameenginedevs/comments/1xm7uvx/virtual_geometry_clas_ray_tracing_in_vulkan_100k/)
reports combining `vk_lod_clusters`-style streamed cluster LOD with ReSTIR DI and single-bounce
ReSTIR GI; its code is not public and this is not peer-reviewed evidence. Together these sources
mean that merely connecting ReSTIR to a streamed cluster renderer is already an obvious and
independently explored engineering combination.

## One remaining, testable systems question

The published ReSTIR-LoD implementation uses whole-object LOD transitions. The cluster systems
above choose a spatially mixed cut each frame, and hit-based streaming can alter the resident cut
over subsequent frames. A possible gap is whether a hierarchy can carry **cut-local surface maps**
that make sparse ReSTIR path shifts across those mixed-cut changes cheaper or more reliable than
building/querying a whole-LOD UV inverse map.

A concrete representation hypothesis is to store partial surface correspondences only on
parent-child edges of the simplification hierarchy. For a reservoir vertex, identify its source
cut node and target active cut node, find their hierarchy path, compose the edge maps, and multiply
the corresponding area Jacobians. The map must carry a chart/branch identifier and explicit support
mask; composing partial bijections may reduce support and must never silently turn a missing map
into a valid shift. Primary and reconnection vertices both need mapping, as shown by ReSTIR-LoD's
ablation. If direct UV lookup already gives equal support, quality, and cost, this representation
has no contribution.

This is only a data-structure hypothesis. Progressive-mesh records and reversible edge collapses
already preserve hierarchical surface detail, and the ReSTIR-LoD paper already supplies UV-based
cross-topology mappings. We have not established that parent-child maps compose robustly on
ManyMesh outputs, that they reduce memory or query cost, or that their difference changes a
full-estimator result. The hypothesis must be abandoned if it reduces to an implementation of
existing correspondences without a material measured advantage.

The literature screen further downgrades this representation idea: Hoppe's progressive meshes
store invertible edge-collapse / vertex-split sequences and support selective refinement, while
Liu et al.'s *Surface Simplification using Intrinsic Error Metrics* (TOG 2023) explicitly produces
a bijective fine-to-coarse point map by tracking barycentric coordinates through local
coarsening operations. Thus composing collapse-local maps is already established geometry
processing machinery. The only plausible distinction left would be a substantial ReSTIR-specific
runtime or estimator benefit on streaming mixed cuts; absent that result, close this map-composition
branch as prior-art-adjacent rather than pursue it as the main novelty claim.

## Falsification gate

1. Build the same geometry at matched triangle budgets with direct UV mapping and with composed
   parent-child maps. Include overlapping charts, group-boundary transitions, missing UVs, and
   high reduction ratios; bind every report to the exact mesh and script hashes.
2. Before rendering, compare support, reciprocal-map rate, position/normal error, Jacobian tails,
   map memory, and per-vertex query cost. Include a direct all-pairs UV map as a finite upper bound.
3. If a geometric advantage survives, evaluate it in ReSTIR-LoD with independent random sequences.
   Compare object-wide ReSTIR-LoD, a mixed cut with reuse disabled, a naive reuse control, direct
   UV mapping, and composed maps. Match geometry and path budgets; report image bias/error, variance,
   temporal correlation, successful path-shift rate, map cost, and full-frame time separately.
4. Include the published CGNS/ReSTIR-PT-Enhanced reuse controls where the renderer supports them.
   A lower variance that increases bias, a geometric proxy gain without a full-estimator gain, or a
   mapping-cost win smaller than its construction/residency cost closes the direction.

No direct paper search can establish that nobody has implemented ReSTIR-specific map composition,
but the generic map-composition idea is prior-art-adjacent and is closed as the primary candidate.
The separate reuse-aware collapse-order hypothesis in
[`RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md`](RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md)
remains low confidence. The current machine has a device-level WARP DXR 1.1 capability result, but
no ReSTIR-LoD renderer checkout or ray-tracing dispatch. A successful WARP device query is not
rendering evidence, and WARP cannot support GPU performance claims. No candidate in this branch
has reached SIGGRAPH standard.

## Sources checked

- Wang et al., [Real-Time Level-of-Detail Rendering with ReSTIR, SIGGRAPH 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/wang2026levelofdetail.pdf), especially Sections 4.2–4.4 and 6.
- Hoppe, [Progressive Meshes, SIGGRAPH 1996](https://www.cs.jhu.edu/~misha/ReadingSeminar/Papers/Hoppe96.pdf); Liu et al., [Surface Simplification using Intrinsic Error Metrics, TOG 2023](https://arxiv.org/abs/2305.06410).
- NVIDIA, [`vk_lod_clusters` README](https://github.com/nvpro-samples/vk_lod_clusters), [hit-based streaming design](https://github.com/nvpro-samples/vk_lod_clusters/blob/main/docs/hitbased_streaming.md), and [changelog](https://github.com/nvpro-samples/vk_lod_clusters/blob/main/CHANGELOG.md).
- NVIDIA, [RTX Mega Geometry SDK](https://github.com/NVIDIA-RTX/RTXMG) and its [Cluster LOD documentation](https://github.com/NVIDIA-RTX/RTXMG/blob/main/docs/ClusterLOD.md).
- NVIDIA, [ReSTIR PT integration documentation](https://github.com/NVIDIA-RTX/RTXDI/blob/main/Doc/RestirPT.md), for the runtime path-reuse control surface.

## Renderer availability correction (2026-11-17)

The statement above that no ReSTIR-LoD checkout existed is superseded: its source was cloned to `out/research/restir-lod` at `37d13d9b1f3e76be88aa79109d24b0fe6e4ef6a9` and all six submodules initialized. Packman then failed twice fetching its Python build dependency (`SSLEOFError`), so the checkout remains source-only: no Falcor build, WARP device enumeration through Falcor, DXR dispatch, or ReSTIR frame was produced. A D3D12 WARP Tier 1.1 capability query still does not establish renderer or estimator feasibility. The detailed log and exact bounded stop condition are in [`RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md`](RESTIR_REUSE_AWARE_LOD_HYPOTHESIS_20261116.md).

