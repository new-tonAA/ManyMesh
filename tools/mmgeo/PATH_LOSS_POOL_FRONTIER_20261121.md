# Exact path-loss candidate-pool frontier (2026-11-21)

## Question

Can the continuous orthographic-pan loss scorer retain its image-quality gains with a smaller QEM shortlist, and can exact lower bounds reduce its CPU cost?

This is a screen of an existing Python prototype. It is not a novelty or SIGGRAPH-readiness claim.

## Frozen protocol

- Same collapse target within each asset: remove 20% of faces.
- Fit viewport 96x96, 2x sampling, continuous one-pixel box filter along a 1.5-pixel orthographic pan, three fixed fitting views.
- Held-out quality: six different azimuth/pan paths, 96x96, 3x sampling, four path samples; compare at equal final face count.
- Candidate pool is the number of lowest-QEM legal edges re-ranked at each edit. `pool=2` and `pool=3` are compared to the existing Pirate `pool=4` capture.
- Single-threaded BLAS; assets run serially. Peak working set was sampled from the Python process using psutil.

## Results

| Asset | Faces | Pool | Path CPU s | QEM CPU s | Candidate evaluations | Peak WS MiB | Coverage delta vs QEM | Depth delta vs QEM | Flat-normal delta vs QEM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pirate unit 5 | 3,032 to 2,426 | 4 | 19.719 | 1.219 | 1,187 | not captured | 0.00% | effectively 0.00% | +1.57% |
| Pirate unit 5 | 3,032 to 2,426 | 3 | 16.203 | 1.172 | 890 | 89.7 | 0.00% | effectively 0.00% | -1.48% |
| Pirate unit 5 | 3,032 to 2,426 | 2 | 15.344 | 1.188 | 599 | 90.1 | -5.26% | -5.41% | -2.28% |
| Rounded Cube | 1,200 to 960 | 2 | 4.188 | 0.469 | 227 | 64.1 | -23.53% | -27.11% | -6.38% |
| Torus | 1,152 to 922 | 2 | 22.234 | 0.453 | 226 | 133.8 | -9.65% | -18.60% | -3.81% |

Negative deltas mean lower error. At pool 2, all three assets improve the aggregate of all three reported metrics over QEM. The corresponding path-scoring cost is still about 8.9x QEM on Rounded Cube, 12.9x on Pirate, and 49.1x on Torus. Improvement is not uniform per held-out view: Pirate pool 2 wins depth on 2/6 and coverage on 1/6 views, despite better averages. These are three assets and one deterministic run per configuration, not a generalization result.

Reducing Pirate from pool 4 to pool 2 cuts candidate evaluations by 49.5% and path CPU by 22.2%; pool 2 also has lower aggregate error than both pool 3 and pool 4 on the frozen six-view report. This is a useful parameter interaction, not yet a new algorithm. It suggests that a wider low-QEM shortlist can inject edits that hurt path quality, while scoring more alternatives increases cost.

## Lower-bound and kernel screens

On Torus at pool 2, enabling per-pixel loss ordering, cached view bounds, and partial-patch retention selected the exact same 115 edges and placements as the unpruned run. The audit recomputed 12 pruned candidates and the largest per-view score difference was zero. However, the audited run took 24.16 CPU seconds; the unpruned run took 22.23 seconds. Without the audit recomputation, it took 23.36 seconds. The across-view bound pruned no candidates, and 12 pixel-level stops did not offset their bookkeeping cost. Do not keep this configuration as a performance claim.

A profile of a 4% Torus run attributed about 5.2 seconds of cumulative time to per-triangle `instantiate_path_lines`, 2.6 seconds to continuous box-loss integration, and 1.8 seconds to front-envelope construction. A NumPy vectorization trial produced exactly the same 23 edit choices and scores as the scalar version but was 8.2% slower. An optional Numba trial could not run because the installed Numba requires NumPy 2.3 or older while this environment has NumPy 2.5. The experimental code was removed; the production research scripts remain unchanged.

I compiled a standalone C++ path-line clipping kernel and first called it once per ray through `ctypes`. The 4% Torus path retained exact scores and choices, but took 17.28 CPU seconds versus 6.66 seconds for the scalar reference. At the full 20% Torus target, the C++-per-ray run retained all 115 edge/placement choices and every per-view score exactly, but took 66.69 CPU seconds versus 22.23 seconds for Python. Its peak working set was 133.9 MiB. This rejects the single-ray FFI integration; its repeated array handling and call overhead outweigh the compiled arithmetic.

