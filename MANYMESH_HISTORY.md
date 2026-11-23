# ManyMesh: experimental history

Some older references are listed as repository paths. Their supporting files
were retained in development archives.

This archive preserves the original geometry/reconstruction proposal and subsequent
measurements, including failed hypotheses. Early mobile, perceptual, and novelty
statements describe ambitions, not validated capabilities. The current direction
and evidence gates are in [MANYMESH.md](MANYMESH.md).

## 2026-11-22: cluster-decoder capacity and scale screens

The frozen polynomial residual control was screened at ranks 8, 16, and 30.
None improved the paired validation image metrics, and the higher ranks increased
storage without rescuing fixed-topology quality. A follow-up latent-scale oracle
tested 0, .25, .5, .75, and 1 on five prepared validation assets. Every nonzero
scale worsened PSNR, SSIM, LDR-FLIP, and LPIPS on four paired assets; the fifth
rejected all nonzero decodes under topology/offset checks. These are small
geometry-only development results, not a final-test or universal learned-decoder
claim. See the rank sweep (`tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md`),
scale probe (`tools/mmtrain/CLUSTER_DECODER_SCALE_PROBE_20261122.md`), and
decoder study (`MANYMESH_CLUSTER_DECODER_STUDY.md`).

The original proposal combined adaptive geometry reduction inspired by Nanite with
a small neural image reconstructor, seeking real-time rendering of complex assets
on ordinary mobile devices. Its guiding idea was to exchange unaffordable computation
for controlled approximation error and then compensate through reconstruction.
This analogy to MegaLights' sampling of many lights was motivational, not evidence
of algorithmic equivalence or a performance result.

## 1. Target problem

High-quality characters, large scene assets, and scanned geometry (photogrammetry
or NeRF exports) can increase vertex processing, memory bandwidth, and GPU cost:

```text
More source triangles
        |
        v
More vertex processing and memory traffic
        |
        v
Higher GPU cost and difficulty meeting device frame budgets
```

Traditional authored LOD reduces triangle count at a visual cost. ManyMesh's stated
goal was to reduce actually rendered geometry while reconstructing visual quality.

## 2. Proposed pipeline

```text
High-poly asset
    |
Clustering / mesh simplification
    |
Low-complexity mesh
    |
Renderer (Google Filament; originally targeted mobile deployment)
    |
Low-resolution rendered image
    |
Lightweight neural reconstruction
    |
Final image
```

This is the original design sketch, not an end-to-end device validation.

## 3. Geometry virtualization inspired by Nanite

The proposal scoped a mobile geometry optimization layer rather than the full
Unreal Engine Nanite system, which includes cluster hierarchies, virtualization,
streaming, and software rasterization.

### Step 1: mesh clustering

An illustrative five-million-triangle character is partitioned into clusters:

```text
Cluster 0: 1000 triangles
Cluster 1: 1000 triangles
Cluster 2: 1000 triangles
...
```

Each cluster stores a bounding box, error metric, and triangle count.

### Step 2: screen-space selection

Instead of only distance switches such as `distance > 50m -> LOD2`, the proposal
uses screen error and final visual impact to retain more detail nearby and less
far away. The original sketch described dropping clusters; implemented legal-cut
selection must replace regions while retaining complete coverage.

### Step 3: simplification

Use established algorithms such as QEM. The original example reduces five million
triangles to five hundred thousand, producing a lower-complexity mesh. These counts
illustrate a target, not a recorded experiment.

## 4. Neural image reconstruction

The proposal uses final-image recovery, analogous in intent to DLSS, rather than
recovering deleted geometry directly. Rendering supplies auxiliary buffers:

```text
Low-resolution color
+ depth
+ normals
+ motion vectors
+ geometry error map
```

A geometry error map was proposed to identify regions affected by simplification:
an illustrative face decreases from 50000 to 5000 triangles, with higher indicated
error there. This was an input hypothesis; later experiments below test whether it helps.

Use a small CNN in the class of RenderSR/Mob-FGSR rather than a large network.
The original size target was tens of KB to several MB with real-time phone inference;
that target was not a measurement.

```text
Input -> tiny CNN -> residual detail -> final frame
```

## 5. Proposed joint optimization

The original document called this its innovation; novelty remained to be established.
Instead of a fixed geometry/render/image chain, estimate visual loss and reconstruction
capacity when choosing geometry reduction:

```text
Geometry -> predicted visual loss -> reconstruction capacity -> geometry budget
```

Illustrative policy assumptions:

| Scene | Assumed reconstruction difficulty | Proposed response |
|---|---|---|
| Static building | Easier | Allow fewer polygons |
| Fast-moving character | Harder | Retain more geometry |

The intended objective combined geometry budget and reconstruction capacity to
reduce rendering cost. These assumptions require experiments and are not guarantees.

## 6. Original experiment design

| Configuration | Illustrative target |
|---|---|
| Full-detail baseline | Five million triangles, 1080p |
| Traditional LOD baseline | Five hundred thousand triangles, 720p |
| ManyMesh | Five hundred thousand triangles plus reconstruction, approaching 1080p quality |

These were planned comparisons, not achieved results.

### Metrics

| Metric | Purpose |
|---|---|
| FPS | Throughput |
| GPU time | Compute cost |
| Memory | Device resource cost |
| Triangle count | Geometry reduction |
| PSNR / SSIM / LPIPS | Image quality |
| Power | Mobile deployment cost |

## 7. Milestone roadmap (historical long-term targets)

The following checkboxes preserve the recorded status, not independent confirmation
that every long-term goal was achieved.

- [x] M0: Filament source checkout and Windows desktop core/tools/runnable samples.
- [x] M1 first slice (section 7.2): Stanford Asian Dragon, 7,219,045 triangles;
  headless fixed-camera/material/exposure `samples/mm_bench`; PSNR/SSIM tool
  `tools/mmmetrics/compare.py`, optional LPIPS interface, GPU timing; measured
  traditional-LOD triangle/quality/time baseline.
- [ ] M1 remaining: LPIPS integration, multiview statistics, phone power/thermal data.
- [x] M2 first slice (section 7.1): offline clusters/errors, screen-error selection,
  global and per-cluster QEM chains, offline software geometry error maps. Grouped
  clusters reduce mean error 43% but do not match the global chain's worst error.
- [x] M2 seam protection: shared-index UV/normal charts, shared-vertex adjacency;
  paired collapse of coincident seam sides with welded-topology crack checks;
  six-model visual review (Dragon/Sphere/Monkey/Torus/Cloth/Shapes) without new holes.
- [x] M2 hierarchy/runtime: per-cluster chains plus grouped parents; nonoverlapping
  CPU DAG cuts in O(nodes), with no index assembly in `selectLodGraphCut`; editor
  savings slider, Maximum/Balanced/Aggressive presets, near/far detail control.
- [x] M2 gates: boundary sets, non-manifold edges, duplicate/degenerate/flipped
  triangles, minimum triangle quality, world-position error. Attribute QEM includes
  normals/UV; material/submesh IDs reach DAG nodes and draw primitives.
- [x] M2 storage/GPU: file pages, pluggable asynchronous fetcher, LRU cache, std430
  and indirect structures; real Vulkan compute cut/`vkCmdDrawIndexedIndirect`/
  R32_UINT and D32 visibility-buffer prototype.
- [x] M2 transport: Windows `HttpByteRangeFetcher` uses WinHTTP HTTP/HTTPS, Range,
  redirects; Android/iOS/Linux/macOS use vendored CivetWeb HTTP Range, with platform
  TLS runtime required for HTTPS. `-DMANYMESH_HTTP_CIVETWEB=OFF` selects injected
  `RangeFetcher` instead.
- [ ] M2 remaining: phone HTTP/HTTPS and network-switch validation.
- [ ] M3 mobile neural reconstruction overall (first slice in section 7.3).
- [x] M3 paired multiview data with identical cameras and per-view error maps.
- [x] M3 small CNN: +1.88 dB at equal resolution versus coarse geometry; +0.98 dB
  over bicubic at half resolution. Compare ESPCN/FSRCNN under the same small-data budget.
- [x] M3 error-map ablation: no meaningful stable gain, -0.19 to +0.13 dB.
- [x] M3 temporal accumulation (section 8.5): subpixel jitter/multiframe accumulation
  complements learning, combined +1.35 dB.
- [x] M3 temporal pan/reprojection (section 8.6): exact rotational reprojection and
  naive blend +0.66 dB, versus -1.36 dB without reprojection.
- [x] M3 learned temporal/recursive-history/rejection experiments (sections 8.7-8.9).
  Translating-camera depth rejection was tested, but history gain at motion
  0/0.6/1.2 was -0.30/+0.15/-0.16 dB, not a stable quality source.
- [ ] M3 temporal error signals (section 8.3 item 3) and depth/motion inputs;
  Mob-FGSR uses color, depth, and motion vectors.
- [x] M3 end-to-end cost (section 7.12): coarse render 1.6 ms, same-resolution tiny
  40-167 ms; low-resolution tiny_up 13.6 ms but below bicubic quality.
- [ ] M3 deployment: offline-trained runtime LUT or extremely low-bit quantization
  (section 8.3 item 5); reconstruction cost remains the section 7.12 blocker.
- [ ] M3 LPIPS and phone energy/thermal evaluation.
- [ ] M4 joint optimization overall, originally intended as the paper's core.
- [x] M4 first slice (section 7.10), negative: uniform/screen allocation collapse to
  the same single-object cut; depth-sorted rows favor uniform by 0.56 dB. At 38.5 dB,
  tiny adds only +0.05 dB and reconstruction does not change allocation ranking.
- [x] M4 hard-budget Dragon 7.18% (section 7.10.3): network +1.7 dB, uniform/distance
  differ 0.01 dB; total budget rather than allocation controls this case.
- [x] M4 20-30% allocation/reconstruction interaction: gate floors yield the same cut;
  at 26.44%, history changes PSNR -0.12 dB, SSIM +0.0035, with no positive interaction.
- [x] M4 budget sweep (section 7.10.4): at equal PSNR reconstruction substitutes
  1.6-1.8x faces in easy views, >2-2.7x in difficult views, the first positive M4 result.
- [x] M4 single cross-budget model (section 7.10.5): 1.5-1.7x easy, >2-2.8x difficult;
  unseen 19.20% budget loses only 0.09-0.13 dB, supporting this experimental deployment form.
- [x] M4 multiasset cross-budget check: add 20 Monkey views, lose 0.01-0.09 dB,
  unseen budget gains +0.08 dB; reductions remain >2.8x / >2.0x.
- [x] M4 12+4-view check: reductions remain >2.8x / >2.0x; doubling training views
  changes tiny gains from +1.26 to +1.78 into +1.25 to +1.94 dB ranges.
- [ ] M4 motion-aware geometry budgets and dynamic strategies. Infer budgets from
  reconstruction capability/predicted loss, compare both baselines, and prepare a paper.
- [ ] M5 Android/Vulkan deployment, real-device measurements, power and thermal evaluation.

### 7.1 M2 first-slice results

Code: CPU library `libs/manymesh/` and CLI `tools/mmgeo/`, documented in
`tools/mmgeo/README.md`. These use already-vendored meshoptimizer 0.18:
`meshopt_buildMeshlets`, `meshopt_computeMeshletBounds`, `meshopt_simplify`,
`meshopt_simplifyScale`, with no new dependencies in that implementation.

Input: Stanford Asian Dragon, 3,609,600 vertices / 7,219,045 triangles,
bounds 201.7 x 112.0 x 134.2. Recorded Release timings on 12th-generation Intel,
20 threads:

| Stage | Recorded time |
|---|---:|
| PLY load | 4.5 s |
| Clustering, 56,399 clusters | 9.1 s |
| Five per-cluster LOD levels | 14.0 s |
| Selection and error-map rasterization | <1 s |
| Recorded total | 14.8 s |

The historical total does not equal the listed stage sum. No timing capture here
explains whether stages overlap or use different scopes; do not cite 14.8 s as a
verified sum.

Five-level error comparison at ratio 0.7, level 3 (approximately 34% faces):

| Configuration | Units | Faces | Weighted mean error | Maximum error |
|---|---:|---:|---:|---:|
| Independent clusters | 56,399 | 2,374,748 | 0.013533 | 0.255045 |
| Groups of 8 | 7,050 | 2,468,995 | 0.009080 | 0.175334 |
| Groups of 32 | 1,763 | 2,474,497 | 0.007927 | 0.031153 |
| Groups of 64 | 882 | 2,474,495 | 0.007702 | 0.024651 |
| Global chain, approximately baseline 2 | 1 | 2,476,053 | Not recorded; one global bound | 0.012313 |

The original comparison used `ratio^L` as its common level target. Actual faces
above differ, so this is approximate rather than exactly matched-face evidence.
Independent mean error (about 0.0135) exceeds the global maximum (about 0.0123).
The historical explanation attributes this to locked cluster boundaries preventing
cross-cluster error redistribution; these numbers alone do not isolate causality.

Grouping 1->64 monotonically reduces weighted mean 0.01353->0.00770 (43%) and
maximum about 0.255->0.025. Shared interior edges can collapse while outer group
boundaries stay locked. `groupClusters()` treats a group as a larger cluster,
reusing downstream code. The global maximum 0.0123 still beats group-64's 0.0247,
motivating hierarchical grouping/DAG investigation.

`meshopt_simplify` interprets `target_error` relative to the supplied vertex-buffer
scale. An unconverted 1% means different absolute deformation for different units,
confounding size comparisons. `simplifyClusterInto` in `Simplifier.cpp` converts
to common world-space units.

On this oversampled scan, tightening screen error 20x, 2.0->0.1 px, increases drawn
faces only 27.4%->36.5%; most clusters already reach their coarsest level. The
original interpretation was that scan triangle counts exceed visual need and
geometry processing may dominate; this observation alone does not measure GPU bottlenecks.

#### 7.1.1 Attribute seams and visual acceptance

The first position-only QEM treated seam-duplicated imported vertices as ordinary
interior vertices, allowing clusters across UV/normal discontinuities. Sphere at
about 25% showed dark triangular holes, PSNR 30.75 dB; the corresponding initial
fix had no holes at about 25% and PSNR 37.57 dB.

`clusterize()` now finds connected components via shared indices, partitions charts,
and builds meshlets per chart. `groupClusters()` grows shared-vertex adjacency
rather than consecutive output clusters, preventing groups across attribute seams
or disconnected components.

Same-camera lit `aiDefaultMat.filamat` comparisons at 960x720:

| Model | Retained faces | PSNR | SSIM | Visual observation |
|---|---:|---:|---:|---|
| Stanford Dragon | 34.2% | 35.19 dB | 0.96124 | No holes; softer scales/horns |
| Sphere | 22.4% | 37.32 dB | 0.99163 | Polygonal silhouette; fine seam shading at coarsest level, topology closed |
| Monkey | 24.1% | 28.06 dB | 0.93454 | Coarser eyes/ears/chin; original boundary count |
| Torus | 33.9% | 37.06 dB | 0.99149 | Polygonal appearance, no cracks |
| Cloth | 57.5% | 44.27 dB | 0.99709 | Little visible difference in this view |
| Shapes | 20.4% | 63.10 dB | 0.99995 | Ground and small spheres intact |

Sphere/Torus gain no boundary edges. Monkey keeps 168, exactly the original OBJ's
openings rather than simplification cracks. At this historical stage face material/
submesh IDs were not preserved and QEM remained position-only: production texture/
attribute correctness remained unresolved even though geometry was no longer torn.

### 7.2 M1 first slice: rendering and image-quality baseline

Quantifying the geometry/quality tradeoff required renders and image metrics.
Previously `tools/diffimg` answered tolerance-based change detection, but no
PSNR/SSIM/LPIPS pipeline quantified the amount of degradation. Added components:

- `samples/mm_bench`: offscreen fixed camera/material/lighting/exposure, no UI,
  PNG output, GPU frame-time median/p99/maximum.
- `tools/mmmetrics/compare.py`: PSNR, SSIM, optional LPIPS, and difference maps.

Offscreen rendering must create a camera with `Engine::createCamera()` and attach
it using `View::setCamera()`. A camera manipulator depends on window events for
projection, which headless capture lacks, yielding blank frames without errors.
`hellotriangle` creates its own camera; `material_sandbox` historically captured
ImGui without the model under this setup.

Stanford Asian Dragon global LOD chain, 1280x720, Intel Iris Xe, OpenGL,
six evenly distributed azimuths, one load followed by per-view rendering:

| Faces | Source fraction | Median GPU frame | Median PSNR | Min PSNR | Max PSNR | Median SSIM | Min SSIM |
|---|---:|---:|---:|---:|---:|---:|---:|
| 7,219,045 | 100% | 41.35 ms | -- | -- | -- | -- | -- |
| 5,053,330 | 70% | 28.36 ms | 39.12 dB | 35.69 | 44.39 | 0.9934 | 0.9773 |
| 3,537,268 | 49% | 20.71 ms | 36.40 dB | 31.42 | 41.05 | 0.9850 | 0.9570 |
| 2,476,053 | 34% | 15.26 ms | 35.36 dB | 31.31 | 39.22 | 0.9831 | 0.9554 |
| 1,733,244 | 24% | 10.89 ms | 34.50 dB | 30.92 | 38.58 | 0.9813 | 0.9526 |

