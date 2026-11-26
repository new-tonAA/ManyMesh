# Shared-position multi-cut fit after hardware MSAA

Status: **the prior negative ranking did not reverse**. The already-fitted
joint ManyMesh geometry lost to the fitted exact-face control after a real
Intel Iris Xe D3D12 4x MSAA resolve at all three face budgets. This was a
post-hoc renderer-sensitivity check of one reused train asset; it is not a new
method result or independent generalization evidence.

## Results

Every comparison uses the original 10,580-face Thingi10K 84736 source OBJ,
the same 24 reserved views from the CPU experiment, and exact equal face
counts. The reference is the original source rendered at 1280x1280 with 4x
MSAA, resolved and box-averaged in linear light to 640x640. Candidate and
control meshes were rendered at 640x640 with native sampling and hardware 4x
MSAA. The fitted control is meshoptimizer LockBorder at 2,286 and 5,290 faces;
the predeclared exact-face QEM fallback is used at 7,934 because the
meshoptimizer output failed the topology audit before scoring.

The table reports candidate minus fitted-control quality. Higher PSNR and
SSIM are better; lower FLIP and silhouette XOR are better.

| Faces | Control | Native Δ PSNR / FLIP / SSIM | 4x MSAA Δ PSNR / FLIP / SSIM | 4x MSAA Δ silhouette XOR |
|---:|---|---|---|---:|
| 2,286 | meshoptimizer | −2.3870 dB / +0.002288 / −0.005211 | −6.8645 dB / +0.002449 / −0.005308 | +0.0001650 |
| 5,290 | meshoptimizer | −1.5423 dB / +0.001887 / −0.004653 | −5.7162 dB / +0.002105 / −0.004306 | +0.0000821 |
| 7,934 | QEM | −0.4282 dB / +0.000905 / −0.001775 | −2.7113 dB / +0.001019 / −0.001490 | +0.0000201 |

The frozen reversal rule required the joint fit to improve both mean FLIP and
pooled PSNR at two or more budgets. It did so at **zero of three**. MSAA did
not rescue this fitted candidate. At 4x MSAA, the candidate's absolute
PSNR/mean-FLIP/mean-SSIM were 37.2477 dB / 0.004436 / 0.992586 at 2,286
faces; 39.8750 / 0.003446 / 0.994553 at 5,290; and 43.2878 / 0.002007 /
0.997707 at 7,934. The corresponding fitted controls scored 44.1122 /
0.001987 / 0.997894; 45.5912 / 0.001341 / 0.998859; and 45.9990 /
0.000989 / 0.999197.

The view rows are correlated camera samples on a single training asset. They
do not support asset-level confidence intervals. This result only says the
previous candidate/control ordering persists under this particular hardware
rasterizer and flat-shaded grayscale shader.

## Protocol and cost scope

The source asset is Thingi10K 84736 (Thingiverse item 28675, CC BY), source
OBJ SHA-256
`b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`. The
geometry archive was pinned to SHA-256
`3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`; each
arm retained the exact requested face count. The comparison reused the prior
24 view/scale pairs and did not refit or tune geometry.

The capture device reported Intel Iris Xe Graphics, D3D12, driver
31.0.101.4502, Windows 11 build 26200, WebGPU 0.33.0, and Python 3.12.3.
The same pinned flat-face shader and transfer path were used for every arm.
The 360 hardware captures are held in the ignored local file
`out/cluster-dag-multicut-final-msaa-20261127/result.raw.captures.npz`
(2,402,062 bytes; SHA-256
`457a99554d2b417126ec0046509d888edea82140793951c8c80d104f6bf3834d`).

Windows application control blocked the unsigned native FLIP extension, so
the raster images were captured on Iris Xe and scored in the existing WSL2
CPU environment. The metric environment was CPython 3.12.3, NumPy 2.3.4,
scikit-image 0.25.2, and flip-evaluator 1.7. No Windows protection setting
was changed. This experiment did **not** measure GPU time, equal-frame-time
quality, SMAA, an upscaler, Filament's production material path, mobile
hardware, or perceptual preference.

## Reproduction and receipts

The [frozen protocol](CLUSTER_DAG_MULTICUT_FINAL_MSAA_RECHECK_PROTOCOL_20261127.md)
records the comparison and rejection rule. The capture runner
([Windows D3D12](bench_cluster_dag_multicut_final_msaa.py)) writes raw captures;
the scorer ([WSL CPU metrics](score_cluster_dag_multicut_final_msaa.py)) computes
PSNR, SSIM, FLIP, and the precomputed silhouette-mask XOR.

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/bench_cluster_dag_multicut_final_msaa.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/cluster-dag-multicut-final-msaa-20261127/result.raw.json
```

```powershell
wsl.exe -d ManyMesh-Ubuntu-D --exec `
  /root/ManyMesh-build/projective-rgb-venv/bin/python `
  /mnt/e/ManyMesh/tools/mmtrain/score_cluster_dag_multicut_final_msaa.py `
  --captures /mnt/e/ManyMesh/out/cluster-dag-multicut-final-msaa-20261127/result.raw.captures.npz `
  --raw-receipt /mnt/e/ManyMesh/out/cluster-dag-multicut-final-msaa-20261127/result.raw.json `
  --out /mnt/e/ManyMesh/out/cluster-dag-multicut-final-msaa-20261127/result.quality.json
```

- [Hardware capture receipt](cluster_dag_multicut_final_msaa_raw_20261127.json),
  SHA-256 `9105a07fea2ec1720c3c17973144aedda0020529d2668bb96a77e6ff191f8eb8`.
- [Per-view metrics and summary](cluster_dag_multicut_final_msaa_quality_20261127.json),
  SHA-256 `79a4b29e6f2b03f82f758d76b33765bd62807be90bdde3385c0336ca69cb6eeb`.
- Prior [multi-cut fit report](CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.md)
  and its [independent topology/boundary verifier](verify_cluster_dag_multicut_projective_cpu.py).

Close this tested shared-position fit configuration. The broader question of
optimizing a cluster hierarchy specifically for a final AA/upscaler remains
untested; this recheck evaluated already-fitted geometry and cannot support
that method claim.
