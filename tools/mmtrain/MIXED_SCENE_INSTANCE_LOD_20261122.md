# Per-instance LOD allocation screen

The [whole-asset profile](MIXED_SCENE_LOD_ALLOCATION_20261122.md) rarely
beats area at its own face cap. This screen measures whether finer
allocation granularity helps at the same cap when splitting draws has
a real GPU cost. Screen-area LOD and visibility queries are established
techniques. [Funkhouser and Séquin](https://pixl.cs.princeton.edu/pubs/Funkhouser_1993_ADA/index.php)
and [Bittner et al.](https://www.cs.purdue.edu/cgvlab/popescu/Visibility/Additional%20References/Bittners%202004.pdf).

## Frozen protocol

- Reuse the same three scenes, nine camera poses, stock depth 1 and 2
  meshes, incidence screening, and full-source fallbacks. Each
  incidence-eligible instance can independently choose depth 1 or 2.
  Pack buffers with the same cache and fetch policy.
- Use 50% of the extra face allowance between uniform screened depths,
  exactly the cap in the previous experiment. The deployable preflight
  policy projects precomputed source bounding-box corners, approximates
  coverage by the clipped screen rectangle, and greedily promotes
  instances by coverage per added triangle. It reserves no headcount
  for extra draws. Make one indexed instanced draw per nonempty
  asset/depth bucket, preserving original instance order in each bucket.
- Three diagnostics use exact integer subset optimization under the
  same cap. One uses the bounding rectangles. Two use native
  frontmost pixel ownership for either the full-source or uniform
  screened coarse scene, obtained by dedicated depth-tested ID draws.
  Measure one 24-sample batch for each ID pass and its capture wall time
  separately. Treat ID
  policies as optimistic quality probes when comparing allocation
  raster time. They require their own visibility cost at runtime.
- Time each allocation and the three previous area allocations,
  both screened uniform endpoints, and the eleven optimized scene
  controls in one run. Use 1280×720, 4× MSAA for allocation, the
  previous full-source 2560×1440 supersampled reference, and three
  rotated batches of 24 GPU samples. Report per-view draw and face
  counts, LDR-FLIP, PSNR, SSIM, and foreground XOR. Check that the
  full-source ID pass covers the same pixels as the native source
  frame.
- Measure camera projection and greedy selection CPU time from
  cached world bounds, separately from GPU time. Bucket allocation,
  upload, runtime submission, and moving-bound updates are outside this
  static replay. To justify a further prototype, the bounding-box
  policy must beat group area on FLIP at the central face cap and
  beat all measured scene and group controls at its p50 GPU budget in at least 6/9
  views each, with median CPU selection under 1 ms.

## Results

The [measurement receipt](mixed_scene_instance_lod_720p_20261122.json)
records 159 mode–view measurements, with 72 GPU samples per mode.
The 138 shared baseline captures match the previous pixels and scores.
All nine reference hashes match. Independent rerenders verify pixelwise
coverage equality between the ID and ordinary native passes for both source
and coarse geometry. All 18 ID image hashes reproduce.

Each cell is p50 GPU milliseconds / LDR-FLIP. The last two columns are equal
because the full-source and coarse ID policies choose the same instances
in all nine views. Their times exclude the visibility pass.

| Scene | View | Group area at 50% | Bounds greedy | Bounds exact | Full-source ID | Coarse ID |
|---|---:|---:|---:|---:|---:|---:|
| display-wall | 1 | 1.138 / 0.007014 | 1.244 / 0.006975 | 1.244 / 0.006975 | 1.271 / 0.006947 | 1.271 / 0.006947 |
| display-wall | 2 | 1.168 / 0.006835 | 1.229 / 0.006763 | 1.231 / 0.006794 | 1.229 / 0.006763 | 1.229 / 0.006763 |
| display-wall | 3 | 1.087 / 0.006471 | 1.210 / 0.006433 | 1.210 / 0.006433 | 1.201 / 0.006425 | 1.201 / 0.006425 |
| layered-aisles | 1 | 1.194 / 0.003948 | 1.224 / 0.003890 | 1.224 / 0.003890 | 1.261 / 0.003863 | 1.261 / 0.003863 |
| layered-aisles | 2 | 1.172 / 0.004772 | 1.309 / 0.004695 | 1.309 / 0.004695 | 1.306 / 0.004691 | 1.306 / 0.004691 |
| layered-aisles | 3 | 1.180 / 0.004311 | 1.259 / 0.004267 | 1.259 / 0.004267 | 1.219 / 0.004278 | 1.219 / 0.004278 |
| mixed-scale | 1 | 1.249 / 0.007283 | 1.289 / 0.007114 | 1.285 / 0.007117 | 1.238 / 0.007118 | 1.238 / 0.007118 |
| mixed-scale | 2 | 1.217 / 0.006989 | 1.237 / 0.006852 | 1.271 / 0.006855 | 1.233 / 0.006849 | 1.233 / 0.006849 |
| mixed-scale | 3 | 1.235 / 0.007513 | 1.239 / 0.007369 | 1.262 / 0.007375 | 1.317 / 0.007369 | 1.317 / 0.007369 |

| Policy | Improves FLIP over group area at the cap | Improves FLIP over all time-eligible scene and group controls | Median paired FLIP change vs. group area | Median paired GPU time change vs. group area |
|---|---:|---:|---:|---:|
| Bounds greedy | 9/9 | 7/9 | −0.00007184 | +0.060 ms |
| Bounds exact | 9/9 | 7/9 | −0.00005815 | +0.063 ms |
| Full-source or coarse ID | 9/9 | 8/9 | −0.00008074 | +0.067 ms |

All three use the same face ceiling. Bounds greedy consumes a median
102,125 more triangles than the group allocation and adds one to three
draws. It lowers FLIP by a median paired 1.47%, improves PSNR and SSIM on
all nine views, and reduces foreground XOR on three. The GPU-time
comparison uses the existing eleven modes, screened uniform endpoints,
and area selections from all three group caps. Its frontier improvement
holds in every timing batch on only 4/9 views, versus 7/9 by pooled p50.

Projection and greedy selection take a median 0.126 ms across the per-view
CPU medians. GPU time includes the extra bucket draws. The static
measurement pre-uploads buckets and excludes preparation, upload and
application CPU submission. Exact subset optimization improves its
screen-rectangle objective, but chooses the greedy assignment on only
5/9 views and does not improve rendered FLIP consistently.

Source and coarse ownership passes take median GPU times of 1.870 ms and
0.873 ms, respectively, across views. Their synchronized capture wall
times are 36.2 ms and 20.5 ms, including eight untimed warmups and the
readback. The equality of selected instances shows coarse ownership would
be sufficient for this objective on the tested views. The standalone pass
is expensive relative to the measured quality differences. The ID variants
hold in every batch on 5/9 views even with visibility cost outside their
raster times.

The bounding-box greedy arm passes the predeclared static gate by pooled
medians. The gain warrants measuring moving cameras, fully paid CPU/GPU
bucket updates, and a matched utilized-face control on independent
scenes. The small effect and batch sensitivity leave the quality–cost
claim open. The tested screen-area allocation is established prior art.
The frozen incidence checks still leave strict source-boundary and full
topology validation open.

## Reproduce

Use the [group allocation experiment](MIXED_SCENE_LOD_ALLOCATION_20261122.md#reproduce)
for the dependencies and frozen receipts. The GPU and input hashes are
recorded alongside the selected instances.

```powershell
python tools/mmtrain/bench_scene_instance_lod.py --baseline tools/mmtrain/mixed_scene_baselines_720p_20261122.json --allocation tools/mmtrain/mixed_scene_lod_allocation_720p_20261122.json --meshes out/geometry-refinement-pilot/motion-meshes --stock out/mixed-scene/stock --upstream out/deps/meshoptimizer-v1.2 --shader-root out/deps/bevy-smaa --out out/mixed-scene/instance-lod-720p.json
```
