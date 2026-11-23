# Geometry layout control for the mixed-scene baseline

In the [mixed-scene benchmark](MIXED_SCENE_BASELINES_20261122.md), stock
meshoptimizer depth 2 drew more triangles than QEM and component cuts yet
ran faster on every view. This follow-up tests whether that speed ordering
survives a common cache and vertex-fetch layout policy.

## Frozen protocol

- Reuse the exact scene transforms, nine camera poses, five meshes per
  asset (full source, QEM, component, stock depth 1 and depth 2), and the
  supersampled reference hashes. Measure native-resolution 4× MSAA on Iris
  Xe at 1280×720. Each mesh uses its existing face count.
- Interleave three layouts in the same timing run. The supplied layout
  preserves input buffers. Fetch-only compacts unused vertices and puts
  the remaining vertices in first-use order while keeping the triangle
  stream in its original order. Cache and fetch reorders triangles with
  stock meshoptimizer vertex-cache optimization and then packs the vertex
  buffer in the resulting first-use order.
- Use meshoptimizer v1.2 WebAssembly through `reorderMesh`, with
  `optsize=false` for rendering. Preserve original triangle winding and
  the exact vertex attribute bytes. Before measuring, invert the remap and
  verify exact ordered triples in fetch-only, and the same multiset of
  ordered triples in cache and fetch. Neither pass welds or quantizes.
- Take four rotated batches of 24 GPU timestamp samples per view and mode.
  Record p50 and per-batch medians. Audit image hashes, pixel deltas,
  FLIP, PSNR, and SSIM. Depth ties can change image output when the triangle
  stream changes. Report such changes and use measured quality per layout.
- Count in how many views stock depth 2 remains faster than each competitor
  under shared cache and fetch optimization. Record the fastest layout for
  each geometry, including fetch-only. Treat speed rankings as descriptive
  for these development scenes; six or more wins on nine views is the
  predeclared threshold for saying the ranking survives on most views.
  A budget-equivalent comparison does not imply equal triangle counts.

## Results

All runs use Intel Iris Xe through D3D12 at 1280×720 with 4× MSAA. This
table reports p50 GPU milliseconds, then takes the median across each
scene's three views. See the [raw receipt](mixed_scene_layout_720p_20261122.json)
for all 96 measurements per mode and view, image metrics, and hashes.

| Scene | Geometry | Supplied | Fetch only | Cache and fetch |
|---|---|---:|---:|---:|
| display-wall | source | 2.689 | 2.750 | 1.815 |
| display-wall | qem | 0.844 | 0.823 | 0.725 |
| display-wall | parts | 0.830 | 0.835 | 0.709 |
| display-wall | cluster1 | 1.100 | 1.089 | 1.109 |
| display-wall | cluster2 | 0.781 | 0.780 | 0.772 |
| layered-aisles | source | 2.679 | 2.752 | 1.746 |
| layered-aisles | qem | 0.895 | 0.879 | 0.685 |
| layered-aisles | parts | 0.841 | 0.849 | 0.716 |
| layered-aisles | cluster1 | 1.089 | 1.135 | 1.130 |
| layered-aisles | cluster2 | 0.786 | 0.787 | 0.812 |
| mixed-scale | source | 3.242 | 3.218 | 2.304 |
| mixed-scale | qem | 0.982 | 0.961 | 0.799 |
| mixed-scale | parts | 0.930 | 0.926 | 0.817 |
| mixed-scale | cluster1 | 1.358 | 1.333 | 1.290 |
| mixed-scale | cluster2 | 0.886 | 0.898 | 0.879 |

- Compared with the supplied layout, the median paired GPU-time decrease
  after cache and fetch is **32.4%** for full source, **19.3%** for QEM, and
  **14.8%** for the component cut. Each improves in all nine views. Stock
  cluster depth 2 changes by a median **0.3% decrease** and is faster in 5/9.
  Fetch-only changes are smaller and mixed. It compacts the two stock
  vertex buffers to 50.4% and 25.5% of their original logical bytes summed
  over the 13 assets. The supplied stock cuts share the source buffer when
  simultaneously resident, so these sizes are per geometry stream.
- Depth 2 beats both alternatives on p50 in **9/9 views** in the supplied
  and fetch-only layouts. With cache and fetch applied to all methods, it
  wins **0/9** against either. Its median time is 0.060 ms higher than QEM
  and 0.076 ms higher than the component cut in paired views. The reversed
  ranking appears in all four batches on 7/9 QEM views and 8/9 component
  views. Even granting each method its fastest measured layout separately
  per view leaves depth 2 slower in all nine.
- With the shared cache and fetch layout, depth 2 still has lower FLIP and
  higher PSNR and SSIM than both alternatives on **9/9 views**. It still
  submits about 24–25% more faces than either, so these are different
  quality–cost points. For example, in layered aisles all three layouts
  use the same input faces within each mode. With cache and fetch, the
  medians are 0.685 ms for QEM, 0.716 ms for components, and 0.812 ms for
  depth 2. The prior speed advantage depended on the buffers supplied to
  the comparison.

All 45 supplied captures and nine references match the previous run by
hash. Fetch-only output is identical to supplied output on all 45 pairs.
Cache and fetch changes some pixels in every pair, as can happen with
triangle-order-dependent depth ties. At most 215 of 921,600 pixels change
in a frame. The largest metric changes are 0.0000111 FLIP, 0.0111 dB PSNR,
and 0.000037 SSIM. The quality ordering above uses the actual captures.

The remap checks recover the exact source vertex IDs, attributes and
triangle winding for all 130 remapped streams. The layouts leave the
underlying geometry and its existing topology issues intact. The
published [meshoptimizer optimization pipeline](https://github.com/zeux/meshoptimizer/blob/9d9890c73011d75920af614485296d1e03e95448/README.md#core-pipeline)
explains the standard cache and fetch passes. This experiment measures the
effect of the layout policies. It does not use pipeline counters to
attribute time to individual GPU stages. Times cover the offscreen GPU
raster and resolve interval with resident geometry. CPU reorder time and
memory residency are outside that interval.

Use a common layout policy for future mixed-scene comparisons. The stock
depth 2 cut supplies a strong quality point, and optimized QEM and
component cuts supply cheaper controls. The supplied-layout SMAA and
upscaling data belong to the earlier benchmark. They need a same-run
optimized-layout measurement before combining them with this frontier.
The [face-budget follow-up](MIXED_SCENE_FACE_BUDGETS_20261122.md) includes
that measurement and compares matched cuts with the same layout policy.
The scene views are repeated measures on a desktop development set.

## Reproduce

Use the meshes, pinned upstream checkout, and dependencies from the
[mixed-scene experiment](MIXED_SCENE_BASELINES_20261122.md#reproduce).
Node 22.16.0 runs the pinned meshoptimizer WebAssembly module. The benchmark
verifies the checked-out revision and records the encoder and helper hashes.

```powershell
python tools/mmtrain/bench_mixed_scene_layout.py --baseline tools/mmtrain/mixed_scene_baselines_720p_20261122.json --meshes out/geometry-refinement-pilot/motion-meshes --stock out/mixed-scene/stock --upstream out/deps/meshoptimizer-v1.2 --out out/mixed-scene/layout-720p.json
```
