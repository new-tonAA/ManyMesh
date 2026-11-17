# Real-mesh candidate pilot

Date: 2026-11-14. This is a diagnostic, not a paper result.

## Capture

`mm_capture_candidates` now exports the initial welded geometry and every initially legal directed Corner placement for each submesh, capped at 100,000 triangles per unit. It does not alter production ranking or submit a candidate. Captures:

| Asset | Units | Source triangles | Initially legal directed candidates |
|---|---:|---:|---:|
| Torus | 1 | 1,152 | 3,456 |
| Monkey | 1 | 15,744 | 45,746 |
| Pirate | 7 | 5,010 | 10,170 |

A deterministic priority-quantile sample of 16 candidates per view was evaluated at three orthographic camera angles. This is a small diagnostic sample, not an unbiased estimate of all candidates.

## First result and failure

The first evaluator used 3x supersampling, horizontal union intervals and Gaussian downsampling. It measured opaque coverage only; no depth, material, normal or lighting. Torus had 6 nonzero silhouette-error samples among 48 tested; Pirate had 4; Monkey had zero.

Monkey repeated at 6x and 12x with six priority-quantile candidates per view, versus sixteen in the first 3x run: all measured silhouette errors remained exactly zero in these smaller samples. These are NOT identical candidate sets, so this is not a matched-candidate convergence proof. It is an **uninformative sampled result**, not evidence the method is correct. Reference cost grew sharply: median raster time was about 243 ms at 6x and 2,009 ms at 12x for the tested candidate path. The initial 3x numbers were about 27 ms, but timings are Python and not comparable to the C++ controlled strip experiment.

Possible causes to investigate before any conclusion: selected candidates are internal/occluded; the three fixed orthographic views miss their projected support; target positions are not correctly transformed in all geometry branches; or the coverage renderer is not exposing depth changes. Add candidate screening for projected support and a depth-aware patch metric before drawing conclusions.

The evaluator had a post-capture fix changing horizontal coverage from center-hit occupancy to exact subpixel interval area. It passed neither a new full run nor a complete external validation after that edit. Existing score JSON files predate this edit and must not be mixed with new results.

## What this does not establish

- No real-asset quality improvement.
- No dynamic runtime gain.
- No comparison against Lindstrom–Turk's local image redraw under identical work.
- No novelty claim. Their 2000 work already covers image-driven edge-collapse ranking and incremental local image maintenance.
- No proof that the filtered residual vector is useful beyond the synthetic strip.

## Next executable experiment

1. Screen candidates by projected affected support and reject empty/occluded candidates explicitly.
2. Use a depth-aware patch reference: frontmost coverage/depth, not union silhouette alone.
3. Verify target projection numerically with a one-candidate visual overlay.
4. Compare 8/16/32 residual features to local patch redraw on the same candidate set.
5. Keep only held-out views/assets and report no-information cases rather than dropping them silently.
