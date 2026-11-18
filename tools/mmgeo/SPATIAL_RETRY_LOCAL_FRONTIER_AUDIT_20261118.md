# Spatial retry local frontier audit (2026-11-18)

## Question

The current DAG builder already retries a rejected multi-child group by splitting its members
along the longest spatial axis, to depth two (`splitGroupMembers` in `LodGraph.cpp`, introduced by
commit `436df8c25`). Does that existing mechanism create a measurable quality-valid cut option in
the captured builds? This re-analysis is needed before proposing a different witness-guided split.

## Method

`audit_spatial_retry_frontier.py` reads each `trial == 0` group from the schema-1 diagnostic ledger.
Strict member-set containment recovers the retry tree for each generation. For every promoted group,
the script requires an exact matching parent in `lod_graph.json`, with matching triangle count and
accumulated error. It also checks that a group's recorded input triangle count equals the sum of its
member DAG nodes and that top-level group regions are disjoint.

The counterfactual keeps every initially promoted parent unchanged. A rejected first-pass group
remains as its input nodes in the baseline; in the retry cut, accepted descendants replace their
members while unpromoted/residual members remain unchanged. The reported maximum accumulated error
is over the union of diagnostic groups for that generation, not the whole mesh cut. Because each
replacement is an actual graph parent and group regions are disjoint, this is a composed local
cut comparison. Retry cost is reported as the sum of triangles passed into all retry groups, and
attempt count is summed from the simplifier records. Triangle visits are an input-size work proxy;
they are not wall time or peak memory. The audit does not measure the rasterized image or every
reachable hierarchy cut.

## Results

Triangle counts are baseline -> spatial-retry cut. `max error` is the group-union maximum
accumulated error for the same generation.

| Asset | Generation | Triangles | Max error | Retry groups accepted | Result |
|---|---:|---:|---:|---:|---|
| Cloth | 5 | 33,144 -> 32,928 (-216) | 0.0486392 -> 0.0486392 | 7 | Dominates locally |
| Cloth | 6 | 32,190 -> 30,764 (-1,426) | 0.0671406 -> 0.0671406 | 16 | Dominates locally |
| Cloth | 7 | 30,752 -> 30,328 (-424) | 0.0680836 -> 0.0680836 | 6 | Dominates locally |
| Cloth | 8 | 30,326 -> 30,296 (-30) | 0.0680836 -> 0.0680836 | 1 | Dominates locally |
| Cloth | 9 | 30,286 -> 30,214 (-72) | 0.0680836 -> 0.0680836 | 1 | Dominates locally |
| Shapes | 4 | 34,548 -> 34,034 (-514) | 0.0440463 -> 0.0440463 | 7 | Dominates locally |
| Shapes | 5 | 24,417 -> 24,219 (-198) | 0.0758241 -> 0.0758241 | 1 | Dominates locally |
| Shapes | 6 | 19,080 -> 18,668 (-412) | 0.1034753 -> 0.1034753 | 1 | Dominates locally |
| Material Sphere | 5 | 4,228 -> 4,192 (-36) | 0.0219702 -> 0.0249058 | 1 | Lower triangles, higher error |
| Material Sphere | 6 | 4,184 -> 3,976 (-208) | 0.0249058 -> 0.0373896 | 1 | Lower triangles, higher error |
| Monkey | 3-7 | unchanged | unchanged | 0 | No retry children recorded |

The extra retry input work per generation exposes a steep diminishing return on Cloth:

| Asset / generation | First-pass input triangle work | Retry input triangle work | Triangles saved | Saved / retry input |
|---|---:|---:|---:|---:|
| Cloth / 5 | 41,340 | 2,326 | 216 | 9.29% |
| Cloth / 6 | 32,928 | 41,764 | 1,426 | 3.41% |
| Cloth / 7 | 30,764 | 48,546 | 424 | 0.87% |
| Cloth / 8 | 30,328 | 47,650 | 30 | 0.06% |
| Cloth / 9 | 30,296 | 47,668 | 72 | 0.15% |
| Shapes / 4 | 47,516 | 5,242 | 514 | 9.81% |
| Shapes / 5 | 34,034 | 3,174 | 198 | 6.24% |
| Shapes / 6 | 24,219 | 5,368 | 412 | 7.68% |

## Frozen-outcome retry-budget oracle

The audit also enumerates whole retry trees per failed root as indivisible packages. It keeps only
packages whose observed output does not exceed the no-retry generation's group-union maximum error,
then solves a 0/1 knapsack over retry input triangles. This oracle sees the completed outcomes before
choosing; it is an optimistic upper bound for a future predictor, not an implementable policy.

