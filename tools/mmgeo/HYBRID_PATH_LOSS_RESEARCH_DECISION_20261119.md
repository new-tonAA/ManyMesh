# Exact path loss + lightweight learning: combination decision (2026-11-19)

## Question

Can the exact filtered path-loss evaluator and a laptop-sized learned mesh optimizer be combined
into a useful, potentially novel simplifier?

## Initial learned residual pilot

The first pilot combined the two directly: exact event-integrated loss was the training target; a
small CPU MLP predicted the residual of a cheap raster score; the corrected score chose a top-K
set; the exact evaluator re-scored that set. The paired table contains 264 collapse candidates in
23 groups over eight assets.

- On 13 one-sample groups, asset-held-out MLP top-2 includes an exact minimizer in 12/13 groups,
  versus 11/13 for raster. Mean best-of-two normalized regret is 1.12% versus 2.10%.
- Across all 23 groups, MLP and raster top-4 both include a minimizer in 21/23 groups.
- Holding out a camera direction removes the apparent gain: both methods reach 11/13 top-2 and
  2.10% mean regret. Joint asset-and-direction holdout also ties at 9/11 and 2.49%.
- At 64 raster samples, the held-out path screen is already saturated at 7/7 top-1 for raster;
  MLP adds no ranking value.

This pilot does not establish runtime savings: shared event setup remains, and no sequential
collapse replay or production integration was measured. Keep this scalar-residual MLP branch
closed as a contribution claim. Reproduction is in
[`HYBRID_LEARNED_PATH_LOSS_20261119.md`](HYBRID_LEARNED_PATH_LOSS_20261119.md) and
[`audit_path_loss_residual_hybrid.py`](audit_path_loss_residual_hybrid.py).

## Prior-art boundary

