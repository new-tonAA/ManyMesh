# Controlled fixed-partition boundary floor

Date: 2026-11-15. Source/capture diagnostic; no new simplification algorithm.

The source-contract audit alone had weak bounds and could not isolate the effect of partitioning.
This experiment holds the archived source geometry fixed, partitions triangles by deterministic
face-adjacency BFS within each material, then measures the conditional combinatorial floor with
every partition boundary locked. Capacities 32/64/128/256/512 were evaluated for all three archived
Torus, Monkey, and Pirate captures. Group triangle IDs, complete per-component audits, capture
hashes, and both script hashes are retained in `out/partition-boundary-floor-20261115/report.json`.

The full material-merged floors are Torus 8, Monkey 164, Pirate 398. A valid component's bound is
`F >= B-2chi` for open components, with a loose closed-component bound, as described in
[the topology audit](OBJ_CONTRACT_FLOOR_AUDIT.md). The topology and every boundary edge of each
partition must survive for this floor to constrain an output. This is a conditional necessity,
not a promise that the bound can be attained.

| Asset | Capacity | Groups | Complete conditional floor | Fraction of original | Unsupported components |
|---|---:|---:|---:|---:|---:|
| Torus | 32 | 54 | 714 | 61.98% | 0 |
| Torus | 64 | 29 | 536 | 46.53% | 0 |
| Torus | 128 | 14 | 400 | 34.72% | 0 |
| Torus | 256 | 6 | unavailable | unavailable | 1 |
| Torus | 512 | 4 | unavailable | unavailable | 1 |
| Monkey | 32 | 751 | 9,634 | 61.19% | 0 |
| Monkey | 64 | 414 | unavailable | unavailable | 1 |
| Monkey | 128 | 218 | unavailable | unavailable | 1 |
| Monkey | 256 | 104 | unavailable | unavailable | 1 |
| Monkey | 512 | 51 | unavailable | unavailable | 1 |
| Pirate | 32 | 249 | unavailable | unavailable | 3 |
| Pirate | 64 | 129 | unavailable | unavailable | 1 |
| Pirate | 128 | 81 | unavailable | unavailable | 6 |
| Pirate | 256 | 73 | unavailable | unavailable | 1 |
| Pirate | 512 | 27 | unavailable | unavailable | 1 |

For the two complete capacity-32 cases, a 55% target is impossible under the stated fixed-partition
contract, despite the much smaller bound on the material-merged surface. This is an actual
controlled example of partition-induced obstruction. It does not show that production ManyMesh
has this obstruction: these are BFS partitions without vertex-count caps, spatial compactness,
chart constraints, or the production clusterizer. They also are not nested across capacities,
so the table is not a monotone coarsening sequence or a hierarchy-repair evaluation.

The unavailable results are meaningful: an edge-connected subset of a manifold surface can have
a disconnected vertex link. The full source surfaces pass the audit, while some BFS patches do
not. Such patches cannot inherit the whole-surface manifold assumptions. Report those failures
rather than filling in their bounds. No actual collapse, attribute gate, rendered error, build
time, or end-to-end improvement was measured. Archived captures are not newly source-bound
imports from the current binary.

This narrows the research task: any proposed grouping repair must distinguish partition-boundary
obstruction from other rejection causes and validate local patch topology. Merely enlarging
clusters or unlocking boundaries remains established prior art, including
[clustered HLOD with progressive boundaries](https://doi.org/10.1111/cgf.70380).
The measured obstruction is not a new mechanism or a SIGGRAPH contribution. A useful repair
algorithm still needs a principled choice of repairs and an equal-cost advantage against greedy
grouping/repair and the modern HLOD baseline on held-out inputs.

```powershell
python tools/mmgeo/audit_partition_boundary_floor.py out/filter-real-candidates/torus.json out/filter-real-candidates/monkey.json out/filter-real-candidates/pirate.json --out out/partition-boundary-floor-20261115/report.json
python -m unittest discover -s tools/mmgeo -p test_partition_boundary_floor.py -v
```

The population run exited 0. Three targeted checks passed for deterministic capacity/material
constraints and exact face coverage, an analytic disk partition cost, and invalid-capacity refusal.
