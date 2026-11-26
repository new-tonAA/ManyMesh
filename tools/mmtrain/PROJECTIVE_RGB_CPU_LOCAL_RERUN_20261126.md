# CPU projective RGB fitting: local rerun

Run date: 2026-11-26. This records the local reproduction of the frozen
[CPU projective RGB protocol](PROJECTIVE_RGB_CPU_PROTOCOL_20261125.md). The
result passed that protocol's **two-asset feasibility gate**. It is not an
asset-generalization result, a mobile measurement, or evidence that a SIGGRAPH
contribution is established.

## Results

The reference is each original source mesh. The baseline and fitted candidate
have the same exact face count and triangle indices. Each asset used 16 fixed
training view/scale pairs and 24 reserved view/scale pairs, rendered at 96 x 96
with 4 spp for fitting and 16 spp for scoring. Image metrics compare the
meshoptimizer initialization and fitted mesh against the source render.

| Asset (source -> target faces) | Accepted steps | Fit time | Python peak RSS | PSNR meshopt -> fit (delta) | SSIM meshopt -> fit (delta) | LDR-FLIP meshopt -> fit (delta) |
|---|---:|---:|---:|---:|---:|---:|
| GlassHurricaneCandleHolder (4,126 -> 2,062) | 8 | 8.393 s | 318,459,904 B | 40.0205 -> 41.1179 dB (+1.0974) | 0.996211 -> 0.996818 (+0.000606) | 0.009973 -> 0.008828 (-0.001144) |
| MaterialsVariantsShoe (22,700 -> 11,350) | 4 | 8.238 s | 343,072,768 B | 50.6251 -> 51.0225 dB (+0.3974) | 0.999384 -> 0.999466 (+0.000081) | 0.002125 -> 0.001936 (-0.000190) |

Both assets met the pre-set per-asset rule: at least one accepted step,
preserved topology and boundary, lower reserved-view mean LDR-FLIP, and no more
than 0.10 dB PSNR or 0.001 SSIM regression. The independent verifier passed
both assets and recomputed the image metrics from the 24 per-view records.
The frozen decision is **advance to a separately frozen multi-asset study**.

| Asset | Boundary edges | Max displacement | Surface Chamfer L1, meshopt -> fit | Normal agreement, meshopt -> fit |
|---|---:|---:|---:|---:|
| GlassHurricaneCandleHolder | 4, preserved | 0.012000 (limit 0.012) | 0.011485 -> 0.011534 | 0.987303 -> 0.987331 |
| MaterialsVariantsShoe | 1,156, preserved | 0.002282 | 0.008424 -> 0.008453 | 0.959120 -> 0.958760 |

The image improvement therefore comes with a small sampled surface-distance
regression on both assets by mean Chamfer L1. Glass's sampled distance p95,
maximum, and normal agreement improve slightly; Shoe's p95 and normal
agreement worsen. Report this as a tradeoff. Fit time is the optimizer's
training wall time, not end-to-end script time. Peak RSS is measured for the
Python process and excludes the short-lived Node.js helper process. The audit
does not test geometric self-intersections.

## Environment and provenance

- Source worktree: commit `1121a1f15b1893a0ffb674d04e1b5a0095035a25`.
- Fit script SHA-256: `0cc8096e9e88360e916ec5e1b32da923fa23ac10dfdcc50bd5833987b84ba2ba`.
- Verifier SHA-256: `89fab5f195aef4ebfaa50ece7dbf9b6a585b22881406d902f2019d8fef42237d`.
- Machine: Intel Core i7-13700H; D-drive WSL2 Ubuntu 26.04; Linux kernel
  `6.18.58.1-microsoft-standard-WSL2`; CPython 3.12.3; Mitsuba 3.9.0,
  Dr.Jit 1.4.0, NumPy 2.3.4, SciPy 1.15.3, scikit-image 0.25.2,
  flip-evaluator 1.7. The fit used the CPU `llvm_ad_rgb` variant.
- Meshoptimizer's JS helper used Node.js 22.16.0 Linux x64. Its release archive
  matched the official SHA-256 `f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e`.
- Inputs: Glass OBJ SHA-256
  `e6f986bd960e31bbc7a0b1d957f0fdf1be25b22de547fd2a3761615d521eb041`; Shoe
  OBJ SHA-256
  `8bd3e8f5ae3dfffe0e7ccbc89f3941aa7c1122a7e8756ddac4c7293df7608c09`.
