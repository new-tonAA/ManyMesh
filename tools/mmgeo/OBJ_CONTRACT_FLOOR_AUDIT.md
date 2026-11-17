# Source OBJ topology and conditional face-count floor

Date: 2026-11-15. Diagnostic evidence for the SIGGRAPH research screen. Updated to schema 2:
winding conflicts are reported independently and do not invalidate the Euler bound.

## Why this was measured

Hierarchy repair can only help if the requested cut is not already excluded by the asset
contract. Earlier Pirate/Lucy pilots did not separate a hierarchy limitation from the intrinsic
cost of preserving disconnected components, material partitions, and open boundaries.
This audit reads source OBJ files directly because Windows Application Control denies the
current mmgeo executable, including its explicitly approved elevated invocation.

## Model and derivation

For a connected simplicial 2-manifold, with V vertices, E edges, F triangles, and B boundary
edges, `3F=2E-B` and `chi=V-E+F`, hence `F=2V-B-2chi`.
If the output preserves all boundary edges and chi, its boundary has B distinct vertices, so
`F >= B-2chi`. A closed simplicial 2-manifold needs at least four vertices; a deliberately loose
bound is `F >= max(4,8-2chi)`. These are standard counting identities, not a novel method.
For context, see the [CGAL surface simplification manual](https://doc.cgal.org/5.2.4/Surface_mesh_simplification/index.html)
and [Euler-characteristic triangulation notes](https://static1.squarespace.com/static/5aff705c5ffd207cc87a512d/t/5c950a447817f75bd2262096/1553271370324/Topology.pdf).

The script welds identical float32 positions, forms both a global partition and a partition by
OBJ material, and separates connected components. Every vertex link must be a connected cycle
or boundary path. Degenerate-index triangles, duplicate faces, or edges with more than two incident
faces make a component unsupported. Winding conflicts and orientability are separate diagnostics;
the Euler bound applies to nonorientable manifolds too. A dual-graph parity solve reports whether
consistent winding is possible, and the minimum number of face flips within each dual component
when it is possible. No input geometry or attributes are modified. See also the
[CGAL orientation documentation](https://doc.cgal.org/6.1/Polygon_mesh_processing/index.html).
Unsupported components
receive no floor; the whole-asset complete floor becomes null. Summing supported components is
reported separately and must not be mistaken for an exact minimum.

OBJ polygons are triangulated by an abstract fan. This reproduces their combinatorial disk
counts only when they are simple valid polygonal faces; it is not Assimp's triangulation or a
geometric embedding check. UV/normal wedges and OBJ object/group-to-Assimp-submesh conversion
are not reproduced. In particular, material boundaries are only a conditional fixed-boundary
contract here. Even supported components have no geometric-error or attribute guarantee.

## Complete population

All eight are local development assets. None is claimed as a previously untouched held-out
asset. Input SHA-256 and the executed script SHA-256 are bound in
`out/obj-contract-floor-20261115-v3/report.json`; per-component counts and failure reasons are retained.
The schema-1 report remains archived, but its orientation-based unsupported classification is
superseded. It must not be used to exclude Pirate from a manifold-input subgroup.

| Asset | Abstract fan triangles | Material components | Unsupported components | Complete conditional floor |
|---|---:|---:|---:|---:|
| Torus | 1,152 | 1 | 0 | 8 |
| Monkey | 15,744 | 3 | 0 | 164 |
| Cloth | 74,976 | 5 | 1 | unavailable |
| Sphere | 8,064 | 1 | 0 | 252 |
| Thin glass | 12 | 1 | 0 | 4 |
| Pirate | 5,010 | 18 | 0 | 398 |
| Lucy | 33,446 | 1 | 0 | 8 |
| Shader ball | 67,832 | 9 | 0 | 1,402 |

Cloth's unsupported 2,854-triangle component has 13 invalid vertex links in this representation.
Its supported components sum to 264. Pirate has four material components with 8/18/8/26
locally inconsistent edge orientations, containing 264/192/264/456 triangles respectively.
All 18 material components are orientable; the parity solve finds a consistent orientation with
298 abstract triangle flips in total. This number concerns fan triangles, not original OBJ polygons;
it does not justify automatically changing authored winding or normals. Without material partitions,
Pirate has 12 components and a conditional floor of 290. These are source-representation findings, not proof that
Assimp or ManyMesh produces the same defects. Polygon-fan and welding assumptions must be checked
against an authorized imported-mesh export before making a production correctness claim.

## Decision and limits

The simple topological bounds do not certify the previously requested 55% budget as impossible.
They also do not prove it attainable: lower bounds provide no construction, and geometry,
attributes, chart/submesh locks, embeddedness, and allowable collapse sequences can raise the
actual minimum. No inference that hierarchy repair is the cause or solution follows from a
large gap between a loose lower bound and a current root cut.

Source inspection also limits how these bounds can be used: `TopologyStats` has no Euler,
connected-component, or vertex-link field. `topologyAcceptable()` in `Simplifier.cpp` rejects
duplicates, degenerates, face-vs-corner-normal flips, increased nonmanifold-edge counts, increased
boundary-edge counts, and insufficient triangle quality. The raw and welded measurements count
undirected edge uses. `flippedTriangles` is a geometric normal test, not an adjacent-face winding
consistency test. Boundary-set preservation is a separate check and is bypassed for source units
larger than `attributeQemMaxTriangles`. Corner's candidate evaluator separately checks common
neighbors and incident-edge triangle counts. These source facts do not prove an actual accepted
topology violation, but they mean the full conditional contract of this audit cannot be inferred
from the shared quality-gate histogram. Each simplification backend needs its own evidence.

Audit the actual imported input of every new hierarchy experiment before interpreting rejection
counters. Report winding separately from vertex/edge manifoldness; keep Cloth's unsupported
component in the population. Any topological impossibility claim needs an explicit preserved
contract verified on the committed geometry, beyond the existing aggregate counters.
This audit provides no new simplification algorithm, native timing, or SIGGRAPH contribution.

## Archived imported-geometry cross-check

The existing `out/filter-real-candidates/{torus,monkey,pirate}.json` captures include all initial
Corner triangles after the import path in `src/capture_candidates.cpp`, not just the selected
collapse candidates. That tool uses the same Assimp triangulate/join/pretransform flags as mmgeo,
and captures submeshes independently. Reading those arrays is a data audit, not a new native run.
`--format capture` now audits their actual triangle connectivity without OBJ fan triangulation.

All three archived captures have the same global and material-partition component counts and
conditional floors as the source-OBJ audit: Torus 1/1 components with floor 8/8; Monkey 3/3
with 164/164; Pirate 12/18 with 290/398. This comparison does not establish identical diagonal
choices or an identical complete imported mesh. Captures bind geometry by their file hashes but
do not establish the current executable's importer behavior, all source dependencies, or normals.
Do not use them as fresh, source-bound results. The report and executed script hash are in
`out/capture-contract-floor-20261115-v2/report.json`.

## Execution and checks

```powershell
python -I tools/mmgeo/audit_obj_contract_floor.py assets/models/torus/torus.obj assets/models/monkey/monkey.obj assets/models/cloth/cloth.obj assets/models/sphere/sphere.obj assets/models/thinglass/thinglass.obj third_party/meshoptimizer/demo/pirate.obj third_party/models/lucy/lucy.obj third_party/models/shader_ball/shader_ball.obj --out out/obj-contract-floor-20261115-v3/report.json
python -I tools/mmgeo/audit_obj_contract_floor.py --format capture out/filter-real-candidates/torus.json out/filter-real-candidates/monkey.json out/filter-real-candidates/pirate.json --out out/capture-contract-floor-20261115-v2/report.json
python -m unittest discover -s tools/mmgeo -p test_obj_contract_floor.py -v
```

The schema-2 population runs exited 0. Eleven targeted tests passed, including a repairable winding
conflict and a nonorientable Moebius strip whose Euler bound remains valid, plus tetrahedron,
disk, annulus, pinches/duplicates, nonmanifold edges, partitioning, partial-population refusal,
capture cross-unit welding/material separation, and invalid capture-index rejection. Both reports'
script hashes and all eight OBJ / three capture hashes were checked against current files.
No C++ was changed or built.
