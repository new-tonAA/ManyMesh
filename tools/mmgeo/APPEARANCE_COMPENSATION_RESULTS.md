# Fixed-budget compensation probe: complete 200-step results

2026-11-15. One inspected Torus checkpoint; existing normal-fitting method family.
No novel simplifier, optimized-attribute minimum, generalization or on-demand performance claim.

The frozen v2 experiment is complete: current mesh plus all eight legal collapses. The original
process failed from concurrent memory allocation; sequential recovery validated its six saved
normal states and finished the remaining three with the unchanged frozen fitter. Recovery
session68129 exited0. `results.json` and the independent summary validate the complete pool,
source/code/geometry/normal hashes, exact actual face counts, parameter bounds, unit normals,
camera populations, per-view sums, recipe and recovery implementations. The old six-case journal
was reconstructed EXACTLY from the final cases (before adding their derived deltas) and matches
its recorded SHA256 `5fade93e2c4c39cb4a5946407877e6016cf766d77cb3fe0bda1ea02399b80a65`.
It is preserved as `inherited-journal-reconstructed.json`.

Data: `out/appearance-compensation-torus-v2/{proposals,results,summary,recovery}.json`.
The source has1152 faces, the current mesh288 and every candidate286. All eight proposed meshes
have143 used vertices and286 normal parameters; the current mesh has144 vertices and288 parameters.
The legal domain, fitting lights/views and full solver configuration are in
[the protocol](APPEARANCE_COMPENSATION_PROTOCOL.md). These are separate geometric-facing v2 scores;
they must not be substituted into the earlier shading-normal-facing audit tables.

## Complete population

Training is three fixed cameras/original lighting; testing is twelve extra cameras under the
original lights and twelve under a .7-radian world-Y light rotation. Lower SSE is better.
All test scores below use fitted normals. Every case reached the200-step cap, so NONE is a
verified stationary local solution or E*. The projected-gradient range is .0191 to .0814.

| Case | Fixed-normal training SSE | Fitted training SSE | Extra-view SSE, original lights | Extra-view SSE, rotated lights |
|---|---:|---:|---:|---:|
| Current | 17.345333 | 12.228047 | 59.599449 | 88.769326 |
| edge-00 | 17.162016 | 12.243154 | 59.894550 | 88.754310 |
| edge-01 | 17.571552 | 12.263767 | 59.658527 | 88.878469 |
| edge-02 | 17.612954 | 12.249945 | 59.693829 | 88.069624 |
| edge-03 | 18.064550 | 12.644056 | 60.110051 | 87.966505 |
| edge-04 | 17.867009 | 12.361957 | 60.137445 | 87.331381 |
| edge-05 | 17.578120 | 12.289666 | 59.361117 | 90.259625 |
| edge-06 | 18.892163 | 13.448922 | 65.412677 | 93.309411 |
| edge-07 | 17.377917 | 12.236261 | 59.733218 | 88.843093 |

Choices using training information only:

- Source QEM: edge-00.
- Actual coverage/depth SSE: edge-07.
- Fixed-normal RGB SSE: edge-00.
- Finite fitted-normal RGB SSE: edge-07.

The normal-fitting score changes the winner relative to QEM/fixed RGB, but NOT relative to the
already available coverage/depth control. Against edge-00 WITH THE SAME fitted-normal budget,
edge-07 reduces extra-view original-light SSE0.2694% (4/12 views worse), but increases rotated-light
SSE0.1000% (8/12 views worse). It offers zero decision/quality difference from the geometric-proxy
winner, since that control selects the same edge-07. Thus neither a rank reversal alone nor the
large fitting gain is evidence for a new useful decision mechanism. The training margin between
edge-00 and edge-07 is only0.00689386, and all fits are incomplete.

Within the current fixed geometry, normal fitting reduces original-light extra-view SSE18.05%
(72.725685 ->59.599449) while increasing rotated-light SSE18.54% (74.887447 ->88.769326). This is a
measured failure of this specific finite single-light-setup fitting control. It is not a theorem
that attribute fitting must hurt relighting or that a sufficiently constrained normal/material
model cannot work. The extra cameras and original orbit are development views, not unseen assets.

## Precision continuation

Every state receives the same additional800-step cap, maxcor50, ftol1e-12 and gtol1e-5, initialized
at its saved200-step point. No favored candidate is extended selectively. The accepted execution
is single-process sequential with requested one-thread BLAS/OpenMP settings, recorded BEFORE
continuation in `out/appearance-compensation-torus-v2-refined-serial/plan.json`, SHA256
`14b1f2aaa92e4dc7d75766d072c98363b8d18b320119a65f2009cb550b55e2fc`.
This continuation was later stopped at the preregistered decision gate after three states; see
the final continuation status below. There is no completed refined ranking.

Only after all nine continuation cases finish and their normal/score/provenance checks pass
may the comparison be updated. Report ranking stability, all projected gradients, all relighting
regressions and per-view failures. If refinement does not provide a useful stable decision gap
against the cheaper geometry control, stop this candidate direction. Even a positive result
would only motivate a concrete cheaper incremental method, not establish novelty.

Do not use recovery invocation time as total experiment time: the preserved original per-case
fits each take roughly115-126 seconds, and failed/paused/concurrent work is outside that partial
clock. There is no fair native or incremental speed comparison. The installed SciPy/NumPy support
warning also remains unresolved; numerical invariants passed but this is not a supported deployment.
Python suite63 passed, with no new production C++ changes.

The latest targeted systems related-work check found SIGGRAPH 2025's *Dynamic Mesh Processing
on the GPU*, which already covers fully dynamic mesh updates, patch structures and conflict
handling. See [the related-work boundary](RELATED_WORK_DYNAMIC_GPU.md). Generic dynamic topology
support or patch-local integration cannot fill the contribution gap here.

```sh
python -I tools/mmgeo/summarize_compensation_probe.py out/appearance-compensation-torus-v2
python -I tools/mmgeo/summarize_compensation_probe.py out/appearance-compensation-torus-v2 --refinement out/appearance-compensation-torus-v2-refined-serial
```

The second command requires completed continuation artifacts. The overall SIGGRAPH objective
remains open: there is currently no verified novel mechanism or quality-cost advantage.

## Uniform precision continuation: stopped by the preregistered decision gate

The 800-step continuation was stopped after three of nine states. It is intentionally incomplete;
`out/appearance-compensation-torus-v2-refined-serial/partial.json` is preserved and there is no
complete `results.json` or refined ranking. The process was interrupted after the parent pool had
already shown that fitted-normal selection and the cheaper coverage/depth control both choose
`edge-07`, while the training fit margin was unresolved and held-out effects were small and mixed.
The preregistered gate required a useful stable decision difference before spending the remaining
fits. This branch therefore did not pass its gate. The partial fits below are not a comparison of
all candidates and must not be presented as one.

| State | Training fitted SSE | Iterations | Projected gradient | Original-light extra-view SSE | Rotated-light extra-view SSE |
|---|---:|---:|---:|---:|---:|
| Current | 12.204554056 | 800 (limit) | 0.00488356 | 59.167396 | 88.904936 |
| edge-00 | 12.219214763 | 684 (converged) | 0.00269467 | 59.557205 | 88.797704 |
| edge-01 | 12.240279862 | 800 (limit) | 0.00446444 | 59.314390 | 88.640986 |

Across just these partial states, lower training SSE does not consistently predict held-out
relighting error. This is a branch stop, not evidence that compensation is ineffective in general.
Do not resume this nine-state refinement without a newly justified decision gap or a different,
lower-cost formulation.