A single view can mislead: at 24%, PSNR spans 30.92-38.58 dB, about 7.7 dB. The
initial casually chosen view was near worst, 3.6 dB below median. Report distributions.
At 24% faces GPU time drops about 74%, 41.4->10.9 ms; the recorded comparison to
the 70% row costs about 4.6 dB/0.012 SSIM. This is the first measured traditional-LOD
baseline, not a reference-to-reference quality loss.

Quality loss is uneven: 70%->49% loses about 2.7 dB median, 49%->24% another
1.9 dB. Together with scan oversampling, this motivates error-curve-based budgets
rather than face ratios. At 70%, 88.2% of pixels match exactly, and 97.8% of large
differences (at least eight 8-bit levels) lie on edges, motivating edge-focused
reconstruction/error signals.

At this historical point LPIPS still required `pip install lpips` (torch was
available) and phone power/thermal data were missing. The source's remaining-work
note said multiview statistics were missing and only one fixed view existed,
contradicting the six-view table above; retain that inconsistency explicitly.

### 7.3 M3 first slice: reconstruction and the error-map hypothesis

The geometry error map was originally presented as a candidate novelty: tell the
network which pixels are geometrically wrong. This experiment tests utility, not
novelty. `tools/mmtrain/train.py` uses paired full-detail targets and level-4
clustered inputs at identical cameras plus mmgeo-projected error maps: 16 views,
12 train/four validation, CPU training, networks with tens to hundreds of thousands
of parameters.

- Scale 1: 640x360 coarse->640x360 fine; isolate geometry without changing resolution.
- Scale 2: 320x180 coarse->640x360 fine; combine geometry and resolution losses.

PSNR is median across four validation views; deltas use paired views:

| Method | Scale 1 | Scale 2 |
|---|---:|---:|
| Coarse / bicubic lower control | 31.48 dB | 30.59 dB |
| tiny | 33.36 | 31.57 |
| Small unet | 33.23 | 31.67 |
| ESPCN, CVPR 2016 | 31.90 | 29.56 |
| FSRCNN, ECCV 2016 | 32.07 | 28.69 |

| Method | Error-map gain, scale 1 | Error-map gain, scale 2 |
|---|---:|---:|
| tiny | +0.027 dB | +0.067 dB |
| unet | +0.061 dB | +0.116 dB |
| espcn | -0.004 dB | +0.072 dB |
| fsrcnn | +0.129 dB | -0.193 dB |

Reconstruction helps this setup: tiny changes 31.48->33.36 dB (+1.88), or +0.98 dB
over bicubic at half resolution. The error map adds no meaningful stable gain,
roughly -0.19 to +0.13 dB with sign changing by model/task. Some scale-1 unet/fsrcnn
paired gains share a sign across all four views but remain small. The original
text called these below a perceptual threshold; no user study established that.

Initial diagnoses/hypotheses:

1. The map resembles a silhouette mask. Median covered value is only 15/255 because
   normalization uses a pixel budget far above actual errors. RGB already exposes edges.
2. Level-4 coarse quality is about 31.5 dB, leaving little error for this map to target;
   more aggressive reduction might reveal usefulness.
3. Twelve images/1500 iterations might be insufficient for learning an extra channel.

Proposed follow-ups were stronger compression, per-view map normalization, dozens
of views, or cluster-level conditioning. Later tests examined architecture/data/loss
and the map itself. Kernel-Predicting CNNs (Bako et al., SIGGRAPH 2017) predict spatial
filters rather than pixels, giving auxiliaries a structural role; multibranch/high-resolution
auxiliaries in CGF 2024 joint denoising/upscaling were another reference.

| Experiment | Result | Interpretation within this setup |
|---|---|---|
| Residual tiny versus kernel-predicting kpn | 33.37 versus 31.48 | Tested filter-only architecture cannot synthesize the missing detail; no evidence this alternative fixes the bottleneck |
| unet, 176,000 parameters, versus tiny, 28,000 | 33.23 versus 33.37 | More capacity did not help |
| 1500->6000 iterations | 33.37->33.42 | Longer training gave little gain |
| Per-view map normalization | +0.04 dB | Little benefit |
| Edge/gradient loss, w=2.0 | 33.37->33.50 | Helps preserve edges relative to the blurring L1 solution |

Map diagnostics: 99.3% of image error falls inside its support (mean 0.0186 inside,
0.0000 outside), with quantile error rising 0.0141->0.0235. It predicts error location
but largely duplicates RGB edges, worth only +0.02 to +0.04 dB in these tests.
Useful conditioning would need information RGB cannot expose, such as signed true-surface
offset; that information is not available in the current runtime contract without
retaining the high-detail reference.

The historical interpretation attributes roughly +2.0 dB to learned high-frequency
priors and proposes more data/perceptual/adversarial losses instead of better maps.
This is a diagnosis, not causal proof that every architecture is exhausted. ESPCN/
FSRCNN below bicubic here do not establish inferior architectures: their papers use
tens of thousands of images and around hundreds of thousands of iterations; this
study uses 12 images/1500 iterations. Compare only under this tiny data budget.

### 7.4 Synthetic scene-level test

Earlier single objects exposed nearly all geometry, limiting selection opportunities.
Real levels contain distant or offscreen geometry. Three changes enabled a scene test:

1. Sphere/frustum culling marks clusters the renderer would cull. Previously
   behind-camera depth clamping to the near plane inflated screen errors, selecting
   level 0 and overstating scene faces.
2. mmgeo explicitly supplied cameras now also get scene-scaled near/far planes;
   default far=1000 silently removed geometry beyond 1000 units.
3. `tools/mmscene` assembles a map with optional ground. Bistro/San Miguel/Powerplant/
   Sponza are hundreds of MB to about 1 GB each, impractical on the available slow
   connection. The benchmark is synthetic and weaker than a real scanned level.

Scene: 5x5 copies of a 416,000-face mesh plus 500,000-face ground, total
10,903,075 faces, bounds 2100 x 123 x 2100, ground-height camera, 640x360, Iris Xe.

| Metric | Value |
|---|---|
| Frustum-culled fraction | 49.0% |
| Actually drawn | 1,333,651, 12.2% of scene / 24.0% of visible geometry |
| GPU frame | About 52.8->8.82 ms, about 6x |
| Quality versus full detail | 30.29 dB PSNR / 0.9297 SSIM; 94.0% exact pixels |

About one eighth of triangles yields about 6x speedup, individual runs 4.7-7.1x,
against 8.2x face reduction. The original interpretation was approximately
triangle-proportional time in this workload; it is not a universal scaling law.
The object covers 38% of the image; scene PSNR 30.29 dB is below the single-object
35.7 dB because errors cover nearby surfaces more broadly. The first reported 1.59x
speedup was wrong: offscreen geometry remained full detail in the exported low mesh.
Section 7.5 documents the correction.

### 7.5 RenderDoc exposed a submitted-triangle counting error

The initial claim that one eighth of faces yielded only 1.59x speedup came from a
bug. RenderDoc v1.46 portable, historically at `D:/RenderDoc/`, enabled scripted
capture in three steps (`renderdoccmd` lacks a capture-frame-N argument):

1. `mm_bench --capture-frame N` finds the API via `GetModuleHandle("renderdoc.dll")`
   and calls `TriggerCapture()`. `__has_include` protects optional `renderdoc_app.h`.
2. Run `renderdoccmd capture -c <template> <exe> <args>`. RenderDoc changes working
   directory, so mesh paths must be absolute. Git Bash rewrites paths unless
   `MSYS_NO_PATHCONV=1` is set.
3. `renderdoccmd convert -i rdc -c zip.xml` emits script-readable XML. The portable
   package lacks Python bindings and PyPI has no `renderdoc` package in this setup.

XML showed HR draws 10,903,075 triangles as expected, but LR draws 6,677,900 despite
mmgeo reporting 1,333,651. Culled clusters in `selectImpl` took `continue` before
assigning `levelPerCluster[c]`, leaving default level 0. `selectedTriangles` excluded
them correctly, but `gatherSelection()` wrote their full detail into `selected.ply`.
Thus 6,677,900 = 1,333,651 visible + 5,344,249 culled: actual reduction was
10.9M->6.68M, 1.63x rather than 8x. Offscreen geometry consumed work without changing
the image; quality measurements remained valid while performance attribution failed.

After the fix, three repeats at 640x360:

| Configuration | Measurements |
|---|---|
| HR, 10,903,075 faces | 41.2 / 52.8 / 62.5 ms; median 52.8, about +/-20% |
| LR, 1,333,651 faces, 12.2% | 8.82 / 8.83 / 8.83 ms |
| Speedup | About 6x, individual 4.7-7.1x |

Face reduction 8.2x gives about 6x frame reduction here. Earlier claims of sublinear
benefits or geometry not being the bottleneck were withdrawn, including the earlier
geometry-versus-fragment interpretation. Supporting observations: quadrupling pixels
360p->720p slows LR only 4.5%, HR only 1%; shadow on/off has no timing change;
a 15,000-face offscreen model (effectively empty frame) costs only 0.33 ms.

Validate submitted counts before performance conclusions. The mismatch was between
reported selection and actual draws, visible immediately in a captured frame.
The integrated GPU shared a remote desktop session: LR repeats differ only 0.1%,
but HR varies about +/-20%. Heavy-load absolute times are unreliable; interpret
contemporaneous ratios with that variability rather than claiming phone performance.

### 7.6 Geometry round two: DAG, quality gates, runtime cuts, and distance

This round implemented section 7.1's hierarchy, attributes, gates, and editor controls.
Each cluster has its own LOD chain; parents merge/simplify up to eight children.
One view may choose different levels across subtrees. Nodes retain material/submesh
IDs; rendering splits primitives by `(material, submesh)` rather than one draw for
the entire cut. Normal/UV terms now enter attribute-QEM collapse costs.

Default gates require candidate boundary sets identical to the base, no increased
non-manifold edges, no duplicate/degenerate/flipped triangles, minimum triangle
quality above threshold, and position error within `targetError * mesh scale`.
The added positional gate detects intact topology with distorted surfaces.

Same-camera 1280x720 visual regression, `--no-shadows`:

| Model | Source faces | 50% target | 75% target | PSNR / SSIM |
|---|---:|---|---|---|
| Sphere | 8,064 | 4,032 (50.00%) | 1,736 (21.53%) | s50: 42.01 / 0.99770; s75: 41.18 / 0.99632 |
| Monkey | 15,744 | 7,872 (50.00%) | 5,426 (34.46%) | s75: 38.80 / 0.99157 |
| Torus | 1,152 | 562 (48.78%, seam pair) | Same as 50% | s50: 30.08 / 0.99195 |

These historical target labels refer to savings controls, while ratios in parentheses
are retained faces. Gates reject more aggressive candidates; the UI must show actual
faces, not only requested targets. Torus previously stopped at 66.32% before paired
seam collapse; it reaches 48.78% under the same gate, with zero welded boundaries.

An apparent right-side Sphere notch was a low-detail shadow-map artifact, not a hole:
exported vertex radii were all 0.500000, every edge had two uses, and normals were radial.
`--no-shadows` removed it. Combine no-shadow fixed-camera images with topology/position
checks instead of attributing every rendering artifact to geometry.

`selectLodGraph` projects `accumulatedError / depth`; nearby detail survives longer
under one pixel threshold. `mm_bench --distance-lod --screen-error 2.0` and the
`Distance-aware (near fine, far coarse)` UI/`D` shortcut permit same-view A/B.
At 2 px, near Monkey draws 8,738 faces (55.50%), far Monkey 6,224 (39.53%).
Recorded quality at that threshold: Monkey 42.36 dB / 0.99526, Torus 49.40 / 0.99944,
closer than fixed savings in those views.

Depth must use the bounding sphere's nearest point,
`dot(center-eye, forward)-radius`, clamped to the near plane. Center depth can
underestimate error for large nearby clusters. GeometryError already used nearest
depth, but LodGraph, mmgpu host reference, and GPU `screenError()` did not. They now
share `screenSpaceErrorForSphere()` / `ScreenErrorProjection`, with regression
`ScreenSpaceErrorForSphereUsesNearestDepth`.

Runtime observations:

- DAG construction, attribute QEM, and gates are offline/editor work.
- `selectLodGraphCut` emits nodes without assembling indices/material arrays;
  a 588-node Monkey DAG takes 0.0031 ms per single-thread CPU selection.
- Reuse `LodGraphCut cut` with `selectLodGraphCut(graph, camera, thresholdPx, cut)`.
  Node/per-level capacities persist, avoiding allocation once sufficient. Camera,
  empty-scene, and graph changes reset results; concurrent callers need separate
  outputs. mm_bench uses this API and reuses screen-error arrays for unchanged cuts;
  the value-returning API remains available.
- Full-index editor `selectLodGraph` costs 0.115-0.253 ms in distance mode, or
  0.657-0.892 ms in savings mode including 32 threshold bisections/refinement,
  for Monkey, below 16.7 ms in these measurements.
- UI rendering uses one static flattened node-index buffer and a prebuilt renderable;
  changed cuts call `RenderableManager::setGeometryAt` rather than repacking/uploading
  indices. `--show-original` reuses leaves to reproduce original triangles.

The independent `tools/mmgpu/` Vulkan 1.0 prototype runs compute cut selection,
`vkCmdDrawIndexedIndirect`, and a depth-tested visibility buffer. Torus/Monkey GPU
node sets and face counts match CPU reference, without visibility-depth differences.
It bypasses public Filament RenderableManager, validating algorithm/layout feasibility,
not completed application integration.

At this recorded stage, `mm_bench --gpu-cut` submits compute through private DriverApi
on OpenGL/Vulkan and uses `assembleLodSelection()` for CPU cross-node deduplication/
materials. Torus matches on both backends (`nodeMismatch=0 / triangleMismatch=0`,
nine nodes, 858 triangles). First dispatch costs OpenGL 779 ms / Vulkan 645 ms,
including shader compilation; the same CPU cut costs 0.02-0.05 ms. Shared GLSL 450/
GLES 3.10 cut shaders, GpuLodCutParams, counters, and camera math live in libs/manymesh
for samples/backend tests. Historical compute tests: Vulkan 7/7, OpenGL six passed/
one skipped. GLES checks SPIR-V compilation, not Android drivers. Synchronous readback
and CPU geometry reconstruction remain; default builds do not enable Vulkan.
Persistent backend compute/indirect execution, renderer cut compaction, and Android/iOS
network/GPU validation remain incomplete. Section 7.8 covers seam simplification.

`AsyncLodStreamingCache` provides nonblocking prefetch, pluggable fetchers, and raw
`(byteOffset, byteCount)` transport. WinHTTP HTTP/HTTPS Range passed loopback and
mm_bench `--stream-url` end-to-end checks with zero failed pages. Vendored CivetWeb
HTTP Range passed loopback 206 checks for the portable transport. Cache/decoder share
the interface. Public RenderableManager still lacks indirect submission; production
GPU integration needs backend work or a custom renderer.

Build and selection optimizations, recorded at different historical revisions:

- Replace per-candidate `std::set`/`std::map` in AttributeSimplifier with reserved
  small vectors, sorted edges, and hash sets. Evaluate initial internal edges once.
- Share one NodeMetrics projection/culling pass across 32 ratio-search bisections.
- During slider drag update cuts/statistics; upload on release into persistent indices.
- Reuse localPositions/localToGlobal/localIndices/destination scratch across units.
- Extended-mesh reuse, October 2026: copying the entire mesh per cluster/group was
  unnecessary because gates read position/normal/UV/AO. SimplifyScratch caches base
  snapshots by meshCacheEpoch and appends generated tails. SimplifyProfile records
  extendedMeshSeconds/extendedMeshCopies. Cloth, 74,976 triangles, nine levels,
  `--target-ratio 0.5`: build 21.07->18.63 s (-11.6%); snapshot 3.25 s/2197 copies
  ->0.28 s/120 copies. Output stays 1986 nodes/nine levels/37488 drawn, with bit-identical
  indices, errors, topology. Monkey retains 413 nodes/7124 drawn/worst 20.2738 px.
  `CachedExtendedMeshDoesNotChangeSimplifiedOutput` checks cached epoch versus epoch=0.
- Corner placement evaluation, October 2026: serial Cloth profiles show 11.13 million
  scores and about 49.1 s in repeated barycentrics, area/cross products, acos, and nearest
  queries. Cache BarycentricWeights per placement; one cross product gives normal and
  quality. Use endpoint distances as nearest-query upper bounds, plane distances as
  strict pointTriangleDistance2 lower bounds, and skip rings when a surface-error lower
  bound cannot beat the best. Serial build 101.19->85.93 s (-15.1%); target 49.08->32.64
  (-33.5%); evaluate 63.58->49.34 (-22.4%). Output 1971 nodes/seven levels/37488 drawn/
  worst 8.8090 px, generated counts, topology, and MMB SHA256 remain identical.
  Parallel build 18.63->15.81 s (-15.1%, repeated 15.8-16.5 s), output 1986 nodes/nine
  levels/37488 drawn/worst 7.8916 px, same hash. Bounds preserve ordering and gates.
- selectionFromCut marks shared cross-node vertices and hashes boundary faces only,
  avoiding sorting everything and a redundant index assembly/discard pass.
