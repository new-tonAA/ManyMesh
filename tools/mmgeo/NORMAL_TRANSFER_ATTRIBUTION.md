# Fixed-geometry normal-transfer attribution

2026-11-15. Classical attribute control, not a novel simplification method.

Previous controlled RGB results derived smooth normals independently from each simplified
mesh. They did NOT establish performance of a simplifier that carries source normal attributes.
Before treating that mismatch as a research gap, compare two normal policies on EXACTLY the
same coarse positions/connectivity: derived normals and source-area normal moments accumulated
through the actual saved collapse history. This control does not rank or change a collapse.

The initial moment of a source vertex is the sum of its incident unnormalized face normals.
For each saved remove->keep collapse, add remove's moment into keep's and zero remove's moment.
Normalize only for final shading. Near-zero used moments fall back to derived normals and are
counted. This is a source-vertex moment average (incident faces overlap among vertices), NOT an
exact integration over a disjoint source patch or an optimal normal correspondence.

Replay checks every saved old endpoint position, reconstructs current positions, replays index
replacement, deletes repeated-index triangles, and verifies the checkpoint connectivity/used
positions. Per-unit histories use the exact applied-action prefix at the chosen checkpoint.
This supports attribution to a real collapse history rather than copying unrelated old normals.
There is still no UV/corner-wedge correspondence, authored-normal export, source-surface error
bound, or complete attribute validation. Treat the two-sided smooth shading as the same restricted
control used before, not a production normal-map comparison.

Fix prior camera/light/filter parameters; compare QEM and cumulative-image geometry at their
final checkpoint (25% requested; Pirate actually 26.23%), all three assets, all twelve measured
views. Report all failures and regressions. No image fitting or test-view choice is performed.
Recompute the old derived-normal RGB scores and require agreement with the saved reference before
using transferred-normal scores. Actual face counts/positions remain fixed for both normal modes.

Normal/appearance attributes are already part of established simplification methods:
- Garland & Heckbert, 1998: https://publications.ri.cmu.edu/simplifying-surfaces-with-color-and-texture-using-quadric-error-metrics
- Hoppe, 1999: https://hhoppe.com/proj/newqem/
The author pages and paper excerpts were inspected. This limited moment averaging is not a
faithful reimplementation of either metric. Adding a normal attribute or switching RGB objectives
does not on its own create a novel contribution.

```sh
python -I tools/mmgeo/evaluate_normal_transfer.py out/filter-real-candidates/torus.json out/progressive-baseline/torus out/progressive-image-control/torus --reference-rgb out/shading-controls/torus.json --out out/normal-transfer/torus.json
```

Substitute each asset. New output hashes bind the capture, checkpoint, history manifest, old RGB
reference and renderer implementations. Run this attribution before claiming a mesh-position
failure solely from the earlier derived-normal RGB regressions.

## Completed results

All three runs exited 0, all twelve views reproduced the previous derived-normal scores within
1e-10 tolerance, and all six histories reconstructed checkpoint connectivity and used positions.
No used vertex required the near-zero-moment fallback. The following compares image-driven
geometry with QEM geometry using the SAME normal policy for both. Positive change means worse.

| Asset | Actual triangles | Derived normals: RGB error change | Carried normals: RGB error change | Worse carried-normal views / 12 |
|---|---:|---:|---:|---:|
| Torus | 288 | +7.34% | +16.73% | 10 |
| Monkey | 3936 | +0.13% | +0.81% | 6 |
| Pirate | 1314 | -22.90% | -26.93% | 3 |

Carried-normal SSE (QEM / image): Torus 69.370819 / 80.973804; Monkey 8.741395 / 8.811861;
Pirate 263.275979 / 192.377696. Changing from derived to carried normals within QEM reduces SSE
6.05% on Torus and 0.75% on Pirate but increases it 3.62% on Monkey. Within image-driven geometry,
it increases SSE 2.17% on Torus and 4.31% on Monkey while reducing it 5.94% on Pirate.

Thus this particular source-moment transfer does not remove the proxy/shading mismatch. It is
NOT evidence that all optimized attribute transfer must fail, or that the low geometry cannot
support a better normal map. There is no authored normal input in these captures. Pirate's
improved sum with three regressed views also shows why aggregate improvement is insufficient
to claim every view improves. Do not select different normal policies per asset to present a win.

`out/normal-transfer/summary.json` checks current hashes for every input, equal actual face counts,
checkpoint ratios, complete identical cameras, and per-view sums. Recreate it with:

```sh
python -I tools/mmgeo/summarize_normal_transfer.py
```

The Python suite passed 57 tests after adding history validation, including deliberate mismatched
geometry/connectivity rejection. This remains a classical attribution control, with no new
production C++ change, dynamic-update cost result, or novel algorithm established.

The later [stationarity audit](APPEARANCE_COMPENSATION_V1_STOP.md) identifies a discontinuity in
the shared shading-normal-facing renderer when normals are optimized. These fixed-normal
comparisons remain measurements of that restricted contract, not a prediction of the separate
triangle-facing v2 renderer or a certificate of attainable optimized-normal appearance.
