# Cluster geometry decoder: feasibility protocol

Date: 2026-11-22. Status: a sidecar prototype, negative rank-8/16/30 polynomial
linear-subspace and latent-scale screens, and an expanded 2021-2026 prior-art audit. No final-test
gain is established; the tested fixed-displacement and local-refinement
configurations are closed. The tested decoder is not a neural model.
The short entry point is [MANYMESH.md](MANYMESH.md).

## Mechanical prototype

[cluster_decoder.py](tools/mmtrain/cluster_decoder.py) loads per-cluster float32
latents, binds sidecars to mesh/model hashes, locks interfaces and source boundaries,
and emits indexed triangles. One optional centroid split adds exactly two faces
without splitting any shared edge. It checks directed cluster boundaries, edge
incidence/winding, duplicate/degenerate triangles, local flips, and a displacement
cap. It does not check global intersections or vertex-link manifoldness and does
not carry authored UV/normal/material data. These checks do not satisfy the full
publication topology/attribute gate by themselves.

This is not a self-contained compressed asset: `decode(mesh, ...)` requires the
source mesh as an input, while the sidecar contains latents and refinement-face IDs.
The current screen measures a geometry modifier, not total asset compression. Any
rate or storage claim must count the base mesh stream (including topology and
attributes), sidecar metadata and payload, decoder/model weights, and any external
index needed to load them. Report shared model weights both separately and
amortized over a stated asset count.

The implementation is not independently random-accessible by cluster. `decode()`
loads the complete latent array, visits every cluster, assembles a whole-mesh result,
and recomputes topology for the complete input and output. The current sidecar is
cluster-indexed storage, not evidence of independently decodable patches. A future
cluster-access claim requires a decoder API and sidecar layout that can request a
subset without reading or rebuilding unrelated clusters, plus a test that decodes
neighboring clusters in different orders and verifies bit-exact shared interfaces.

The shared polynomial basis is a deterministic control, not a trained neural decoder.
The [training-only smoke runner](tools/mmtrain/cluster_decoder_pilot.py) uses zero
latents, persists/reloads base geometry and weights, and checks fixed output plus
face refinement. It records complete NPZ sidecar/model sizes and process-wide peak
memory, not GPU memory or a hard operating-system memory cap. Its decode timing
includes sidecar loading and local validation but excludes source parsing, partitioning,
and model-file loading. No quality improvement is inferred from identity decoding.
The [completed training-only screen](tools/mmtrain/CLUSTER_DECODER_SMOKE_20261121.md)
records all 16 assets, 14 tests, actual bytes, audit times, and process peak memory.
The subsequent [image-quality screen](tools/mmtrain/CLUSTER_DECODER_QUALITY_20261121.md)
uses FLIP/LPIPS plus PSNR/SSIM on 12-view renders. The latest [same-face meshoptimizer
comparison](tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md) shows the rank-8 fixed
output cannot improve its vertex-preserving meshoptimizer base. Its local refinement
loses to direct meshoptimizer simplification at equal final face count. No final-test
gain is established.

The follow-up [rank sweep](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md)
varies the shared polynomial basis rank from 8 to 16 and its full 30-dimensional
rank. All fixed-topology ranks lose to same-face QEM on all reported validation
metrics; storage rises and rank 30 rejects two prepared validation outputs. This
closes the tested polynomial subspace family, not learned geometry decoding in
general. The held-out test split remains unused.

The [latent-scale probe](tools/mmtrain/CLUSTER_DECODER_SCALE_PROBE_20261122.md)
multiplies the frozen rank-8 validation latent by 0, .25, .5, .75, and 1. On
the four prepared assets where nonzero variants passed validation, every
nonzero scale worsened PSNR, SSIM, FLIP, and LPIPS relative to the exact alpha-0
base; all paired 95% asset-bootstrap intervals exclude zero in the worse
direction. A fifth asset rejected every nonzero scale under topology/offset
checks. This rules out simple residual over-amplitude as a fix for the tested
direction. The per-asset best scale uses the evaluation views and is only an
oracle diagnostic, not evidence of generalization.

## Negative result against meshoptimizer

