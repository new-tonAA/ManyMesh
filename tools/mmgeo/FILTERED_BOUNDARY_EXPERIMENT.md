# Filtered boundary simplification experiments

Date: 2026-11-14. Branch: `research/filter-aware-simplification`.
Status: controlled synthetic experiment, NOT a validated general mesh simplifier or SIGGRAPH result.

## What was implemented

- Private `libs/manymesh/src/FilteredBoundaryError.{h,cpp}`: Gaussian-filtered step displacement loss, derivatives and signed pair interaction. Small motions use Gaussian autocorrelation quadrature to avoid cancellation. Four-point quadrature is approximate; general large-coordinate cancellation remains a limitation.
- `tests/test_filtered_boundary.cpp`: seven tests against independent numerical image integration, derivatives, tiny motions, thin structures, Gram checks and invalid input.
- Explicit, non-default CMake target `mm_boundary_bench`: orthographic strip meshes, 41 cross-sections / 80 triangles. Removing an internal cross-section produces a 78-triangle mesh. This paired boundary deletion is NOT the general Corner edge-collapse operator.
- Controlled renderer: continuous Gaussian filtering horizontally, sampled rows with normalized discrete Gaussian convolution vertically. This is not Filament, PBR, hardware rasterization, visibility-event handling or a production antialiasing pipeline.
- Predictors: squared boundary displacement, independent boundary loss, within-row coupled loss, cross-row coupled loss and Fourier quadrature (4/8/16/32 frequencies).
- Latest source adds `--dynamic`: successive section removal/insertion at 60/40/24/40/60/24 triangles, moving procedural geometry, cumulative residual vector vs local-only residual ablation. Residual rebuild and undo checks are included. **This dynamic version has compiled but has NOT executed successfully.**

The runtime selector and simplification scoring are unchanged. A later follow-up adds `CornerCandidateCapture` to the production Corner entry point, null by default: it observes only initial-state candidates and does not intentionally alter selection. It captures the existing best placement per directed edge, so it is not an exhaustive placement oracle. Two tests verify output isolation, candidate applicability, caps and reset, but these tests have only passed syntax checking, NOT execution. Earlier full-suite results do not cover this interface change. The frontier-lock audit remains pending; the isolated strip experiment does not use DAG locks and cannot establish their correctness.

## Measurements already obtained

All 24 cases are development data: six procedural strips, four phase/filter configurations, 39 candidate deletions per case (936 candidates). No independent unseen mesh test exists yet.

### WSL Clang Release: within-row proxy versus local patch rendering

Artifacts: `out/filter-boundary-patch/summary.json`.

- Median proxy time for all 39 candidates: 58.69 microseconds.
- Median local-patch reference time: 466.73 microseconds.
- Median per-case patch/proxy ratio: 7.66x.
- Patch reference matches full-image reference to max absolute SSE difference 2.78e-16.
- Coupled predictor chooses the full-image optimum in 22/24 cases.
- Versus displacement-squared and independent-boundary predictors: 5 improved cases, 0 worse, 19 unchanged.
- Summed selected SSE: displacement 0.0305601, coupled 0.0287081, oracle 0.0285311.
- Median aggregate relative L1 prediction error approximately 22.8%. The proxy omits vertical filter coupling, so it is NOT an accurate absolute image-error estimator.
- Full-frame CPU rendering was much slower, but it is not the meaningful strong baseline; local patch rendering is.

### WSL Clang Release: including cross-row coupling

Artifacts: `out/filter-boundary-rows/summary.json`.

- Median proxy 463.16 microseconds, patch 463.67 microseconds.
- Median per-case patch/proxy ratio 0.989x: no useful speed advantage.
- Median relative L1 about 1.00%; optimum selected in 24/24 cases.
- At sigma 0.5, median relative L1 3.28%; at sigma 0.9, 0.0164%. Continuous horizontal integration still differs from sampled pixel evaluation.

**Negative result:** explicitly enumerating all needed row/boundary interactions largely removes the initial speed advantage.

### Native GCC 9.2 -O3: Fourier residual vector

Artifacts: `out/filter-boundary-native/summary.json`. Native and WSL absolute timings must not be compared as one experiment.

