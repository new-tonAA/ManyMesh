# Adjacent-merge control with explicit shared-position contracts

Date: 2026-11-15. Existing seam safeguard reproduced in a geometry-only reference control.

## Question and contract

The earlier [merge counterfactual study](ADJACENT_MERGE_COUNTERFACTUAL.md) included four invalid
assembled policy outputs despite valid individual union patches. The production code already
has a relevant safeguard: `buildLockedMaskContext()` and `respectsLockedMask()` in
`libs/manymesh/src/Simplifier.cpp` retain source locked positions and reject edges between locked
positions that were absent from the source unit. This follow-up evaluates the same pair family
with that explicit contract instead of promoting the missing check as new research.

For a single group or pair of groups, a source position is seam-locked if any original group
outside the current unit references it. Thus a pair removes only its internal interface locks;
all third-party group references still apply. Source ownership is computed from the frozen
original capacity-32 groups. Physical open boundaries remain fixed independently of this mask.
Both endpoints of each new edge are tested by exact source-position identity, not only by vertex
index, so coordinate aliases cannot hide a forbidden locked-position chord.

The reference adds these constraints before initial candidate queuing, allows fixed-target
contractions only when they preserve them, and checks the final locked-position/edge sets. It
rebuilds both all single-group baselines and all 2,542 adjacent-pair counterfactuals from the same
source geometry. Comparing guarded pairs against the old unguarded baseline would be invalid.
Policy choices and work caps are unchanged: pair order, shared edges, normalized shared vertices,
and outcome-informed gain/work greedy at .25/.5/1.0 source-triangle work caps, including failed
query charges. The last ordering still requires the full offline outcome table and is not an
optimal bound or a cheap deployable policy.

This is **not** a faithful end-to-end production reproduction. The grouping is BFS, the positions
are normalized doubles, and no authored attribute, source-distance, quality-backoff, or global
intersection gate is implemented. The Python guard rejects forbidden chords after **each
collapse**, whereas the production shared-mask check is applied to a whole simplification
candidate. A production sequence might transiently create and then remove such an edge, so the
per-collapse reference is potentially more restrictive. It must not be called equivalent to
production Corner. Its purpose is to measure the missing seam constraint under a common rule
for every compared policy.

## Validation and execution

Five targeted tests passed: distinguishing physical borders from seam masks, refusing new seam
chords, retaining a shared interior vertex, invalid mask indices, and detecting new locked edges
through coordinate aliases. Constructor dispatch through the initial queue was traced so that
the outside-owner locks apply before any edge is proposed, and subsequent versioned queue updates
retain the directed fixed-target roles of the prior reference.

The separate validator reconstructs each unit and outside-owner mask from the frozen source,
checks every saved pair and single-group output for boundary/locked coordinates, retained seam
positions and absent new locked-position edges, verifies exhaustive pair coverage, and reproduces
policy work accounting and assembled topology. This validates final geometry for every unit;
it does not independently replay every intermediate operation or establish rendered quality.

```powershell
python -m unittest discover -s tools/mmgeo -p test_seam_contract_qem_control.py -v
python tools/mmgeo/probe_seam_contract_merges.py out/adjacent-merge-counterfactual-20261115/report.json --out out/seam-contract-merges-20261115/report.json
python tools/mmgeo/validate_seam_contract_merges.py out/seam-contract-merges-20261115/report.json --out out/seam-contract-merges-20261115/summary.json
```

Source hashes, captures, the old counterfactual table, and the old baseline are bound in the new
report. The original process and independent validator both exited 0. All 1,054 single groups
and 2,542 adjacent pairs completed. The validator checked all **3,596** saved units and all policy
assemblies. The final `report.json` and `summary.json` supersede `report.partial.json`. No C++
source was changed.

## Complete results

The guarded single-group baselines are Torus 788, Monkey 10,608, and Pirate 3,298 faces. Their
total measured Python simplification/audit time is 71.89 seconds. Exhaustively measuring all
pairs costs the same 135,035 source-triangle work units as before and 581.52 seconds in this
run, before using any outcome-informed ordering. These are single-run Python costs, not native
timing claims. The full offline table cannot be charged as only its selected queries.

Each entry is `output faces / charged query work`. All **36/36** policy/budget combinations now
pass the stitched combinatorial topology check; this does not prove self-intersection freedom
or visual/attribute fidelity. The baseline and all policies use the same new seam contract.

| Asset | Work cap/source faces | Pair order | Shared edges | Normalized shared vertices | Measured gain/work greedy |
|---|---:|---:|---:|---:|---:|
| Torus | .25 | 740 / 256 | 732 / 256 | 736 / 263 | 732 / 256 |
| Torus | .50 | 730 / 545 | 676 / 576 | 680 / 550 | 680 / 550 |
| Torus | 1.0 | 688 / 1123 | 608 / 1128 | 634 / 1134 | 606 / 1130 |
| Monkey | .25 | 10302 / 3925 | 9758 / 3904 | 9792 / 3922 | 9662 / 3927 |
| Monkey | .50 | 9974 / 7854 | 9104 / 7871 | 9206 / 7842 | 8982 / 7845 |
| Monkey | 1.0 | 9228 / 15730 | 8290 / 15726 | 8434 / 15732 | 8250 / 15074 |
| Pirate | .25 | 3158 / 1221 | 3000 / 1223 | 3006 / 1228 | 2924 / 1238 |
| Pirate | .50 | 3004 / 2477 | 2788 / 2490 | 2792 / 2480 | 2686 / 2503 |
| Pirate | 1.0 | 2776 / 4996 | 2516 / 4998 | 2534 / 5002 | 2454 / 4958 |

At the full source-work cap, the outcome-informed greedy saves only 2, 40, and 62 faces relative
to shared-edge ordering (0.33%, 0.48%, and 2.46% of that ordering's output). Spent work differs
below the caps, especially Monkey gain-greedy, so these are common-cap comparisons, not exact
matched-query-work or equal-wall-time results. The outcome-greedy matching is still non-optimal;
at Torus's .50 cap it is worse than shared edges. All measured pair gains are nonnegative in
this development population, not a general monotonicity guarantee.

The 32-face partitions' fixed boundaries continue to obstruct large reductions, but a standard
contact-driven merge already captures much of the observed two-group benefit. Reproducing an
existing seam rule removes the four earlier assembly failures in this cohort. This supports
the safeguard's relevance and corrects the control; it establishes no new compatibility method.

**Decision:** the evidence does not justify promoting generic two-group utility prediction,
topological counting, shared-contact scores, or the existing seam chord guard as the SIGGRAPH
contribution. Close this geometry-count-only predictor prototype rather than tuning its scores
on the same three assets. A future repair mechanism needs an explicit difference in full
geometry/attribute-valid construction, measured on held-out inputs at real matched build cost.
The geometry-only controls remain reusable evidence, not a submission-ready algorithm.
