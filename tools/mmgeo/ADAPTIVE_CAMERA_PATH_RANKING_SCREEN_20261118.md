# Adaptive camera-path ranking for legal collapses (2026-11-18)

## Status

Promising one-asset algorithm screen. Not a SIGGRAPH contribution claim, not a continuous-path
certificate, and not a production simplifier. All experiments use CPU raster depth/coverage; no ray
tracing or ReSTIR is involved.

## Prototype

`audit_adaptive_orbit_sampling.py` selects camera samples online from a fixed candidate pool. It
starts from both path endpoints and the midpoint, then bisects the interval with the largest
observed normalized score variation, candidate-rank disagreement, and winner change. Candidate
path losses are estimated by trapezoidal integration. The algorithm reads scores only at already
selected views when choosing its next view.

The screen uses frozen 48-candidate pools and a finite raster oracle. On Monkey over the segment
`[2.13, 2.48]`, 16 uniform raster views define the reference trapezoidal integral. With four queries:

| Sampler | Sample indices | Selected candidate | Regret vs. 16-view finite oracle |
|---|---|---:|---:|
| Adaptive | 0, 4, 8, 15 | 42909 | 0 |
| Uniform | 0, 5, 10, 15 | 5852 | 208.89x median candidate loss |

The 91 endpoint-anchored four-view subsets were also enumerated. Only 39.6% selected the finite
oracle winner; the adaptive schedule selected it. The best hindsight subset was `[0, 1, 2, 15]`,
which is an upper bound and not an online policy.

## Independent interstitial-view check

To test for aliasing on the training grid, the full 48-candidate pool was rerendered at all 15
midpoints between the original 16 angles. This is a new raster evaluation, not a reuse of the
finite-oracle rows. Across those held-out views, candidate 42909 ranked first by integrated loss
(mean `4.65e-10`); candidate 5852 ranked 35/48 (mean `1.04e-4`, normalized regret `43.63x` the
candidate median). Per-view winners varied across seven IDs, so an individual view winner is not a
substitute for a path-integrated choice.

The shifted segment `[2.48, 2.83]` was also screened. Candidate 42909 had zero loss at every
sampled view, and both adaptive and uniform schedules selected it. This is stability evidence for
that candidate, but it is not a second adaptive-versus-uniform win.

## Phase and resolution ablation

The result depends on the raster configuration. At scale 1, the full 48-candidate training pool
selects candidate 43972 with both four-view adaptive and uniform schedules; there is no measured
adaptive advantage. At scale 3, the unshifted screen favors candidate 42909 adaptively while the
uniform schedule selects 5852. Reusing those scale-3 choices on the 15 interstitial views at scale
1 reverses the pairwise result: 5852 has zero measured mean loss and 42909 has mean loss
`1.92e-9`. At scale 4, 42909 wins again (mean `4.28e-10` versus `9.14e-5` for 5852). This means
candidate rankings must be recomputed for the target sampling/filter configuration; the chosen
collapse does not transfer across scales.

With a `(+0.1, +0.1)` pixel phase shift at scale 3, four-view adaptive and uniform schedules both
select 42909 with zero finite-oracle regret. This is stable selection but no adaptive gain. The
endpoint-anchored random control matches the winner in 87.9% of four-view subsets under this phase,
compared with 39.6% without the shift. The single original phase therefore overstates the
algorithm's advantage.

## Naive raster-event density probe

`probe_projected_edge_sample_events.py` solves projected edge/sample-center crossing events for
the source and collapsed affected triangles. For candidates 42909 and 5852, the 0.35-radian,
128-pixel, 3x-sample path produced respectively 533 and 684 distinct event angles from 54 source
and collapsed edge records. This list is not sparse. It also contains internal-edge events that
may not change the source-versus-candidate residual, and omits unchanged-triangle visibility and
depth-order events. Thus event enumeration is not yet an efficient integral algorithm. A future
version must first prune to events that change the *visible residual* and account for the pruning
cost; if that work approaches repeated patch redraw, stop.

