# Direct complementary placement: frozen comparison

2026-11-14. Follow-up research request; not a passed gate or a novelty claim.
The previous fixed-state generator remains rejected. This separate exploratory test asks whether
directly optimizing complementary states changes that conclusion; it does not silently change
the previous pass threshold or reclassify its result.

For two geometry-only residuals a,b, a uniformly chosen state over T independent frames gives

    L_T(a,b) = ||(a+b)/2||^2 + ||a-b||^2/(4T), T=8.

Optimize vertex placement with this objective directly, alternating between two states. Both
start at the original Corner target, share the original collapse connectivity and remove two
triangles. Candidate positions must pass the same endpoint-distance/quality/orientation guard.
This is standard block coordinate search on a different objective, not new optimization theory.

Controls fixed before running:

- Same 144 development candidate/frame cases as the earlier placement experiments, no success
  selection. Report original seed and all unchanged cases.
- Two independent searches: static image SSE and two-state finite-history objective above.
- Eight sweeps of six signed world-axis proposals, radius 0.125 edge length times
  0.5**floor(sweep/2). Static moves its single state; pair alternates state 0 and state 1.
- Each sweep tests its six proposals from a fixed center, then accepts the best strict improvement.
- Equal upper limits of 48 proposal evaluations each. Invalid geometry consumes a slot; thus this
  is a matched proposal ceiling, NOT a claim of equal wall time. Report actual raster counts,
  fit times and rejections separately. No reuse across the two timed searches.
- A stronger free diagnostic control is the best single static image among EVERY geometry rendered
  by the pair search, including discarded intermediate states. Also compare against the midpoint
  of the final pair if it passes the same geometry guard (one extra diagnostic render).
- Freeze test offsets -0.037 and +0.043 radians, not used for training/selection. These remain
  development assets, not independent asset generalization; no refit or test-based reversion.
- Test both mean-bias and T=8 IID expected SSE, plus coverage SSE and instantaneous worst SSE.
- Require >=10% aggregate gain over matched static search AND best-of-pair single-state control on
  at least two assets, retained on the two test offsets, before expanding the dynamic system.
- Full appearance, sequential simplification, temporal reprojection, GPU time and switching costs
  are outside this preflight. Passing this test would not establish SIGGRAPH readiness.

Support bounds include all positions reachable by the frozen search and all affected source
triangles, with filter halo. Eight static steps travel at most 0.46875 edge lengths, so a 0.5
edge-length ball around the seed is conservative (pair and midpoint are inside as well).
Baseline and both alternatives use the same rectangle and sample phase.
The finite-history formula is verified against exhaustive IID schedules on small residuals.

Execution correction: initial runs repeatedly drew unchanged triangles per proposal. Torus
completed; Monkey/Pirate were interrupted before completing. The final run caches the unchanged
depth/coverage image and combines it with affected-face redraws, preserving frontmost depth.
Both search policies use this same cache; it is existing local-redraw machinery, not a claimed
contribution. Final results use a separate output directory, with first-case-per-frame full-image
checks against the complete rasterizer. Earlier partial timings are not included in final results.