- Screen/ratio selection share cut cleanup, eliminating cross-node duplicate faces.
- Thread-local generation marks replace whole-source ownership allocation/clearing;
  touch only vertices referenced by the current cut.
- Streaming v3 adds vertexCount, retaining v2 reading. Async prefetch accepts LodGraphCut
  and raw byte ranges; page-table binary search replaces resident-map scans.
- One-time node-index upload reproduces old Torus images exactly, PSNR inf/SSIM 1.0.
- Async request drops queued old-cut pages while allowing active fetches to complete
  and cache. A regression checks obsolete queue cancellation during camera changes.
- Sorted unique vectors replace required-page sets; LRU uses binary search to retain
  pages needed by the current cut, avoiding per-page tree-node allocation.
- HttpByteRangeFetcher supports timeouts, IPv6, and Range validation; WinHTTP also
  redirects. `--stream-url` loads lod_graph.mmb; `--stream-save` exports it.
- BVH nearest-triangle gates replace vertex-by-all-triangles scans; one nearest query
  serves positions and attributes, avoiding two trees. Benefit grows for larger groups.
- Independent cluster chains and same-level groups build in parallel with per-worker
  remap/scratch. Merge in original group order, preserving IDs/children/indices/errors.
- Thread-local duplicate-face hash reuse avoids allocations across ratio-search cuts.
- Cloth, 74,976 triangles/group 8/five levels/ratio 0.7: build 37.02->1.93 s; the
  intermediate BVH/shared-query serial version costs 18.18 s, parallel about 9.4x
  faster. Output remains 1915 nodes/seven levels/252 roots/589 leaves,
  38098/74976=50.81%. Example parallel stages: clusterize 0.060 s, leaf setup 0.021 s,
  chains 0.534 s, groups 1.163 s. Monkey 3.21->0.23 s. Set MANYMESH_BUILD_THREADS=1
  for serial reproduction/A-B.
- Historical suite grows to 44 tests: 43 regular plus HTTP requiring
  MANYMESH_HTTP_RANGE_TEST_URL. Parallel determinism, source/generated cut compaction,
  and four-chart welding regressions are included; regular tests pass.
- Fixed auto-framed 960x720, no shadows: Monkey 50% is 7,872 faces/50.00%/40.99 dB/
  0.99349; aggressive 6,042/38.38%/38.12/0.99009. Torus 562/1,152=48.78%, 40.56/
  0.99655. Differences are contours/normal interpolation, without holes, flips, or
  added non-manifold edges.

Corner profiling and topology cleanup, October 2026:

CornerSimplifyProfile separates setup/evaluate/topology/target/apply; topology splits
neighbor/triangles/local-triangles/local-edges, aggregated into cluster/group profiles.
Topology was about 80% of evaluate, dominated by local triangle sorting/edge uniqueness.
Thread-local generation marks deduplicate neighbors/affected/local triangles. Count
only edges of changed triangles; other counts stay fixed. Non-manifold units fall
back to full two-ring checks; MANYMESH_CORNER_FULL_EDGE_CHECK=1 forces the control.
Three assets produce identical results across paths.

Dead incident triangles incorrectly entered local edge counts, rejecting legal
collapses; after correction Torus briefly reached 346/1,152=30.03%. This exposed
one source corner interpolating to differing UVs across neighbors (maximum difference
0.04). Rejecting that difference stopped Torus at 33.16%. Default behavior now emits
coincident generated vertices per UV cluster, preserving each chart's affine mapping.
`--corner-split-uv 0` reproduces old average-UV behavior; default is 1.

At default gates: Torus target 0.2 ->400/1,152=34.72%, closed, minimum quality 0.2869;
Monkey target 0.3 ->4,712/15,744=29.93%, target 0.2 ->4,162/15,744=26.44%, boundary
168/non-manifold 0/duplicate 0/flipped 0. Remaining Torus group rejections: topology
16/geometry 1. UV is no longer the main blocker. Old 33.16%/38.00% images/metrics use
the UV-rejection version and must not be cited as current defaults.

Corner evaluation drops about 5-10 to 1.5-3.8 microseconds. With the priority change
below, seven-level Monkey DAG costs about 4.5 s, Torus 0.30 s. Full-check Monkey costs
3.6 s in the comparison; the source attributes about 13-15% to the new path itself,
with other differences from more accepted work/levels. These are separate timings,
not a controlled decomposition. Old UV-gate visual control: 960x720 aiDefaultMat,
no shadows, Monkey eye (0,-0.016,3.25), Torus (0,0,3.2), targets origin. Monkey 44.99%
37.80/0.98573, 38.00% 37.37/0.98135; Torus 33.16% 38.94/0.99451. Cloth not rerun;
images show no holes/flips/new boundaries or obvious UV distortion.

Corner priority, 2026-10-19:

Previously the queue used QEM cost even though placement scores measured local
surface deviation. It now uses:

```text
surfaceError/edgeLength + 0.25*uv/limit + 0.1*normal/limit
+ 0.1*barycentricOutside + 0.25*(1-minTriangleQuality) + 1e-6*QEM
```

Quality weight 0.25 balances the Torus/Monkey sweep: 0.10 retains about 4% more
Monkey faces; 0.50 makes the DAG shallower and yields 7,518 faces. Gates, welded
boundaries, and chart splitting are unchanged. At identical targets Torus 0.2 changes
550->400 (47.74%->34.72%), Monkey 0.3 changes 7,124->6,244 (45.25%->39.66%), with zero
new defects. Nearly equal-face fixed-camera 960x720/no-shadow Monkey: new 7,084 versus
old 7,124 gives 35.50 dB/0.98590 versus 34.61/0.98443; mean absolute error 0.002235
versus 0.002421. Torus new 562 versus old 550 gives 37.22/0.99646 versus 37.58/0.99554:
lower PSNR but better SSIM/mean error. Monkey build costs 3.1->4.5 s; cut remains
0.0018 ms. Referenced vertices reduce 7,867->7,402 Monkey, 625->562 Torus, implying
fewer upload bytes but no measured phone gain. Images:
`out/ab-monkey-priority-montage.png`, `out/ab-torus-priority-montage.png`.

Attribute-error chart selection, 2026-10-19:

measureCandidateErrors formerly interpolated normal/UV from one nearest triangle.
Coincident chart duplicates could cause the BVH to pick another chart, falsely
reporting 45-72-degree normal or 0.55-0.68 UV errors. Position still uses the true
nearest triangle; attributes choose the closest source normal/UV among candidates
within `bestDistance + tinyTieTolerance`. No gate/topology/boundary thresholds change.
Monkey target 0.3 changes 6,244/39.66% ->4,712/29.93%, target 0.2 reaches 4,162/26.44%;
group attribute rejects 80->12, same `--quality-debug 1` build 4.47->3.23 s. Remaining
12 rejects still show max normal 45-72 degrees, mean 1-5; retain gates and investigate
generated-reference errors versus real seam loss. Same camera/reference, 960x720/no
shadows, 6,244 faces: new 27.10/0.97167 versus old 25.24/0.92891. At 26.44% facets
remain visible, but no holes/flips/new boundaries. Images:
`out/ab-monkey-attrfix-ref.png`, `out/ab-monkey-attrfix-4162.png`,
`out/ab-monkey-attrfix-6244.png`. Regression:
AttributeMetricsSelectTheSourceChartAtADuplicatePosition matches each coincident chart.

Shared scratch and welded gates, 2026-10-18:

Each Corner attempt copied the entire mesh (Cloth 38k source +40k generated vertices)
just to append a few vertices. Per-worker SimplifyScratch now copies the base once per
simplification call, rewriting only generated tails per attempt. Welded topology
measureWeldedTopologyImpl/preservesWeldedBoundaries now hash referenced unit vertices
only and sort uint64_t boundary edges, avoiding whole-model vectors/maps per candidate.
Cloth 74,976 triangles, `--mode dag --levels 7 --cluster-tris 128`: build 8.42->6.63 s
(-21.3%), chains 2.82->2.11, groups 5.07->4.19. Unchanged: 1989 nodes/eight levels/272
roots/589 leaves, 37488/74976=50.00%, boundary 500, zero non-manifold/duplicate/flipped,
cut vertices 30953. Monkey images match exactly (PSNR inf, SSIM 1.0); test_manymesh
57 passed/one skipped. These are CPU optimizations; RenderDoc is useful later for
GPU dispatch/visibility profiling rather than these build timings.

Remaining integration items: public application compute/indirect/storage-buffer API,
persistent GPU buffers/cut compaction, production visibility-buffer integration,
and phone HTTP/HTTPS. CPU source/generated compaction is in section 10.1; three-or-more
coincident copies use Corner welding, including a four-copy regression (section 7.8).

#### 7.6.1 Spatial bisection retry, November 2026

Two changes affect local unit partitioning/evaluation without relaxing quality gates.
First, compare topology using each candidate's own basis. seamCollapse groups measure
welded positions; attribute-QEM/meshoptimizer candidates use raw indices. Comparing raw
candidate boundaries with a welded base's outer boundary incorrectly treated valid
internal seams as holes. acceptable() now receives the measurement mode explicitly.

Pirate 5,010 faces, default split-charts 1/group 8/target 0.55: 158 nodes/seven levels/
46 roots/2,822 faces (56.33%) ->171 nodes/eight levels/45 roots/2,756 faces (55.01%).
`ceil(5010*0.55)=2756`, so the budget becomes exactly reachable. Accepted groups 14->27.
The older unreachable claim in learned-LOD section 14 predates this correction.

Second, if a multimember group fails gates, split its longest bounding-box axis
and independently retry halves, up to two recursive levels (8->4->2). Full gates
still apply; only failed groups incur extra work. Release, same machine/options,
`mmgeo --mode dag --dag-group 8`:

| Asset/target | After basis fix, before retry | With retry | DAG build |
|---|---|---|---|
| Pirate 55% | 2,756 (55.01%), worst 19.62 px, 45 roots | 2,756, 11.93 px, 29 roots | 1.20->1.98 s |
| Pirate 30% | 2,658 (53.05%), 22.32 px | 2,552 (50.94%), 22.32 px | 1.16->1.95 s |
| Lucy 55% | 18,396 (55.00%), 5.89 px, 52 roots | 18,396, 5.38 px, 18 roots | 5.91->9.06 s |
| Lucy 30% | 16,560 (49.51%), 14.35 px | 16,044 (47.97%), 12.04 px | 5.98->9.06 s |
| Monkey/Torus/Sphere | -- | Bit-identical nodes/faces/errors | -- |

Monkey/Torus/Sphere already have only 1-3 roots and no applicable failed groups.
All boundary/non-manifold/duplicate/degenerate/flipped statistics match. Failure-heavy
builds cost about 1.5-1.65x. Intermediate parents permit finer, more evenly distributed
same-budget cuts; Pirate 55% selected nodes increase 48->53. mmgeo now prints:

```text
budget reached: 2756 <= 2756 triangles (55.01% <= 55.01%)
budget unreachable: coarsest legal cut is 2822 triangles (56.33%), budget is 2756 (55.01%)
```

### 7.7 Vulkan prototype: GPU cut, indirect draw, and visibility

`tools/mmgpu/` independently builds an OBJ DAG using Vulkan 1.0 and uploads
GpuLodNode in std430 storage buffers:

1. One invocation per node checks culled/coarse-enough ancestors along parent chains,
   then its own error, producing the same nonoverlapping cut as selectLodGraphCut.
2. Atomic range reservation copies selected indices into compact GPU ranges and emits
   VkDrawIndexedIndirectCommand; firstIndex addresses the range, firstInstance is node ID.
3. Three vertex passes mark referenced source vertices, assign dense IDs/gather
   positions, and rewrite indices. No cross-invocation spin loops are used.
4. vkCmdDrawIndexedIndirect consumes GPU-produced vertex/index/indirect buffers.
5. Fragments write cluster/triangle IDs to R32_UINT attachments, with D32_SFLOAT depth.
6. Readback compares visibility against the CPU reference per pixel.

Intel Iris Xe measurements:

| Scene | CPU cut | GPU cut | Compact vertices | Visible pixels | Node agreement | Triangle agreement | Depth difference |
|---|---|---|---|---:|---:|---:|---:|
| Torus, 640x360, 2 px | 9 nodes / 1,062 tris | 9 / 1,062 | 592 / 637 | 23,700 | 99.99% | 99.93% | 0 |
| Monkey, 640x360, 2 px | 169 nodes / 11,136 tris | 169 / 11,136 | 7,604 / 9,908 | 27,648 | 99.98% | 99.93% | 0 |
| Cloth, 640x360, 2 px | 435 nodes / 36,068 tris | 435 / 36,068 | 18,637 / 38,091 | 32,878 | 99.89% | 99.75% | 0 |

Monkey at 0.5/1/2/4/8 px has identical CPU/GPU selected node sets, face counts,
and culling counts. The historical record also reports 1,152 culled triangles and
zero visible pixels when facing away; the asset for that particular count is not
specified separately. Sub-1% triangle-ID raster differences occur at shared-edge
tie breaks. The source describes node/depth consistency; the table above records
slightly imperfect per-pixel node-ID agreement, so do not read it as exact agreement
at every pixel.

Visual review found no broken surfaces, holes, or contour damage. CPU/GPU/diff
visibility images are in ignored build outputs `out/mmgpu-final-torus/` and
`out/mmgpu-final-monkey/`. GPU draw buffers need no CPU reconstruction/readback.
For all three meshes sorted compact indices match compactLodSelection elementwise;
indirect command count equals selected nodes.

Filament backend compute support exists: VulkanDriver::dispatchCompute, VulkanProgram
compute slots, shared descriptor machinery for compute pipelines/storage buffers,
and dispatch on Noop/OpenGL/WebGPU. DriverAPI drawIndexedIndirect uses Vulkan
vkCmdDrawIndexedIndirect or individual OpenGL glDrawElementsIndirect for GLES 3.1.
An earlier five-case test inventory records Vulkan 5/5 in out/cmake-vulkan with
FILAMENT_SUPPORTS_VULKAN=ON. Cases cover compute SSBO->fragment across bind points,
indirect buffers->fragment, and ComputeTest.manymeshGpuLodNodeTable, uploading exact
buildLodGraph/flattenLodGraph node/index buffers and checking parent/level/ranges
from compute to prevent C++/shader layout drift.

The remaining gap is application-facing Engine handles for persistent storage
buffers, compute programs, and dispatch. The independent prototype does not establish
public Filament renderer integration.

### 7.7.1 OpenGL compute fixes and draw merging

Three bugs prevented effective OpenGL compute:

1. OpenGLProgram queried SSBOs using glGetUniformBlockIndex, conflating uniform/storage
   namespaces and producing GL_INVALID_INDEX instead of a binding map entry.
2. Deferred descriptors updated before draw2 but not dispatchCompute.
3. No post-compute memory barrier guaranteed visibility to buffer copies/readback or
   vertex/index/indirect consumers.

Fixes use glGetProgramResourceIndex with GL_SHADER_STORAGE_BLOCK and
glShaderStorageBlockBinding, falling back to a unique declared binding if GLSL block
and backend/SPIR-V instance names differ. Dispatch updates descriptors first and
issues glMemoryBarrier for shader storage, buffer update, vertex attributes,
element arrays, and command/indirect consumption afterward. In this five-case test
snapshot, OpenGL changed from one pass/one failure to four passes/one skip; Vulkan
passed 5/5. A different expanded seven-case snapshot records Vulkan 7/7 and OpenGL
six passes/one skip in the backend summary. These counts refer to different test
inventories and revisions, not competing results from one run. Both require a
Vulkan-enabled build to execute Vulkan tests; a disabled build cannot run `--api vulkan`.

Individual glDrawElementsIndirect calls support GLES 3.1, where multi-draw indirect
is not core. Intel/WGL rejects indirect sources allocated through the asynchronous/
shared-context path with GL_INVALID_OPERATION. GPU glCopyBufferSubData copies commands
to driver-private scratch before drawing, without CPU readback. Vulkan directly
consumes original indirect buffers.

ComputeTest.graphicsConsumesComputeOutput exposed Vulkan descriptor lifetime loss:
compute commit consumed the pending bindDescriptorSet state, leaving graphics commit
without a set and fragment reads zero. VulkanDescriptorSetCache retains the logically
bound set and rebinds when bind point/layout changes, permitting one SSBO at compute
and graphics points without repeated caller binding. A global VkMemoryBarrier after
dispatch makes compute writes visible to indirect/vertex/uniform/fragment/transfer reads.

RenderDoc shows the 4,626-triangle Monkey cut at 960x540 issuing 1,433
glDrawElementsInstanced calls, about 3.2 triangles/draw. Indices are contiguous,
but mm_bench creates per-node primitives and keeps 1,433 slots, 1,432 with zero indices
in the merged configuration. Empty-primitive traversal drives the CPU overhead.
Merge same-material adjacent index ranges and size renderable primitives to groups,
rebuilding on cut changes. Optional `--compact-cut-indices` concatenates current-cut
indices per material only on cut changes, without rebuilding vertices. Indirect/
multi-draw would avoid repeated uploads in a production path; both controls remain.