The individual ingredients are established. Neural Mesh Simplification learns a lightweight
network to propose/select mesh triangles in one pass
([CVPR 2022 paper](https://openaccess.thecvf.com/content/CVPR2022/papers/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.pdf)).
Appearance-Driven Automatic 3D Model Simplification optimizes mesh and shading against image-space
differences with a differentiable renderer
([EGSR 2021 paper](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc)).
Continuous from-segment visibility computes visibility intervals analytically along a camera
translation segment ([Popescu et al., TVCG 2025](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)).
Therefore, “neural simplification + image loss,” “camera path awareness,” and “analytic visibility
events” are each too broad to claim as new.

## Exact bound replay and online implementation

I changed the combined method into an offline replay. For each candidate and each screen cell, the
event solver records an exact, nonnegative loss contribution. Evaluating a subset of cells gives a
valid lower bound on total candidate loss. The replay fully evaluates the first candidate in cheap
raster order as an incumbent, then evaluates cells for each later candidate until its accumulated
lower bound cannot beat that incumbent. It changes only work order and early stopping; the exact
winner remains the decision rule. A contribution-sorted policy is also reported as a *clairvoyant
upper bound* because it uses the unseen exact cell losses to choose work. The probe now has an
online mode that actually evaluates only the scheduled cells; a saved full evaluation can audit
that it selects an exact minimizer.

The probe and replay are [`probe_shared_envelope_raster_tile.py`](probe_shared_envelope_raster_tile.py)
and [`audit_exact_loss_cell_pruning.py`](audit_exact_loss_cell_pruning.py). The screen used 12
legal collapses, a 32x16 output tile subdivided into sixteen 8x4 cells, 8 temporal raster samples
for the cheap ordering, and orthographic path radius 1. It included rounded cube and Material
Sphere at 45° and 90° pan, plus Torus and Pirate at both directions. All audited replays selected
an exact minimizer. The check uses relative tolerances, including for near-zero losses.

| Held-out group | Fixed cell order | Cheap raster cell order | Small MLP order | Oracle order |
|---|---:|---:|---:|---:|
| Rounded Cube, pan 45° | 133/192 | 113/192 | 62/192* | 58/192 |
| Material Sphere, pan 45° | 136/192 | 77/192 | 46/192* | 28/192 |
| Rounded Cube, pan 90° | 137/192 | 93/192 | 64/192† | 60/192 |
| Pirate unit 5, pan 90° | 133/192 | 30/192 | 30/192‡ | 30/192 |
| Torus, pan 90° | 95/192 | 32/192 | 32/192‡ | 32/192 |

Counts are exact cell integrations needed by the replay to certify the selected candidate, not
measured end-to-end speedups. `*` trains on the other asset at pan 45°; `†` trains on the same
asset at pan 45°; `‡` trains on other assets at pan 45°. A second multi-asset training screen
reduced Rounded Cube at pan 90° from 93 raster-ordered cells to 93 learned-ordered cells (tie),
and Pirate from 30 to 34 (small regression); Torus remained tied at 32. When trained only on
Rounded Cube and tested on Pirate, the MLP increased the count from 30 to 142, although the exact
certificate still selected the right candidate. So far the robust gain comes from cheap raster
cell ordering, not from learning. The MLP sometimes helps within a narrow asset/path split, but
does not consistently improve on the non-learned policy under asset/path holdout.

Cheap raster cell ordering avoided 41%–84% of candidate-cell integrations in the five
nontrivial held-out groups; an easy zero-loss group required only 27/192 integrations even with
fixed cell order. In online mode, the probe includes candidate preparation, raster work, shared
event setup, and scheduled exact integration in its core wall time:

| Case | Full exact core | Online core | Exact cell integrations | Reference winner |
|---|---:|---:|---:|---|
| Rounded Cube, pan 45°, 1 raster sample, mean of two runs | 0.302 s | 0.251 s | 192 → 97 | yes |
| Rounded Cube, pan 90°, 1 raster sample | 0.323 s | 0.271 s | 192 → 113 | yes |
| Rounded Cube, pan 45°, 8 raster samples | 0.388 s | 0.346 s | 192 → 113 | yes |
| Material Sphere, pan 45°, 1 sample, mean of three runs | 1.304 s | 1.214 s | 192 → 132 | yes |

The measured core reduction is about 11%–17% for Rounded Cube and 7% for Material Sphere.
On the latter, shared event setup alone is about 0.68 s, so candidate pruning has limited impact.
The 8-sample raster order costs more than one sample and saved less time in the Rounded Cube
case. The one-sample raster can have large score error; it is used only to order work, while the
exact lower bound and complete incumbent determine the result. These timings are a small Python
prototype benchmark, not C++ production performance, and need more repetitions and meshes.

Reproduce the Rounded Cube 45° online comparison with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/rounded_cube.json --seed-candidate 72 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 32 --tile-height 16 --steps 1 --pan-angle 45 --path-radius 1 --loss-cell-width 8 --loss-cell-height 4 --out out/pathloss-captures/rounded-cube-full-1sample.json
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/rounded_cube.json --seed-candidate 72 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 32 --tile-height 16 --steps 1 --pan-angle 45 --path-radius 1 --loss-cell-width 8 --loss-cell-height 4 --online-pruning --reference-capture out/pathloss-captures/rounded-cube-full-1sample.json --out out/pathloss-captures/rounded-cube-online-1sample.json
```

## Online learned cell ordering screen (2026-11-19)

I connected a tiny NumPy MLP to the actual online exact-cell loop. The first candidate is fully
integrated to establish an exact incumbent. Later candidates are integrated cell by cell; their
partial sum of nonnegative exact cell losses is a valid lower bound, and the candidate is stopped
once that sum reaches the incumbent. The learned model only orders cells. It cannot accept a
collapse or change the winner without the exact bound. Its input is cheap-raster cell-loss share
and normalized cell coordinates; its target is the log fraction of exact candidate loss in each
cell. Training and inference require no external ML framework.

For a 12-candidate Rounded Cube screen (192 candidate-cell integrations without pruning), an MLP
trained on three other meshes at 45-degree pan and evaluated on the held-out Rounded Cube at
90-degree pan needed 29 exact cell integrations in both runs, versus 113 for raster cell ordering.
Both policies selected candidate 72, whose loss was fully evaluated; every rejected candidate had
a partial exact lower bound at least that incumbent. The raster run took 0.270-0.297 s in the
measured core. The learned run took 0.480-0.555 s including per-process training (0.275-0.318 s);
subtracting training gives 0.206-0.237 s, while inference over 12 candidates took about 0.00058 s.
That subtraction estimates the cost when one pre-trained model is reused. It is not a measured
multi-query benchmark, and the Python timings are noisy.

The cross-asset result did not transfer uniformly. On Material Sphere at the held-out 90-degree
pan, the MLP and raster both required 27/192 exact integrations; learned total core time was 1.161 s
versus 1.046 s for raster. Thus the online interface works and can cut exact calls on one controlled
screen, but current data does not show robust quality-preserving speed gains across meshes. The
NumPy ranker, single 32x16 tile, orthographic pan path, and 12 local candidates are an exploratory
prototype, not SIGGRAPH evidence. No full-resolution/color objective, sequential collapse replay,
production integration, broad joint asset/path holdout, or resource-profiled run was performed.

Reproduce the held-out Rounded Cube query with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/rounded_cube.json --seed-candidate 72 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 32 --tile-height 16 --steps 1 --pan-angle 90 --path-radius 1 --loss-cell-width 8 --loss-cell-height 4 --online-pruning --cell-order-policy learned --cell-order-train-captures out/pathloss-captures/material-sphere-cell-pruning.json out/pathloss-captures/pirate-unit5-cell-pan45.json out/pathloss-captures/torus-cell-pan45.json --out out/pathloss-captures/rounded-cube-online-learned-pan90.json
```

The next gate is a frozen model evaluated on several independent meshes and path directions with
paired raster/learned wall-time repeats. Keep the simple raster policy if the learned advantage
does not persist after training is amortized.

## Position baseline and sparse shared visibility

An offline replay tested a simpler spatial baseline on four meshes at 45° and 90° pan. For each
held-out mesh and pan, the training data came from the other three meshes at the opposite pan.
The prior is the average fraction of candidate loss in each cell, computed on informative training
candidates. Raster scores still order candidates and cells. The prior breaks ties in cell raster
scores. Across the eight captures, raster ordering used 443 cell integrations and raster with the
position tie-break used 307. The latter reduced work on three captures and tied on five, with the
same minimum loss on all eight. Position alone used 321. These captures use the same local tile
layout and eight temporal raster samples. This is a count replay, and the earlier online MLP used
different splits or raster budgets. It motivates a matched comparison against a position baseline.

A separate optimization reduces the shared visibility work paid before any candidate can be
pruned. For each screen axis, subtract the maximum path displacement from the lower bound and the
minimum displacement from the upper bound. The initial bounds contain all changed source
triangles and all replacement vertices. Projection is affine for the orthographic image-plane
translation in this probe. A pixel
whose entire footprint lies outside those swept bounds has zero filtered difference at every time.
The probe omits those pixels from the event cache and, at the remaining samples, partitions only
the intersected faces. This preserves the grid of loss contributions for downstream pruning.

| Model and path | Cached raster taps | Shared setup | Full solver core |
|---|---:|---:|---:|
| Rounded Cube, 90°, one tap per pixel | 512 → 28 | 115 → 38 ms | 313 → 129 ms |
| Material Sphere, 90°, one tap per pixel | 512 → 16 | 666 → 279 ms | 1,358 → 755 ms |
| Rounded Cube, 0°, four taps per pixel | 2,048 → 72 | 204 → 15 ms | 607 → 129 ms |

Each row is one sequential baseline/optimized pair on a 32x16 tile with 12 candidates, 16 loss
cells, and one temporal raster sample. All 576 per-candidate cell losses and all 36 full candidate
losses were identical in the saved outputs. These are Python CPU wall times. Cached tap count
describes event storage demand. The savings depend on how much of the evaluation tile the swept
bounds occupy. Process peak working set remains unmeasured. The follow-up
comparison combining the smaller event cache and learned ordering was deferred after the host
reported under 1 GiB of available memory.

Conservative screen coverage and hierarchical space-time visibility culling are established in
[Hierarchical Stochastic Motion Blur Rasterization](https://fileadmin.cs.lth.se/graphics/research/papers/2011/mbtraversal/).
Edge-collapse decisions driven by rendered differences are established in
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf).
The research question is whether certificates of unchanged visibility can be propagated across
successive legal collapses to avoid rebuilding overlapping event caches, while preserving the
same filtered objective. These localized runs measure the reuse opportunity inside one batch.

Add `--swept-support` to the full integration command above to compare the two setups. The table
uses `--pan-angle 90` with Rounded Cube seed 72 and Material Sphere seed 16518, and
`--pan-angle 0 --scale 2` with Rounded Cube seed 72. Keep the full candidate-cell outputs for the
equality check. The position replay uses:

```powershell
$data = "out/pathloss-captures"
python tools/mmgeo/audit_path_loss_position_prior.py `
    --pair "$data/rounded-cube-cell-pruning.json" "$data/rounded-cube-cell-pruning-pan90.json" `
    --pair "$data/material-sphere-cell-pruning.json" "$data/material-sphere-cell-pruning-pan90.json" `
    --pair "$data/pirate-unit5-cell-pan45.json" "$data/pirate-unit5-cell-pan90.json" `
    --pair "$data/torus-cell-pan45.json" "$data/torus-cell-pan90.json"
```

## Incremental visibility across accepted edits

The [sequential replay](probe_incremental_path_visibility.py) caches the front depth envelope
at each subpixel tap and accumulates the filtered squared coverage and depth difference from the
original mesh. It applies six captured edge collapses in sequence. The edited vertex sets are
disjoint so that a collapse from the initial capture can still be applied to its original local
geometry after earlier edits. Selection uses projected proximity to a fixed seed, with a
fixed 32x16 evaluation tile. The replay therefore isolates the evaluation update from changing
candidate queues and geometric legality checks.

For an old envelope interval, a surviving front primitive is still the upper bound of all
surviving primitives. Only new lines can change that front. An affine depth gap that is positive
at both ends of an overlap stays positive through the overlap. The dominance policy uses this
criterion to reuse an entire tap when all its old winners survive and every new line is strictly
behind. Otherwise the interval policy retains this survivor reasoning individually and consults
the full current line set only for intervals whose old winner was edited. At such intervals,
removal may expose an arbitrarily far surface. Repair therefore searches the original scene bins
and the accepted patches before clipping the surviving lines to the invalid interval.

| Case | Tap rebuilds, intersection → dominance | Full-scene interval length, dominance → interval repair | Core update times, intersection / dominance / interval |
|---|---:|---:|---:|
| Rounded Cube, 90°, one tap per pixel | 104 → 82 | 164.0 → 21.3 | 48.7 / 44.7 / 47.1 ms |
| Rounded Cube, 45°, four taps per pixel | 378 → 305 | 610.0 → 90.5 | 195.4 / 191.3 / 195.9 ms |
| Material Sphere, 90°, one tap per pixel | 25 → 23 | 46.0 → 13.8 | 172.8 / 140.6 / 145.7 ms |

Durations sum over all taps and six updates, with each complete path spanning two time units.
Each policy shares the initial source index and cache (99, 289, and 468 ms in the table order).
Update timings are single sequential runs. Initial setup, result snapshots, and audits are
excluded from the per-policy update times. Full rebuilds from the current mesh provide a
fresh geometry and visibility baseline at every step. On the union of the compared event
partitions, the largest total visibility disagreement at any tap in any step was
`5.33e-15` path time units, around floating-point event boundaries. The maximum absolute
per-pixel objective difference was `3.86e-32`. The interval policy reduced full-scene line
inputs by 18–43% against dominance. Its interval clipping and assembly increased update time
in all three cases. Use dominance as the simpler runtime candidate for this data.

The replay uses floating-point event construction, an opaque depth model, fixed box filter taps,
and orthographic translations. It keeps audit snapshots in memory. Peak working set, rendered
material error, overlapping edits, candidate decisions, and full simplification quality remain
unmeasured. In these captures every tap that lost its dominance check also had an edited old
winner, so insertion-only repair has no measured benefit here.

Lindstrom and Turk update raster images locally after collapses at discrete views.
Gribel et al. compute analytical per-pixel visibility intervals for motion blur.
Popescu et al. compute continuous visibility from a camera segment. The working question is
whether retaining a bounded cache of continuous visibility across overlapping edits can improve
the cost of actual simplification decisions and retain the same loss.
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf) ·
[Analytical Motion Blur Rasterization with Compression](https://diglib.eg.org/bitstreams/f47ec493-1364-493c-a32b-c4e6ea94ec0c/download) ·
[Continuous from-Segment Visibility](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)

```powershell
$data = "out/pathloss-captures"
$probe = "tools/mmgeo/probe_incremental_path_visibility.py"
python $probe "$data/rounded_cube.json" --seed 72 --count 6 --out "$data/incremental-rounded-pan90.json"
python $probe "$data/rounded_cube.json" --seed 72 --count 6 --pan-angle 45 --scale 2 --out "$data/incremental-rounded-pan45-scale2.json"
python $probe "$data/material_sphere.json" --seed 16518 --count 6 --out "$data/incremental-sphere-pan90.json"
```

## Live candidate regeneration and partial score reuse

The [dynamic simplification probe](probe_dynamic_path_simplification.py) now rebuilds its candidate
pool from the current topology after accepting each edge. It proposes midpoint placements in a
fixed screen tile and admits interior edges whose endpoint links are cycles. It checks common link
vertices, duplicate faces, and orientation of surviving faces. All methods receive the same
candidate pool, ordered by projected proximity to the seed. The loss is relative to the original
mesh, using the same path and filtered depth and coverage channels as the replay. This is a local
CPU simplifier with a fixed candidate budget and a restricted midpoint and topology model.

The scene index retains stable face IDs and updates the bins of modified faces on acceptance.
Each accepted patch advances the version of every pixel with an old or new triangle intersection
at any of its taps anywhere on the path. These versions account for hidden geometry, which can
become visible when another candidate is evaluated. Matching the current front surface alone
would miss that dependency. If a candidate's incident triangle connectivity and projected
vertex positions still match its saved patch, this patch retains its support. Each pixel in
that support whose version did not advance can reuse its predicted envelope and loss, even
if other pixels of the same candidate must be recomputed. The sum of updated pixel losses
incorporates the current global objective. The retained candidate cache is bounded by the pool
size and temporary overlap between the old and new pool during a step.

In the initial whole-candidate cache experiment, three runs took eight steps each. All 24 decisions
matched the fresh spatial baseline, and all 21 consecutive pairs edited at least one common
face. In 14 of those pairs, the chosen edges shared a vertex. The whole-candidate cache had zero
hits. The four-tap Rounded Cube 45° run reduced tap rebuilds from 1,545 with intersection-only
updates to 1,354 with depth dominance. The one-tap Material Sphere 90° run reduced them from
522 to 432. Accepted-state visibility matched fresh scene reconstruction at every step.

The partial-pixel follow-up completed on Rounded Cube at 90°. Each step scored 12 candidates.
It performed a separate full tile and triangle index rebuild for all 96 candidate proposals.
The three methods chose the same edge at every step as that full reference. Maximum candidate
loss difference against the full reference was `6.94e-18`. The accepted tile and the fresh
accepted-state tile agreed at every step. The run reduced the mesh from 1,200 to 1,184 faces.

| Rounded Cube, 90° | Exact tap rebuilds | Candidate pixels reused across steps | Scoring time |
|---|---:|---:|---:|
| Intersection updates | 642 | 0 | 1.134 s |
| Depth dominance | 557 | 0 | 1.064 s |
| Depth dominance and partial pixel reuse | 497 | 74 | 0.939 s |

Times are from one run and exclude candidate generation, accepted-state updates, and reference
rebuilds. The follow-up jobs on the other two cases did not run after available system memory
fell below 850 MiB. The partial update has one verified workload. It still needs wider paths,
larger candidate budgets, production edge legality, and comparison of complete meshes against
geometric and appearance-driven baselines.

```powershell
$data = "out/pathloss-captures"
python tools/mmgeo/probe_dynamic_path_simplification.py "$data/rounded_cube.json" --seed 72 --edits 8 --pool 12 --audit-all-candidates --out "$data/dynamic-rounded-pan90.json"
```

## Matched-budget quality outside the optimization path

The dynamic probe now has a midpoint QEM control. Both methods regenerate current edges with
the same screen-local shortlist, orientation and topology checks, and midpoint placements.
The QEM control sums area-weighted original face-plane quadrics and accumulates them at each
merge, as in the existing geometry baseline. The two runs diverge according to their own scores.
This isolates the ranking decision under the probe's constraints. A full-mesh QEM implementation
with optimized placements is still a separate baseline.

After 20 Rounded Cube collapses (1,200 to 1,160 faces), the two methods chose different edges
at 18 of 20 steps. The exact coverage-plus-depth loss on the optimization segment was
`2.25e-5` for path ranking and `0.372` for midpoint QEM. Independent raster evaluation uses
80x80 full frames with four taps per pixel and eight midpoint poses per test path. It compares
box-filtered coverage, depth, and world-space flat triangle normals against the original mesh.
The two visible test paths change the pan direction and radius, and one also changes azimuth
by 0.65 radians. An opposite-azimuth test gave all zeros because the altered region was hidden.

| Rounded Cube held-out path | Metric | Midpoint QEM | Coverage and depth | Coverage, depth, and normals |
|---|---|---:|---:|---:|
| Same view, new pan | Coverage MSE | 8.54e-6 | 0 | 0 |
| Same view, new pan | Depth MSE | 5.01e-6 | 1.36e-9 | 2.71e-9 |
| Same view, new pan | Flat-normal squared distance | 1.27e-5 | 1.45e-5 | 5.69e-6 |
| Changed view and pan | Coverage MSE | 3.66e-6 | 0 | 1.22e-6 |
| Changed view and pan | Depth MSE | 1.82e-6 | 1.41e-9 | 6.29e-7 |
| Changed view and pan | Flat-normal squared distance | 7.81e-6 | 1.11e-5 | 6.78e-6 |

The coverage and depth improvement coexists with higher flat-normal error on both visible
test paths. To measure the tradeoff, the probe can also integrate squared differences of
filtered visible flat normals. A face normal is constant over each visibility interval, so
the interval partition already used for coverage and depth suffices. The preselected
weight of 0.25 puts the maximum unit-normal squared difference on the same scale as a
unit coverage mismatch. Existing geometry-based invalidation also covers modified normals.

The normal objective reduced the two visible held-out normal errors versus QEM by 55% and 13%.
It gave up some of the coverage and depth advantage of the two-channel objective on the changed
view. On the optimization segment, the joint objective was 0.0562 versus 0.455 for midpoint QEM.
All three update policies agreed at all 20 path-ranked decisions, and the accepted states had
zero measured pixel-loss difference against fresh reconstruction. The normal-aware run
rebuilt 2,088 taps with intersections alone, 1,872 with dominance, and 1,729 with partial cache
reuse. These measurements concern a small local edit budget and the two visible held-out paths.

Material Sphere is a counterexample with the same 0.25 weight, 20 edits, 12 candidate edges
per step, and the same evaluation settings. Both meshes ended at 9,388 of 9,428 faces.
The optimization-segment objective was 0.0129 with path ranking and 0.0720 with QEM.
On the three held-out paths, the path-ranked mesh had 1.33x, 5.59x, and 2.96x the QEM depth
errors, and 1.11x, 2.19x, and 2.79x the flat-normal errors. On the changed view both coverage
errors were zero. The other two coverage errors were 1.35x and 2.64x the QEM errors.
All 20 decisions matched across the visibility update policies, and all accepted states
matched fresh per-pixel reconstruction. Intersections, dominance, and partial reuse rebuilt
1,626, 1,499, and 1,456 taps, respectively. Scoring took 8.18, 8.12, and 7.53 seconds in one
run, excluding candidate generation, commit, and independent validation.

These two meshes separate implementation correctness from generalization. The cache preserves
the optimized objective, and a single optimization path can favor edits that increase error
elsewhere. Retain Material Sphere as a failure case for evaluating a multi-view objective or
a geometry constraint. Both assets are now development cases for any such change. Use other
assets and paths before drawing a generalization conclusion.

```powershell
$data = "out/pathloss-captures"
$probe = "tools/mmgeo/probe_dynamic_path_simplification.py"
python $probe "$data/rounded_cube.json" --seed 72 --edits 20 --pool 12 --compare-qem --out "$data/quality-rounded-pan90.json"
python $probe "$data/rounded_cube.json" --seed 72 --edits 20 --pool 12 --compare-qem --normal-weight 0.25 --out "$data/quality-rounded-normal-pan90.json"
python $probe "$data/material_sphere.json" --seed 16518 --edits 20 --pool 12 --compare-qem --normal-weight 0.25 --out "$data/quality-sphere-normal-pan90.json"
```

[Surface Simplification Using Quadric Error Metrics](https://www.cs.cmu.edu/afs/cs.cmu.edu/user/garland/www/quadrics/index.html) ·
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)

## Multiple optimization paths and a view-level lower bound

The [multi-view probe](probe_multiview_path_simplification.py) keeps the same shortlist and
midpoint placement rules as the single-path and QEM runs. It sums coverage, depth, and
weighted flat-normal loss over three equal-weight orthographic camera paths at azimuths
0°, +120°, and −120° relative to the primary view. The paths share pan direction, radius,
and tap count. Each view lazily indexes affected pixels and shares immutable face coefficients
with its original mesh. The per-view candidate cache remains bounded by the live shortlist.

A candidate's lower bound is the sum of its completed view losses plus the current losses
outside its swept support in the remaining views. Those pixels cannot be changed by the
candidate, and every omitted pixel loss is nonnegative. A candidate can be dropped when that
bound exceeds the best completed score and its tie tolerance. The probe uses double-precision
sums and a numerical margin. An audit completes the skipped scores and verifies each chosen
edge and every observed bound against those completed scores.

| Mesh | View evaluations out of 720 | Pruned candidates with completed-score audits | Chosen-edge disagreements |
|---|---:|---:|---:|
| Rounded Cube, 20 edits | 415 | 153 | 0 |
| Material Sphere, 20 edits | 524 | 162 | 0 |
| Torus, 20 edits | 644 | 53 | 0 |

Rounded Cube produced the same geometry as the single-path normal-aware run. On Material
Sphere the three-path objective reduced the changed-view depth MSE from 7.63e-7 to 1.53e-7
and flat-normal error from 1.42e-4 to 7.08e-5 versus one-path ranking. Its depth and flat-normal
errors still exceeded QEM on all three held-out raster paths. The same-view new pan regressed
in all channels versus one-path ranking, while the opposite view traded lower normal error
for higher coverage and depth error. The mean flat-normal squared distance across the three
paths fell by 20% versus one path and remained about 55% above midpoint QEM.

Torus was evaluated next with the same preset camera offsets and normal weight. All methods
removed 40 faces, leaving 1,112. Its average held-out combined raster error fell from 6.61e-4
with one path to 5.04e-4 with three paths. QEM was lower at 4.61e-4. The three-view selection
improved the opposite-view normal error against both controls, while increasing the normal
errors for the other two views. For Material Sphere the corresponding combined errors are
9.57e-5, 9.56e-5, and 4.97e-5, respectively. Each mean weights the three test paths equally
and uses the same 0.25 flat-normal weight as the continuous objective.

An independent no-audit scoring run on Rounded Cube selected exactly the same 20 edges as a
separate exhaustive run. The candidate stage took 2.16 s with the support bound and 2.74 s
without pruning, including shortlist generation and excluding setup. These single runs used
the same cached solvers. Removing the unchanged-pixel term yielded the same 415 view
evaluations and took 2.20 s, so the extra term had no count benefit on this case.
Torus used 662 evaluations with the partial-only bound and 644 with the support bound.
Its chosen edges and placements matched exactly. The extra term therefore accounted for
18 of the 76 skipped evaluations on Torus. The two Torus runs differed in audit mode, so
their timings do not isolate the term's cost.

Image-driven simplification with multiple views and appearance-driven mesh optimization both
have established precedents. The experiment distinguishes the exact preview objective and
the work saved by its lower bound from the separate question of held-out fidelity.
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf) ·
[Appearance-Driven Automatic 3D Model Simplification](https://users.aalto.fi/~laines9/publications/hasselgren2021egsr_paper.pdf)

```powershell
$data = "out/pathloss-captures"
$probe = "tools/mmgeo/probe_multiview_path_simplification.py"
python $probe "$data/material_sphere.json" --control "$data/quality-sphere-normal-pan90.json" --audit-pruning --out "$data/multiview-sphere-normal-pan90.json"
python $probe "$data/rounded_cube.json" --control "$data/quality-rounded-normal-pan90.json" --audit-pruning --out "$data/multiview-rounded-normal-pan90.json"
python tools/mmgeo/probe_dynamic_path_simplification.py out/filter-real-candidates/torus.json --seed 2500 --edits 20 --pool 12 --compare-qem --normal-weight 0.25 --out "$data/quality-torus-normal-pan90.json"
python $probe out/filter-real-candidates/torus.json --control "$data/quality-torus-normal-pan90.json" --audit-pruning --out "$data/multiview-torus-normal-pan90.json"
```

For the same-state sequence comparison, add `--score-only` and run separately with no other
option, `--partial-only-bound`, and `--exhaustive`.

## Geometric gates for three-path simplification

The same 12 legal midpoint proposals are generated before geometry screening. The first arm
admits the four lowest accumulated QEM contraction costs, then orders the admitted proposals
by the three-path objective. It preserves the earlier traversal order within that shortlist.
An endpoint check with a one-edge shortlist reproduced the Rounded Cube QEM trajectory,
including all 20 edge IDs and placements. QEM plane error is available in the run output as a
proxy for geometric distortion.

| Mesh, 40 removed faces | Midpoint QEM | Unguarded three-path loss | Top-four QEM shortlist |
|---|---:|---:|---:|
| Rounded Cube | 8.05e-6 | 1.66e-6 | 2.13e-6 |
| Torus | 4.61e-4 | 5.04e-4 | 2.75e-4 |
| Material Sphere | 4.97e-5 | 9.56e-5 | 1.00e-4 |
| Pirate unit 5 | 1.02e-6 | 1.14e-6 | 8.06e-7 |

Each entry is the held-out mean of coverage MSE + depth MSE + 0.25 times flat-normal squared
distance, using the three unchanged validation paths. The top-four arm improved Torus by 40%
versus QEM and remained about twice as costly in image error on Material Sphere. It admitted
80 candidates per mesh and used 190, 226, 203, and 214 exact view evaluations in table order,
including early stopping. Completion of skipped admitted candidates confirmed each chosen edge.
On Pirate unit 5 the fixed top-four rule improved on QEM by 21% at 2,992 faces.
Relative to QEM, it improved three of the four tested meshes and doubled error on Material Sphere.

The second arm holds a geometric budget defined by the largest source-to-representative distance
over the reference QEM trajectory. It keeps the original vertex IDs represented by each live
vertex and rejects a proposed merge whose target would exceed the cap for any member of either
group. The reference trace supplies an offline matched budget. This experiment includes its
results only at the actual number of edits available to all controls.

For any source triangle, interpolate the source vertex coordinates and their final representative
coordinates with the same barycentric weights. The norm of their difference is bounded by the
largest source vertex displacement. The final audit checks that the surviving triangle images
are the final mesh and that each collapsed triangle projects onto an edge or vertex still in that
mesh. If both conditions hold, the map covers the final surface, and the vertex displacement
also bounds the symmetric Hausdorff distance between the two surfaces. It can be much looser
than the actual distance. Geometric bounds have earlier alternatives in
[Simplification Envelopes](https://www.cs.umd.edu/~varshney/papers/simp_env.pdf).

| Mesh | Edits under cap | Maximum displacement cap / observed bound | Held-out mean, QEM / displacement gate |
|---|---:|---:|---:|
| Rounded Cube | 20 | 0.03537 / 0.03297 | 8.05e-6 / 3.28e-5 |
| Torus | 20 | 0.32811 / 0.32445 | 4.61e-4 / 3.93e-4 |
| Material Sphere | 18 | 0.09379 / 0.09067 | 4.76e-5 / 8.38e-5 |
| Pirate unit 5 | 20 | 0.01551 / 0.01432 | 1.02e-6 / 9.97e-7 |

Distances are in capture coordinates. All four final maps passed the surface coverage check.
Material Sphere exhausted the legal proposals within its 12-edge pool under the cap, so its
quality comparison uses 18 edits for all arms. Rounded Cube's held-out error increased by a
factor of 4.08 even though its computed geometric upper bound was below QEM's final bound.
This directly limits what the geometric certificate can guarantee about rendered fidelity.
The cap and map audit use double precision.

A separate retry arm widened the legal geometric pool to 48 only when the original pool
contained no feasible proposal. It scored at most 12 eligible edges. Material Sphere used
the wider pool once, at edit 19, and completed all 20 edits. The source-to-representative
bound remained 0.09186 under the unchanged 0.09379 cap. At the matched 9,388 faces its
held-out mean was 8.52e-5, versus 9.57e-5 for single-path ranking and 4.97e-5 for QEM.
Widening resolved this observed stall and left the quality gap.

Treat the fixed top-four rule as a candidate for a larger controlled comparison. The
displacement limit addresses a separate geometric requirement, and held-out fidelity
needs its own evidence. The current pilots use one local region and midpoint placements.
A broader result needs a larger edit budget, different assets and validation paths, and
a full-mesh QEM baseline with optimized placements.

```powershell
$data = "out/pathloss-captures"
$probe = "tools/mmgeo/probe_multiview_path_simplification.py"
python $probe "$data/material_sphere.json" --control "$data/quality-sphere-normal-pan90.json" --qem-shortlist 4 --audit-pruning --out "$data/guard-qem4-sphere-normal-pan90.json"
python $probe "$data/material_sphere.json" --control "$data/quality-sphere-normal-pan90.json" --match-qem-displacement --audit-pruning --out "$data/guard-map-sphere-normal-pan90.json"
python $probe "$data/material_sphere.json" --control "$data/quality-sphere-normal-pan90.json" --match-qem-displacement --displacement-retry-pool 48 --audit-pruning --out "$data/guard-map48-sphere-normal-pan90.json"
python tools/mmgeo/probe_dynamic_path_simplification.py out/filter-real-candidates/pirate.json --seed 3000 --unit-index 5 --edits 20 --pool 12 --compare-qem --normal-weight 0.25 --out "$data/quality-pirate-normal-pan90.json"
```

## Decision and remaining gate

The exact lower-bound mechanism now runs online in the Python research probe and shows a modest
end-to-end win on these localized depth-only cases. The cheap raster map is a useful work-order
baseline. The learned allocator has not passed the cross-asset/path comparison. The numerical
screens are small, use one localized tile, and cover only orthographic translation. They are
evidence of an algorithmic direction, not a SIGGRAPH contribution.

The next required work is to port the online policy to the actual mesh candidate solver and measure
full cost, then expand to larger candidate pools, full-frame RGB/material loss,
perspective or camera rotation, and sequential legal collapses. Re-run asset-and-path held-out
learning only after those captures exist. A focused search is still needed for prior work on
certified adaptive image-error refinement for mesh simplification. If raster ordering accounts
for the gain and learning remains tied or worse, remove the network rather than keep it for novelty.
