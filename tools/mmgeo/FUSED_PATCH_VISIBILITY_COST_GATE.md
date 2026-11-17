# Local proxies inside the original BVH: cost and predicate screen

Date: 2026-11-15. The tested full-equivalence patch design does not establish a useful speedup.

## What changed from the failed separate hierarchy

The [separate-support-tree experiment](VISIBILITY_QUERY_BVH_COST_GATE.md) paid too much for a
second traversal. This experiment keeps the original fine BVH and attaches a local proxy to
selected existing subtrees. It shares their traversal and already tested spatial bounds.
Candidates are the maximal source BVH nodes containing at most 32, 64, or 128 triangles, forming
three complete disjoint cuts per asset. These numbers are patch capacities, not retained mesh
percentages. The nine configurations use the same saved uniform ray cohorts as the last test.

Within a source node, a classical fixed-boundary QEM exhausts legal collapses. Every placement
must remain in the original patch's axis-aligned box. Source and final oriented boundary chains
must agree, and boundary positions remain fixed. A circular cone covering **both** source and
final face normals supplies the same-facing coverage condition. If the direction passes this
condition and the finite segment spans the full source-node box, the proxy replaces traversal
below that node. Otherwise the original subtree is queried. Coarse root testing is skipped using
the already tested containing source-node bound; it is not a free unrelated spatial lookup.

The code does not change the source BVH split, primitive ordering, or triangle kernel. Disabled
replacement has identical answers and primitive counts to the original query, checked on the
saved rays and independent random tests. Both source and proxy caches use the same Python scalar
types. Finite-segment clipping is checked explicitly; a targeted example has a valid facing cone
but a changed clipped hit, and therefore must take the original path.

This preserves binary any-hit coverage under its checked conditions, not first-hit depth,
appearance, attributes, or material quality. Local proxies can be geometrically inaccurate where
the runtime condition rejects them. That is safe for the tested query, but is not a generally
renderable coarse mesh or a production Corner reproduction.

## Evidence and measurements

Across the assets, 88/1188/370 unique source-node candidates are built, reused where cuts share a
node. The independent validator checks 1,737 reduced patch geometries, including inactive ones,
for source correspondence, fixed oriented boundary, pinned coordinates, containment, cone data,
and serialized proxy geometry. It reconstructs the saved trees and checks **258,048** fine,
actual, and free-oracle ray queries plus operation counts/metrics against the saved results.
Every actual/oracle output equals the independent archived fine-raster target on the measured rays.

The oracle is deliberately optimistic: at a node passing the full-equivalence condition it traces
both the original subtree and proxy, then charges only the cheaper result under AABB cost 1,
triangle cost 2. Certificate/choice cost is free. Its local answers must agree. This bounds the
opportunity for these particular patches and this certificate family under those weights; it
does not bound different certificates, representations, fused kernels, or hardware costs.

The actual-work column below uses AABB=1, triangle=2, cone=0.5 as a **hypothetical** sensitivity
model, not calibrated CPU/GPU instruction costs. All ratios are relative to the fine baseline.

| Asset | Capacity | Active proxies / cut nodes | Free-oracle saving | Actual modeled work | Paired CPU time | Numerical runtime payload |
|---|---:|---:|---:|---:|---:|---:|
| Torus | 32 | 44 / 52 | 1.00% | 1.0103x | 1.000x | 1.461x |
| Torus | 64 | 16 / 28 | 0 | 1.0103x | 1.014x | 1.246x |
| Torus | 128 | 0 / 16 | 0 | 1.0000x | 1.056x | 1.000x |
| Monkey | 32 | 648 / 727 | 3.33% | 1.0012x | 1.049x | 1.522x |
| Monkey | 64 | 304 / 386 | 2.76% | 1.0008x | 1.012x | 1.361x |
| Monkey | 128 | 123 / 183 | 1.93% | 1.0058x | 1.000x | 1.228x |
| Pirate | 32 | 96 / 239 | 0.113% | 1.0016x | 1.018x | 1.251x |
| Pirate | 64 | 26 / 121 | 0.036% | 1.0003x | 1.000x | 1.105x |
| Pirate | 128 | 7 / 62 | 0.016% | 1.0000x | 1.037x | 1.049x |

The CPU column comes from five paired repetitions in the separate timing audit. Small differences
are not statistically established speedups/slowdowns, especially with CPU-clock granularity and
scheduling noise. No native/GPU measurement was made. The wall-time audit ranges from roughly
0.996x to 1.080x actual/fine; it does not supply a consistent substantial improvement either.

Other operation weights can slightly favor the Monkey configurations: over triangle/AABB weights
1,2,4,8 and cone/AABB weights 0.25,0.5,1, the best actual modeled work is about 0.991x. Thus this
design is **not** dominated in every primitive-count category as the separate hierarchy was.
The supported conclusion is small opportunity and no demonstrated net performance advantage,
not a universal impossibility. Fine any-hit BVH traversal is already cheap, and many removed
triangles would never have been tested by a successful ray.

The payload column counts numerical arrays needed for source/proxy queries and attachment/cone
data, excluding build-only primitive bounds. It excludes Python containers, dictionary storage,
and actual GPU/indexed-mesh layouts. It is not process RSS or a complete GPU memory measurement.

## Timing correction: initial apparent gains are invalid