| Monkey path, 4,626 / 3,740 triangles | Cut nodes | Draws | CPU steady-state frame |
|---|---:|---:|---:|
| Per node, --no-merge-draws | 1,433 | 1,433 | 72.0 ms |
| Adjacent ranges, default | 1,433 | 1 | 7.4 ms |
| Per node, 50% cut | 560 | 560 | -- |
| Adjacent ranges, 50% cut | 560 | 183 | 35.7 ms |
| 50% with --compact-cut-indices | 560 | 1 | 7.05 ms |

All three full-detail and both 50% images match exactly, RGB max difference zero.
Keep --no-merge-draws to reproduce. GPU frame cost is only 0.21-0.22 ms here: this
repairs Filament/GL submission overhead, not shading or triangle throughput.


### 7.7.2 Current-source cluster cut eligibility audit (2026-11-23)

Reran the pinned meshoptimizer v1.2 depth-1/depth-2 face-budget screen against the current `mmgeo` binary and original Thingi10K source meshes. Across 16 candidate cuts, six passed strict topology and directed-boundary checks; four of those were under the upstream face cap, on two of eight assets. The single face-count match failed topology, leaving no valid exact-face pair for an image-quality comparison. This establishes that the historical eligibility problem also occurs in the current binary, but does not provide a quality ranking. The audit protocol and results (`tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md`) and raw hash-pinned receipt (`tools/mmtrain/current_source_clusterlod_audit_20261123.json`) preserve the run. The first reproduction attempt also found a stale path assumption in the helper; `compare_manymesh_clusterlod.py` now takes the upstream cut directory explicitly.

### 7.8 Paired collapse across UV/normal seams

OBJ duplicates positions at attribute discontinuities. Raw-index topology sees a
boundary on each side; collapsing only one tears the welded surface. Locking both
previously held Torus at 66.32%.

Each unit builds a PositionKey map. AttributeSimplifier pairs seamPartner only for
exactly two copies, both boundary-marked. Three-or-more copies use the slower
CornerSimplifier welded-position path, then emit per-chart generated vertices;
CornerSimplifierHandlesFourChartCopiesAtOnePosition covers four copies.

Paired evaluation/commit:

1. Require candidate (remove,keep) to be a current boundary edge and find its partner.
2. Both sides must still be boundary edges; reject stale partners after neighboring edits.
3. Evaluate each ordinary collapse with seam-boundary permission; reject the pair
   if either side fails.
4. Require disjoint replaced-triangle sets, guarding malformed input.
5. Use maximum of the two errors so one side cannot conceal the other.
6. Apply first then second. Disjoint one-rings on opposite seam sides make the
   paired result equivalent to one atomic edit under these conditions.

After local checks, weld source and candidate indices by position and compare
canonical boundary sets and manifoldness. Commit only unchanged welded boundaries;
this detects changed contours despite unchanged edge counts or one-sided motion.
Single-side boundary collapse remains rejected. LodGraph enables seamCollapse by
default; AttributeSimplifyOptions::seamCollapse and SimplifyOptions::seamCollapse
permit strict-boundary callers to disable it.

Same camera, 1280x720, no shadows:

| Model | Source | Simplified | Retained | PSNR / SSIM | Topology defects |
|---|---:|---:|---:|---|---:|
| Torus before seam pairing | 1,152 | 764 | 66.32% | -- | 0 |
| Torus paired | 1,152 | 562 | 48.78% | 30.08 / 0.99195 | 0 |
| Monkey | 15,744 | 7,872 | 50.00% | 40.99 / 0.99349 | 0 |
| Sphere | 8,064 | 4,030 | 49.98% | 46.19 / 0.99850 | 0 |
| Cloth | 74,976 | 38,098 | 50.81% | -- | 0 |

Defects count non-manifold edges and duplicate/degenerate/flipped triangles.
Welded Torus boundary count is zero. Images:
`out/seam-angle-original.png`, `out/seam-angle-50.png`, `out/seam-angle-75.png`,
`out/seam-monkey-original2.png`, `out/seam-monkey-50.png`, `out/seam-sphere-original.png`,
`out/seam-sphere-50.png`. Review found no holes/cracks/obviously broken surfaces;
50% Torus/Monkey are visibly coarser with main features and contours intact.

The fast path only supports exact pairs. Cross-chart QEM can generate new positions
and interpolate attributes, but extreme cases still stop at geometry/attribute gates;
these gates are not relaxed to obtain lower counts.

Three-plus copies and UV consistency, October 2026:

- Four-copy topology regression is supplemented by
  CornerSimplifierKeepsAttributesOfThreeChartCopiesAtOnePosition: a closed disk of
  three fan charts, with three different UV/normal copies at its center, must not
  merge chart attributes into one output vertex.
- LodGraphKeepsThreeChartCopiesAndTheirUvIslands covers buildLodGraph ->
  selectLodGraphAtRatio ->compactLodSelection, requiring a parent spanning three
  charts and checking each triangle vertex against a chart's affine position->UV map.
- That end-to-end test exposed barycentric extrapolation divergence at coarse levels,
  up to 0.04 UV. Averaging corners broke position/UV correspondence and distorted
  some textured triangles; an earlier version rejected these placements.
- Current output partitions by sourceVertex and UV cluster, allowing coincident
  generated vertices with per-triangle chart UV/normal/AO. Position-welded topology
  remains closed. CornerSimplifierEmitsOneVertexPerDivergentUvCluster checks multiple
  coincident vertices, separate UV islands, and closure. --corner-split-uv defaults
  on; zero permits A/B.
- Same target/gates in mmgeo DAG: Torus target 0.2 is 550/1,152=47.74% on both paths,
  split cut 625 vertices/594 generated versus averaged 587/556, 38 additional UV
  variants. Monkey target 0.3 split 7,124/15,744=45.25% versus averaged 7,256/15,744
  =46.09%, 132 fewer triangles; vertices 7,867 versus 7,922. Both have zero
  non-manifold/duplicate/degenerate/flipped counts and similar UV sign/area ratios.
  Extra coincident vertices remove averaging risk.

### 7.9 Shading compensation: measured benefits and limits

This round implemented and measured a complete shading-compensation path. The
following experiments use different cameras, references, materials, and historical
geometry revisions; their absolute PSNR values are not interchangeable.

Capabilities:

- DetailBake, `mmgeo --bake-normal N`, bakes the difference between source and
  interpolated LOD normals into LOD UVs, producing tangent-space detail-normal.png,
  neutral (128,128,255). LOD vertex normals retain low-frequency shape.
- computeUvTangents() derives per-vertex tangent/handedness from UVs, including
  mirrored charts, replacing arbitrary orthogonal bases in mm_bench.
- `--detail-normal <png> --normal-strength s` uses aiDetailNormal.mat with specular
  antialiasing; `--roughness` permits separate roughness experiments.
- repairShadingNormals(), `mmgeo/mm_bench --shade-crease DEG`, and the UI's Smooth
  seam normals average coincident vertex normals within the crease angle using
  triangle-corner weights. Real hard edges and all geometry stay intact.

Monkey, 960x720, same camera, no shadows, reference 15,744 triangles:

| Variant | PSNR | SSIM |
|---|---:|---:|
| LOD 7,084 faces, 44.99% | 37.17 dB | 0.98708 |
| Detail normal, strength 1.0 | 36.70 | 0.98311 |
| Detail normal, 0.25 | 37.12 | 0.98638 |
| Specular AA only, 0 | 37.18 | 0.98707 |
| Roughness 0.55 | 37.19 | 0.98672 |

Bake coverage at Monkey 45% is 97.4% UV, lost-normal mean 1.28 degrees/max 89.98;
568 mismatched texels remain neutral and are excluded from the mean. At 38%, mean
is 1.45 degrees. Detail normals add shading bands near eyes/muzzle. At 44.99%, the
+/-2-pixel silhouette band covers 1.5% of pixels but 73.4% of squared error; interior
PSNR is 42.85 dB. Shading cannot repair coverage.

The historical diagnosis: Corner preserves source normals in GeneratedVertex.normal,
leaving only roughly 0.7-1.6-degree interpolation error. Source and LOD pixels hit
different surface points; transferring the source normal at the same UV need not
match the reference pixel. Deleted silhouettes, occlusion/contact shadows, thin
structures, and projection changes dominate. Detail normals remain useful for real
microstructure absent from vertex density, such as sculpt-to-game baking, not an
automatic default for normal-preserving decimation. Prefer finer nearby LOD and
investigate source AO/cavity before increasing normal-map strength.

A single 2D map needs a unique [0,1] atlas. The original baker rejects actual referenced
UVs outside that domain: generated Torus [-0.020,1.047], tiled Cloth
[-2.39,5.01] x [0,3.70]. They need unique atlases/per-tile baking to avoid conflicting
surface writes. Monkey initially was the only tested asset passing this check.
A later tolerance correction is recorded below.

#### Height and parallax: near-zero measured gain

bakeDetailHeightMap() rasterizes source and LOD into one UV atlas and computes:

```text
height = dot(sourcePosition - lodPosition, lodNormal)
```

Encode R8 with neutral 128 into detail-height.png and record recommendedUvScale in
a text sidecar. This avoids missed coplanar ray samples and accidentally hitting
another surface layer. Monkey 45% misses fall 12,070->5,481 and mean absolute height
0.0106->0.00154. At 38.19%: 6,408 misses, mean 0.00169. Both recommended scales are
about 0.0414; 512x512 baking costs 163-172 ms.

aiParallax.mat iteratively samples height; CLI/UI expose --detail-height,
--parallax-scale, --parallax-layers, --parallax-strength. getWorldViewVector points
from fragment to camera, so positive height uses:

```text
uv = baseUv + height * viewTangent.xy / viewTangent.z
```

Same-camera 960x720/no shadows, Monkey 44.99%, detail normal plus POM:

| POM strength | PSNR | SSIM |
|---|---:|---:|
| 0 | 40.39 dB | 0.99300 |
| 1.0 | 40.43 | 0.99306 |
| 2.0 | 40.45 | 0.99308 |

At 38.19%, only 40.05->40.10 dB. Across four views POM-0 median/minimum is
42.40/40.05 dB, POM-2 42.38/40.10; median SSIM 0.99534->0.99529. The single-view
roughly 0.06 dB is not robust. Internal resampling cannot recover contours or thin
geometry. Height-gradient micro-normals also fail: strength 1 creates black edge
crusts, 32.65 dB; 0.1 still darkens edges, 40.04 dB. They are not in the default
material. POM remains optional for actual displaced/microstructured assets and
defaults off here. Priorities remain geometry LOD, source AO, and seam repair.

#### Seam normals and strength

selected.ply has 7,724 vertices but 3,628 positions. In 2,179 duplicate-position
groups the normal difference median is 2.47 degrees, P90 11.11, max 42.09. With
crease 10, median becomes 0.01 degrees and pairs above 5 degrees fall
2,318/7,610 ->1,330/7,610; the real 42.09-degree fold stays distinct.

| Monkey 44.99% variant | PSNR | SSIM |
|---|---:|---:|
| Original normals | 41.90 dB | 0.99500 |
| Crease 5 | 41.89 | 0.99499 |
| Crease 10 | 41.90 | 0.99509 |
| Crease 20 | 41.87 | 0.99505 |
| Crease 30 | 41.78 | 0.99515 |

Torus 46.70%, crease 10: 45.81->45.91 dB, SSIM 0.99825->0.99844. Ten degrees
removes nose/cheek bands; 20/30 can blur real eye-socket folds and add dark patches.
Default enabled crease is 10; hard surfaces should use 5 or disable. This repairs
shading discontinuities, not geometry. The same 1.5%-pixel/73.4%-error band remains.

--shade-strength F in [0,1] and UI Shading strength interpolate toward the cluster
mean; zero preserves input, one matches full repair. Normal detail/Roughness sliders
permit independent A/B. --shade-auto / Auto strength (screen error) chooses zero
below 0.25 px, rises smoothly to 0.50 at 1 px, then remains 0.50 rather than flattening
real variation. Same-camera 960x720/no shadows, Monkey 44.99%:

| Strength | PSNR | SSIM |
|---|---:|---:|
| 0 | 41.84 dB | 0.99494 |
| 0.25 | 41.91 | 0.99523 |
| 0.50 | 41.93 | 0.99535 |
| 0.75 | 41.90 | 0.99529 |
| 1.00 | 41.83 | 0.99504 |

At 62.1% and 38.2%, 0.50 also beats zero/one by about +0.09/+0.08 dB.
The policy changes seam normals only.

#### Screen-space cavity: negative result

aiCavity.mat estimates world mean curvature using fragment dFdx/dFdy and darkens
concavities. --shade-cavity/UI Cavity shading sets strength; --curvature-scale sets
world scale, default from bounds. IBL/shadows are needed because ambientOcclusion
does not affect direct-only shading. aiDefaultMat excludes this code; explicitly
select aiCavity.filamat. Monkey 44.99%, 960x720, lightroom_14b IBL, 15,744-face reference:

| Variant | PSNR | SSIM |
|---|---:|---:|
| LOD | 36.29 dB | 0.99293 |
| Cavity 0.10 | 36.00 | 0.99203 |
| Cavity 0.25 | 34.85 | 0.98869 |
| Cavity 0.50 | 31.54 | 0.98047 |

Curvature sees low-mesh facets rather than missing source detail; darkening amplifies
them. Keep it as an artist-controlled experimental material, default zero. The
historical proposed order was source AO/cavity bake, height/displacement/POM, then
temporal/neural reconstruction; none guarantees restoring silhouettes/displacement.

#### Source-mesh vertex AO

AmbientOcclusion uses BVH cosine-hemisphere visibility, baked at LOD vertices without
UV requirements. Offset rays along source normals, default length 10% of source bounds
diagonal. Snap generated points to nearest source triangles first; otherwise points
inside the source falsely appear fully occluded. Average coincident samples to avoid
AO seams. mm_bench --bake-ao --ao-samples 32 --ao-strength 0.5 uses aiBakedAo;
mmgeo --bake-ao 32 [--ao-radius R] writes PLY red channels.

Monkey 15,744->8,660 faces, 55.01%, 960x720/no shadows, 32 samples, radius 0.365,
21,774 LOD vertices, 150-190 ms baking:

| AO strength | PSNR | SSIM |
|---|---:|---:|
| 0 | 41.64 dB | 0.99560 |
| 0.25 | 44.00 | 0.99640 |
| 0.50 | 44.92 | 0.99660 |
| 0.75 | 43.37 | 0.99603 |
| 1.00 | 40.91 | 0.99482 |

Three-view median/minimum: no AO 45.35/41.64, AO-0.50 48.21/44.92 dB; SSIM
0.99804->0.99845. At 62.0/55.0/45.0% cuts, gains +3.78/+3.28/+2.69 dB motivate
fixed 0.50, not increasing strength as faces fall. Crease 10 adds about +0.10 dB/
+0.00023 SSIM. AO changes visibility response, not triangles/contours.

Reference correction: 41.64->44.92 compares against a high-detail reference also
using vertex AO. It does not apply to an unoccluded reference. With an un-AOed
reference, Monkey 44.99%, 960x720, changes 42.51->40.45 dB with vertex AO or 41.77
with texture AO. Match AO representations when claiming restored appearance.

A separate fixed-camera single-frame 55.01% check uses --dag --savings 0 --bake-ao
as high-detail reference: no AO 41.49/0.99595, AO-0.50 46.20/0.99718, mean absolute
error 0.001146->0.000380; plus crease 10 gives 46.21/0.99721. Gain +4.71 dB, error
roughly one third. Different cameras explain differing absolutes. Shadows in eye
sockets/brows/nose/ears improve; silhouette steps/thin structures do not.

#### Unified optional compensation material

aiLodCompensated.mat takes the minimum of source-UV AO map and DAG vertex AO, blends
by aoStrength, optionally adds source-to-current-cut detail normals and roughnessBoost.
Detail-map alpha stores lost angle/90 degrees; roughness changes only where alpha
indicates loss. Old RGB maps read alpha=1. Optional heightMap uses aiParallax sampling
with shared UVs for normal/AO. compensationStrength gates the whole effect for live A/B;
zero was intended as unchanged shading, with a small measured specular-AA difference below.

--shade-compensate selects the material; --compensate-size defaults 512;
--compensate-normal negative default means zero for runtime baking, one for explicit
--detail-normal. --roughness-boost defaults zero. Negative default parallax strength
automatically becomes one only with explicit --detail-height. UI C / Shading
compensation, Compensation amount, Normal detail, Roughness compensation, and Rebake
maps for this cut control the same state. New cuts require normal rebakes; AO maps
are baked once. Missing/tiled/out-of-range UVs fall back to vertex AO and reupload
compact vertices instead of leaving a white AO map.

| Error source | Shading capability | Mechanism |
|---|---|---|
| Coincident seam-normal discontinuity | Reliable local repair | repairShadingNormals / crease 10 |
| Cavities/contact/directional visibility | Partial | Vertex/texture AO, bent normals |
| Current-cut folds/contact | Partial, indirect light | GTAO/SSCT |
| Removed micronormals | Partial, UV/tangent dependent | Detail normals |
| Highlights sharper than remaining geometry | Statistical approximation | Lost-angle roughness |
| Silhouette/thin structure/displacement/coverage | Cannot restore | Geometry gates, AA, distance LOD, shadow proxies for shadow coverage only |

