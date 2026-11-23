# Exact finite strict-cut frontier oracle (2026-11-19)

## Question

The remaining construction-scheduling hypothesis says rejection-aware or learned scheduling may
improve a complete, strict-valid DAG cut under the same construction-work budget. Before designing
another predictor, I computed an exact finite upper bound over the successful parent nodes already
present in four captured development DAGs. This answers whether those candidate outputs have
schedule headroom at all.

## Oracle definition

For each captured promoted parent, the replay uses its recorded output triangles, accumulated error,
input-triangle-attempt work, and dependency children. A dynamic program recursively enumerates cuts
by choosing either (a) to expose children and combine their frontiers, or (b) to use a promoted
parent after paying for the successful dependency closure needed to build it. For each policy error
cap, it keeps the exact Pareto frontier of construction work versus complete-cut triangle count.
Every retained cut is passed through the existing reconstruction routine; its exact leaf cover,
triangle count, max accumulated-error proxy, and promoted-parent work closure are checked against the
DP state.

The calculation requires the captured graph to have single-parent nodes. All four graphs passed
that condition. Failed groups are skipped with zero work, so the result is an optimistic hindsight
upper bound; it is not a realizable online schedule. Work is the established retrospective proxy
`inputTriangles * observedAttempts`, not wall time or peak memory. Quality is max `accumulatedError`
over the cut, not rendered image error. This oracle says nothing about unsampled candidate groups,
new splits, raster quality, or generalization.

## Results

The exact DP completed for Cloth, Material Sphere, Monkey, and Shapes: 192 policy/budget rows total,
with 4–11 distinct error caps per asset. The largest retained frontier at any cap was 3,917 states
for Cloth, 129 for Material Sphere, 1,030 for Monkey, and 4,312 for Shapes. All states passed the
complete-cut reconstruction checks. The combined run completed in about 50 seconds; observed
Python working set was about 220 MiB, with roughly 5.7 GiB system RAM available during the run.

The table reports the oracle's additional triangle reduction over the frozen quality-aware (`1.0`)
policy, at the same work cap and a max-error cap no worse than that policy's cut:

| Asset | Work budget | Policy triangles | Oracle triangles | Extra reduction |
|---|---:|---:|---:|---:|
| Cloth | 10% | 32,346 | 31,010 | 1,336 |
| Cloth | 20% | 31,516 | 30,350 | 1,166 |
| Cloth | 50% | 30,556 | 30,350 | 206 |
| Material Sphere | 10% | 4,532 | 4,532 | 0 |
| Material Sphere | 20% | 4,180 | 3,972 | 208 |
| Material Sphere | 50% | 3,972 | 3,972 | 0 |
| Monkey | 10% | 11,202 | 10,812 | 390 |
| Monkey | 20% | 7,328 | 7,328 | 0 |
| Monkey | 50% | 5,392 | 5,392 | 0 |
| Shapes | 10% | 54,240 | 53,114 | 1,126 |
| Shapes | 20% | 36,988 | 35,660 | 1,328 |
| Shapes | 50% | 24,462 | 15,452 | 9,010 |

The oracle has substantial room over cost-only and boundary orderings on Cloth and Shapes, but much
less over the already stronger hindsight heuristic on Cloth and over the learned quality-aware
policy on Material Sphere and Monkey. Shapes retains the clearest finite headroom, especially at
50% work. This is useful evidence that scheduling can matter on the captured successful groups; it
does not show that any implementable scheduler can find the oracle cuts before paying for failed or
unknown outcomes.

## Prior-art and novelty boundary

Budgeted mesh cuts are established. For example, *Interactive Rendering* formulates both minimizing
triangles under an error threshold and minimizing error under a triangle budget, with an added node
budget ([paper](https://www.cs.jhu.edu/~misha/ReadingSeminar/Papers/Niski07.pdf)). Therefore the DP
and its finite Pareto frontier are evaluation machinery, not the contribution. A possible research
direction must explain how ManyMesh's strict topology/attribute/geometry gates and unknown parent
outcomes can be scheduled online to approach a useful part of this upper bound at measured work and
memory, while beating fixed-level, cost-only, boundary, and existing DAG2/HLOD-style baselines on
held-out assets and rendered image quality.

This preflight does not clear that bar. It only gives a decision criterion: if a future online policy
cannot close meaningful portions of this finite gap on Shapes/Cloth and generalize without losing on
other meshes, stop this scheduler direction. The learned quality-aware rule already failed the
limited cross-asset benefit gate documented in
[the memory-capped learned synthesis note](LEARNED_MEMORY_CAPPED_DAG_SYNTHESIS_20261119.md).

## Reproduction

```powershell
python tools/mmgeo/audit_exact_cut_frontier_oracle.py --asset all --state-limit 6000 --out out/exact-cut-frontier/all.json
```

The source audit is [audit_exact_cut_frontier_oracle.py](audit_exact_cut_frontier_oracle.py); the
ignored machine-readable result is `out/exact-cut-frontier/all.json`. The earlier unconstrained
three-objective prototype was stopped when its Shapes frontier grew to about 6.5 GiB. The final
implementation fixes one error cap at a time, prunes the work/triangle frontier, and bounds
intermediate states; it completed at about 220 MiB working set. No C++ source or production policy
was changed, and no renderer/build was run.
