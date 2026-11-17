# Visibility-aware UV branch matching screen

Date: 2026-11-17. CPU direct-light proxy only; not a full path tracer, ReSTIR estimator, or
novelty claim.

## Question

The prior geometry-only screen on Cloth and Shapes rarely changed ReSTIR-LoD's nearest-world-space
UV branch assignment. This follow-up asks whether self-visibility makes the mapping problem more
meaningful on a high-overlap case.

## Method

Use the generated Camera LOD0→LOD1 pair (590→560 triangles, 5.1% reduction). Sample 1,000 source
points by source UV triangle area. At each UV coordinate, enumerate source and target triangle hits
and build the same greedy one-to-one matching used in the paper's overlap case under two costs:

1. squared world-space distance (nearest-point baseline); and
2. RMS difference between 32 fixed Fibonacci-sphere samples of diffuse response
   `max(0,n·ω) * V(ω)`, with `V` evaluated by CPU BVH self-visibility against each LOD mesh.

The directional environment is uniform. This adds diffuse cosine and self-shadow response to the
earlier Lambertian-only signature, but omits other scene occluders, textures/materials, glossy
transport, multi-bounce paths, and actual reservoir reuse. The samples are UV-area weighted, not
camera/path weighted. The existing Python BVH is a research reference, not a production ray tracer.

## Result

All 1,000 UV samples had multiple target hits. The partial bijection mapped 997 source samples; in
three cases the source hit set had more branches than the target set, leaving the sampled branch
unmatched, as permitted by ReSTIR-LoD's partial map.

The visibility-signature assignment changed 24/997 mappings (2.41%). Across all mapped samples,
mean response-signature RMS fell from 0.010874 to 0.010850, a 0.22% decrease. Mean world
displacement rose from 0.00233 to 0.00363 of the combined bounds diagonal (+56%); p99 displacement
rose from 0.0786 to 0.1213. Among the changed pairs, mean signature RMS fell by 0.000991 while mean
displacement rose by 0.0540 of the bounds diagonal. This exposes a real tradeoff in the proxy, but
the average response benefit is small and the mapping displacement tail gets worse.

The run performed 17,444,220 AABB tests and 6,013,215 triangle tests for the 1,000-sample screen.
These are instrumented Python query counts; they are not a hardware-runtime comparison.

A separate 20,000-sample census found that this Camera asset has 2–42 UV hits on the source and
2–43 on the target at sampled UVs, with source/target hit counts differing on 249 samples. That
extreme chart stacking plus only 5.1% simplification makes it a poor stand-in for a normal textured
asset. The more aggressively reduced Shapes mesh preserves sampled fiber cardinality exactly
(14,312 single-hit, 90 thirteen-hit, 5,598 fourteen-hit UVs on both levels); therefore the local
asset set does not expose a material UV-branch-coverage failure to fix.

## Decision

Do not promote visibility-signature UV branch matching as a contribution from this result. The
screen uses one lightly simplified asset and a one-bounce diffuse self-visibility proxy. It provides
no evidence of a useful image-quality, estimator-variance, or total-cost gain. It also sits close to
[Tokuyoshi, *Efficient Spatial Resampling Using the PDF Similarity* (I3D 2023)](https://doi.org/10.1145/3585501),
which compares directional target-PDF shapes including BSDF and visibility for ReSTIR spatial reuse.
The difference—using such a signature to assign cross-LOD overlapping-UV branches—is not by itself
novelty evidence.

The surviving full-estimator hypothesis remains untested. Reopening this branch requires a held-out
asset with substantial UV-overlap ambiguity and meaningful LOD change, an actual LoD-aware ReSTIR
renderer, and a statistically convincing full-estimator error/correlation/cost Pareto gain over
nearest mapping and modern runtime reuse controls. No suitable local asset or RT hardware path is
currently available.

## Reproduction

```powershell
python -I tools/mmgeo/audit_restir_visibility_matching.py `
  --source out/restir-overlap-extension-20261117/camera/lod0.obj `
  --target out/restir-overlap-extension-20261117/camera/lod1.obj `
  --samples 1000 --directions 32 `
  --out out/restir-visibility-matching-20261117/camera_0_1.json
```

The JSON binds source, target, and script SHA-256 hashes, per-pair examples, and query counters at
`out/restir-visibility-matching-20261117/camera_0_1.json`. The small UV-bin check confirms all
source and target hit queries were nonempty; partial-map omissions arise only when the source set
has greater cardinality than the target set.

No production C++ was changed and no software tests were run.