A second native function that batches multiple ray queries compiled successfully. Windows Application Control blocked loading the generated DLL with WinError 4551, so the batch function received no runtime validation or performance result. I did not rename the binary or try another execution environment. The unverified native source and DLL were removed, leaving the Python reference unchanged. A batched kernel is still a possible route, but it needs an approved execution path before it can be evaluated.

Re-enabling `--reuse-face-records` on the full Torus pool-2 run preserved all 115 choices and scores but increased path CPU from 22.23 to 37.33 seconds; peak working set stayed about 134 MiB. This cache is not a useful speed setting for this configuration.

I also varied the order in which exact candidate scores are completed. Reversing the QEM shortlist on the 20% Pirate run preserved all 303 choices and per-view scores, but increased path CPU from 15.34 to 49.30 seconds. It pruned 26 more candidate completions (599 to 573), so pruning count alone does not predict runtime.

The `first-view` order pre-scores every candidate on the first camera path, then sorts by that exact contribution plus the remaining views' nonnegative outside-support losses. On a 4% Torus prefix, it preserved all 23 choices, placements, and per-view scores; the pruning audit passed, and path CPU fell from 19.23 to 7.91 seconds (peak working set about 100 MiB). On the full 20% Torus run, it again preserved all 115 choices, scores, and held-out results, and reduced later-view evaluations from 456 to 422 and completed candidates from 226 to 206. However, path CPU rose from 22.23 to 53.98 seconds (peak working set 134.3 MiB). The short-prefix speedup does not survive the full run; this ordering is rejected as a general acceleration. It demonstrates that exact admissible bounds can preserve the answer while a poorly amortized scoring schedule still makes the algorithm slower.

I screened a cheaper single-frame raster order on the same 1,152-face Torus. At pool 4 and a 4% target, exact evaluation of the full pool selected the same 23 edits and held-out scores as QEM ordering; CPU was 8.09 versus 18.88 seconds. That short-prefix timing did not generalize. At the full 20% target, raster ordering still selected the same exact pool-4 sequence and held-out scores, but CPU rose from 83.59 to 106.73 seconds; its one-frame proxy cost 12.95 seconds and it did not reduce exact view calls. The proxy's QEM-rank winner distribution was 1:7, 2:14, 3:17, 4:77, so it often promoted high-rank edges without helping exact pruning.

Restricting exact path scoring to the coarse raster's top K is a measurable speed/quality tradeoff, but it did not produce a better Torus frontier. Top-2 took 22.92 seconds versus 83.59 seconds for exact pool 4, at 133.3 MiB peak working set, but diverged from its sequence after 12 of 115 edits and raised held-out coverage, depth, and flat-normal error by 8.4%, 10.7%, and 8.6%. It was also slightly slower and worse on all three metrics than exact QEM pool 2 (22.23 seconds). Top-3 took 100.34 seconds at 134.8 MiB; versus pool 4 its coverage and flat-normal errors were 1.1% and 6.1% higher, while depth error was 4.1% lower. It is not a useful Pareto point on this mesh. Do not describe coarse-to-exact shortlisting as a quality/performance win from these results.

Finally, a 4% pool-4 Torus run with a 50,000-line per-view current-scene ray cache, using strip width 1 because the cache cannot be combined with strip width 4, preserved all 23 edits and reduced CPU from 28.97 to 24.59 seconds. The peak process working set changed from 98.0 to 99.2 MiB; cache peaks were 5,903–6,603 lines per view, with 327 hits and 9,251 misses. The faster matched strip-width-4 baseline took 18.88 seconds, so this cache configuration does not improve the best measured setup and is not retained as an acceleration claim.

I temporarily routed strip-anchor common-scene queries through the same ray cache and invalidated anchors touched by accepted edits. The 4% pool-4 audit preserved all choices and scores; the independent full-frame path rebuild differed by at most `2.24e-16` per pixel. Runtime rose from 18.88 to 26.23 CPU seconds at 107.8 MiB peak working set, with only 166 hits versus 3,593 misses. I removed this integration because it is slower and adds bookkeeping; the parser continues to reject this combination.

A second exact-kernel trial memoized the source-side piecewise-polynomial integral prefixes used by the continuous box filter, since those source fronts are unchanged across collapse candidates. On the 4% Torus/pool-4 audit, it retained the same 23 choices and per-view scores, and the final full-frame rebuild differed by at most `2.24e-16` per pixel. The scorer itself slowed from 16.96 to 19.66 CPU seconds (+15.9%), and peak working set rose from 104.4 to 119.9 MiB. Most source fronts were not reused enough to amortize the extra tables. I removed this optimization; the exact reference implementation remains unchanged.

