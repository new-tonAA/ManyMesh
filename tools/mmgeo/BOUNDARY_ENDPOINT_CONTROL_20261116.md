# Fixed-boundary endpoint QEM control

Date: 2026-11-16. This is a classical control, not a novelty claim.

## Question

The archived geometry-only `ProgressiveQEM` refuses an edge when either endpoint is locked. That
prevents an interior vertex from collapsing into a boundary vertex, even if the boundary vertex
stays fixed and every boundary edge remains unchanged. This control removes that extra restriction
while retaining the reference solver's link, duplicate-face, orientation, and triangle-quality
checks. Each accepted boundary collapse keeps the boundary endpoint at its original position and
is additionally rejected if the exact boundary edge set would change.

## Frozen inputs and result

The run uses capacity-32 groups from
`out/partition-qem-exhaustion-20261115/report.json`, with capture SHA-256 checks enforced by the
script. It topology-checks each group before and after simplification, verifies fixed boundary
positions and exact boundary-edge equality, and compares component Euler-characteristic
multisets. Only groups whose input topology audit is complete are included below; unsupported
groups remain excluded.

| Asset | Checked groups | Previous locked-endpoint QEM | Fixed-boundary endpoint QEM | Conditional floor | Groups at floor |
|---|---:|---:|---:|---:|---:|
| Torus | 54 / 54 | 788 | 714 | 714 | 54 / 54 |
| Monkey | 751 / 751 | 10,664 | 9,634 | 9,634 | 751 / 751 |
| Pirate | 246 / 249 | 3,300 | 2,880 | 2,864 | 241 / 246 |
| **Total** | **1,051 / 1,054** | **14,752** | **13,228** | **13,212** | **1,046 / 1,051** |

The endpoint-permitting control removes 1,524 additional triangles (10.3% of the checked old-QEM
output). The five Pirate groups above the conditional floor have a total gap of 16 triangles; the
largest individual gap is six. These are local geometry-only results, not a source-distance,
self-intersection, attribute, or rendered-quality guarantee. The 7.16 s solver time is Python
research-kernel time, not a production build-cost comparison.

## Decision

This falsifies the interpretation that most capacity-32 QEM exhaustion was evidence of an
unavoidable hierarchy or partition floor. The reference's endpoint lock was the dominant cause in
these supported groups. A follow-up action audit replayed the accepted endpoint actions and checked
them against the production source guard. `CornerSimplifier.cpp` can choose a fixed border/locked
target, but with `lockBorder` enabled it also rejects a collapse into a border target if any face
incident on the removed vertex does not contain that target. All 2,099 boundary-target actions in
the permissive Python sequence violate that guard. Thus production has fixed-target placement but
does not admit these same operations under its current border precheck. The action audit is recorded
in `out/boundary-endpoint-action-audit-20261116-v3/report.json`. A second, explicitly approximate
check used cross-group source-vertex reuse as a proxy for the production locked mask: 2,030 of the
2,099 target vertices were shared, and 2,023 of those actions would still hit the source
locked-chord precheck if the fan guard were removed. Only 76 recorded actions avoid both the fan
rejection and that approximate chord check (69 unshared targets, seven shared targets without a
detected chord). The frozen BFS partition is not the exact production leaf/group structure, so
these are diagnostic counts, not a production prediction.

The follow-up [shared-chord control](probe_boundary_endpoint_qem_shared.py) reran simplification
with that proxy locked mask and the locked-target chord condition, while retaining the exact
boundary-edge and pinned-position contract. It produced 14,630 triangles versus the 14,752
locked-endpoint baseline:

| Asset | Previous locked-endpoint QEM | Shared-chord proxy QEM | Additional removal |
|---|---:|---:|---:|
| Torus | 788 | 788 | 0 |
| Monkey | 10,664 | 10,610 | 54 |
| Pirate | 3,300 | 3,232 | 68 |
| **Total** | **14,752** | **14,630** | **122 (0.83%)** |

This is still a geometry-only proxy experiment and does not enforce Corner's fan precheck or its
attribute/surface gates. Its small gain weakens the idea that merely relaxing that fan rule will
provide a substantial contribution. Report:
`out/boundary-endpoint-shared-lock-control-20261116-v2/report.json`.

The Python result is still not a new algorithm and does not establish a production-quality result:
it lacks Corner's seam-chord, UV/normal, source-surface, and higher-level quality checks. Do not
promote hierarchy repair based on the old-QEM gap. A narrower candidate is to replace the blanket
fan rejection with an incremental exact-boundary certificate plus the existing locked-chord and
attribute gates. This is now low priority: the geometry-only shared-chord control gains only 122
faces on these inputs. Boundary-aware simplification also has substantial prior art, and no
SIGGRAPH novelty is established.
The archived Windows executable was denied by Application Control, so this action comparison is
not a production replay.

## Reproduction

```powershell
python tools/mmgeo/probe_boundary_endpoint_qem.py `
  out/partition-qem-exhaustion-20261115/report.json `
  --capacity 32 `
  --out out/boundary-endpoint-control-20261116/report.json
```

The report binds the frozen input, script, and per-capture hashes. Script:
`tools/mmgeo/probe_boundary_endpoint_qem.py`. Result:
`out/boundary-endpoint-control-20261116/report.json`.
The source-guard comparison is reproduced by `tools/mmgeo/audit_boundary_endpoint_actions.py` and
its hash-checked frozen output is `out/boundary-endpoint-action-audit-20261116-v3/report.json`.
The shared-chord proxy control is reproduced by
`tools/mmgeo/probe_boundary_endpoint_qem_shared.py` with the partition report and `--capacity 32`.
