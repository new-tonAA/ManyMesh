# Render quality within saved ManyMesh cuts

The [assembled-cut audit](HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md)
found edge-valid cuts at the upstream face cap on five of eight development
meshes. Their geometric error objective produced worse image quality than
upstream. This follow-up tests how much of that gap can be recovered by
selecting on rendered quality within the same saved hierarchies.

## Protocol

- Keep the [upstream clusterlod depth 1](../mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md)
  face cap for each asset and the same no-duplicate, directed-edge, and
  complete leaf cover constraints. Check each solver result independently.
- Enumerate at most twelve distinct cuts per asset. Use four solves with
  source-face-weighted accumulated geometric error, two with face count,
  and six with seeded random per-node objectives. Exclude each previous
  leaf cover as it is found. The first solve is the geometric control.
- Render the same eight orthographic views at 192x192 with four samples per
  pixel. Fit on view IDs 0, 2, 4, and 6 using mean LDR-FLIP. Evaluate the
  chosen cut on IDs 1, 3, 5, and 7. The cut policy uses the four fit scores
  only. The pool's best result with hindsight is reported as a separate
  diagnostic. Upstream scores come from the same four held-out views.

## Results

The eight graphs yielded 44 distinct legal cuts. Three had no cut at their
cap. The pool is complete for 263198 and 191968, where the solver exhausted
the alternatives. The twelve-cut limit was reached on the other three assets
with feasible cuts.

| Asset | Legal cuts scored | Chosen faces / cap | Held-out LDR-FLIP, geometric | Fit selection | Pool best with hindsight | Upstream |
|---|---:|---:|---:|---:|---:|---:|
| 263198 | 2 | 140 / 226 | 0.004648 | 0.004648 | 0.004648 | 0.002738 |
| 44710 | 12 | 1,564 / 1,586 | 0.029625 | 0.016039 | 0.016039 | 0.003699 |
| 191968 | 6 | 408 / 530 | 0.010888 | 0.010888 | 0.010888 | 0.002136 |
| 383021 | 12 | 6,894 / 6,894 | 0.003344 | 0.003344 | 0.003344 | 0.000385 |
| 257594 | 12 | 17,222 / 17,222 | 0.045351 | 0.042818 | 0.042332 | 0.003170 |

Relative to the geometric control, the fit selection lowers mean held-out
LDR-FLIP by 0.003224. Its paired 95% asset-bootstrap interval is
[−0.008658, 0.000000] for fit minus geometric. Three assets tie and two
improve. Relative to upstream, the fit selection has mean LDR-FLIP
**+0.013122** (95% interval **[+0.003698, +0.026644]**). Both intervals use
20,000 paired resamples with seed 20261122. The fit selection loses to
upstream on all five assets, as does the best cut in each measured pool.
The run took 68 seconds on the development laptop including the solves
and image scoring.

Rendered selection matters on two assets, but the tested procedure leaves
the upstream quality gap intact. Close this reranking formulation. The
results do not bound the unexamined cuts in the three capped pools. This
development experiment uses historical graph exports, reused static assets,
and flat shading. It does not establish a production rendering result.

Generic image-driven simplification is established, including the use of
rendered differences to choose geometric edits. This experiment uses rendered
differences to rerank frozen cuts. [Prior work by Lindstrom and Turk](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)

## Reproduce

Use the [graph export commands](HISTORICAL_CUT_TOPOLOGY_AUDIT_20261122.md#reproduce).
Run from the repository root.

```powershell
python tools/mmgeo/bench_saved_cut_view_rerank.py --receipt out/upstream-clusterlod/historical-full-witness/receipt.json --upstream tools/mmtrain/upstream_clusterlod_20261122.json --upstream-dir out/upstream-clusterlod/validation --out out/upstream-clusterlod/saved-cut-rerank.json
```

See the [receipt](saved_cut_view_rerank_20261122.json) for every attempted
solve, selected node ID, and per-view metric.
