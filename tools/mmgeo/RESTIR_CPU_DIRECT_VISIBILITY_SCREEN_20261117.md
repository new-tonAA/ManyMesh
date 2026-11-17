# ReSTIR-LoD CPU Direct-Visibility Screen (2026-11-17)

## Question and scope

Does the one-vertex, paired RIS/GRIS estimator show a cross-LOD error change after adding actual mesh self-visibility? This is a mechanism screen for the low-confidence reuse-aware LOD hypothesis. It is not a full path tracer, a ReSTIR-LoD reproduction, a collapse-order experiment, or evidence of SIGGRAPH readiness.

The source point is sampled uniformly in UV area on the source mesh, mapped to the target mesh by the existing nearest-surface UV transport, and weighted with the target geometric-area/UV-area Jacobian. Four colored directional lights are used. Glossy runs sum six discrete view directions and use a synthetic Phong material (diffuse 0.25, specular 0.75, exponent 64). Each candidate is tested against the source or target mesh's triangle BVH. Same-LOD and cross-LOD estimators share candidate streams. The error includes both the conditional reservoir-selection covariance and the squared error of the conditional estimator mean.

## Results

### Diffuse negative control

The valid v4 run used 2,048 batches of 32 candidates, a 0.05 uniform proposal floor, and two 16-samples-per-face reference replicates on each of Torus L1->L2 and Sphere L2->L3.

| Transition | Cross/same relative MSE | Paired difference | Family-wise 95% interval | Result |
|---|---:|---:|---:|---|
| Torus L1->L2 | 1.0170 | +0.02217 | [-0.00415, +0.04848] | Not significant |
| Sphere L2->L3 | 0.99934 | -0.000795 | [-0.00455, +0.00296] | Not significant |

The reference relative standard errors were 0.0051% for the Torus source and 0.0585% for its target; for Sphere they were 0.00011% and 0.0053%, respectively. The diffuse direct-light screen therefore provides no evidence of a cross-LOD MSE penalty.

### Glossy Torus L1->L2

All runs used 32 candidates per batch, a 0.05 uniform proposal floor, a synthetic Phong exponent of 64, and zero UV misses or ambiguous mappings.

| Seed / batches | Cross/same relative MSE | Paired delta | 95% normal interval | Bootstrap 95% interval |
|---|---:|---:|---:|---:|
| 20261121 / 1,024 | 2.597 | +2.451 | family interval [-1.702, +6.604] | Not recorded |
| 20261122 / 4,096 | 2.453 | +2.190 | [+0.795, +3.585] | [+1.031, +3.695] |
| 20261123 / 8,192 | 1.868 | +1.313 | [+0.747, +1.879] | [+0.859, +1.942] |

The two independent larger runs both have positive normal and bootstrap intervals. Their point estimates differ materially, so the effect magnitude is not settled. The paired-delta distribution is strongly right-skewed in both: the median is -0.127 and -0.145, the 99th percentile is +23.97 and +20.79, and the maxima are 2,038 and 1,993. Thus the positive expected MSE difference is driven by rare high-error batches; typical batches do not show the same direction. The extreme tail is reproducible, but its probability and convergence rate are not yet characterized.

The conditional normalized reservoir-selection covariance was 1.287 same-LOD vs. 1.414 cross-LOD for the 4,096-batch run, and 1.295 vs. 1.285 for the 8,192-batch run. In contrast, the corresponding total relative MSE differences were +2.190 and +1.313. The added error therefore sits mainly in candidate-set/proposal mismatch for this screen, not in a stable increase of the conditional reservoir-selection term. Mean ESS fell from about 9.31-9.36 to 7.21-7.22. Reference relative standard error on the glossy cross-LOD integral was 0.86% and 0.29% in the two larger runs.

### Candidate count at fixed total candidate budget

The next comparison keeps the total candidate count at 262,144 while changing the batch from 8,192x32 to 2,048x128. The M=128 setting was repeated with two independent seeds.

| Seed / batches x candidates | Cross/same relative MSE | Paired delta | Bootstrap 95% interval | Delta median / 99th percentile / maximum |
|---|---:|---:|---:|---:|
| 20261123 / 8,192x32 | 1.868 | +1.313 | [+0.859, +1.942] | -0.145 / +20.79 / 1,993 |
| 20261124 / 2,048x128 | 1.386 | +0.542 | [+0.289, +0.877] | -0.173 / +9.90 / 160 |
| 20261125 / 2,048x128 | 1.487 | +0.676 | [+0.356, +1.026] | -0.157 / +12.07 / 150 |

