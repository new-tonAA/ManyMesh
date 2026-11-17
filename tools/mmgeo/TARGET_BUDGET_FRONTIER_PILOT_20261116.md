# Target-Budget DAG Frontier Pilot (2026-11-16)

## Question

Does the existing `--dag-group` setting produce a useful quality/build-cost frontier
when the requested triangle budget is fixed? This is a control for the proposed
target-conditioned repair work, not a new method.

## Frozen run contract

- Input: `third_party/meshoptimizer/demo/pirate.obj`, SHA-256
  `cf11ea6f1fad6688123fbb80c5ca39ad5e48908cfa53d68e09a3f03f53c524a1`.
- Executable: `out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe`, SHA-256
  `46b5ab1fe0cbf2ab9c2e1eb900fd94dfb7df08665eddce955118849e96774900`.
- Relevant source content hashes match the binary provenance already recorded in
  `SIGGRAPH_2027_LITERATURE_DELTA_20261115.md`: `main.cpp`
  `1ca3c71a1f514129778858782b80ddfa24ee65441a59d80d3b4c6b1e44486820`, `LodGraph.cpp`
  `9a5e5dab0e12762803c74db5b35bab2756f6998a96e584eb32e40e14f2a5460e`, and `Simplifier.cpp`
  `9c7dcfce176df66b10aac6f4bcd35a6e71f53cbb4bb8b2612b4af2f0c4523f5a`.
- Workspace `HEAD` when rerun: `6836c6e484b19010cfce7d413429141020f169bc`.
  The tree is dirty; the content hashes above, rather than `HEAD` alone, bind the
  relevant sources. Build flags are not independently recorded.
- Shared arguments: `--mode dag --levels 7 --ratio 0.7 --tier balanced
  --target-ratio 0.55 --corner-seam 1 --corner-split-uv 1 --quality-gate 1
  --dump-obj 0 --write-dag 1 --target-ratio-cut 0.55,0.60,0.65`.
- Each group size was rerun once, sequentially, with a fresh output directory under
  `out/targetbudget-frontier-pilot-20261116/pirate-gN/`.

## Results

| `--dag-group` | Build time (s) | Total mmgeo time (s) | Nodes / levels | Selected faces | Reported worst selected screen error (px) |
|---:|---:|---:|---:|---:|---:|
| 2 | 0.51 | 0.52 | 195 / 8 | 2,756 (55.01%) | 19.3397 |
| 4 | 1.64 | 1.65 | 188 / 10 | 2,756 (55.01%) | 21.1741 |
| 8 | 2.90 | 2.91 | 184 / 9 | 2,756 (55.01%) | 12.4154 |
| 16 | 3.05 | 3.07 | 183 / 9 | 2,756 (55.01%) | 20.4373 |
| 32 | 3.17 | 3.18 | 181 / 9 | 2,756 (55.01%) | 12.5229 |

All five runs reached the same target-selected cut size. The reported screen error is
the executable's auto-camera cut metric (1920x1080); it is not a measured image-space
distortion against a reference render. Group 8 has the best value among these five
settings. Relative to group 2 it lowers the reported error by 35.8%, at 5.69x the
build time. Group 4 is slower and has 9.5% higher error than group 2; group 16 is
slower and has 5.7% higher error. Group 32 is close to group 8 in error (0.9% higher)
and takes 9.3% longer to build.

## Interpretation and next gate

The relation is non-monotone. A fixed group-size sweep therefore provides a tuning
baseline, not evidence for selective repair or a paper contribution. It also gives a
concrete cost ceiling for a next counterfactual: compare candidate repairs against the
current hierarchy and blind 8-to-4-to-2 retry at matched construction time, then test
whether the exact offline best repair selection materially improves a **quality-valid**
cut frontier. If the oracle has little gain, close hierarchy repair. If it helps but
greedy marginal frontier gain per build second matches it, this line has no distinct
algorithm yet.

Limits: one asset, one run per setting, one selected target budget, one auto camera,
and no reference-image quality measurement or held-out assets. This pilot does not
establish robust timing, perceptual quality, a repair gain, or novelty.

