# ReSTIR Nested-LOD Geometry Screen (2026-11-17)

## Question

Does building a coarser mesh by simplifying the immediately preceding LOD change the direct-light ReSTIR proxy error compared with the existing independently generated LOD2, at the same triangle count?

This is an exploratory geometry-mechanism screen. It does not establish a novel simplification method or a SIGGRAPH-ready result.

## Meshes and mapping check

The source is Torus LOD1 (748 triangles). The existing LOD2 has 486 triangles. The alternative target also has 486 triangles and was generated from LOD1 with the current `mmgeo.exe` chain mode, `--ratio 0.65 --attribute-qem 0 --lock-border 0 --quality-gate 0 --target-error 0.1`. This makes the alternative a nested parent-child simplification, while the existing chain levels are generated independently from the input mesh. The quality gate was disabled because the seam boundary constraint rejected this collapse; this is a material limitation.

Both targets had complete sampled UV coverage, zero ambiguous matches, and zero misses in 10,000 UV samples. The separate OBJ combinatorial audit found one supported component and conditional floor 8 for the source and both targets. This audit does not certify geometric quality or self-intersection freedom.

At matched triangle count, the alternative has lower sampled source-to-target displacement at the median and p95, but a worse maximum normal angle:

| Mapping metric | Existing LOD2 | Nested position-QEM target |
|---|---:|---:|
| Normalized world displacement, p95 | 0.01784 | 0.00565 |
| Normalized world displacement, p99 | 0.02553 | 0.01089 |
| Geometric normal angle, p95 | 36.79 deg | 12.22 deg |
| Geometric normal angle, p99 | 43.04 deg | 18.05 deg |
| Geometric normal angle, maximum | 57.13 deg | 80.63 deg |
| Area Jacobian, p95 | 1.421 | 1.106 |

This is not a geometry-error-matched comparison: most sampled distortion metrics favor the nested target, while the extreme normal deviation is worse.

## Paired direct-visibility screen

The screen uses a synthetic Phong surface (diffuse 0.25, specular 0.75, exponent 64), four colored directional lights, six discrete views, mesh self-visibility, 128 candidates per batch, 2,048 batches, and a 0.05 uniform proposal floor. Same-LOD and cross-LOD cases share candidate streams. Baseline and alternative target runs also share the source candidate stream within each seed. The two seeds are independent. Every run had zero UV misses and zero ambiguous mappings.

| Seed | Existing LOD2 cross/same MSE | Nested target cross/same MSE | Baseline paired delta | Alternative paired delta | Alternative minus baseline, bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| 20261130 | 1.397 | 0.997 | +0.554 | -0.0038 | [-0.908, -0.273] |
| 20261202 | 1.139 | 0.993 | +0.195 | -0.0099 | [-0.312, -0.107] |

Both paired alternative-minus-baseline intervals are strictly negative. In each run, the alternative target's own cross-minus-same interval includes zero, while the existing target's interval is positive. This supports the narrow finding that changing the target geometry can remove the mean penalty in this particular direct-light proxy.

The paired effect is tail-driven rather than typical-batch improvement. The median alternative-minus-baseline delta is slightly positive in both seeds (+0.108 and +0.112), while its 99th percentile is only +2.46 and +2.30; the most negative outliers are -201 and -52. The nested target mainly removes rare, very high-error events from the existing target. That behavior matches the earlier heavy-tail observations but makes the estimated mean sensitive to seed and tail convergence.

## Cross-asset screen: Sphere L2->L3

The same position-QEM nested-target procedure produced 2,212 triangles from a 3,406-triangle Sphere L2, versus 2,214 triangles in the existing L3. The 2-triangle difference is 0.09%. Both targets had complete support and zero ambiguity in 20,000 UV samples; the OBJ combinatorial audit accepted one component with conditional floor 252. At common UV samples, p95 normalized displacement was effectively equal (0.0030575 baseline, 0.0030568 alternative); p95 normal deviation was 6.61 deg vs. 5.47 deg, while maximum area Jacobian was worse for the alternative (6.03 vs. 4.88).

Two independent paired direct-visibility runs (4,096 batches x 32 candidates) measured:

| Seed | Existing L3 cross/same MSE | Nested target cross/same MSE | Baseline paired delta | Alternative paired delta | Alternative minus baseline, bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| 20261204 | 1.056 | 1.023 | +0.0765 | +0.0309 | [-0.0887, -0.0043] |
| 20261206 | 1.076 | 1.027 | +0.1018 | +0.0359 | [-0.1231, -0.0178] |

