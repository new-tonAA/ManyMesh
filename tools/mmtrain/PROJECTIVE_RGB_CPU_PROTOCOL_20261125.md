# CPU projective RGB fitting protocol

Frozen before the RGB fitting run. This is a low-cost feasibility screen for a
CPU differentiable-rendering route. It is not an asset-held-out result, a CUDA
reproduction, a mobile measurement, or a novelty claim.

## Question and decision

Can fixed-topology vertex fitting against full neutral-material RGB images
improve over its exact meshoptimizer initialization at the same face count on
both reused development assets? The strongest comparator is the unchanged
meshoptimizer LockBorder mesh. The resource match is exact topology and face
count; fitting cost and peak CPU memory are measured separately.

Advance only if each asset has at least one accepted optimization step, passes
the topology and boundary checks, improves mean reserved-view LDR-FLIP, and
does not regress pooled PSNR by more than 0.10 dB or mean SSIM by more than
0.001. Otherwise close this CPU RGB configuration. Passing only authorizes a
separately frozen study; it does not establish generalization.

## Inputs and split

Use the same two CC0 Khronos development assets as the earlier CPU silhouette
fit, at the exact 50% meshoptimizer LockBorder face count:

| Asset | Source faces | Target faces | Source OBJ SHA-256 |
|---|---:|---:|---|
| GlassHurricaneCandleHolder | 4,126 | 2,062 | `e6f986bd960e31bbc7a0b1d957f0fdf1be25b22de547fd2a3761615d521eb041` |
| MaterialsVariantsShoe | 22,700 | 11,350 | `8bd3e8f5ae3dfffe0e7ccbc89f3941aa7c1122a7e8756ddac4c7293df7608c09` |

These assets and their reserved views have already been used in development;
they are not an untouched confirmation set. The original source mesh is the
image and surface reference. Meshoptimizer output is the initialization and
matched-face comparator.

## Frozen fit and evaluation

- Fit only vertex positions; keep triangle indices fixed and lock all open
  boundary vertices. Reject degenerate or nonmanifold topology, changed source
  boundary, face-count mismatch, normal reversal below the script's 0.20
  threshold, or displacement above 0.012 normalized units. The automated
  topology audit does not test geometric self-intersections.
- Use Mitsuba 3.9.0 `direct_projective` with Dr.Jit 1.4.0 `llvm_ad_rgb`, neutral
  diffuse reflectance, one directional light, and a constant background.
  Optimize unweighted full-frame linear-RGB MSE over 16 fixed training camera
  and scale pairs at 96 x 96 and 4 samples per pixel for continuous and primary
  visibility gradients. Use a fixed Laplacian preconditioner, maximum step
  0.002, and at most eight iterations. No material or light fitting.
- Score 24 distinct direction and scale pairs at 96 x 96 and 16 samples per
  pixel. Keep the same seed, camera, light, and transfer function for the
  source reference, meshoptimizer baseline, and fitted candidate. Convert
  linear radiance to sRGB and report per-view and pooled PSNR, SSIM, and
  LDR-FLIP. Report sampled symmetric surface distance, normal agreement,
  topology, boundary eligibility, fitting time, and process peak RSS.
- LPIPS, hardware MSAA, SMAA, upscaling, temporal quality, power, GPU time, and
  mobile behavior are not measured by this screen.

## Prior work and interpretation

Differentiable image-space mesh and shading optimization is established by
Hasselgren et al. (EGSR 2021), and Mitsuba's projective integrator explicitly
supports continuous and primary-visibility derivatives. This CPU run asks
whether the existing desktop has a feasible full-image optimization path; it
does not test a distinct algorithm or support a novelty claim. The frozen CUDA
placement control remains a separate protocol and is not replaced by this
renderer.

## Reproduction

The pinned Ubuntu workflow is
[`manymesh-projective-rgb-cpu.yml`](../../.github/workflows/manymesh-projective-rgb-cpu.yml).
It downloads the GLBs at Khronos revision
`e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea`, checks their recorded hashes,
extracts the original geometry, runs the fit, and uploads one raw JSON receipt
and one NPZ geometry archive per asset. The JSON stores the script/input/archive
hashes, exact camera bases, package versions, raw per-view scores, and fit
trace. Run the workflow manually or push a change to its path filters.

After downloading and extracting an artifact, independently verify its input
and geometry hashes, exact camera split, 24 raw view rows, recomputed PSNR/SSIM/
FLIP means, surface metrics, fixed topology, locked boundaries, displacement,
and normal constraints with:

```powershell
python tools/mmtrain/verify_projective_rgb_cpu.py $artifactDirectory
```

The verifier also checks that the recorded per-asset decision agrees with the
frozen thresholds below. It cannot test geometric self-intersections.

## Execution history

The first two workflow runs, `45636675594` and `45637927355`, failed before
rendering either asset. Asset download, hash validation, extraction, and package
installation all succeeded. `camera_sets()` imported `fit_visible_contours`,
whose transitive import chain referenced a missing `compact` symbol in
`preflight_appearance_meshes`; no Mitsuba render, optimization, or image score
was produced. The current source removes that dependency and generates the
frozen camera bases locally.