At M=128 the tail is smaller, but it remains strongly right-skewed and both independent paired intervals remain positive. The conditional covariance increases by only +0.039 and +0.058, compared with total paired deltas of +0.542 and +0.676. Mean ESS is about 30 on the identity baseline and 17 on the cross-LOD case. This is consistent with larger reservoirs reducing, but not removing, the cross-LOD proposal mismatch in this toy screen; it does not establish the same behavior in multi-bounce ReSTIR.

### Proposal-support floor screen

At M=128 and 2,048 batches, the uniform mixture floor was raised from 0.05 to 0.25 and 0.50. Each floor used a different seed, so these are exploratory cross-vs-same results, not paired estimates of the effect of changing the floor.

| Uniform floor / seed | Cross/same relative MSE | Paired delta | Bootstrap 95% interval | Delta 99th percentile / maximum | Mean ESS same / cross |
|---|---:|---:|---:|---:|---:|
| 0.05 / 20261124 | 1.386 | +0.542 | [+0.289, +0.877] | +9.90 / 160 | 29.97 / 17.10 |
| 0.05 / 20261125 | 1.487 | +0.676 | [+0.356, +1.026] | +12.07 / 150 | 30.10 / 17.19 |
| 0.25 / 20261126 | 1.154 | +0.215 | [+0.126, +0.315] | +8.25 / 34.5 | 25.49 / 15.82 |
| 0.50 / 20261127 | 1.178 | +0.258 | [+0.166, +0.352] | +11.10 / 24.6 | 19.40 / 13.65 |

The separate-seed higher-floor runs appeared to have smaller means, but the common-random-number contrast at seed 20261126 does not support that interpretation. It compares 0.25 minus 0.05 floor with identical source-point samples, proposal uniform variates, reference integrals, and batches. The mean change in cross-minus-same normalized MSE is +0.0044, with a normal 95% interval [-0.1222, +0.1310] and a 10,000-replicate bootstrap interval [-0.1243, +0.1285]. This shows no measurable floor effect in that paired screen. The per-batch contrast remains heavy-tailed, ESS falls at higher floors, and a second paired seed is needed before drawing a general conclusion. Do not claim that raising the floor fixes the mismatch.

### Cross-asset screen: Monkey LOD0->LOD1/LOD2

The same paired glossy direct-light proxy was run on the 15,744-triangle Monkey LOD0 with 32 candidates per batch, a 0.05 proposal floor, and no UV misses. LOD1 has 12,070 triangles and LOD2 has 11,702. At 1,024 batches, LOD0->LOD1 was null (cross/same relative MSE 0.998; family-wise 95% interval for the paired difference [-0.0395, +0.0344]). The LOD0->LOD2 pilot ratio was 1.384, but its two-contrast family-wise interval was wide and crossed zero ([-0.4687, +1.4598]).

LOD0->LOD2 was then repeated with two independent 4,096-batch seeds and eight reference samples per face per replicate:

| Seed | Cross/same relative MSE | Paired mean difference | Bootstrap 95% CI | Family-wise 95% CI | Median / p99 / max paired delta |
|---|---:|---:|---:|---:|---:|
| 20261118 | 1.087 | +0.1134 | [+0.0308, +0.2222] | [+0.0184, +0.2085] | -0.0115 / +2.88 / 139.44 |
| 20261119 | 1.104 | +0.1347 | [+0.0632, +0.2223] | [+0.0547, +0.2148] | -0.0074 / +3.49 / 106.59 |

The mean penalty direction reproduces, but it remains tail-driven: both paired medians are slightly negative. Mean conditional reservoir-selection covariance changes only from 1.064 to 1.059 in the first seed and from 1.060 to 1.070 in the second; mean ESS falls modestly from 7.75 to 7.52 and 7.76 to 7.47. Reference relative standard errors are 0.055%/0.204% and 0.037%/0.283% for same/cross LOD. This suggests that the small added MSE is mainly in candidate-set/proposal mismatch, not a stable conditional reservoir-selection penalty. The LOD0->LOD1 null and LOD0->LOD2 positive result also show that transition strength matters. This is a third-asset mechanism replication only: it uses the existing ordinary LOD chain, not an alternative collapse order, and still has one surface vertex, synthetic shading, no camera paths, no multi-bounce transport, and no temporal/spatial history.

## Interpretation and limits