Both paired intervals are strictly negative. Their paired-delta-change medians are only +0.0128 and +0.0044, with minima -37.97 and -69.45, again indicating a tail-driven mean reduction. The direction reproduces on this second asset, but the effect is modest and remains a direct-light proxy.

## Matched-budget construction-path control: 314 faces

To separate nested construction from ordinary QEM, a second 314-triangle target was generated directly from the 1,152-triangle Torus LOD0 using the same position-only QEM settings (`--mode chain --levels 2 --ratio 0.273 --target-error 0.1 --lock-border 0 --attribute-qem 0 --quality-gate 0`). The nested comparator is the 314-triangle target simplified from the 486-triangle nested level. Both targets have 100% support in 20,000 common-seed UV samples, zero ambiguous hits, and one supported closed component in the combinatorial audit.

The direct-from-LOD0 target has lower sampled p95 displacement and normal error, while its maximum normal error is slightly higher. The comparison is therefore not geometry-quality matched:

| Metric | Nested 314 from 486 | Direct 314 from LOD0 |
|---|---:|---:|
| Triangles | 314 | 314 |
| Normalized displacement p95 / p99 | 0.01295 / 0.02084 | 0.01101 / 0.01726 |
| Normal angle p95 / p99 / max | 26.84 / 40.38 / 47.76 deg | 21.23 / 32.08 / 49.94 deg |
| Area Jacobian p95 / p99 / max | 1.372 / 1.634 / 2.436 | 1.312 / 1.529 / 1.842 |

The direct-visibility estimator was rerun at M=128 with the exact reference-sampling settings used by the nested-target manifests (16 reference samples per face, 2 replicates). Paired common-random changes in cross-minus-same normalized MSE were:

| Seed | Nested cross/same ratio | Direct cross/same ratio | Nested delta | Direct-from-LOD0 delta | Direct minus nested, bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| 20261130 | 1.125 | 1.066 | +0.17465 | +0.09200 | -0.1790 to +0.0118 |
| 20261210 | 1.117 | 1.113 | +0.16336 | +0.15809 | -0.1082 to +0.1018 |

Both intervals cross zero. The paired difference is heavy-tailed; the median is slightly negative in both runs, while mean differences are unstable across seeds. These data do not show that nested construction improves the direct-light proxy over direct ordinary QEM at the same triangle count. They also do not isolate a ReSTIR-aware objective, because the targets differ in geometric error and both use ordinary position QEM.

## More aggressive budget check: 204 faces

A sequential 204-triangle target from the 314-face nested mesh retained complete sampled UV support. Its p95 displacement is close to the 486-face baseline (0.01756 vs. 0.01784), but its maximum normal angle and area-Jacobian tail are worse. At M=128, paired alternative-minus-baseline intervals cross zero for both seeds: [-0.421, +0.485] and [-0.645, +0.049] (bootstrap 95%). This is inconclusive at the lower budget and gives no evidence of a stable quality-risk gain.

## Cross-asset construction-path control: Monkey LOD0->LOD2

A 11,700-face direct-from-LOD0 position-QEM target was compared with the 11,702-face existing LOD2 (0.02% face-count difference) using 20,000 common UV samples. The direct target improved p95 normalized displacement (0.000399 vs. 0.001299) and p95 normal angle (2.08 vs. 5.06 degrees), but worsened maximum area Jacobian (8.29 vs. 5.10) and missed one sampled UV mapping point (estimated support 99.97% vs. 100%). Both targets pass the same OBJ combinatorial audit (three components, conditional floor 164); this is not a geometric-quality-matched comparison.

Two common-random 2,048x32 glossy direct-visibility seeds were run. The existing target had cross/same MSE 1.120 and 1.021 (both paired family intervals include zero); the direct-QEM target had ratios 1.019 and 1.008 (seed 1 family interval [+0.0006, +0.0482], seed 2 [-0.0042, +0.0267]). The paired alternative-minus-baseline changes in cross-minus-same MSE were -0.1335 (normal 95% [-0.2946, +0.0276], bootstrap [-0.3119, +0.0027]) and -0.0171 (normal [-0.0601, +0.0259], bootstrap [-0.0631, +0.0229]); both intervals cross zero and the means differ substantially. The direct-QEM mesh is better on p95 geometry but has a worse maximum Jacobian and 14-16 UV misses per 65,536 candidates. The matched-random screen therefore finds no robust advantage for this ordinary alternative, and the remaining geometry confound prevents attributing the first-seed direction to collapse path or estimator awareness.

