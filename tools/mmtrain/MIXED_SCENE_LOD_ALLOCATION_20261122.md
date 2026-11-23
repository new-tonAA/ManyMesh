# Face-budget allocation across asset groups

This screen asks whether whole asset groups need different stock cluster
depths to improve the measured quality–cost frontier in mixed scenes.
[Funkhouser and Séquin](https://www.cs.princeton.edu/courses/archive/spring01/cs598b/papers/funkhouser93.pdf)
already use a multiple-choice cost–benefit formulation for LOD allocation.
The experiment tests a narrower empirical question about offline
single-group FLIP benefits measured with the full scene and shared depth.

## Frozen protocol

- Reuse the three mixed scenes and all nine views. Each eligible asset
  group draws either stock depth 2 or stock depth 1. All its instances
  use the same depth and share the same indexed draw in every allocation.
  The source and both cuts must pass the prior duplicate-face,
  repeated-vertex and nonmanifold-edge incidence screen. Other groups
  draw the same full source in every allocation.
- Pack all geometry with the previous cache and fetch policy. Use the
  same 1280×720 renderer, native 4× MSAA on all allocations, and archived
  supersampled reference hashes. Enumerate all group masks and capture
  the combined scene for each. Score exact achromatic LDR-FLIP and
  record one image hash per mask. This finite oracle does not optimize
  untested cuts, shading, or continuous budgets.
- Use caps at 25%, 50% and 75% of the triangle gap between the uniform
  eligible depths. Every compared mask must fit its cap. The area
  policy maximizes the sum of archived native projected coverage per
  promoted group, measured in isolation. This control has access to the
  current camera and the full source geometry's coverage. The fitted
  profile maximizes the sum of relative FLIP improvements of single
  promotions averaged over the other two views of the same scene.
  It never reads the evaluated view's scores to select the mask.
- Both policies solve the small subset problem exactly for their own
  objective. Ties use fewer triangles, then ascending mask number.
  The oracle minimizes the actual full-scene FLIP at each cap. Also
  record an optimistic additive policy with single-promotion values
  from the current view to diagnose the effect of holding the view out.
- Time the unique selected masks, both uniform endpoints and the
  11 previous optimized baselines together in three batches of
  24 samples per mode. Identical masks share one timing. Evaluate image
  quality against the same reference and compare each result with every
  measured control at its p50 GPU budget. Record search and calibration
  costs separately from the GPU raster-through-resolve interval.
- Advance the fitted profile only if it reduces FLIP versus area in at
  least 6/9 views at the 50% cap, with positive median reduction, and
  improves on all eligible measured controls in at least 6/9 views.
  This development gate is necessary for a new prototype. A fresh
  corpus and camera paths, full runtime cost, and a strict topology
  audit remain necessary for a contribution claim.

## Results

All runs use 1280×720 output on Intel Iris Xe with D3D12. The group-depth
assignments use 4× MSAA.
The [raw receipt](mixed_scene_lod_allocation_720p_20261122.json) contains
384 scored assignments and 142 timed mode–view pairs with 72 GPU samples
each. All nine references and 99 shared baseline captures reproduce the
archived images and scores. Each timed allocation reproduces its enumerated
capture. Time eligibility uses a pair's p50 and lower FLIP is better.

| Scene | Eligible groups | Uniform depth 2 triangles | Uniform depth 1 triangles | Assignments per view |
|---|---:|---:|---:|---:|
| Display wall | 5 | 877,735 | 1,182,070 | 32 |
| Layered aisles | 5 | 855,252 | 1,120,854 | 32 |
| Mixed scale | 6 | 784,170 | 1,237,896 | 64 |

The area policy improves on all GPU-time-eligible uniform controls on all
nine views at each cap. The uniform controls consist of both screened
endpoints and the eleven remeasured optimized baseline modes. The fitted
profile adds no improvement beyond area at 25% or 75%, and improves only
three views at 50%. The fitted-profile frontier comparison also includes
area assignments from all three caps as controls.

| Share of available extra triangles | Area improves on all time-eligible uniform controls | Median FLIP change of area vs. best uniform control | Fitted profile improves on area | Fitted profile improves on all time-eligible controls |
|---|---:|---:|---:|---:|
| 25% | 9/9 | −0.000948 | 0/9 | 0/9 |
| 50% | 9/9 | −0.000969 | 3/9 | 3/9 |
| 75% | 9/9 | −0.000236 | 0/9 | 0/9 |

The median FLIP difference between the fitted and area assignments at the
50% cap is zero. In the three mixed-scale views where they differ, the
fitted profile promotes ToyCar instead of SheenChair. It spends 103,554 more
triangles and adds 0.092–0.117 ms. The FLIP reduction in those views ranges
from 0.00000018 to 0.00003587. On all nine views and all three caps, the
optimistic current-view additive ranking attains the minimum FLIP in the
finite pool. Across these faces and views, coupling between promotions
does not require a non-additive selection rule to attain the measured
minimum. Even the finite oracle improves on area in only three
view–cap pairs.

The median elapsed time to capture and score the full pool for a view is
17.48 seconds. The median 0.323 ms selection measurement includes all
weights, subset objectives, and caps, with per-view profile scores already
available. These exploratory wall times are separate from the timed GPU
passes. The area control uses archived single-group coverage measurements.
A deployable baseline would need a runtime coverage proxy and its cost.

The tested fitted profile misses the frozen gate. Keep area allocation
as a baseline for group-level policies on these scenes. This result covers
a finite asset-group pool, static reused scenes and a welded-incidence
screen. Per-instance granularity, new geometry, temporal behavior and
strict boundary preservation remain outside the test.

## Reproduce

Use the [mixed-scene setup](MIXED_SCENE_BASELINES_20261122.md#reproduce)
for the geometry and pinned Bevy inputs and the
[face-budget experiment](MIXED_SCENE_FACE_BUDGETS_20261122.md#limits-and-reproduction)
for its optimized reference receipt.

```powershell
python tools/mmtrain/bench_scene_lod_allocation.py --baseline tools/mmtrain/mixed_scene_baselines_720p_20261122.json --optimized tools/mmtrain/mixed_scene_face_budgets_720p_20261122.json --meshes out/geometry-refinement-pilot/motion-meshes --stock out/mixed-scene/stock --upstream out/deps/meshoptimizer-v1.2 --shader-root out/deps/bevy-smaa --out out/mixed-scene/lod-allocation-720p.json
```
