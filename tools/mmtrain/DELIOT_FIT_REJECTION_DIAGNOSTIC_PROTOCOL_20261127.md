# Deliot-style fit rejection diagnostic protocol

Frozen 2026-11-27 before the diagnostic rerun. This is instrumentation of the
already-failed local Deliot-style fit, not a new method or quality experiment.
It replays the original 16 training views, 5,290-face inputs, random seeds,
renderer, perturbations, Adam updates, guards, and line search exactly. It does
not load or score the previously examined 24 diagnostic views. The only
question is which guard or loss condition rejects each line-search trial.

## Falsifiable question

Do all 40 candidate trials (2 arms × 4 updates × 5 halvings) fail the face
normal/degeneracy guard before training-loss evaluation, as inferred from the
prior render counts, or are any trials rejected for a different reason?

Record, for every trial, the minimum face-normal dot ratio, degenerate-face
count, whether the trial reaches training-loss evaluation, and whether its
loss is accepted. Do not change any parameter, use any evaluation view, or
interpret this replay as a pass/fail quality result. A run with mismatched
frozen input hashes or adapter is invalid and stops without fallback.

## Frozen inputs and execution

- Asset: Thingi10K 84736, train split, CC BY; source SHA-256
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Geometry archive SHA-256
  `3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`.
- Prior Deliot-fit raw receipt SHA-256
  `e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a`.
- Reuse the first fit's 16 training camera matrices, `SEED=20261127`,
  `GRADIENT_SAMPLES=8`, `UPDATES=4`, `EPSILON=1/288`, Adam settings, boundary
  locks, displacement cap, and normal floor from
  `fit_deliot_msaa_per_pixel_dev.py` without modification.
- Use the same original-source 2x 4x-MSAA reference and 640x640 D3D12
  candidate rasterizer on Intel Iris Xe. Do not run image-quality scoring.
- Save only the diagnostic receipt. No candidate geometry is promoted and no
  production/API/format changes follow from this diagnostic alone.

## Reproduction

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/diagnose_deliot_fit_rejections.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --fit-receipt out/deliot-msaa-per-pixel-dev-20261127/result.raw.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/deliot-fit-rejection-diagnostic-20261127/result.json
```

This diagnostic can distinguish a geometry-guard dead end from stochastic
loss non-improvement. It cannot establish whether a changed optimizer would
improve image quality or generalize to other assets.