Corrected run [`45639236184`](https://github.com/new-tonAA/ManyMesh/actions/runs/45639236184)
completed the fit-and-score and artifact-upload steps for both assets. It
published `projective-rgb-cpu-GlassHurricaneCandleHolder` (2,786,338 bytes) and
`projective-rgb-cpu-MaterialsVariantsShoe` (8,356,930 bytes). Both artifact
directories passed `verify_projective_rgb_cpu.py`, which recomputed the held-out
image metrics and checked source/geometry hashes, view records, face counts,
fixed indices, locked boundaries, displacement, normals, and the frozen gate.
The per-asset decisions were both `advance to a separately frozen multi-asset
study`. The verifier does not test geometric self-intersections or rerender
the stored images independently.

### Local D-drive WSL2 rerun, 2026-11-26

The initial preflight failure was a proxy-routing problem, not a GitHub or PyPI
outage. Windows `curl` inherited `HTTPS_PROXY`/`ALL_PROXY` pointing at
`127.0.0.1:9`, while Git used its separate repository proxy at
`127.0.0.1:7890`. WSL had `autoProxy=false`, so its Linux processes needed the
current WSL host-gateway address on port 7890 explicitly. Using that proxy per
command reached PyPI and the official Node.js release endpoint; no system or
global proxy settings were changed.

The D-drive distro had Python 3.14 but the pinned scientific packages require
Python 3.12 wheels. A local `uv` installation provided CPython 3.12.3 and a
virtual environment with the workflow's exact versions: Mitsuba 3.9.0, Dr.Jit
1.4.0, NumPy 2.3.4, SciPy 1.15.3, scikit-image 0.25.2,
fast-simplification 0.2.0, flip-evaluator 1.7, Numba 0.62.1, trimesh 4.5.3,
and Pillow 12.1.1. The first fit invocation then exposed a separate missing
`node` runtime for the repository's meshoptimizer JS helper. Node.js 22.16.0
Linux x64 was downloaded into the D-drive build directory and verified against
the official `SHASUMS256.txt` entry (`f4cb75bb...9467e84e`). It was not
installed system-wide.

The rerun used source commit `1121a1f15b1893a0ffb674d04e1b5a0095035a25`,
matching fit-script SHA-256
`0cc8096e9e88360e916ec5e1b32da923fa23ac10dfdcc50bd5833987b84ba2ba`, and the
two source OBJ hashes frozen above. Runs were serial on WSL2 Ubuntu 26.04,
Linux kernel `6.18.58.1-microsoft-standard-WSL2`, Intel Core i7-13700H, using
Mitsuba's CPU `llvm_ad_rgb` variant. Local raw outputs remain under
`/root/ManyMesh-build/projective-rgb-local-20261126/`; the dated report records
their SHA-256 hashes and per-asset summary measurements:
[`PROJECTIVE_RGB_CPU_LOCAL_RERUN_20261126.md`](PROJECTIVE_RGB_CPU_LOCAL_RERUN_20261126.md)
and its [machine-readable receipt](PROJECTIVE_RGB_CPU_LOCAL_RERUN_20261126.json).

Both local assets passed the frozen criteria: accepted optimization steps,
strict topology and source-boundary checks, improved held-out mean LDR-FLIP,
and PSNR/SSIM within the specified limits. The local and CI metrics are not
identical (Glass accepted 8 local steps versus 6 in CI), so their values are
reported separately, not averaged. Both runs authorize only a separately
frozen multi-asset study. The screen still uses two reused development models,
has no asset-held-out evidence, and does not test MSAA, SMAA, upscaling, temporal
quality, GPU performance, mobile behavior, user preference, or
self-intersections. Some sampled surface-distance measures worsened after
fitting; this is an image/geometry tradeoff, not a general geometric win.

### Exact-face QEM development control, 2026-11-26

The original two-asset advancement rule compared the RGB fit with its
meshoptimizer initializer only. Before scoring any confirmation asset, a
follow-up added border-preserving QEM at the same target face count on these
same reused development models. The QEM outputs passed their face-count and
source-boundary checks, but results were mixed: QEM was better than the fit on
GlassHurricaneCandleHolder, and the fit was better on MaterialsVariantsShoe.
The fitted mesh therefore does not show a stable advantage over this stronger
baseline, and this configuration is **not advanced to the reserved 30-model
pool**. The original meshoptimizer-only gate remains a historical feasibility
result; it is not a contribution result. See the [QEM development report](PROJECTIVE_RGB_CPU_QEM_CONTROL_DEV_20261126.md)
and [machine-readable receipt](PROJECTIVE_RGB_CPU_QEM_CONTROL_DEV_20261126.json).

The QEM workflow run completed on the hosted Ubuntu runner. The local Windows
attempt initially stopped with `ArrayMemoryError`, and that WSL invocation
returned `COMMITMENT_LIMIT`; neither was a quality result. On 2026-11-27 the
existing D-drive WSL virtual environment successfully ran the full independent
fit-artifact verifier for both assets. The QEM per-view image means were also
independently re-aggregated from the downloaded receipts. A verifier step has
been added to the workflow but has not yet run in hosted CI. Raw artifacts and
their hashes are listed in the [dated report](PROJECTIVE_RGB_CPU_QEM_CONTROL_DEV_20261126.md).


### QEM-initialized fit development follow-up, 2026-11-27

The same RGB optimizer was initialized from the saved border-preserving QEM
mesh. Its narrow QEM-only thresholds passed on both reused assets. Before
advancing, a same-host pass also scored raw QEM, QEM fit, raw meshoptimizer, and
meshoptimizer fit together at the exact same face count and on the same views.
The QEM fit beat the meshoptimizer fit on the candle holder, but lost on the
shoe by 5.421 dB PSNR, 0.001038 SSIM, and 0.001950 mean LDR-FLIP. Therefore the
full stronger-baseline gate fails; close this configuration and do not score
the reserved 30-model pool with it. The two initializers cannot be selected per
asset after looking at the held-out views. See the [frozen development
protocol](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_PROTOCOL_20261127.md),
[result report](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.md), and
[raw receipt](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.json).
