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
`projective-rgb-cpu-MaterialsVariantsShoe` (8,356,930 bytes). The JSON metrics
and geometry archives have not yet been inspected; the per-asset pass/fail
criteria and algorithmic decision therefore remain **unverified**.

On 2026-11-26, a local rerun was preflighted in the D-drive WSL2 Ubuntu 26.04
distro before attempting the fit. The exact pinned OBJ files are already
present at `out/khronos-curated-screen-20261123/{GlassHurricaneCandleHolder,
MaterialsVariantsShoe}/geometry.obj`; their SHA-256 hashes match the frozen
protocol. However, this distro has Python 3.14 without `pip` and none of the
pinned renderer/metric packages. Both the WSL `curl` request and a Windows
read-only `curl -I` request to the pinned Khronos raw asset endpoint failed
with a connection reset, so the Linux dependencies cannot currently be
installed from the configured environment. The existing Windows CPython 3.12
Mitsuba package is not a safe fallback: the earlier backend preflight recorded
Windows Code Integrity blocking its unsigned Mitsuba extension (see
[`MITSUBA_CPU_BACKEND_PREFLIGHT_20261125.md`](MITSUBA_CPU_BACKEND_PREFLIGHT_20261125.md)).
No fitting, render, or score was run in this local attempt. This is an
environment/dependency blocker, not a method result; the CI artifacts remain
unreviewed.