The first run was interrupted after discovering that deserialized source caches and newly built
proxy caches used different scalar types. Its directory contains an explicit invalidation note.
The authoritative `-v2` run normalizes both caches and has a targeted type-equality test.

The initial repetitions in v2 also show a wall-time phase change (roughly 0.3s to 1.2s on Torus).
Dividing independently selected medians produced an apparent large gain even though paired runs
mostly did not improve. That **ratio-of-medians field in the raw report must not be used as a
performance claim**. Raw samples are retained. The independent `timing-audit.json` reruns **all
nine configurations**, in alternating paired order, with both process CPU time and wall time.
It checks outputs and primitive costs during each repetition. These paired results supersede
the first timing interpretation. No initial 2--3x apparent speedup is accepted as evidence.

## A weaker predicate: checked implication, not a new theorem

The full-equivalence condition is stronger than necessary for one query outcome. For two local
oriented triangle chains with the same fixed boundary, their projected signed winding
multiplicities agree away from projected edges. This standard fact gives two different rules:

* If **proxy** triangles all have one projected orientation, a proxy hit has nonzero winding,
  so the source must contain at least one hit. Source triangles may have mixed orientations.
* If **source** triangles all have one projected orientation, a proxy miss has zero winding,
  so the source must also miss. Proxy triangles need not all share an orientation.

The other implication in either rule is invalid. An exact rational control uses a square's
four-triangle folded fan as source and its flat two-triangle cap as proxy. Their oriented
boundaries agree. Source projected signs are `[+,-,+,+]`, proxy signs `[+,+]`. In 980 checked
off-edge grid points, all 201 proxy hits are source hits, while **45 proxy misses are source
hits**. Swapping source/proxy yields the complementary invalid-hit counterexample. Another 229
points on supporting boundary/edge lines are explicitly excluded. This is a finite exact control
plus the winding argument; it is not a robust floating-point implementation.

We also fit separate source/proxy cones on the **same already built geometry**, without tuning
or producing a new runtime. Across 20,844 reduced-patch/view pairs, a proxy-only cone adds 308
potential hit-certificate pairs beyond the old combined cone, and a source-only cone adds 1,422
potential miss-certificate pairs. Separately fitted cones need not have nested acceptance regions;
the old combined certificate can still be retained. These counts are **not weighted by actual
node visits, hit/miss outcomes, or query costs**. They do not establish useful performance and
cannot be reported as a speedup. A two-stage asymmetric query may pay for a proxy and then a
fine query when the outcome is not certified. Full-box segment-span guards remain necessary.

## Prior-art limits and decision

[GPUOpen 2022](https://gpuopen.com/learn/why-multi-resolution-geometric-representation-bvh-ray-tracing/)
describes stopping BVH traversal at internal nodes and using approximate geometric/shading
responses, and cites earlier RLOD plane proxies. Therefore node-local representations and
reusing BVH traversal are established. Its bias/LOD goals differ from this exact binary-coverage
condition; the architectural overlap still cannot be claimed as a new contribution.

[N-BVH, SIGGRAPH 2024](https://iliyan.com/publications/NeuralBVH/) integrates neural ray-query
representations with classical BVH queries. Its author abstract was accessible; the full PDF was
too large for the browsing tool. It is not an exact local-patch guarantee, but excludes claiming
generic local replacement of BVH ray-query work as new. No runtime comparison was performed.

[Bethe et al., CGF 2020](https://doi.org/10.1111/cgf.14008) already uses path-traced importance,
shadow-silhouette information, and error quadrics to guide reduction. Merely switching the
objective to shadow/illumination importance would not fill the novelty gap.

Stop expanding the **combined-cone, fixed-cut patch** implementation on these three development
assets. It fixes the previous redundant traversal but leaves very little measured headroom and
no validated end-to-end benefit. The asymmetric implication is a precise remaining question,
not a surviving originality claim: it must be compared with established inside/outside proxies,
conservative occluders, winding-based silhouettes, and actual paid queries before more runtime
integration. The SIGGRAPH goal remains unmet; no publication-quality algorithm exists yet.

## Reproduction and authoritative artifacts

Five targeted tests cover contained fixed-boundary reduction, disabled traversal equivalence,
finite-segment rejection despite an accepted cone, cut/oracle bookkeeping, and identical scalar
types for deserialized/rebuilt trees. The structural asymmetric check uses exact rational arithmetic
for its toy control and existing frozen patch data for its eligibility count.

```
python -m unittest discover -s tools/mmgeo -p test_fused_patch_visibility.py -v
python tools/mmgeo/benchmark_fused_patch_visibility.py --out out/fused-patch-visibility-20261115-v2
python tools/mmgeo/validate_fused_patch_visibility.py out/fused-patch-visibility-20261115-v2/report.json
python tools/mmgeo/audit_fused_query_timing.py out/fused-patch-visibility-20261115-v2/report.json
python tools/mmgeo/analyze_asymmetric_patch_certificates.py out/fused-patch-visibility-20261115-v2/report.json
```

Report: `out/fused-patch-visibility-20261115-v2/report.json`, SHA-256
`ce030715cff41ca62f8201c18a4e4a02134acecceb590a0f3fc46988aec60ceb`.
The adjacent `validation.json`, `timing-audit.json`, and `asymmetric-eligibility.json` separately
bind the report and their generating sources. No production C++ or native build changed.
