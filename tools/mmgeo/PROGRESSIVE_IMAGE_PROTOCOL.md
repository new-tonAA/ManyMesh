# Substantial-reduction image-driven control

2026-11-15. Frozen before running: standard image-driven method family, NOT a novel contribution.
Final status: all three asset runs, all nine checkpoints and twelve-view evaluations completed.
See Lindstrom–Turk, Image-Driven Simplification (2000), already reviewed in this repository:
https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf .

The earlier cumulative image control removed only twelve faces from the captured initial pool.
This control regenerates current-mesh candidates through 75/50/25% retained-face checkpoints.
Each step extracts four distinct current edges in QEM order, each at its first legal QEM placement.
It evaluates all four against the CURRENT accumulated coverage/depth residual on three fitting
views (azimuth 0.13+2*pi*k/3, elevation component .37). It commits the best measured increment;
ties within 1e-14 choose QEM order. Rejected/stale entries do not consume a candidate slot.
Unselected proposals return to the heap; image scores are never reused across geometry updates.
This is a limited QEM-shortlisted image control, not exhaustive image-optimal simplification.

Use the same source capture, local gates, endpoint/midpoint/QEM placement proposals and boundary
locks as the regenerated QEM reference. Identical per-unit retained-face targets apply. All
submeshes participate as occluders, including units already simplified at a checkpoint. Stable
source face/vertex IDs allow exact source-fragment replacement. The current mesh and all-layer
cache must agree by full rerender at EVERY checkpoint, including accumulated filtered residual.
Visibility differences between composed edits are evaluated against the updated cache.

Local raw delta is filtered with the identical Gaussian/box filter, using conservative old/new
triangle bounds and halo. Score is the full cumulative SSE increment, not a standalone positive
error. Negative increments are allowed. Selection must not silently reset residual to zero.
Record actual committed faces, candidate evaluations, initialization, scoring, commits, validation
and total wall time. Candidate count or local-query cost alone cannot be called a speedup.

Twelve measurement views are not used for ranking. They are familiar development assets, not an
independent generalization set. This control fits three views while source contours used eight;
report that distinction rather than implying identical construction information. No attributes,
new intersection proofs, native/GPU costs or continuous temporal validation are supplied.

Start with Torus to establish cost/correctness before the larger two assets. Stop expansion if
checkpoint cache/full-raster validation fails. A runtime limitation must be reported separately
from a quality failure; do not lower the face target and label it a completed large-reduction run.

```sh
python -I tools/mmgeo/progressive_image_baseline.py out/filter-real-candidates/torus.json --out out/progressive-image-control/torus
python -I tools/mmgeo/evaluate_progressive_baseline.py out/filter-real-candidates/torus.json out/progressive-image-control/torus
```

## First completed asset: Torus

All three retained-face targets are reached (864/576/288), with full current-cache and accumulated
residual checks at each checkpoint. The fitting sequence makes 432 collapses and 1728 candidate
evaluations. Twelve measurement views give the following comparison to saved standard QEM:

| Retention | QEM sum SSE | Image-driven sum SSE | Reduction | Worse views / 12 |
|---|---:|---:|---:|---:|
| 75% | 1.73368463 | 1.67720728 | 3.258% | 4 |
| 50% | 11.99398535 | 11.29514322 | 5.827% | 5 |
| 25% | 182.37097446 | 159.07894230 | 12.772% | 3 |

This is a small-pool classical image-driven control, not a claim of image-optimal geometry.
Full views include regressions; mean improvement is not uniform view improvement. QEM and image
policies regenerate DIFFERENT mesh states and candidate pools after their first different choice,
so this is a complete policy comparison, not an equal-fixed-pool rank comparison.

Measured Torus Python time: total 80.62 s, cache setup 0.27 s, candidate scoring 61.75 s,
commits 5.92 s, checkpoint full validation 3.19 s; remaining time includes QEM/legal queue work
and artifact writes. These are per-category wall clocks, no native/GPU comparability. Standard
QEM's earlier complete run was approximately 1.33 s on this asset, so no speed advantage follows.

