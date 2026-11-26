# Deliot-style per-pixel fit under hardware MSAA: development result

Completed 2026-11-27 on the local Iris Xe/D3D12 laptop. The frozen
configuration failed its advance gate. This is a one-asset feasibility screen,
not a SIGGRAPH contribution, asset-generalization result, runtime benchmark, or
mobile result.

## Decision

At an exact 5,290-face budget, the fixed-topology Deliot-style stochastic fit
did not improve either arm. All four Adam updates for each arm were rejected;
the output positions equal their initial positions. The nonzero estimated
gradients therefore do not count as an optimization result. The candidate also
lost to the exact-face meshoptimizer control on the frozen 24 diagnostic views.
Close this exact optimizer configuration. Do not score the reserved 30-model
pool or treat this result as evidence against other final-reconstruction
objectives.

| Arm | Pooled PSNR | Mean LDR-FLIP | Mean SSIM | Mean silhouette XOR |
|---|---:|---:|---:|---:|
| ManyMesh raw and unchanged fit | 39.036 dB | 0.002960 | 0.994882 | 0.0004652 |
| meshoptimizer raw and unchanged fit | 45.722 dB | 0.001228 | 0.999002 | 0.0003251 |
| ManyMesh minus meshoptimizer | -6.686 dB | +0.001732 | -0.004121 | +0.0001401 |

Lower FLIP and silhouette XOR are better; higher PSNR and SSIM are better.
For sampled source-surface diagnostics, raw and unchanged-fit ManyMesh had
Chamfer L1 0.007581 and absolute-dot normal consistency 0.94160. The
meshoptimizer control had 0.007518 and 0.94015 respectively. These are
20,000-point-per-direction estimates, not exact surface distances.

## What ran

- Asset: Thingi10K 84736, a reused train asset, CC BY; source is the original
  10,580-face mesh. Source SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Inputs: ManyMesh and meshoptimizer LockBorder cuts, both exactly 5,290
  faces and 2,645 vertices. The input DAG archive SHA-256 is
  `3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`.
- Renderer: Intel Iris Xe Graphics, D3D12, `wgpu==0.33.0`; candidate
  resolution 640x640, reference rendered at 1280x1280 and linearly box
  averaged, with hardware 4x MSAA for both. No CUDA was used.
- Optimizer: eight Rademacher perturbation estimates per update, four Adam
  updates, epsilon and learning rate `1/288`, fixed topology, locked boundary
  vertices, maximum cumulative displacement 0.012, face-normal dot-ratio
  floor 0.20, and up to five line-search trials. Training used 16 fixed views.
- Scoring: 24 reused, correlated diagnostic views; LDR-FLIP at 67 pixels per
  degree, pooled-MSE PSNR, SSIM, silhouette XOR, and sampled surface/normal
  diagnostics. These diagnostic views were previously examined and are not an
  untouched test set. WSL CPU metric environment: Python 3.12.3, NumPy 2.3.4,
  SciPy 1.15.3, scikit-image 0.25.2, `flip-evaluator` 1.7.
- Hardware capture took 48.42 seconds wall time and recorded 40 high-resolution
  reference renders plus 2,400 low-resolution candidate/fit renders. This is
  mixed Python/CPU and GPU run time, not GPU frame time. Peak memory was not
  recorded.

The raw trace has nonzero gradient norms, but `accepted_halving` is null for
all eight arm-updates, and train MSE is unchanged. The render counter is exactly
the count for references, base/ID/perturbation renders, and the 96 diagnostic
renders; no line-search candidate entered the training-loss renderer. This is
consistent with every candidate being rejected by the normal guard before
loss evaluation. The runner does not record per-reason rejection counters, so
that cause is an inference from the trace, renderer count, and implementation,
not a directly recorded rejection statistic.

The structural checks pass for the unchanged outputs: exact face counts,
locked vertices, zero degenerate faces, zero displacement, and normal ratio
1.0. The optimizer gate fails because no update was accepted and no training
loss improved. The quality gate fails by -6.686 dB PSNR, +0.001732 mean FLIP,
and -0.004121 SSIM versus the fitted meshoptimizer arm; the SSIM margin is
-0.001.

## Reproducibility

The protocol was frozen before fitting and scoring:
[protocol](DELIOT_MSAA_PER_PIXEL_FIT_DEV_PROTOCOL_20261127.md).
Windows performed D3D12 rendering and capture; the existing WSL virtual
environment scored the captures:

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/fit_deliot_msaa_per_pixel_dev.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/deliot-msaa-per-pixel-dev-20261127/result.raw.json
```

The saved WSL scoring command is:

```bash
python tools/mmtrain/score_deliot_msaa_per_pixel_dev.py \
  --raw-receipt out/deliot-msaa-per-pixel-dev-20261127/result.raw.json \
  --captures out/deliot-msaa-per-pixel-dev-20261127/result.captures.npz \
  --geometry out/deliot-msaa-per-pixel-dev-20261127/result.geometry.npz \
  --out out/deliot-msaa-per-pixel-dev-20261127/result.quality.json
```

The capture archive remains in ignored `out/`; its SHA-256 is recorded below.
Tracked machine-readable outputs are the
[raw hardware receipt](deliot_msaa_per_pixel_fit_dev_raw_20261127.json) and
[quality receipt](deliot_msaa_per_pixel_fit_dev_quality_20261127.json).

| Artifact | SHA-256 |
|---|---|
| Frozen protocol | `283142e1ee6dca95acf27b70da0fe2c681023f5fcc9ba6e43666326dea6ff066` |
| Fit runner at execution | `71f0e3e9afd3cfe477168bf027380352b61eb5107894769eb045441928947486` |
| Scorer | `6019caacc82db603b067d80fec3338d96d2238766f4a189de97e62ffc5c41833` |
| Raw receipt | `e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a` |
| Quality receipt | `a00f31d4451d6b308a06c7277fd7a1cc751fa907a6a2e923123ef84d1adb9d1b` |
| Capture archive, retained locally under ignored `out/` | `56a056b94a499be686ca01d258cb8b107922a90eaa618f895bb90004dd6c8edf` |
| Output geometry archive, retained locally under ignored `out/` | `5a58c1f13da7da0e766819ede8b9fbb17942c0871e9cb08b7be6da68ff895f25` |

The implementation computes perturbations, losses, and gradient accumulation
on the CPU; D3D12 supplies rasterization and per-sample IDs. It is neither the
paper's all-GPU implementation nor a throughput evaluation. The black-box
per-pixel estimator, small number of perturbations, single asset, fixed shader,
correlated views, and lack of explicit rejection counters limit diagnosis.
The next experiment must change the update mechanism or make rejected-step
causes observable under a separately frozen protocol; do not tune this closed
setting against the reused diagnostic views.