I added `--fit-view-count` to measure a view-budget ablation. It selects one centered camera path, two opposite paths, or the existing three paths. On Torus, all runs used the same pool, face target, fitting resolution, and six held-out paths:

| Fitting paths | Path CPU s | Peak WS MiB | Coverage delta vs QEM | Depth delta vs QEM | Flat-normal delta vs QEM | Held-out wins (coverage/depth/normal) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 18.83 | 77.7 | -1.28% | -1.57% | +0.21% | 2/6, 2/6, 1/6 |
| 2 | 42.33 | 105.8 | -7.47% | -15.14% | -3.23% | 4/6, 4/6, 6/6 |
| 3 | 22.23 | 133.8 | -9.65% | -18.60% | -3.81% | 3/6, 5/6, 6/6 |

The one-view run was about 15% faster than the three-view run, but it gave up most of the quality gain and slightly worsened flat-normal error. Two paths were slower than three; they chose a different sequence with larger downstream supports. Therefore runtime is not monotonic in the number of fitted views, and no useful adaptive view-budget policy is established by this ablation.

A final exact update experiment used the incremental front-envelope repair helper for candidates whose old front winner is untouched. On the 4% Torus/pool-4 audit it retained all 23 edits and held-out results; independently rebuilding every final frame changed pixels by at most `2.2345e-16`, and candidate score differences were at most `6.66e-29`. It replaced 308 of 6,113 scene-line queries (about 5.0%), but scorer time rose from 16.96 to 19.51 CPU seconds (+15.0%); full run CPU rose from 18.88 to about 22.75 seconds. The local interval merge's bookkeeping outweighed those saved queries, so I removed it.


## Fitting-view traversal order screen

The three fitting cameras are symmetric in the objective, but the exact branch-and-bound scorer visits them in sequence. I swapped only the two secondary views, leaving the view set, candidate pool, objective, mesh, and all collapse placements unchanged. These paired full-run timings were collected in one session; absolute CPU times differ from the earlier capture table, so compare each pair internally. Peak working set was not sampled.

| Asset | Pool | Edits | Fixed order CPU s / completed candidate-view scores | Swapped secondary order CPU s / scores | Same edge and target sequence |
|---|---:|---:|---:|---:|---|
| Torus | 2 | 115 | 65.80 / 226 | 58.77 / 227 | yes |
| Pirate unit 5 | 4 | 303 | 51.11 / 1,187 | 49.30 / 844 | yes |

The swapped order reduced paired CPU time by 10.7% on Torus and 3.5% on Pirate; Pirate also avoided 343 completed candidate-view scores. Since the selected edge and target are identical at every step, the produced meshes are identical. This is a low-cost performance adjustment, not a new simplification objective or a novelty claim. It is still a one-run, two-asset result; broader mesh coverage and repeat timing are needed before calling the ordering generally faster. The capture outputs are `torus-96px-pool2-fixed-order-confirm.json`, `torus-96px-pool2-fixed-order-swapped.json`, `pirate-96px-pool4-fixed-order-confirm-u5.json`, and `pirate-96px-pool4-fixed-order-swapped-u5.json` under the ignored `out/pathloss-captures/` directory. Global QEM driver SHA-256: `5684439c6971b5605a3eee15ad80f1743e4dcf3c632cfef9528557041157ec45`.


## Bounded axis-scanline coefficient cache

For axis-aligned pan, each triangle's intersection interval on a fixed image row/column is independent of the moving pixel coordinate. I added an opt-in cache to `SceneIndex`: it lazily stores those exact affine intervals by fixed coordinate, then shifts only the interval endpoints and depth intercept for each query. Separate horizontal and vertical spatial bins avoid scanning unrelated faces. Working-scene rows are invalidated after each accepted collapse; immutable source rows remain cached. Each scene object is bounded to 20,000 line records and 512 row keys.

A 512-ray micro-screen over all four signed axes had zero face-set mismatches, with maximum line coefficient difference `3.42e-14`. A separate 512-ray test placed rays exactly through projected mesh vertices; ambiguous vertex/co-edge scanlines now fall back to the reference query and had zero face-set mismatches. After perturbing and replacing a triangle, cache invalidation also preserved zero mismatches. Full 4% simplification on Torus and Pirate unit 5 preserved every edge and target from the no-cache run; an independent final-view rebuild had maximum pixel differences of `1.15e-16` and `1.82e-17`, respectively.