- Local output directory:
  `/root/ManyMesh-build/projective-rgb-local-20261126/`. The result JSON and
  geometry archive SHA-256 values are recorded in the
  [machine-readable receipt](PROJECTIVE_RGB_CPU_LOCAL_RERUN_20261126.json).
- The hosted counterpart is workflow run
  [45639236184](https://github.com/new-tonAA/ManyMesh/actions/runs/45639236184).
  Its artifacts independently passed the same verifier. The local and hosted
  fit results differ slightly (Glass accepted 8 local steps and 6 in CI); keep
  the run-specific results separate rather than averaging them.

The pinned environment was created inside the D-drive distro with:

```sh
MANYMESH_PROXY_HOST="$(ip route show default | awk '{print $3; exit}')"
export HTTP_PROXY="http://${MANYMESH_PROXY_HOST}:7890"
export HTTPS_PROXY="http://${MANYMESH_PROXY_HOST}:7890"
export ALL_PROXY="http://${MANYMESH_PROXY_HOST}:7890"
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" all_proxy="$ALL_PROXY"
/root/.local/bin/uv python install 3.12.3
/root/.local/bin/uv venv --python 3.12.3 /root/ManyMesh-build/projective-rgb-venv
/root/.local/bin/uv pip install --python /root/ManyMesh-build/projective-rgb-venv/bin/python --only-binary :all: mitsuba==3.9.0 drjit==1.4.0 numpy==2.3.4 scipy==1.15.3 scikit-image==0.25.2 fast-simplification==0.2.0 flip-evaluator==1.7 numba==0.62.1 trimesh==4.5.3 pillow==12.1.1
```

The Node archive was fetched and checked before extraction:

```sh
curl -fL https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-x64.tar.xz -o /root/ManyMesh-build/node-v22.16.0-linux-x64.tar.xz
echo 'f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e  /root/ManyMesh-build/node-v22.16.0-linux-x64.tar.xz' | sha256sum -c -
tar -xJf /root/ManyMesh-build/node-v22.16.0-linux-x64.tar.xz -C /root/ManyMesh-build
```

The two local invocations used the pinned source and OBJ hashes above; only the
asset path, hash, and output directory differ:

```sh
export PATH="/root/ManyMesh-build/node-v22.16.0-linux-x64/bin:$PATH"
/root/ManyMesh-build/projective-rgb-venv/bin/python /root/ManyMesh-build/projective-rgb-source-1121/tools/mmtrain/fit_projective_rgb_cpu.py --source /mnt/e/ManyMesh/out/khronos-curated-screen-20261123/GlassHurricaneCandleHolder/geometry.obj --sha256 e6f986bd960e31bbc7a0b1d957f0fdf1be25b22de547fd2a3761615d521eb041 --out /root/ManyMesh-build/projective-rgb-local-20261126/GlassHurricaneCandleHolder/result.json
```

For `MaterialsVariantsShoe`, substitute its `geometry.obj`, source hash
`8bd3e8f5ae3dfffe0e7ccbc89f3941aa7c1122a7e8756ddac4c7293df7608c09`, and
output directory `MaterialsVariantsShoe`.

The earlier local preflight's proxy failure had two causes: Windows `curl`
inherited `HTTPS_PROXY`/`ALL_PROXY=http://127.0.0.1:9`, while Git used its
separate repository proxy at `127.0.0.1:7890`; WSL had `autoProxy=false` and
needed its current host-gateway address and port 7890 passed to the Linux
command. The setup above discovers the current WSL gateway from the default
route; check it again if reproducing later. After correcting that per-command
route, dependencies and the official Node archive downloaded. No global proxy,
Defender, or Smart App Control setting changed.

## Scope and next decision

These are two previously used development assets. Their 24 score views were
reserved from fitting, but the models themselves were not held out. The gate
only establishes that this CPU implementation is executable and clears its
pre-registered feasibility rule on these two examples. It does not clear the
separate frozen CUDA/nvdiffmodeling placement control or justify a custom DAG
optimizer.

The next useful step is to freeze an independently licensed, class-balanced
multi-asset cohort and region-blocked view split, then compare against the same
meshoptimizer initialization under the existing PSNR/SSIM/LDR-FLIP and
surface-distance criteria. Do not claim a general method result unless the
held-out assets support the gain with paired uncertainty. MSAA, SMAA, temporal
reconstruction, upscaling, user preference, complete frame time, and physical
mobile hardware remain unmeasured.
