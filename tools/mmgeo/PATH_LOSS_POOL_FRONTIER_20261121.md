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

## Decision

The exact path-loss direction now has a promising **three-asset quality signal at pool 2**, under a shallow memory footprint (64–134 MiB peak working set), but it remains much slower than QEM. Exact lower-bound pruning and simple vectorization did not close that gap. The next practical step is a native batched path-event and filter kernel with an unchanged scalar reference, then rerun the same fixed protocol and require score/sequence parity before evaluating speed. If a native kernel cannot approach QEM while preserving the measured quality gains, retire this method as a practical simplifier.

The quality evidence is still limited to a geometry/flat-normal CPU proxy, six held-out paths, and three authored assets. A submission claim additionally needs more independent meshes, perspective or rotating paths, shaded RGB/material evaluation, randomized repetitions, and a focused comparison with viewcell, analytic rasterization, and kinetic-visibility prior work.

## Reproduction and provenance

Python driver SHA-256: `4177be64fab00d2f40d76e1a08268db07a440ff0fb014c119801fa064e82c525`.

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