On Cloth generation 6, the fixed retry run spends 41,764 retry input triangles and saves 1,426
triangles. The frozen-outcome oracle retains the same 1,426-triangle saving at a 35,584 retry-work
budget (about 14.8% below the fixed run) under the same group-union maximum-error cap. At half that
oracle budget (17,792), it saves 996 triangles. At Cloth generation 7, half of eligible oracle work
(16,168) saves 270 of the 424 triangles; at generation 8, a half budget saves zero because the only
useful retry tree is indivisible. Shapes generation 4 saves 320 of 514 triangles at half of eligible
retry work (2,621).

This establishes only **offline allocation headroom in a frozen development capture**. It does not
show that the rejected-candidate witness fields predict successful retries, that a scheduler can
realize the upper bound, or that triangle visits track wall time/memory. The next experiment should
freeze the split budget and assets, use only first-pass gate/witness data to rank retry trees, and
compare against spatial-median all-retry and a simple measured-gain-per-input-triangle baseline.
Measure the full build and peak memory, then audit the resulting complete cut with the raster metric.
The split policy must beat those controls on held-out assets before it can support a research claim.

## First-pass rejection-mask ranking screen

To see whether the existing schema-1 gate histograms contain a useful early signal, the audit also
ranks whole root retry trees by one of four **first-pass-only** features: total, attribute, topology,
or geometry rejection counts per 1,000 input triangles. Ties use a stable member-ID order. The
retrospective evaluation uses each completed tree's measured triangle-visit work and output; it does
not use eventual triangle savings to rank. The budget check treats a whole observed tree as
indivisible and uses its completed retry work as package cost, so this is not an executable online
scheduler.

At half of Cloth generation 6's total retry work budget, total reject density saves 810/1,426
triangles while staying within the baseline group-union error cap; attribute, topology, and geometry
reject density save 504, 722, and 668 respectively. On Shapes generation 4, attribute rejection
density saves 314/514 at 2,430 triangle visits under a 2,621-visit cap. These are small, retrospective
examples from development assets. Material Sphere has nonzero rejection masks, but each productive
retry tree exceeds the half-work budget as an indivisible package; at full budget its generations 5
and 6 cuts reduce triangles while exceeding the baseline maximum error. The mask screen therefore
does not establish a cross-asset predictive signal or an online benefit. The schema-2 witness records
may provide more localized features, but only a runtime capture and held-out asset evaluation can
determine that.

Adding a cost-only control weakens the mask-ranking result further. At 50% of Cloth generation 6's
full retry work, total reject density and smallest-work-first both save 810 triangles. At generation
8, smallest-work-first saves 30 triangles using 16,410 visits while every gate-mask rank saves zero
at its half-budget point. Shapes generation 4 is the clearest positive mask delta: attribute/geometry
ranking saves 314 versus 270 for smallest-work-first at the same 2,621-visit cap. Cloth generation 9
attribute ranking finds the one productive tree at half budget, while smallest-work-first does not.
These sparse, non-held-out differences are not enough to justify a witness-aware scheduler; it must
show repeatable held-out gain over cost-only allocation and spend measured wall time, not just input
triangle visits.

Generations are alternative cuts of successive builder states; do not sum the reductions across
rows as one mesh-wide triangle saving. At Cloth generation 6, for example, the retry alternatives
recover 1,426 triangles at the same group-union maximum error. This is a positive result for the
existing generic spatial split on these captured builds, not evidence for the proposed witness split.

## Full retry-work budget curve follow-up (2026-11-18)

The four archived audits were extended from four budget samples (25/50/75/100%) to 101 caps from 0% through 100% of each generation's total all-retry triangle-input work. At every cap, first-pass rejection-mask ranks and smallest-work-first greedily select whole retry trees that fit. If a selected union exceeds the baseline group-union error cap, its valid triangle saving is scored as zero. The hindsight knapsack oracle selects only whole trees that save triangles and satisfy that error cap. This isolates ranking quality but is still a retrospective work proxy: package outcomes, total retry work, raster quality, wall time, and peak memory are not predicted or measured.

Only 8 asset/generation rows had any oracle-eligible tree: Cloth generations 5-9 and Shapes generations 4-6. Material Sphere had retries that reduced triangles only with higher error, and Monkey had no retry trees. Aggregating the 101-point saved-triangle curves across those 8 rows, smallest-work-first reaches 83.7% of oracle integrated savings. Total, attribute, topology, and geometry rejection-density ranks reach 75.0%, 76.1%, 69.0%, and 72.2%, respectively. Against smallest-work-first by row, total reject density wins 0 / ties 5 / loses 3; attribute wins 2 / ties 2 / loses 4; topology wins 1 / ties 2 / loses 5; geometry wins 0 / ties 2 / loses 6. The few attribute wins are outweighed by losses and are not held out.

