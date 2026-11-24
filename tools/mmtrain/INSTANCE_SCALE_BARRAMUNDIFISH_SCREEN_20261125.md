# BarramundiFish Instance-Scale Follow-Up — 2026-11-25

## Question and scope

Does the frozen stock meshoptimizer depth-2 cut reduce GPU raster time when a
topology-clean, closed BarramundiFish mesh is repeated in a dense fixed-layout
scene, and what image-quality deltas accompany it? The comparison is full
source versus depth-2 at 1,000, 4,000, and 10,000 instances. Both arms use the
same instance transforms, camera, 1280 x 720 output, and 4x MSAA; the image
reference is full source at 2x resolution with 4x MSAA and a linear-light box
resolve. This is a single-asset desktop diagnostic, not an asset-generalization
study or a ManyMesh contribution claim.

The previous five-asset screen's raw receipt showed a clean closed BarramundiFish
source and depth-2 cut: zero boundary edges, duplicate faces, and nonmanifold
edges in both. The other four assets had changed boundary-edge counts, and
CesiumMilkTruck had duplicate and nonmanifold geometry. This follow-up isolates
BarramundiFish so those ineligible assets do not enter its aggregate image
metrics. No geometric simplification or LOD selection is added; only the scene
asset subset changes.

## Frozen protocol

- Asset identity and license: the pinned Khronos glTF Sample Assets source and
  extracted-geometry hashes in the manifest and source receipt. This asset was
  already used for development and is not held out.
- Geometry: full source (3,864 faces) versus the frozen stock meshoptimizer
  depth-2 cut (966 faces). The cut indices, upstream commit, executable hash,
  and input manifest are hash-checked by the runner.
- Scene: 1,000, 4,000, and 10,000 rigid repeated instances in the same
  deterministic grid spanning 18 by 13 world units. No instance culling or
  per-count tuning. One indexed draw per arm.
- Rendering: Intel Iris Xe, D3D12, wgpu, 1280 x 720 output, flat neutral gray
  directional shading, 4x MSAA. Full-source native rendering is retained only
  as an ancillary coverage/raster diagnostic. Timing excludes CPU updates,
  LOD selection, loading, and presentation.
- Quality: LDR-FLIP, PSNR, SSIM, silhouette XOR, and image hashes against the
  common supersampled full-source reference. Report all three workload points.
- Repeats: two separate invocations. Each has two batches of 12 timestamp
  samples per mode and workload (24 samples total), after warm-up. Report
  invocation p50 values and their range. This range is not a confidence
  interval.
- Decision rule: if the depth-2 arm does not reduce median GPU raster time at
  10,000 instances, close the per-asset raster-cost observation. Report image
  deltas without calling them acceptable or perceptual; that requires a
  broader asset study and, for preference claims, human evidence. Exclude the
  quality comparison if the source/cut topology or closed-boundary audit fails.

The mechanism is a standard meshoptimizer cluster cut, not a new method. Its
strongest comparator here is the full source at the same 4x MSAA, under the
same scene and camera. This measures a geometry-versus-raster-cost tradeoff at
unequal face counts; it does not compare simplifiers at matched face count.

## Reproduction

The frozen mesh and license inputs live in the existing ignored research
directories under `out/geometry-refinement-pilot` and `out/mixed-scene/stock`;
the complete source assets are not vendored. Run twice with the recorded
isolated Python environment and pinned Bevy shader checkout:

```powershell
$env:PYTHONPATH = 'out/contour-gpu-pydeps-20261123;out/manymesh-research-pydeps-20261123'
python tools/mmtrain/bench_instance_scale.py `
  --manifest out/geometry-refinement-pilot/motion-96.json `
  --meshes out/geometry-refinement-pilot/motion-meshes `
  --stock out/mixed-scene/stock `
  --shader-root out/deps/bevy-smaa `
  --source-lists out/geometry-refinement-pilot/assets/sources.json out/geometry-refinement-pilot/holdout-assets/sources.json `
  --assets BarramundiFish `
  --out out/mixed-scene/instance-scale-barramundi-20261125-a.json