At Monkey 29.38%, silhouette XOR is 0.19% of pixels and 66.7% of squared error;
material strength cannot fix that component. At 45.25%, a 256-square detail map has
mean angle 1.02/max 88.19 degrees, mean alpha 1.59/255, 34.0% nonzero texels, only
257 above alpha 32. Fixed-material 960x720/no shadows, roughnessBoost 0 versus 0.5:
41.088 versus 41.094 dB; 0.008% pixels change by more than one LSB, max 10 LSB.
Forcing alpha 255 produces a 48.9 dB difference and 1.86% changed pixels, confirming
per-texel gating rather than uniform roughness.

Same camera, Monkey 44.99%, 960x720/no shadows; each uses a reference with matching
material representation:

| LOD/reference representation | PSNR | SSIM | Observation |
|---|---:|---:|---|
| No compensation | 42.60 dB | 0.99559 | Source normals and auto seam repair |
| Vertex AO 0.50 | 43.36 | 0.99558 | Recommended in this test |
| 512-square AO map | 42.77 | 0.99529 | Little value over dense vertex interpolation |
| Detail normals | 41.64 | 0.99412 | Worse in this UV/tangent setup |

Within this normal-preserving pipeline, vertex AO and seam repair are the most
consistent surface tools; maps, detail normals, roughness remain optional. The
1.5%-pixel/73.4%-error silhouette band cannot be crossed by shading.

#### Fixed-camera 45.25% error decomposition

960x720/no shadows, eye (1.982729,1.347563,4.480644), target
(0,-0.015564,0.019503), 7,124-face Monkey versus 11,250-face full-detail DAG.
Silhouette XOR: 736 pixels, 0.11%, 68.3% of squared error; common-coverage PSNR
37.24 dB, full image 42.50 dB. Every variant uses its own matching reference:

| Variant | Common-coverage PSNR | Change |
|---|---:|---:|
| No compensation | 37.24 dB | -- |
| Crease 10 / auto | 37.42 | +0.18 |
| AO 0.50 | 37.28 | +0.04 |
| AO + normal 0.25 | 37.17 | -0.07 |
| Roughness 0.40 / 0.60 | 36.25 / 36.62 | -0.99 / -0.62 |

Full-image PSNR in order: 42.50/42.57/42.71/42.67/42.35/42.49 dB.
Artifacts: out/shade-detail-check/. Seam repair is the stable local shading gain;
AO depends on view/cavity exposure. More shading strength cannot remove dominant
coverage error at 30-45% budgets.

| Variant | Full PSNR | Common PSNR | Silhouette XOR share of squared error |
|---|---:|---:|---:|
| No compensation | 42.50 dB | 37.24 dB | 68.3% |
| Crease 10 / auto | 42.57 | 37.42 | 69.1% |
| TAA on reference and LOD | 41.00 | 31.40 | 6.9% |
| Cross-asset tiny CNN | 42.65 | 36.85 | 64.1% |
| Crease + tiny CNN | 42.70 | 36.96 | 64.6% |

After 60 TAA convergence frames, both sides give 41.00/0.99160 versus no-AA
42.50/0.99555. XOR share drops but interior blur dominates. This static case favors
MSAA; it does not rule out temporal rendering with valid motion/history. tiny's
+0.15 dB whole-image gain comes from edges while common coverage loses 0.39 dB;
SSIM rises 0.99555->0.99583. Same-asset Dragon gain +1.88 versus cross-asset +0.15
motivates diverse training or separately reported fine-tuning, not unconditional
recovery. Artifacts: out/temporal-check/.

Historical measured ladder: at least 45% use seam normals/vertex AO 0.5 with matching
references; 25-45% use 4x MSAA/seam normals and error-driven AO fade; below 25% revisit
geometry placement, distance LOD, shadow proxy, or reconstruction. UI presets and
--shade-error-driven encode these heuristics, not a universal optimum.

#### Three assets and three views

960x720/no shadows/--auto-frame --ignore-ceiling, about 45-47% faces. Both sides
use the same AO representation: 256-square maps for Monkey/Torus, automatic vertex
fallback for tiled Cloth.

| Asset/retention | No compensation | Compensation | Delta | SSIM |
|---|---:|---:|---:|---|
| Monkey 44.99% | 45.83 dB | 46.36 dB | +0.53 | 0.99700->0.99812 |
| Torus 43.23% | 45.70 | 45.69 | -0.01 | 0.99813->0.99814 |
| Cloth 46.98% | 38.54 | 44.12 | +5.58 | 0.99238->0.99539 |

Monkey improves around facial cavities; Torus has AO mean 0.998 and little change.
Open Cloth vertex AO mean 0.492 looks darker against a no-AO reference (38.21 versus
44.52 dB), but improves +5.58 dB against matching vertex AO. This restores matching
visibility response, not an unshadowed source appearance. On Monkey, AO-only 46.36
falls to 45.36 with detail normals (-1.00), 42.42 with roughness +0.10 (-3.94).
Keep those optional. compensationStrength=0 differs from the ordinary material at
69.91 dB, recorded mean 0.000013/255, 0.2% of pixels above 1/255, attributed to
specularAntialiasing; these recorded statistics use unspecified aggregation details.

Monkey radius 0.15/0.365 automatic/0.75/1.5 yields 44.91-44.92 dB and SSIM
0.99658-0.99669. Smooth closed Torus AO mean 0.994 gives 45.81->45.80 dB, neutral.
Before snapping correction, inside-source generated vertices caused AO minimum
0.000 and a black inner ring; the corrected result removes that artifact.

Production notes: primarily multiply AO into indirect/IBL. aiBakedAo also modulates
baseColor for direct-only headless controls; avoid double darkening preexisting AO.
Deformation needs updated baking or prebaked local AO. Upload packs UBYTE4 instead
of FLOAT4, 16->4 bytes/vertex; quantization comparison 78.34 dB.

AO enters the source Mesh::ao field, interpolated to generated corners and clamped
[0,1]. `mmgeo --ao-field N` bakes once on source (Monkey 9,908 vertices, 16 samples,
radius 0.365, 46-74 ms), then propagates through nodes/cuts without rebaking per cut.
MMB format version 7 expands generated records nine->ten words, +4 B/vertex; older
files remain readable, missing AO=1.0. Monkey generated AO range 0.000-1.000, mean
0.861 versus source 0.837; PLY red uses 209 values. Regression
LodGraphCarriesAmbientOcclusionThroughSimplification covers interpolation,
serialization, and appendGeneratedVertices extension. It still cannot repair
silhouette/thin/contact geometry or displacement.

#### Optional high-detail shadow proxy

--shadow-proxy draws source or --shadow-proxy-ratio-selected finer geometry only to
shadow maps. shadowProxy.mat disables main color/depth writes; its depth variant
still casts shadows. Share g_lodVertexBuffer and add indices. Visible LOD stops
casting to avoid overlapping contours. UI P / High-poly shadow proxy, detail ratio,
Shadow bias, Shadow normal bias expose controls.

Default sun constantBias=0.001/normalBias=1 self-occludes different source/LOD
surfaces, causing forehead stripes. Proxy defaults 0.010 m/3.0 remove them but can
detach contacts. Monkey same explicit camera, 960x720/default material/sun shadows:

| Cut | No proxy PSNR/SSIM | Proxy PSNR/SSIM | Changed pixels |
|---|---|---|---:|
| 55.01% | 31.23 / 0.99079 | 31.19 / 0.98895 | 0.35% |
| 45.25% | 31.09 / 0.98949 | 31.08 / 0.98780 | 0.36% |

No PSNR benefit in this single-object self-shadow case. Differences cover about
0.3% pixels and 1024-square maps erase small cavities. Expected cross-object/high-resolution
shadow gains remain hypotheses. Default off: it adds a high-detail depth draw and
cannot restore main-camera coverage.

#### Error-weighted compensation and runtime AO

recommendedShadingCompensationWeight returns zero below 0.25 px, reaching one at
1 px. --shade-error-driven stores it in vertex alpha; compensationStrength*alpha
gates AO/bent normal/detail/POM, allowing fine and coarse regions different weights.
Single-object Monkey 50%, 640x360, 128-square AO/16 rays, global versus weighted:
43.76->43.73 dB, no meaningful gain. Default off; mixed-distance usefulness remains
unmeasured. The material uses simple specular AO, with optional bent normal in G/B.

--ssao enables Filament GTAO; --ssct adds screen-space cone tracing along main light
in the same pass, affecting indirect lighting of current-cut folds/contact. No UV,
source mesh, or bake is needed, but each frame adds depth processing and fullscreen AO.
UI controls quality/resolution Half/Full and shares CLI --ssao-quality/--ssao-resolution.
Radius zero means 10% of bounds diagonal; SSCT distance zero means 25%.

Reference and LOD must share settings. Fixed cameras, 3-4 views, 960x720/no shadows/IBL;
median PSNR/SSIM:

| Asset/cut | No SSAO | GTAO | GTAO + SSCT |
|---|---|---|---|
| Cloth 48.09% | 44.82 / 0.99808 | 44.85 / 0.99808 | 45.04 / 0.99809 |
| Monkey 45.25% | 41.68 / 0.99692 | 41.72 / 0.99692 | Not isolated |
| Torus 47.74% | 39.19 / 0.99675 | Not isolated | 39.20 / 0.99673 |

Cloth gains +0.22 dB, Torus is neutral. The historical prose says Monkey +0.08 dB,
while this table's GTAO difference is +0.04; no separate +0.08 measurement is supplied.
Full-resolution High adds about 2.1-2.5 ms median GPU time; half-resolution Medium+SSCT
on Cloth retains 45.04/0.99809 at about +0.88 ms. The original mobile recommendation
for Half/Medium was unvalidated on phones. Source AO remains preferred for source
cavities; screen AO supplements current-cut contact under matching references.

#### 29.38% extreme cut and UV tolerance

Monkey 15,744->4,626 faces, boundary 168 unchanged, other defects zero, same
1024x640 camera/no shadows; high detail uses the same source-UV AO map:

| Variant | PSNR | SSIM | Delta |
|---|---:|---:|---:|
| No compensation | 39.78 dB | 0.99159 | -- |
| AO map 0.5 | 39.81 | 0.99083 | +0.03 |
| Plus normal 0.25 | 39.79 | 0.99077 | +0.01 |
| Normal 1.0 | 39.46 | 0.98934 | -0.35 |
| Normal 1.0 + POM 1.0, front view | 39.46 | 0.98934 | Same as no POM |

XOR covers 0.19% pixels/66.7% error; +/-2-pixel band 1.03%/72.7%; interior PSNR
35.16 dB. The source estimates an ideal-interior whole-image upper value near
45.4 dB without specifying the derivation; keep this as a reported estimate, not a
verified bound. Normal maps at 256-square still yield only 39.49 dB, suggesting
surface correspondence rather than just resolution/noise. Front-view POM has no
visible displacement here. Default pomStrength=0 and explicit --detail-height are
needed to enable it under the shared compensation gate.

Generated UV extrapolation can slightly leave [0,1]. Original tolerance 1e-3 rejected
whole maps at Monkey 29.38% overshoot 0.0008-0.0094. A 2% atlas tolerance permits
small overshoot; genuine tiling/wrap changes such as x3 remain rejected. Rasterization
stays inside texture bounds.

#### UV-space AO map

bakeAmbientOcclusionMap rasterizes source UV triangles, performs BVH cosine-hemisphere
samples per covered texel, and dilates charts four texels. Output R8 via
`mmgeo --bake-ao-map N` ->ao-map.png; mm_bench --ao-map-size N bakes, --ao-map loads,
aiBakedAoMap.mat/UI Baked AO map use shared sample/radius options.

Monkey 512x512/32 samples: 151,190 texels covered (57.7%), mean 0.914/minimum 0.000,
0.57-0.63 s, 256 KiB or about 341 KiB with mips. Tiled/out-of-bounds Torus/Cloth need
unique atlases or vertex AO. One default 3x3 Gaussian smoothing pass averages only
covered texels, then dilates, avoiding interchart bleed. At Monkey 44.99%, map AO
41.77->41.82 dB and cleaner cavities. Moving 512->1024 changes renders by 57.8 dB,
mean absolute difference 0.0285/255, but costs 2.34 s and 4x memory; 512 suffices for
these tested low-frequency cavities.

UI/DAG baking uses high-detail source; ordinary headless baking uses its supplied
mesh, not an implicit high-detail source. Use offline mmgeo source maps and --ao-map
for source-to-LOD comparisons. Monkey 7,084 faces/44.99%, 960x720/no shadows:

| High-detail reference | LOD no AO | LOD vertex AO 0.5 | LOD map AO 0.5 |
|---|---|---|---|
| No AO | 42.51 / 0.99540 | 40.45 / 0.99432 | 41.77 / 0.99376 |
| Vertex AO 0.5 | 40.47 / 0.99424 | 43.17 / 0.99528 | 40.30 / 0.99267 |
| Map AO 0.5 | 41.65 / 0.99380 | 40.23 / 0.99282 | 42.69 / 0.99507 |

Matching vertex references favor vertex AO by +2.87 dB; map references favor maps
by +2.46. Under matching expressions at 55/45/38%, map gains over vertex are only
+0.04/+0.06/+0.08 dB (CPU Lambert recomputation +0.31/+0.27/+0.26). At 7-8 thousand
LOD vertices interpolation is already dense. Maps matter for source-textured AO or
more extreme cuts, not as unconditional replacements. AO changes appearance relative
to no-AO references. Geometry, distance LOD, and tested temporal sampling, not stronger
surface terms, must address missing coverage.

#### Bent normals: effective, but not a PSNR gain

Reuse AO hemisphere samples, cosine-accumulate visible directions, and pair opposite
azimuths so a fully visible surface returns its geometric normal without Monte Carlo
tilt. Average coincident positions to avoid seams. Pack tangent-space xy in vertex
G/B, reconstruct z=sqrt(1-x*x-y*y); R retains AO, so one UBYTE4 carries both with no
extra vertex bandwidth. aiBakedAo sets material.bentNormal for diffuse IBL and
bentNormals specular AO. Assign before prepareMaterial, which transforms/caches
shading_bentNormal; assigning afterward originally produced identical strength-zero/one
images and no lighting effect.

Monkey 44.99%, 1024x640/32 samples/radius 0.365: 17,027 vertices tilt, mean 8.4 degrees,
max 89.6. Strength 0->1 changes mean 0.15/255, max 16/255, 117,400 channels, image
PSNR 50.1 dB, concentrated in cavities. Sun intensity zero gives identical differences,
isolating indirect response. Small amplitude is expected with about 8-degree average
tilt and default direct-light dominance.

Against a bent-normal high-detail reference, strength zero gives 39.59/0.99436,
one 38.98/0.99300. High-detail own toggle is mean 0.13/255/max14, comparable to LOD
0.15/255/max16, but differing surface samples do not align per pixel. Default
--bent-normal-strength is zero. IBL, IBL intensity, sun intensity, and bent-normal
UI/CLI permit artist review. Effects apply only to indirect diffuse/specular visibility,
not geometry/coverage. Procedural IBL is third-order SH; use real environment maps
for assets. Production vertex-colored assets need CUSTOM0/separate attributes to
avoid overwriting authored colors.

#### Torus 20% diagnostic and historical tests

A 20% target, 230 faces, is not blocked by arbitrary rejection of an already acceptable
334-face result: its zero welded boundaries coexist with max geometry error 0.030999
versus budget 0.025108, about 23% excess. A 446-face candidate has acceptable 0.024817
error but 566 welded boundaries versus zero, actual cracks. Under that revision's
UV-split defaults, Torus stops at 550/1,152=47.74%, closed/min quality 0.3228, group
rejects topology16/geometry7. Old 33.16% belongs to an earlier UV-rejection version.
Local-minimum-error placement and budget-triggered alternate placement changed entire
collapse sequences and yielded about 43-48%; those trials were reverted to first-legal
placement. Later section 7.6 entries report subsequent defaults; this archive is not
chronologically sorted by every embedded experiment.

Recorded MSVC Release suite: 76 cases, 75 passed/one HTTP skipped without a local
server. Tests cover three-chart attributes, divergent UV clusters, full DAG
build/select/compact/island preservation, UV-AO coverage/determinism/concavity/tiling,
seam normals/strength/auto policy, source AO determinism/welding/snapping, and height
neutrality/sign/out-of-range rejection. mmgeo/mm_bench/manymesh built and captures ran
in that historical round; these are not tests rerun for the English translation.

#### Equal-AA controls and lower-budget saturation

Monkey 29.38%, 4,626 faces, 1024x640, same camera/default material. Enable identical
AA on high detail and LOD, not only LOD:

| AA on both sides | PSNR | SSIM |
|---|---:|---:|
| None | 39.76 dB | 0.99159 |
| MSAA 2x | 40.87 | 0.99221 |
| MSAA 4x | 41.40 | 0.99262 |
| TAA | 37.92 | 0.99060 |

MSAA gains +1.11/+1.64 dB smooth coverage without restoring deleted geometry.
Eyes/nose/ears remain coarse. Static TAA blurs/mismatches history here.
Reproduce --msaa 4 / --taa; out/shadecomp-monkey29/montage_msaa.png. Phone bandwidth/
fill costs were not measured; the original 2x/dynamic-resolution advice is a hypothesis,
not Android/iOS evidence.

