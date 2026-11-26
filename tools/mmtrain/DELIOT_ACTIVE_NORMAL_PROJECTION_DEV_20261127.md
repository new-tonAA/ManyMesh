# Active-normal projection for the Deliot-style fit: result

Completed 2026-11-27 on the local Intel Iris Xe/D3D12 laptop. The frozen gate
failed. This is a one-asset development screen for an established numerical
control, not a novelty result, held-out asset study, runtime benchmark, or
mobile result.

## Decision

Hildreth projection made all eight linearized subproblems converge, and exact
geometry checks stayed valid. However, the ManyMesh arm accepted only one of
four updates, at the smallest line-search step (1/16); the meshoptimizer arm
accepted none. ManyMesh training MSE fell 2.44% on that single update, but its
mean LDR-FLIP worsened on the 24 reused diagnostic views. It remains far behind
the exact-face meshoptimizer control. Close this projected-update
configuration; do not tune it on these views or expand it to the reserved
multi-asset pool.

| Arm | State | Pooled PSNR | Mean LDR-FLIP | Mean SSIM | Mean silhouette XOR |
|---|---|---:|---:|---:|---:|
| ManyMesh raw | initial | 39.036 dB | 0.002960 | 0.994882 | 0.0004652 |
| ManyMesh projected fit | 1/4 updates accepted | 39.379 dB | 0.003940 | 0.994072 | 0.0003649 |
| meshoptimizer raw | initial | 45.722 dB | 0.001228 | 0.999002 | 0.0003251 |
| meshoptimizer projected fit | 0/4 updates accepted; unchanged | 45.722 dB | 0.001228 | 0.999002 | 0.0003251 |

ManyMesh versus its own raw initializer gains 0.343 dB PSNR and reduces
silhouette XOR by 0.0001003, but mean FLIP worsens by 0.000980 and SSIM drops
0.000809. Relative to fitted meshoptimizer, it is still lower by 6.343 dB
PSNR, higher by 0.002712 mean FLIP, lower by 0.004930 SSIM, and has slightly
higher silhouette XOR (+0.0000398). Lower FLIP/XOR and higher PSNR/SSIM are
better. The 24 views are correlated, reused development diagnostics; no
confidence interval or generalization claim is supported.

Sampled source-surface Chamfer L1 changed from 0.007581 to 0.007603 for
ManyMesh; absolute-dot normal consistency changed from 0.94160 to 0.94191.
These 20,000-point-per-direction estimates are not exact surface distances.
The meshoptimizer arm was unchanged at Chamfer L1 0.007518 and normal
consistency 0.94015.

The frozen decision was `fail`: structural constraints pass, but not all four
updates were accepted in both arms; both training losses do not improve; the
fitted ManyMesh arm does not beat fitted meshoptimizer on FLIP and PSNR; and
the SSIM margin fails (-0.004930 versus the -0.001 limit).

## Step-level evidence

The projection subproblem converged on every update, using 28-85 full sweeps
for ManyMesh (206 total) and 35-43 for meshoptimizer (158 total). The maximum
linearized violation was below `1e-6` on all eight updates. Exact nonlinear
geometry checks still rejected some full steps, as expected; feasible steps
then often failed the training-loss test.

- ManyMesh accepted only update 0 at halving 4. Its training MSE changed from
  `9.76310e-5` to `9.52472e-5`; later three updates did not improve it.
- meshoptimizer accepted zero updates; its training MSE remained
  `1.27745e-5` throughout.
- Final structural checks passed: both retained exactly 5,290 faces, zero
  degenerate faces, locked vertices unchanged, displacement at most 0.000476,
  and minimum normal ratio at least 0.9432.
- The D3D12 run took 61.19 seconds total, including 40 high-resolution source
  references and 2,864 low-resolution renders. Per-arm fit time was 24.27 s
  for ManyMesh and 22.36 s for meshoptimizer. These are mixed CPU/GPU offline
  timings, not frame-time or a performance claim. Peak process memory was not
  recorded.

The geometry projection is an adaptation of established active-constraint
projection to a signed face-normal ratio. Mesh-quality constraints and
feasible line search already have direct prior art in Blauth and Leithaeuser;
this experiment does not establish novelty. Their method is a comparator for
the numerical technique, not a result for ManyMesh's stochastic raster loss
or cluster DAG. See the [prior-art screen](../../docs/manymesh/siggraph-prior-art-screen-20261123.md)
and [paper](https://arxiv.org/abs/2412.00006).

## Reproducibility and limits

The [frozen protocol](DELIOT_ACTIVE_NORMAL_PROJECTION_DEV_PROTOCOL_20261127.md)
records the mechanism, comparators, exact conditions, and pass rule. The
[raw hardware receipt](deliot_active_normal_projection_raw_20261127.json)
contains per-update projection and line-search traces; the
[quality receipt](deliot_active_normal_projection_quality_20261127.json)
contains all 24 per-view metrics and sampled surface diagnostics.

| Artifact | SHA-256 |
|---|---|
| Protocol | `eaaa9097198aacec8cf0c40f297d2926ef97cfbacb102ad9d137059bff429108` |
| Runner | `dbaca153a35ac46f3fee5933bf54af5e82a0efd96c26f8fc8207e63818e4be35` |
| Scorer | `6019caacc82db603b067d80fec3338d96d2238766f4a189de97e62ffc5c41833` |
| Raw receipt | `dc23e69488f35961fb6ddc1186f88967a7e12dc3093c460aa071be2697c03f6d` |
| Quality receipt | `7127e46e5fbff58cc44c5a60b94e4fe783fc6faaef4013c6d75a47c95dc2b80e` |
| Capture archive (local ignored `out/`) | `fae896b41f729ac7dbf67aa9ad7e78078d5329a76a0ca5a976b406fd9be2ab75` |
| Output geometry archive (local ignored `out/`) | `079bcf1edd3eefaf60afb251fc47981f19eba7194d1395e3799a666e681b8d88` |

Metrics were scored in WSL2 with Python 3.12.3, NumPy 2.3.4, SciPy 1.15.3,
scikit-image 0.25.2, and `flip-evaluator` 1.7. This screen uses one reused
train asset, a flat grayscale shader, previously examined correlated views,
and no production Filament path, SMAA, upscaler, temporal sequence, phone,
equal-frame-time comparison, or human study. The geometry/capture artifacts
remain local under ignored `out/`; the tracked receipts preserve their hashes.
