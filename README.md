# ManyMesh

ManyMesh investigates how mesh level of detail (LOD) affects rendered image
quality and cost. It is a Filament research checkout. **No submission-ready
method or mobile-performance claim is established.**

![Khronos Suzanne rendered at 3,936 and 982 triangles beside a map of silhouette differences.](docs/manymesh/suzanne-lod.png)

*Khronos Suzanne, flat shaded, 384 × 384 per panel, CPU reference render. The center panel is the depth-2 cut from unmodified meshoptimizer v1.2. The right panel marks binary coverage differences. Asset: UX3D / Norbert Nopper, CC0 1.0. [Figure receipt](docs/manymesh/suzanne-lod.json).*

## Research status

**No current ManyMesh method has passed both the novelty and quality–cost
gates.** The latest candidate question is whether offline appearance
optimization can improve a constrained cluster LOD hierarchy after
antialiasing or upscaling. This is an untested hypothesis with close prior art;
compare separately at matched face count and matched complete frame time.
Hasselgren et al. already optimize
mesh appearance from differentiable image-space losses for simplification and
LOD; silhouette-sensitive view-dependent simplification dates to Luebke and
Erikson, and exact coarse-mesh silhouette clipping to Sander et al. ([Hasselgren
et al.](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc),
[Luebke and Erikson](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf),
[Sander et al.](https://hhoppe.com/silclip.pdf)). No distinction or benefit has
been established.

Evaluation is two-stage: compare image quality at matched final face counts,
then compare complete frame time at matched conditions. Report LDR-FLIP, PSNR,
SSIM, silhouette/coverage error, and temporal quality on frozen camera paths;
include QEM, meshoptimizer, MSAA, SMAA, and available upscalers where applicable.
The final-image reconstruction interaction is an untested hypothesis. No
physical-phone or user-preference result is available.

## What the current screens show

- **The 13-asset fusion screen is 0/13 under its stated joint criterion.**
  Neither silhouette-fusion prototype beat every qualified control on all of
  LDR-FLIP, PSNR, and SSIM at or below its per-asset GPU p50. This does not mean
  MSAA lost on every metric. A cheaper control selected after seeing results
  dominated both prototypes on all three metrics for each asset, so this is an
  exploratory, post-hoc comparison. It is fixed-view grayscale Iris Xe desktop
  data, not phone or full-frame timing. [Report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md) · [verified repeat](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json)
- **Moving-camera allocation did not pass equal cost.** In a three-scene,
  48-frame screen, per-instance allocation used more faces and ran slower on
  GPU. A face-budget-matched offline oracle improved the temporal metric in one
  scene only and added CPU selection cost. [Report](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- **One seven-asset source-reference screen found a narrow exception.** Under a
  retrospective one-float32-ULP boundary rule, 15 of 21 cuts were eligible.
  Across 18 exact-face comparisons, ManyMesh lost all five image metrics in 15,
  won all five in two meshoptimizer comparisons on the 987-face
  GlassBrokenWindow, and had one mixed result. It did not beat an eligible QEM
  pair. This is reused development data, the boundary rule was chosen after an
  initial run, and the broken-window hierarchy missed the requested 30% and 70%
  cuts. The two wins are meshoptimizer-only: border-preserving QEM returned 859
  faces for requested cuts of 381, 491, and 569 faces, so no QEM pair passed the
  exact-face gate. [Full report](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md) ·
  [metrics and hashes](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json)
- **No independent confirmation set exists yet.** Geometry preflight now has
  nine provisional candidates across several object classes; the pool is
  unfrozen and includes low-detail models and assets with excluded marks.
  [Expanded candidate screen](docs/manymesh/khronos-expanded-candidate-screen-20261123.md) and
  [earlier source screens](docs/manymesh/khronos-followup-candidates-20261123.md)

| Works in the measured scope | Does not pass | Not measured |
|---|---|---|
| Desktop experiments now compare several reconstruction modes, moving-camera paths, and geometry controls. | No new geometry or reconstruction method has a repeatable quality–cost win over strong controls. | Physical-phone performance, power, thermals, user preference, and independent held-out generalization. |

## Next gate

The source contour priority improved mean PSNR at equal face counts on
seven development assets. FLIP was mixed, and plain QEM matched its one
all-metric win over meshoptimizer. [Contour priority report](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md)

The first two preflight assets failed to supply a full set of legal meshes
near 30% retention. [Input preflight](tools/mmtrain/APPEARANCE_INPUT_PREFLIGHT_20261123.md)
The next experiment needs cleared assets with matching face counts, frozen
views, QEM and meshoptimizer controls, and a CUDA workstation. Advance only
if the differentiable baseline produces a repeatable held-out gain, then
test the DAG constraints with real antialiasing and upscalers. See the
[research status](MANYMESH.md) and
[next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md). Mobile or preference
claims need separate device measurements or a user study.

## Project notes

- [Concise research status](MANYMESH.md)
- [Learned LOD research and experiment record](MANYMESH_LEARNED_LOD_RESEARCH.md)
- [Dated experiments and backend test inventories](MANYMESH_HISTORY.md)
- [SIGGRAPH 2027 direction, prior art, and stop criteria](SIGGRAPH_2027_DIRECTION.md)
- [Prior-art screen with full-text access status](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Research continuation prompt and evidence protocol](MANYMESH_RESEARCH_LOOP.md)
- [Next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Moving-camera per-instance LOD screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- [Filament documentation](filament/README.md)