The 2026-11-22 development screen compares meshoptimizer 0.18.1 with the earlier
QEM base at identical face counts, then retrains and evaluates the rank-8 control
on meshoptimizer bases. On five paired validation assets, meshoptimizer improves
PSNR by 9.72 dB (95% paired asset bootstrap interval [+6.48, +12.55]), SSIM by
0.0306, and lowers LDR-FLIP from 0.02530 to 0.00775 and LPIPS-SqueezeNet from
0.02386 to 0.00581. The fixed rank-8 output has zero image-metric change because
its decoded displacements are effectively zero.

The budgeted refinement output is compared with meshoptimizer simplified from the
source to exactly the same final triangle count. On four paired validation assets,
it loses 2.02 dB PSNR (95% interval [-2.25, -1.78]), worsens SSIM, FLIP, LPIPS,
silhouette XOR, and sampled Chamfer L1. One additional high-budget baseline was
rejected by the duplicate-face audit, so it is excluded from the paired denominator.
These are development results, not a final test; see the [full report and metric
protocol](tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md) and the paired
[screen receipts](tools/mmtrain/cluster_decoder_meshopt_screen_20261122.json) and
[refinement receipt](tools/mmtrain/cluster_decoder_refine_budget_20261122.json).

Decision: stop the tested rank-8/16/30 polynomial formulations. This does not
establish that all learned mesh reconstruction is ineffective. No production
format or renderer API was changed.

Do not proceed with a render-loss-only variant: differentiable image-space mesh
and shading optimization for simplification/LOD is established by Hasselgren et
al. Any decoder follow-up first needs a precise distinction from Neural
Progressive Meshes and localized learned refinement, then a preflight showing that
the distinction can be measured. The minimum decisive comparison is exact
independent cluster access and seam preservation versus a faithful progressive
compression baseline, at matched geometry bytes, render quality, preprocessing,
load/decode time, and memory. The current prototype has not demonstrated this
advantage; without it, close the decoder branch rather than relabeling the current
mechanism.

## Research question

Can a shared, small CPU decoder plus per-cluster residual latents improve the
quality/triangles/bytes/load-time frontier for conventional rendered meshes while
preserving interfaces between independently decoded clusters?

The candidate contribution must be a concrete mechanism for bounded, compatible
reconstruction and its measured advantage. Cluster granularity and CPU execution
at load time are deployment choices; they do not establish novelty.

## Prior-art comparison

The descriptions below were checked against primary papers and author/institution
pages on 2026-11-22. The full texts of Neural Progressive Meshes and Learned
Localized Mesh Refinement were inspected. They establish overlap, not
implementation equivalence; a code-level, matched-cost comparison is still
needed to verify the remaining distinction.

