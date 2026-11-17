# Compact edit-support queries: full-cost reference gate

Date: 2026-11-15. The tested separate-support-tree design fails this cost gate.

## Result and interpretation

The [previous support preflight](EDIT_VISIBILITY_SUPPORT_PREFLIGHT.md) reduced the set of rays
requiring fine coverage queries, but did not charge the support query. This experiment implements
that query, an ordinary fine-mesh baseline, a coarse-mesh query, and the complete exact-fallback
path using shared kernels. All nine frozen source/output pairs are correct on the measured cohort.
They are also **more expensive in every primitive-count category** than querying the fine mesh:
more AABB tests, slightly more triangle tests, and additional cone tests.

The tested selector is therefore dominated under any constant positive linear cost assigned to
these three primitive types, on this workload. This is a statement about these reference paths
and cohorts; it is not a proof about all GPU implementations, caches, workloads, hierarchies,
geometric proxies, or exact visibility algorithms. Instrumented scalar Python query times are
1.61--2.38x the fine baseline, consistently with the operation counts. No native/GPU speedup is
claimed, and adding construction costs cannot rescue a slower query in this reference.

## Mechanism and fair baseline

Each edit is compressed to one three-dimensional AABB over its affected vertices and target,
plus a circular cone enclosing all old/new oriented face normals. Chain failures or cones at
least a hemisphere wide are uncullable. A primitive's axis is the normalized sum of its normals;
the cone radius covers the most distant normal. The test `abs(axis dot rayDirection)>sin(radius)`
is sufficient to discard a patch. Numerical margins widen cones and boxes; they are not formal
floating-point error bounds.

An ordinary twelve-bin spatial SAH builds both triangle and support BVHs, with forced splitting
above four primitives per leaf. Support nodes also store merged cones. Entire child cones can
be sign-flipped during merging because the patch's two-sided same-facing condition is invariant
under a consistent orientation reversal. Each merged cone contains the selected signed child
cones; it becomes uncullable if the radius reaches a hemisphere. This is a conservative data
structure, not a new normal-cone hierarchy algorithm.

Fine and coarse geometry use the **same** two-sided Moller--Trumbore triangle kernel, ray/AABB
slab kernel, SAH builder, leaf size, and near-child-first any-hit traversal. Query triangles are
stored as a vertex and two edge vectors for both meshes. The baseline is already accelerated:
it does not linearly scan fine triangles. Both query paths include identical counter recording.

The hybrid first tests the fine root box, returning a definite miss if possible. It then verifies
that the finite segment spans a box containing source, coarse, and all intermediate edit hulls.
Clipped segments query fine geometry. Otherwise it queries the support hierarchy and chooses
fine geometry on uncertain rays, coarse geometry on certified rays. The already tested fine root
is reused when falling back. All guard, support, proxy, and conditional fine work is charged.
No support mask is a free lookup, and coarse and fine are not always both queried at runtime.

A separate counter decomposition checks this path against

```
selector counters
  + fine counters minus the reused root test, on fine/clipped decisions
  + coarse counters, on coarse decisions.
```

It agrees for every timed ray in all nine cases. Fine-box misses still cost one AABB test, as in
the ordinary baseline. Finite-segment clipping is covered by a targeted moving-patch counterexample;
the main orthographic workload has endpoints deliberately outside the entire history box.

## Workload and correctness

The same three archived source captures and nine QEM outputs are frozen. All 8,184 recorded
collapses are replayed, and each output array is checked against the archived mesh. Scene geometry
is normalized once using the source center/radius for stable reference arithmetic.

For each of twelve old view directions, the saved 384x384 sample grid is divided into 32x32
equal screen strata. One subpixel is chosen uniformly within each stratum using seed 20261115.
There are **12,288 rays per source/output pair**, with their origins, directions, maximum
distance, view/sample indices, and independent saved-raster fine/coarse targets archived in NPZ.
The sample set is not chosen using disagreement or query cost. The reference intersection kernel
reproduces both fine and coarse saved coverage for every sample.

All **29,321 archived disagreement atoms** across the nine cases form a separate stress cohort.
Each must select fine fallback or a valid definite fine-box miss. None is allowed to silently use
the wrong coarse result. These stress samples are excluded from timing and uniform-cohort counts.
They do not substitute for validation of arbitrary clipped shadow segments or unseen cameras.

The timed runs use a warm-up and three repetitions with alternating baseline/hybrid order.
Timers cover the instrumented complete query loop; construction, cone fitting, and replay are
reported separately. Independent cone-validation work is outside the construction timer. This
is CPU Python evidence about a reference design, not an estimate of hardware traversal throughput.

## Measurements

Ratios below are hybrid divided by fine for counts, time, and runtime array payload. Cone tests
are additional operations per ray; they are not treated as equivalent to triangle/AABB tests.

| Asset | Requested retained level | AABB-test ratio | Triangle-test ratio | Extra cone tests/ray | Python query time ratio | Numerical runtime payload ratio |
|---|---:|---:|---:|---:|---:|---:|
| Torus | 75% | 1.925 | 1.012 | 4.380 | 2.03 | 1.91 |
| Torus | 50% | 2.211 | 1.013 | 6.255 | 2.24 | 1.83 |
| Torus | 25% | 2.143 | 1.005 | 5.905 | 2.17 | 1.74 |
| Monkey | 75% | 1.560 | 1.006 | 2.776 | 1.61 | 1.91 |
| Monkey | 50% | 2.023 | 1.019 | 5.841 | 2.08 | 1.82 |
| Monkey | 25% | 2.354 | 1.012 | 8.198 | 2.38 | 1.73 |
| Pirate | 75% | 1.858 | 1.015 | 2.752 | 1.87 | 1.92 |
| Pirate | 50% | 2.029 | 1.013 | 3.486 | 2.05 | 1.83 |
| Pirate | 25% | 2.072 | 1.005 | 3.804 | 2.03 | 1.75 |