Two added integration tests check (a) one-edge pool exactly reproduces ordinary QEM geometry,
and (b) after a real multi-collapse history, patch-predicted incremental SSE agrees with independent
full rasterization against the original. Total Python suite: 54 passed; diff whitespace check passes.

The larger Monkey and Pirate jobs used the SAME parameters and have since completed. Intermediate
checkpoint files were not counted as completed runs. Final manifests and full-view results now
exist for both; completing the baseline still does not pass a novelty or publication gate.

## Second completed asset: Pirate

All checkpoints pass full-cache and accumulated-residual validation. Actual faces match QEM:
3760 / 2516 / 1314; the nominal final 25% target remains unreachable for the same locked small
units, so final actual retention is 26.23%. Test-view geometry reductions versus QEM are
30.16% / 36.21% / 9.42%. This is a completed larger-reduction run, unlike the earlier
six-collapse fixed-pool experiments. It still supplies no novelty or runtime advantage.

Python total 243.21 s, setup 0.77 s, scoring 177.56 s, commits 16.97 s, full validation 6.37 s,
7385 candidate evaluations. All timings include the limited-pool policy and validation overhead;
comparison with the earlier 19.05 s QEM run gives no cost advantage. Different component gates
can leave fewer than four legal candidate edges, so evaluations need not be four per action.

The RGB extension and its limitations are described in [controlled shading](SHADING_CONTROLS.md).

## Final completed asset: Monkey and full comparison

Monkey reaches 11808/7872/3936 faces, with actual mesh/full-cache/residual checks passing at each
checkpoint. Its original process returned exit code zero, final manifest was read and twelve-view
geometry/RGB evaluation completed. Python total 826.78 s, cache setup 3.58 s, scoring 600.34 s,
commits 52.67 s, validation 15.49 s, 23616 candidate evaluations. Approximately 90.95 s for the
prior QEM reference offers no cost advantage for this image policy. This is offline prototype
wall time, not a calibrated native performance comparison.

| Asset | Retention target | Actual faces | Geometry SSE reduction vs QEM | Worse geometry views / 12 |
|---|---:|---:|---:|---:|
| Torus | 75% | 864 | +3.258% | 4 |
| Torus | 50% | 576 | +5.827% | 5 |
| Torus | 25% | 288 | +12.772% | 3 |
| Monkey | 75% | 11808 | -23.848% | 5 |
| Monkey | 50% | 7872 | +8.160% | 8 |
| Monkey | 25% | 3936 | +5.223% | 6 |
| Pirate | 75% | 3760 | +30.156% | 3 |
| Pirate | 50% | 2516 | +36.211% | 0 |
| Pirate | 25% | 1314 | +9.416% | 5 |

All nine points match actual QEM faces. Independent topology counters preserve each source's
Euler characteristic, boundary-edge count, nonmanifold-edge count, duplicate/zero-area counts.
These are necessary structural checks, not global surface/attribute validity proofs. Source
normal/UV/material capture is still absent. The image control has a 23.85% geometry regression
on Monkey at 75% retention, so even geometry-only gains are not uniform across budgets.

**Decision:** retain as a completed, executable, bounded-pool image-driven control. Do not call
it a new simplification algorithm or a real-time benefit. The separate RGB audit reveals that
the positive final geometry proxy gains are not stable appearance gains across assets; it must
be included in future acceptance rather than reporting only depth/coverage. A proposed novel
mechanism still needs its own derivation, closest-work difference, matched-work comparisons and
full attribute/temporal checks. Simply adding RGB to an existing image-driven score is already
within the established family and would not itself satisfy the research goal.

The full Python suite passes 56 tests. `out/shading-controls/summary.json` binds all three
completed asset manifests, geometry evaluations, RGB evaluations, cameras and raster hashes.
No long-running progressive-image jobs remain from this experiment.
