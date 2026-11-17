# Bounded candidate evaluation: stop/go experiment

Date: 2026-11-14. Established partial-distance / branch-and-bound principle, NOT a novelty claim.

## Exact problem being tested

Fixed camera, fixed sampled depth/coverage renderer, frozen pool of legal initial Corner
placements, conservative support-conflict invalidation. Compare FULL cumulative image evaluation
with a blockwise partial-sum lower bound. Both must choose the same sequence of six collapses,
not merely attain similar average error. Assets and views are the existing development trajectory.
This is not an unseen-asset, PBR, continuous-image or general online topology result.

For candidate change d with filtered support R and current residual r relative to original:

    deltaE = sum_R (r+d)^2 - sum_R r^2
    lower(B) = sum_B (r+d)^2 - sum_R r^2,  B subset R.

Output blocks are disjoint; each evaluates its own input filter halo. The first term is a sum of
nonnegative terms, so lower(B) <= deltaE. The negative old-energy term is required: later operations
can cancel previous residuals. Prune only when lower exceeds the best fully evaluated deltaE plus
an explicit numerical margin. A margin is not outward-rounded interval arithmetic; results claim
sampled numerical agreement, not a formal floating-point certificate.

Block order is fixed center-first, candidate order is original Corner priority; neither reads
candidate reference error. The first incumbent is fully evaluated. The final policy is checked
against exhaustive operation IDs. A mismatch is a failure, not silently accepted near-equivalence.

## Costs counted

Candidate fragment transactions are still created before block evaluation. Blocks add repeated
halo resolution/filtering and Python dispatch. Cache setup is included in total policy timing.
Report candidate counts, pruned count, blocks evaluated, total runtime and actual committed output.
Less evaluated blocks without lower total cost is a negative result.

## Initial result: prune count does not imply speed

All 18 real asset/view collapse sequences matched exhaustive selection. Torus/Monkey/Pirate
pruned 1200/1314, 1465/1613, 1440/1573 candidate evaluations respectively, and evaluated only
2649/17090, 2552/11171, 2142/10960 output blocks. Nevertheless total policy speed ratios were
0.939x / 0.975x / 0.953x: all slower. The full candidate transaction had already been built,
while overlapping halos and repeated dispatch added work. This is a negative implementation result.

One targeted final revision (`--lazy-fragments`) resolves only requested output halos, excluding
changed old faces and rasterizing replacement triangles clipped to the halo. Only the winner gets
a full transaction for commit. Tests compare on-demand and prebuilt-transaction outputs. The real
asset run completed: all 18 operation sequences still match exhaustive evaluation, but total
speed ratios are 0.903x / 0.864x / 0.897x for Torus / Monkey / Pirate. It is slower than both
exhaustive and prebuilt-transaction pruning. Artifacts: `out/bounded-lazy-pilot/summary.json`.

**Stop decision:** discontinue this Python blockwise pruning implementation as the proposed
main algorithm. This does not disprove a different native implementation, but there is no
measured quality-cost advantage supporting expansion. The mathematical lower bound and tests
remain reusable correctness references. High pruning rate is not an algorithmic speedup, and
ordinary branch-and-bound does not establish novelty.

## Tests

- Nonzero prior residual and several block sizes match full loss.
- Early lower bounds do not exceed exact loss.
- Error-canceling operation has negative deltaE and must not be pruned by a zero incumbent.
- Existing seven transaction tests and seven depth tests remain required.

## Prior-work boundary

Image-Driven Simplification already uses lazy dirty-edge evaluation. Appearance-Preserving
Simplification describes estimated costs and guaranteed error checks/requeue. Ordinary lower-bound
pruning is not a new algorithm. The narrow question is whether this particular sampled/filter-aware
local evaluation has useful quality-preserving cost behavior. A positive result would still need
mechanism-specific novelty investigation; a negative cost result stops this implementation route.

Sources:
- https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf
- https://pages.jh.edu/dighamm/version2/research/2000_11_appearance_preserving_simplification.pdf

Command template:

```sh
python -I tools/mmgeo/simplify_with_fragment_cache.py out/fragment-transactions-cost-audit/torus.json out/filter-real-candidates/torus.json --bounded --out out/bounded-collapse-pilot/torus.json
```
