# Depth-aware candidate protocol (2026-11-14)

## Frozen scope

Three existing real development assets (Torus, Monkey, Pirate), not unseen assets. New contiguous
orthographic camera trajectory: six frames at angles linspace(2.13, 2.48) radians, elevation
component 0.37, fixed original-mesh normalization. This trajectory was not part of the earlier
0.2/1.7/3.4-radian silhouette pilot. It is a new evaluation trajectory, not an independently
held-out benchmark after repeated tuning. No PBR, shadows, animation, mesh streaming or live
multi-collapse policy is evaluated here.

## Changes that implement the five-part diagnostic goal

1. Projected support is checked against the viewport. Counts include total, outside,
   baseline-visible affected faces, no baseline-visible face, sampled and not sampled.
   A baseline-occluded collapse can uncover a surface or move it forward, so it is **not**
   assumed safe or zero-error. A small deterministic control sample of this stratum is retained.
   Zero-error cases after reference evaluation remain in reports.
2. Opaque two-sided z-buffer selects the nearest face. Loss has separate coverage and
   coverage-premultiplied normalized camera-depth channels. Both channel SSEs are reported;
   their unweighted sum is only the diagnostic selection objective, not a perceptual metric.
   Every candidate patch redraw includes all unchanged occluders intersecting the patch.
3. Orange original edges, cyan candidate edges, yellow target and gray patch rectangle are
   exported as overlays. The fixed camera transform is also checked in a unit test. These
   overlays show all affected edges (not depth-tested line rendering). Images use fixed mappings.
4. Candidates are compared at matched actual triangle counts. The alternatives are the original
   Corner priority, local 3x reference redraw, and coarse 1x redraw + 8/16/32 total real DCT
   coefficients across both channels. This predictor **still rasterizes**. Its full cost includes
   coarse rasterization, filtering, basis setup and encoding. DCT applied to reference residuals
   is separately labeled a representation oracle, not a deployable prediction or speedup.
5. The reported evaluation is on these real assets along the new contiguous trajectory. Synthetic
   strip numbers are not mixed into the report. Adjacent fixed-candidate screen residual changes
   are reported only if the candidate occurs in both immediately consecutive frames. This is not
   motion-compensated flicker and not the temporal stability of a deployed selector.

## Correctness checks

`python -I tools/mmgeo/test_depth_candidate_pilot.py`

Seven tests passed: frontmost selection/disocclusion, full/patch equality with occluders, fixed
projection, sketch dimensions and energy, emergence of a baseline-hidden face, viewport/filter
halo and empty offscreen geometry. Full-frame redraw independently checks EVERY sampled patch
with tolerance 1e-10, outside performance timing. Exact IDs break equal-depth ties consistently.
These tests do not prove continuous coverage accuracy; pixel sampling still requires convergence.

## Commands

```sh
python -I tools/mmgeo/depth_candidate_pilot.py out/filter-real-candidates/torus.json --out out/depth-candidate-trajectory/torus.json
python -I tools/mmgeo/depth_candidate_pilot.py out/filter-real-candidates/monkey.json --out out/depth-candidate-trajectory/monkey.json
python -I tools/mmgeo/depth_candidate_pilot.py out/filter-real-candidates/pirate.json --out out/depth-candidate-trajectory/pirate.json
python -I tools/mmgeo/summarize_depth_pilot.py out/depth-candidate-trajectory/torus.json out/depth-candidate-trajectory/monkey.json out/depth-candidate-trajectory/pirate.json --out out/depth-candidate-trajectory/summary.json
```

Input capture and evaluator SHA256 are recorded. Python timings are exploratory single-pass CPU
measurements, no confidence interval or GPU/mobile performance claim. Full-frame verification and
image export are excluded from the timed patch/predictor work and reported as validation overhead,
not hidden deployment work. Capturing candidates and geometry extraction is offline and is not
included in those per-candidate costs.

## Visual audit so far

Torus frame 0 / candidate 2220: affected triangles and target lie on the same upper surface patch;
the patch covers the affected region. The 32x depth-error image remains nearly black. This verifies
plausibility of placement but is not compelling visible quality evidence. More demanding budgets,
higher resolution and material/normal evaluation remain necessary before a paper claim.
