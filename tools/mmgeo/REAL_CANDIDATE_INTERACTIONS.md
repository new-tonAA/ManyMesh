# Filtered image-error interactions between real collapse candidates

2026-11-15. Exact offline audit, not a new algorithm claim.

## Method

Used the three hashed 288-candidate raw raster-delta exports (six frames x 48 candidates), at
128x128, 3x supersampling and sigma=0.9. Reconstructed each candidate's exact two-channel
filtered image residual, then computed the Gram matrix. For same-frame candidates with disjoint
affected vertex one-rings,

    E(i+j) = E(i) + E(j) + 2 <F d_i, F d_j>.

This is exact for the frozen linear spatial filter and the recorded independent single-collapse
deltas. It does NOT imply the geometric operations remain valid together: visibility deltas can
change after the first edit. No pair is claimed as a legal committed batch.

I also counted selection-order reversals: for a shared disjoint context collapse k, compare the
standalone ranking E(i) vs E(j) against E(i+k) vs E(j+k). All candidate IDs and view frames were
retained. Corrected input hashes are in `out/candidate-interactions-v3/{asset}.json`.

## Results

| Asset | Compatible pairs | Image-overlapping | Pairs with >10% cross interaction | Ranking reversals / tested triplets |
|---|---:|---:|---:|---:|
| Torus | 6,286 | 866 | 6 | 221 / 268,807 (0.0822%) |
| Monkey | 6,667 | 774 | 19 | 503 / 302,104 (0.1665%) |
| Pirate | 6,594 | 976 | 54 | 1,472 / 295,517 (0.4981%) |

There are real large cross terms, but strong pairs are sparse (0.10%, 0.28%, 0.82% of all
one-ring-disjoint pairs). Ranking reversals are below 0.50% of tested triplets. The triple count
includes cases with near-tied standalone scores, so reversals alone do not imply a useful decision
change. The audit therefore finds a real interaction signal but does not establish that a predictor
can find it cheaply, that the corresponding collapses compose legally, or that quality/cost improves.

No expensive all-pairs patch rerender follows automatically: that would reproduce the known
quadratic cost concern of the Gram path. Next gate is to inspect the reversal cases' geometry,
screen-space support and actual two-operation topology, then compare a cheap overlap prefilter and
the exact interaction score against exhaustive joint scoring on the same frozen pool. Stop if the
small reversal rate consists only of near ties or if legal joint operations erase the effect.

## Reproduction

```sh
python -I tools/mmgeo/audit_real_candidate_interactions.py out/filter-real-candidates/torus.json out/fragment-transactions-cost-audit/torus.json out/discrete-filter-pilot/torus.txt --out out/candidate-interactions-v3/torus.json
```

The manifest-bound report is the fragment-transaction cost audit; using the related depth report
is rejected by the hash check. The script currently reports the complete JSON, including strongest
examples and per-frame statistics. No C++ or production ranking changes were made.

## Self-context correction and actual pair rendering

The initial matrix had a true diagonal, allowing context k to be one of its own alternatives.
This incorrectly compared i+k to k+k. Earlier reversal figures 1284/1518/1951 are withdrawn;
`out/candidate-interactions/` is superseded. The corrected matrix has a false diagonal; ranking
rejects self compatibility and duplicate IDs. Two regression tests cover orthogonal residuals
(no reversals) and an analytic distinct-context reversal. Both pass.

Reversals above absolute 1e-12 plus relative 1e-6 times the compared standalone sum are
218/484/1057. These numerical floors do not establish perceptual significance. Alternatives i,j
may overlap each other because only either i+k or j+k is applied, never all three together.

The reconstructed residual energy of every archived candidate is now checked against its original
export reference. `audit_joint_collapse_raster.py` actually applies both captured operations and
redraws frontmost geometry, unchanged occluders included, with conservative union support/halo.
The initial strongest-case check (`out/candidate-interactions-v2/joint-*.json`) audited 14/30/57
pairs: 4/0/1 pairs had raw nonadditivity above 1e-12. Nevertheless the largest-impact reversal in
each frame survived actual redraw in 18/18 cases. This is a selected disconfirmation set, not a
population quality benchmark. It demonstrates that genuine examples survive and that simply
adding individual deltas is not always correct.

