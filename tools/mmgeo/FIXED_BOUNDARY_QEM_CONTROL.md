# Fixed-boundary target control

Date: 2026-11-15. Classical baseline improvement, not a new simplification algorithm.

## Frozen comparison

The previous QEM exhaustion control disallowed either collapse endpoint being locked. This
follow-up adds directed interior-to-locked-boundary collapses whose target is exactly the
boundary vertex position. It uses the same three archived captures, 15 partitions, group triangle
IDs, asset normalization, quadrics, placement scoring, regenerated candidate queue, relative face
orientation and triangle-quality tests. The original reference code and original results are
unchanged. The new candidate set can change greedy order; fewer final faces are not assumed.

The control refuses removal or movement of locked vertices and never contracts an edge with
both endpoints locked. An added fixed-target collapse must pass the original local legality
checks and an explicit boundary-edge-set comparison before committing. The experiment also
checks final boundary edges/coordinates and the chi multiset for supported input components.
Output positions, triangles, actions, source face/vertex IDs, counts, and timing are retained.

This is geometry-only. It has no source-distance cap, authored attributes, render comparison,
or global self-intersection check. It is not production Corner, which already has fixed-target
handling. A lower exhausted triangle count alone is not a quality/cost result or a SIGGRAPH
contribution. Unsupported source patches remain reported without a manifoldness guarantee.

## Validation

Three targeted tests passed: a four-triangle disk reaches its two-triangle boundary-preserving
triangulation; locked vertices cannot be removed/moved; and the directed keep/remove roles remain
correct when the locked target has the larger vertex ID. The separate replay validator implements
boundary counting with vectorized sorted edges and checks every committed intermediate state,
then compares replayed coordinates/triangles exactly with the saved final geometry. It does not
call the QEM queue or legality evaluator. Shared-edge and empty boundary counting cases passed.

The code review traced constructor-time dispatch through `push`, directed queue entries,
version invalidation, `legal`, `advance`, and geometry serialization. Single-process execution
has no shared mutable worker state. Changes in keep/remove ordering preserve the version tuple
positions expected by `advance`. Fixed coordinates are checked by exact equality. Tests cover
the index-order reversal that could otherwise silently remove a boundary endpoint. Full input
validation is provided by the archived capture loader and baseline constructor; arbitrary corrupt
or degenerate meshes are not supported by this experiment. Larger Python boundary checks can
increase runtime, which must be reported rather than presented as a speed advantage.

## Commands and artifacts

```powershell
python -m unittest discover -s tools/mmgeo -p test_fixed_boundary_qem_control.py -v
python tools/mmgeo/probe_fixed_boundary_qem.py out/partition-qem-exhaustion-20261115/report.json --out out/fixed-boundary-qem-20261115/report.json
python tools/mmgeo/validate_fixed_boundary_qem.py out/fixed-boundary-qem-20261115/report.json --out out/fixed-boundary-qem-20261115/summary.json
```

Both the original simplification process and the separate replay validator exited 0. The final
`report.json` and `summary.json` supersede the intermediate `report.partial.json`. All 15
partitions completed. Source/capture/baseline hashes are bound in the report; the validator binds
both its own source and the final report hash in the summary. It replayed **34,425** collapses,
checking each intermediate boundary edge set and pinned coordinates and exactly matching all
saved final geometry. Exact face coverage and group/aggregate counts also matched.

| Asset | Capacity | Previous QEM faces | Fixed-target QEM faces | Fraction of source | Python solver seconds |
|---|---:|---:|---:|---:|---:|
| Torus | 32 | 788 | 714 | 61.98% | 0.304 |
| Torus | 64 | 574 | 536 | 46.53% | 0.496 |
| Torus | 128 | 434 | 402 | 34.90% | 0.700 |
| Torus | 256 | 232 | 206 | 17.88% | 1.760 |
| Torus | 512 | 130 | 118 | 10.24% | 7.581 |
| Monkey | 32 | 10,664 | 9,634 | 61.19% | 23.701 |
| Monkey | 64 | 8,110 | 7,492 | 47.59% | 38.805 |
| Monkey | 128 | 6,030 | 5,634 | 35.78% | 55.200 |
| Monkey | 256 | 4,300 | 4,042 | 25.67% | 75.301 |
| Monkey | 512 | 3,002 | 2,860 | 18.17% | 91.435 |
| Pirate | 32 | 3,372 | 2,942 | 58.72% | 8.061 |
| Pirate | 64 | 2,560 | 2,268 | 45.27% | 12.533 |
| Pirate | 128 | 1,940 | 1,686 | 33.65% | 17.310 |
| Pirate | 256 | 1,468 | 1,286 | 25.67% | 22.997 |
| Pirate | 512 | 974 | 860 | 17.17% | 28.988 |

No individual group retained more faces than its archived baseline in this population; this is
an observation, not a monotonicity guarantee for other meshes or greedy orders. The groups
without a verified topology claim remain exactly the unsupported source groups reported in the
earlier audit (Torus 256/512 one each, Monkey 64/128/256/512 one each, Pirate 3/1/6/1/1).
Boundary preservation was nevertheless verified for every operation in all groups. Times are
single Python runs with per-group audit overhead, not a randomized native-speed comparison.

Torus 32, Torus 64 and Monkey 32 reach their full fixed-boundary topological floors exactly
(714/536/9,634). Torus 128 is only two faces above its floor of 400. Therefore the prior excess
counts in these cases can be removed by an ordinary fixed-target operation without hierarchy
repair. The 32-face fixed partitions still cannot reach the 55% target for the two fully
supported assets, while 64-face partitions produce outputs below 55% on all three assets under
this restricted geometry-only model. The latter is no proof of production quality-valid cuts.

Research decision: close **topological-floor scoring plus relaxing the reference endpoint rule**
as an independent novelty route. The counting score is equivalent to interior-vertex counting
on open manifold patches; fixed-target collapse is standard and already reflected in production
Corner. A proposed hierarchy-repair algorithm must now beat this stronger control as well as
production Corner and blind/greedy repairs under full geometry/attribute gates and matched total
construction cost. No current result establishes that advantage or a SIGGRAPH contribution.

Review Summary:
- **The Blocker**: No demonstrated quality/cost or novelty advantage for a new repair mechanism;
  this control only establishes and removes a known reference-operator restriction.
- **Intent vs. Code**: Adds the intended directed fixed-target operations and preserves boundary
  identity/positions through every recorded transition in the frozen population.
- **Explicitly Checked & Ruled Out**: Locked-target index order, stale-version tuple layout,
  boundary endpoint removal/movement, constructor dispatch, incomplete queue exhaustion, source
  changes, partition omissions/duplication, and final-geometry replay mismatch. No concurrency
  is introduced; no public C++ API or production build wiring changes.
- **Minor Cleanups**: None required for this experimental scope. Global intersection, source
  distance, authored attributes and production integration remain outside the control's claims.
