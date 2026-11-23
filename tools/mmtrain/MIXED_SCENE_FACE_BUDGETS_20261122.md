# Matched geometry budgets in mixed scenes

The [layout control](MIXED_SCENE_LAYOUT_CONTROL_20261122.md) removes a
buffer-order timing advantage. Stock cluster depth 2 still retains about
one quarter more faces than the older QEM and component cuts. This screen
tests whether its image-quality advantage persists at the same or nearly
the same geometry budget, and whether retaining source normals matters.

## Frozen protocol

- Use the three existing development scenes, their nine frozen views,
  1280×720 output, the archived full-source supersampled reference, and
  the same Iris Xe renderer. Apply the same stock meshoptimizer cache and
  fetch optimizer to every timed geometry stream. Verify face and vertex
  attribute identity under remapping.
- Generate whole-mesh cuts using fast-simplification 0.2.0 with its default
  aggressiveness. Request stock depth 2's face count and try offsets in
  this order: 0, +1, −1, +2, −2. Stop on exact count. Select the smallest
  absolute difference with first-request tie breaking. This selection
  uses counts only. Recompute area-weighted normals on QEM as in the
  existing component benchmark.
- Compare three cohorts. The exact cohort cuts only assets with exact
  face counts. The broad cohort also accepts a one-face difference per
  asset. The edge-clean cohort starts with the broad selections and
  requires no repeated-vertex or duplicate faces and no nonmanifold
  welded edges in the source and both cuts. Ineligible assets draw the
  same optimized full source in both arms, with identical transforms and
  one indexed instanced draw per group. Report all fallbacks and the
  final per-scene face budgets. The edge screen is an incidence diagnostic,
  since it does not certify boundary correspondence or self-intersection.
- In the broad cohort add a stock arm with area-weighted normals
  recomputed on the same cut. Keep positions, triangle indices, and
  layout unchanged. This isolates normal fields within one geometry;
  it does not isolate the effect of the stock simplifier's attribute cost.
- Remeasure the existing 11 AA and geometry modes with optimized
  buffers in the same run, including full-source SMAA and linear or
  Catmull–Rom upscaling. Record three rotated batches of 24 timed frames
  and report p50 GPU time together with FLIP, PSNR, SSIM, and foreground
  XOR. Use the same capture, reference, and timestamp rules as the
  original mixed-scene screen. The scenes are reused development settings.
- As a separate geometric diagnostic, use 12,000 area-uniform surface
  samples per direction and method for each broad-cohort asset. Record
  sampled symmetric Chamfer distance, tail distance, and geometric face
  normal agreement. Record any sampling rejection from zero-area faces.

## Results