Disjoint one-rings preserve each operation's captured local mesh, but do not prove global
intersection safety or complete attribute/Corner legality. Deleted-face counts are checked to
add across the two operations; full production validation remains open.

## Does the interaction change the selected two-collapse output?

Added two exhaustive selectors over the same one-ring-disjoint pair pool: minimize E(i)+E(j),
or minimize E(i)+E(j)+2Gij. Both have the same two-collapse/four-triangle reduction budget.
The model is an offline oracle using measured residuals; no runtime speed claim is made.
Both selected pairs are actually applied and rendered, alongside the strongest example pairs.

All 18 asset/frame pairs choose identical IDs under both selectors. Actual summed output SSE:

| Asset | Independent selector | Cross-term selector | Reduction |
|---|---:|---:|---:|
| Torus | 1.61125868e-5 | 1.61125868e-5 | 0% |
| Monkey | 1.86216267e-8 | 1.86216267e-8 | 0% |
| Pirate | 2.63740362e-13 | 2.63740362e-13 | 0% |

Final v3 actual-geometry audit covers 20/36/63 selected pairs, each removing four triangles.
Nonadditive raw samples occur in 4/0/1 pairs, and the 18 strongest-context reversals remain.
The small selected-output errors reflect a restricted candidate pool and tiny reduction, so this
is a screening result, not evidence of perceptual quality or a substantial compression ratio.

Decision: this pool provides real interaction examples but NO observed selected-output benefit
at a two-collapse budget. Do not expand a global Gram scorer from this result. Larger reductions
and regenerated candidate pools could behave differently; they would need a separate frozen
protocol, actual joint visibility evaluation and a comparison against the existing cumulative
image-driven baseline. Neither this correction nor exact scoring constitutes a new mechanism.

```sh
python -I tools/mmgeo/audit_joint_collapse_raster.py out/filter-real-candidates/torus.json out/candidate-interactions-v3/torus.json --out out/candidate-interactions-v3/joint-torus.json
python -I -m unittest discover -s tools/mmgeo -p 'test_*.py'
```

38 Python tests pass; `git diff --check` passes. This continuation changes the research audit and
documentation, without revalidating the historical C++ build state.

## Frozen-pool multi-collapse follow-up (2026-11-16)

Extended the same Torus candidate pool to 4, 8 and 12 simultaneous collapses. Each of six views
contains 48 frozen initial-state candidates; every candidate removes exactly two triangles, and
candidate sets require pairwise-disjoint affected vertex one-rings. The independent selector
minimizes the sum of single-collapse filtered SSE. The interaction selector includes all pairwise
filtered residual cross terms. k=2 and k=4 are exact finite-pool subset searches; k=8 and k=12 use
deterministic greedy prefixes. Every selected composite is actually applied to the source mesh and
fully rerasterized.

At all four budgets, independent and interaction selectors choose the **same candidate set in all
six views**. The actual filtered coverage/depth SSE changes by 0% in every view. The maximum
absolute gap between pairwise prediction and full composite redraw is 2.8e-17. All 12 outputs per
budget preserve the torus's Euler characteristic, connected component count, closed two-manifold
edge incidence, oriented edge consistency, signed-volume orientation, and have zero duplicate or
zero-area faces. At k=12 the cut removes 24/1,152 triangles (2.08%), still a small reduction.

This is a stronger negative result for the *frozen Torus pool*: pairwise screen-space interactions
do not change the selected output up through 12 collapses. It does not test regenerated candidates,
substantial reduction, authored attributes, global self-intersection, or other meshes, and it is
not a runtime result. Do not expand the pairwise interaction scorer for this pool. If the broader
filter-aware line continues, the next evidence must come from a regenerated legal sequence at a
meaningful reduction, not more scoring of these initial candidates.

The 48 schedules, topology records, source hashes, and exact settings are in
`out/multi-collapse-interactions-20261116/torus.json`; reproduction code is
`tools/mmgeo/audit_multi_collapse_interactions.py`. No tests were run for this offline diagnostic.
