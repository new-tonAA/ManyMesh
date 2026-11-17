# ReSTIR-LoD overlapping-UV branch-matching preflight

Date: 2026-11-17. This is a geometry-only falsification screen, not a path-tracing or ReSTIR
experiment, and not a novelty claim.

## Question

ReSTIR-LoD maps points on different LOD surfaces through UV space. For overlapping UV charts, its
paper greedily matches source/target surface hits by minimum world-space distance. Could choosing
the one-to-one branch assignment by a simple light-transport signature improve cross-LOD
correspondence on a ManyMesh asset?

## Screen

Use the Cloth LOD0→LOD1 and LOD0→LOD2 OBJ exports from the earlier UV transport preflight. Cloth is
the most promising local stress case: about 62.9% of uniform source-UV-area samples hit multiple
target triangles. For each transition, draw 20,000 deterministic source samples weighted by UV
triangle area. At each sampled UV, enumerate all source and target surface hits and greedily form a
one-to-one pairing by either:

1. the ReSTIR-LoD baseline cost, squared world-space distance; or
2. RMS difference between 128 fixed Fibonacci-sphere samples of the Lambertian cosine response
   `max(0, n·ω)`.

For the selected source branch, record whether the pair changed, position displacement, geometric
normal angle, area-Jacobian ratio, and cosine-signature difference. The implementation records input
OBJ hashes and its own source hash in each JSON output.

## Results

Both Cloth transitions mapped all 20,000 sampled source points. 12,573/20,000 samples (62.865%)
were UV ambiguous. The Lambertian-signature assignment selected the exact same target branch as
nearest-world-distance matching in every sample; changed-pair count was zero. Consequently all
reported displacement, normal-angle, Jacobian, and signature statistics were identical.

For Cloth LOD0→LOD1 the baseline mean / p95 normal-angle error was 0.531° / 2.495°, and mean / p95
position displacement was 5.42e-5 / 4.13e-4 of the source bounds diagonal. For LOD0→LOD2 those
values were 0.652° / 3.214° and 7.88e-5 / 5.55e-4. These small geometric errors are consistent
with the earlier report that this chain only removed 2.6% and 2.9% of faces.

To avoid relying only on the lightly simplified Cloth mesh, I generated Shapes LODs using the same
ManyMesh Release binary and ran the existing UV preflight. LOD0→LOD3 removes 51.2% of triangles;
28.61% of 20,000 sampled UV points are ambiguous, all samples have target support, and all nearest
round trips return to the source branch. The p99 normal difference is 3.04° and p99 position
displacement is 0.104% of the bounds diagonal. On this transition, a smaller 4,000-sample,
32-direction matching screen changed 5 pairings (0.125%). The mean cosine-signature discrepancy
increased by 0.122%; mean position displacement increased 181.7%, driven by a 6.97%-of-bounds
outlier. This is a small diagnostic sample, but it provides no evidence that the tested signature
objective improves the baseline. Shapes is not a rendering or path-distribution test.

Camera LOD0→LOD1 is an additional UV-overlap stress case: all 20,000 UV samples had multiple target
hits, but the chain removed only 5.1% of triangles. The baseline nearest map had 99.455% sampled
mutual nearest round trips, with p99 position displacement 7.67% of bounds and p99 normal angle
45.3°. A new 20,000-sample hit-count census shows why this is a poor representative stress asset:
source UV fibers contain 2–42 triangle hits and target fibers 2–43; the hit-set cardinalities differ
on 249/20,000 samples (173 source-greater, 76 target-greater). The cardinality-only uniform-branch
coverage estimate is 99.824%, but this assumes equal branch weights and is not the actual greedy
mapping rate. Camera's extreme stacking and minimal 5.1% reduction make its tail a diagnostic, not
evidence of a useful simplification result.

For comparison, Shapes LOD0→LOD3 has 20,000/20,000 equal source/target hit-set cardinalities after
51.2% triangle reduction: 14,312 samples have one hit on each side, 90 have 13, and 5,598 have 14.
Thus the largest-reduction local asset preserves the sampled UV-fiber multiplicity exactly. All
finite samples leave untested UV locations and do not prove global mapping continuity.

## Decision

Close simple geometric Lambertian-signature branch matching as a contribution candidate for the
tested local assets. It changed no Cloth branch and changed only 5/4,000 Shapes branches while
slightly worsening the aggregate proxy and producing a large displacement outlier. Do not promote
“normal-aware UV matching” from these results. UV overlap by itself is not a sufficient stress
case: the overlapping branches must have competing spatial and transport matches at a meaningful
LOD reduction.

The screen does not test texture/BSDF response, visibility, full path contributions, reservoir
weights, multi-pass variance, temporal covariance, or mapping smoothness. It does not refute a
contribution-aware matcher on other assets. However, matching by a transport/PDF signature is
adjacent to established ReSTIR reuse-compatibility methods, including [Tokuyoshi, *Efficient Spatial
Resampling Using the PDF Similarity* (I3D 2023)](https://doi.org/10.1145/3585501). A future proposal
would need to show a mapping change and a full-estimator Pareto gain on held-out assets before
claiming novelty. The current machine still has no hardware RT path, so that decisive validation is
not available here.

## Artifacts

- [`audit_restir_overlap_matching.py`](audit_restir_overlap_matching.py)
- `out/restir-overlap-matching-20261117/cloth_0_1_v2.json`
- `out/restir-overlap-matching-20261117/cloth_0_2_v2.json`
- `out/restir-overlap-matching-20261117/shapes_0_3_4000.json`
- `out/restir-overlap-extension-20261117/{camera,shapes}_uv.json`
- `out/restir-multiplicity-20261117/{camera_0_1_v2,shapes_0_3_v2}.json`
- Source geometry and UV measurements: [`RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md`](RESTIR_LOD_UV_TRANSPORT_PREFLIGHT_20261116.md)

No production C++ was changed and no software tests were run.