Pirate's actual retained levels are 75.05%, 50.22%, and 26.23%. Exact face counts, repetition
times, four separate cohorts (viewport, source rectangle, fine hits, fine misses), all primitive
counts, decisions, and construction costs are in the JSON and per-ray cost archives.

The runtime payload sums all arrays read by the query: fine, coarse, and support. Unused
fine/coarse primitive bounds from the builder are excluded; support primitive bounds are required
and included. The scalar reference's cached triangle-edge geometry and float64 arrays are used
consistently. This improves over the earlier flat-hull representation but is **not process RSS**,
Python-object storage, or a fair GPU/indexed-vertex memory estimate. Compressed file size is not
used as a memory result.

## Free-selector controls and remaining room

The independent validator also measures a **zero-cost classifier** that makes exactly the current
compact selector's decisions, but pays only the resulting complete fine/coarse query. Definite
misses use the ordinary fine-query cost rather than being treated as a free known answer. In a
hypothetical model assigning cost 1 to an AABB test and 2 to a triangle test, this oracle changes
work by the following amounts; negative means a saving:

| Asset | 75% | 50% | 25% |
|---|---:|---:|---:|
| Torus | -0.12% | -0.02% | +0.21% |
| Monkey | -1.58% | -1.69% | -1.53% |
| Pirate | +1.42% | +1.80% | +0.39% |

Thus making this classifier cheap without changing its decisions leaves little headroom in
this kernel/workload. These weights are a sensitivity example, not calibrated hardware costs.
The complete grid of triangle/cone weight assumptions is retained in `validation.json`.

A much stronger **perfect free switch** uses both hidden outcomes and both complete query costs.
Where source and proxy agree, it picks whichever query is cheaper for the chosen weights;
where they disagree it picks fine. At the same triangle weight 2, it saves 8.48--16.24% in these
nine cases. This is not an implementable selection rule. It is a lower-cost bound within the
family of choosing one of these two complete queries with free perfect information; it does not
bound fused traversal or a different geometry/acceleration representation. It prevents overstating
the failure as a universal impossibility result while making the current selector's weakness clear.

## Prior art and decision

[Johnson and Cohen, Spatialized Normal Cone Hierarchies, I3D 2001](https://www2.cs.utah.edu/gdc/publications/papers/johnsonI3D2001.pdf)
already combines spatial bounds and normal cones for silhouette, distance, and area-light shadow
boundary queries. The primary indexed abstract was accessible; attempts to fetch its full PDF
timed out. The hierarchy itself cannot be claimed as new here.

[Sander et al., Silhouette Clipping, SIGGRAPH 2000](https://hhoppe.com/silclip.pdf) is also close:
progressive hulls enclose a fine model, a precomputed anchored-cone edge hierarchy extracts its
exact silhouette, and stencil/alpha masks clip coarse rasterization. Their method has explicit
closed/oriented/static mesh and viewpoint restrictions and does not solve arbitrary internal
depth or finite shadow segments. Its existence excludes presenting generic coarse rendering
plus exact silhouette correction, or a perspective cone hierarchy, as an original next step.

Close this **separate support BVH plus separate coarse/fine BVHs** prototype. Do not tune more
cone parameters or leaf sizes on the same three assets to chase the former support fractions.
The geometric coverage condition remains a checked reference, but a new candidate must remove
the redundant query cost or change the representation and have a defensible difference from the
existing silhouette/proxy methods. Fusing work into an existing hierarchy is a possible question,
not an implemented or novelty-validated contribution. Before another runtime prototype, its
mechanism and cost advantage must be specific. The SIGGRAPH goal is still unmet.

## Verification and reproduction

Four new targeted tests cover SAH traversal and serialization against an independent 3x3 linear
intersection solver, double-cone composition against raw normals, the clipped finite-segment
counterexample, and parallel/inside-origin slab cases. The previous seven local coverage tests
remain unchanged. The benchmark verifies external raster targets, cost decomposition, random
leaf-cone conservatism, archived stress samples, and repeated-query determinism.

The separate validator reloads all saved trees and rays, without building a new hierarchy, and
rechecks **331,776** fine/coarse/hybrid ray queries plus their operation counts and cohort totals.
No production C++ or native build changed. The native executable constraint remains as documented
in the research ledger; independent Python kernels do not execute or bypass that binary.

```
python -m unittest discover -s tools/mmgeo -p test_visibility_query_bvh.py -v
python tools/mmgeo/benchmark_visibility_query_bvh.py --out out/visibility-query-bvh-20261115
python tools/mmgeo/validate_visibility_query_bvh.py out/visibility-query-bvh-20261115/report.json
```

Authoritative report: `out/visibility-query-bvh-20261115/report.json`, SHA-256
`b7cf208bf651eb8b9ecd2256ae91d493bd5405f48df7526572dac8f50c2c9557`.
The adjacent `validation.json` binds the report and validator and contains rechecked cost sensitivity
and runtime-payload results. Source captures, old manifests, ray cohorts, raw cost arrays, and
serialized trees have separate SHA-256 bindings.
