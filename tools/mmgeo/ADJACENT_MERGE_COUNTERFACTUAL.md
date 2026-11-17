# Adjacent-partition merge utility screen

Date: 2026-11-15. Offline counterfactual study of geometry-only grouping controls.

## Frozen question

The fixed-target QEM control removed the old endpoint restriction. This screen asks whether
actual two-group simplification gains differ enough from elementary boundary/contact scores
to justify a new repair decision mechanism. Inputs are exactly the existing capacity-32 BFS
groups and archived fixed-target outputs; no parameters are fit to candidate outcomes.

Enumerate every pair of groups sharing a source edge within the same material: Torus 138,
Monkey 1,903, Pirate 501. Exhaust the same fixed-target QEM on the union of the original source
triangles of each pair, preserving its outer boundary and coordinates. Record the final geometry,
audits, elapsed Python time, and additional saving relative to the two separately simplified
groups. This builds from source, not from their simplified output. It is a two-group replacement
study, not an incremental simplification from current output or a multi-level hierarchy build.

All outcomes, including negative gains or unsupported merged-patch topology, remain in the
report. A pair can be committed by the simulated policies only if the input/output union patches
are supported with the same chi multiset, the boundary remains fixed, and the gain is positive.
Individual pair audits are insufficient to establish compatibility; selected disjoint pair
outputs are assembled with all untouched group outputs and audited after exact-position welding.
The source geometry is normalized once per asset as in the fixed-target baseline.

## Controls and accounting

Four deterministic policies use the same pair family and tie-break by pair IDs: lexicographic
pair order, shared-source-edge count, normalized shared-vertex score, and a greedy policy ordered
by measured gain per input triangle. The last policy peeks at every outcome and is an offline
diagnostic, not an implementable cheap policy or a globally optimal matching bound. A regression
test includes a matching where that greedy policy is suboptimal.

