# Inverse-raster feasible placement pilot

2026-11-14. Research candidate, NOT established novelty or production-ready simplification.

## Mathematical object

Given a fixed collapse connectivity and a seed sample-to-triangle assignment, exactly one vertex
of each surviving affected triangle moves. In orthographic projected xyz coordinates, signed
triangle area A, barycentric numerators and depth numerator N are affine in that moving vertex.
For fixed epsilon and positive orientation, `(z-epsilon) A <= N <= (z+epsilon) A` is linear.
Area and barycentric-sign constraints are also halfspaces. Joint optimization of epsilon and
position is NOT an LP (epsilon times area is bilinear). Feasible placement itself is not new:
angle-bounded kernels, simplification envelopes and other constrained placement methods exist.

The implemented primitive creates halfspaces for a sampled set of visible seed-owner points.
It does NOT encode all competing surfaces or uncovered pixels. A full frontmost patch rerender
checks sampled coverage and depth before acceptance. This is not a complete visibility cell,
not continuous coverage preservation, and not a mathematical guarantee for unsampled pixels.

## Solver and geometry limits

Dependency-free alternating projections return a feasible witness or iteration-budget failure;
failure is NOT proof of infeasibility. Fixed depth tolerances are 0.75/0.5/0.25 of the seed's
maximum sampled deviation. Three attempts are compared and original Corner placement is retained
unless full patch coverage/depth improves. This acceptance makes no-regression in the chosen
metric tautological; only acceptance rate, magnitude, validation quality and total cost are useful.

First version solved screen constraints and rejected positions beyond endpoint displacement
allowance afterward. 144 candidates: 0 accepted Torus, 0 Monkey, 6 Pirate. Most feasible witnesses
failed this geometric guard. Pirate accepted-case median error reduction ~63.9%, but aggregate
SSE only 0.857055 -> 0.856690; dramatic local ratios do not establish overall benefit.

A follow-up solves in world displacement coordinates. The same two endpoint displacement balls
are included in alternating projections, rather than relaxing the gate. World-to-screen Jacobian
is fixed from the original camera normalization. Triangle quality and orientation are still checked
afterwards. It does NOT run the complete Corner attribute/surface gate, preserve UV/normal shading,
or detect new global self-intersections. Do not enable in production.

## In-solve endpoint-ball result

Without relaxing displacement allowance, the constrained version accepted 0/48 Torus, 6/48 Monkey,
9/48 Pirate candidate placements. It removed the post-hoc geometric rejection bottleneck but did
not establish meaningful aggregate gain: Monkey total SSE 0.0177563272 -> 0.0177543517 (~0.011%),
Pirate 0.857055099 -> 0.856692274 (~0.042%). Accepted-case medians (47.7% / 75%) are misleading
without these aggregate numbers. Median per-candidate time is 37.1 / 79.3 / 44.6 ms, including
seed raster and proposal validation, not a real-time update cost.

All accepted positions were evaluated without refitting at offsets -0.21 and +0.17 radians
from their fitting view. Monkey: 12 cases, 9 improved / 2 worse / 1 unchanged; total SSE
8.63862e-6 -> 3.39034e-6. Pirate: 18 cases, 6 improved / 6 worse / 6 unchanged, including two
coverage regressions; total SSE 0.00719388 -> 0.0138587 (about 1.93x worse). Torus had no accepted
placements to audit. Artifacts: `out/raster-placement-constrained/side-view-audit.json`.

This is a disconfirmation test on the same development assets, not an independent asset benchmark.
The single-view placement model does not justify reusable stable LOD claims. Do not deploy it.
Multi-view simultaneous constraints could be a future hypothesis, but cannot be assumed to retain
feasibility or gains and would need separate new evaluation trajectories and full attribute gates.

## Joint-view follow-up: frozen protocol

`evaluate_multiview_placement.py` uses the SAME full 144 visible-support candidate set, not only
single-view successes. Fit offsets are -0.12/0/+0.12 radians, jointly mapped into world-displacement
constraints with identical endpoint-ball limits. Acceptance requires neither coverage nor depth
regress in ANY fitting view and strict improvement of summed loss. This is a conditional fallback
rule, not proof of generalization. Original placement is retained if no proposal passes.

Test offsets, not used for fitting/acceptance, are -0.27/-0.06/+0.06/+0.29. These include intermediate
and extrapolated views; they are not a guarantee over continuous motion. Unchanged fallback cases
are explicitly recorded and excluded from claims of novel geometry improvement. If test metrics
regress, do not silently revert using those test outcomes or refit on them; report the failure.
The same development assets are used, not unseen assets. Full attribute/surface gates remain open.

Five mathematical tests now include independent world-to-view Jacobians across several cameras.
Practical success would require nontrivial acceptance rate and aggregate quality benefit, retained
at test views, plus plausible solve cost; tiny positive examples or fallback-only safety do not
satisfy that requirement. No SIGGRAPH claim follows from solving a convex feasibility subproblem.

## Resumed joint-view audit (2026-11-14)