Monkey 26.44%, 4,162 faces, 960x720/no shadows/fixed camera: baseline 26.37/0.96480;
crease10/auto keeps 26.37 but SSIM 0.96567. Vertex AO-0.5 falls 25.14/0.95846,
-1.23 dB, with blocky chin/cheek darkening. Matched 4x MSAA gives 26.39/0.96541,
plus crease 26.38/0.96606. Model coverage is larger than the 29.38% view; MSAA gain
shrinks +1.64->+0.02 dB, so camera-specific gains cannot transfer. Keep material
extras off, retain seam repair for SSIM, and evaluate AA against device budgets.
Artifacts: out/shade26/montage_26.png, shading.json, msaa.json, within.json.

Monkey 38.00%, 5,982 faces, 960x720/no shadows, matching material/AA references:

| Variant | PSNR / SSIM | Comparison |
|---|---|---|
| No AA | 37.38 / 0.98135 | Baseline |
| MSAA 4x | 38.81 / 0.98342 | +1.43 dB |
| AO | 37.33 / 0.98023 | +0.72 versus same-material compensation-off 36.61/0.97843 |
| AO + normal 0.25 | 37.28 / 0.97999 | -0.05 |
| AO + MSAA 4x | 38.69 / 0.98240 | Below MSAA alone |

AO creates blocky neck/chin darkening. Mean normal difference 1.69 degrees is too
small to offset resampling noise. This view favors AA; AO fades only at higher
retention or under suitable IBL. Artifact: out/shadecomp38/montage_38.png.

Automatic framing changes model size, so a fixed-camera --dag --savings 0.62
repeat at 5,982 faces, 38.00%, 960x720/no shadows gives:

| Variant | PSNR | SSIM |
|---|---:|---:|
| No AA | 41.81 dB | 0.99323 |
| MSAA 4x | 42.07 | 0.99355 |
| Crease 10 / auto | 41.94 | 0.99383 |
| Both | 42.17 | 0.99401 |

Gains +0.26 AA/+0.13 seam/+0.36 combined. UI Use measured preset for this cut selects
4x MSAA/crease10-auto and disables AO/normal/POM/roughness below 45%; above it selects
vertex AO0.5/crease10-auto. --auto-shading-preset / Auto apply measured preset reruns
on cut changes; manual controls may override. Geometry choice is unchanged.
recommendedShadingCompensationPreset(retainedRatio,hasCompensation) in
manymesh/ShadingNormals.h and ShadingCompensationPresetFollowsTheMeasuredLadder cover
the 45% threshold, missing-AO fallback, and AA/seam settings.

#### Placement before shading

A later Corner placement trial evaluates keep/remove/midpoint/QEM optimum, tangent-plane
projection, and nearest source-triangle projection rather than returning the first legal
QEM-ranked placement. Ranking combines bidirectional surface deviation, displacement
from rewritten triangle planes, UV/normal errors, and barycentric extrapolation. It
avoids inside-shell optima and chart-UV extrapolation. Historical suite here has
72 cases, 71 passed/one environment-dependent skipped, a different revision from above.

Torus 1,152 faces, same three-quarter camera, 960x720/no shadows/MSAA4, original reference:

| Variant | Faces / retention | PSNR | SSIM |
|---|---|---:|---:|
| Old stress cut | 338 / 29.3% | 31.86 | 0.98370 |
| Surface-only rank, excessive UV extrapolation | 382 / 33.2% | 31.12 | 0.97869 |
| QEM-first | 444 / 38.5% | 32.49 | 0.98693 |
| Surface + plane deviation | 452 / 39.2% | 33.89 | 0.98773 |

At low budgets, keep placements near the source instead of sacrificing surfaces
for a few faces. Old geometric damage costs about 2.4 dB, beyond 0.3-0.4 dB shading/AA
gains. Compared with QEM-first, 1.8% more faces yields +1.40 dB/+0.00080 SSIM.
Stricter plane weight gives 474 faces/34.29 dB; default weight 0.5 is a compromise.
A visible upper-left ring notch in 338/444 results disappears at 452.
Artifact: out/torus-lod-montage-final.png.

Same DAG material/lighting path on reference and LOD avoids PLY-vs-DAG confounding:
Monkey 6,928 faces/44.00%, crease10/auto 43.28->43.39 dB, SSIM 0.99511->0.99549;
Cloth 36,036/48.06%, 40.74->40.78, 0.99046->0.99083. Boundaries stay unchanged and
non-manifold/duplicate/flipped counts zero. These small 0.04-0.11 dB shading gains
repair discontinuities, not coarse Cloth geometry or missing contours. Preserve
geometry gates and use AA/seam repair as modest supplements; reserve AO/detail/POM
for suitable assets and matching references.

### 7.10 M4 first slice: allocation inside reconstruction, a negative result

The original hypothesis was that reconstruction capacity should determine geometry
budgets. First test whether allocating a fixed triangle total differently changes
quality ranking after reconstruction, before training a joint model.

`tools/m4alloc/run.py` compares uniform selectLodGraphAtRatio with distance
selectLodGraph at fixed screen-error threshold. It renders each view separately,
bisects distance thresholds toward uniform's actual faces, then trains identical tiny
configurations with matching seeds/iterations/validation. --ignore-ceiling lets
uniform reach the requested ratio. The historical uniform label describes this
existing ratio selector, not necessarily identical per-cluster reductions in every case.

#### 7.10.1 Single-object cuts provide little allocation freedom

Monkey, 640x360, eight azimuths, nominal 35% budget:

| Policy | Faces | Actual retention |
|---|---:|---:|
| Uniform, --savings 0.65 | 5,504 | 34.96% |
| Distance, calibrated 17.78 px | 5,130 | 32.58% |

Counts differ by 6.8%. More decisively, adjusting uniform to 0.326 (5,130 faces)
or 0.379 (5,966) makes matched-policy renders exactly identical, RGB max diff zero.
With one centered object at similar depths, ratio/screen selectors find the same
DAG plateaus rather than distinct allocations.

| Budget | Policy | Faces | Bicubic | tiny | Paired tiny gain |
|---|---|---:|---:|---:|---:|
| 35% | Uniform | 5,504 | 38.98 dB | 38.98 dB | +0.00 |
| 35% | Distance | 5,130 | 38.32 | 38.34 | +0.01 |

Rounded aggregate columns need not subtract to the paired gain. This configuration
cannot isolate M4 allocation benefits; previous interpretations of single-object
LOD differences as policy differences were withdrawn. Use depth variation/offscreen
geometry, while recognizing other same-object configurations might differ.

#### 7.10.2 Depth-ordered instances still favor uniform

Three Monkey instances along z, 47,232 faces total, near-end camera, four views,
+/-20-degree azimuth, 640x360:

| Policy | Median faces | Bicubic | tiny | Gain |
|---|---:|---:|---:|---:|
| Uniform | 16,532 | 38.52 dB | 38.57 dB | +0.05 |
| Distance, 8.66 px | 16,300 | 37.96 | 38.00 | +0.04 |

Outputs differ on 0.03-0.46% of pixels, with 1.4% different counts; uniform is
about 0.56 dB better before reconstruction. Within the roughly 5.5-9.5-unit depth
range, extra near-detail does not offset lost distant detail. Tiny adds only
0.04-0.05 dB and preserves ranking. Geometry error alone does not measure recoverability.

At target 20%, gates stop uniform at 15,050 faces, 31.86%. Calibrated distance
matches exactly, RGB max diff zero, bicubic/tiny 37.36/37.39 (+0.03). The coarsest
legal cut supplies no alternative here; allocation freedom occurs at intermediate
budgets, where this uniform baseline wins.

The historical next hypothesis sought coarse inputs around 33-35 dB where networks
might add 0.5-1 dB, rather than tuning weights above 35% Monkey budgets. Section 8.9
raises neural gain +0.05->+0.50 dB but temporal history changes PSNR -0.12 dB. More
neural headroom alone still does not establish budget allocation by reconstruction.

#### 7.10.3 Dragon at about 7% of original faces

Use scanned out/m3/lr_mesh.ply, 1,980,131 faces (27.4% of original), build the DAG
once, and export multiple cuts using --target-ratio-cut / --screen-error-cut.
run_preselected.py renders these without rebuilding per camera. Original Dragon
has 7,219,045 faces. The source called this strictly equal-face, but the table
differs by 200 triangles; interpret it as near-equal-face:

| Policy | Faces / original fraction | Bicubic | tiny | Gain |
|---|---|---:|---:|---:|
| Uniform, target 0.262 | 518,585 / 7.18% | 29.81 dB | 31.50 dB | +1.69 |
| Distance, 2 px | 518,385 / 7.18% | 29.80 | 31.51 | +1.71 |

Only 0.01-0.04% pixels differ, quality about 0.01 dB. Both gain about 1.7 dB,
showing useful reconstruction at hard budgets, unlike Monkey's +0.05. In these
cases total geometry matters more than allocation. This motivates asking how much
geometry a reconstruction model substitutes at a quality target, rather than
assuming it must reverse allocation rankings.

#### 7.10.4 Budget sweep: geometry substitution at equal PSNR

Four uniform Dragon budgets, one tiny trained per budget, six training/two validation
views. Reuse eight out/m3 high-detail targets/cameras to avoid repeatedly rendering
7.2 million faces:

| Faces | Original fraction | Bicubic | tiny | Paired gain |
|---|---:|---:|---:|---:|
| 499,277 | 6.92% | 36.25 dB | 37.05 dB | +0.79 |
| 692,833 | 9.60% | 36.84 | 37.75 | +0.91 |
| 989,836 | 13.71% | 37.42 | 38.53 | +1.11 |
| 1,385,804 | 19.20% | 37.88 | 39.10 | +1.22 |

Log-budget interpolation at fixed PSNR:

| Quality | tiny budget | Bicubic budget | Reduction |
|---|---:|---:|---:|
| 37.05 dB | 6.92% | About 10.9% | 1.6x |
| 37.75 | 9.60% | About 17.5% | 1.8x |
| 38.53 | 13.71% | >19.2% | >1.4x |

This is the first positive recorded quality/budget coupling, about 1.6-1.8x at
selected targets, not an end-to-end cost result. Harder v08-v15 views, same budgets:

| Faces | Original fraction | Bicubic | tiny | Gain |
|---|---:|---:|---:|---:|
| 499,277 | 6.92% | 29.58 dB | 30.84 dB | +1.26 |
| 692,833 | 9.60% | 30.25 | 31.57 | +1.32 |
| 989,836 | 13.71% | 30.53 | 32.08 | +1.55 |
| 1,385,804 | 19.20% | 30.72 | 32.51 | +1.78 |

| Quality | tiny budget | Bicubic budget | Reduction |
|---|---:|---:|---:|
| 30.84 dB | 6.92% | >19.2% | >2.7x |
| 31.57 | 9.60% | >19.2% | >2.0x |
| 32.08 | 13.71% | >19.2% | >1.4x |

Hard views show larger substitution than easy ones. The >2.7x value is a lower
bound relative to the measured bicubic range, not a certified bound on arbitrary
budgets or views. The source's assertion that this alone sufficed for a paper was
premature: each budget is trained separately on the same six views, an in-domain
control rather than a single deployable/generalizing model. Section 7.11 mixed
training loses 0.1-0.25 dB. Both view groups have shadows and differ from section
7.10.3's unshadowed front view; compare within tables, not absolute PSNR across them.

#### 7.10.5 One model across budgets

Train tiny on 6.92/9.60/13.71%, fully excluding 19.20% for budget extrapolation;
validate the final two views per budget.

| Hard views v08-v15 | Bicubic | Per-budget | Cross-budget 2000 iterations | Cross-budget 6000 |
|---|---:|---:|---:|---:|
| 6.92% | 29.58 | 30.47 | 30.81 | 30.85 |
| 9.60% | 30.25 | 31.38 | 31.56 | 31.59 |
| 13.71% | 30.53 | 31.94 | 31.95 | 31.98 |
| 19.20%, unseen budget | 30.72 | 32.38 | 32.29 | 32.28 |

| Easy views v00-v07 | Bicubic | Per-budget | Cross-budget 2000 |
|---|---:|---:|---:|
| 6.92% | 36.25 | 37.03 | 36.99 |
| 9.60% | 36.84 | 37.75 | 37.67 |
| 13.71% | 37.42 | 38.53 | 38.41 |
| 19.20%, unseen budget | 37.88 | 39.08 | 38.97 |

Hard-view cross-budget 6000 gains +0.38/+0.21/+0.04 dB versus per-budget on trained
budgets; easy views lose 0.04-0.12. The excluded budget loses roughly 0.09-0.13 dB.
Fixed-PSNR substitution persists: easy 1.5x at 36.99 dB/1.7x at 37.67; hard >2.8x
at 30.85/>2.0x at 31.59. Bicubic only reaches 19.2%, limiting these comparisons.
This supports one frozen model in this experimental domain, not broad asset transfer.
Uniform/distance still differ only 0.01 dB in the preceding test.

Add 20 Monkey training views to Dragon's 18 three-budget views: single object
35% x8, row 31.86% x8, row 35% x4, total38, other settings fixed:

| Budget | Dragon -only cross-budget | With Monkey | Difference |
|---|---:|---:|---:|
| 6.92% | 30.85 | 30.76 | -0.09 |
| 9.60% | 31.59 | 31.56 | -0.03 |
| 13.71% | 31.98 | 31.97 | -0.01 |
| 19.20%, unseen | 32.28 | 32.36 | +0.08 |

Hard-view reductions remain >2.8x at 30.76/>2.0x at 31.56. This checks interference
from a second training asset; it is not an unseen-asset evaluation.

Expand from six training/two validation to 12/four, using all 16 M3 views and holding
out v12-v15, still excluding 19.20% from training:

| Budget | Bicubic | Cross-budget tiny | Gain |
|---|---:|---:|---:|
| 6.92% | 29.69 | 30.94 | +1.25 |
| 9.60% | 30.25 | 31.73 | +1.48 |
| 13.71% | 30.58 | 32.28 | +1.70 |
| 19.20%, unseen | 30.76 | 32.70 | +1.94 |

6.92% tiny30.94 beats19.20% bicubic30.76, preserving >2.8x; 9.60% preserves >2.0x.
Gains change from +1.26-1.78 to +1.25-1.94 as training views double. Four validation
views still vary: at 6.92%, first view 32.5 versus others 30.8-31.0 dB. Report this as
preliminary single-asset Dragon evidence at 7-19% budgets with 12+4 views, requiring
more scans and deployment tests, rather than treating it as SIGGRAPH readiness.

Reproduction, six-plus-two split and excluded 19.20%:

```shell
python tools/mmtrain/train.py --data out/m4-dragon/cross-train \
    --val-data out/m4-dragon/cross-val/budget_989836 \
    --model tiny --scale 1 --iterations 6000 --no-error-map \
    --out out/m4-dragon/cross/cross_tiny
# Evaluate individual budgets, including the excluded budget.
python tools/mmtrain/train.py --data out/dragon-train \
    --val-data out/m4-dragon/cross-val/budget_1385804 --model tiny --scale 1 \
    --no-error-map --eval-only out/m4-dragon/cross/cross_tiny.pt
```

One DAG build exports near-matched cuts, about two minutes in the historical run:

```shell
mmgeo out/m3/lr_mesh.ply --mode dag --target-ratio 0.262 \
    --screen-error-cut 2 --eye 2.220,-6.737,220.771 \
    --look-at 2.220,-6.737,9.837 --out out/m4-dragon/cuts --dump-format ply
python tools/m4alloc/run_preselected.py \
    --uniform-mesh out/m4-dragon/cuts/selected.ply \
    --distance-mesh out/m4-dragon/cuts/selected_px_2.ply \
    --target-mesh out/m3/hr_mesh.ply --out out/m4-dragon/run518 \
    --views 8 --view-span 40 --eye 2.220,-6.737,220.771 \
    --target 2.220,-6.737,9.837 --iterations 2000
```

### 7.11 More training data/capacity: small gains, insufficient magnitude

One alternative explanation for section 7.10's failures was a narrow Dragon prior.
The source describes32 views/three assets/four budgets, but its actual listed inputs
are Dragon and Monkey in single-object/row configurations, not three independent
source assets. They comprise12 Dragon training views plus8 Monkey 35%, four row 35%,
eight row 31.86%; validation remains Dragon 12-15. train.py adds independent --val-data
and --eval-only for frozen-weight transfer.

| Model/data | Dragon validation PSNR | SSIM | Monkey transfer | Row transfer |
|---|---:|---:|---:|---:|
| tiny, Dragon 12, 2000 iterations | 33.42 | 0.9784 | 38.37 | 38.05 |
| tiny, mixed 32, 2000 | 33.14 | 0.9786 | 38.36 | 38.04 |
| tiny, mixed 32, 6000 | 33.33 | 0.9798 | 38.43 | 38.19 |
| unet, mixed 32, 6000 | 33.36 | 0.9800 | 38.46 | 38.30 |

