# Dynamic recapture: complete-pool and edge-frontier controls (2026-11-16)

## Why the first result was insufficient

The initial eight-step experiment compared a 32-candidate frozen sample against 32 candidates
resampled after every collapse. It showed that a tiny frozen sample loses options, not that
candidate regeneration beats a complete legal edge queue. This follow-up uses every visible legal
candidate and separates current placement refresh from newly created edge candidates.

## Complete visible pool screen

Torus starts at 1,152 triangles. The initial Corner capture contains 3,456 directed legal
placements, of which 2,218 affect a currently visible triangle in the fitted view. Both policies
score all 2,218 initially and make eight two-triangle collapses.

| Policy | Final fitted-view SSE | 13-view final SSE | Selection and redraw time |
|---|---:|---:|---:|
| Frozen initial legal placements | 9.1265e-7 | 0.0785581 | 199.83 s |
| Recapture all current placements | 4.5351e-9 | 0.9285744 | 246.00 s |

Fresh placements reduce fitted-view SSE by 99.503%, but increase the final 13-view sum by
1,082% (11.82x). They also take 1.23x the measured selection/redraw time; capture itself costs
0.639 s over eight steps. The frozen policy must avoid candidate one-ring overlap because its
stored endpoint placements become stale; the refreshed policy allows adjacent collapses. This
screen is therefore not a fully matched ablation. It does show that the large fitted-view win is
not a robust multi-view quality win.

## Matched edge-frontier ablation

Both policies now recapture the current mesh after every collapse, use the same current legal
placements, allow adjacent collapses, and score every visible legal candidate against the same
fitted view. The `initial-edge-frontier` control admits only current candidates whose directed
edge descends from an edge in the source mesh. `all-current-edges` also admits adjacencies created
by earlier collapses. Stable vertex identities are propagated across OBJ round trips; every
round-trip raster is identical, and the identity remap is exact on this input.

| Policy | Final fitted-view SSE | 13-view final SSE | Selection, recapture, and redraw time |
|---|---:|---:|---:|
| Initial-edge frontier, current placements | 6.1378e-8 | 0.0141378 | 155.80 s |
| All current edges and placements | 4.5351e-9 | 0.9285744 | 157.73 s |

Allowing new edges lowers the fitted-view SSE by 92.611% at nearly equal measured work. The
13-view sum rises by 6,468% (65.68x). The eligible edge counts differ by at most about 1.1%; both
policies score roughly 2,188–2,224 visible candidates per step. Thus new edges can supply
additional fitted-view options in this Torus sequence, but those options overfit the single
selection view and fail the multi-view check.

All 16 selected collapses preserve the source Euler characteristic, connected-component count,
closed two-manifold edge incidence, oriented-edge consistency, signed-volume orientation, and
zero duplicate or zero-area faces. Patch predictions match full redraw within 1.36e-20, and all
OBJ round trips have zero raw-raster difference. Both policies remove 16/1,152 faces (1.39%).
The final 13-view audit contains the fitted view, six nearby views, and six full-orbit views; these
views do not participate in selection.

## Decision

Close dynamic recapture and newly created edge candidates as standalone contribution claims. This
is a geometry-only, one-asset, 1.39%-reduction screen; it has no authored materials, no PBR
evaluation, and no held-out asset. More fundamentally, sequential image-driven edge-collapse
selection and local image updates already appear in [Lindstrom and Turk, *Image-Driven
Simplification* (TOG 2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf).
View-cell error constraints also have established analytical foundations in [Eisemann and
Decoret, *On Exact Error Bounds for View-Dependent Simplification*](https://publications.graphics.tudelft.nl/rails/active_storage/blobs/redirect/eyJfcmFpbHMiOnsiZGF0YSI6IkJBaHBBc29RIiwiZXhwIjpudWxsLCJwdXIiOiJibG9iX2lkIn19--c2114546586e5dea53462d9b284e0363fd94e016/viewdepArticle.pdf).

The fitted-view improvements are useful diagnostics, not evidence for SIGGRAPH readiness. A next
image-driven project would need a distinct error or representation mechanism and a fair held-out
multi-view/material quality-versus-total-work result. This follow-up changes only research code
and reports; no production C++ was changed and no software tests were run.

## Reproduction

```powershell
python -I tools/mmgeo/audit_dynamic_recapture.py `
  out/filter-real-candidates/torus.json `
  --executable out/cmake-vulkan/tools/mmgeo/Release/mm_capture_candidates.exe `
  --out out/dynamic-recapture-fullpool-20261116 `
  --steps 8 --size 96 --scale 2 --candidates 3456 --audit-size 128 --audit-scale 3

python -I tools/mmgeo/audit_dynamic_edge_frontier.py `
  out/filter-real-candidates/torus.json `
  --executable out/cmake-vulkan/tools/mmgeo/Release/mm_capture_candidates.exe `
  --out out/dynamic-edge-frontier-20261116 `
  --steps 8 --size 96 --scale 2 --audit-size 128 --audit-scale 3
```

Machine records are [`complete-pool JSON`](../../out/dynamic-recapture-fullpool-20261116/dynamic-recapture-audit.json)
and [`edge-frontier JSON`](../../out/dynamic-edge-frontier-20261116/dynamic-edge-frontier-audit.json).
The corresponding research scripts are [`audit_dynamic_recapture.py`](audit_dynamic_recapture.py)
and [`audit_dynamic_edge_frontier.py`](audit_dynamic_edge_frontier.py).