## Visible residual-event filter

`probe_visible_residual_events.py` tests each candidate edge event against the full source and
collapsed triangle coverage immediately on both sides. This measures whether the event changes the
raw source-versus-candidate coverage residual at that sample, rather than merely whether a triangle
edge crosses the sample.

| Candidate | Candidate edge/sample events tested | Events that change visible coverage residual | Fraction |
|---:|---:|---:|---:|
| 42909 | 533 | 0 | 0% |
| 5852 | 684 | 28 | 4.1% |

On the same 15 interstitial views, candidate 5852's mean filtered error is mostly coverage
(`7.40e-5`) with a smaller depth component (`2.28e-5`). Candidate 42909 has zero coverage error
and depth mean `4.54e-10`. This makes coverage-event filtering relevant to the observed difficult
pair, but does not prove its cost advantage: the current prototype tests every edge event by
re-evaluating full-mesh coverage on both sides. It also omits depth-order events and filters raw
coverage transitions, not the final Gaussian-filtered error integral.

The next algorithmic prototype is an event-updated filtered-coverage integral. Start from one
rasterized residual, process only events that toggle a source-versus-candidate coverage sample,
and update the filtered residual energy locally using the Gaussian kernel response. Between
events the raw coverage residual is constant, so its filtered squared error is constant and can be
integrated exactly by interval duration. Depth error needs a separate event-free interval
integrator. This is the current algorithm hypothesis; the required speedup and generality remain
unproven.

### Local filtered-energy update check

The prototype `probe_incremental_filtered_coverage.py` replays the 28 detected coverage toggles for
candidate 5852, updating only the output pixels in each toggle's Gaussian support. Its predicted
filtered coverage loss agrees with direct raster/filter measurements at all 31 angles in the
combined endpoint, training, and interstitial grid from 2.13 to 2.48 radians. The maximum absolute
per-view energy error is `6.51e-19` (mean `3.01e-19`), and the event-duration integral is
`1.81904e-4`.

This verifies the local Gaussian update arithmetic against the raster filter implementation for
this case. It does **not** validate event-stream completeness: the 28 toggles came from a
candidate-local edge event list, which may omit unchanged-geometry visibility changes. It also
does not measure speedup, integrate depth, or establish a win against strong simplification
baselines. Treat this as a validated component, not a complete algorithm or a SIGGRAPH result.

A denser falsification check added 127 uniformly spaced direct raster measurements over the same
camera interval. Together with the 31 earlier measurements, all 157 measured energies agree with
the event replay to within `8.68e-19` absolute error; no missing transition was exposed at those
sampled angles. This is still finite sampling, not a proof that the event list is complete between
samples. The dense check also uses direct full-mesh rasterization as its oracle, so it validates
the replay but does not establish a runtime advantage.

### Second-asset replay

The same event-generation and incremental-update scripts were applied to Pirate candidate 309,
whose 16-view mean loss in the frozen pool is `0.2649`. Its event generator produced 662 unique
candidate-local edge/sample events, of which 117 toggled visible coverage residual (`17.7%`). The
event-updated filtered energy matches direct raster measurements at 525 angles (the original 16
angles plus 509 uniform checks) with maximum absolute error `2.50e-16`. The event integral is
`0.227379`; a trapezoidal integral over the 509-point uniform grid is `0.227296`, a relative
difference of `0.0363%`. A coarser 127-point grid differed by `0.20%`, consistent with quadrature
error around the residual jumps. This is a second-asset validation of the update and integral
against dense direct sampling. The full-mesh event audit below checks event completeness on the
candidate's measured support; runtime benefit remains unproven.

### Full-mesh edge-event audit

To test whether unchanged geometry adds coverage-residual events, the audit forms a conservative
sample support from (1) samples where the affected local triangles already disagree at the path
start and (2) every sample crossed by a source or collapsed affected-triangle edge during the
path. Any later local coverage disagreement at a sample must begin at one of those affected-edge
events. For each support sample, `audit_fullmesh_residual_event_coverage.py` enumerates
edge/sample events from **all** source and collapsed mesh edges, evaluates full-mesh coverage on
both sides, and compares those toggles with the candidate-local event list.

