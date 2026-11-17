# Shared-child parent alternatives: geometry and cut audit (2026-11-16)

## Question

Can deterministic ManyMesh DAG builds with different `--dag-group` values produce a useful alternative parent for the exact same child meshes, so a multi-parent DAG could select among the alternatives without changing cut coverage or triangle budget?

## Data and checks

- Audited repeat-1 captures for seven assets across group sizes 2, 4, 8, 16, and 32, all at the same 55% target and source/configuration. The source graph JSON and serialized `.mmb` hashes were checked against their manifests.
- Decoded MMB v7 node records, generated vertices, canonical position IDs, and oriented faces. Cross-checked node links, triangle counts, boundary/topology counters, minimum triangle quality, and stored normal/UV errors against JSON.
- Compared direct child regions and exact child mesh-state hashes, including generated position and appearance data. Parent surface hashes use canonical positions and preserve winding while ignoring triangle order. A separate directed boundary-edge hash checks whether alternatives expose the same interface.
- All six different-surface alternatives were built with `--quality-gate 1`; each also passed the recorded default attribute limits: minimum triangle quality >= 0.02, maximum normal error <= 35 degrees, mean normal error <= 17.5 degrees, mean UV error <= 0.10, and maximum UV error <= 0.80. The native per-build quality gate additionally checked topology, geometry error, and boundaries.

## Results

Across 7 assets, 5 group sizes, and 35 deterministic graphs, source leaf IDs and partitions were stable. There were 1,536 shared immediate-child-region sets. Six sets had identical direct child mesh states but distinct parent surfaces: cloth 1, Pirate 2, and shapes 3. All six had identical undirected and oriented parent boundary signatures across variants.

Every alternative had the same triangle count as its counterpart. The examples with different accumulated errors were:

| Asset / source region | Groups | Parent triangles | Accumulated error |
|---|---:|---:|---:|
| cloth, 2 leaves | 2 / 4 | 136 | 0.0106736 / 0.0106736 |
| Pirate, 2 leaves | 2 / 4 / 8 | 112 | 0.0141240 / 0.0140924 / 0.0140924 |
| Pirate, 4 leaves | 4 / 16 | 284 | 0.00500047 / 0.00539064 |
| shapes, 2 leaves | 2 / 8 | 140 | 0.00115780 / 0.00104429 |
| shapes, 4 leaves | 4 / 8 | 194 | 0.00747724 / 0.00694233 |
| shapes, 8 leaves | 8 / 16 | 386 | 0.00984252 / 0.00906073 |

The saved native 55% cuts for all candidate-bearing assets had exact-once leaf coverage, and their node triangle sums matched the recorded cut totals. Two shapes candidates were selected by their native cuts and could be virtually swapped at equal triangle budget while preserving the same child leaf region, bounds, and directed boundary. Switching shapes group 2 node 1622 to group 8 node 1597 reduced that node's accumulated error by 9.80%. The reverse swap increased it by 10.87%.

The local projected-error ordering follows from identical bounds, but the reconstructed whole-cut maximum screen error did not change: another selected node remained the bottleneck. For shapes group 2, the saved maximum stayed 0.483677 px after the lower-error swap; for group 8 it stayed 0.485730 px. The only native-selected Pirate alternative increased local error by 7.8% and had different bounds, so it did not qualify as a robust screen-error substitution.

## Decision

This establishes a real, small-scale construction opportunity for shared-parent alternatives, with exact source inputs and compatible boundaries. It does **not** establish a useful global quality/budget gain: all alternatives have equal triangle count, only one tested substitution improves local error, and no native cut's maximum screen error improved. Candidate mining itself is not a paper contribution; DAG2 already covers multi-parent DAG construction at a high level.

The targeted novelty check found a closer precedent than DAG2: [Batched Multi-Triangulation (IEEE Visualization 2005)](https://vcg.isti.cnr.it/publication/2005/CGGMPS05/) models general mesh descriptions as fragments that paste over the same floor/domain, requires boundary preservation for conforming mesh pasting, and extracts valid representations from DAG cuts. [Benthin and Peters, HPG 2023](https://diglib.eg.org/bitstream/handle/10.1111/cgf14868/v42i8_04_14868.pdf) separately establish binary DAG2 construction by making split clusters multiple parents of the same children. These precedents make “store multiple same-region parents in a DAG” a poor novelty claim. This was a targeted check, not a complete literature survey.

Keep the local result as a reproducible control, not a SIGGRAPH candidate. Further work is justified only if it tests a distinct mechanism beyond general MT/DAG alternatives; it must target the selected cut's active bottleneck across held-out views/assets, preserve equal budget and construction/memory accounting, and improve whole-cut screen or rendered quality. Stop this line if gains remain local or are offset by build/storage cost. No production C++ changed and no software tests were run.

## Reproduction

```powershell
python -I tools/mmgeo/audit_shared_parent_candidate_reuse.py `
  out/targetbudget-repeat-control-20261116/build_repeats.json `
  out/targetbudget-heldout-20261116/builds.json `
  --out out/shared-parent-candidate-audit-20261116/report_geometry_final.json

python -I tools/mmgeo/audit_shared_parent_cut_substitutions.py `
  out/shared-parent-candidate-audit-20261116/report_geometry_final.json `
  out/targetbudget-repeat-control-20261116/build_repeats.json `
  out/targetbudget-heldout-20261116/builds.json `
  --out out/shared-parent-candidate-audit-20261116/cut_substitutions_final.json
```

The final geometry report binds script SHA-256 `55d4048fef920b8af2af2e762a308dae8a3589925ed6109564adef23ccb4eabe`. Report SHA-256 is `173ec7a0d78f11250b5758ae141d1c1e2099d31adbcc2f86c867be6fd88ba66a`; the cut-substitution report SHA-256 is `46012cdec14fa65e8a1770963aca425a93e6cc1e083b4586165b32d7e283fff1`.
