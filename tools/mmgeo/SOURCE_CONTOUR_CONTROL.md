# Source contour quadrics: stronger classical control

2026-11-15. This is a baseline comparison, not a proposed novel contribution.

## Frozen construction

Before running this policy, fix eight azimuths `0.13 + 2*pi*k/8`, elevation component 0.37,
strength 1 and retention targets 75/50/25%. No tuning from the measured output. Preserve
the existing QEM topology, geometry, boundary and per-unit gates. For each source edge shared
by two oppositely facing triangles, add a plane through that edge parallel to the view direction.
Squared distance to the plane penalizes projected contour displacement. Edge weight is edge
length times mean source edge length, divided by eight views, so its units match area-weighted
surface quadrics. The solved combined quadric generates positions as well as scores.

The quadric is fixed from the SOURCE and accumulated through the collapse history. It is not
updated from runtime visibility. Hidden apparent-contour edges are not removed, and global
occlusion/materials are not modeled. The measurement orbit has 12 azimuths starting at zero,
none identical to the eight construction views. All assets remain previously used development
assets. No unseen-asset or continuous-motion generalization claim follows.

## Why include an already established family?

The large-reduction QEM results show substantial silhouette loss. A new mechanism must beat
strong classical contour controls, not claim novelty for the fact that silhouettes are important.
View-dependent silhouette criteria already appear in FastMesh and Hoppe's progressive refinement.
Quadrics constraining an edge with an added plane are also classical boundary-preservation tools.
This implementation is a deliberately simple source-contour control within that family, not a
faithful reproduction of any particular paper or a state-of-the-art claim.

Sources inspected:
- https://www.ifi.uzh.ch/dam/jcr:ffffffff-82b7-d340-0000-000058d8660d/FastMesh.pdf
- https://hhoppe.com/vdrpm.pdf

## Evaluation

Compare actual triangle counts, not requested ratios. Do not treat a missed contour budget as
an equal-budget quality victory. Evaluate full-image coverage/depth at the same twelve cameras
using the existing evaluator, independent source normalization and identical filter. Report
per-view regressions along with sums and independent topology statistics. Runtime timings are
offline Python, not native simplifier or renderer measurements. Attribute validation remains open.

```sh
python -I tools/mmgeo/progressive_geometry_baseline.py out/filter-real-candidates/torus.json --policy source-contour --out out/source-contour-control/torus
python -I tools/mmgeo/evaluate_progressive_baseline.py out/filter-real-candidates/torus.json out/source-contour-control/torus
```

Substitute each asset. Outputs are a separate run with policy, fit cameras, constraint count,
action history and source/script/mesh hashes. The original standard-QEM artifacts remain a
different baseline version and their saved hashes must not be relabeled as this policy's code.

## Measured results

All nine comparison points have exactly matched actual triangle counts (including Pirate's
missed target, where BOTH policies retain 1314 faces). Twelve evaluation cameras are included
at every point. Positive reductions below mean lower coverage+depth SSE than standard QEM;
negative reductions mean higher error.

| Asset | Requested retention | Actual faces | Relative SSE reduction | Regressed views / 12 |
|---|---:|---:|---:|---:|
| Torus | 75% | 864 | +10.138% | 3 |
| Torus | 50% | 576 | +13.963% | 0 |
| Torus | 25% | 288 | -10.851% | 11 |
| Monkey | 75% | 11808 | -0.008% | 7 |
| Monkey | 50% | 7872 | -20.128% | 10 |
| Monkey | 25% | 3936 | +3.105% | 3 |
| Pirate | 75% | 3760 | -19.119% | 10 |
| Pirate | 50% | 2516 | +26.048% | 0 |
| Pirate | 25% | 1314 | +6.871% | 4 |

No parameter was changed after observing the results. The simple contour control is neither
uniformly better nor a reliable large-reduction solution. In particular, 50%-retention successes
on Torus/Pirate must be reported alongside the 20.1% Monkey regression. Topology counters retain
each source's Euler/boundary counts with zero new duplicate faces, zero-area faces or nonmanifold
edges across all checkpoints. They remain limited local/topological checks.

Source contour constraint counts are 896/6083/6764. Offline Python build wall times are
1.36/86.04/18.97 seconds, with assets launched concurrently; there is no controlled native/GPU
throughput claim. Standard-QEM Torus was rerun after adding this optional policy and positions
AND triangle arrays remain exactly equal at all three checkpoints. One new regression checks
that the additional quadric is PSD, zero strength adds no penalty, and invalid directions fail.
The Python suite now passes 42 tests; `git diff --check` passes.

Decision: retain BOTH classical controls in future matched-face comparisons, without selecting
a different policy per test view or claiming this family is novel. The experiment identifies
where a fixed source-contour surrogate fails, but does not identify the causal reason: visibility
changes, insufficient weighting and correspondence drift remain unseparated explanations.
No dynamic contour regeneration or occlusion-aware correction has yet been tested.

Full metrics, input/raster hashes and actual-retention checks are in
`out/source-contour-control/comparison.json`. The comparison graph is
`out/source-contour-control/comparison.png`. Reproduce their aggregation with:

```sh
python -I tools/mmgeo/compare_progressive_baselines.py
```
