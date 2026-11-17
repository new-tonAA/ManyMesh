# Frozen partition QEM exhaustion

Date: 2026-11-15. Geometry-only control using the existing Python ProgressiveQEM reference.

## Purpose and frozen scope

The earlier [partition floor study](PARTITION_BOUNDARY_FLOOR_PREFLIGHT.md) supplied necessary
counting bounds but no simplification outcomes. This follow-up uses exactly the same archived
captures, group triangle IDs, and capacities 32/64/128/256/512 for all Torus/Monkey/Pirate groups.
The capture, frozen-partition report, QEM implementation, audit implementation, and experiment
script are bound by SHA-256. It is not a current ManyMesh execution or equal-native-build-cost study.

All positions use one source-asset normalization per asset. Every group is compacted to its
referenced vertices, then the unchanged reference QEM is advanced toward zero until its queue
is exhausted. This avoids choosing a different target for favored groups. Output positions,
triangles, exact source face/vertex IDs, counts, rejections, Python elapsed times, and topology
audits are retained. Every group's output must preserve its boundary edge set and the original
positions of boundary vertices. Supported input/output components must retain their chi multiset
to be included in the checked-topology subgroup. Unsupported inputs are run and reported without
claiming the conditional bound applies to them.

## Operator restriction and meaning of the bound

This reference's `push()` refuses an edge if **either** endpoint is locked. It cannot contract an
interior vertex into a locked boundary vertex, even when this could preserve all boundary edges.
Corner's production behavior is different: it can keep a fixed target under local checks. A gap
between this QEM's exhausted count and the topological bound is not evidence that no other legal
simplifier can improve it, nor that production Corner has the same limitation. No attributes,
source-distance ceiling, authored normals, UVs, self-intersection check, or rendered error is used.

There is also no new information in the open-manifold counting score by itself:

`F = 2Vi + B - 2chi`, so `F - (B - 2chi) = 2Vi`.

Thus the optimistic removable-face count derived from this loose bound just counts interior
vertices. It cannot be presented as a new repair-utility predictor. For the particular reference
operator, a stronger elementary bound is `Fout >= Fin - 2(Vi-Ci)`, where Ci is the number of
components of the initial interior-vertex edge graph: edge contractions within that graph cannot
remove its last vertex in a component, and every allowed collapse removes two faces. This is an
operator-specific counting bound, not a new simplification method. A four-triangle disk with one
interior vertex demonstrates the distinction: its fixed-boundary topological floor is two, but
this QEM has no eligible edge and remains at four.

## Execution and results

The original process completed all three assets and 15 partitions and exited 0. Final artifacts
are `out/partition-qem-exhaustion-20261115/report.json` and `summary.json`. The intermediate
`report.partial.json` is preserved but is superseded by the final result. The summary verified
current script/capture hashes, exact input-face coverage, aggregate output counts, exhausted queues,
and the operator-specific bound for every group in the topology-checked subgroup. Boundary edge
sets and pinned coordinates were checked during the experiment. No additional whole-pipeline
quality guarantee follows from these checks.

| Asset | Group capacity | Actual triangles | Fraction of source | Python solver seconds | Topology-unverified groups |
|---|---:|---:|---:|---:|---:|
| Torus | 32 | 788 | 68.40% | 0.285 | 0 |
| Torus | 64 | 574 | 49.83% | 0.505 | 0 |
| Torus | 128 | 434 | 37.67% | 0.689 | 0 |
| Torus | 256 | 232 | 20.14% | 3.361 | 1 |
| Torus | 512 | 130 | 11.28% | 7.914 | 1 |
| Monkey | 32 | 10,664 | 67.73% | 20.454 | 0 |
| Monkey | 64 | 8,110 | 51.51% | 34.975 | 1 |
| Monkey | 128 | 6,030 | 38.30% | 55.960 | 1 |
| Monkey | 256 | 4,300 | 27.31% | 71.008 | 1 |
| Monkey | 512 | 3,002 | 19.07% | 89.960 | 1 |
| Pirate | 32 | 3,372 | 67.31% | 7.268 | 3 |
| Pirate | 64 | 2,560 | 51.10% | 12.444 | 1 |
| Pirate | 128 | 1,940 | 38.72% | 17.877 | 6 |
| Pirate | 256 | 1,468 | 29.30% | 23.942 | 1 |
| Pirate | 512 | 974 | 19.44% | 28.548 | 1 |

Times are one Python control run with normalization and output orchestration outside the group
solver timer; they are not randomized timing confidence intervals or native HLOD construction
costs. The topology-unverified counts match unsupported input patches in the frozen audit.

For the four wholly supported cases, the stronger locked-endpoint bound explains most of the
remaining faces:

| Case | Fixed-boundary topological floor | Locked-endpoint operator floor | Actual exhausted count |
|---|---:|---:|---:|
| Torus 32 | 714 | 786 | 788 |
| Torus 64 | 536 | 574 | 574 |
| Torus 128 | 400 | 418 | 434 |
| Monkey 32 | 9,634 | 10,642 | 10,664 |

Decision: the loose topological bound alone is not a novel repair-utility mechanism, and this
control cannot attribute stagnation to hierarchy construction. Before judging a repair policy,
the comparison must include a classical simplifier that permits a legal interior-to-fixed-boundary
collapse, with boundary sets/coordinates and local topology verified. Otherwise improvement may
only remove the reference solver's extra endpoint restriction. Production Corner already has
fixed-target handling, so a Python baseline improvement would not itself be a new contribution.
Keep the global-build-budget repair hypothesis open only for a new mechanism and a measured
advantage over those controls; these results do not establish SIGGRAPH novelty or quality.

```powershell
python tools/mmgeo/probe_partition_qem_exhaustion.py out/partition-boundary-floor-20261115/report.json --out out/partition-qem-exhaustion-20261115/report.json
python -m unittest discover -s tools/mmgeo -p test_partition_qem_exhaustion.py -v
python tools/mmgeo/summarize_partition_qem_exhaustion.py out/partition-qem-exhaustion-20261115/report.json --out out/partition-qem-exhaustion-20261115/summary.json
```

Three targeted tests passed: a reference-operator stop above the topological floor, winding
independence of boundary counts, and refusal of an inconsistent frozen floor. The operator-specific
bound was separately checked on an analytic disk and a single triangle. No C++ was changed.