```

For the second invocation, change the output filename suffix from `-a` to `-b`.
Each receipt records the selected asset, full manifest and stock-cut hashes,
geometry hashes, renderer and hardware, timing samples, image metrics, and
script hashes.

## Results

Both invocations used identical geometry, script, manifest, and stock-cut
hashes. Reference and candidate image hashes and quality metrics match exactly
across runs at all three workload points. Each invocation recorded 24 GPU
timestamp samples per mode and workload. The table reports the median of the
two invocation p50 values; the range in parentheses is the observed range
between invocation p50s, not an uncertainty interval. Speedup is the ratio of
those median p50 values.

| Instances | Submitted triangles: source / depth-2 | Source 4x GPU p50 (range) | Depth-2 4x GPU p50 (range) | Speedup | PSNR delta | LDR-FLIP delta | SSIM delta | Silhouette XOR: source / depth-2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 3.864M / 0.966M | 3.058 ms (3.057-3.058) | 1.527 ms (1.524-1.529) | 2.00x | -0.380 dB | +0.00272 | -0.00199 | 1.110% / 1.190% |
| 4,000 | 15.456M / 3.864M | 10.524 ms (10.523-10.524) | 2.955 ms (2.953-2.956) | 3.56x | -0.132 dB | +0.00093 | -0.00119 | 2.214% / 2.333% |
| 10,000 | 38.640M / 9.660M | 26.155 ms (26.148-26.162) | 6.657 ms (6.652-6.661) | 3.93x | -0.015 dB | +0.00013 | -0.00024 | 3.563% / 3.670% |

Quality deltas compare the depth-2 render to the source render, both at output
resolution with 4x MSAA, against the common full-source 2x-resolution,
4x-MSAA, linear-light downsampled reference. Positive LDR-FLIP is worse. At
10,000 instances the depth-2 cut submits 75% fewer triangles and reduces the
measured GPU raster interval by about 3.9x, while image metrics are slightly
worse on every reported comparison. At 1,000 and 4,000 instances the PSNR
loss is larger. These figures describe a single reused asset, one fixed view,
one desktop integrated GPU, and this synthetic fixed-footprint layout. The
timings omit loading, CPU work, LOD selection, culling, and presentation; they
are neither full-frame nor mobile results. The comparison is not at equal face
count or equal image quality and does not support a ManyMesh method claim.

An additional welded-topology audit passes vertex-link manifoldness,
orientability, edge incidence, and closedness for both source and cut. Each has
three connected components with Euler characteristic 2; the source/cut
component signatures match. This establishes equal closed orientable
combinatorial surface types for this pair. It does not check geometric
self-intersections, near-coincident seams, attributes, or surface distance.
The source is the pinned Khronos BarramundiFish sample asset, licensed CC0-1.0;
its asset and geometry hashes are in each receipt. Reproduce the stronger audit
with:

```powershell
$env:PYTHONPATH = 'out/contour-gpu-pydeps-20261123;out/manymesh-research-pydeps-20261123'
python tools/mmtrain/audit_instance_scale_topology.py `
  --manifest out/geometry-refinement-pilot/motion-96.json `
  --meshes out/geometry-refinement-pilot/motion-meshes `
  --stock out/mixed-scene/stock `
  --asset BarramundiFish `
  --output out/mixed-scene/barramundifish_topology_20261125.json
```

The audit implementation and output are available as
[`audit_instance_scale_topology.py`](audit_instance_scale_topology.py) and
[`topology receipt`](barramundifish_topology_20261125.json).

As a post-hoc geometry diagnostic, 4,096 deterministic area-weighted surface
samples per direction were measured against the exact nearest triangle and
normalized by the source bounding-box diagonal. The source-to-cut mean distance
is 0.000982, with p95 0.002982 and p99 0.004300; cut-to-source is 0.000977,
with p95 0.003095 and p99 0.004743. Mean nearest-face normal differences are
6.85 and 7.05 degrees, respectively. This is a finite-sample diagnostic, not a
Hausdorff bound or a preregistered acceptance threshold. The full sampling
protocol and raw values are in the [surface-error receipt](barramundifish_surface_error_20261125.json)
and can be reproduced with [`measure_instance_scale_surface_error.py`](measure_instance_scale_surface_error.py).

The raw receipts are
[`run A`](instance_scale_barramundifish_20261125_a.json) and
[`run B`](instance_scale_barramundifish_20261125_b.json). Their exact hashes,
all per-mode timing samples, and all per-workload metrics are retained there.
No additional model or camera was scored, and these reused development data
are not held-out evidence.