Mixed 2000 does not improve transfer; 6000 adds Monkey +0.06/row +0.14 dB but loses
Dragon 0.09. U-Net transfer gains +0.09/+0.25, Dragon -0.06. These 0.1-0.25 gains fall
short of the hypothesized 0.5-1 dB needed to change M4 rankings. U-Net 176,000 versus
about 20,000 tiny parameters adds only 0.03 dB; longer training adds 0.19. In these tests,
more capacity is not an effective fix, not proof it can never help. Tiny gains 1.7 dB
on 7% geometry but 0.05 on 35%; coarseness controls available recovery more than modest
mixed-data expansion. The historical recommendation was to test hard budgets before
further enlarging a spatial network.

### 7.12 End-to-end cost: inference consumes geometry savings

Quality substitution of 1.5-2.8x faces must be charged against full frame costs.
tools/m4alloc/e2e.py and bench_infer.py measure Dragon 7.2M, 640x360, Iris Xe, PyTorch CPU
eager. GPU rendering, shadows enabled, median over 60 frames:

| Geometry | Resolution | GPU frame |
|---|---|---:|
| Full 7.2M | 640x360 | 23.81 ms |
| Full 7.2M | 320x180 | 20.46 |
| Coarse 499k, 6.92% | 640x360 | 1.59 |
| Coarse 499k, 6.92% | 320x180 | 1.40 |

Quartering pixels speeds full detail only 14%, supporting geometry-dominated cost in
this workload. Tiny has 20,259 parameters, about 79 KiB fp32 or 20 KiB int8 weights;
small weights do not imply cheap full-image convolution.

| Input/model | One thread | Two | Four | Eight | Sixteen |
|---|---:|---:|---:|---:|---:|
| 640x360 tiny | 167.1 ms | 79.3 | 67.8 | 61.3 | 39.9 |
| 320x180 tiny_up, then upsample | 44.6 | 23.7 | 13.6 | 17.7 | -- |

Three 32-channel 3x3 layers at 640x360 require billions of multiply-adds.

| Pipeline | Render | Infer | Sum | Speed versus full | Quality versus full |
|---|---:|---:|---:|---:|---|
| A: coarse640x360+tiny | 1.59 | 39.9, 16 threads | 41.5 ms | 0.57x, slower | 30.94 dB,+1.25 over coarse |
| A, one thread | 1.59 | 167.1 | 168.7 | 0.14x | 30.94 |
| B: coarse320x180+tiny_up | 1.40 | 13.6,four threads | 15.0 | 1.59x | 28.07,bicubic28.69 |

These totals add separately measured render/inference; they do not measure overlapped
execution, transfers, or a deployed integrated runtime. Same-resolution reconstruction
costs 40-167 ms, 25-100x the roughly 1.6 ms render, and is slower than full geometry even
at 16 threads. The source's sentence saying only single-threading was faster contradicts
the table and is withdrawn. Lower-resolution tiny_up is faster but loses to bicubic,
28.07 versus 28.69, and to pipeline A 30.94; the tested low-resolution features do not
recover the needed detail.

Geometry substitution is an in-domain quality observation, not a deployed win.
Suggested next directions: NSS-style parameter prediction/hidden state, offline LUT
(section 8.3 item5), INT8/low-bit quantization, or GPU/NPU inference. Optimized NCNN,
TFLite, or ONNX Runtime might differ, but no phone speedup is measured here.
Same-resolution gain is +1.25 for this validation set; the separate harder-view result
reaches +1.94. Keep those scopes distinct.

Reproduction:

```shell
python tools/m4alloc/e2e.py --model out/m4-dragon/cross/cross16_tiny.pt \
    --budgets 499277:out/m4-dragon/cross16-val/budget_499277:out/m4-dragon/lr-dag2/selected.ply \
    --full-mesh out/m3/hr_mesh.ply --eye 213.1540,-6.7370,9.8370 \
    --target 2.220,-6.737,9.837 --out out/m4-dragon/e2e --threads 16 --shadows
python tools/m4alloc/bench_infer.py --model out/m4-dragon/cross/cross16_tiny.pt \
    --image out/m4-dragon/cross16-val/budget_499277/lr_v00.png \
    --threads 1,2,4,8,16 --sizes 640x360
python tools/m4alloc/bench_infer.py --model out/m4-dragon/cross/cross2_tiny_up.pt \
    --arch tiny_up --scale 2 --image out/m4-dragon/budget16-lr320/budget_499277/lr_v00.png \
    --threads 1,2,4,8 --sizes 320x180
```

## 8. Historical related-work notes and resulting experiments

These are the original literature notes, not a fresh survey or reproduced external
benchmarks. Their dates, hardware, integration status, and exact claims require
primary-source confirmation before reuse in a paper.

### 8.1 Mobile reconstruction notes

| Method | Recorded mechanism | Inputs | Recorded costs/claims |
|---|---|---|---|
| Arm NSS, SIGGRAPH 2025 | Learned temporal upscaling on Arm GPU neural acceleration | Low color, history, motion, depth, jitter, camera matrices, previous hidden tensor | About 4 ms, 540p->1080p, 10 GOPs, INT8 |
| Qualcomm GSR | Handwritten nonneural single-pass spatial upscaling | Current color | Low cost, no motion needed |
| Mob-FGSR, SIGGRAPH 2024, Zhejiang/OPPO/UCSB | Offline MLP baked into runtime LUT, frame generation/upscaling without runtime network | Color/depth/motion, no extra G-buffer | Frame generation about 1.9-2.2 ms, upscaling 1.66 ms; source notes commercial deployment |
| FSR2 / DLSS | Temporal upscaling | Color/history/motion/depth | Original notes questioned mobile suitability; no local device comparison establishes that claim |

The recorded NSS architecture is a four-layer UNet with skips predicting a 4x4
per-pixel kernel, temporal coefficients, and hidden state. About 100 recurrent frames
precede backpropagation, with spatial/temporal losses and rejection masks. These
notes motivated parameter prediction and accumulation, not an assertion that this
repository reproduces NSS or that every phone uses the same execution path.

### 8.2 Mobile geometry notes

| Neighbor | Recorded observation |
|---|---|
| Tencent NanoMesh, SIGGRAPH | Offline clustered hierarchy and runtime streaming/culling/raster/visibility, 80-million-face mobile scene; direct M2 precedent |
| Arm Mali / UE Nanite | Reported 630,000-face tree 5->38 FPS; tile-based vertex throughput and HSR may alter geometry/Z-culling tradeoffs |
| Adreno, Vulkanised 2026 | Reported concerns for visibility buffers, especially 600-series, descriptor indexing, and per-triangle culling versus hardware binning/LRZ |

These historical platform-specific notes do not justify universal hardware claims
or transfer desktop timings to phones.

### 8.3 Five proposed revisions (original heading said four)

1. Add temporal information to the spatial M3 model. NSS/DLSS/FSR2 and the temporal
   parts of Mob-FGSR motivated color history/motion/depth rather than only stronger
   spatial CNNs. This does not imply that every upscaler, including GSR, is temporal,
   or prove temporal information must dominate in our setting.
2. Qualify the earlier KPN rejection: a single-frame filter cannot synthesize all
   absent detail, whereas temporal parameter prediction can combine historical
   samples. A failed spatial KPN is not a rejection of all kernel-predicting methods.
3. Reconsider redundant error maps. Color/depth/motion already serve related systems;
   a temporal geometry-error change might contain information missing from RGB.
   This remains an untested signal hypothesis.
4. Investigate tile-based rendering/HSR geometry costs. The original inference that
   mobile geometry savings must exceed desktop savings was unsupported without device
   measurements. Desktop resolution scaling does not determine phone bottlenecks.
5. Explore offline-learned LUTs or low-bit inference, motivated by Mob-FGSR's
   deployment model, rather than assuming full-resolution CNNs are affordable.

### 8.4 Jittered accumulation and a sampling correction

mm_bench --jitter N renders Halton subpixel offsets from one camera, providing
samples for accumulation. Same-resolution, no learning, two validation views from
six total:

| Accumulated frames | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| Simple-average PSNR | 33.15 | 33.60 | 33.81 | 34.07 dB |

Eight-frame averaging gains +0.92 dB; the recorded six-view trend is monotonic.
Tiny, 2000 iterations:

| Frames | Simple average | Learned |
|---|---:|---:|
| 1 | 33.15 | 34.35 |
| 4 | 33.81 | 34.60 |
| 8 | 34.07 | 34.39 |

Single-frame learning gains 1.2 dB; more frames add only about 0.2. Unlike 540p->1080p,
equal-resolution rendering has no comparable fourfold output-sample deficit.

The earlier scale 2 experiment simulated 320x180 by resizing 640x360. That is not native
low-resolution rendering: resizing averages multiple samples first.

| Source of 320x180 input | Bicubic PSNR at 640x360 |
|---|---:|
| Native render, one sample/pixel | 28.33 dB |
| Resized 640x360 render | 30.12 |

About 1.8 dB discrepancy makes earlier scale 2 values, including 30.59 dB bicubic,
optimistic for native rendering. Resize controls showed only +0.06 dB temporal gain,
versus +0.35 monotonically for native low resolution. Native 320x180,seven jitter frames,
one view v00:

| Accumulated frames | 1 | 2 | 4 | 7 |
|---|---:|---:|---:|---:|
| Bicubic PSNR | 28.33 | 28.49 | 28.62 | 28.68 dB |

This run completed only one of six planned views. The source reports machine
contention (ToDesk 7568 CPU seconds) and about two minutes per 320x180 render before
stopping. The next planned experiment was six views/eight native jitter frames,
then compare learned temporal, single-frame bicubic, and simple averaging.

### 8.5 Native low resolution and accumulation

Redo with native 320x180, not resized, four training/two validation views out of six,
tiny 2000 iterations. Median on the two validation views:

| Configuration | PSNR | SSIM | Gain over simple single frame |
|---|---:|---:|---:|
| Bicubic, one frame | 30.33 | 0.9629 | -- |
| Bicubic, eight-frame average | 31.11 | 0.9668 | +0.78 |
| Learned, one frame | 31.21 | 0.9672 | +0.88 |
| Learned, eight frames | 31.68 | 0.9707 | +1.35 |

Learning and accumulation complement each other here, though gains are not simply
additive: learned eight-frame adds +0.47 over learned single / +0.57 over averaging.
Native 2x upscaling shows a larger temporal contribution than the equal-resolution
+0.2 case. Scope is four training views/two validation, one seed, about 20k parameters;
compare within this corpus, not as general mobile or perceptual evidence.

### 8.6 Rotating-camera history with motion compensation

Section 8.5 stacks one-camera samples without motion. Pure rotation pan provides a
cheap alignment test: no parallax, correspondence depends on rotation rather than
depth and is analytically computable. mm_bench --pan D rotates view direction while
holding eye fixed; tools/mmtemporal/temporal.py reprojects/blends.

Twelve frames, 3-degree pan, native 320x180->640x360,simple exponential blending:

| Configuration | Median PSNR, frames 1-11 |
|---|---:|
| Coarse single frame | 28.27 dB |
| History without reprojection | 26.91 |
| Correct rotational reprojection | 28.93, +0.66 |

Unaligned history loses 1.36 dB from ghosting; alignment makes this blend useful.
The recorded next steps were learned current/history/motion inputs,recursive history,
and occlusion rejection, rather than treating rotation as a disocclusion test.

### 8.7 Learned temporal model and history rejection

Replace blending with a network reading current coarse RGB plus reprojected RGB,
outputting full-detail frames. temporal.py --export emits triples; mmtrain --stack 2 reads them. Same two evaluation frames:

| Configuration | PSNR | Gain over coarse |
|---|---:|---:|
| Coarse single | 28.26 | -- |
| 50/50 history | 28.93 | +0.67 |
| Learned current only | 29.56 | +1.30 |
| Learned current+history | 30.18 | +1.92 |

Learned temporal beats fixed blending +1.25 dB, consistent with useful content-adaptive
history use in this sample. It does not establish broad generalization.

| Color-clipping threshold | Temporal gain |
|---|---:|
| No color rejection | +0.65 dB |
| 0.05 | +0.02 |
| 0.10 | +0.07 |
| 0.20 | +0.21 |

Color clipping hurts this rotational control. Most history is geometrically valid;
current/history differences include the reconstruction errors being averaged, so
rejecting them can discard useful samples. This is a local diagnosis, not a universal
rule about denoising or temporal rejection. Out-of-frame validity masking is always
on, including baseline. True disocclusion requires translating cameras/depth and
is not tested by rotation alone.

### 8.8 More sequence data

The first learned test used one sequence/11 samples and risked overfitting. Expand
to four sequences of eight frames, four azimuths, 3-degree pan,28 training triples and
four validation frames as reported:

| Configuration | PSNR | SSIM | Gain |
|---|---:|---:|---:|
| Coarse single | 31.09 | -- | -- |
| 50/50 blend | 32.04 | -- | +0.95 |
| Learned current | 31.79 | 0.9739 | +0.70 |
| Learned current+history | 32.61 | 0.9779 | +1.52 |

The smaller +0.57 learned-over-blend gain, versus earlier +1.25, is more conservative;
it does not by itself prove the old result was overfitting. The source additionally
reports naive temporal median gain +0.85 over 32 frames, versus section 8.5's +0.78.
These use differing aggregation scopes. Twenty-eight triples/four validation frames/
one seed remain too small for broad claims; multiple scenes/trajectories are needed.
The recorded 28-plus-four counts do not explain whether validation overlaps sequence
samples; no independent split guarantee should be inferred without capture metadata.

### 8.9 Translating cameras, depth reprojection, and disocclusion

Rotation experiments lacked parallax. New capture pipeline:

- mm_bench --translate D --frames N translates eye and target together along camera
  right, preserving view direction. Separate --frames from --jitter so high-detail
  targets keep matching cameras rather than accidental subpixel offsets.
- --camera-out writes exact eye/target/FOV/resolution per frame. Depth/reprojection
  consume this list instead of independently deriving paths; half-pixel discrepancies
  can look like reprojection bugs.
- tools/mmdepth software-rasterizes coarse geometry into float32 view-depth MMDEPTH1.
  Public Filament APIs do not expose depth-attachment readback in this configuration.
- temporal.py --cameras ... --depth-dir ... reconstructs world positions from current
  depth, projects into previous camera, samples history/prior depth, and rejects
  relative-depth discrepancies above 5% as disocclusion.

Monkey 7,074/15,744=44.93%, four azimuths/eight frames, native160x90->640x360, total
translation 0.6 units, camera distance about 3.25, no shadows. Fixed-weight blending:

| Weight | Reprojection | Depth rejection | History rejection | PSNR | Gain over coarse |
|---|---|---|---|---:|---:|
| 0.10 | Yes | Yes | 3.0-8.6% | 34.48 | -0.03 |
| 0.25 | Yes | Yes | 3.0-8.6% | 34.17 | -0.34 |
| 0.25 | Yes | No | 0% | 34.10 | -0.41 |
| 0.50 | Yes | Yes | 3.0-8.6% | 32.52 | -2.00 |
| 0.75 | Yes | Yes | 3.0-8.6% | 29.50 | -5.01 |
| 0.50 | No | -- | -- | 27.37 | -7.14 |

Reprojection recovers 5.14 dB relative to unaligned blending, but does not make
accumulation profitable: bilinear-history blur hurts current high frequencies,
more at larger weights. Even 0.10-0.25 is near-neutral or negative. Different 2x
rotational and 4x translating setups need not yield the same result. Depth rejection
at 0.25 improves -0.41->-0.34, +0.07 dB while rejecting 3.0-8.6%. That shows a measured
effect, not exhaustive proof of mask correctness; larger-motion behavior needs testing.

Learned tiny, 2000 iterations,reported 28 triples/two validation views:

| Configuration | PSNR | SSIM | Gain |
|---|---:|---:|---:|
| Coarse single | 34.51 | -- | -- |
| Learned current | 35.39 | 0.9838 | +0.88 |
| Learned current+history | 35.54 | 0.9832 | +1.03,+0.15 over current |

History adds only 0.15 dB versus the earlier rotational 0.57; true disocclusion and
larger 4x resolution gaps may explain the difference. SSIM declines 0.9838->0.9832;
PSNR gain alone does not establish temporal fidelity.

At lower geometry 4,162/15,744=26.44%, same sequence/gate floor for target 0.2:

| Configuration | PSNR | SSIM | Gain |
|---|---:|---:|---:|
| Coarse single | 33.96 | -- | -- |
| 0.50 blend, reprojected | 32.30 | -- | -1.65 |
| 0.50 blend, unaligned | 27.23 | -- | -6.72 |
| Learned current | 34.46 | 0.9807 | +0.50 |
| Learned current+history | 34.34 | 0.9842 |  +0.38, -0.12 over current |

History PSNR benefit reverses +0.15->-0.12 as geometry coarsens, despite higher SSIM.
This corpus does not support temporal reconstruction as a way to reduce geometry
budget; current-frame synthesis and smoothing trade off rather than give a stable gain.

Motion sweep at about 45% geometry, four views/eight frames:

| Translation | Coarse | Reprojected blend | Unaligned | Learned current | Learned history | Extra history gain |
|---|---:|---:|---:|---:|---:|---:|
| 0.0 | 34.38 | 34.38,0.00 | 34.38,0.00 | 35.78 | 35.48 | -0.30 |
| 0.6 | 34.51 | 32.52,-2.00 | 27.37,-7.14 | 35.39 | 35.54 | +0.15 |
| 1.2 | 34.13 | 31.23,-2.90 | 26.31,-7.82 | 35.27 | 35.11 | -0.16 |

