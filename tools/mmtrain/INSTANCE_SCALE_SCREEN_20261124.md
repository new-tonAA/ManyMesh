# Instanced scene scale screen

This is a desktop scalability diagnostic, not a mobile-performance result or
an algorithm contribution. It asks whether the existing offscreen rendering
harness can measure many repeated instances and how a fixed stock cluster cut
trades image quality for GPU time as instance count grows.

## Frozen comparison

- Use the five pinned Khronos glTF Sample Assets `Avocado`, `BarramundiFish`,
  `CesiumMilkTruck`, `Lantern`, and `WaterBottle`. Their source records and
  mesh hashes are embedded in the JSON receipt. The sample assets are CC0 or
  CC BY 4.0; source-list receipts identify each license.
- Test 1,000, 4,000, and 10,000 rigid instances. Distribute the five asset
  types cyclically over one deterministic grid. Keep the grid's world bounds
  fixed at 18 by 13 units, so projected object size decreases as density
  increases. Use one indexed instanced draw per asset type.
- Compare full source geometry against the fixed depth-2 meshoptimizer cluster
  cut. Both use identical transforms, camera, neutral gray directional shading,
  resolution (1280 x 720), and 4x MSAA. Do not cull instances or tune per-count
  parameters. The image-quality reference is the full source rendered with 4x
  MSAA at 2560 x 1440, then box-downsampled in linear light.
- Also capture full-source native rendering without AA as a coverage and
  raster-cost diagnostic. It is not part of the equal-MSAA candidate comparison.
- After eight warm-up frames per mode, collect 12 GPU timestamp samples in two
  batches. Report median and p95 per workload, actual submitted triangles,
  fixed draw count, coverage, LDR-FLIP, PSNR, SSIM, silhouette XOR, and image
  hashes. The three instance counts are workload points, not independent
  samples from an asset population.

## Decision scope

This screen can establish only desktop raster cost and image quality for these
five reused assets under this camera and layout. It excludes CPU scene update,
LOD selection, culling, asset loading, presentation, power, memory peak, motion,
or a strict source-boundary correspondence audit. The receipt does record basic
topology counts for the stock cuts. Those counts reveal that the depth-2
CesiumMilkTruck cut has one duplicate triangle and two nonmanifold edges. The
boundary-edge counts differ from the source for Avocado, CesiumMilkTruck,
Lantern, and WaterBottle. Thus the aggregate image-quality comparison is not
eligible under the strict topology/boundary gate; it is diagnostic only. The
GPU raster timings remain measurements of the submitted index and vertex
buffers. This screen does not establish an end-to-end ManyMesh win, mobile
behavior, or generalization. A follow-up would need eligible cuts from multiple
independently licensed scenes and must time full CPU and GPU frame paths before
making a scalable-LOD claim.

## Reproduction

Run from the repository root with the dependencies listed in the
[mmtrain README](README.md). The following input manifest, extracted PLY files,
stock meshoptimizer cuts, and pinned Bevy shader checkout were local research
artifacts and are not included in the repository. The receipt records their
asset provenance and hashes, but this is not a standalone reproduction bundle.
The command used for this run was:

```powershell
$env:PYTHONPATH = 'out/contour-gpu-pydeps-20261123;out/manymesh-research-pydeps-20261123'
python tools/mmtrain/bench_instance_scale.py `
  --manifest out/geometry-refinement-pilot/motion-96.json `
  --meshes out/geometry-refinement-pilot/motion-meshes `
  --stock out/mixed-scene/stock `
  --shader-root out/deps/bevy-smaa `
  --source-lists out/geometry-refinement-pilot/assets/sources.json out/geometry-refinement-pilot/holdout-assets/sources.json `
  --out out/mixed-scene/instance-scale-20261124.json
```

The raw GPU timestamp samples, deterministic transform hashes, source/cut
provenance, input hashes, shader and script hashes, retry log, and per-workload
image metrics are stored in both
[`instance_scale_repeat_a_20261124.json`](instance_scale_repeat_a_20261124.json)
and [`instance_scale_20261124.json`](instance_scale_20261124.json). The paired
invocation summary and repeat checks are in
[`instance_scale_repeats_20261124.json`](instance_scale_repeats_20261124.json).

## Results

