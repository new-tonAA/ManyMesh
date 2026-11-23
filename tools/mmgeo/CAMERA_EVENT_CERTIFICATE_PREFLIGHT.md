# Candidate-ranking certificates under camera motion: preflight

Date: 2026-11-15. This is a research question and stop/go specification, not an algorithm or a
novelty claim.

## Why the broad idea is already taken

View-dependent progressive meshes already refine and coarsen incrementally as view parameters
change, exploit frame coherence, and use projected error ([Hoppe 1997](https://hhoppe.com/vdrpm.pdf)).
View-cell LOD work bounds projected error over a camera cell and reuses visibility candidates
([Chhugani et al. 2005](https://www.cs.jhu.edu/~graphics/papers/Chhugani05.pdf)). Kinetic visibility
also supplies event/certificate ideas. A generic “cache simplification decisions in a camera cell
and invalidate them on events” is therefore not a defensible novelty claim.

## Narrow question worth testing

For a fixed legal collapse pool and a fixed accumulated simplification state, can the ordering of
two candidate collapses under a filtered screen-space loss be certified over a small camera-motion
domain, using work proportional to actual ranking/visibility events rather than rerendering every
candidate throughout that domain?

The proposed distinction is the *path-dependent filtered loss ordering*: after each committed
collapse, the residual image changes, and the relevant object is the sign of the difference between
two candidate losses, not only a per-operation maximum geometric deviation. Even this distinction
may be subsumed by earlier view-dependent visual-error methods; literature review must include
image-driven simplification, projected-error bounds, occlusion-aware LOD, and kinetic visibility.

## Falsifiable first experiment (offline oracle only)

1. Freeze a real legal candidate pool at a mesh state and record exact operation IDs, current
   filtered residual, camera path, sample pattern, and renderer parameters.
2. At each camera sample along a short smooth orbit, exhaustively rerender every candidate and
   record exact loss ordering. This is the oracle; it makes no speed claim.
3. Measure how often the winner changes, how far the winner's margin is from zero, and whether
   changes coincide with candidate-support, silhouette, or depth-order events.
4. Test a conservative pairwise margin certificate only after the oracle establishes useful
   temporal coherence. Any certificate must be compared with the exact oracle at every sampled
   view and may only claim numerical sampled validity until a formal bound is proved.
5. Count the work to build and update certificates, including invalidation, raster/filter support,
   and candidate regeneration. Compare with fresh QEM, fresh geometry coverage/depth ranking, and
   full filtered-image ranking under the same mesh, face budget, and frame-time budget.

## Stop conditions

- Stop if exhaustive winners change frequently or at near-ties that make exact invalidation dense.
- Stop if event/support changes invalidate most candidates, or certificate maintenance costs as much
  as full candidate evaluation.
- Stop if the filtered criterion does not choose valuable candidates that geometry controls miss.
- Stop if an existing method already provides the same path-dependent ranking guarantee.
- Do not implement a dynamic data structure or touch the production ranker before this preflight
  passes. SIGGRAPH 2025's *Dynamic Mesh Processing on the GPU* already covers generic dynamic
  topology, patch-local updates, and conflict handling; those cannot serve as the novel mechanism.

## Current evidence and status

The prior fixed-view compensation pool selected the same `edge-07` as the cheap coverage/depth
control. Its small held-out relighting differences were mixed, and the expensive precision
continuation was stopped after three of nine states at its preregistered decision gate. The existing
real-candidate interaction audit found sparse large cross terms but no changed selected pair or
selected-output benefit at its two-collapse budget. None of this establishes that camera-motion
certificates help; it motivates requiring an exhaustive, motion-aware oracle before implementation.

Status before the first oracle: no new algorithm, implementation, quality gain, speed gain, or
novelty had been established. The first frozen-pool result follows below.

## First frozen-pool oracle (2026-11-15)

Added `audit_camera_rank_stability.py`; it freezes the first 48 candidate IDs from the existing
fragment-transaction report and exhaustively evaluates the same candidates over a camera orbit.
This is exact only for the existing sampled orthographic depth/coverage renderer, source mesh,
initial candidate placements and independent one-collapse edits. No operations are committed, so
it does not model changing legality or a sequential simplification path. Artifacts and script hashes
are in `out/camera-rank-stability/`.

| Asset / views | Distinct winners | Winner flips | Adjacent rank ρ (mean / min) | Adjacent top-10 overlap (min) | Winners with zero loss |
|---|---:|---:|---:|---:|---:|
| Torus / 32 | 3 | 5 | 0.987 / 0.936 | 9/10 | 0/32 |
| Monkey / 8 | 4 | 3 | 0.722 / 0.564 | 6/10 | 7/8 |
| Pirate / 8 | 4 | 3 | 0.908 / 0.786 | 7/10 | 8/8 |

The 32-angle Torus sweep took a median 2.06 seconds/view in Python. Monkey and Pirate took 14.69
and 6.92 seconds/view respectively at the same 128x128, 3x, σ=0.9 setup. These costs include
per-candidate image evaluation and are not a runtime benchmark. Between neighboring samples,
90–100% of the 48 candidate scores changed by more than 1e-14. That suggests a naive event cache
would invalidate densely; it does not rule out a useful pairwise margin certificate, because most
adjacent rankings remain correlated.

The dataset is too small and fixed-pool to establish a general conclusion. Torus shows persistent
high rank correlation with a few near-tie winner flips; Monkey/Pirate show weaker rank coherence,
and their selected winners are usually zero-loss at this discrete sampling, making winner identity
less meaningful. More importantly, no certificate has been constructed or costed. This pilot does
**not pass the implementation gate**: its signal is not strong enough to justify a dynamic data
structure or production integration, and it does not establish a SIGGRAPH contribution. Preserve it
as a bounded screening result. Reopen only if an independently defined, conservative, low-cost bound
can be evaluated on a regenerated pool and beats full re-evaluation while matching the exact oracle.

## Localized Torus ranking flip (2026-11-16)

Added `probe_camera_event_localization.py`. The capture and candidate-report SHA256 values match the
32-view oracle exactly. For frozen candidate 1656 versus control 2275, a 49-angle sweep followed by
bisection found a single 3x supersample whose coverage differs over a finite camera interval:

- At sample `(y=190, x=110)`, source triangle 567 and its collapsed counterpart both cover the sample
  at the interval start. At `2.30017737315273` rad the source triangle's edge leaves the sample,
  while collapsed triangle 567 (vertices `[283,296,272]`) still covers it. This starts a one-sample
  coverage discrepancy. The raster-predicate transition is bracketed within `5.51e-14` rad by the
  current oracle's `1e-10` barycentric inside tolerance; this is not a formal geometric root bound.
- At `2.32886658782779` rad the collapsed triangle's own edge leaves the sample and the discrepancy
  ends. In between, the filtered loss for candidate 1656 is about `1.18e-3`, versus roughly
  `1.4e-6`–`1.8e-6` for candidate 2275. Before and after the interval, candidate 1656's loss is
  below the control. The sampled winner therefore depends on whether the camera lies inside this
  narrow coverage-difference interval.
- Sensitivity is severe: across the same 2.29935–2.31065 rad sweep, candidate 1656 wins at all 25
  tested angles for 1x and 2x sampling, while candidate 2275 wins at all 25 angles for 4x and 6x.
  At 3x, candidate 1656 wins only 4/49 angles and 2275 wins 45/49. The 4x/6x runs also see
  different numbers of raw coverage samples. These are separate sampling configurations, not a
  claim that their loss values are directly comparable.
- A 3x subpixel phase ablation shifts the projected source and candidate together by ±0.10 screen
  pixels in x/y. For phases `(-.10,-.10)`, `(-.10,+.10)`, and `(+.10,-.10)`, candidate 2275 wins
  all 25 sampled angles. For `(+.10,+.10)`, the coverage discrepancy ends at `2.301493673243` rad;
  candidate 1656 wins 20/25 angles and 2275 wins 5/25. Thus the event window and winner change
  under a small subpixel phase shift, even at fixed resolution and filter.

This localizes a real discontinuity in the **sampled** candidate loss, but it weakens the proposed
ranking-certificate story: the winner is not stable to raster sample density/phase, and one
candidate/sample pair is not evidence that event enumeration is sparse or cheaper. No path-dependent
loss certificate, event-generation cost, production renderer result, sequential collapse, PBR
quality gain, or speedup has been measured.

The generic event mechanism is also prior art. Popescu et al.'s *Complex VEs on All-In-One VR
Headsets Through Continuous From-Segment Visibility Computation* computes, per pixel center, camera
translation intervals by detecting when a point changes sidedness against a projected triangle edge,
then depth-composites the intervals. Akenine-Möller et al.'s time-continuous triangle rasterization
also evaluates time-dependent edge functions for spatiotemporal samples. Those works do not, from the
reviewed text, maintain a filtered image-loss ranking over collapse candidates along a rotating
camera path; that narrower combination remains only a possible distinction, not a novelty claim.
Eisemann and Décoret derive exact view-dependent simplification error bounds for arbitrary polygonal
viewcells (general 2D and particular 3D cases), with validity regions that handle face-wide error,
silhouettes, and textures. Zhang and Turk combine a surrounding-camera-space visibility measure with
QEM for visibility-guided collapse ordering. These further rule out broad claims about viewcell
error certification or camera-space visibility-weighted simplification.
Sources: [Popescu et al. (primary paper)](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf),
[Akenine-Möller et al. (primary paper)](https://fileadmin.cs.lth.se/graphics/research/papers/stoc2007/motion.pdf),
[Eisemann and Décoret (author publication page)](https://publications.graphics.tudelft.nl/papers/724),
[Zhang and Turk (primary paper)](https://faculty.cc.gatech.edu/~turk/my_papers/surfviz_vis2002.pdf).

**Decision:** the event is now a concrete adversarial case for a future bound, but it does not pass
the implementation gate. Before any dynamic structure, the next useful study must count/build
candidate-versus-source coverage intervals over a regenerated pool, compare their full construction
and update cost against exact reranking, and test phase/resolution robustness. Stop if interval
enumeration is dense or if rankings change materially under modest raster-phase changes.

## Full-orbit phase screen (2026-11-17)

To separate a narrow per-view ranking flip from an orbit-level objective, the same two legal Torus
candidates (1656 and 2275) were evaluated at 65 uniformly spaced camera angles over `[2.13, 2.48]`
radians. Each pass used the existing 128x128, 3x depth/coverage raster and Gaussian `sigma=0.9`,
with the candidate and source shifted together by each of four subpixel phases `(+/-0.1, +/-0.1)`.
For every phase, the sampled orbit-mean loss ranked candidate 2275 first. Candidate 1656's mean was
332x–1,804x the mean for 2275. This differs from the narrow 3x interval where candidate 1656 wins
4 of 49 sampled views: a local event can flip a per-view winner while the sampled orbit-average
ranking remains stable under these four phase shifts.

The 260 per-angle losses are preserved in
[`CAMERA_PHASE_AVERAGE_20261117.csv`](CAMERA_PHASE_AVERAGE_20261117.csv). The four detailed local
JSON records are `out/camera-phase-average-20261117/phase-0.json` through `phase-3.json`; each binds
the capture, candidate report, and script hashes. Input hashes are capture
`091a30aba8a3d09db01de91bfc537b7d73a42550d6b350c3f976d9e723644c31`, candidate report
`36b5cc07196eb53d6885d42fa58b9eae6844174d12e329fcfef4f15abfed3c76`, and driver
`591b883158ec91ef364716311291358235585048ec241421c670bef08928fb3b`. This is a two-candidate frozen-pool screen, and
the 65-angle average is a numerical quadrature, not an exact continuous-camera integral. It does
not establish an algorithm or a SIGGRAPH contribution. It weakens the ranking-certificate framing
and motivates a separate falsifiable question: can an event-driven evaluation of the *integrated
filtered image loss over a camera path* beat a well-sampled multi-view baseline in decision quality
and total cost? Any such work must include exact raster/filter event costs, compare against the
existing image-driven simplification baseline, and stop if ranking or benefit does not generalize
across assets, paths, phase, and resolution.

## Multi-asset finite-orbit subset regret screen (2026-11-18)

Extended the frozen 48-candidate pool to 16 uniformly spaced angles for Pirate and Monkey, retaining
the existing 32-angle Torus report. For each report, scored candidate means on systematic phase
offsets and 500 deterministic random angle subsets, selected the subset-mean winner, and measured
its regret against the winner over that report's full sampled orbit. Regret is normalized by the
median candidate's full-orbit mean loss. This is a finite-orbit diagnostic: Pirate and Monkey have
16 oracle angles (not a dense or continuous integral), candidates are independent single collapses,
and subset construction / rendering cost is not measured as a speedup.

| Asset | Orbit samples | Full-orbit winner | Zero candidate-view scores | Samples at first tested >=90% winner match | Worst normalized regret at that sample count |
|---|---:|---:|---:|---:|---:|
| Torus | 32 | 2275 | 0% | 4/32 (96.9%) | 0.712x at 4 views; 0 at 8 views |
| Pirate | 16 | 2588 | 5.1% | 12/16 (95.0%) | 39.62x |
| Monkey | 16 | 42909 | 7.0% | 12/16 (93.6%) | 194.4x |

At half the orbit, Pirate and Monkey winner-match rates were 73.9% and 73.5%; their p95 normalized
regrets were 39.62x and 194.4x. Winner identity is tie-sensitive when some candidates have zero
loss, so report both winner-match and full-orbit regret. The results reject a cheap, generic sparse
view approximation for this frozen pool: Torus is unusually easy, while Pirate and Monkey require
most of the sampled orbit to control tail regret. They do not test an event-integrated algorithm,
which remains unsupported and is not promoted to an active candidate.

Reproduction:

```powershell
python -I tools/mmgeo/audit_camera_rank_stability.py out/filter-real-candidates/pirate.json out/fragment-transactions-cost-audit/pirate.json --frames 16 --out out/camera-rank-stability/pirate-pool0-16.json
python -I tools/mmgeo/audit_camera_rank_stability.py out/filter-real-candidates/monkey.json out/fragment-transactions-cost-audit/monkey.json --frames 16 --out out/camera-rank-stability/monkey-pool0-16.json
python -I tools/mmgeo/summarize_camera_orbit_sampling.py out/camera-rank-stability/torus-pool0-32.json out/camera-rank-stability/pirate-pool0-16.json out/camera-rank-stability/monkey-pool0-16.json --out out/camera-rank-stability/subset-regret-20261118.json
```

The analysis uses NumPy `default_rng(9173 + k)` and 500 random subsets per subset size, in addition
to all systematic offsets when the view count is divisible by `k`. Analysis script SHA256 is
`944e2fe57c963365a0d88abf876e3c474d98c016596a40c52033fee675e03c48`. Frozen report SHA256 values:
Torus `ec089179fe7c7cd7e73a8c8c4145755af42d2e0e28099d470dd41a2134d8c9ae`, Pirate
`4cf62dbcf9c28197bac0a5cc8e5e2ba080c6c5a350515b107c98a82d7e90d2ef`, Monkey
`13f3a3cf37dd3e5c94611b25a983e12e42c0d681f69cafcbea406e9c5a17f81e`; aggregate JSON hash
`3751d8039237a9fe2e78e9934ac6eba6271b0d4f804a03419c1eb1a975bf0c10`.

**Decision:** do not pursue generic sparse-view selection or event-driven caching based on these
results. Reopen only with an event method that has a clear cost model and demonstrably lower total
work than dense image-driven scoring on held-out assets, paths, phases, and resolutions. Neither this
screen nor the two-candidate orbit preflight establishes a new algorithm, a quality gain, or SIGGRAPH
readiness.
