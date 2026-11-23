# Contour selector budget feasibility screen

Run on 2026-11-23. **Result: across all 12 development assets and three requested face ratios, the selector produced zero equal-face, geometry-distinct candidates. No image-quality comparison was possible.** This is a diagnostic screen, not held-out evidence or a SIGGRAPH result.

## Protocol

- Built the current `tools/mmgeo/src/main.cpp` into `out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe` with the Visual Studio 2022 Release configuration. The build completed with 11 existing MSVC flag warnings and zero errors. The older Ninja build tree remained unusable; the executable used here was built by the Visual Studio generator.
- Ran [`bench_contour_budget.py`](bench_contour_budget.py) on all 12 OBJ fixtures in `assets/models/*/*.obj`. Each run built a fresh DAG, requested 0.3, 0.5, and 0.7 uniform-ratio cuts, and exported cone-risk cuts at interior multipliers `k={3,4,5}` with a 5-degree margin. The script reads all 108 binary PLY headers and fails if a file is missing or its face count differs from the CLI report.
- Recorded source-mesh hashes, executable and script hashes, source revision, actual selected triangle counts, candidate and uniform-output hashes, exit status, and end-to-end wall time in [`contour_budget_screen_20261123.json`](contour_budget_screen_20261123.json). The rerun recorded 108 candidate PLYs and zero header mismatches.
- Source revision: `2d417cacdeb545a13e6bfb7192310191e60670d6`; modified `main.cpp` SHA-256: `c044d8d026b32ccb335e99a8c9b0ef4e2ffc766e51455647f29f75bdcf6edea4`; executable SHA-256: `8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e`; benchmark script SHA-256: `85e30abf4920374d8ff278244c2ecd1952eff99afbc993f9de42e4a77f83b89f`.

## Results

| Asset | Source faces | Uniform faces at requested R=0.3 / 0.5 / 0.7 | Face delta at R=0.3 (k=3/4/5) | Face delta at R=0.5 (k=3/4/5) | Face delta at R=0.7 (k=3/4/5) |
|---|---:|---:|---:|
| camera | 590 | 296 / 296 / 394 | +20/+20/+20 | +20/+20/+20 | -8/-8/-8 |
| cloth | 74,976 | 30,214 / 37,488 / 52,484 | 0/0/0 | -4/-4/-4 | +6/-18/-2 |
| cornell_box | 288 | 228 / 228 / 228 | 0/0/0 | 0/0/0 | 0/0/0 |
| cube | 48 | 36 / 36 / 36 | 0/0/0 | 0/0/0 | 0/0/0 |
| material_sphere | 9,428 | 3,972 / 4,714 / 6,600 | +208/+208/+208 | +78/+78/+78 | +20/+20/+20 |
| monkey | 15,744 | 4,724 / 7,870 / 11,020 | -352/-352/-352 | +88/+88/+88 | +50/+50/+50 |
| prism | 8 | 8 / 8 / 8 | 0/0/0 | 0/0/0 | 0/0/0 |
| rounded_cube | 1,200 | 280 / 576 / 840 | 0/0/0 | 0/0/0 | +4/+4/+4 |
| shapes | 73,728 | 22,119 / 36,864 / 51,610 | +98/+98/+98 | -372/-372/-372 | +16/-6/+10 |
| sphere | 8,064 | 1,978 / 4,032 / 5,644 | 0/0/0 | +34/+34/+34 | -2/-2/-2 |
| thinglass | 12 | 12 / 12 / 12 | 0/0/0 | 0/0/0 | 0/0/0 |
| torus | 1,152 | 366 / 562 / 804 | +36/+36/+36 | -58/-58/-58 | -4/-4/-4 |

The uniform column lists actual faces for requested ratios 0.3 / 0.5 / 0.7. Candidate columns list actual-minus-uniform face delta in `k=3/4/5` order at those same ratios. Across the 12 assets, exact face-count matches occurred on 7/12, 5/12, and 4/12 assets at the three respective requested ratios, but every exact match was byte-identical to the uniform geometry. There were zero equal-face, geometry-distinct candidate pairs. All three multipliers produced identical output geometry on 12/12 assets at ratios 0.3 and 0.5; at 0.7 they differed on two assets, but none yielded an exact-face alternative. At the 0.5 budget, only `rounded_cube` matched exactly among the eight assets whose uniform cut reached 25-52% face retention, and that output was identical to the uniform cut.

## Decision and limits

Close this cone-risk implementation as a contribution candidate. It generated no equal-face, geometry-distinct candidate across 12 fixtures and three requested budgets; therefore there was no candidate image-quality comparison to run. Do not infer that the approach improves FLIP, PSNR, SSIM, silhouette error, topology, or frame time; none of those candidate properties was evaluated here. The 29.22-second sum is end-to-end wall time for all 12 DAG builds/exports, not selector-only CPU cost.

These are repository development fixtures, not independent confirmation assets. No renderer, MSAA path, reference image, or visual metric participated in the screen. The root README's historical image results are unrelated to this run. A separate 13-asset silhouette-profile experiment and its negative results remain documented in [`DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md`](../mmtrain/DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md).

The proposed differentiable DAG direction remains untested and has high novelty risk. Its cheap nvdiffmodeling/Hasselgren placement baseline cannot run on this host: PyTorch is `2.7.1+cpu`, `torch.cuda.is_available()` is false, `nvidia-smi` is absent, and the repository scan found no Dragon asset. Do not start the custom optimizer or claim SIGGRAPH novelty until suitable CUDA compute and hash-pinned, redistribution-cleared assets are available.

The `test_manymesh` and `test_utils` Debug targets also compiled successfully in the Visual Studio tree, but Windows Application Control blocked launching both binaries. Runtime unit-test results are therefore unavailable; this does not affect the recorded PLY face-count and hash checks, but cone and library invariants remain unverified by those suites.
