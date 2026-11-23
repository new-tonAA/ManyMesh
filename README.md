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

| Works in the measured scope | Does not pass | Not measured |
|---|---|---|
| Desktop experiments now compare several reconstruction modes, moving-camera paths, and geometry controls. | No new geometry or reconstruction method has a repeatable quality–cost win over strong controls. | Physical-phone performance, power, thermals, user preference, and independent held-out generalization. |

## Next gate

Do not start a custom cluster-DAG optimizer yet. First run a matched-face
differentiable simplification baseline on legally cleared assets with CUDA,
held-out views, QEM, and meshoptimizer controls. Advance only if it produces a
repeatable held-out gain; then test the DAG-specific constraints and real
antialiasing/upscalers. See the [research status](MANYMESH.md) and
[next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md). Mobile or preference
claims need separate device measurements or a user study.

## Project notes

- [Concise research status](MANYMESH.md)
- [Next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Moving-camera per-instance LOD screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- [Filament documentation](filament/README.md)
