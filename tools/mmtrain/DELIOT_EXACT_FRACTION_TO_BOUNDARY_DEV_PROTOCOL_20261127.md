# Exact fraction-to-boundary control for Deliot-style fitting

Frozen 2026-11-27 before this feasibility run. This is a local numerical
control on one reused training asset, not a novelty claim or a quality result.

## Question and decision rule

Does an exact nonlinear fraction-to-boundary scale, applied to the existing
stochastic Adam direction, allow the Deliot-style D3D12 fit to make repeated
training-loss-reducing steps while respecting the original signed face-normal
floor and cumulative displacement limit? Compare the ManyMesh cut and exact-
face meshoptimizer LockBorder control with identical render and optimization
costs.

Advance to a separately frozen image-quality development comparison only if
each arm accepts at least 3 of 4 updates, every accepted update lowers the
16-view training MSE, and both final geometries pass the exact face count,
locked-boundary, displacement, nondegeneracy, and 0.20 signed normal-ratio
checks. Otherwise close this fixed-topology stochastic raster-fit route under
the tested objective and optimizer. This screen does not score diagnostic or
held-out image views.

## Frozen inputs and cost match

- Asset: Thingi10K file 84736 / Thingiverse item 28675, train split, CC BY;
  original source OBJ SHA-256
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Geometry archive SHA-256:
  `3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`.
- Preceding fit receipt SHA-256:
  `e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a`.
- Exact 5,290-face ManyMesh and meshoptimizer LockBorder arms from that
  archive; lock each arm's frozen boundary vertices.
- Hardware is Iris Xe / D3D12 with `wgpu==0.33.0`. Keep the existing 640²
  candidate renderer, 4x MSAA, 16 training camera bases, grayscale shader,
  eight Rademacher estimates per update, four Adam updates, seed, epsilon,
  learning rate, and Adam coefficients unchanged. No CUDA or software adapter.
- The only changed control is the global step fraction. Estimate gradients and
  update Adam state exactly as in the active-normal projection screen, but do
  not project the direction. Compute the first feasible boundary along the
  Adam direction from the exact quadratic signed-area constraints and the
  cumulative per-vertex displacement balls. Multiply the limiting fraction by
  0.9 for a strict interior step, then use the existing five-trial training
  MSE line search. Record both the fraction limit and the exact post-step
  checks.

For a face with `x(α)=x+αd`, the signed normal ratio relative to the initial
face is quadratic: `r(α)=c+bα+aα²`. The permitted region is `r(α)>=0.20`.
The step fraction is bounded by the earliest positive root for every face.
The displacement bound `||x_i+αd_i-x_i^0||<=0.012` is also solved along the
same line. The final acceptance check recomputes all constraints from the
resulting float32 geometry; the quadratic bound alone is not treated as proof.

## Scope and interpretation

Fraction-to-boundary step control is a standard constrained-optimization
pattern. This adaptation is an implementation/control check, not a claim of
novel optimization theory. The one reused asset and its training views can
only decide whether this local raster-gradient route is numerically viable;
they cannot establish image-quality superiority, asset generalization, a
cluster-hierarchy contribution, or mobile performance. No final-AA quality
views are scored in this feasibility gate.

## Reproduction

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/fit_deliot_fraction_to_boundary_dev.py `
  --geometry out/cluster-dag-multicut-fit-20261127/result.geometry.npz `
  --prior-receipt tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json `
  --fit-receipt out/deliot-msaa-per-pixel-dev-20261127/result.raw.json `
  --source out/stream-rate-distortion-preflight-20261127/84736/source.obj `
  --out out/deliot-fraction-to-boundary-dev-20261127/result.raw.json
```
