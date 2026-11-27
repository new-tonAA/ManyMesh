# Exact fraction-to-boundary Deliot feasibility screen

## Result

The frozen feasibility gate failed. The ManyMesh arm accepted 3/4 updates,
but exact-face meshoptimizer accepted only 2/4; the protocol required at least
3/4 in each arm. Do not score image-quality views or advance this fit route.
This closes the tested fraction-to-boundary control under the fixed stochastic
raster-gradient objective, not every possible geometry optimizer.

Both arms kept exactly 5,290 faces and 2,645 vertices, preserved locked
vertices, had no degenerate faces, remained under the 0.012 displacement cap,
and stayed above the 0.20 signed face-normal ratio floor. Every limiting
constraint was a face-normal constraint. The much smaller-than-allowed
displacements show the safe fraction was restrictive: the largest displacement
was 0.0001903 for ManyMesh and 0.00002960 for meshoptimizer.

| Arm | Accepted updates | Training MSE, before → after | Relative reduction | Minimum normal ratio | Max displacement |
|---|---:|---:|---:|---:|---:|
| ManyMesh | 3/4 | 9.76310e-5 → 9.47348e-5 | 2.97% | 0.207125 | 0.0001903 |
| meshoptimizer LockBorder | 2/4 | 1.27745e-5 → 1.27453e-5 | 0.228% | 0.883764 | 0.00002960 |

Training MSE is not an image-quality result. Even on those same training
views, the final ManyMesh MSE remained about 7.43 times the meshoptimizer
control's. No PSNR, SSIM, LDR-FLIP, silhouette, or held-out metric was scored
for this run. There is no quality win or loss claim from this feasibility
screen.

The exact quadratic bound removed the earlier immediate normal-floor
violations and enabled repeated feasible ManyMesh descent, but its final small
fractions did not let the stronger control pass the predeclared acceptance
gate. Further changes to the step limiter, optimizer, or thresholds would be a
new experiment and require a new frozen protocol; this tested configuration is
closed.

## Reproduction and provenance

Protocol: [frozen fraction-to-boundary screen](DELIOT_EXACT_FRACTION_TO_BOUNDARY_DEV_PROTOCOL_20261127.md).
Run the command in that protocol from the repository root. The raw receipt is
[`deliot_fraction_to_boundary_raw_20261127.json`](deliot_fraction_to_boundary_raw_20261127.json).

The run used the Thingi10K 84736 train asset, Iris Xe / D3D12, `wgpu==0.33.0`,
16 training views, 8 stochastic gradient estimates per update and 4 Adam
updates per arm. It rendered 16 high-resolution references and 2,768 low-
resolution candidate/gradient images in 43.72 seconds total; measured fitting
time was 19.22 seconds for ManyMesh and 17.17 seconds for meshoptimizer.
Verified input hashes are recorded in the raw receipt. This is one reused
training asset, does not measure frame time, does not test a phone, and does
not provide held-out evidence.