| Asset | Pool | Edits | No-cache path CPU / scorer s | Cached path CPU / scorer s | Candidate-view evaluations | Peak process RSS with cache | Peak cached row lines per view (source/current) |
|---|---:|---:|---:|---:|---:|---:|---|
| Torus | 4 | 23 | 20.30 / 21.48 | 9.97 / 10.21 | unchanged: 92 / 89 / 88 | 99.3 MiB | 9,028/2,792; 9,028/4,681; 9,028/3,220 |
| Pirate unit 5 | 4 | 61 | 5.08 / 4.26 | 2.17 / 1.31 | unchanged: 244 / 244 / 206 | 72.8 MiB | 3,117/341; 2,850/523; 3,248/264 |

This is the first broad end-to-end speed result in this path-loss branch: scorer time fell 52.5% on Torus and 69.2% on Pirate, with the same output mesh. Peak RSS was sampled at 50 ms intervals around the final cached runs; Torus used 99.3 MiB and Pirate 72.8 MiB. Available system RAM before the experiments was 2.09 GiB. The result remains a two-asset, 4% simplification screen with 96-pixel fitting views and orthographic axis-aligned pan. It does not establish a SIGGRAPH contribution or performance at larger resolutions, non-axis paths, or 20% reduction.

### Full 20% Torus cache check

The same bounded cache was tested at the full 20% Torus target (1,152 to 922 faces), pool 2, with final fitting-view rebuilds enabled. It preserved all 115 edge/placement choices from the no-cache baseline. The independent final-view audit differed by at most `1.84e-15` per pixel, and sampled peak RSS was 135.3 MiB. However, this does **not** scale as an accelerator: summed scorer time rose from 21.99 s to 55.49 s (2.52x), while completed candidates and per-view evaluations were effectively unchanged (226 vs. 227 and 686 vs. 687). The cache reaches 9,028 source lines and 2,500-2,957 current-scene lines per view. The 4% speedup therefore does not generalize to the full target; do not present the cache as a general performance win. The 20% cache capture is `out/pathloss-captures/torus-96px-pool2-axis-row-cache-20pct.json` (SHA-256 `bf2573202d8b58b6e2aabdc24849ee7ba234cba66fe61f5bf1eb1da1e357ccf8`). Available system RAM before this run was 2.16 GiB.

### Full-run cache diagnosis and local invalidation

I exported cache hit/miss, build/shift/fallback time, and invalidation counters, then repeated the full-clear run. The immutable source caches had 99.2% hit rates. Current-scene caches had only 56.2-57.8% hit rates; each of 115 accepted edits per view cleared about 2,265-2,305 rows, for 6,855 misses total across the three views. Row construction cost 2.75-2.99 s per view, with no degeneracy fallbacks. This identified global invalidation as avoidable work, so `SceneIndex.update` now invalidates only rows intersecting the old/new bounds of edited triangles.

The local invalidation run preserved the baseline's complete 115-edit edge/placement sequence and the final-view rebuild stayed within `1.84e-15` per pixel. It raised current-scene hit rates to 60.3%, 60.3%, and 61.7%, and lowered misses from 6,855 to 6,235 total across the three views. Scorer time changed from 55.29 s to 54.24 s (one run per variant, about 1.9% faster); sampled peak RSS was 135.7 MiB. It remains about 2.47x slower than the 21.99 s no-cache scorer. Selective invalidation is correct on this full target but does not make this cache a useful full-run accelerator. Do not invest further in cache policy without a structural change to candidate scoring.

Reproduce the cached runs with:

