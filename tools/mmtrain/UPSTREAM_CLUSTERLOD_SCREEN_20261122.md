# Upstream meshoptimizer cluster LOD baseline

This screen evaluates the stock meshoptimizer cluster hierarchy on eight reused
[Thingi10K validation assets](THINGI10K_PILOT_DATA_20261120.md). The
[whole mesh comparison](CLUSTER_DECODER_BASELINE_70PCT_VALIDATION_20261122.md)
used a global simplifier from the vendored meshoptimizer. The baseline here
uses the upstream partition, cluster simplification, and complete cut exports.

## Protocol

- Build the unmodified [meshoptimizer v1.2 demo](https://github.com/zeux/meshoptimizer/tree/9d9890c73011d75920af614485296d1e03e95448/demo)
  at commit `9d9890c73011d75920af614485296d1e03e95448`. Run its rasterization
  preset with 128 vertices and triangles per cluster, permissive simplification
  and sloppy fallback. The geometry inputs contain positions and indices.
- Export complete depth 1 and 2 cuts with earlier terminal clusters retained.
  Also export the demo's built-in static view cut at its default error threshold
  (`DUMP=-1`). Score that cut as frozen geometry across all views.
- Verify that the depth 0 export contains exactly the input oriented triangles.
  Verify vertex correspondence and recover the shared source floats from the
  index buffer to prevent decimal OBJ printing from perturbing geometry.
- Request the upstream cut's actual face count from border-preserving whole
  mesh QEM through fast-simplification 0.2.0. Report mismatched face counts
  and rejected outputs. Keep only reduced, count-matched pairs with both
  topology and directed source boundary checks passing in the quality summary.
- Use eight fixed orthographic views at 192x192, 4x pixel sampling, flat
  shading, and 67 pixels per degree for LDR-FLIP. Also measure PSNR, SSIM,
  silhouette XOR, coverage MAE, and sample 10,000 surface points per direction.
  The topology check covers degenerate and duplicate faces and invalid welded
  edge incidence. It does not detect mesh self-intersections.
- The CPU renderer and demo run on Intel Core i7-13700H with Windows 11.
  The demo timing includes process launch, OBJ parsing, hierarchy construction,
  extra diagnostics, and OBJ export. It is not pure build or render timing.

## Upstream cuts versus whole mesh QEM

All 24 exported upstream cuts passed the edge and boundary checks. The demo's
static view left two assets at full resolution. Exact matched QEM comparisons
exclude those ties and preserve QEM failures and face count shortfalls in the
raw receipt. The 95% percentile intervals use 20,000 pairs resampled by asset
within each cut type, seed 20261122.

| Upstream cut | Reduced assets | Valid exact QEM pairs | Mean LDR-FLIP delta [95% interval] | Mean PSNR delta [95% interval], dB |
|---|---:|---:|---:|---:|
| Depth 1 | 8/8 | 6/8 | −0.000976 [−0.001817, −0.000200] | +3.60 [+1.80, +6.22] |
| Depth 2 | 8/8 | 4/8 | −0.016251 [−0.027415, −0.005087] | +7.57 [+4.45, +9.77] |
| Built-in static view | 6/8 | 4/8 | −0.002902 [−0.006832, −0.000380] | +3.65 [+1.55, +6.16] |

Lower LDR-FLIP and higher PSNR favor clusterlod. The deeper comparison retains
only four matched assets. These summaries apply to the shown exact pairs.

## ManyMesh cuts at the same requested budgets

The existing Windows release binary in `out/cmake-vulkan/tools/mmgeo/Release/`
was built on 2026-11-18. The receipt identifies it by SHA-256. The experiment
uses ManyMesh DAG mode with a nominal level ratio of 0.5 and its quality gate
enabled. One build per asset exports two cuts requested at the stock upstream
depth 1 and 2 face budgets. This comparison describes that binary and its
exported cuts. The current C++ worktree has separate changes.

| Thingi10K file | Depth 1 budget → ManyMesh faces | Depth 2 budget → ManyMesh faces | ManyMesh edge and boundary check, both cuts |
|---|---:|---:|---|
| 90431 | 368 → 392 | 184 → 392 | Pass |
| 263198 | 226 → 140 | 112 → 108 | Pass |
| 44710 | 1,586 → 1,586 | 792 → 965 | Fail |
| 191968 | 530 → 408 | 264 → 238 | Pass |
| 383021 | 6,894 → 6,870 | 3,446 → 4,257 | Fail |
| 100894 | 2,910 → 2,849 | 1,454 → 2,849 | Fail |
| 257594 | 17,222 → 17,032 | 8,608 → 11,332 | Fail |
| 94990 | 13,598 → 13,415 | 6,794 → 10,031 | Fail |

ManyMesh meets the face cap and passes the geometry checks on **2/8 assets at
each depth**. At the first depth, both qualifying ManyMesh cuts have higher
LDR-FLIP than clusterlod. At the second depth, one qualifying cut has lower
LDR-FLIP and one has higher LDR-FLIP. There are zero exact face matches that
also pass the topology checks on both sides. The overshoot and topology
failures prevent a matched-budget quality claim for this ManyMesh binary.

The five failing inputs are closed under the same edge audit. On the exported
ManyMesh cuts for depth 1 budgets, the position-welded counts of edges with
three or more incident faces are 2, 31, 8, 320, and 327 for assets 44710, 383021,
100894, 257594, and 94990 respectively. The independent PLY audit agrees with
the binary's nonmanifold counts. The local simplification gate did not ensure
valid whole cuts in this build. The [follow-up audit](../mmgeo/HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md)
traces 676 nonmanifold edges to multiple selected nodes. An offline edge-constrained
selection finds legal cuts at five of the eight same budgets, with worse LDR-FLIP
than upstream on all five. Current source compiled, but Windows application
control blocked execution of the freshly built binary.

Raw metrics and failed rows are preserved in the [upstream receipt](upstream_clusterlod_20261122.json)
and the [ManyMesh receipt](manymesh_clusterlod_control_20261122.json). The current-source follow-up,
which reruns the eligibility gate against a hash-pinned current binary, is documented in the
[current-source audit](CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md).

## Reproduce

Use the Python dependencies from the [codec comparison](GEOMETRY_CODEC_RATE_DISTORTION_20261122.md).
From the repository root on Windows, build the pinned demo with GCC 9.2.0.

```powershell
git clone --depth 1 --branch v1.2 https://github.com/zeux/meshoptimizer.git out/deps/meshoptimizer-v1.2
$src = 'out/deps/meshoptimizer-v1.2'
$units = @(Get-ChildItem -LiteralPath "$src/src" -Filter '*.cpp' | ForEach-Object { $_.FullName })
$units += @("$src/demo/main.cpp", "$src/demo/nanite.cpp", "$src/demo/tests.cpp", "$src/tools/objloader.cpp")
g++ -std=c++11 -O2 -DNDEBUG -o "$src/meshoptdemo.exe" @units
python tools/mmtrain/bench_upstream_clusterlod.py --manifest out/thingi10k-metadata/meshes/download_manifest.json --upstream $src --out out/upstream-clusterlod/validation
python tools/mmtrain/compare_manymesh_clusterlod.py --manifest out/thingi10k-metadata/meshes/download_manifest.json --upstream-receipt out/upstream-clusterlod/validation/receipt.json --mmgeo out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe --out out/upstream-clusterlod/manymesh-control
```
