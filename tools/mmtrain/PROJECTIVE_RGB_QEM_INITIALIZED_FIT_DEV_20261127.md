# QEM-initialized projective RGB fit: development result

Completed 2026-11-27 in the existing D-drive WSL2 environment. This is a
two-asset development screen, not an asset-generalization result or novelty claim.
The initial QEM-only screen passed on both assets. Before deciding to advance,
the frozen amendment added the already available meshoptimizer-initialized fit
as a stronger equal-face, equal-view, equal-render-cost comparator.
See the [protocol](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_PROTOCOL_20261127.md).

## Results

| Asset | Faces | Fit steps | Fit time | Delta vs QEM: PSNR / SSIM / FLIP | Delta vs meshoptimizer fit: PSNR / SSIM / FLIP | Full gate |
|---|---:|---:|---:|---|---|---|
| GlassHurricaneCandleHolder | 2,062 | 8 | 6.43 s | +1.0885 / +0.0002373 / -0.0016650 | +2.3388 / +0.0004714 / -0.0021236 | pass |
| MaterialsVariantsShoe | 11,350 | 3 | 5.29 s | +0.1656 / +0.0000802 / -0.0001342 | -5.4214 / -0.0010378 / +0.0019499 | fail |

Positive PSNR/SSIM and negative LDR-FLIP deltas favor the QEM-initialized fit.
It beat raw QEM on both assets. It also beat the meshoptimizer-initialized fit
on GlassHurricaneCandleHolder, but lost to it on MaterialsVariantsShoe by
5.4214 dB PSNR, 0.001038 SSIM, and 0.001950 mean LDR-FLIP. The full
strong-baseline gate therefore fails. Both fitted meshes retained exact face
counts, fixed QEM topology, and source boundaries; the optimizer accepted 8
steps for Glass and 3 for Shoe.

The 5.12 to 6.43 s values are offline CPU optimization time, not runtime render
cost. This run rendered all four candidate meshes plus the source in one
local pass on the same 24 views. Raw per-view metrics, fit histories, input
and output hashes, and package versions are in the [machine-readable receipt](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.json).

## Decision and limits

**Close this QEM-initialized configuration under the tested procedure. Do
not score the reserved 30-model pool with it.** The QEM-only improvement is
real on these two reused models, but it does not consistently beat the
existing meshoptimizer-initialized fit. Selecting different initializers
per asset would be an untested selection method and cannot rescue this result.

The original two assets were used during development, and the held-out view
split is not region-blocked. No cross-asset or perceptual-preference claim is
supported. No GPU/mobile, MSAA/SMAA/upscaler, temporal, or user study result
was measured. No production API or `.mmb` change follows.

The run used Mitsuba 3.9.0, Dr.Jit 1.4.0, NumPy 2.3.4, SciPy 1.15.3,
scikit-image 0.25.2, flip-evaluator 1.7, and trimesh 4.5.3 under WSL2.
The two-asset process peaked at 336,992 KiB RSS.
The tracked runner hash and full software versions are in the receipt.
Inputs came from [workflow run 45852622096](https://github.com/new-tonAA/ManyMesh/actions/runs/45852622096).

Reproduce with:

```sh
source /root/ManyMesh-build/projective-rgb-venv/bin/activate
python tools/mmtrain/fit_projective_rgb_qem_init_dev.py \
  --artifact-root out/projective-rgb-qem-control-dev-45852622096 \
  --output-dir out/projective-rgb-qem-initialized-fit-dev-20261127
```