The glossy screen supports a narrow mechanism hypothesis: a source-conditioned proposal can produce rare, very high-error candidate batches after UV transport to a coarser mesh, even when the area Jacobian is included and the mapped support has no misses. Increasing candidates per batch reduces the tail at fixed total candidate count. The apparent proposal-floor benefit across different seeds disappears in the common-random paired comparison. Positive paired mean-MSE intervals persist in all glossy screens. The diffuse control is null, and the glossy result depends on a synthetic material, four discrete lights, six discrete views, one surface vertex, and one existing LOD transition. It has no camera path domain, multibounce transport, textures, spatial or temporal reservoir history, or inter-frame correlation. No alternative collapse sequence was compared.

The surviving research question remains whether an offline collapse sequence can improve the full ReSTIR error/correlation/cost frontier at equal geometry and total cost. The next screens should characterize tail stability under candidate count, proposal-floor, and material changes, then move to a real path-tracing estimator. The Falcor/ReSTIR-LoD checkout has not rendered a frame because Packman dependency acquisition is blocked by a repeated CloudFront Python-package TLS failure. Until a renderer-level result exists, keep the collapse-order hypothesis low-confidence.

Per-ray geometry LOD is not itself a novelty claim: locally adaptive ray-tracing LOD predates this work. The SIGGRAPH 2026 ReSTIR-LoD paper says ray-footprint/depth selection is possible but its implementation uses one LOD for all rays in a frame. Any future contribution must address correct, efficient reservoir path reuse when paths use different geometry representations, and beat prior runtime reuse controls; a simple per-ray LOD integration is insufficient. See [ReSTIR-LoD (SIGGRAPH 2026)](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/) and [Locally-Adaptive LOD for Hardware-Accelerated Ray Tracing (SIGGRAPH Asia 2023)](https://graphics.cs.utah.edu/research/projects/ray-tracing-hw-adaptive-lod/).

## Reproducibility and audit

- Driver: [`restir_cpu_direct_visibility_screen.py`](restir_cpu_direct_visibility_screen.py)
- Diffuse valid output: `out/restir-cpu-direct-visibility-20261117/direct-visibility-floor005-v4.json`
- Glossy initial screen: `out/restir-cpu-direct-visibility-20261117/glossy-direct-visibility-v1.json`
- Independent glossy runs: `out/restir-cpu-direct-visibility-20261117/torus12-glossy-confirm-4096.json`, `out/restir-cpu-direct-visibility-20261117/torus12-glossy-confirm-8192-seed20261123.json`, `out/restir-cpu-direct-visibility-20261117/torus12-glossy-largeM-2048x128-seed20261124.json`, `out/restir-cpu-direct-visibility-20261117/torus12-glossy-largeM-2048x128-seed20261125.json`, `out/restir-cpu-direct-visibility-20261117/torus12-glossy-floor025-2048x128-seed20261126.json`, and `out/restir-cpu-direct-visibility-20261117/torus12-glossy-floor050-2048x128-seed20261127.json`
- Common-random floor manifests: `out/restir-cpu-direct-visibility-20261117/torus12-glossy-floor005-commonseed20261126.json` and `out/restir-cpu-direct-visibility-20261117/torus12-glossy-floor025-commonseed20261126.json`; paired analysis: `out/restir-cpu-direct-visibility-20261117/floor025-minus-floor005-commonseed20261126.json`
- Monkey LOD0->LOD1/LOD2 pilot: `out/restir-cpu-direct-visibility-20261117/monkey-glossy-two-transitions-pilot.json`; independent LOD0->LOD2 confirmation manifests with batch deltas: `monkey02-glossy-confirm-4096-seed20261118.json` and `monkey02-glossy-confirm-4096-seed20261119.json`.
- The 4,096- and 8,192-batch manifests bind driver SHA-256 `81c268c78977326d79f11e74edaf9ef1c0d8c85459e7d906f34ee19a2f9c24fb`, UV transport helper SHA-256 `c15b87a5d102da2c632d82eb60bb2e5ec88b589a96d24c7870ac33bab75e1d42`, and visibility BVH SHA-256 `3d4b9c3465ac6ff6ff937f9c287b5e2b44a85136248a65f9bf33c9eaa5a44113`.
- The common-random floor manifests bind driver SHA-256 `a53df25e8bbc01f0d8d955eed416f0cd46940a1be70787ba9fe9d5bcbd73b76d`; the paired analyzer is [`analyze_restir_floor_contrast.py`](analyze_restir_floor_contrast.py).
- Three earlier direct-visibility runs are invalid and excluded: v1 used the target Jacobian for the identity baseline; v2 also used the target normal for that baseline; v3 generated one candidate per nominal batch while dividing weights by 32. Only diffuse v4 and the listed glossy manifests are reported here.
- No production C++ changed and no software tests were run.