The normalized contact score is `sharedVertices * (1/sqrt(Va)+1/sqrt(Vb))`. This is a classical
score control inspired by the actual [meshoptimizer partition source](https://github.com/zeux/meshoptimizer/blob/master/src/partition.cpp)
(`pickGroupToMerge`, inspected 2026-11-15). Upstream additionally accounts for spatial bounds,
partition sizes, and agglomerative updates. This experiment is not a faithful full reproduction
or a performance comparison to meshoptimizer; shared-contact grouping itself has direct prior art.

Each query costs the union's **source triangle count**, including a query that fails or gives
no gain. Already-committed groups cannot be queried/committed again. Each policy is simulated
independently at caps of 0.25/0.5/1.0 times the asset source face count. A query that does not fit
the remaining cap is skipped; consequently exact spent work may differ below the same cap and
must be reported. This is a work proxy, not equal measured wall time or equal native construction
cost. The offline gain-greedy policy also requires the full counterfactual table: its total
measurement work/time are reported separately and cannot be hidden by charging only chosen pairs.

No source-distance/attribute/global-intersection gate, image rendering, held-out asset, continuous
camera, production clusterizer or production Corner run is provided. A stitched combinatorial
topology pass does not prove embeddedness or appearance fidelity. A gain over pair order is
insufficient novelty; the decision must outperform elementary contact controls under full gates
and a real matched-cost protocol before promoting a new repair mechanism.

## Execution and checks

```powershell
python tools/mmgeo/probe_adjacent_partition_merges.py out/fixed-boundary-qem-20261115/report.json --out out/adjacent-merge-counterfactual-20261115/report.json
python -m unittest discover -s tools/mmgeo -p test_adjacent_partition_merges.py -v
```

Three targeted tests passed: material/edge adjacency, charging failed queries without committing
them, and the non-optimality of outcome-greedy matching. The original process and subsequent
summary validator both exited 0. All **2,542** adjacent pairs completed. The final `report.json`
and `summary.json` supersede `report.partial.json`. The summarizer checked source/capture/baseline
hashes, exhaustive adjacency coverage, every pair's boundary and fixed coordinates, work/count/gain
accounting, disjoint positive eligible selections, query budgets, and reproduced every assembled
topology audit. Final geometry is retained for every counterfactual, including ineligible ones.

The exhaustive table cost 135,035 source-triangle work units and about 249.21 seconds of Python
measurement/orchestration in this run. Per-asset work/time: Torus 7,576 / 3.97s, Monkey 101,476 /
193.30s, Pirate 25,983 / 51.93s. The diagnostic gain-greedy ordering depends on this upfront table;
its simulated selected-query budget is not its full deployment cost. There were 198 ineligible
union patches (16/145/37) and zero measured negative gains in this development population.

## Complete policy results

Each entry is `output faces / charged query work`. The cap fraction multiplies source face count,
not the previous simplified count. Smaller face counts are meaningful here only when the assembled
topology check passes. **Invalid** entries failed that check and are excluded as valid gains.

| Asset | Cap fraction | Pair order | Shared edges | Normalized shared vertices | Measured gain/work greedy |
|---|---:|---:|---:|---:|---:|
| Torus | .25 | 674 / 256 | 666 / 256 | 668 / 263 | 668 / 263 |
| Torus | .50 | 664 / 545 | 618 / 576 | 620 / 550 | 620 / 550 |
| Torus | 1.0 | 626 / 1123 | 562 / 1128 | 580 / 1134 | 560 / 1130 |
| Monkey | .25 | 9366 / 3925 | 8892 / 3904 | 8916 / 3922 | 8818 / 3909 |
| Monkey | .50 | 9082 / 7854 | 8318 / 7871 | 8406 / 7842 | 8214 / 7871 |
| Monkey | 1.0 | **Invalid** 8430 / 15730 | 7580 / 15726 | 7690 / 15734 | 7550 / 15327 |
| Pirate | .25 | 2812 / 1223 | 2682 / 1223 | 2682 / 1228 | 2624 / 1247 |
| Pirate | .50 | 2678 / 2476 | 2484 / 2490 | 2482 / 2480 | 2426 / 2473 |
| Pirate | 1.0 | 2458 / 5000 | **Invalid** 2244 / 5002 | **Invalid** 2260 / 5001 | **Invalid** 2230 / 4780 |

At the full source-work cap the valid Torus/Monkey shared-edge results differ from the
outcome-informed greedy results by only 2/30 faces (about 0.36%/0.40% of the shared-edge outputs),
despite the latter's access to the exhaustive table. At smaller caps there are differences, but
they do not establish a new implementable predictor or equal-wall-time quality advantage. Torus's
shared-edge policy even beats gain/work greedy at the .25 cap; that is consistent with greedy
matching being non-optimal. Do not report the latter as a universal oracle upper bound.

## Assembly failures and existing safeguards

All four invalid policy cases contain a new duplicate face produced by two independently
simplified disjoint pair blocks. Monkey's conflicting blocks are [494,496] and [499,500]; Pirate's
are [103,123] and [102,125] for all three invalid policies. Each affected assembled component also
has one nonmanifold edge and two invalid vertex links. The coordinate-based duplicate trace is
preserved in `duplicate-diagnosis.json`. These are two distinct geometric motifs, not four
independent failure discoveries. Individual patch manifoldness and unchanged outer boundary sets
do not establish union compatibility.

Follow-up source inspection found that production `Simplifier.cpp::respectsLockedMask()` already
rejects new edges between locked seam positions that were absent in the source unit. Both blocks
in each observed conflict create such new locked-boundary chords in this controlled partition.
The Python control does not implement this full shared-seam contract. This is a known safeguard
and a missing control constraint, not evidence for a new global-compatibility algorithm or a
production ManyMesh defect. A production-faithful follow-up must include the actual seam mask
and candidate backoff/resimplification; a post-hoc filter is not a faithful runtime reproduction.

Decision: generic repair-by-merging and shared-contact scores remain established baselines.
This screen provides no sufficient advantage for a new utility predictor, and the invalid
results cannot be used to inflate gains. Do not promote this branch as a SIGGRAPH mechanism.
The next claim must identify a difference beyond these contact and seam-contract controls and
survive full geometry/attribute gates at genuinely matched construction cost on unseen assets.

```powershell
python tools/mmgeo/summarize_adjacent_partition_merges.py out/adjacent-merge-counterfactual-20261115/report.json --out out/adjacent-merge-counterfactual-20261115/summary.json
```
