# Mixed-Group Cut Frontier Screen (2026-11-17)

## Question

Can patches from separately built `--dag-group` graphs be mixed over a common source-leaf
partition to improve an equal-triangle-budget cut, and does the improvement survive geometry
assembly and a multi-view image-space check?

This is a candidate-pool headroom experiment. It is not a new runtime cut builder, and the
screen-space sphere-error objective is not a perceptual image metric.

## Method and validation

`audit_mixed_group_cut_frontier.py` builds a binary set-partitioning MILP over nodes from the
five repeat-1 graphs in `out/targetbudget-heldout-20261116/builds.json`. Every candidate node
covers a source-leaf region; selected regions must cover all leaves exactly once, and the
selected triangle count must stay within the smallest native cut's triangle budget. Candidate
patches are dominated only within the same region, oriented boundary signature, material, and
submesh. The objective minimizes the worst auto-framed projected sphere error.

`audit_mixed_group_cut_geometry.py` recreates this repository's Assimp OBJ source-vertex order,
checks all base-leaf triangles against the source, validates every JSON/MMB pair, and verifies
the reconstructed native g2 cut against the saved PLY. Native PLY position signatures match at
1e-6 world-unit precision; Shapes has a maximum matched coordinate delta of 1.19e-7, and its
normal/UV/material/submesh face attributes also match. Material Sphere positions match exactly,
but 914 native faces differ in normal/UV attributes; its raster result is therefore interpreted
only as binary coverage plus first-hit depth.

The mixed geometry is assembled into PLY, then `audit_crossasset_visibility.py` evaluates a
fixed 16-azimuth orbit at 256x256, 2x supersampling, Gaussian sigma 0.9. This metric is binary
coverage plus normalized first-hit depth, not shaded appearance. The new `--triangle-budget`
option permits different face counts under one shared upper bound.

## Results

| Asset / cut | Triangles | Mean filtered total SSE | Worst-view SSE | Result |
|---|---:|---:|---:|---|
| Shapes mixed, groups 2/4/8/16 | 40,538 | 0.000079735 | 0.000553698 | Best in tested budget set; 16/16 views beat g16 |
| Shapes native g16 | 40,550 | 0.000094798 | 0.000576297 | Best eligible fixed-group cut in the existing 16-view sweep |
| Shapes native g8 | 40,550 | 0.000097153 | 0.000574194 | Worse than mixed |
| Shapes native g2 | 40,550 | 0.003067094 | 0.026443765 | Much worse than mixed |
| Shapes mixed, groups 2/16 only | 40,524 | 0.000094045 | 0.000559438 | 0.8% mean-SSE gain over g16; 7 wins, 1 tie, 8 losses |
| Material Sphere mixed, groups 2/4 | 5,152 | 6.789020 | 10.680644 | Worse than every native cut; loses 16/16 views to g32 |
| Material Sphere native g32 | 5,186 | 4.274621 | 7.191440 | Best fixed-group baseline |

For Shapes, the five-graph oracle found a 21.5% improvement in its projected-sphere objective
over the best native cut. The assembled cut used groups 2/4/8/16 in proportions 265/23/17/4;
group 32 contributed no selected patch. It has exact leaf coverage, 12 fewer triangles than
the cap, and the same boundary-edge multiset, degenerate count, and non-manifold count as native
g2. Against the strongest eligible fixed-group image-space control, g16, its mean SSE is 15.9%
lower and it wins all 16 views.

The g2+g16 ablation cuts most of that gain: its mean SSE is only 0.8% lower than g16 and it
loses in half the views. Material Sphere is a direct proxy counterexample: the same five-graph
oracle reports a 13.3% projected-sphere improvement, yet the realized mixed PLY has 58.8%
higher mean filtered SSE than native g32 and loses every view. Its chosen patches come only from
g2 and g4 even though g32 is the clear image-space winner.

## Cost and interpretation

For Shapes, building all five graphs costs 29.05 seconds and stores 30.82 MiB of MMB data;
the best fixed g16 graph costs 7.84 seconds and stores 6.12 MiB. The candidate-pool build cost
is 3.71x and its serialized graph storage is 5.03x. The four graph sizes actually used by the
selected cut still cost 23.67 seconds, or 3.02x the g16 build. For Material Sphere, all five
graphs cost 10.19 seconds and store 3.31 MiB, versus 2.69 seconds and 0.59 MiB for g32; despite
the roughly 3.79x build cost, the mixed result is worse in the measured raster metric. MILP
selection time and combined-pool memory are not included in these ratios.

The experiment establishes that a cross-build region-cover oracle can find a real quality gain
on one asset, but the result is not robust across assets and costs several times more to build.
The proxy is therefore rejected as the selection objective. Do not promote this branch to a
production heuristic or a SIGGRAPH contribution.

## Prior-art boundary

Batched Multi-Triangulation already represents mesh fragments over a DAG, allows a fragment to
replace the same floor/domain, and composes precomputed patches from varying partition levels
into valid conforming cuts ([Cignoni et al. 2005](https://vcg.isti.cnr.it/Publications/2005/CGGMPS05/BatchedMT_Vis05.pdf),
Sections 3–4). The 2026 clustered-HLOD work also constructs multi-resolution cluster
representations with progressively simplified, matching boundaries
([Ladeuil et al. 2026](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380)). Mixing patches from
several group-size graphs is consequently a framework-level instance of established
multiresolution patch composition, not a defensible novelty claim by itself.

## Reproduction

```powershell
python -I tools/mmgeo/audit_mixed_group_cut_frontier.py --asset shapes --out out/mixed-group-frontier-20261117/shapes.json
python -I tools/mmgeo/audit_mixed_group_cut_geometry.py --mixed-json out/mixed-group-frontier-20261117/shapes.json --native-ply out/targetbudget-heldout-20261116/rep-01/shapes-g2/selected_ratio_0.55.ply --output-ply out/mixed-group-frontier-20261117/shapes-mixed.ply --output-json out/mixed-group-frontier-20261117/geometry_audit.json
python -I tools/mmgeo/audit_crossasset_visibility.py --mesh assets/models/shapes/shapes.obj --asset shapes --triangle-budget 40550 --cut mixed=out/mixed-group-frontier-20261117/shapes-mixed.ply --cut g2=out/targetbudget-heldout-20261116/rep-01/shapes-g2/selected_ratio_0.55.ply --cut g8=out/targetbudget-heldout-20261116/rep-01/shapes-g8/selected_ratio_0.55.ply --cut g16=out/targetbudget-heldout-20261116/rep-01/shapes-g16/selected_ratio_0.55.ply --output out/mixed-group-frontier-20261117/mixed_visibility.json
```

The two-graph Shapes ablation and Material Sphere repeat use the same commands with the
corresponding asset/group inputs and output paths. All captured inputs are hash-bound in the
result JSONs. No production C++ code changed and no software tests were run.

## Decision

Close “mix independent group-size DAG patches under a projected-sphere worst-error oracle” as
a research candidate. Retain the two positive Shapes PLYs and image metrics as controls only.
This result does not change the overall SIGGRAPH goal status; no paper-level contribution has
been established.
