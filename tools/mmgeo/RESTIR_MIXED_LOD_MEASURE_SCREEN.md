# Mixed-cut / per-ray LOD measure screen

Date: 2026-11-15. Literature correction and exact finite estimator control.

## Correction to the earlier opening

The [SIGGRAPH 2026 ReSTIR-LoD paper](https://research.nvidia.com/labs/rtr/publication/wang2026levelOfDetail/wang2026levelOfDetail.pdf)
explicitly states in Section 6 that its formulation does not require one LOD per object per frame;
that restriction is enforced by its implementation. Section 4.1 permits partial bijective surface
maps, Section 4.3 gives their area Jacobian and multiplies it for reused vertices, and Section 4.4
chooses a single object LOD to simplify the implementation's path-space definition. Its per-ray
future-work statement does not establish that a different estimator is necessary. The earlier
research note overstated an estimator-level opening by emphasizing the implementation restriction.

An arbitrary *frozen spatially mixed cut* still defines one scene seen by all rays. That case
must be distinguished from a geometry selection policy depending on the incoming ray, footprint,
or preceding path vertices. A measurable deterministic selector can define a primary-sample-space
integrand `F(u, L(u))`, even if the approximation is not reciprocal or does not represent a single
physical surface. Lack of reciprocity alone does not make the integral undefined. Conversely,
unbiased estimation of this approximate target does not establish unbiasedness relative to the
highest-resolution physical scene. The intended target must be fixed before discussing bias.

## Known estimator machinery

[GRIS (2022)](https://research.nvidia.com/labs/rtr/publication/lin2022generalized/) already addresses
correlated weighted samples from different domains and their shift mappings. Recent
[stochastic pairwise MIS (2026)](https://research.nvidia.com/labs/rtr/publication/hedstrom2026stochastic/)
and [compatibility-guided neighbor selection (2026)](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/)
provide additional close baselines for unbiased reuse and selecting useful spatial neighbors.
Some large PDF downloads were rejected by the browsing tool; do not claim complete full-text
comparisons for those papers. The ReSTIR-LoD paper's relevant sections were accessible.

## Exact finite control

`restir_lod_measure_preflight.py` enumerates all 16 pairs of candidate draws and all conditional
reservoir selections using rational arithmetic. The target has four atoms with area measures
`a=(1,2,3,4)`, contribution values `f=(2,5,3,7)`, and a positive resampling target
`pHat=(3,1,8,2)`. Its direct reference integral is `sum(a*f)=49`.

A canonical domain samples each atom with probability 1/4. A second source has areas
`(7,5,2,9)`, probabilities `(1,2,3,4)/10`, and either the full permuted mapping `(2,0,3,1)`
or the partial mapping `(2,null,null,1)`. These are supplied abstract correspondences, not maps
constructed from real meshes or a ray-dependent selector.

For a source atom x mapping to y, its integration weight is `aSource(x)/pSource(x)`. The shift
factor is `aTarget(y)/aSource(x)`. Choose a mixing weight `m_i(y)=1/c(y)` on covered domains,
where c(y) is the number of domains whose partial map covers y. The canonical sample covers all
targets, so these mixing weights sum to one. Resampling uses
`w_i=m_i*pHat(y)*J_i*aSource(x)/pSource(x)` and output weight `sum(w)/pHat(selected)`.
Null mappings have zero weight. These standard measure/support conditions suffice for this model.

| Control | Exact expected estimate | Error vs reference |
|---|---:|---:|
| Full map, area Jacobian and support weights | 49 | 0 |
| Partial map, area Jacobian and support weights | 49 | 0 |
| Partial map, constant half mixing weight | 34 | -15 |
| Full map, omitted area Jacobian | 139/2 | 41/2 |

The model rejects many-to-one maps rather than silently treating them as partial bijections,
and rejects uncovered target support. This is a finite control of existing theory, not a new
estimator, a simulation of ReSTIR path tracing, or proof that a particular per-ray surface map
works. In particular it contains no visibility query, BSDF, path reconnection, coupled selector,
real cluster transition, temporal reservoir correlations, or GPU runtime.

## Research decision

Do not build a new GPU path tracer merely to show area weighting or support-corrected reuse on
mixed LODs. Those requirements already have a formulation and the finite control exhibits no
new estimator gap. Downgrade **generic mixed-cut/per-ray ReSTIR mapping and weighting** as an
active novelty claim. This does not prove every per-ray problem solved; it removes the current
reason given for pursuing this branch.

A future reopening requires a concrete selector/map for which the published formulation cannot
directly provide a valid, useful shift, a precisely specified target, and a mechanism improving
quality per total time over ReSTIR-LoD plus established GRIS/MIS and compatibility controls.
An implementation restriction or support failure by itself is insufficient. No SIGGRAPH-level
contribution or renderer result has been established.

## Artifacts and checks

```powershell
python -I tools/mmgeo/restir_lod_measure_preflight.py --out out/restir-lod-measure-preflight-20261115/report.json
python -m unittest discover -s tools/mmgeo -p test_restir_lod_measure_preflight.py -v
```

The exact enumeration exited 0. Three independent contract tests passed: nonuniform canonical
sampling, refusal of uncovered support, and refusal of a many-to-one map. The report binds the
executed script hash. No C++, renderer, or GPU path was changed.
