# Complete cut topology and budget audit

The [upstream cluster LOD comparison](../mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md)
reported five ManyMesh cut failures with the local quality gate enabled.
This follow-up identifies their origin in the saved hierarchies and checks
which of those hierarchies contain an alternative under the same face cap.

## Evidence and scope

The 2026-11-18 ManyMesh binary rebuilt the same eight position-only Thingi10K
assets and saved its complete DAG. The first upstream depth sets each face cap.
For every asset, the selected nodes cover exactly the source leaves and the
serialized leaf triangles match the source. The audit reproduces the runtime's
canonical-position face deduplication, then compares oriented triangle
multisets with the exported PLY. Seven comparisons match exactly. Asset 100894
requires a one-to-one reconciliation of six vertex positions within two float32
units in the last place. Its largest absolute coordinate difference is
`2.22e-16` in the scaled export coordinates. The reconciled assembly and PLY
match on the full triangulation and welded edge incidence.

The same release target was built from worktree HEAD
`2d417cacdeb545a13e6bfb7192310191e60670d6` and the existing diagnostic edits.
MSVC built `mmgeo.exe` successfully and reported warnings for unused compiler
and linker options. Windows application control refused child process creation
with `WinError 4551`. The receipt pins the three modified source files, the
source diff, and the executable. Current source still traverses the selected node
cover and deduplicates faces in `selectionFromCut` without an assembled-edge
check. The measured results below come from the historical binary.

## Where the edge failures occur

The failing cuts contain 688 nonmanifold edges. Of these, 676 (98.3%) are
absent from the source and receive faces from multiple selected nodes. On
44710, nodes 41 and 42 each contribute two oppositely oriented faces to each
of two new edges. Each of those edges is locally valid in each node and
nonmanifold in the assembled cut, where it has four incident faces. No faces
are removed by deduplication in that example.

Refining every selected node incident to a bad edge produces an edge-valid
cut on all five affected assets. All five then exceed their original face
caps. These checks concern edge incidence, winding, and the source boundary.
They do not certify vertex links or the absence of self-intersections.

## Feasible cuts at the same face caps

A mixed integer model selects a disjoint cover of the saved leaves. It rejects
zero-area faces and duplicate position triangles, preserves directed source
boundary edges, and permits each other edge to be absent or used twice with
opposing directions. It minimizes the number of faces first. When it finds
a feasible cut inside the cap, a second solve minimizes the source-face-weighted
mean accumulated geometric error under that cap. Both objectives use only the
saved graph. The second solver has no access to the measured views or image
errors. Independent checks verify each resulting leaf cover and assembled mesh.

| Thingi10K asset | Upstream depth 1 face cap | Nonmanifold edges in native cut | Faces after incident-node refinement | Minimum feasible faces in saved graph | Error objective cut faces |
|---|---:|---:|---:|---:|---:|
| 90431 | 368 | 0 | 392 | 392 | — |
| 263198 | 226 | 0 | 140 | 108 | 140 |
| 44710 | 1,586 | 2 | 1,690 | 1,178 | 1,586 |
| 191968 | 530 | 0 | 408 | 238 | 408 |
| 383021 | 6,894 | 31 | 7,980 | 5,404 | 6,894 |
| 100894 | 2,910 | 8 | 4,114 | 3,278 | — |
| 257594 | 17,222 | 320 | 22,408 | 16,766 | 17,222 |
| 94990 | 13,598 | 327 | 20,546 | 16,118 | — |

HiGHS certified optimality under this model for all eight minimum-face
solves and all five error objective solves. Feasible cuts improve the count of
assets that pass the edge check and face cap from 2/8 to 5/8. All five scored
cuts have higher LDR-FLIP than the stock upstream cluster LOD cuts using the
same protocol. On the three assets with exactly matched face counts, the
ManyMesh cut has mean LDR-FLIP **+0.02300** and mean PSNR **−19.82 dB** relative
to upstream. This is a descriptive comparison of three development assets.
The error objective is a geometric proxy and does not bound the best
possible image quality of any feasible saved cut.

This diagnoses a correctness gap in the tested selection path. Replacing that
selection with offline constrained optimization gives valid cuts where the
graph has enough budget headroom, with lower image quality than upstream on
these assets. It does not establish a research contribution. The three
infeasible caps apply to the saved graph and the no-duplicate contract of the
model. A different builder could change that frontier.

The [rendered reranking follow-up](SAVED_CUT_VIEW_RERANK_20261122.md) scores
44 valid cuts from these graphs. Fitting on rendered views improves the
held-out LDR-FLIP on two assets, while the best cut in the measured pool
for each of the five feasible assets still loses to upstream.

## Reproduce

Use the [upstream receipt and dependencies](../mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md).
Run from the repository root.

```powershell
python tools/mmtrain/compare_manymesh_clusterlod.py --manifest out/thingi10k-metadata/meshes/download_manifest.json --upstream-receipt out/upstream-clusterlod/validation/receipt.json --mmgeo out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe --out out/upstream-clusterlod/historical-full-witness --write-dag
python tools/mmgeo/audit_cut_edge_witnesses.py --receipt out/upstream-clusterlod/historical-full-witness/receipt.json --upstream-dir out/upstream-clusterlod/validation --out out/upstream-clusterlod/historical-full-witness.json
python tools/mmgeo/audit_manifold_cut_feasibility.py --receipt out/upstream-clusterlod/historical-full-witness/receipt.json --upstream-dir out/upstream-clusterlod/validation --out out/upstream-clusterlod/historical-cut-oracle.json
```

The [combined receipt](historical_cut_topology_audit_20261122.json) records
the build identities, matched artifact hashes, specific offending edges, node
ownership, solver timings and status, and per-view image quality.