| Frequencies | Median patch / predictor ratio | Median relative L1 | Optimum choices / 24 | Worse than displacement baseline |
|---:|---:|---:|---:|---:|
| 4 | 4.15x | 43.5% | 22 | 2 |
| 8 | 2.55x | 1.59% | 23 | 1 |
| 16 | 1.35x | 1.00% | 24 | 0 |
| 32 | 0.69x | 1.00% | 24 | 0 |

These are one process's repeated timing blocks, not randomized multi-run confidence intervals. All predictors use known analytic strip boundaries, so extraction costs from an arbitrary mesh are absent. No GPU acceleration claim follows.

The representation is a signed complex residual vector. Parseval converts boundary/row interactions to a norm. For current cumulative residual r and operation delta, the error change is `2 Re<r, delta> + ||delta||²`. This is standard mathematics, not a novelty claim. Inverse deltas only remain valid under unchanged projection/filter state; camera changes require rebuilding or a separately validated transport rule.

## Visual check

Read the 4x nearest-neighbor enlarged reference/displacement/coupled images for strip-0-1. The thin strip remains connected, but is dark and the images cannot be reliably distinguished at that exposure/scale. No convincing visual improvement is claimed. Real assets, consistent higher-resolution crops, amplified error images, multiple lights and continuous motion remain required.

## Validation and blockers

- Includes formatted using repository tool.
- Header standalone C++17 syntax check passed with GCC.
- New kernel tests: 7 passed.
- Full ManyMesh suite before the dynamic tool extension: 89 passed, 1 HTTP environment-dependent skip.
- Required desktop Debug command attempted: `CC=clang-18 CXX=clang++-18 ./build.sh -ip desktop debug`; failed in split host-tools configuration because existing cache selected unsupported GNU. No build cache was deleted or modified to conceal this.
- Release utils suite: 333 passed, 1 failed: `JobSystem.JobPoolExhaustionNullJobRun`, expected 16384 held jobs, observed 16383. Not investigated or fixed by this experiment.
- WSL later stopped and repeated startup failed with `HCS_E_CONNECTION_TIMEOUT`.
- Native standalone experiment compiled and ran for the spectral measurements above. After adding the dynamic experiment, native compilation succeeded but execution returned `Permission denied` (exit 126). Do not bypass this restriction by renaming/copying binaries or changing security policy. The exact cause is not established.
- Latest source including output-file validation passed GCC C++17 `-Wall -Wextra -pedantic -fsyntax-only`; runtime remains unverified. The dynamic output JSON created by redirection is empty, not a result.

## Reproduction once execution is available

From a functioning, authorized Linux/WSL environment:

```sh
cmake --build out/regroup-linux-clang --target test_manymesh mm_boundary_bench -j 4
out/regroup-linux-clang/libs/manymesh/test_manymesh
mkdir -p out/filter-boundary-reproduction
out/regroup-linux-clang/tools/mmgeo/mm_boundary_bench > out/filter-boundary-reproduction/static.json
out/regroup-linux-clang/tools/mmgeo/mm_boundary_bench --dynamic out/filter-boundary-reproduction > out/filter-boundary-reproduction/dynamic.json
```

Existing executables and data may be from earlier source versions. Final experiments must archive binary/input/source hashes, compiler, flags and timing methodology; current pilot is exploratory and lacks a complete reproducibility manifest.

## Novelty gate

Lindstrom–Turk 2000 already used image-error edge-collapse ranking, local redraw, dirty marking and lazy updates. DiffVG discusses prefiltering and conflation of nearby boundaries. Gaussian filtering and the Gram expansion are not inventions here. No evidence currently establishes novelty or a publishable advantage.

Required next evidence: regenerated legal candidate sequences at a meaningful reduction, compared against a fair local-render baseline, with visible quality and bounded total update cost on general meshes. The 2026-11-16 frozen-pool follow-up exhaustively compared independent versus pairwise-interaction selection at 2/4 collapses and extended both to greedy 8/12-collapse schedules across six Torus views. All selectors chose identical sets, with 0% actual SSE change; 12 collapses removed only 2.08% of faces. The result closes interaction-aware ranking for this initial candidate pool, not regenerated sequences or other assets. Dynamic execution, real-mesh production validation and prior-art full-text comparison remain open. Do not enable the method by default or claim SIGGRAPH readiness. Details: [multi-collapse interaction audit](MULTI_COLLAPSE_INTERACTION_AUDIT_20261116.md) and [machine records](../../out/multi-collapse-interactions-20261116/torus.json).