## What this does not establish

- All tested alternatives are ordinary position QEM with the quality gate disabled; they are not ReSTIR-aware and are not a new collapse-order objective.
- The original 486-face nested comparison is confounded by better p95 geometry. The 314-face construction-path control finds no statistically resolved nested-versus-direct-QEM difference and remains geometry-mismatched.
- The screen covers two assets with one LOD transition each, synthetic Phong shading, direct lighting, and one surface vertex, with two seeds per asset. It has no camera-path estimator, multiple bounces, temporal/spatial reservoir history, or full-image metric.
- ReSTIR-LoD already provides cross-topology UV mapping and area Jacobians. Progressive/nested mesh construction is prior art. The remaining candidate is only whether a ReSTIR-aware hierarchy improves the full estimator/error/correlation/cost frontier over those baselines.

The next useful experiment is an equal-budget, geometry/appearance-matched comparison against both ordinary QEM and illumination-driven reduction, followed by full path tracing with current ReSTIR reuse controls. A SIGGRAPH-level claim also requires held-out assets/materials/views and a quality-cost frontier.

## Reproducibility

- Alternative generation: `mmgeo.exe` SHA-256 `46b5ab1fe0cbf2ab9c2e1eb900fd94dfb7df08665eddce955118849e96774900`.
- Alternative OBJ: `out/restir-alt-lod-screen-20261117/position-qem-unlocked-ungated/lod1.obj`, SHA-256 `9bb39a3d46ea55d706950ba11fc85592f1243afa773bcdccde6efa59f575dfa7`.
- UV mapping manifests: `out/restir-alt-lod-screen-20261117/baseline-lod2-uv-transport.json` and `out/restir-alt-lod-screen-20261117/position-qem-unlocked-ungated/uv-transport.json`.
- Topology audit: `out/restir-alt-lod-screen-20261117/obj-topology-audit.json`.
- Sphere alternative: `out/restir-alt-lod-screen-20261117/sphere-position-qem-unlocked-ungated/lod1.obj`; UV and topology manifests are in the same folder and `out/restir-alt-lod-screen-20261117/sphere-topology-audit.json`.
- Sphere direct-screen manifests and paired analyses: `out/restir-alt-lod-screen-20261117/sphere-baselineLod3-M32-seed20261204.json`, `sphere-positionQEM-M32-seed20261204.json`, `sphere-positionQEM-minus-baseline-commonseed20261204.json`, `sphere-baselineLod3-M32-seed20261206.json`, `sphere-positionQEM-M32-seed20261206.json`, and `sphere-positionQEM-minus-baseline-commonseed20261206.json`.
- Direct-visibility driver SHA-256 for paired runs: `a53df25e8bbc01f0d8d955eed416f0cd46940a1be70787ba9fe9d5bcbd73b76d`.
- Estimator manifests and paired analyses are in `out/restir-alt-lod-screen-20261117/`.
- Direct-from-LOD0 314-face target: `out/restir-alt-lod-screen-20261117/torus-direct-314-from-lod0/lod1.obj`, SHA-256 `8fd3c99f4ae0dd1b898fc4e98e1a76ffbf44fdd2c47c933d995e8ea9e3f4ed24`; UV and topology manifests are in the same directory. Its paired direct-light runs are `torus-direct-fromL0-M128-seed20261130-matchedref.json` and `torus-direct-fromL0-M128-seed20261210-matchedref.json`; paired nested-versus-direct analyses are `directFromL0-minus-nested314-commonseed20261130.json` and `directFromL0-minus-nested314-commonseed20261210.json`. The preliminary seed-20261130 run with 64 reference samples per face and 4 replicates is not used in paired analysis; the `matchedref` runs are authoritative.
- Monkey direct-from-LOD0 target: `out/restir-alt-lod-screen-20261117/monkey-direct-from-lod0-qem/lod1.obj` (11,700 faces); UV support report `monkey-direct-qem-uv-support.json`, topology report `monkey-direct-qem-topology.json`, paired screen manifests for seeds 20261120/20261121 and paired analyses `monkey-direct-qem-minus-baseline-seed20261120.json` and `monkey-direct-qem-minus-baseline-seed20261121.json`.
- No production C++ changed and no software tests were run.
