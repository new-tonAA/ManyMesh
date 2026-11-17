# Hidden source-contour constraints: controlled ablation

2026-11-15. Freeze before the filtered simplification run. This is causal screening within a
classical family, not a novel contribution. Visibility-weighted simplification already exists:
Zhang & Turk, Visibility-Guided Simplification (VIS 2002), author paper inspected at
https://faculty.cc.gatech.edu/~turk/my_papers/surfviz_vis2002.pdf . Their surface/camera visibility
weighting is not claimed to be new here.

Question: does the source-contour control fail because it constrains occluded contours?
Classify visibility on the same eight frozen source views. For each apparent-contour edge,
parameterize its segment by t in [0,1]. Triangle barycentric coordinates and triangle-to-edge
depth difference are affine in t. Clip these inequalities, union hidden intervals, and weight
the contour quadric by the remaining visible fraction. Larger depth is nearer, two-sided opaque
geometry; incident triangles are excluded to avoid self equality. This is classical hidden-line
clipping, not new mathematics. Tolerances: projected area 1e-14, coverage 1e-12, depth 2e-10,
slope 1e-15 in globally normalized source units. It is floating-point interval clipping, not an
interval-arithmetic or continuous-motion guarantee. All submeshes participate as occluders.

Two controls share the same source mesh, camera set, base quadrics, gates and target fractions:

1. **Visible:** multiply each source contour term by its visible segment fraction.
2. **Strength-matched:** retain ALL contour terms and multiply them uniformly by
   sum(edgeLength * visibleFraction)/sum(edgeLength), separately per submesh. Thus total scalar
   contour weight matches the visible policy; directional/geometric distribution differs.

Compare both to original QEM and the all-source-contour control. This prevents explaining
lower error from merely reducing all contour weights as evidence for occlusion-aware weighting.
No view-wise or asset-wise winner selection; all nine checkpoints and all twelve measurement
views must be reported. Requested ratios and boundaries are unchanged; compare actual faces.
No post-result tuning. Visibility is SOURCE-only and is not recomputed as the mesh changes.
Consequently this does not test dynamic visibility or eliminate correspondence-drift explanations.

Before simplification, source visibility counts for Torus were 896 terms, 176 wholly hidden
and 32 partially visible. These are construction diagnostics, not a quality outcome.

```sh
python -I tools/mmgeo/source_contour_visibility.py out/filter-real-candidates/torus.json --out out/contour-visibility/torus.json
python -I tools/mmgeo/progressive_geometry_baseline.py out/filter-real-candidates/torus.json --policy source-contour --contour-filter visible --visibility-json out/contour-visibility/torus.json --out out/visible-contour-control/torus
python -I tools/mmgeo/progressive_geometry_baseline.py out/filter-real-candidates/torus.json --policy source-contour --contour-filter strength-matched --visibility-json out/contour-visibility/torus.json --out out/matched-contour-control/torus
```

Substitute each asset; evaluate with `evaluate_progressive_baseline.py` and compare to both
saved baselines. Hashes bind the source and visibility inputs. No material, UV, lighting,
global self-intersection or native real-time validation is supplied by this diagnostic.

## Results

Source constraints classified wholly hidden / partially hidden / all:

| Asset | Wholly hidden | Partially hidden | All edge/view terms | Prepass seconds |
|---|---:|---:|---:|---:|
| Torus | 176 | 32 | 896 | 0.46 |
| Monkey | 3500 | 449 | 6083 | 79.70 |
| Pirate | 3599 | 916 | 6764 | 24.76 |

The prepass uses all source triangles as potential occluders and is an offline Python reference,
not a runtime method. Visible fractions and strength controls were frozen before either run.

Relative SSE reduction of VISIBLE policy compared with each control (positive = lower error):

| Asset | Retention target | Vs QEM | Vs all contours | Vs strength-matched |
|---|---:|---:|---:|---:|
| Torus | 75% | +18.831% | +9.674% | +9.670% |
| Torus | 50% | +15.944% | +2.302% | +2.239% |
| Torus | 25% | -8.858% | +1.797% | +1.862% |
| Monkey | 75% | -26.334% | -26.323% | -26.331% |
| Monkey | 50% | -10.739% | +7.816% | -1.207% |
| Monkey | 25% | +9.598% | +6.701% | +9.308% |
| Pirate | 75% | -31.283% | -10.212% | -10.647% |
| Pirate | 50% | +15.214% | -14.650% | +8.115% |
| Pirate | 25% | +19.876% | +13.964% | Not matched |

All comparisons except the last strength-control point match actual face counts exactly. At
Pirate's last checkpoint visible/all/QEM retain 1314 faces but strength-matched retains 1316:
the visible-vs-strength relative score is deliberately left undefined. No gates were relaxed to
force a comparison after seeing outcomes. All twelve view errors and regression counts remain
in `out/contour-visibility/summary.json`, alongside input hashes, not only these aggregate sums.
Independent topology counters at all eighteen new checkpoints match the source Euler and
boundary counts, with no new nonmanifold edges, duplicate faces or zero-area faces.

**Interpretation:** removing occluded source terms does not resolve the lack of reliable gains.
It improves some cases, but loses to uniform weakening at Monkey 50% and Pirate 75%, and remains
worse than plain QEM at Torus 25%, Monkey 75%/50% and Pirate 75%. The count of hidden constraints
therefore cannot by itself explain the previous policy's quality failures. It would be too strong
to conclude that occlusion never matters or that source-correspondence drift is now proven to be
the cause. Weight anisotropy, discrete changes in the collapse trajectory and changing visibility
remain confounded. No parameter sweep or test-outcome-based policy selection was performed.

Decision: do not promote source visibility reweighting as the proposed mechanism. The added
strength control matters: a selected positive result against all contours alone would have been
insufficient. Retain this as a stronger diagnostic baseline. A new mechanism still needs a clear
contrast with established visibility-guided/image-driven methods and end-to-end benefit.

## Validation

Five analytic hidden-line checks cover front/behind half-segment visibility, overlapping occluder
union, excluded incident triangles, coplanar depth, depth-crossing splits and disjoint intervals.
A QEM regression checks visible weights of one reproduce all-contour quadrics exactly and zero
weights reproduce plain quadrics. Total Python suite: 48 passed. `git diff --check` passes.
No C++ or current native build validation is implied. Aggregate with:

```sh
python -I tools/mmgeo/summarize_contour_visibility.py
```
