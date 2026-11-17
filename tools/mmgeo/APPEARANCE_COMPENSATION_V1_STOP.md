# V1 stopped: facing discontinuity prevents a reliable fitting control

2026-11-15. This is a rendering/optimization diagnosis, NOT a mesh simplification contribution.
The original recipe and implementation are preserved unchanged.

The v1 run used the prior RGB control's two-sided shader, which orients the interpolated sample
normal according to sign(n_shading dot view). The facing decision thus depends on the attributes
being optimized. At the horizon, this flips the entire shading normal and can create a jump in
the rendered value. Its derivative away from the jump is correct, but an ordinary smooth local
optimizer can stop at that discontinuity.

Observed current-mesh fit: training SSE 16.79048570 -> 11.60184523. L-BFGS-B returned success
on its relative-reduction condition after 24 iterations and 325 objective evaluations, yet the
maximum projected gradient was 0.35041181 with no active parameter bounds. Success was therefore
NOT evidence of a stationary attribute minimum. The last evaluations alternated around
11.60184523 and 11.60911282 while shrinking the step.

The saved normal parameters were independently reconstructed and re-evaluated. Along the
normalized negative gradient, the analytic directional derivative is -1.48026523. A step of
1e-9 changes one sample's facing, causing SSE to INCREASE by 0.00726758205. The central finite
difference is about +3.63e6. At step1e-11 neither side changes facing and the finite difference
returns -1.48023815, agreeing with the analytic local derivative. This is direct evidence of
the branch discontinuity, rather than merely a timeout or an assumed optimizer bug.

`out/appearance-compensation-torus-v1/stationarity-current.json` contains the full audit and
normal/recipe/code hashes. Reproduce with:

```sh
python -I tools/mmgeo/audit_normal_fit_stationarity.py out/appearance-compensation-torus-v1
```

The main process was explicitly interrupted through its own execution session; terminal exit1
was confirmed. It completed the current mesh and edge-00/edge-01 only; `partial.json` is NOT a
completed eight-candidate experiment, and there is NO valid winner or final `results.json`.
Edge-00 had optimizer failure; edge-01 stopped with projected gradient .448. Do not rank the
candidate direction from these partial scores. Do not extend just a favored candidate.

A separate v2 uses triangle GEOMETRY to choose the two-sided orientation, independent of the
fitted shading normal. This removes that particular value discontinuity while retaining
normal interpolation, renormalization, the lights, filter, candidate pool, attribute and solve
budgets. It is a different renderer contract with a fresh source reference. Old RGB audit
numbers remain valid for their documented restricted v1 shader; they must not be silently
replaced or interpreted as v2 numbers. The v1 limitation further narrows what the earlier
normal-control regressions establish about appearance.

V2 adds tests for geometry-facing/world-normal sign agreement at different windings/cameras,
independent reference shading, shading-normal horizon continuity, and analytic derivatives
across the old horizon. The complete Python suite now passes 62 tests. This is measurement
hygiene needed before algorithm research, not progress on novelty by itself.

## Real-mesh verification of the separate v2 control

`compare_facing_continuity.py` reconstructs the SAME saved v1 geometry, normal parameters and
negative-gradient direction in both renderers, rebuilding the appropriate source reference
for each. At step1e-7 the v1 directional-derivative discrepancy is 36337.9177, while v2's is
3.85e-9. At step1e-9 v2's discrepancy is 1.42e-6 (finite-difference cancellation), versus v1's
3.63e6. Thus the observed real-mesh cliff is removed by the geometric-facing contract; this
does not prove the normal-fitting optimization is globally convex or fully converged.

The checked plot is `out/appearance-facing-diagnosis/continuity.png`; the numerical artifact
`continuity.json` binds both implementations, the recipe and the original audit. Reproduce:

```sh
python -I tools/mmgeo/compare_facing_continuity.py
```

The first v2 current-mesh solve reaches its 200-iteration cap (not the old facing cliff), with
projected gradient .0726. Its original-light extra-view SSE decreases from72.72569 to59.59945,
but rotated-light SSE increases from74.88745 to88.76933. These are partial control observations,
not a completed candidate selection or a general statement about optimized normal fields.
They already show why fitting gain alone cannot establish robust relightable quality. The
complete pool and stationarity must be assessed before accepting or rejecting its ordering.
