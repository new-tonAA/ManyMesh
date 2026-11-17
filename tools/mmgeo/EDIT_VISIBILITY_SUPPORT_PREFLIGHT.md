# Collapse-history visibility support: a concrete preflight

Date: 2026-11-15. A potentially useful support reduction, not a demonstrated SIGGRAPH algorithm.

**Follow-up decision:** the [full-cost compact-query test](VISIBILITY_QUERY_BVH_COST_GATE.md)
has now completed. All nine separate-support-tree configurations are dominated by direct fine-BVH
queries in primitive counts and are slower in the instrumented Python reference. The support
fractions below remain valid, but no longer justify pursuing that runtime design.

## Question and closest prior art

The [previous cost gate](PROXY_VISIBILITY_COST_GATE.md) found that ordinary constant-probability
proxy correction can add too much coverage noise. This experiment instead asks whether a
conservative support can limit **deterministic exact fallback**: use the fine mesh only on rays
that may change binary coverage, and use the coarse mesh elsewhere.

The ingredients have explicit predecessors. [Simplification Envelopes, SIGGRAPH 1996](https://www.cs.umd.edu/~varshney/papers/simp_env.pdf)
uses inner/outer envelopes to bound approximation error. [Xia, El-Sana, and Varshney, TVCG 1997](https://www.cs.umd.edu/gvil/papers/av_vd.pdf),
Sections IV-C and V-A.1, stores normal information in a merge hierarchy and uses normal cones
to distinguish front-facing, back-facing, and silhouette regions during selective refinement.
Thus envelopes, collapse history, normal cones, and silhouette-aware refinement are not new.
[Billen et al., EGSR 2014](https://graphics.cs.kuleuven.be/publications/BLD14PVEGP/BLD14PVEGP_paper.pdf)
already uses geometric proxies for unbiased visibility and exact/correction queries, including
inside/outside proxies. The remaining question is whether a particular compact composition of
edit-derived coverage certificates can accelerate exact any-hit queries beyond these baselines.
This search does not establish that this composition is novel.

## Checked geometric condition

For each frozen collapse, take every face incident to either endpoint before the edit. Reorient
this local patch consistently; refuse nonmanifold or nonorientable patches. Replace the removed
vertex, omit the collapsed triangles, and check that the old and new oriented boundary chains
are identical. Boundary vertices must exclude both moving/removed endpoints, so their positions
are fixed. Compute the old and new unit face normals after this orientation repair.

For parallel lines of direction d, if **all old and new oriented face normals have strictly the
same sign when dotted with d**, the projected local coverage is invariant in ideal arithmetic.
The reason is not a small-distance approximation: the old and new projected triangle chains
have the same boundary and therefore the same winding multiplicity away from their edges. All
triangle orientations have one sign, so nonzero multiplicity is equivalent to local coverage.
Unchanged occluders cannot invalidate equality of the local binary coverage. Composition over
the recorded edits therefore preserves global binary coverage outside uncertain edit supports.

For an uncertified edit, each affected old triangle and its replacement lie in the four-point
convex hull of its old vertices and the collapse target. A projected axis-aligned box of those
four points conservatively encloses their footprints. The union of these boxes for uncertified
edits is the tested support. The prototype evaluates all stored face normals, rather than using
a compressed circular cone; it refuses dot products within 1e-10 of grazing. This threshold and
the box padding are **not proved floating-point error bounds**. Exact-grid validation below is
separate from the ideal argument.

This condition concerns full projected lines, or rays whose relevant geometry is wholly in front
of their origin. It does **not** preserve first-hit depth, shading, materials, or arbitrary finite
shadow segments. A targeted test is an explicit counterexample: a fixed-boundary patch moves
from z=0 into a segment spanning z in (0.1,1), with all projected orientations unchanged; segment
visibility changes although full-line coverage does not. For a future finite-segment experiment,
a sufficient extra guard is that the segment spans the entire intersection of its supporting line
with a box containing all relevant old/new geometry. Clipped cases must fall back. That guard
and a shadow-ray implementation have not been measured in this experiment.

## Frozen experiment and controls

The same three archived captures and nine existing QEM outputs are used, with no new optimization
or parameter tuning. The script replays **8,184** stored actions and reproduces every saved
snapshot's positions and triangles exactly. All local boundary-chain checks pass. Full history
is retained at each level; counts are not obtained by rerunning a modified QEM.

Three supports are compared:

1. **All edit boxes:** every affected face's four-point box across the complete history.
2. **Endpoint difference boxes:** exact-coordinate unmatched triangles from the source/final
   meshes, without using the intermediate edits. This checks whether history alone is useful.
3. **Orientation-filtered edit boxes:** exclude edits that meet the checked direction condition.

Normalization and denormalization change some vertex coordinates by floating roundoff. To keep
unchanged faces from appearing edited just because of that roundtrip, endpoint matching uses the
source after the same roundtrip as the archived QEM outputs. All **36** roundtrip-source coverage
images are independently rasterized and must equal their original-capture coverage exactly on
the frozen grid. The support prototype does not silently treat approximate coordinates as exact.

Each asset has 12 frozen orthographic views, 128x128 pixels, and 3x3 sample atoms per pixel. All
108 source/output comparisons reproduce their archived disagreement counts. We save the actual
binary coverage and support masks; the separate validator does not call replay, orientation,
normal tests, or box construction. It reconstructs `where(support,fine,coarse)` for all three
supports and confirms exact equality to fine coverage in **324** comparisons (47,775,744 atoms).
No finite-grid false negative was observed. This is not proof over continuous rays or float inputs.

## Results

The table counts fallback **inside the projected source-vertex bounding rectangle**. This removes
some easy background from the denominator. The rectangle is a cohort control, not a simulated
or timed BVH. The last column separately counts fallback among actual fine-mesh hits.

| Asset | Retained faces | All edit boxes | Endpoint boxes | Filtered boxes | Filtered fallback on fine hits |
|---|---:|---:|---:|---:|---:|
| Torus | 864 (75.00%) | 78.66% | 78.61% | 21.53% | 23.54% |
| Torus | 576 (50.00%) | 83.84% | 83.69% | 36.83% | 38.29% |
| Torus | 288 (25.00%) | 90.10% | 89.53% | 63.38% | 64.96% |
| Monkey | 11808 (75.00%) | 23.87% | 23.86% | 1.78% | 2.90% |
| Monkey | 7872 (50.00%) | 43.91% | 43.89% | 5.87% | 9.00% |
| Monkey | 3936 (25.00%) | 59.02% | 58.94% | 18.87% | 28.49% |
| Pirate | 3760 (75.05%) | 33.44% | 33.43% | 20.49% | 48.78% |
| Pirate | 2516 (50.22%) | 42.37% | 42.22% | 34.43% | 77.01% |
| Pirate | 1314 (26.23%) | 47.83% | 46.93% | 46.51% | 97.25% |

![Measured fallback support fractions](../../out/edit-visibility-support-20261115/support-fractions.png)

History boxes alone give practically no improvement over comparing the endpoint meshes. The
orientation condition gives a substantial reduction for Torus and Monkey, with smaller benefit
for Pirate. At Pirate's most reduced level it still requests fine queries on 97.25% of fine-hit
rays, so this representation does not create a universal cheap-query proxy. Large reductions in
the fraction of invariant edits are also not interchangeable with reductions in actual ray work.

The flat hull representation is already costly. Even using comparable float32 vertices and
uint32 source indices, its **hull vertices alone** occupy the following multiples of captured
source indexed-mesh data, excluding normals, topology metadata, hierarchy, and container overhead:

| Retained level | Torus | Monkey | Pirate |
|---|---:|---:|---:|
| About 75% | 3.17x | 3.03x | 2.97x |
| About 50% | 6.13x | 6.03x | 5.90x |
| About 25% | 9.09x | 9.04x | 8.76x |

The prototype actually uses float64 arrays. The ratios above use the same 32-bit element size
for both sides to avoid confounding the representation overhead with a data-type change. The
compressed mask files are offline view-specific outputs; their small file sizes are not evidence
of a compact runtime representation.

## Decision and next cost gate

Keep the checked orientation-filtered support as a **narrow candidate for a query-cost test**.
Drop the interpretation that a union of swept edit boxes alone provides a useful new mechanism.
No novel primitive, new estimator, native speedup, or SIGGRAPH contribution is claimed.

The next comparison must charge support traversal, conditional fine queries, proxy queries,
storage, and construction against an ordinary fine-mesh acceleration structure. A fallback
fraction is not `E[c_fine * fallback]/E[c_fine]`: many skipped misses are already cheap, while
fallback may concentrate on expensive hits. A zero-cost mask lookup is an oracle lower-cost
control, not the proposed runtime. Per-view projected boxes currently have to be rebuilt and
all edit normals tested; no persistent query hierarchy or continuous-camera update exists.
Any compact hierarchy must be checked against the present full-mask reference before timing it.
The finite-segment guard needs explicit counterexamples and an independent intersection kernel.

The three assets are reused development data, with geometry-only attributes. Larger unseen
assets, realistic shadow-ray distributions, equal-reference image results, and total runtime
cost are absent. Prior-art comparison must distinguish the composition from established normal
cone refinement and exact/inside/outside geometric proxy methods before a publication claim.
The active SIGGRAPH goal remains unmet.

## Reproduction and evidence

Seven targeted tests pass: fixed-boundary interior collapse; inconsistent input winding repaired
locally; moved boundaries refused; folded/grazing projections refused; nonmanifold patches refused;
projected-box union checked by direct sample predicates; randomized certified directions checked
with a separate triangle-side union test; and the finite-segment counterexample. Some tests cover
multiple related conditions. No production C++ or native build changed.

```
python -m unittest discover -s tools/mmgeo -p test_edit_visibility_support.py -v
python tools/mmgeo/edit_visibility_support.py --out out/edit-visibility-support-20261115
python tools/mmgeo/validate_edit_visibility_support.py out/edit-visibility-support-20261115/report.json
python tools/mmgeo/plot_edit_visibility_support.py out/edit-visibility-support-20261115/report.json
```

Authoritative output: `out/edit-visibility-support-20261115/report.json`, SHA-256
`c941e16f97d014942d9ffd4e15ded935b0d272f75958e451d0a08867e77bec51`.
The report binds captures, manifests, source evaluators, all replayed output meshes, and the three
mask archives by hash. Independent checks are recorded in the adjacent `validation.json`.
