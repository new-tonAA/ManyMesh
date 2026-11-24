# Poly Haven matched-face LPIPS supplement

Completed 2026-11-25. This post-hoc metric supplement reuses the
already-scored 21-model fixed-view cohort; it is descriptive, not
independent or confirmatory held-out evidence. Lower LPIPS is better.

The PSNR, SSIM, LDR-FLIP, and silhouette-XOR replay matched every
original per-view score within the frozen `1e-6` tolerance.

ManyMesh minus control is reported below. Negative values favor
ManyMesh on LPIPS; intervals bootstrap the 16 source-collection groups.

| Sampling | Control | Mean paired delta | 95% group-bootstrap CI | Groups won / 16 |
|---|---|---:|---:|---:|
| native | Border-preserving QEM | +0.00126752 | [+0.00075138, +0.00184701] | 1/16 |
| native | meshoptimizer LockBorder | +0.00204782 | [+0.00142827, +0.00278328] | 0/16 |
| msaa4 | Border-preserving QEM | +0.00172163 | [+0.00107273, +0.00243348] | 0/16 |
| msaa4 | meshoptimizer LockBorder | +0.00266908 | [+0.00195458, +0.00348164] | 0/16 |

## Limits

This reuses assets and fixed views already evaluated with other
metrics. LPIPS is not a user study and does not establish
perceptual preference. It cannot by itself reopen the tested
ManyMesh cut or advance the unrun CUDA placement control.

See the [frozen protocol](POLYHAVEN_LPIPS_SUPPLEMENT_20261125.md),
[machine-readable receipt](polyhaven_lpips_supplement_20261125.json),
and [original matched-face screen](POLYHAVEN_QUALITY_SCREEN_20261124.md).