The Claude Code run completed before the session lost API access. The frozen outputs are
`out/raster-placement-multiview/{torus,monkey,pirate}.json`. They are individual candidate
placements, NOT sequential simplification or a dynamic LOD benchmark.

`audit_multiview_placement.py` checks capture/evaluator hashes, candidate IDs and frame angles,
then evaluates ALL fallback and accepted candidates at the four frozen test offsets. For accepted
positions it redraws both seed and proposed geometry over the entire image and compares with
the recorded patch scores. This checks patch support/filter bookkeeping using the same rasterizer;
it is not independent validation of that rasterizer. Test outcomes never change the saved positions.

The original output only saved test scores for accepted positions. Those sums are a selected
subset, not the population denominator. For example Pirate's accepted-subset reduction is 53.47%,
but the complete 192 candidate/view cases reduce SSE only from 2.79682590047 to 2.78354207017
(0.47496%). There are 9 improvements, 1 regression, and 182 unchanged cases; no coverage regression.
The regression is frame 1, candidate 1987, offset -0.06: depth SSE 1.80415e-11 -> 4.12514e-10.
Its large relative ratio has tiny absolute magnitude, and is retained rather than silently reverted.
Torus accepts 0/48 placements and all 192 test cases remain unchanged (SSE 30.1011501241).

Monkey accepts 4/48 placements. Across all 192 test cases SSE changes from 0.0414128309888
to 0.0414065177539 (0.015245% reduction), with 15 improvements, 1 regression and 176 unchanged.
The accepted-subset reduction alone is 45.55%. Its regression is frame 2, candidate 24551,
offset -0.06: depth SSE 5.84075e-10 -> 8.29332e-10, without a coverage regression.
Across the 36 accepted candidate/test-view pairs, full-image and recorded patch metrics agree
to a maximum absolute difference of 3.71e-21. All 576 candidate/view cases are reported.

| Asset | New placements | All-test SSE reduction | Improved / worse / unchanged |
|---|---:|---:|---:|
| Torus | 0/48 | 0% | 0 / 0 / 192 |
| Monkey | 4/48 | 0.015245% | 15 / 1 / 176 |
| Pirate | 5/48 | 0.474961% | 9 / 1 / 182 |

Decision: this completes the frozen joint-view pilot, but it does not pass the existing practical
success gate. Keep it as an experimental reference; do not extend this placement heuristic into
the dynamic production path based on these results. Aggregate gains are small, Torus has none,
cost is high, and neither full appearance gates nor sequential/continuous-motion behavior was
tested. Two tiny depth regressions do not justify claiming widespread instability either.
Any subsequent mechanism must establish a concrete difference and an explicit comparison budget
before another parameter sweep; these test views are now inspected development data.

Recorded median fitting times are 231.66 / 1875.82 / 613.64 ms per candidate for
Torus / Monkey / Pirate. They include reference-image rasterization repeated per candidate/view,
constraint construction, solving and fitting acceptance, but exclude test-view evaluation.
These are archived run timings, not measurements from the audit and not pure solver timings.
Neither a real-time update advantage nor a quality/time Pareto improvement has been demonstrated.

Reproduce for each asset (replace `pirate` with `torus` or `monkey`):

```sh
python -I tools/mmgeo/audit_multiview_placement.py out/filter-real-candidates/pirate.json out/depth-candidate-trajectory/pirate.json out/raster-placement-multiview/pirate.json --out out/raster-placement-multiview/audit-pirate.json
python -I -m unittest discover -s tools/mmgeo -p 'test_*.py'
```

The Python suite passes 23 tests, including two new population-reporting regressions and five
placement-math tests. This continuation changes Python audit/reporting and documentation only;
it does not revalidate earlier C++ changes or resolve historical desktop build failures.

## Tests

Five tests verify affine terms at random positions, equivalence of halfspaces to direct raster
equations at fixed depth epsilon, world-to-view Jacobians, simple feasible systems and endpoint-ball
constraints. The real experiment uses 48 visible-support candidates per asset over six previously
used camera frames, not an independent held-out set. Fixed ownership may miss better disconnected
feasible regions or all useful placements after correspondence changes.

## Prior art status

A bounded independent search found:
- Angle-Bounded 2D Mesh Simplification: feasible kernels/halfplanes and disks/QCQP already exist.
- Simplification Envelopes: hard error-limited simplification is established.
- Screen Space Meshes: depth/silhouette-based screen parameterization is established.
- Image-Driven Simplification: appearance-driven collapse evaluation is established.

Only excerpts/abstracts were checked for the most recent placement search, not full equivalence
analysis. No claim that inverse-raster placement is unprecedented is justified.

Sources:
- https://graphics.cs.uni-paderborn.de/graphics/papers/Angle_Bounded_2D_Mesh_Simplification-Preprint.pdf
- https://matthias-research.github.io/pages/publications/screenSpaceMeshes.pdf
- https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf

Artifacts: `out/raster-placement-pilot/` (initial guard-after-solve),
`out/raster-placement-constrained/` (same limits included inside solve).
