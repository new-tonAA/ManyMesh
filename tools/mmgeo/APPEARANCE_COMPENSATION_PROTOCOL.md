# Fixed-budget normal fitting on current legal collapses

2026-11-15. A classical inverse-rendering decision control. No novelty or optimality claim.
Implements the smallest experiment in APPEARANCE_RECOVERABILITY_PREFLIGHT.md.

## Frozen inputs and choices

Before any shading measurements, `appearance_compensation_probe.py prepare` replays source
Torus QEM to the saved 288-triangle checkpoint, verifies all saved positions/connectivity,
and extracts the first eight distinct CURRENT legal QEM edges at their first legal placement.
It respects heap versions, link/local-quality gates and original accumulated source quadrics.
It does not reinitialize the quadrics on the coarse mesh. All proposals remove two triangles.
The complete pool is saved to `out/appearance-compensation-torus-v1/proposals.json`, SHA256
`4f81610a116b5d38b2bb6b3c447ea468f9c1e2a2070188068bfbd79cac39467d`.

Positions/topology are fixed while fitting each case. A normal is parameterized by
normalize(n_derived + t1*x + t2*y), where t1,t2 are an orthonormal tangent frame and each scalar
is in [-.5,.5]. This gives two scalars per used vertex and at most atan(sqrt(.5)) = 35.27 degrees
tilt. The domain is anchored separately on each mesh's derived normals; it is a restricted
geometry-dependent attribute policy, not a source-authored wedge transfer or unrestricted normal
map. Every proposed mesh has the same attribute count; the current mesh naturally has one extra
surviving vertex. There are no extra wedges, material parameters, texture pixels or view-specific
attributes. Unused vertices have no optimization variables.

Every case, including the current mesh, starts at zero and uses L-BFGS-B with the SAME 200-iteration
cap, ftol1e-11, gtol1e-5, maxls30 and maxcor10. Retain the optimizer status/message, actual number
of evaluations, objective trace, boundary counts and projected gradient. A finite local solve is
an attainable score, NOT E*, a global minimum, a lower bound or matched convergence accuracy.
The renderer has two-sided orientation and clamped diffuse/specular lobes; derivatives are valid
away from their nonsmooth sets. Line-search failures or incomplete solves must be disclosed.

Training uses three azimuths .13+2*pi*k/3, the previous fixed lights, ambient .06, diffuse plus
exponent-64 Blinn-Phong strength .2, source-normalized orthographic cameras, 128px, sample scale3,
Gaussian sigma.9 followed by box downsampling. Geometry is fully rasterized separately for every
proposal before fitting: frozen ownership is used only while its geometry remains fixed. The
objective includes all RGB pixels, coverage changes and filter halos, with zero background.

The derivatives propagate through vertex-normal normalization, barycentric interpolation,
sample-normal renormalization, facing, lighting, Gaussian convolution and box downsampling.
The filter uses SciPy convolution with an explicit adjoint; tests check equality to the prior
renderer, filter dot-product identity, nonlinear objective finite differences, and a known
recoverable smooth-normal example. Every fitted training score is also independently recomputed
with the unmodified prior shading implementation before accepting the case.

## Evaluation and decision

Choose four candidates solely on training data: minimum source QEM cost, minimum rendered
coverage/depth SSE, minimum fixed-normal RGB SSE, and minimum fitted-normal RGB SSE. Fitted
and fixed deltas each subtract the corresponding current-mesh score, so an optimized after-state
is never compared with an unoptimized before-state. Save every candidate, not just winners.

For each case, evaluate BOTH derived and fitted normals at twelve azimuths 2*pi*k/12 under
the original lights and a second setup with all light directions rotated .7 radians about
world Y. These are excluded from fitting/selection, but the asset and original orbit have been
used in earlier development. This is NOT an independent asset test or broad relighting evidence.
Report per-view results, aggregate scores, and worse-view counts. A lower training score alone
is not sufficient. Timing includes setup, fitting and evaluation separately; no native comparison
or dynamic incremental update is implemented.

If the fitted winner differs, compare its actual extra-view/light errors to the fixed-RGB and
geometry winners WITH equally fitted normal budgets. Quantify ordering changes and their size.
If unconverged scores or a small margin leave the ordering uncertain, refine ALL cases with the
same additional budget in a separately recorded continuation, rather than extending only a
preferred candidate. If the fitted ordering offers no useful measured benefit, stop this
candidate direction as prescribed in the preflight. A benefit merely motivates research on
cheaper incremental evaluation; normal fitting or this experiment is not a new contribution.

## Environment and reproduction

