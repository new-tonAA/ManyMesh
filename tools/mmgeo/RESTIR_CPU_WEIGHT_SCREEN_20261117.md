# ReSTIR-LoD CPU Weight Screen (2026-11-17)

## Question

Does transporting one-vertex RIS/GRIS candidates between existing ManyMesh LoDs measurably change RGB estimator error, and is the change robust to a broader directional proposal? This is a mechanism preflight for the reuse-aware collapse-order hypothesis, not a full ReSTIR or mesh-quality experiment.

## Estimator and setup

The source point is sampled uniformly in source UV-area measure, then mapped to the target by the existing nearest-UV transport. A discrete colored-light / view-direction candidate is sampled using source-face luminance importance with a uniform directional support mixture. For each mapped candidate,

```text
q(y,k,v) = p_source(k,v | uv) / (sourceUvArea * targetGeomArea/targetUvArea)
w_i      = (1/M) h_i / q_i
g_i      = RGBContribution_i / h_i
```

where `h` is contribution luminance. The exact conditional reservoir-selection covariance trace is

```text
W * sum_i(w_i * ||g_i||^2) - ||sum_i(w_i * g_i)||^2.
```

The test uses the real UV-mapped Torus and Sphere LOD meshes in `out/restir-lod-map-preflight-20261116/`, four discrete colored directional lights, six discrete view directions, and a synthetic glossy material with 0.25 diffuse, 0.75 specular, and Phong exponent 64. Diffuse controls were also run. Each contrast has 4,096 independent batches of 32 candidates; identity and cross-LOD cases share the same candidate stream. The main screen has five transitions and ten shading/transition contrasts, with Bonferroni family-wise 95% intervals. The independent-seed confirmation has two selected glossy contrasts. Every listed cross-LOD run reported zero UV misses and zero ambiguous hits.

The reported ratio is cross-LOD relative total RGB MSE divided by same-LOD relative total RGB MSE. The paired interval is for the difference in those per-batch normalized MSEs, cross-LOD minus same-LOD. Ratios are point estimates; the interval below quantifies the paired difference.

## Main screen, uniform proposal floor 0.05

| Transition | Triangle counts | Relative MSE ratio | Paired difference | Family-wise 95% interval |
|---|---:|---:|---:|---:|
| Torus L0→L1 | 1152→748 | 1.042 | +0.0623 | [-0.0018, +0.1264] |
| Torus L1→L2 | 748→486 | 2.178 | +1.7610 | [+0.5250, +2.9969] |
| Sphere L0→L1 | 8064→5240 | 0.997 | -0.0044 | [-0.0210, +0.0122] |
| Sphere L1→L2 | 5240→3406 | 1.007 | +0.0104 | [-0.0106, +0.0314] |
| Sphere L2→L3 | 3406→2214 | 1.053 | +0.0707 | [+0.0172, +0.1241] |

All five diffuse intervals include zero. The strongest glossy result is Torus L1→L2. Its normalized covariance decomposition changes from approximately 1.278 conditional plus 0.217 between-candidate-set variance at the identity baseline to 1.361 plus 1.895 after transport. Thus most of this toy signal is in candidate-set variance, not the conditional reservoir-selection term. The corresponding mean weight ESS falls from 9.32 to 7.36. Sphere L2→L3 has a smaller increase: conditional covariance stays near 1.10, between-candidate-set variance rises from about 0.235 to 0.306, and ESS falls from 7.52 to 7.09.

## Independent seed and proposal-floor sensitivity

| Transition | Floor | Relative MSE ratio | Paired difference | Family-wise 95% interval |
|---|---:|---:|---:|---:|
| Torus L1→L2 | 0.05, independent seed | 1.878 | +1.3102 | [+0.2897, +2.3307] |
| Sphere L2→L3 | 0.05, independent seed | 1.087 | +0.1179 | [+0.0702, +0.1655] |
| Torus L1→L2 | 0.25 | 1.757 | +1.1885 | [+0.6850, +1.6921] |
| Sphere L2→L3 | 0.25 | 1.037 | +0.0507 | [+0.0072, +0.0942] |
| Torus L1→L2 | 0.50 | 1.420 | +0.6995 | [+0.4148, +0.9842] |
| Sphere L2→L3 | 0.50 | 1.062 | +0.0954 | [+0.0381, +0.1527] |

The positive paired intervals persist at both higher uniform floors. The Torus point estimate is smaller at higher floors, while the smaller Sphere estimate is not monotonic across these runs. Raising the floor also lowers cross-LOD ESS (Torus 6.76 at 0.25 and 6.02 at 0.50; Sphere 6.55 and 5.58), so this is not a free correction. Different floors use independent candidate streams; this sensitivity check does not isolate a causal parameter effect or identify an optimal proposal.

## What this establishes—and what it does not

The repeated Torus and Sphere signals justify testing proposal/geometry interaction in a real renderer. They do not show that a different collapse order can improve the signal: these are existing LOD chains, and no alternate collapse orders were compared. The screen has no camera domain, visibility, shadows, textures, multi-vertex paths, real BSDF/light sampling, iterative spatial or temporal reservoir history, or inter-frame covariance. A synthetic one-vertex RGB MSE cannot stand in for image error or full ReSTIR variance.

A targeted web search for ReSTIR mesh simplification, path reuse with LOD simplification, proposal mismatch with collapse order, and reservoir-based mesh LOD did not surface a paper on optimizing collapse order for the full ReSTIR error/correlation/cost frontier. This is a bounded search, not evidence that nobody has done it. ReSTIR-LoD already establishes cross-topology mapping and area-Jacobian transport; GRIS establishes the need to account for correlated reuse. See the primary sources: [ReSTIR-LoD (SIGGRAPH 2026)](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/), [GRIS foundations (SIGGRAPH 2022)](https://www.siggraph.org/wp-content/uploads/2022/08/ACM-Transactions-on-Graphics-TOG-Vol.-41-No.-4.-2022.html), and [ReSTIR PT Enhanced (I3D 2026)](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/).

## Next research gate

Per the user's 2026-11-17 instruction, the ray-tracing hypothesis is inactive. This one-vertex CPU result is retained only as a bounded diagnostic; it is not image-quality evidence and will not drive the simplifier.

## Reproducibility

- Driver: [`restir_cpu_weight_screen.py`](restir_cpu_weight_screen.py)
- Main manifest: `out/restir-cpu-weight-screen-20261117/source-importance.json`
- Independent seed: `out/restir-cpu-weight-screen-20261117/confirmation-seed-20261118.json`
- Proposal floors: `out/restir-cpu-weight-screen-20261117/floor-025.json`, `floor-050.json`
- Driver SHA-256 in all current manifests: `d34d54d9bfa72b8784f45a717c79dcac0efcdcb7a0cba6a4d2569302ca0f49fb`
- UV transport helper SHA-256: `c15b87a5d102da2c632d82eb60bb2e5ec88b589a96d24c7870ac33bab75e1d42`

No production C++ was changed and no software tests were run.
