# CPU PyTorch3D silhouette placement screen

Status: amended after an implementation defect was found in the first local
run. The earlier run incorrectly rasterized the simplified face indices on
the source positions; its fit and quality results are invalid and excluded.
The corrected run uses the full source face array for its target. This remains
a local development screen on two reused assets, not a CUDA reproduction, an
asset-generalization test, or a contribution claim.

## Question and decision

Does a fixed-topology, silhouette-supervised vertex fit using PyTorch3D's CPU
mesh rasterizer show a stable development signal over the unchanged
meshoptimizer LockBorder initializer at identical topology and face count?
For this local development screen, require improvement in both mean
silhouette XOR and mean LDR-FLIP on both assets, no PSNR regression greater
than 0.05 dB, and a passing boundary/topology audit. The camera views had been
scored in the invalid first run; even a positive corrected result cannot pass
the held-out research gate.

## Frozen inputs and controls

- Assets: BarramundiFish and Corset from the existing Khronos CC0 intake.
- Reference: each asset's full-source `reference.obj`, never a hierarchy cut.
- Candidate initializer: `meshoptimizer_lock_border.obj`; topology and face
  count remain fixed. Compare with the unchanged meshoptimizer and QEM exports
  and ManyMesh export using the existing `bench_appearance_controls.py`
  scorer and manifest.
- Reuse the frozen 32 training eye positions in
  `appearance_cuda_protocol_20261124.json`. Render each target using
  `reference.obj` and its full source face array. Fit only interior
  initializer vertices; retain the boundary vertices and indices. Score the
  corrected run on the separate 24 view/scale pairs in the existing WGPU
  scorer. Those views are no longer an untouched held-out set.
- The source, initializer, other controls, cameras, and scorer are hash-pinned
  by `matched_appearance_inputs_20261124.json` and the scorer receipt.
- This host's reserved-view scorer must use `--adapter llvmpipe --backend
  Vulkan --allow-software`. Those images are software-rendered quality
  measurements only; they are not hardware timing, Iris Xe, or mobile results.

## CPU fit implementation

- Renderer: PyTorch3D `V0.7.8` release commit
  `75ebeea0908c5527e7b1e305fbc7681382db47`, built with CPU-only PyTorch
  `2.4.1+cpu`; no CUDA device is used.
- At each of the 32 training cameras, rasterize the full source at 256 x 256
  and use its binary coverage as the target. Rasterize the candidate with
  `blur_radius=(4/256)^2`; turn signed squared edge distances into soft
  coverage using `sigmoid(-signed_distance / (1/256))`. Average-pool each
  2 x 2 block to 128 x 128 and minimize mean squared coverage error.
- Optimize 128 deterministic Adam updates (16 epochs over eight fixed
  minibatches of four cameras), learning rate 0.001, plus a 0.1 mean-squared
  displacement penalty. Cap displacement at 0.012 normalized units and reject
  updates that violate the inherited 0.2 face-normal dot bound. Do not tune
  these settings from view scores.
- After fitting, recompute and record the mean coverage MSE for the unchanged
  initializer and fitted mesh across the same 32 training eyes. This is a
  same-split diagnostic; per-minibatch losses are not an aggregate comparison.
- This rasterizer and soft-coverage objective differ from the frozen NVIDIA
  nvdiffrast control and from final WGPU rasterization/MSAA. Record that
  surrogate gap; do not pool timings or call this an exact reproduction.

## Measurements and limits

Record input/script/dependency hashes, per-step training loss and gradient
checks, face count, boundary and topology results, maximum displacement, CPU
fit time, peak RSS, and every view's PSNR, SSIM, LDR-FLIP, and silhouette-XOR
result. The existing scorer supplies the common WGPU render path and
full-source reference. Report each asset separately. There are only two reused
assets and the evaluated views have previously been observed, so this run
cannot establish an independent confidence interval or generalization claim.
No phone, temporal reconstruction, preference study, or equal-frame-time
benefit is measured here.

## Reproduction

Run `fit_pytorch3d_cpu_silhouette.py` in the isolated D-drive WSL environment
with its `pytorch3d-cpu-venv`; run `bench_appearance_controls.py` on each
output against the frozen inputs. Keep generated meshes and raw JSON in
untracked `out/` folders.