```powershell
python tools/mmgeo/probe_global_path_qem.py out/filter-real-candidates/torus.json --remove-fraction .04 --size 96 --scale 2 --radius 1.5 --quality-size 96 --quality-scale 3 --quality-steps 4 --integrate-along-pan --strip-width 1 --pool 4 --axis-row-cache --score-only --audit-final-views --out out/pathloss-captures/torus-pool4-axis-row-cache-4pct.json
python tools/mmgeo/probe_global_path_qem.py out/filter-real-candidates/pirate.json --unit-index 5 --remove-fraction .04 --size 96 --scale 2 --radius 1.5 --quality-size 96 --quality-scale 3 --quality-steps 4 --integrate-along-pan --strip-width 1 --pool 4 --axis-row-cache --score-only --audit-final-views --out out/pathloss-captures/pirate-u5-pool4-axis-row-cache-4pct.json
python tools/mmgeo/probe_global_path_qem.py out/filter-real-candidates/torus.json --remove-fraction .20 --size 96 --scale 2 --radius 1.5 --quality-size 96 --quality-scale 3 --quality-steps 4 --integrate-along-pan --strip-width 4 --pool 2 --axis-row-cache --score-only --audit-final-views --out out/pathloss-captures/torus-96px-pool2-axis-row-cache-20pct.json
python tools/mmgeo/probe_global_path_qem.py out/filter-real-candidates/torus.json --remove-fraction .20 --size 96 --scale 2 --radius 1.5 --quality-size 96 --quality-scale 3 --quality-steps 4 --integrate-along-pan --strip-width 4 --pool 2 --axis-row-cache --score-only --audit-final-views --out out/pathloss-captures/torus-96px-pool2-axis-row-cache-local-invalidation-20pct.json
```

Remove `--axis-row-cache` for the matched baseline. Raw runs are ignored under `out/pathloss-captures/`. The implementation and line budgets are in `probe_dynamic_path_simplification.py`; the global driver exposes the option. Source SHA-256: dynamic evaluator `ff62a873c193663af43f4cf158d053b41f09b98a8d9d80e353583493f9123992`; multiview scorer `22a2a1af7206ecde08778bf8fb899c4636cdcd10bd56b3a88e6fab719d09da14`; global driver `0cbfa40ed386ee1c3ba63c3bdf13f2d834c7a6b7fd5d175525ac62c535f5be33`.

## Decision

The exact path-loss direction still shows a **three-asset quality signal at pool 2**, under a shallow measured memory footprint, but remains much slower than QEM. The bounded axis-scanline cache passed exactness checks and sped up two 4% runs; it was 2.47x slower on the full 20% Torus target even after selective row invalidation. Exact lower-bound pruning, face-record reuse, simple vectorization, and a native per-ray kernel did not close the gap. Candidate-specific view ordering did not give a consistent win; a fixed secondary-view reorder was a small improvement in two full runs. Treat path loss as a research quality objective, not a practical simplifier at this implementation speed. The next step is to pivot to a structural algorithmic hypothesis with a credible end-to-end complexity advantage, while retaining exact path loss as an evaluator or quality guard where useful. The native batch route cannot be evaluated while Windows Application Control blocks its DLL; no code relying on that route remains in the worktree.

The quality evidence is still limited to a geometry/flat-normal CPU proxy, six held-out paths, and three authored assets. A submission claim additionally needs more independent meshes, perspective or rotating paths, shaded RGB/material evaluation, randomized repetitions, and a focused comparison with viewcell, analytic rasterization, and kinetic-visibility prior work.

## Reproduction and provenance

Python driver SHA-256: `1c6e63e0e687f028f95ab459a0df45840dec24178c9a86d6a03877ea1e31ab38`.

| Capture | SHA-256 |
|---|---|
| Pirate unit capture | `e63ec2f6749cceb168cc2135467e643715e10afc838c3e1b9e3a91fa7681d28d` |
| Rounded Cube capture | `89bf7eff63037228f36820556ad0b3b0ec0a6474a71cbe7c2dc96c26cb4bd2f4` |
| Torus capture | `091a30aba8a3d09db01de91bfc537b7d73a42550d6b350c3f976d9e723644c31` |
| Torus 20% axis-row-cache capture | `bf2573202d8b58b6e2aabdc24849ee7ba234cba66fe61f5bf1eb1da1e357ccf8` |
| Torus 20% profiled cache capture | `80064b4b914aea776e2fc04e017b5aa030723ff2c207b26d24bd7ba012d78822` |
| Torus 20% local-invalidation capture | `e0ec7a02818b40cd08c05546c735cae0aba6e50623825d278eeb56a4cb59a1c4` |

The JSON runs are ignored under `out/pathloss-captures/`. Example pool-2 command:

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmgeo/probe_global_path_qem.py `
  out/filter-real-candidates/torus.json `
  --remove-fraction .20 --size 96 --scale 2 --radius 1.5 `
  --quality-size 96 --quality-scale 3 --quality-steps 4 `
  --integrate-along-pan --strip-width 4 --pool 2 `
  --out out/pathloss-captures/torus-96px-pool2.json
```

No C++ code or production pipeline changed. No software test suite was run.
