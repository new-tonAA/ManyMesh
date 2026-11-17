# Substantial-reduction reference baseline

2026-11-15. Standard QEM baseline, not an algorithmic contribution.

## Why this changes the research setup

The preceding 48-candidate tests and two-collapse selections explored small local changes and
sometimes near-zero residuals. They do not establish behavior at meaningful triangle reductions.
This reference continuously regenerates current edges, placements and topology tests, reaching
75%, 50% and 25% source triangle retention where constraints permit. It makes those reduction
regimes available for later experiments, without presenting baseline construction as innovation.

The current native mmgeo executable is blocked by Windows application control. The explicit WSL
attempt first returned E_ACCESSDENIED inside the sandbox; approved outside execution then failed
to mount `D:\HW\wsl\ubuntu-bmc\ext4.vhdx` with ERROR_PATH_NOT_FOUND. The Linux process is terminal.
No native baseline or current C++ validation was obtained. This independent Python baseline uses
saved welded geometry, rather than weakening operating-system execution policy.

## Algorithm and limitations

Classic accumulated plane quadrics, source face-area weighting, endpoints/midpoint/solved
placements, a priority queue with local version invalidation, and deterministic ordering.
After every collapse, candidates on the entire affected one-ring are regenerated. Alternative
placements compete using their own QEM cost; a rejected placement does not hide other targets.
Each imported submesh remains separate. Vertices on boundary edges, nonmanifold edges and
disconnected incident face fans are locked. Every candidate checks the current edge link,
duplicate triangles, local orientation and triangle quality. Source-unit coordinates are
normalized once and output is restored to world units. Every checkpoint uses the same source
camera normalization; output levels never auto-fit their own bounds.

This is geometry-only reference code. Saved captures do not contain original corner UV/normal
attributes. It therefore does not reproduce production Corner, appearance gates, distance error
ceilings, intersection safety, GPU performance or complete surface topology guarantees. Output
topology statistics are independently recomputed; they do not constitute a complete validity proof.
Tiny/locked components can miss the requested per-unit budget. Report actual assembled face count.

## Evidence and reproduction

| Asset | Source faces | 75% checkpoint | 50% checkpoint | 25% checkpoint |
|---|---:|---:|---:|---:|
| Torus | 1152 | 864 | 576 | 288 |
| Monkey | 15744 | 11808 | 7872 | 3936 |
| Pirate | 5010 | 3760 | 2516 | 1314 |

Pirate retains 26.23% at its last checkpoint; boundary-locked small units do not reach their
individual targets. This is reported as a missed budget rather than relabeled as a matched 25%
case. All three independently preserve their original boundary edge count and Euler characteristic
at every checkpoint, with zero reported nonmanifold edges, duplicate faces or zero-area faces.

Twelve-view summed coverage+depth SSE at the three checkpoints:

| Asset | 75% checkpoint | 50% checkpoint | 25% checkpoint |
|---|---:|---:|---:|
| Torus | 1.73368 | 11.99399 | 182.37097 |
| Monkey | 0.005657 | 0.098983 | 1.153186 |
| Pirate | 3.85619 | 25.90802 | 248.26747 |

These are sums, not normalized perceptual scores. At the last checkpoint coverage accounts for
72.2% / 78.1% / 79.9% of the measured two-channel SSE. This provides a concrete high-reduction
target for future silhouette/visibility mechanisms; it does not prove any proposed mechanism
will improve on a strong image-driven baseline. Source meshes differ, so raw cross-asset SSE
should not be compared as if the assets had equal projected complexity.

The baseline build wall times were 1.33 / 90.95 / 19.05 seconds in Python, with assets launched
concurrently. They are offline development timings without GPU/renderer or production Corner
comparability. Output figures are `out/progressive-baseline/geometry-comparison.png` and
`out/progressive-baseline/baseline-error-curves.png`.

Three added regression checks cover a periodic torus reduced to 25% while recomputing its edge
counts, Euler characteristic and all vertex/face incidence; a tetrahedron that cannot collapse
into duplicate faces; and a fully boundary-locked patch with an unreachable budget. All 41 current
Python tests pass. This result does not revalidate historical C++ modifications.

The evaluator renders the complete meshes at 12 evenly spaced azimuths, 128 pixels, 3x sample
scale and sigma 0.9. It records filtered coverage/premultiplied-depth SSE separately, raw sample
coverage changes, worst view and full aggregate. This is a static development-asset orbit, not
unseen assets, PBR or temporal behavior. Fixed figures visualize normalized depth, not color.

```sh
python -I tools/mmgeo/progressive_geometry_baseline.py out/filter-real-candidates/torus.json --out out/progressive-baseline/torus
python -I tools/mmgeo/evaluate_progressive_baseline.py out/filter-real-candidates/torus.json out/progressive-baseline/torus
python -I tools/mmgeo/plot_progressive_baseline.py
```

Substitute `monkey` and `pirate` for the first two commands. Final artifacts contain action logs,
source/script hashes, mesh hashes and actual/reached budgets in each asset's `manifest.json`;
`evaluation.json` contains independently recomputed topology and full-view metrics.

The next mechanism comparison must operate at matched ACTUAL retention, use regenerated
candidates and compare to cumulative image-based simplification as well as this QEM reference.
Two-operation or selected positive examples alone remain insufficient evidence for the goal.
