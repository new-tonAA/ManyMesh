# CPU PyTorch3D silhouette placement screen

Completed 2026-11-27 on the local D-drive WSL2 environment. **The tested
configuration fails its development gate and is closed.** This was fixed-
topology CPU geometry optimization; it did not train a neural network and did
not use CUDA.

## Frozen comparison

The screen fit vertex positions of the meshoptimizer LockBorder cut on 32
frozen training cameras, then compared the fit with unchanged meshoptimizer,
border-preserving QEM, and ManyMesh cuts. Each target used the full source mesh
and full source face array. Both reused development assets retained exactly
half of their source faces, kept the candidate indices fixed, and passed the
boundary audit. The assets were not held out by asset or view-sphere region.

The optimizer used PyTorch3D's CPU rasterizer and soft coverage, rather than
the frozen nvdiffrast adapter. It generated 128 Adam updates per asset. Costs
below include source-target rasterization and optimization, but exclude Python
startup, OBJ parsing, and the later WGPU scoring pass.

| Asset | Source to candidate faces | Training coverage MSE change | CPU target plus fit | Peak RSS | Max displacement |
|---|---:|---:|---:|---:|---:|
| BarramundiFish | 3,864 to 1,932 | -0.193% | 260.77 s | 316.4 MiB | 0.001302 |
| Corset | 18,324 to 9,162 | -0.032% | 1,057.18 s | 321.3 MiB | 0.000187 |

Both fitted meshes stayed within the frozen 0.012 displacement bound and
passed the boundary audit. The small training-loss changes did not produce a
robust image-quality win.

## Reserved-view result

Each asset was scored once on 24 frozen view-distance pairs at 640 x 360,
against a full-source reference rendered at 2x resolution with 4x MSAA and a
linear box resolve. The WGPU backend was Vulkan llvmpipe, a CPU software
adapter. These are image-quality comparisons, not hardware timing. The table
reports fitted minus unchanged meshoptimizer LockBorder. Positive PSNR/SSIM
and negative FLIP/XOR deltas favor the fit.

| Asset | Sampling | Delta PSNR (dB) | Delta SSIM | Delta LDR-FLIP | Delta silhouette XOR |
|---|---|---:|---:|---:|---:|
| BarramundiFish | Native | +0.407525 | +0.00028570 | +0.00009308 | -0.00011104 |
| BarramundiFish | 4x MSAA | -0.167112 | -0.00004843 | +0.00021110 | -0.00008048 |
| Corset | Native | +0.053995 | +0.00006624 | +0.00000055 | -0.00001338 |
| Corset | 4x MSAA | +0.095813 | +0.00001463 | +0.00002680 | -0.00001465 |

The frozen gate requires mean FLIP improvement on both assets under the tested
sampling modes. FLIP worsened for BarramundiFish under native sampling and for
both assets with 4x MSAA. The gate therefore fails, despite improved silhouette
XOR in all four rows. **Do not advance this configuration to the reserved
30-model pool.** This closes the tested PyTorch3D soft-coverage fit; it does
not falsify all geometry optimization.

## Corrections and receipts

The first local attempt was invalid: it rasterized candidate face indices on
the source positions when constructing fit targets. Its fit and quality
outputs are excluded. The corrected fitter uses the full source face array;
the checked-in receipt contains only the corrected run. Raw receipts, fitted
meshes, and full traces remain under the ignored
`out/pytorch3d-cpu-silhouette-screen-corrected-20261127/` directory.

The [protocol](PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_PROTOCOL_20261127.md) records
the frozen settings and limitations. The [machine-readable receipt](PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_20261127.json)
contains the 48 per-view records, control metrics, input and script hashes,
and hashes of raw receipts.

The CPU environment used PyTorch `2.4.1+cpu`, PyTorch3D `0.7.8` at commit
`75ebeea0908c5527e7b1e305fbc7681382db47`, and no CUDA device. PyTorch3D's
release lists support for PyTorch through 2.4.1 and CPU implementations for a
subset of its operations. The local rasterization and vertex-gradient check
passed. See the [PyTorch3D installation guide](https://github.com/facebookresearch/pytorch3d/blob/main/INSTALL.md)
and [v0.7.8 release](https://github.com/facebookresearch/pytorch3d/releases/tag/V0.7.8).