Unaligned losses grow 7.14->7.82 dB; alignment helps but the reprojected blend still
loses 2.90 at the largest motion. Learned history gains -0.30/+0.15/-0.16 change sign;
no uncertainty estimates establish whether these small differences exceed training
variation. Static current-only 35.78 is highest there; more motion reduces history
reliability. No positive low-motion/lower-geometry-budget regime is established.

Remaining work: recurrent learned hidden state (current model is one-step feedforward,
while temporal.py recursively accumulates history), depth/motion as network channels
rather than only reprojection inputs, and long-sequence temporal flicker metrics.

## 9. Original motivation versus a complete mobile Nanite implementation

The source titled this section as superiority over mobile Nanite. No matched
comparison establishes superiority. Its actual motivations were narrower scope than
full UE Nanite, no NVIDIA-specific dependency, Filament's open cross-platform/Android
foundation, explicit baselines, and a learning component. The MegaLights sampling/
reconstruction analogy was motivational. Neither adding AI nor sharing an analogy
establishes a contribution. The general intent was controlled approximation plus
reconstruction instead of unaffordable computation.

## 10. Historical development environment and builds

The original numbering used 9.1-9.5 below and another section10 for implementation
status; those labels are preserved for references. This is a recorded environment,
not an assertion that today's machine/configuration is identical.

### 9.1 Repository structure

The repository is a Google Filament source snapshot including vendored third_party,
used as ManyMesh's renderer base, upstream commit
`4bcb2e4e5aa2fdba45b0db73dcb92f5dbfc38752`. The recorded blobless partial clone/sparse
checkout excluded:

```text
third_party/dawn   # WebGPU dependency, about 517 MB, unused in this research configuration.
docs / docs_src    # Documentation site and images.
art               # Design sources.
```

Restore when needed, subject to network/disk constraints:

```bash
git sparse-checkout add third_party/dawn
# Alternatively restore the complete checkout.
git sparse-checkout disable
```

### 9.2 Recorded local machine

| Component | Recorded version/location |
|---|---|
| CPU/RAM | 12th-generation Intel, 20 threads / 16 GB |
| GPU | Intel Iris Xe integrated |
| Visual Studio | 2022, MSVC 19.38.33145, D:/visual studio 2022 |
| CMake | 3.31.6, bundled with VS |
| Ninja | 1.12.1, bundled with VS |
| Python | 3.12.3, Anaconda |

The snapshot's CMake rejects MSYS2 via MSYSTEM. Clear that environment variable
when invoking a native cmd build from Git Bash.

### 9.3 Windows desktop build

The recorded Windows workflow uses native VS tools/CMake rather than the Unix
build.sh. out/ is ignored:

```bat
:: Run in an x64 native-tools command environment.
call "D:\visual studio 2022\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B out\cmake-release -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DFILAMENT_BUILD_TESTING=OFF
:: Core engine.
ninja -C out\cmake-release -j 10 filament
:: Runnable sample.
ninja -C out\cmake-release -j 10 material_sandbox
```

Recorded outputs: out/cmake-release/filament/filament.lib, and tools/matc/matc.exe,
tools/cmgen/cmgen.exe, tools/resgen/resgen.exe beneath the build tree.

### 9.4 Recorded repository-local configuration

These settings were repository-local rather than global. This archive does not
apply or revalidate them:

| Setting | Value | Recorded rationale |
|---|---|---|
| http.proxy | http://127.0.0.1:7890 | Intermittently blocked direct GitHub access |
| core.autocrlf | false | Preserve worktree/object bytes |
| core.sparseCheckout | true | Exclude large unused directories |

### 9.5 Historical MSVC build correction

FRenderer owns unique_ptr<TextureCache> with only a forward declaration. MSVC
instantiated destruction in two FramePacer translation units, producing C2338,
cannot delete incomplete type; the recorded Clang/GCC builds did not trigger it.
Add the complete TextureCache.h definition in:

```text
filament/src/FramePacer.cpp
filament/src/details/FramePacer.cpp
```

This is a historical correction description, not a new source edit in the translation.

## 10. Implementation status recorded in October 2026

### 10.1 Recorded completed components

- Attribute-aware cluster/group QEM; per-corner normals/UVs, seam-internal collapse,
  and generated QEM-optimal positions.
- Exact-position leaf shared locks and assembled-cut welding/deduplication, including
  coincident faces across nodes/UV copies. Torus/Monkey/Sphere/Cloth regressions show
  no new boundary/non-manifold/duplicate/degenerate/flipped defects.
- Cluster chains, group merging, single-member root continuation; --target-ratio
  selects a nearby gate-valid budget cut, not guaranteed requested counts.
- CPU cuts, paged caches, async prefetch, WinHTTP/CivetWeb Range transport, indirect
  commands, editor controls, contiguous-range draw merging, optional per-material
  --compact-cut-indices.
- compactLodSelection keeps referenced source/generated vertices and remaps indices.
  Balanced Monkey 22,268->7,516 (33.8%), Torus 1,706->502 (29.4%), Sphere 10,647->2,019
  (19.0%); images match exactly. Stream versions 4/5/6 remain readable; v4 falls back
  to positionSource.
- buildLockedMaskContext scans referenced source vertices per unit rather than
  all mesh vertices, bit-identical output. Cloth DAG 17.2->10.3 s, Monkey 3.9->2.1 s;
  Cloth lock-mask build 9.5->0.37 s.
- mmgpu runs real Vulkan compute cut, compact indices/draws, three-pass vertices,
  indirect drawing, and visibility. One command buffer now contains cut/compaction/
  visibility, one vkQueueSubmit/WaitIdle per frame. Torus 640x360/2 px, five warm
  frames: old three-submit summed wait 2.56-3.01 ms ->1.24-1.42 ms. GPU timestamps:
  cut 0.32-0.33, compaction 0.05, visibility 0.11 ms. --legacy-submit reproduces old behavior.
  Monkey 640x360 costs 1.58 ms; Cloth 320x180 5.38 ms, cut 3.68. Compute/compute and
  compute/graphics barriers connect stages; mark reads the actual compact count in
  shader, without intermediate host readback. Torus/Monkey/Sphere/Cloth match CPU
  selected/source-vertex sets and triangle topology, visibility overlap 100%, depth
  difference zero. Parallel dense vertex IDs are legal permutations, not promised
  bit-identical CPU IDs. Historical Vulkan backend dispatchCompute/readBufferSubData
  tests pass 2/2 in out/cmake-vulkan on Iris Xe, preceding later expanded suites.
- RenderDoc single-submit evidence:
  out/renderdoc-mmgpu/single_torus_capture.rdc/.xml,320x180/2 px, one queue submit/wait,
  four compute dispatches (cut+three vertex passes), one vkCmdDrawIndexedIndirect,
  one render pass, three image-to-buffer readbacks, seven barriers. Barriers cover
  host->compute/indirect/vertex input, compute->compute, compute->graphics, and
  graphics/transfer->host. Destination stages narrowed from ALL_COMMANDS/ALL_GRAPHICS
  to actual consumers. Exit status validates source-vertex sets/topology rather
  than dense-ID allocation order; all four assets pass single/legacy A-B with exit 0.

### 10.2 Quality-first floors

At the recorded default gates, Torus target 0.2 stops 400/1,152=34.72%; Monkey target 0.3
stops 4,712/15,744=29.93%, target 0.2 stops 4,162/15,744=26.44%. Remaining group topology/
attribute rejections, not old UV averaging, limit further reduction. Better mechanisms
must preserve gates rather than relaxing them solely for counts. Nearly equal-face
Monkey 7,084 versus old 7,124 gains +0.89 dB/+0.00147 SSIM (section 7.6). Attribute-chart
fix at 6,244 gives 27.10/0.97167 versus 25.24/0.92891. These are historical revisions,
not a fresh comparison with today's worktree.

### 10.3 Incomplete components

- Public Engine lifecycle/API for persistent compute/storage/indirect objects, despite
  backend dispatch/drawIndexedIndirect and independent GPU compaction.
- Production Filament visibility-buffer integration.
- Phone HTTP/HTTPS/network switching; CivetWeb HTTPS needs platform TLS runtime.
- Phone power, bandwidth, and frame-time validation.

### 10.4 M5 prerequisites

Available code includes GLES 3.10 cut shaders, portable CivetWeb HTTP Range, Vulkan
backend compute/indirect entries, and a non-Vulkan OpenGL ES-compatible path. That
is not device validation. The recorded machine lacked:

| Acceptance item | Recorded status | Missing prerequisite |
|---|---|---|
| Android build | Not configured | Empty ANDROID_HOME/ANDROID_SDK_ROOT, no adb/sdkmanager/NDK |
| Device timing/power/thermals | Unmeasured | arm64-v8a device, stable power and temperature collection |
| Device HTTP/HTTPS/switching | Unmeasured | Device networking and controlled server |

The original text called desktop Iris Xe a mobile-GPU proxy; it cannot establish
phone timing, power, or thermals. Report desktop measurements as desktop. A device
loop requires Android command-line/platform tools/NDK, an arm64 Vulkan 1.0 or GLES 3.1
device, a mobile harness for the headless capture path, and Perfetto/battery data.
External hardware is required for that evidence.

## 11. SIGGRAPH evidence update on 2026-11-22

The cluster-decoder screen closed the tested rank-8/16/30 polynomial controls and
their latent-scale variants on validation. The local-refinement variant lost to
same-face meshoptimizer on the paired image and sampled-surface metrics. The
32-asset Thingi10K test split was not used in these follow-ups because it had
already informed earlier experiments. See the decoder study (`MANYMESH_CLUSTER_DECODER_STUDY.md`)
and matched-face report (`tools/mmtrain/CLUSTER_DECODER_MESHOPT_20261122.md`).

A separate multi-asset rendered audit tested the continuous-pan path-loss reranker
against QEM at equal final faces. On four development units and eight orbit views
per unit, path loss changed mean PSNR by +0.224 dB (95% asset-bootstrap interval
[-0.182, +0.782]); SSIM and LDR-FLIP intervals also included zero. Its existing
construction runs took 4.5–15.1 times as long as QEM. This result does not pass
the quality-cost gate. The report (`tools/mmgeo/PATH_LOSS_RENDER_QUALITY_20261122.md`)
retains the metric protocol, per-asset changes, topology checks, hashes, and limits.

A prior-art audit confirmed that adjustable-memory external continuous LOD
hierarchies and time- or memory-limited view-dependent reconstruction were already
described by Birkholz in 2006. Derzapf, Menzel, and Guthe later described
view-dependent out-of-core progressive meshes with file-backed operation nodes,
bounded node loading per frame, and GPU memory management ([VMV 2010 paper](https://doi.org/10.2312/PE/VMV/VMV10/025-032)).
Memory-bounded construction and capped runtime streaming are therefore not novelty
claims. The narrower strict-gate partial-cut idea remains an untested engineering
comparison and must include faithful construction and runtime-streaming baselines.
See the screen (`tools/mmgeo/ON_DEMAND_DAG_BUILD_MEMORY_SCREEN_20261118.md`).

The filter-aware boundary-loss hypothesis received a further prior-art audit.
EdgeGrad (ECCV 2024) supplies raster-loss gradients at mesh visibility edges and
intersections, while DiffSoup (CVPR 2026) reconstructs budgeted triangle soups from
multiview images. These do not directly solve legal, attribute-preserving collapse
of authored meshes, but they close generic antialiasing-aware image loss and
image-driven triangle budgets as novelty claims. The existing strip and frozen-pool
results still show no general quality-cost gain. See the [updated audit](MANYMESH_FILTER_AWARE_SIMPLIFICATION.md#2026-11-22-prior-art-update).

The Torus dynamic-recapture controls were also checked against their machine
records. At eight collapses (1.39% of faces), permitting newly created edges
improved the fitted-view score but made the independent 13-view filtered error
65.68 times larger than the matched initial-edge frontier. This is direct evidence
of view overfitting for that rule and budget, not a general result about
view-dependent simplification. See the [matched audit](tools/mmgeo/DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md).

The current entry page and next gate are in [MANYMESH.md](MANYMESH.md). These
screens do not establish a SIGGRAPH-ready algorithm; a fresh licensed confirmation
set and a candidate with a repeatable advantage over strong baselines remain
necessary.

A fixed-budget dynamic LOD pilot compared projected-area ranking with per-asset
direction/scale appearance profiles on 13 Khronos assets and four motion paths held
out from calibration. The per-asset profiles changed mean grayscale PSNR by +0.258 dB,
but this used reused development assets and did not establish cross-asset transfer. A
leave-one-asset-out shared-profile evaluation reduced the PSNR change to +0.083 dB
(95% asset-bootstrap CI [-0.019, +0.190]); SSIM was inconclusive and silhouette IoU
declined (95% CI [-0.000351, -0.000085]). This closes the shared-profile formulation
as a contribution candidate. The per-asset screen (`tools/mmtrain/DYNAMIC_LOD_13ASSET_20261122.md`)
and leave-one-asset-out report (`tools/mmtrain/DYNAMIC_LOD_LOAO_13ASSET_20261122.md`)
record protocols, per-asset metrics, timing and prior-art limits.

A temporal follow-up rendered the isolated-cell sequences in memory for thirteen
assets on four held-out motion paths at 640x360, then measured adjacent-frame
image-derivative error against full-detail reference sequences. The shared profile reduced foreground
temporal-difference MAE by 0.000942 (95% asset-bootstrap CI [0.000488, 0.001434]
in the improvement direction; 12/13 assets) and reduced switch-bearing transitions
by 2.08 per 48-frame path. This custom pixel diagnostic is not motion-compensated or
perceptually calibrated; it does not reverse the silhouette-IoU regression or establish
temporal stability. CGVQM was not run because its implementation and model weights
were absent locally. The temporal report (`tools/mmtrain/DYNAMIC_LOD_TEMPORAL_DIAGNOSTIC_20261122.md`)
and measurement protocol (`tools/mmmetrics/TEMPORAL_QUALITY_PROTOCOL.md`) record the
metric definition, paired results, hashes, and limits.

After the upstream implementation and weights became available, CGVQM-5 was run
on two captured 48-frame paths for the same 13 reused Khronos assets. Averaging
the paired path deltas within each asset gave a selected-profile-minus-area mean
of -0.0590 (95% asset-bootstrap CI [-0.1476, +0.0424]); 4 assets improved and 9
regressed. The interval crosses zero. Scoring used the upstream model with an
OpenCV FFmpeg input adapter rather than PyAV, so this is not a canonical
reproduction or independent confirmation. See the full report (`tools/mmmetrics/CGVQM_DYNAMIC_LOD_SCREEN_20261122.md`)
and protocol (`tools/mmmetrics/TEMPORAL_QUALITY_PROTOCOL.md`).

## 12. 2026-11-23: original-source and asset-feasibility follow-up

A current-source Monkey diagnostic now uses the original 15,744-triangle OBJ
as reference, addressing the mismatch in the historical silhouette still. Across
eight orthographic views, the 30%, 50%, and 70% cuts attributed 34.75%, 25.84%,
and 25.88% of squared image error to silhouette-XOR pixels. This does not
confirm the historical 68.3% value as a general property. Exact directed-edge
matching flagged every cut, but a retrospective one-to-one coordinate map
matched all 168 oriented boundary edges within 0.52 float32 epsilon at unit
radius. Maximum sampled curve deviation was 6.08e-8 normalized units and
relative length error was 3.3e-9, consistent with small coordinate-rounding
differences. At exact
face counts, eligible QEM and meshoptimizer controls beat its image metrics at 30% and 50%;
at 70%, the QEM output was rejected for duplicate geometric triangles and the
eligible meshoptimizer control beat it. This is a reference-corrected diagnostic,
not a held-out result. The geometric-boundary audit was retrospective; freeze
its tolerance before confirmation scoring. See the report (`tools/mmtrain/MONKEY_ORIGINAL_SOURCE_DIAGNOSTIC_20261123.md`),
image receipt (`tools/mmtrain/monkey_source_reference_diagnostic_20261123.json`),
and curve receipt (`tools/mmtrain/monkey_boundary_curve_audit_20261123.json`).

Asset screening also found a local DamagedHelmet GLB with 15,452 triangles and
no exact/name match in the bounded text scan. The extractor applies default-scene
node transforms, but the strict topology gate rejected this source for seven
non-manifold or inconsistently oriented edges before any image scoring. Its
local license note lacks a version, and the exact local binary is not mapped to
a pinned upstream revision. Keep it for development diagnostics only. The
asset report (`tools/mmtrain/DAMAGED_HELMET_TOPOLOGY_GATE_20261123.md`) records
the source, extraction, logs, and rejection. The revised extractor rejects the
skinned Fox asset rather than using its unposed base geometry for image-quality
evaluation; see the asset-screen decision (`MANYMESH_CONFIRMATION_ASSET_SCREEN.md`).

## 13. References

- [Google Filament](https://github.com/google/filament).
- Upstream build documentation: [BUILDING.md](BUILDING.md).
- Repository agent guidelines: [AGENTS.md](AGENTS.md) and skills/.
