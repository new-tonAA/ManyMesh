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

I added `--fit-view-count` to measure a view-budget ablation. It selects one centered camera path, two opposite paths, or the existing three paths. On Torus, all runs used the same pool, face target, fitting resolution, and six held-out paths:

| Fitting paths | Path CPU s | Peak WS MiB | Coverage delta vs QEM | Depth delta vs QEM | Flat-normal delta vs QEM | Held-out wins (coverage/depth/normal) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 18.83 | 77.7 | -1.28% | -1.57% | +0.21% | 2/6, 2/6, 1/6 |
| 2 | 42.33 | 105.8 | -7.47% | -15.14% | -3.23% | 4/6, 4/6, 6/6 |
| 3 | 22.23 | 133.8 | -9.65% | -18.60% | -3.81% | 3/6, 5/6, 6/6 |

The one-view run was about 15% faster than the three-view run, but it gave up most of the quality gain and slightly worsened flat-normal error. Two paths were slower than three; they chose a different sequence with larger downstream supports. Therefore runtime is not monotonic in the number of fitted views, and no useful adaptive view-budget policy is established by this ablation.

## Decision

The exact path-loss direction still shows a **three-asset quality signal at pool 2**, under a shallow memory footprint (64–134 MiB peak working set), but it remains much slower than QEM. Exact lower-bound pruning, face-record reuse, simple vectorization, and a native per-ray kernel did not close that gap. Reducing fitted views also lacks a useful tradeoff so far. The next algorithmic gate is candidate-specific view allocation: a cheap decision must predict when omitted paths can change the winner, retain held-out quality, and lower total scoring time. Any such rule needs a held-out path/mesh evaluation. The native batch route cannot be evaluated while Windows Application Control blocks its DLL; no code relying on that route remains in the worktree. If neither this route nor a pure-Python query-reduction method can approach QEM while preserving the measured quality gains, retire the method as a practical simplifier.

The quality evidence is still limited to a geometry/flat-normal CPU proxy, six held-out paths, and three authored assets. A submission claim additionally needs more independent meshes, perspective or rotating paths, shaded RGB/material evaluation, randomized repetitions, and a focused comparison with viewcell, analytic rasterization, and kinetic-visibility prior work.

## Reproduction and provenance

Python driver SHA-256: `a6869b654f91bf8625f42c1a5e1ed6d4b667ab19f6d979b8c1e9f5ef7e6226c5`.

| Capture | SHA-256 |
|---|---|
| Pirate unit capture | `e63ec2f6749cceb168cc2135467e643715e10afc838c3e1b9e3a91fa7681d28d` |
| Rounded Cube capture | `89bf7eff63037228f36820556ad0b3b0ec0a6474a71cbe7c2dc96c26cb4bd2f4` |
| Torus capture | `091a30aba8a3d09db01de91bfc537b7d73a42550d6b350c3f976d9e723644c31` |

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