| Asset / candidate | Full-mesh edge geometries | Support samples | Global edge events checked | Local / full-mesh residual toggles | Unmatched | Root + sweep | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pirate / 309 | 7,668 | 158 | 1,224 | 117 / 117 | 0 | 0.09 + 1.19 s | 1.29 s |
| Monkey / 5852 | 23,708 | 113 | 2,549 | 28 / 28 | 0 | 0.26 + 5.32 s | 5.59 s |

Both cases have zero unmatched transitions at `1e-7` radians. The start-mismatch samples were
already contained in the affected-edge sample set for these two candidates. This is a finite
audit of two assets, one path, and one candidate per asset, not a proof for arbitrary meshes. The
harmonic root solver and event grouping are not interval-certified, and depth-order events are not
included. The batched quartic-root solver reproduces the same 1,448 Pirate and 1,368 Monkey local
edge events as the scalar solver. The global sweep now tracks per-triangle inside states and
coverage counts, reevaluating only triangles incident to each edge event; direct start/end states
and every event-side incident state had zero disagreement. This reduces the original scalar audit
from 39.7 to 1.29 s on Pirate and from 930.5 to 5.59 s on Monkey (30.8x and 166.5x). These are
single-candidate CPU probes, not an end-to-end simplification speedup. Scoring thousands of
collapses still requires amortization or candidate shortlisting, and depth-order events are absent.

## Limits and novelty boundary

- The only informative adaptive-versus-uniform result is one Monkey asset, one short camera
  segment, one frozen 48-candidate subset, one raster configuration, and one collapse decision.
- The input capture has 3,456 initially legal candidates. The 48-candidate pool is sampled, not
  exhaustive. There is no sequential collapse trajectory or regenerated pool.
- The score measures filtered depth/coverage residuals, not full shaded RGB or PBR appearance.
- The interstitial rerender validates the selected candidate against that same 48-candidate pool;
  it does not validate unqueried candidates or generalize to held-out assets.
- Adaptive-versus-uniform benefit disappears under the tested phase shift and at scale 1. Reusing
  a candidate chosen at another raster scale can reverse the pairwise result.
- Naive edge/sample events are dense, while only a small fraction change the visible coverage
  residual. The current visibility probe finds those events by repeated full-mesh checks, so it
  has not demonstrated an efficient algorithm.
- Full-mesh edge enumeration found no additional coverage-residual toggles on the audited local
  supports for Monkey and Pirate. Batched root generation plus incremental triangle-state updates
  reduced those audits to 5.59 s and 1.29 s, but they still cover only one candidate per mesh and
  omit depth events.
- The local Gaussian update matches direct measurements for two candidates on two assets (157
  angles on Monkey; 525 on Pirate). The root solver is not interval-certified; the optimized
  full-mesh audit still takes 5.59 s for one Monkey candidate.
- We did not measure an adaptive-versus-uniform wall-time speedup. The reported view-count
  reduction is not a runtime claim.
- View-dependent simplification, image-driven collapse scoring, path-calibrated LoD metrics, and
  continuous visibility events are established neighboring work. This prototype's exact
  combination of adaptive sampling for legal-collapse path ranking remains a bounded search
  question, not a novelty assertion.