An older Pirate regroup-diagnostic pool provides a separate weak feasibility check.
Its Linux manifest binds executable SHA-256
`13df2f63bfab914493840f45a7c55a2e51d27c4f80a5047c152178e3144c03ea` and source commit
`edb6ecc7a16e3a68b7b0be80a1317e8e21dd6f16`; it is not this pilot's Windows executable
or a matched build-time comparison. The 48 recorded trials were split across local
baselines of 180, 176, and 1,174 triangles. Every alternative used more local triangles
(ranges 192–206, 186–192, and 1,288–1,426 respectively); none gave lower error at no
more faces. Some alternatives did lower local error while spending more faces, so this
does not rule out global reallocation among nodes. It does make a face-saving local
repair oracle on this existing candidate pool unlikely. Source data:
`out/regroup-diagnostics-cache-fix/manifest.json`,
`out/regroup-diagnostics-cache-fix/summary.json`, and
`out/regroup-diagnostics-cache-fix/pirate-1/diagnostics.json`.

The next oracle comparison must assemble alternatives into complete legal cuts at each
frozen budget and measure the whole build/memory cost. Summing isolated local errors or
using the diagnostic's `improves` bit is insufficient for that claim.

## Artifacts

Each run directory contains the captured `run.log`, `lod_graph.json`, `lod_graph.mmb`,
and the same three requested cut exports (`selected_ratio_0.55.ply`,
`selected_ratio_0.6.ply`, `selected_ratio_0.65.ply`). JSON SHA-256 values:

| Group | `lod_graph.json` SHA-256 |
|---:|---|
| 2 | `345eee5ce897d34d6b57dbbcf7ac745f2150cdeb2a02e54a76340d04b2871136` |
| 4 | `d005f9299714416c119dc5a60859725624f22cb3658dbf89244a1bdb3f6767de` |
| 8 | `e5757b9451f95bfa6da3ee0b3fe4c4979b0e873792859776744ec4171be26b66` |
| 16 | `3c7abd5cb396c6a6ad75269af5178bcef3e55e1b82a15ed0892d560e201f216f` |
| 32 | `0da060fecfd290576fdedbfc27eaeadb153a82f0a7ee8333c0f2d27e529cc055` |

## Follow-up: full-orbit coverage/depth raster diagnostic

To check whether the auto-camera sphere-error ranking reflects visible geometry, I compared the
saved 55% cuts against the source Pirate mesh using the repository's supersampled two-sided CPU
coverage/depth rasterizer. The source and all cuts use the same normalized orthographic camera,
16 evenly spaced azimuths, 256x256 output, 2x raster supersampling, Gaussian sigma 0.9, and
box downsampling. Each target cut has exactly 2,756 triangles. The metric is the sum of filtered
binary-coverage and normalized first-hit-depth SSE, averaged across the 16 views.

| `--dag-group` | Build time (s, single run) | Mean filtered total SSE ↓ | Coverage SSE | Depth SSE | Raw supersample coverage mismatch |
|---:|---:|---:|---:|---:|---:|
| 2 | 0.51 | **50.4305** | 39.9904 | 10.4401 | 0.2662% |
| 4 | 1.64 | 59.0186 | 46.8010 | 12.2176 | 0.3029% |
| 8 | 2.90 | 53.1926 | 42.6330 | 10.5595 | 0.2767% |
| 16 | 3.05 | 52.1492 | 41.5508 | 10.5983 | 0.2724% |
| 32 | 3.17 | 53.0815 | 42.3899 | 10.6916 | 0.2738% |

For this diagnostic, group 2 has both the lowest mean coverage/depth SSE and the shortest recorded
build. Group 8's mean SSE is 5.48% higher than group 2, despite its 5.69x recorded build time.
Across the five group-size points, the rank correlation between the original auto-camera sphere
error and this 16-view raster SSE is Spearman rho = 0.10; with only five settings this is
descriptive, not a statistical result. The coarse proxy's group-8 win therefore does not transfer
to this simple multi-view visibility objective.

This remains a single mesh, one elevation, one resolution/filter setting, and geometry-only
coverage/depth. It omits material, texture, normals, PBR lighting, user studies, varied camera
trajectories, and multiple assets. Build times are the original single runs, not randomized
measurements. It is a stronger falsification of the group-8 proxy claim, not a paper-quality
benchmark or a new algorithm result.

Reproduce with `python tools/mmgeo/audit_target_budget_visibility.py`. The output is
`out/targetbudget-frontier-pilot-20261116/visibility_audit.json`, which binds the source mesh,
five graphs and PLY cuts, rasterizer, analysis script, executable, and relevant C++ sources by
SHA-256.