This strengthens the negative decision: **close scalar rejection-mask ranking as the repair-allocation candidate.** The schema-2 details may still diagnose where a specific split should occur, but another mask or scalar rank should not justify a runtime-policy workaround, another expensive build, or a SIGGRAPH claim. Reopen only with a distinct, specified witness-to-partition mechanism that predicts a cut-level gain over spatial median and cost-only controls, then evaluate it on held-out assets with a conventional raster metric and measured memory/time. Reproduction artifacts: `out/spatial-retry-audit-20261118-fullcurve/{cloth,shapes,material-sphere,monkey,summary}.json`; analyzer: `summarize_spatial_retry_budget_curves.py`.

## Decision

This reveals real local headroom that the prior adjacent-group swap screen did not measure. The
generic spatial retry is already a meaningful baseline: any witness-directed split must improve its
triangle/error frontier at equal total construction work and peak memory. In Cloth, later levels
spend more retry triangle work than the first-pass group work while saving at most 424 triangles;
this points to a concrete split-budget allocation question, but the triangle-visit ratio must not be
presented as a time speedup. Material Sphere also shows that a lower triangle count can raise the
group's maximum accumulated error; counts alone are not a quality result.

No retry-specific wall time, total build time delta, peak-memory delta, filtered-raster metric, or
held-out-asset result was available in these captures. This therefore does **not** show an equal-cost
gain, a new algorithm, or SIGGRAPH readiness. The follow-up full-budget screen below closes scalar
rejection-mask ranking as a candidate. A schema-2 runtime capture is justified only if a distinct,
explicit witness-to-partition mechanism is specified first. Any viable candidate must beat spatial
median and cost-only controls on complete strict-gate cuts, at matched measured work, raster quality,
and memory on held-out assets.

## Reproduction and provenance

Run from the repository root:

```powershell
python -I tools/mmgeo/audit_spatial_retry_frontier.py `
  out/quality-witness-current/cloth-regroup-pilot-200k/diagnostics.json `
  out/quality-witness-current/cloth-regroup-pilot-200k/lod_graph.json `
  --out out/spatial-retry-audit-20261118/cloth.json
```

Repeat with `shapes-regroup-pilot-200k`, `material-sphere-regroup-pilot-200k`, and
`monkey-regroup-pilot-200k`. These are existing captures, not new `mmgeo` executions. For the full-budget
rerun, write each result into `out/spatial-retry-audit-20261118-fullcurve/` and then run:

```powershell
python -I tools/mmgeo/summarize_spatial_retry_budget_curves.py `
  out/spatial-retry-audit-20261118-fullcurve `
  --out out/spatial-retry-audit-20261118-fullcurve/summary.json
```

Captures bind to workspace HEAD `422c7e50c4c802f88788dbf27e6d01273dc343ec`. The updated audit script
SHA-256 is `239330b061d0ed8cfbf3f60b3156c90d478dbe8e1f4b0cf1fdaede64315821a2`; the new summary script
SHA-256 is `973a1dbaf991756423a5c6dea904530e926849981ceb59cda294f4f72c07b474`.

| Asset | diagnostics.json SHA-256 | lod_graph.json SHA-256 |
|---|---|---|
| Cloth | `5f0d31c64f1cbb400a93d404d89cc7664dd7a9e30162c9063fe9c820ebfa3326` | `f018718ba6cb166e4b056def3ee7ac2c42da6f6e7a13863e5785ba515e004607` |
| Shapes | `cae99c3ebca145580a0afc92e704a99db6076a29d9bfb38258776e6200f6d506` | `682bf375100bd4937fcc80c764e6d42695c8969fa339a13aefbf22a94412fd1a` |
| Material Sphere | `e924aedc187971fb68075e810b75e525af9aa3794fe30a6ecba37c2b7c2b2394` | `7279643ccdbef6c812d6e2492e03ec8cf8500eec3c12c39cf780537fdae9e11a` |
| Monkey | `939cb4e4fcea22f3cba8278f73e99abf0e7a53a85cef053202fc59943c466195` | `95d9ceeaafb807e8e89b9d31d00a7e5c93cd6e53e9204f11881e4b86052356f3` |

No C++ code changed and no software tests were run. The audit script completed for all four captured
assets and matched every promoted diagnostic group to one saved graph node.
