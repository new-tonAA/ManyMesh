# Temporal geometry research screening, 2026-11-14

Status: two implemented screening experiments, no established SIGGRAPH contribution.
Protocol: [complementary geometry](COMPLEMENTARY_GEOMETRY_PROTOCOL.md).

## Experiment 1: finite equal-budget state ensembles

Each of 144 candidate/frame cases removes exactly two triangles. Connectivity is identical across
the placement variants of a candidate. The seed and up to nine fixed alternative placements are
filtered by the unchanged geometry-only guard; no UV/material validation is implied.

| Asset | Cases / multistate | Best static SSE | Mixture SSE | Reduction | Candidates with >=10% gain |
|---|---:|---:|---:|---:|---:|
| Torus | 48 / 37 | 7.422517275 | 7.422254597 | 0.003539% | 1 |
| Monkey | 48 / 44 | 0.0177536580 | 0.0163840635 | 7.714436% | 7 |
| Pirate | 48 / 43 | 0.814547389 | 0.811344997 | 0.393150% | 7 |

No asset passes the frozen 10% aggregate gain requirement; at least two were required. Monkey's
optimizer reaches the iteration cap for some cases, but summed duality gaps bound the best
possible gain in this pool by 7.715581%, still below the threshold. Torus/Pirate bounds are
0.003539%/0.393150%. These are floating-point diagnostics, not interval-arithmetic proofs.

The mixture's predicted IID eight-frame SSE is 7.422425294 / 0.0165632685 / 0.814148187.
These values evaluate the bias-optimal weights; they do NOT solve the finite-window-optimal
weight problem, and do not model reprojection, clamping, motion, flicker or switching cost.
Offline wall times were 1.47 / 50.05 / 20.89 seconds, including oracle rendering and file writes,
with three assets run concurrently. They are not controlled runtime benchmarks.

The important baseline is the best static state from the SAME pool, not the original seed.
For Pirate, static alternative placement already accounts for most of the improvement over the
Corner seed (0.857055099 -> 0.814547389). Temporal mixing only adds the small remaining gain.

Decision: stop expanding this fixed proposal generator. The convex hull solver is a standard
diagnostic, not the new geometry mechanism. Its lower bound applies only to the enumerated states.

## Experiment 2: sampling-phase specialization and culling confound

Use all 864 archived exact candidate deltas, with hashes verified. Partition each 3x3 sampling
lattice into nine global jitter phases. A phase is safe if every changed coverage sample is zero
and the largest normalized depth change is within a given tolerance. Report the fixed sweep
0, 1e-8, 1e-6, 1e-4, without choosing a threshold after seeing the result.

At zero tolerance, additional safe phase/candidate opportunities beyond all-phase-safe candidates:

| Asset | Raw opportunities | With visible affected faces | With visible faces actually deleted |
|---|---:|---:|---:|
| Torus | 40 | 0 | 0 |
| Monkey | 222 | 0 | 0 |
| Pirate | 691 | 39 | 0 |

At depth tolerance 1e-6 these columns are 40/0/0, 222/0/0 and 694/52/4.
At 1e-4 they are 40/0/0, 259/52/18 and 714/167/47. Coverage remains exact at every threshold.

Visibility is independently audited by rendering the original full image, keeping face IDs, and
counting phase samples owned by affected/deleted faces. At strict zero tolerance none of the newly
safe opportunities deletes a face that contributed a visible sample in that phase. Thus the raw
opportunity counts do not demonstrate a benefit beyond ordinary invisible/subpixel-work culling.
Even positive visible-deleted counts at relaxed depth tolerance are only candidate opportunities,
not compatible committed batches or image-quality/total-cost gains.

Decision: do not call phase-specific culling an original simplification algorithm. Keep the
diagnostic as a control for future jointly generated states. It uses fixed archived orthographic
cameras and geometry/depth; no colors, shadows, reflections or hardware coverage conventions.

## What remains a specific research hypothesis

**Generate geometry that compensates the remaining signed error, instead of randomly perturbing
one optimized geometry or merely choosing a favorable sampling phase.** This has not been
implemented or validated here; the failed pilot does not authorize claims that it will succeed.

For current mixture residual r, a new admissible state with residual d improves the convex mixture
locally only when <r,d> < ||r||^2. This is a standard column-generation/conditional-gradient
condition, not new mathematics. A proposed geometric construction would have to exploit it to
find complementary topology/placements under the SAME triangle, attribute and transition budget.
It must compete against spending the same reference renders/optimization steps improving ONE
static mesh. A true algorithmic contribution would need an efficient geometric construction and
a cheap runtime certificate, not just applying an off-the-shelf optimizer to pre-rendered images.

For a finite IID window T, the proper objective is

    (1 - 1/T) w^T G w + (1/T) diag(G)^T w,

before motion, transitions and nonlinear reconstruction. Unlimited-history bias reduction alone
is insufficient. No unbiasedness for arbitrary opaque meshes or guarantee for unknown states is
claimed. The next design review must establish a concrete construction and compare it to
appearance-driven optimization, stochastic aggregate simplification, mesh error diffusion and
the 2026 LoD/ReSTIR work before implementing a larger dynamic system.

## Literature boundary

- [LoD with ReSTIR, 2026](https://research.nvidia.com/labs/rtr/publication/wang2026levelOfDetail/wang2026levelOfDetail.pdf),
  sections 4 and 6: maps between supplied LoD surfaces through UV space, with matching for overlap;
  assumes consistent UVs. History correspondence itself is already covered. A joint geometry
  generator would be a different research object, but difference is not evidence of usefulness.
- [Error Diffusion on Meshes](https://www.kyprianidis.com/p/smi2014/alexa-smi2014.pdf), section 5:
  applies graph error diffusion to vertex subset selection. Generic mesh error diffusion is covered.
- [Stochastic Simplification of Aggregate Detail](https://doi.org/10.1145/1276377.1276476):
  stochastic element selection with statistical alteration; general stochastic geometry is covered.
- [Frank-Wolfe primal/dual certificates](https://proceedings.mlr.press/v28/jaggi13.html):
  standard optimization machinery used in this diagnostic; no novelty claim for the certificate.
- [Screen Space Meshes](https://matthias-research.github.io/pages/publications/screenSpaceMeshes.pdf):
  screen-space surface generation is an additional necessary comparison for any sampling-conditioned
  geometry proposal. Current search is bounded, not a proof of absence of prior work.

## Reproduction and validation

Replace `monkey` with `torus` or `pirate`:

```sh
python -I tools/mmgeo/evaluate_complementary_geometry.py out/filter-real-candidates/monkey.json out/depth-candidate-trajectory/monkey.json --out out/complementary-geometry/monkey.json
python -I tools/mmgeo/evaluate_sampling_phases.py out/discrete-filter-pilot/monkey.txt --out out/sampling-phase-pilot/monkey.json
python -I tools/mmgeo/audit_sampling_phase_visibility.py out/filter-real-candidates/monkey.json out/sampling-phase-pilot/monkey.json --out out/sampling-phase-pilot/audit-monkey.json
python -I -m unittest discover -s tools/mmgeo -p 'test_*.py'
```

30 Python tests pass; seven added tests cover analytic segment optima, known irreducible bias,
opposite-error cancellation, finite IID variance, a numerical dual bound, global sampling phase
and worst absolute errors. `git diff --check` passes. No C++ changes in this research continuation;
historical full-build failures are not resolved or revalidated by these tests.

Artifacts: `out/complementary-geometry/{asset}.json`, per-candidate residual/target/weight `.npz`
archives alongside them, and `out/sampling-phase-pilot/{asset,audit-asset}.json`.