| Work | Established mechanism | Overlap and next comparison |
|---|---|---|
| [Silhouette Mapping, Harvard TR-1-99](https://dash.harvard.edu/bitstreams/7312037d-a6e3-6bd4-e053-0100007fdf3b/download) | Stores silhouettes sampled from multiple viewpoints, interpolates a nearby-view silhouette, and stencil-clips coarse geometry. | Explicit silhouette reconstruction predates this project. It trades geometric fidelity for view-sampled silhouette data and clipping; compare memory, arbitrary-view behavior, and complete render cost. |
| [Perceptually Guided Simplification of Lit, Textured Meshes, 2002](https://pages.jh.edu/dighamm/version2/research/2003_02_perceptually_guided_simplification_of_lit_textured_meshes.pdf) | Uses a view-dependent perceptual metric for mesh operations, sensitive to silhouettes, texture content, and dynamic lighting. | A silhouette-only learned correction or generic perceptual simplification objective is not a novelty boundary. A new method needs a different measurable mechanism and stronger matched-budget results. |
| [SMAA: Enhanced Subpixel Morphological Antialiasing, 2012](https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2012.03014.x) | Reconstructs image edges using local contrast and pattern classification, with MSAA/SSAA combinations and temporal reprojection options. | The reviewer-suggested silhouette network must beat a strong image-space contour baseline at equal end-to-end cost; edge pixels alone do not establish a geometry contribution. |
| [N-GLOD, CVPR 2021](https://research.nvidia.com/nglod) | Octree feature volume, multiple SDF LODs, interpolation, and direct implicit rendering. | Local features and neural LOD already exist. Compare representation and decode/render cost; emitting triangles is a distinction, not evidence of superiority. |
| [Neural Mesh Simplification, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html) | One-pass vertex sampling, sparse-attention triangle proposals, and triangle classification. | Learning geometry reduction is established. Compare quality, topology, and complete resource cost at matched output size. |
| [Appearance-Driven Automatic 3D Model Simplification, EGSR 2021](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/) | Jointly optimizes triangle meshes and shading models using a differentiable renderer to minimize image-space difference; includes mesh decimation and LOD. | Render-space mesh fitting and appearance-preserving simplification are established. Replacing nearest-surface labels with image loss is not a novelty claim. |
| [Neural Compression for 3D Geometry Sets (NeCGS), ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.html) ([paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.pdf), [code](https://github.com/rsy6318/NeCGS)) | Compresses geometry sets with a shared quantization-aware auto-decoder, per-model embedded features, entropy coding, and a TSDF-Def volume reconstructed to triangle surfaces with deformable marching cubes. Evaluates up to 1,000 Thingi10K models with rate-distortion, Chamfer, normal consistency, F-score, and decompression time. In its AMA resolution-128 ablation, the paper reports 1.493 MB, compression ratio 253.45, Chamfer 3.436 x 10^-3, F1-0.005 0.842, and 98.95 ms inference/decompression on the stated RTX 3090 / Xeon test system. | Direct overlap with shared decoder plus per-asset latent geometry compression and mesh reconstruction; this is a required comparison if ManyMesh claims learned multi-asset compression. Its implicit TSDF-Def / DMC representation is a different output contract; the paper does not report preserving authored mesh attributes or exact source topology. Any distinction on those properties must be demonstrated at matched full bytes, quality, decode cost, and asset contract. The authors' code is public, but it has not yet been built or reproduced here. |
| [Neural Progressive Meshes, SIGGRAPH 2023](https://doi.org/10.1145/3588432.3591531) | Trains a shared subdivision encoder/decoder and stores per-face features, including progressive residual features, for mesh compression and quality-rate control. Its Thingi10K benchmark reports point-to-mesh distance and normal error; at compression ratio 61.39 it reports 4.12 x 10^-4 and 7.19 degrees, respectively, at 25,600 faces. The reported ratio excludes topology transmission. Its CPU-only decoder takes 6.93 s to subdivide a 400-face mesh to 25,600 faces on an i7-12700K. | Closest compression neighbor and a necessary baseline. A shared decoder, residual payload, or low load-time decode is insufficient novelty. A future claim must isolate arbitrary-topology/cluster access or boundary guarantees and beat this method at matched full bytes, rate-distortion, and total cost. The reported timing is a paper reference, not a directly comparable benchmark; reproduce both methods under the same machine, input, and accounting. The author-listed [project page](https://neural-progressive-meshes.github.io/) returned 404 during this audit, so the reference implementation was not verified. Image-space quality is not reported in this comparison, so our render metrics would be complementary, not directly comparable. |
| [Mesh Compression with Quantized Neural Displacement Fields, Eurographics 2025](https://doi.org/10.1111/cgf.70074) | Fits and quantizes a neural displacement field that adds detail to a coarse mesh. | A trained displacement decoder with a compact payload has direct precedent. A new decoder needs a measurable advantage from sharing weights or independently accessing clusters, and must account for the base mesh and displacement representation in its byte budget. |
| [End-to-End Compressed Meshlet Rendering, CGF 2024](https://doi.org/10.1111/cgf.15002) and [Towards Practical Meshlet Compression, VMV 2024](https://doi.org/10.2312/vmv.20241204) | Use local meshlet geometry encoding and GPU decode. Mlakar et al. evaluate local precision under a global error bound. Kuth et al. use a shared position grid to prevent cracks between independently stored meshlets. | These are direct baselines for local compression and shared boundary positions. A CPU decoder must demonstrate an advantage under its target hardware and access contract. |
| [Geometric Rounding and Feature Separation in Meshes, CAD 2019](https://doi.org/10.1016/j.cad.2018.10.003) and [Perception-Driven Adaptive Compression of Static Triangle Meshes, CAD 2015](https://doi.org/10.1016/j.cad.2014.08.002) | The former prepares geometry for safe rounding by separating nearby features. The latter allocates quantization precision according to perceptual relevance. | A quantization extension needs a distinct mechanism beyond preserving topology under coordinate rounding or allocating more bits to visually important regions. |
| [Learned Localized Mesh Refinement, SIGGRAPH Asia 2026](https://doi.org/10.1145/3829340.3842280) ([full arXiv HTML](https://arxiv.org/html/2609.31946), [code](https://github.com/seanxzhan/learned-localized-mesh-refinement)) | The full paper presents a dependency-free vertex-split forest tokenizer and locally conditioned autoregressive model for geometry and topology. Inference can refine selected vertices in arbitrary split orders and leave other regions unchanged; it supports view-dependent face-budget refinement and optional manifold checks. It reports 14.2 s average global generation; its view-dependent example uses under 60% of the full-refinement face count and 55% less runtime. | Local topology-changing refinement and view-dependent budget allocation are established. The paper does not formulate reconstruction-aware optimization of an existing cluster DAG or enforce its shared mixed-cut interfaces. A ManyMesh distinction must demonstrate those precise hierarchy constraints and matched-cost image-quality gains. |
| [Model Simplification through Refinement, 2025 preprint](https://arxiv.org/abs/2507.15186) | Builds simplified models by refining a coarse approximation, guided by curvature, with interactive-time targets. | Coarse-to-fine construction and refinement as an alternative to precomputed decimation are established. A load-time decoder needs a separate resource/quality advantage. |
| [MeshOctave, 2026 preprint](https://arxiv.org/abs/2609.38985) | Learns dyadic resolution transitions as per-face split-and-rewire tokens with discrete diffusion. | Learned topology-changing refinement and multi-scale mesh reconstruction are established. A generic local refinement decoder is not a novelty boundary. |
| [Simplifying Textured Triangle Meshes in the Wild, TOG 2025](https://doi.org/10.1145/3763277) | Simplifies non-manifold, disconnected textured meshes as simplicial 2-complexes and transfers appearance without UV-layout dependence. | Robust asset handling and appearance-aware simplification are established. A useful method must test messy authored assets and distinguish its input contract. |
| [Single Edge Collapse Quad-Dominant Mesh Reduction, SIGGRAPH 2025](https://doi.org/10.1145/3731143) | Uses dihedral-weighted quadrics to preserve quad structure under single-edge collapses. | Mesh-quality and structure-aware simplification remains an active, strong baseline area. |
| [Clustered HLOD with As-Simplified-As-Possible Boundaries, 2026](https://doi.org/10.1111/cgf.70380) | Builds progressive internal regions and progressive boundary portions that stay consistent between neighboring clusters. | This directly addresses the fixed-boundary versus simplification-quality tension. Fixed interfaces alone are not novel; compare boundary quality and crack-free transitions. |
| [UltraMeshRenderer, TOG 2025](https://doi.org/10.1145/3731186) | Uses size-balanced hierarchical patches, coherence-aware LOD selection, and in-place GPU memory management for out-of-core rendering. | Large-mesh rendering, GPU memory bounds, streaming, and temporal coherence are established. A resource claim needs a distinct mechanism and end-to-end comparison. |
| [Appearance-Preserving Scene Aggregation, TOG 2025](https://doi.org/10.1145/3708343) | Represents aggregated scene appearance with a volumetric directional scattering representation. | Scene-level appearance substitution already offers a geometry-independent low-detail path; include it when making broad scene-rendering claims. |

This is an expanded screen, not an exhaustive novelty search. Inspect full papers,
supplementary material, and implementations before making a novelty claim. Include
classical progressive meshes, displacement/detail encodings, and quantized/meshopt/
Draco representations in any full comparison. Fixed-topology displacement,
budgeted refinement, higher ranks, and latent scaling failed their current validation
screens and are closed in the tested polynomial form. Generic multi-view render-loss
fitting is already established; it cannot be the proposed new mechanism by itself.

The current prototype does not implement the independent cluster access that might
separate its storage layout from global learned geometry-set compression or
progressive reconstruction. Do not start a new decoder training run on the basis of
that distinction until a minimal API/data-layout design shows how partial decode
preserves shared boundaries, and until NeCGS, NPM, and deterministic matched-cost
baselines can be run or faithfully reproduced.

## Input and output contract

Use static, edge-manifold triangle meshes first. Preserve all source boundary edges,
material/chart interfaces, winding, and connectivity outside a decoded patch.
Assign canonical positions shared by neighboring clusters one immutable owner.
Displacement of shared boundary positions is exactly zero. New vertices may be
inserted inside faces; do not split an interface edge without a common refinement
contract. Per-corner UV and normal discontinuities must stay distinct.

The CPU runs once at asset loading and outputs ordinary vertices/indices. A research
sidecar stores cluster IDs, input hashes, decoder identity, latent dtype/shape, and
payload. Count the base mesh stream plus sidecar, metadata, scales, quantization
overhead, decoder weights, and external indexes. Report shared weights separately
and amortized over explicit asset counts. Keep `.mmb` and rendering APIs unchanged
during screening.

## Freeze before evaluation

Use the existing licensed 32-asset Thingi10K split: 16 train, 8 validation, 8 test.
The same test assets were already exposed to tile-ranking and super-resolution
screens, so this is a development pilot, not a pristine final evaluation set.
Use train/validation for architecture, latent size, refinement budget, losses,
quantization, and stopping decisions. Freeze hashes/configuration before the one
new decoder test run. A publication claim requires a fresh licensed, balanced
confirmation set with no shared source objects or near duplicates across splits.

Run assets serially under an explicit RAM cap. The first mechanical prototype
must establish zero interface displacement, bounded triangle counts, valid output,
and actual sidecar decoding independently of training. Identity output is a
correctness control; per-asset fitting is an upper bound, never generalization.

## Comparisons and reporting

- Compare fixed-topology displacement and bounded local refinement at equal final
  face counts, including ordinary QEM/Corner, meshoptimizer cluster LOD, and
  deterministic refinement/displacement encodings. Include shared model bytes.
- For compression claims add rate-distortion against meshopt and Draco. Report
  base mesh + sidecar + metadata + model bytes, decoded CPU/GPU bytes, and peak RSS.
- For render-cost claims compare MSAA/SMAA and lower resolution with a named,
  frozen existing upscaler. Measure complete frame cost on identical hardware,
  resolution, lighting, cameras, and submission path; separate build/load costs.
- Report geometric distance and normal error, silhouette XOR, PSNR/SSIM, and
  FLIP/LPIPS. Record metric versions and color conventions. Analyze independent
  camera paths for popping and temporal instability; produce video.
- Pair per-asset measurements; bootstrap assets rather than treating correlated
  frames as independent samples. Show all assets and failures with intervals.
- Audit exact boundary edge equality, manifoldness, duplicates, degeneracy, winding,
  and displacement-induced intersections. Edge invariants alone do not prove a
  globally intersection-free surface. Any rejected output counts as a failure.

Pass only with repeatable held-out Pareto improvement over strong nonlearned
baselines, paired uncertainty supporting the gain, and no boundary/topology
violations. Stop a failed configuration rather than substituting training-set gains.
Only a passed gate justifies Filament integration and a library/pinned-patch package.
Mobile and perceptual claims additionally require device measurements and a user
study respectively. No phone is currently available for the planned evaluation.

## Submission timing

The [official Technical Papers page](https://s2027.siggraph.org/program/technical-papers/)
currently lists form/conflicts on 21 January 2027, paper on 28 January, and upload
on 29 January, all at 22:00 UTC. Checked 2026-11-21. These replace the attachment's
historical estimates. Recheck the program page and detailed policy before submission;
other official overview pages still contain provisional dates. Submission remains
conditional on evidence, anonymization, policy review, and artifact permissions.