Both final invocations used identical script hashes and produced identical
reference and candidate image hashes and image metrics at all three scene sizes.
The table reports the median of the two invocation-level GPU p50 values, with
the observed two-run p50 range in parentheses. The p95 ranges list the two
invocation p95 values; neither range is a confidence interval. Quality is
measured against the supersampled full-source reference. Delta columns compare
the cluster cut with full-source 4x MSAA at the same output resolution.

| Instances | Source / depth-2 triangles | Indexed draws | Full source 4x GPU p50 (p95 range) | Depth-2 4x GPU p50 (p95 range) | Speedup | PSNR delta | LDR-FLIP delta | Silhouette XOR: source / depth-2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 3,614,800 / 902,400 | 5 | 3.368 ms (3.353–3.384); p95 3.40–9.86 | 1.550 ms (1.545–1.555); p95 1.56–4.10 | 2.17x | -1.118 dB | +0.00925 | 1.070% / 1.317% |
| 4,000 | 14,459,200 / 3,609,600 | 5 | 12.979 ms (11.837–14.120); p95 12.54–14.83 | 3.654 ms (3.267–4.042); p95 3.29–4.66 | 3.55x | -0.388 dB | +0.00420 | 1.850% / 2.083% |
| 10,000 | 36,148,000 / 9,024,000 | 5 | 29.001 ms (28.606–29.396); p95 29.53–31.05 | 6.734 ms (6.724–6.745); p95 7.03–7.38 | 4.31x | -0.190 dB | +0.00168 | 3.191% / 3.433% |

The fixed stock cut submits about 75.0% fewer triangles at each count. At
10,000 instances it reduces the measured GPU raster interval by about 4.3x,
while its 4x-MSAA image is slightly worse on PSNR, LDR-FLIP, SSIM, and coverage
XOR. The 1,000- and 4,000-instance points show a larger quality loss. The
4,000-instance p50 varies by about 16% between invocations, while the 10,000-
instance p50 varies by about 3%. The repeated measurements support a large
workload-specific raster-cost gap, but not a device-wide scaling model or a
reliable tail-latency estimate.

### Topology and boundary eligibility

The receipt's per-asset topology counts make the aggregate image comparison
ineligible under the strict geometry gate. Four cuts change their source
boundary-edge count, and the CesiumMilkTruck cut also has duplicate and
nonmanifold geometry.

| Asset | Source boundary edges | Depth-2 boundary edges | Duplicate faces | Nonmanifold edges | Strict screen |
|---|---:|---:|---:|---:|---|
| Avocado | 38 | 11 | 0 | 0 | Boundary count differs |
| BarramundiFish | 0 | 0 | 0 | 0 | Basic topology counts pass |
| CesiumMilkTruck | 8 | 0 | 1 | 2 | Topology and boundary fail |
| Lantern | 48 | 30 | 0 | 0 | Boundary count differs |
| WaterBottle | 264 | 137 | 0 | 0 | Boundary count differs |

This is a screening table from the recorded edge-incidence counts; no geometric
boundary-curve correspondence audit was run. The closed BarramundiFish cut is
the only asset in this mixed scene whose recorded counts satisfy the basic
screen. Because timings and quality were aggregated across all five assets,
the 10,000-instance PSNR delta is descriptive only and cannot be attributed to
a topology-eligible cut. The GPU timing remains a measurement of the buffers
that were actually submitted.

This is a fixed-view desktop stress test, not a matched-quality or matched-time
winner for ManyMesh. It uses a synthetic fixed-footprint layout of five reused
assets, gray shading, resident geometry, five indexed instanced draws, and no
visibility culling. It measures no CPU update or LOD selection, memory peak,
load time, presentation, motion, device power, or mobile GPU behavior. It does
not validate the stock cuts' topology. The result supports only that a fixed
cluster cut can reduce raster cost in this particular dense desktop workload;
it does not establish that ManyMesh's dynamic hierarchy can select that cut
profitably or that the quality loss is acceptable.

The run used Intel Iris Xe Graphics, driver 31.0.101.4502, D3D12, wgpu 0.33.0,
and 1280 x 720 output. The exact source and cut counts, reference and image
hashes, per-mode timing samples, asset licenses, geometry hashes, shader hashes,
and benchmark hash are in the receipts. The Khronos sample assets are from the
[pinned asset collection](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/f0920f5b32d172a30efe3f9257e965918831e6ea).
