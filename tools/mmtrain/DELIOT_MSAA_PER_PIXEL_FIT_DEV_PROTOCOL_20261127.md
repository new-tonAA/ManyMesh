# Deliot-style per-pixel fit under hardware MSAA: development screen

Protocol frozen 2026-11-27 before fitting or image scoring. This tests whether
the newly verified local D3D12 per-sample-ID path can produce a useful fixed-
topology image-gradient baseline on one reused training asset. It is not a
faithful reproduction of Deliot et al., a cluster-DAG contribution, or
confirmation evidence.

## Question and pass/fail rule

At an exact 5,290-face budget, can a Deliot-style per-pixel stochastic
finite-difference fit optimize the ManyMesh cut through the actual local 4x
MSAA renderer well enough to beat the same optimizer applied to an exact-face
meshoptimizer LockBorder control, against the original source mesh?

Advance this fixed-topology configuration only if all the following hold:

1. Both fits reduce mean training-view linear RGB MSE relative to their raw
   inputs and complete all four predeclared updates.
2. The fitted ManyMesh cut has lower mean LDR-FLIP and higher pooled PSNR than
   the fitted meshoptimizer control on the 24 diagnostic views.
3. Its mean SSIM is no more than 0.001 below the control.
4. Both outputs retain exactly 5,290 faces, preserve locked vertices, stay
   within 0.012 normalized displacement, and maintain a face-normal dot-ratio
   floor of 0.20 against their own initial geometry.

Any failed condition closes this one-asset configuration; it does not falsify
all final-AA fitting or a future hierarchy-level method. A pass only justifies
a separately frozen development study. The 24 diagnostic views were already
scored in earlier experiments on this train asset and are not an untouched
test set.

## Frozen inputs and split

- Asset: Thingi10K file 84736 / Thingiverse item 28675, train split, CC BY.
- Original source OBJ SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Geometry archive: `out/cluster-dag-multicut-fit-20261127/result.geometry.npz`,
  SHA-256 `3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`.
- One 5,290-face raw ManyMesh cut, initialized from the archive's
  `union_initial_positions` and cut-local vertex mapping; lock the archived
  MMLG cluster-boundary mask. Compare with the archive's exact-face
  5,290-face meshoptimizer LockBorder positions/faces; lock its open-boundary
  vertices. Both inputs must pass the existing topology and boundary audit.
- Training cameras: the 16 deterministic camera/scale bases returned by the
  existing `fit_projective_rgb_cpu.camera_sets()` implementation. They are
  fixed before optimization.
- Diagnostic cameras: the 24 camera bases in the preceding multi-cut fit
  receipt. Reuse is explicitly non-confirmatory; do not tune on the diagnostic
  result or score the reserved 30-model pool.

## Frozen renderer and optimizer

- Use Intel Iris Xe Graphics, D3D12, WebGPU `wgpu==0.33.0`; reject software
  adapters. Do not require CUDA or alter Windows security settings.
- Use the existing flat-face grayscale lighting shader, per-face normals,
  black background, and camera transform. Render the original 10,580-face
  source at 1280x1280 with hardware 4x MSAA, resolve in linear light, and
  box-average to 640x640 for the reference. Render candidates at 640x640 with
  hardware 4x MSAA. The image-loss samples and final image metrics use this
  same output operator.
- Use the Deliot per-pixel stochastic finite-difference estimator: eight
  independent Rademacher sign vectors per update, four updates, and
  `epsilon=1/288` normalized object-space units per vertex coordinate. At the
  near camera distance and 640-pixel width this is approximately a one-pixel
  perturbation per coordinate. Use Adam (`beta1=0.9`, `beta2=0.999`) with
  learning rate `epsilon`.
- Write triangle IDs as `face_index + 1` to a four-sample `r32float`
  attachment; zero is background. Use the ID samples from the unperturbed
  current mesh. Compute one resolved-pixel RGB-MSE difference between the
  plus/minus renders; attribute one quarter of that difference to each covered
  sample's triangle, then map each triangle to its three vertex coordinates.
  This sample-fraction attribution is a ManyMesh implementation choice, not a
  claim from Deliot et al.
- This first feasibility implementation performs perturbation, per-pixel loss
  evaluation, and gradient accumulation in Python/NumPy on the CPU; D3D12
  performs the reference/candidate rasterization and sample-ID writes. It is
  not the paper's all-GPU compute-shader implementation and supplies no
  optimizer-throughput evidence.
- Keep topology fixed. Lock the predeclared boundary vertices, cap cumulative
  displacement at 0.012, reject steps that violate the 0.20 face-normal
  dot-ratio floor, and use a training-MSE backtracking line search with up to
  four halvings. Apply identical settings and render counts to both arms.
- Record total wall time, GPU submissions/readbacks, peak process memory,
  training loss trace, fit geometry, and every per-view diagnostic image.
  Offline fitting cost is not runtime frame-time.

## Metrics, analysis, and limits

Convert resolved linear grayscale images to sRGB and report per-view and
aggregate LDR-FLIP at 67 pixels/degree, pooled-MSE PSNR, SSIM, and silhouette
XOR. Score FLIP in the existing WSL CPU environment because Windows application
control blocks the native FLIP extension. Keep the two fits paired by camera.
Views are correlated and provide no asset-level confidence interval. The
small-sample stochastic estimator, single reused asset, one face budget,
previously examined diagnostic views, flat shader, and desktop-only renderer
limit the conclusion. This screen does not test the production Filament path,
SMAA, upscaling, temporal behavior, mobile performance, or user preference.

## Reproduction

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/fit_deliot_msaa_per_pixel_dev.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/deliot-msaa-per-pixel-dev-20261127/result.raw.json
```

Use the pinned WSL `projective-rgb-venv` to score the saved capture archive
with `score_deliot_msaa_per_pixel_dev.py`. Do not edit the protocol after
scoring; record implementation bugs and safe retries separately.