Relevant prior art: [Image-Driven Simplification (2000)](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf),
[Image-Error-Based LoD for Landscape Visualization (2010)](https://diglib.eg.org/server/api/core/bitstreams/0e6ea129-fa7f-4a40-9013-c7c834349011/content),
[continuous from-segment visibility (2025)](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf),
and [FastMesh view-dependent simplification](https://www.ifi.uzh.ch/dam/jcr%3Affffffff-82b7-d340-0000-000058d8660d/FastMesh.pdf).

## Hybrid learned shortlisting hypothesis

The user suggested combining the raster-event method with a lightweight learned mesh optimizer. A
network that directly maps a mesh to a simplified mesh is already established: [Neural Mesh
Simplification (CVPR 2022)](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html)
predicts a new triangle set, and [Neural Geometry Fields (SIGGRAPH 2024)](https://iveevi.github.io/ngf/)
and [PoNQ (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/html/Maruani_PoNQ_a_Neural_QEM-based_Mesh_Representation_CVPR_2024_paper.html)
cover neighboring learned mesh representations and neural/QEM combinations. [MeshCNN (SIGGRAPH
2019)](https://ranahanocka.github.io/MeshCNN/) already learns which legal edge collapses to perform
for task-driven pooling, and a 2026 [GNN-guided QEM method](https://www.mdpi.com/2227-7390/14/10/1610)
learns edge importance to adjust collapse costs. [Appearance-driven raster simplification
(2021)](https://arxiv.org/abs/2104.03989) and [continuous from-segment visibility
(2025)](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)
also rule out claiming learned collapse ranking, image-space simplification, or path edge events as
new in isolation.

The narrower hypothesis is a **learned proposal plus deterministic path-loss verification**. A
small model shortlists existing legal collapses using local geometry and camera/raster descriptors;
the event-updated filtered-loss evaluator then verifies candidates before the simplifier applies
them. The model predicts a path-dependent score and uncertainty, not arbitrary output topology.
Uncertain cases trigger exact evaluation or a deterministic fallback. The searched literature
shows strong neighboring components, but we have not found an exact match for predicting sparse
collapse-residual events or their filtered-loss correction and then verifying them with this event
integral. That is a bounded search result, not a novelty claim.

The first feasibility screen is implemented in `probe_learned_candidate_shortlist.py`. It uses 13
local-geometry and projected-area features, an 8-unit hidden layer (121 parameters), and leave-one-
asset-out splits over 144 examples (48 candidates each for Monkey, Pirate, and Torus). Tied losses
use average ranks, and top-5 quality is also measured by normalized loss regret. The 96-row
training folds are far too small for a generalization claim, but the MLP put an optimal-loss
candidate in top-5 on `0/3` held-out assets; mean Spearman was `0.080` and mean normalized top-5
regret `0.459`. Lower-is-better QEM priority achieved an optimal-loss top-5 on `1/3`, mean
Spearman `0.489`, and mean normalized top-5 regret `0.000065`; random ranking gave mean Spearman
`0.097` and regret `0.0031`. The current MLP is worse than QEM priority and the random baseline on
this small screen. No inference-latency or peak-RSS claim was measured. Do not scale this model
branch until more held-out assets and path/phase examples are available, or until features predict
event support/filtered-loss residuals better than QEM priority.

The notebook target remains a design budget, not a measurement: a two-layer 32/64-unit MLP with
roughly 2k-10k parameters (under 0.1 MiB of FP32 weights) and batched 32-64D collapse features.
Offline training is acceptable; CPU inference, feature construction, cold start, runtime
dependencies, and peak RSS must all be counted. Any later evaluation must split by asset rather
than camera view, report held-out top-K recall of the exact raster winner and sequential collapse
quality, and compare fixed triangle budget and fixed wall time against raster-only, QEM/Corner,
MeshCNN-style learned pooling, and learned mesh simplification.

### Integrated shortlist-to-event-verifier handoff screen

To make the proposed division of labor concrete, the leave-one-asset-out script now records the
actual five candidate IDs proposed by each ranker. On held-out Monkey, the MLP shortlist is
`[26314, 29953, 28286, 40721, 25551]`; its best candidate has exact-raster rank 10/48 and normalized
top-5 regret `0.0447`. The lower-is-better QEM shortlist is
`[29766, 21515, 42909, 40823, 26314]`; it contains the exact-raster winner and has zero top-5 regret.
Thus an exact verifier restricted to the MLP shortlist cannot recover the pool winner on this
screen, while QEM already supplies a better shortlist. This is a retrospective full-raster oracle
comparison, **not** an execution of the event verifier on those five IDs.

Reproduce the shortlist IDs with:

```powershell
python -I tools/mmgeo/probe_learned_candidate_shortlist.py `
  --out out/adaptive-camera-sampling-20261118/learned-shortlist-integrated-candidates.json
```

The current event verifier is also only a coverage-channel path integral; the complete-support
global event audit took 5.59 seconds for one Monkey candidate and is not interval-certified. A
practical hybrid therefore needs both (a) held-out top-K recall substantially better than QEM and
(b) a measured event-verification cost below the saved full-raster work, with depth/order changes
and fallback behavior included. The current learned proposal fails (a), and the event component has
not established (b). The combination is a testable architecture, not a demonstrated benefit or a
SIGGRAPH-level contribution.

The narrow next hypothesis, if this branch is revisited, is to predict *event-support / filtered
loss residual* with a tiny model trained across meshes and camera paths, then use deterministic
event processing to verify only a confidence-calibrated shortlist. This changes the learned target
from generic collapse quality to the work saved by the event evaluator. It remains speculative:
learned collapse ranking, neural mesh simplification, and continuous path visibility are established
prior art, and no exhaustive search has established novelty for this exact composition.

### Shared-event amortization check

The support sets in the Monkey reports for candidate 5852 (113 pixels) and candidate 42909 (99
pixels) have zero overlap. Candidate 5852 has 28 visible residual transitions; candidate 42909 has
none. Thus caching source edge events only at each candidate's support pixels would not amortize
across this difficult/easy pair. This is one pair, so it does not rule out overlap for larger,
spatially coherent shortlists. It does rule out assuming that candidate shortlisting automatically
creates shared event work; any proposed batch cache must measure support overlap and setup cost.

A further primary-source boundary check found [*Differentiable Micro-Mesh Construction* (CVPR
2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Dou_Differentiable_Micro-Mesh_Construction_CVPR_2024_paper.pdf),
which combines mesh optimization with multi-view rasterization losses, and [*Neural Mesh
Simplification* (CVPR 2022)](https://openaccess.thecvf.com/content/CVPR2022/papers/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.pdf),
which predicts mesh points and connectivity with a lightweight triangle classifier. Together with
continuous from-segment visibility and learned edge-collapse ranking, this closes the broad claim
that a lightweight learned simplifier plus raster loss or visibility is itself novel. The remaining
distinction would need to be the specific legal-collapse, path-event residual algorithm and a
measured advantage under strict topology/attribute constraints; the current data do not establish
either.

### Event-verifier run on the MLP's actual top proposal

To test the handoff rather than only its retrospective shortlist recall, ran the local event probe
and then the full-mesh support audit on MLP top-1 candidate 26314. The candidate's 16-view raster
loss is entirely depth error (`4.1848e-8` mean); its measured coverage loss is zero. The local
probe found 3,181 unique candidate edge/sample events over 651 support pixels and zero residual
coverage transitions. The full-mesh audit checked 34,441 events from all 23,708 source/collapsed
edge geometries over those support pixels and again found zero transitions, zero incremental or
endpoint state disagreements, and zero unmatched events. The root pass took 2.89 s and the
incremental sweep 80.77 s (83.78 s total).

This is a stronger failure of the current hybrid: the verified coverage objective cannot rank this
proposal because its sampled path error lies wholly in the unimplemented depth channel, and the
large support makes verification expensive. The audit supports finite coverage-event completeness
for this candidate at the stated floating-point tolerances; it is not an interval certificate, a
depth audit, or evidence that every candidate will be this costly. Available system memory was
3.45 GiB before and 3.32 GiB after the run. Artifact:
`out/adaptive-camera-sampling-20261118/monkey-fullmesh-event-audit-mlp-top1-26314.json`.

## Next kill gate

Repeat the adaptive decision on multiple newly sampled paths and held-out assets, using a complete
or explicitly stratified legal-candidate pool. Compare adaptive selection against fixed uniform
views, best same-budget systematic views, exact full-path raster evaluation, and QEM/Corner. Include
filter phase and resolution changes. Measure query and update wall time, selected-candidate loss on
independent interstitial views, and the resulting sequential collapse quality at matched triangle
count. Only then consider an event-derived interval bound. Kill this branch if the adaptive policy
does not consistently beat strong same-budget controls or if its ranking changes under modest path,
phase, or resolution perturbations.

## Reproduction

```powershell
python -I tools/mmgeo/audit_adaptive_orbit_sampling.py `
  out/camera-rank-stability/torus-pool0-32.json `
  out/camera-rank-stability/pirate-pool0-16.json `
  out/camera-rank-stability/monkey-pool0-16.json `
  --out out/adaptive-camera-sampling-20261118/report.json

python -I tools/mmgeo/audit_camera_rank_stability.py `
  out/filter-real-candidates/monkey.json `
  out/fragment-transactions-cost-audit/monkey.json `
  --frames 16 --angle-start 2.13 --angle-end 2.48 --size 128 --scale 1 `
  --out out/adaptive-camera-sampling-20261118/monkey-scale1-pool0-16.json

python -I tools/mmgeo/audit_camera_rank_stability.py `
  out/filter-real-candidates/monkey.json `
  out/fragment-transactions-cost-audit/monkey.json `
  --frames 16 --angle-start 2.13 --angle-end 2.48 --size 128 --scale 3 `
  --phase-x 0.1 --phase-y 0.1 `
  --out out/adaptive-camera-sampling-20261118/monkey-phase-01-pool0-16.json

python -I tools/mmgeo/probe_projected_edge_sample_events.py `
  out/filter-real-candidates/monkey.json --ids 42909 5852 `
  --start 2.13 --end 2.48 --size 128 --scale 3 `
  --out out/adaptive-camera-sampling-20261118/monkey-edge-events.json

python -I tools/mmgeo/probe_visible_residual_events.py `
  out/filter-real-candidates/monkey.json --ids 42909 5852 `
  --start 2.13 --end 2.48 --size 128 --scale 3 `
  --out out/adaptive-camera-sampling-20261118/monkey-visible-events.json

python -I tools/mmgeo/probe_adaptive_winner_holdout.py `
  out/filter-real-candidates/monkey.json `
  out/fragment-transactions-cost-audit/monkey.json `
  --ids 42909 5852 --out out/adaptive-camera-sampling-20261118/monkey-heldout.json

python -I tools/mmgeo/audit_camera_rank_stability.py `
  out/filter-real-candidates/monkey.json `
  out/fragment-transactions-cost-audit/monkey.json `
  --frames 15 --angle-start 2.1416666666666666 --angle-end 2.4683333333333333 `
  --size 128 --scale 3 `
  --out out/adaptive-camera-sampling-20261118/monkey-interstitial-pool0-15.json

python -I tools/mmgeo/audit_fullmesh_residual_event_coverage.py `
  out/filter-real-candidates/pirate.json `
  out/adaptive-camera-sampling-20261118/pirate-visible-events-309.json `
  --candidate-id 309 `
  --out out/adaptive-camera-sampling-20261118/pirate-fullmesh-event-audit-309.json

python -I tools/mmgeo/audit_fullmesh_residual_event_coverage.py `
  out/filter-real-candidates/monkey.json `
  out/adaptive-camera-sampling-20261118/monkey-visible-events-5852.json `
  --candidate-id 5852 `
  --out out/adaptive-camera-sampling-20261118/monkey-fullmesh-event-audit-5852.json

python -I tools/mmgeo/verify_batched_edge_event_roots.py `
  out/filter-real-candidates/pirate.json `
  out/adaptive-camera-sampling-20261118/pirate-visible-events-309.json `
  --candidate-id 309

python -I tools/mmgeo/probe_learned_candidate_shortlist.py `
  --out out/adaptive-camera-sampling-20261118/learned-shortlist-loao-ties.json
```

No software test suite was run. The experiments were small CPU raster probes. The builder and
renderer were not launched.