The [measurement receipt](mixed_scene_face_budgets_720p_20261122.json) records
all issued QEM targets, hashes of input receipts and new buffers, incidence
counts, 72 timing samples per view and mode, and quality scores. QEM uses the
same input positions and triangle indices as the stock cluster builder.
[Fast-simplification source and API](https://github.com/pyvista/fast-simplification)

| Scene | Exact triangles per arm | Broad QEM / stock triangles | Edge-clean QEM / stock triangles | Mesh types simplified, exact / broad / edge-clean |
|---|---:|---:|---:|---:|
| Display wall | 1,721,120 | 446,840 / 446,865 | 1,286,415 / 1,286,425 | 2 / 7 / 4 |
| Layered aisles | 1,533,426 | 436,494 / 436,512 | 1,567,134 / 1,567,134 | 3 / 6 / 1 |
| Mixed scale | 1,997,220 | 558,870 / 558,900 | 1,478,658 / 1,478,664 | 2 / 7 / 3 |

Five unique assets reach the exact face count. Seven more undershoot by
one face. Lantern stalls at 1,632 faces for its 1,348-face target and
draws full geometry in both arms. After instance replication the broad
QEM arm submits 18–30 fewer triangles per scene, below 0.006% of the
stock count. Five unique assets pass the edge-clean pairing. Its high
scene-wide face counts arise from the common full-resolution fallbacks.

Each cell below gives p50 GPU ms / LDR-FLIP, taking the median across the
three views within the scene.

| Scene | Cohort | QEM | Stock cluster depth 2 |
|---|---|---:|---:|
| display-wall | exact | 1.678 / 0.00934 | 1.684 / 0.00672 |
| display-wall | near | 0.749 / 0.01330 | 0.824 / 0.00919 |
| display-wall | edge | 1.383 / 0.01145 | 1.401 / 0.00868 |
| layered-aisles | exact | 1.591 / 0.00595 | 1.597 / 0.00526 |
| layered-aisles | near | 0.790 / 0.00773 | 0.825 / 0.00582 |
| layered-aisles | edge | 1.696 / 0.00446 | 1.696 / 0.00425 |
| mixed-scale | exact | 2.048 / 0.01077 | 2.061 / 0.00794 |
| mixed-scale | near | 0.897 / 0.01496 | 0.889 / 0.01031 |
| mixed-scale | edge | 1.652 / 0.01093 | 1.657 / 0.00794 |

| Cohort | Stock minus QEM p50 GPU ms | Stock minus QEM LDR-FLIP | Stock minus QEM PSNR in dB | Stock faster |
|---|---:|---:|---:|---:|
| Exact | +0.050 | −0.00252 | +2.81 | 2/9 |
| Within one face per asset | +0.041 | −0.00411 | +2.36 | 1/9 |
| Edge-clean | +0.001 | −0.00265 | +1.88 | 4/9 |

These deltas are medians of paired view differences. Stock has lower FLIP
and higher PSNR and SSIM in all nine views for each cohort. Foreground XOR
is lower in 9/9 exact views, 9/9 broad views and 6/9 edge-clean views.
The near-zero median time difference in the edge-clean cohort summarizes
mostly full-source scenes. It is insufficient evidence of equivalent
cost for a full reduced scene.

### Normal and surface controls

Recomputing normals on the identical broad-cohort stock mesh raises FLIP
in all nine views (median +0.000380). It still beats matched QEM in FLIP,
PSNR and SSIM on all nine views. Retained source normals contribute to the
image-quality advantage. The geometry and other simplifier differences
remain relevant.

Ten of the 12 broad-cohort assets have paired surface estimates.
AntiqueCamera and CesiumMilkTruck are excluded from the surface summary
after a degenerate-triangle rejection. Stock has lower sampled mean
Chamfer distance on 4/10 assets and lower sampled p95 surface distance on
6/10. Geometric face-normal agreement is higher on 8/10. On the five
edge-clean assets, the corresponding counts are 3/5, 3/5 and 5/5.
The picture-quality gain is more consistent here than sampled distance
gains.

### Optimized AA and upscaling controls

With the common optimized buffers, the existing QEM and component cuts
with 4× MSAA still beat full-source half-resolution linear and Catmull–Rom
upscaling on GPU time, FLIP, PSNR and SSIM in all nine views. The unfiltered
stock depth 2 cut with MSAA also beats both upscalers on all four measures.
It runs faster than full-source SMAA in 9/9 views and has lower FLIP in 7/9.
Full-source SMAA has lower FLIP than the older QEM and component cuts in
all nine views, at a higher GPU cost. These comparisons use the same
timing run as the face-budget experiment.

## Limits and reproduction

The proximity and incidence screens use reused gray, rigid, desktop
scenes. They leave the strict source-boundary and full topology gate
open. The GPU intervals span raster through resolve and any post-processing.
CPU submission, runtime LOD selection, and asset loading are outside them. View counts
are descriptive repeated observations. The results set a stronger
target for a new simplifier, with an exact or near-exact face budget,
shared layout, and both image-space and geometric measurements.

Follow the [scene benchmark setup](MIXED_SCENE_BASELINES_20261122.md#reproduce)
and [layout control](MIXED_SCENE_LAYOUT_CONTROL_20261122.md#reproduce) to obtain
the same PLY exports, stock cut files and Python environment. This revision
generalizes the shared render helper to accept a different mode list and
reference draws. All nine reference images and 45 shared reordered MSAA
captures still reproduce the earlier hashes and scores.

```powershell
python tools/mmtrain/bench_scene_face_budgets.py --baseline tools/mmtrain/mixed_scene_baselines_720p_20261122.json --layout tools/mmtrain/mixed_scene_layout_720p_20261122.json --meshes out/geometry-refinement-pilot/motion-meshes --stock out/mixed-scene/stock --upstream out/deps/meshoptimizer-v1.2 --shader-root out/deps/bevy-smaa --out out/mixed-scene/face-budgets-720p.json
```
