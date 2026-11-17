# Mesh/raster cooperation: fragment-transaction experiment

Date: 2026-11-14. Research hypothesis, not a novelty claim or SIGGRAPH readiness evidence.

## Implemented mechanism

`transactional_raster.py` implements per-tile fragment lists with stable triangle IDs and ALL
sampled depth layers. An edit removes fragments from affected faces and rasterizes replacement
faces; only queried tiles are resolved. It supports actual commit, immediate undo, and version
checks rejecting stale/foreign proposals. Retained transactions use copy-on-write tile arrays.
This is a sampled depth/coverage mechanism, not full material shading or continuous visibility.

Seven tests pass, including hidden-layer recovery through 20 layers, equal depth, movement across
tiles, stale/foreign transactions, multi-edit sequences and random sequential edits/undo checked
against a separately implemented complete rasterizer. Undo is only permitted for the most recent
commit, not arbitrary history replay. Full multi-level mesh topology state is NOT managed here.

## Stronger baseline

`benchmark_fragment_transactions.py` compares against a spatially indexed patch redraw. An index
returns all unchanged occluders intersecting the patch; affected/new faces are explicitly included.
Both methods use identical geometry, sample grid, filter and patch. Four timed repetitions use
alternating execution order after warm-up. Reference/full-frame validation is outside timings.
Camera changes rebuild both index/cache; no free cross-frame cache reuse is assumed.

Candidate geometry is from existing Corner capture and the previously fixed real-asset trajectory.
The Python stateful code is an executable research mechanism, not a production C++ implementation.

## Ten-candidate batches: failed amortization

Six camera frames per asset, ten candidates each. 180 comparisons passed with maximum image
residual discrepancy 1.43e-16; real-candidate commit/undo checks also passed.

| Asset | Median query speedup | Setup-inclusive batch speedup | Median cache setup | Persistent arrays |
|---|---:|---:|---:|---:|
| Torus | 3.93x | 0.87x | 82.84 ms | 1.77 MiB |
| Monkey | 37.44x | 0.69x | 863.89 ms | 1.54 MiB |
| Pirate | 14.75x | 0.97x | 285.61 ms | 1.36 MiB |

At ten candidates, ALL assets are slower after setup. The estimated break-even is 12.2, 13.7,
10.4 candidates respectively. This is an estimate from these candidates, not a measured universal
threshold. A separate 48-distinct-candidate batch experiment is required to test it.

Memory numbers exclude Python dictionary/set/object overhead, raster temporaries, source geometry
and histories retained by the caller. Depth complexity is unbounded; never claim hard memory bounds.
Timing is Python CPU, not GPU, mobile or whole-frame rendering. Commit/undo times are separately
recorded, not included in query batch figures.

## Forty-eight distinct candidates per frame (preliminary cost accounting)

The larger batch ran 288 real candidates per asset over the same six cameras. All sampled outputs
and commit/undo checks agreed with indexed redraw (largest residual discrepancy 3.99e-16).
Initial setup-inclusive batch ratios were 2.36x / 3.05x / 4.91x for Torus / Monkey / Pirate.
However, review found first full-cache resolve time was not included. These figures are preliminary,
not final end-to-end results. The implementation now records initial resolve, and distinguishes an
already-available reference image from from-scratch rendering. Corrected runs are pending.

## Corrected initialization accounting

`out/fragment-transactions-cost-audit/summary.json` includes initial full-cache resolve. For 48
candidates/frame, existing-reference batch speed ratios are **2.20x / 3.05x / 4.84x** (Torus /
Monkey / Pirate). From scratch, including the baseline's original image render, ratios are
2.52x / 3.70x / 5.40x. Corrected break-even counts are about 13.5 / 14.6 / 8.2. These remain
Python batch evaluation measurements, not renderer or simplifier frame speedups.

## Actual mesh operations, not only candidate evaluation

`simplify_with_fragment_cache.py` executes six collapses per view, maintains cumulative image
residuals, and writes edited OBJ meshes. Candidates whose original one-ring support touches a
previously edited one-ring are invalidated. This conservative rule preserves initial local
candidate assumptions, but is not a general legality update system or global self-intersection
proof. Every commit sequence is checked against independently rasterized actual output geometry.

All 18 asset/view pairs reached equal budgets (12 fewer triangles than source). Cumulative image
selection beat original Corner ordering within the SAME limited candidate pool in all 18 cases.
Summed coverage+depth SSE (Corner ordering -> cumulative):

- Torus: 0.0278098 -> 0.000257328.
- Monkey: 0.00145081 -> 1.88904e-7.
- Pirate: 0.00156268 -> 1.30323e-9.

These dramatic ratios are against nearly zero errors at tiny reductions; they are NOT perceptual
quality improvements of the same magnitude. Both policies operate a capture-derived restricted
pool, not the full production Corner algorithm. They both use cache machinery for output checking;
the recorded Corner timing is therefore not production Corner throughput. Cumulative-policy
median time is about 0.61 / 1.24 / 0.71 seconds. No realtime, high-reduction, material or temporal
stability result follows. This experiment establishes a working strong image-driven baseline,
not a novel method. Artifacts: `out/fragment-batch-simplify/`.

## Evidence and source

- `out/fragment-transactions/{torus,monkey,pirate,summary}.json`
- `tools/mmgeo/test_transactional_raster.py`
- `tools/mmgeo/benchmark_fragment_transactions.py`
- `tools/mmgeo/summarize_transactions.py`

Input report and implementation hashes are recorded; setup and raster correctness are verified in
all frames. No visual difference is expected when the sampled outputs agree. Faster evaluation
alone does not prove better mesh quality or new algorithmic contribution.

## Novelty gate

Multi-layer fragment buffers, incremental redraw and image-driven simplification already exist.
Targeted independent full-text review of Lindstrom–Turk 2000 §4.2.3 found an explicit description
of object buffers retaining all depth layers to undo old triangles, reveal occluded surfaces and
render replacement triangles. Their actual implementation instead uses hardware local redraw
with row/column triangle-ID buckets. Thus BOTH mechanisms compared here are already discussed by
that work. Object buffers are attributed there to Atherton 1981; that earlier full text was not
verified in this session. Do not confuse object buffers with Mark–Proudfoot F-buffers.

**Decision: reject fragment transactions as the proposed independent SIGGRAPH contribution.**
Keep this implementation only as a strong executable baseline. Version checks, tile organization
and ordinary transactional bookkeeping do not rescue novelty. No production default was changed.

Sources: [Lindstrom–Turk 2000](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf),
[Atherton publication entry](https://doi.org/10.1145/800224.806816).
