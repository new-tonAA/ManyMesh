# Shared-position multi-cut fit: final MSAA recheck

Status: frozen post-hoc renderer-sensitivity check. The joint three-cut fit
already failed its CPU projective-renderer gate. This recheck asks whether the
candidate/control ordering changes under this machine's real D3D12 4x MSAA
resolve. It cannot reopen the method, establish generalization, or qualify a
mobile result.

## Question and decision rule

Does the joint ManyMesh fit beat its predeclared fitted exact-face control
after rasterization and 4x MSAA resolve, against the original source mesh?

Compare the joint fit with the fitted control at the same 2,286, 5,290 and
7,934 face budgets. The fitted control remains the strongest eligible baseline
selected before image scoring: meshoptimizer LockBorder at 2,286 and 5,290;
boundary-preserving exact-face QEM at 7,934 because the meshoptimizer output
failed topology eligibility. A reversal is recorded only if the joint fit has
both lower mean LDR-FLIP and higher pooled PSNR at at least two of the three
budgets. Otherwise the prior negative ranking is not reversed. This rule is a
descriptive one-asset screen; the 24 views are correlated and are not
independent samples. SSIM and silhouette XOR are secondary diagnostics.

## Frozen inputs and rendering

- Asset: Thingi10K file 84736 / Thingiverse item 28675, train asset, CC BY.
- Original source OBJ SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Reuse the already scored candidate and control coordinates from
  `out/cluster-dag-multicut-fit-20261127/result.geometry.npz`; verify its hash
  against the preceding experiment receipt before rendering. Do not refit,
  change geometry, or tune any setting after viewing results.
- Reuse the exact 24 reserved direction/scale pairs stored in the previous
  experiment receipt. They remain post-hoc reused views for this sensitivity
  check, not a new holdout.
- Device: Intel Iris Xe integrated GPU, WebGPU 0.33.0, D3D12 backend. A CPU
  adapter or software fallback is ineligible; abort if the selected adapter is
  not the named hardware device.
- Candidate captures: 640x640 at native sampling and 4x MSAA.
- Reference: original 10,580-face OBJ at 1280x1280 with 4x MSAA, resolved in
  linear light and box-averaged 2x2 to 640x640.
- Use the pinned `bench_component_gpu.py` flat-face grayscale shader for every
  arm: per-face normals, light vector `(0.36, 0.80, 0.48)`, intensity
  `0.20 + 0.75 * max(dot(n, light), 0)`, and black clear. Use the same camera
  transform, clipping range, and transfer function for every arm. Match the
  previous CPU camera basis and screen scale; use the corresponding square
  sensor field of view (`focal = 2.88`). Convert resolved linear grayscale to
  sRGB before PSNR, SSIM, and FLIP. FLIP uses the repository's pinned evaluator
  at 67 pixels per degree. Silhouette XOR compares nonzero linear coverage
  masks.
- The Windows capture process writes sRGB images and image hashes only. Compute
  PSNR, SSIM, and FLIP in the existing WSL CPU verification environment,
  because Windows application control blocks the unsigned native FLIP DLL in
  the isolated Python environment. Do not change application-control policy.
- Record each view's metrics and image hashes. Aggregate PSNR by pooled MSE;
  report mean and worst-view FLIP, SSIM, and silhouette XOR. Do not derive
  confidence intervals from views.

## Eligibility and limits

The prior topology and boundary audits are prerequisites; the script must
reconfirm exact face counts for every arm before uploading. This screen changes
only the rasterizer and final resolve. It does not measure frame-time or claim
an equal-time advantage, and it does not compare MSAA against SMAA or an
upscaler. It is one reused train asset and uses flat shading rather than the
full production Filament material path. Any result is a desktop Iris Xe
hardware result for this exact shader and camera set.

## Reproduction

Use the ignored local `out/msaa-quality-venv` containing `wgpu` 0.33.0 to run
`bench_cluster_dag_multicut_final_msaa.py` with the pinned NPZ, prior JSON
receipt, source OBJ, and raw output JSON paths recorded in the result. Then
use the existing WSL `projective-rgb-venv` to run
`score_cluster_dag_multicut_final_msaa.py` against the capture archive and raw
receipt. The metric result records the image, archive, prior receipt, and
metric-script hashes. Do not install into or alter the system Python
environment.
