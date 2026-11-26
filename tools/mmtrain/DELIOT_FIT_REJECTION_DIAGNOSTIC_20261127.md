# Deliot-style fit rejection diagnostic

Completed 2026-11-27 on the local Iris Xe/D3D12 laptop. This deterministic
replay instrumented the already-failed fit; it did not score image quality or
change any frozen optimizer setting.

## Finding

All **40/40** line-search trials (two geometry arms, four updates per arm, five
halvings per update) were rejected by the face-normal dot-ratio floor. None
was rendered for candidate training loss. No trial was degenerate; every
trial's minimum signed normal ratio was below zero, hence below the required
0.20 threshold. Each failed step included at least one face whose normal had
reversed its projection onto that face's initial normal.

| Arm | Trials rejected by normal floor | Minimum ratio across trials | Maximum ratio across trials | Accepted updates |
|---|---:|---:|---:|---:|
| ManyMesh | 20/20 | -27.3506 | -0.3456 | 0/4 |
| meshoptimizer LockBorder | 20/20 | -81.3238 | -0.2604 | 0/4 |

This directly confirms the cause that the original report could only infer
from renderer counts. It explains why the implementation never reached its
training-loss line search; it does not establish whether a feasible direction
would improve image quality.

## Exact replay check

The diagnostic used the same Thingi10K 84736 train asset, original source,
5,290-face ManyMesh and meshoptimizer inputs, 16 training camera matrices,
random seeds, D3D12 4x-MSAA operator, eight perturbations per update, four Adam
updates, epsilon, boundary locks, displacement limit, and normal threshold as
the frozen fit. No previously scored validation view was loaded. On all four
updates in both arms, the replay exactly matched the original raw trace's
training MSE, gradient norm, and maximum vertex step. It recorded 16 source
reference renders and 2,304 fit renders in 32.29 seconds. The run produced no
quality score and is not a new candidate result.

The receipt is the [machine-readable diagnostic](deliot_fit_rejection_diagnostic_20261127.json);
the exact rerun settings and command are frozen in the
[diagnostic protocol](DELIOT_FIT_REJECTION_DIAGNOSTIC_PROTOCOL_20261127.md).
Input hashes were checked before rendering. The tracked receipt SHA-256 is
`ce7acd26d10e834f0845fb72c4fa9cfe2955789ff3e6a7fd7d9c2d6382632858`.

The Windows environment emitted an import-time compatibility warning because
NumPy 2.5.4 is outside SciPy 1.15.3's declared `<2.5.0` range. The diagnostic
does not use SciPy for its finite-difference or normal-constraint calculations,
and the replay exactly matched the existing trace, but the environment warning
is retained as a reproducibility limitation.

## Prior-art consequence

This failure points to a constrained search-direction problem, but that alone
is not new. Blauth and Leithaeuser project gradient directions onto active
mesh-quality constraints and modify line search to maintain feasibility,
including fixed-boundary treatment. Their paper targets PDE shape optimization
and triangle-angle/tetrahedral-mesh quality, not stochastic raster image loss
or authored cluster-DAG LODs. It is a direct numerical-method precedent and
should be treated as a baseline, not a novelty claim. See the
[paper](https://arxiv.org/abs/2412.00006) and the updated
[bounded prior-art screen](../../docs/manymesh/siggraph-prior-art-screen-20261123.md).

The next optimizer study must freeze a distinct, constraint-feasible update
rule and compare it against the unmodified Deliot-style update and deterministic
geometry controls. It must report accepted-step rate, all constraint
violations, image quality, and full optimization cost. A one-asset pass would
only justify fresh asset-held-out development; it would not establish a
SIGGRAPH contribution.
