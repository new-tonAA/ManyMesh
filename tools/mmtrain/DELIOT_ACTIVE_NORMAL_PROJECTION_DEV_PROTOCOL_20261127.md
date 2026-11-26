# Active-normal projection for the Deliot-style fit: development protocol

Frozen 2026-11-27 before fitting or scoring. This is a numerical feasibility
control motivated by the rejection diagnostic, not a novelty claim. Constrained
mesh-quality optimization with projected directions and feasible line search
has direct prior art; this screen tests its use with the local stochastic
rasterizer gradient and a signed face-normal constraint.

## Question and decision rule

At an exact 5,290-face budget, does projecting each existing Adam proposal
onto the linearized feasible half-spaces of all face-normal constraints allow
the Deliot-style D3D12 fit to complete its four updates and reduce training
loss, while retaining the frozen 0.20 normal-ratio floor and locked vertices?
Compare ManyMesh and the exact-face meshoptimizer LockBorder control with
identical projection settings and costs.

Advance only if all conditions hold:

1. The projected search direction converges to linearized feasibility within
   100 cyclic projections at normalized constraint violation `1e-6` or less
   for every update in both arms.
2. All four updates in each arm are accepted by the original exact normal
   guard, displacement cap, and training-MSE line search; every accepted step
   decreases the 16-view training MSE.
3. Both outputs retain exactly 5,290 faces, preserve locked vertices, have no
   degenerate faces, stay within 0.012 displacement, and meet the exact 0.20
   signed normal-ratio floor.
4. On the 24 previously scored diagnostic views, ManyMesh has lower mean
   LDR-FLIP and higher pooled PSNR than projected meshoptimizer, with mean
   SSIM no more than 0.001 below it.

The 24 views are reused development diagnostics, not confirmation views; the
image comparison cannot establish generalization. Any failed condition closes
this optimizer configuration. A pass permits only a fresh, separately frozen
multi-asset development screen.

## Frozen inputs and comparison

- Asset: Thingi10K 84736 / Thingiverse item 28675, train split, CC BY; original
  10,580-face source OBJ SHA-256
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Geometry archive SHA-256
  `3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`;
  preceding Deliot-fit receipt SHA-256
  `e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a`.
- Arms are the exact 5,290-face ManyMesh cut and exact-face meshoptimizer
  LockBorder control. The source mesh, renderer, flat-face grayscale shader,
  training cameras, 24 diagnostic cameras, sample count, seeds, and all loss
  metrics match the preceding frozen local fit.
- Hardware is Intel Iris Xe Graphics / D3D12, WebGPU `wgpu==0.33.0`; no CUDA,
  mobile device, or software-adapter fallback. References use 1280x1280 4x
  MSAA and linear box-downsampling to 640x640; candidates use 640x640 4x MSAA.
- Preserve eight Rademacher estimates, four Adam updates, epsilon and learning
  rate `1/288`, beta values 0.9/0.999, 0.012 cumulative displacement cap,
  boundary locks, 0.20 normal-ratio floor, and five exact-geometry/loss line
  search trials. The only algorithm change is the projected update direction.

## Projected direction

For face `f` with current vertices `x`, initial oriented area vector `n0`, and
current area vector `n(x)`, define
`g_f(x) = dot(n(x), n0) / dot(n0, n0) - 0.20`. The frozen mesh is feasible
when every `g_f >= 0`. Compute the analytic per-vertex Jacobian row `J_f` of
this constraint, zeroing components for locked vertices. Given the Adam
proposal `s`, use Hildreth cyclic dual projections to solve the Euclidean
projection:

`min_d 0.5 * ||d - s||^2`, subject to `g_f(x) + J_f d >= 0` for every face.

Process faces in stable face-index order. Stop when the maximum linearized
violation is at most `1e-6`, or fail the update after 100 full sweeps. Apply
the existing displacement cap, then retain the original exact nonlinear
normal check and backtracking-loss check. Projection output alone is not
accepted as proof of geometric feasibility.

This adapts the established active-constraint projection idea to a 3D surface
mesh's frozen signed normal-ratio condition. It is not a reproduction of
Blauth and Leithaeuser's PDE shape-optimization algorithm, and it does not
establish a research contribution. See the full-paper audit in
[`siggraph-prior-art-screen`](../../docs/manymesh/siggraph-prior-art-screen-20261123.md).

## Reproduction

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/fit_deliot_active_normal_projection.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --fit-receipt out/deliot-msaa-per-pixel-dev-20261127/result.raw.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/deliot-active-normal-projection-dev-20261127/result.raw.json
```

Score only the saved captures with the existing pinned WSL CPU metric
environment and `score_deliot_msaa_per_pixel_dev.py`. Record complete fitting
time, projection sweeps and residuals, accepted steps, all exact geometry
checks, and per-view image metrics. Do not edit this protocol after scoring.