The installed SciPy emits a warning that NumPy 2.5.4 exceeds its supported <2.5.0 range. Do not
silence this warning or present this environment as a supported deployment. The numerical checks
above passed, and package versions are frozen in the recipe. Any later supported-environment
replication must be recorded as another run and checked, not silently merged into these timings.

```sh
python -I tools/mmgeo/appearance_compensation_probe.py prepare --out out/appearance-compensation-torus-v1
python -I tools/mmgeo/appearance_compensation_probe.py measure --out out/appearance-compensation-torus-v1
```

Preparation rejects an existing recipe. Measurement verifies its input hashes and rejects an
already completed output. Each completed case is written to `partial.json`; only the terminal
`results.json` plus a verified process exit establishes experiment completion. Normal arrays
are saved with output hashes. No production C++ files are changed by this experiment.

## V1 stop and separate v2

V1 was explicitly stopped after a [verified shader-facing discontinuity](APPEARANCE_COMPENSATION_V1_STOP.md)
made the normal-fitting scores unsuitable as an optimized-attribute comparison. It has only
three completed cases; no final ranking is claimed. This was not a process timeout.

V2 chooses two-sided orientation from triangle geometry, independently of optimized shading
normals. It uses the SAME frozen eight candidates and all remaining protocol choices. The
reference source and every mesh are re-rendered with the v2 contract; no old shader scores are
mixed into the comparison. Its FINAL recipe SHA256 is
`cc59f5e5ab2cf045965aeb37a0d325b9b38c87623e1dc32341d33c583af67ec7`.

```sh
python -I tools/mmgeo/appearance_compensation_probe_v2.py prepare --out out/appearance-compensation-torus-v2
python -I tools/mmgeo/appearance_compensation_probe_v2.py measure --out out/appearance-compensation-torus-v2
python -I tools/mmgeo/summarize_compensation_probe.py out/appearance-compensation-torus-v2
```

Only measurement completion, independent training-score checks, the final artifact and verified
exit0 establish the full v2 outcome. The environment compatibility caveat still applies.

## Uniform precision refinement and resource failure

The first completed v2 cases all hit the 200-iteration cap with appreciable projected gradients.
To test ranking stability, the next stage gives ALL nine states the same additional 800-iteration
L-BFGS-B cap, maxcor50, ftol1e-12, gtol1e-5, maxls30, starting from their saved 200-step parameters.
It adds no attribute variables. This is another finite local solve, not a global optimality proof.
Its source code and complete case list are bound in a separate plan before the first continuation.

An initial process-pool attempt was denied the Windows worker pipe. The approved escalated retry
started three workers, but concurrent allocation caused the original v2 parent to fail on a
3.38MiB NumPy allocation (session85465, verified exit1). The refinement run was explicitly stopped
through session1945, verified exit1. Neither attempt completed a refinement case; their `stop.json`
records remain in `out/appearance-compensation-torus-v2-refined{,-run2}/`. No measurements from
these stopped attempts are used as a completed result or as an algorithmic failure.

`complete_compensation_probe.py` resumes the original frozen protocol sequentially, retaining
the six completed states (current through edge-04), binding their original journal and normal
hashes in `recovery.json`, and independently reconstructing/re-evaluating their saved parameters.
It fits only the three unfinished cases using the SAME frozen `Problem.fit` routine and budget.
The final artifact binds this recovery implementation in addition to the original recipe.
Inherited timings remain unchanged; recovery invocation time excludes previous failed/paused
work and must not be called total experiment time. The normal arrays and full pool are checked
by `summarize_compensation_probe.py` before making any selection claim.

Subsequent continuation uses `serial_refine_compensation_probe.py`: one process, one case at a
time, requesting one BLAS/OpenMP thread before numerical-library imports. It keeps the SAME
extra solver budget for every case, stores each completed case atomically, and can resume from
its bound prefix without re-fitting completed cases. Thread requests and both implementation
hashes are in its plan. Changes to resource use are documented, not presented as algorithm speedup.

```sh
python -I tools/mmgeo/complete_compensation_probe.py out/appearance-compensation-torus-v2
python -I tools/mmgeo/summarize_compensation_probe.py out/appearance-compensation-torus-v2
python -I tools/mmgeo/serial_refine_compensation_probe.py out/appearance-compensation-torus-v2 --out out/appearance-compensation-torus-v2-refined-serial
python -I tools/mmgeo/summarize_compensation_probe.py out/appearance-compensation-torus-v2 --refinement out/appearance-compensation-torus-v2-refined-serial
```

The serialization provenance test checks that adding the parent's final derived delta scores
preserves the saved-state binding, while changing its parameters or cameras invalidates it.
The Python suite passed 63 tests. Full original and refined results, optimizer status and
stationarity remain required; partial ordering is not an accepted contribution.
