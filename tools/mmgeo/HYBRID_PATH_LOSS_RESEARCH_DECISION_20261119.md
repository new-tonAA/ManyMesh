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

## Whole-mesh QEM with optimized placements

The [global comparison](probe_global_path_qem.py) uses the existing progressive QEM queue for
both trajectories. The queue ranks each edge's best legal placement among the quadric minimizer,
its endpoints, and its midpoint. The geometry control takes the first legal edge. The path
method scores the first four distinct legal edges with three continuous raster paths, using
each edge's QEM placement. The queue considers the entire capture unit. Both trajectories use
the same topology, boundary, orientation, and triangle quality rules at their respective current
meshes. The swept support includes the projected placement, which can lie beyond the old edge.
Every scored patch is checked against the edit actually accepted by the queue.

The loss uses the earlier 0.25 flat-normal weight. Quality is independently measured on six
holdout azimuths 24°, 75°, 155°, 190°, 275°, and 330° from the reference azimuth, each with
a different pan direction. Each holdout path uses four midpoint poses, 80x80 pixels, and four
taps per pixel. The combined error averages coverage MSE, depth MSE, and 0.25 times squared
flat-normal distance across these paths.

| Mesh | Removed faces | Held-out mean, QEM | Held-out mean, path reranking |
|---|---:|---:|---:|
| Rounded Cube | 60 (5%) | 1.23e-7 | 1.15e-7 |
| Torus | 58 (5%) | 7.41e-6 | 7.22e-6 |
| Pirate unit 5 | 152 (5%) | 8.26e-8 | 8.57e-8 |
| Material Sphere | 94 (1%) | 8.89e-14 | 3.21e-13 |

The sphere errors in the 1% run are both near zero at this sampling resolution. The absolute
values matter more than their ratio. The earlier local gains on Rounded Cube and Torus shrink
to 7% and 3% in this full-unit comparison. Pirate reverses direction and regresses by 4%.
The 5% Rounded Cube run audited 29 pruned candidates without an edge disagreement.

| Mesh at 20% removal | Final faces | Held-out QEM | Held-out reranking | Reranking / QEM runtime |
|---|---:|---:|---:|---:|
| Rounded Cube | 960 | 3.86e-6 | 4.35e-6 | 2.18 / 0.48 s |
| Torus | 922 | 1.46e-4 | 1.27e-4 | 7.05 / 0.47 s |
| Pirate unit 5 | 2,426 | 6.47e-6 | 5.22e-6 | 6.86 / 1.22 s |
| Material Sphere | 7,542 | 2.35e-5 | 2.30e-5 | 49.04 / 3.89 s |

All methods reached the requested matched face budgets. Pirate and Torus improved by 19% and
13% in mean held-out error. Sphere improved by 1.9%, with lower error on every holdout path
in this run. Rounded Cube was 13% worse than QEM. These timings are one run per comparison
in Python, including queue and view setup and excluding held-out renders. Relative to scoring
all three views of every proposal, this filter skipped 119 of 1,440 evaluations on Rounded
Cube, 23 of 1,380 on Torus, 181 of 3,636 on Pirate, and 179 of 11,316 on Sphere. The current
bound therefore removes little of the full-unit scoring overhead in this experiment.

The archived QEM implementation independently reproduced all 1,481 baseline edge and vertex
placement decisions at the 20% budgets. The refactored scorer also reproduced the earlier
local Rounded Cube top-four trajectory. On the global Rounded Cube run it audited 62 pruned
proposals and reproduced all 120 chosen edges. Rebuilding every final-view pixel from the
accepted geometry gave a maximum absolute pixel-loss difference of 3.97e-14 versus the cache.

The benchmark shows modest quality gains on some meshes with a stronger baseline and a
substantial runtime cost. It makes the placement-matched global queue the reference for
future scoring changes. Additional improvements need wider assets and a scoring method with
larger savings at unchanged decisions.

```powershell
$probe = "tools/mmgeo/probe_global_path_qem.py"
$data = "out/pathloss-captures"
python $probe "$data/rounded_cube.json" --remove-fraction .05 --audit-pruning --out "$data/global-qem4-rounded.json"
python $probe "$data/rounded_cube.json" --remove-fraction .20 --audit-pruning --audit-final-views --score-only --out "$data/global-qem4-20pct-rounded-audit.json"
python $probe out/filter-real-candidates/pirate.json --unit-index 5 --remove-fraction .20 --out "$data/global-qem4-20pct-pirate.json"
python $probe "$data/material_sphere.json" --remove-fraction .20 --out "$data/global-qem4-20pct-sphere.json"
```

[Surface Simplification Using Quadric Error Metrics](https://www.cs.cmu.edu/~garland/quadrics/) ·
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)

## Pixel-level early stopping and reusable scene records

The pixel-bound arm starts each view with all known contributions outside the swept support.
Within the support it adds nonnegative exact pixel losses and conservatively rounds each
incremental sum down. Pixels can be traversed in scan order or descending current loss. A
candidate that crosses the incumbent limit stops before any further visibility queries. Its
partial patch cannot replace a complete patch in the reuse cache.

The separate geometry reuse arm takes old face coefficients from the current scene index
and retains already computed replacement coefficients when a patch signature survives an
edit. It can also cache full current-scene intersection lists by tap. The list cache evicts
least recently used entries at a configured line-record budget. An accepted edit invalidates
all taps of every pixel intersecting its old or new patch, even if the edit had been hidden.
The original-scene index remains separate. These changes preserve the objective and the
candidate queue.

The comparisons use the whole-unit four-edge shortlist at the same 20% face budget as the
previous section. A pixel visit counts an iteration of the patch update loop, including cases
where no envelope rebuild is needed. A tap rebuild counts reconstruction of the visible
envelope at one subpixel position. The timing tool also records per-process CPU time to reduce
confounding from other workloads on the host.

| Mesh | Pixel visits, view bound / pixel bound | Tap rebuilds, view bound / pixel bound |
|---|---:|---:|
| Rounded Cube | 3,737 / 3,822 | 843 / 953 |
| Torus | 23,701 / 27,090 | 9,959 / 11,890 |
| Pirate unit 5 | 5,824 / 6,388 | 998 / 1,381 |
| Material Sphere | 50,710 / 54,553 | 12,873 / 15,389 |

The four pixel-bound runs reproduced all 1,481 edge and placement decisions of the view-only
bound. A separate Rounded Cube run completed the scores of 109 interrupted proposals and
rebuilt every final pixel, with a maximum pixel loss difference of 3.97e-14. The pixel bound
still increased both work counters on all four meshes. Interrupting a candidate can remove a
complete patch that the view-only baseline would have reused at a later collapse. A timing
result without these work counters would be especially hard to interpret on this shared host.

The instrumented Rounded Cube pair recorded 795 complete patch cache hits with the view
bound and 711 with the pixel bound. This supports an interaction with future reuse.

| Mesh | CPU seconds, reference / face and line reuse | Scene-line cache hits / queries | Peak line records, one view |
|---|---:|---:|---:|
| Rounded Cube | 2.09 / 1.84 | 251 / 843 | 548 |
| Torus | 17.84 / 15.47 | 1,749 / 9,959 | 1,362 |
| Pirate unit 5 | 19.97 / 16.98 | 230 / 998 | 392 |
| Material Sphere | 70.39 / 78.28 | 2,044 / 12,873 | 3,814 |

The combined cache used a limit of 8,192 records per view. All four paired runs gave exactly
the same selected per-view scores, edges, and placements. Rounded Cube also audited all
62 view-pruned proposals and independently rebuilt the final views, with the same 3.97e-14
maximum pixel difference. A 16-record limit exercised eviction and reproduced the same
trajectory. CPU times include setup and are single paired runs. The combined option saved
12–15% on the first three meshes and used 11% more CPU time on Material Sphere. A cache hit
skips a line query and still builds the new visible envelope, so hit counts and envelope
rebuild counts measure different work.

On the 236-edit Material Sphere prefix (5% face removal), the four configurations took
56.73 s without reuse, 54.67 s with face coefficients alone, 49.75 s with scene-line caching
alone, and 46.89 s with both. The selected edges, placements, and per-view scores of all
four match the first 236 edits of the 20% run. These single-run timings show an early
benefit from both layers, while the 20% pair does not establish an overall Sphere speedup.
Keep the new modes optional. An adaptive policy would need paired measurements through
the later portion of the trajectory and validation on additional meshes.

```powershell
$env:OPENBLAS_NUM_THREADS = "1"
$probe = "tools/mmgeo/probe_global_path_qem.py"
$data = "out/pathloss-captures"
python $probe "$data/rounded_cube.json" --remove-fraction .20 --pixel-order loss --audit-pruning --audit-final-views --score-only --out "$data/pixel-rounded-audit.json"
python $probe "$data/material_sphere.json" --remove-fraction .20 --score-only --out "$data/face-ray-sphere-base.json"
python $probe "$data/material_sphere.json" --remove-fraction .20 --reuse-face-records --ray-cache-lines 8192 --score-only --out "$data/face-ray-sphere-reuse.json"
```

## Resuming interrupted candidate scores

With `--retain-partial`, an interrupted view stores its evaluated pixels and records the pending
pixel addresses. The entry stays within the live edge shortlist. A later evaluation requires the
same geometry and placement signature. It joins the pending pixels with the evaluated,
intersecting pixels whose scene stamps have advanced. The remaining cached candidate losses
can be reused. An early stop stores that state without submitting a partial patch as a
collapsible candidate. All evaluation views still complete before committing a winner.

The optional `--cached-view-bound` includes the known interior terms in the lower bound of each
unscored view. These terms occupy pixels disjoint from the unchanged exterior. Both groups
use evaluated losses in the current scene or losses certified by the signature and stamps.
Omitted contributions are nonnegative. A fully scored view replaces its entire lower bound,
which prevents counting any cached term twice. The same mechanism works with full cache entries
when pixel stopping is disabled.

| Mesh, 20% removed | Tap rebuilds, view only / discard / retain | CPU seconds, discard / retain | Resumed entries / covered pixels |
|---|---:|---:|---:|
| Rounded Cube | 843 / 953 / 826 | 2.20 / 2.05 | 89 / 148 |
| Torus | 9,959 / 11,890 / 9,807 | 7.69 / 6.77 | 136 / 3,792 |
| Pirate unit 5 | 998 / 1,381 / 986 | 7.72 / 6.70 | 270 / 592 |
| Material Sphere | 12,873 / 15,389 / 12,668 | 55.13 / 46.72 | 995 / 4,382 |

All three arms selected exactly the same edges, placements, and per-view scores over 1,481
collapses. Retention cuts 13–29% of the tap rebuilds of pixel pruning with discarded state. The
retained variant also rebuilds 1–2% fewer taps than the view-only reference. The discard and
retain CPU times are single matched pairs. A separate Rounded Cube run completed all 109
interrupted candidate scores and independently rebuilt the final views. Its maximum
pixel loss difference was 3.97e-14. The method preserves the existing comparison's held-out
quality by reproducing the same geometry.

| Mesh | View evaluations, view only / retain plus cached bound | Tap rebuilds | CPU seconds |
|---|---:|---:|---:|
| Rounded Cube | 1,321 / 1,223 | 843 / 826 | 2.09 / 2.05 |
| Torus | 1,357 / 1,101 | 9,959 / 9,805 | 6.69 / 6.64 |
| Pirate unit 5 | 3,455 / 2,949 | 998 / 986 | 6.44 / 6.97 |
| Material Sphere | 11,137 / 8,652 | 12,873 / 12,641 | 50.59 / 45.11 |

The combined policy reproduced all decisions and per-view scores. It reduces view evaluation
calls by 7–22%, with a 1–2% reduction in actual envelope reconstructions. Some of the skipped
calls would have been complete-cache hits. Material Sphere used 11% less CPU time and Pirate
used 8% more. These are single paired runs. Keep the view-only strategy as the baseline until
an exact policy gives a larger reduction in geometry work across cases.

Two additional checks isolate the bound and audit the combined pruning path. On Torus, the
cached-view-bound-only run reproduced all 115 edge, placement, and per-view-score records from
the view-only run. On Rounded Cube, the retain-plus-bound run independently completed all 109
pruned candidate scores and rebuilt the final views; the maximum pixel difference was
3.97e-14. The extra audit used the same geometry trajectory, so it checks score reconstruction
without changing the winner sequence.

```powershell
$env:OPENBLAS_NUM_THREADS = "1"
$probe = "tools/mmgeo/probe_global_path_qem.py"
$data = "out/pathloss-captures"
python $probe "$data/rounded_cube.json" --remove-fraction .20 --pixel-order loss --retain-partial --audit-pruning --audit-final-views --score-only --out "$data/partial-rounded-audit.json"
python $probe "$data/material_sphere.json" --remove-fraction .20 --score-only --out "$data/resume-sphere-view.json"
python $probe "$data/material_sphere.json" --remove-fraction .20 --pixel-order loss --retain-partial --cached-view-bound --score-only --out "$data/resume-sphere-memo.json"
```

Lazy edge costs and partial image updates are established ideas in
[Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf).
The tested additional invariant concerns how unfinished per-pixel work and its lower bound
survive accepted topology changes across multiple continuous views.

## Joint edge and placement selection

The full-unit probe can rerank the legal placements on each of the same four shortlisted edges.
The queue already generates the two endpoints, midpoint, and quadric minimizer when the solve is
well conditioned. The new arm deduplicates equal points and checks each alternative with the
same link, boundary, flip, and triangle quality rules. The existing path score then chooses an
edge and placement jointly. Cache and pruning records distinguish the placements. The queue
regenerates edges and placements after each accepted edit.

The comparison uses the same approximately 20% face removal, three optimization paths, and six
independent evaluation paths as the full-unit reference above. Each trajectory regenerates its
own shortlist, so differences can include both changed placements and later edge choices. The
experiment measures the value of adding placement choices to this online policy.

| Mesh | Final faces | Accepted alternative placements | Held-out QEM | Held-out edge only | Held-out edge and placement | Edge only / joint CPU seconds |
|---|---:|---:|---:|---:|---:|---:|
| Rounded Cube | 960 | 73 / 120 | 3.86e-6 | 4.35e-6 | 6.22e-6 | 2.72 / 10.61 |
| Torus | 922 | 7 / 115 | 1.46e-4 | 1.27e-4 | 1.45e-4 | 7.09 / 23.75 |
| Pirate unit 5 | 2,426 | 151 / 303 | 6.47e-6 | 5.22e-6 | 1.78e-5 | 7.72 / 25.41 |
| Material Sphere | 7,542 | 579 / 943 | 2.35e-5 | 2.30e-5 | 1.96e-5 | 57.47 / 335.13 |

The combined score at the three fitting paths fell by 66.8%, 0.9%, 78.4%, and 50.1% respectively.
The held-out score increased by 42.9%, 14.2%, and 240.8% on the first three meshes, where coverage,
depth, and flat-normal errors each increased on average. Material Sphere reduced mean held-out
error by 14.7%, winning on four of six paths, at 5.8 times the edge-only CPU time. This leaves
evidence of placement headroom on one mesh and poor generalization on the other three.
Rounded Cube CPU timings include independent pruning audits for both policy arms. The final-view
rebuild and holdout render are outside these timings. Both controls reproduced the archived
edge and target sequences and all recorded scoring-path losses across 1,481 edits per control.

The Rounded Cube pruning audit independently completed 732 rejected edge/placement proposals.
Rebuilding the three final scoring views independently gave a maximum per-pixel absolute loss
difference of 3.70e-14. The topology guards are local and the experiment uses flat normals,
coverage, and depth. Textured appearance and global self-intersections are outside this screen.

To separate camera choice from sampling density, I independently rendered the same three
Rounded Cube output meshes at the three fitted azimuths and the original 90-degree pan.
The replay used a 64x64 viewport, the original half-length of one pixel, and 16 uniformly
spaced midpoint poses per path. At one sample per pixel, the edge-only and joint scores were
1.89e-5 and 3.04e-6. At four taps per pixel with box filtering, they were 1.25e-6 and 3.04e-6.
The ranking reverses with the camera and mesh held fixed. This isolates sensitivity to the
sampling and reconstruction setting on one mesh. A new camera direction is unnecessary to
produce this failure. The saved replay is `out/pathloss-captures/placement-rounded-phase-audit.json`.

A robust placement objective must address this sampling sensitivity before more legal
placements are offered to the optimizer. The measured joint rule is not a general quality or
runtime improvement.

Continuous path scoring of these discrete placements is the specific intervention. Prior work
already optimizes mesh coordinates against rendered references in
[Image-Driven Mesh Optimization](https://repository.gatech.edu/server/api/core/bitstreams/86062420-b350-49d7-b2b1-1d56c387e2bc/content)
and jointly optimizes geometry and shading in
[Appearance-Driven Automatic 3D Model Simplification](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/).

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$probe = 'tools/mmgeo/probe_global_path_qem.py'
$data = 'out/pathloss-captures'
python $probe "$data/rounded_cube.json" --remove-fraction .2 --compare-placements --audit-pruning --audit-final-views --out "$data/placement-rounded.json"
python $probe out/filter-real-candidates/torus.json --remove-fraction .2 --compare-placements --out "$data/placement-torus.json"
python $probe out/filter-real-candidates/pirate.json --unit-index 5 --remove-fraction .2 --compare-placements --out "$data/placement-pirate.json"
python $probe "$data/material_sphere.json" --remove-fraction .2 --compare-placements --out "$data/placement-sphere.json"
```

## Sharing visibility among box filter samples

An orthographic pan along a pixel axis gives several taps the same projected line. If a tap
starts at `p + d * offset`, its ray at path time `t` is the ray from `p` at time
`t + offset`. Along each row or column of taps, solve one envelope over the interval
that spans all shifted paths. Shift its event times by `-offset`, transform the affine depth
intercept by `slope * offset`, and clip to the original time window. The filter still combines
all taps before squaring and integrating coverage, depth and flat-normal residuals.

With a regular N-by-N box grid, the maximum number of independent visibility solves per
pixel drops from N squared to N. Geometry changes still invalidate cached pixel entries
when they intersect the shared interval. Dominance is tested over that interval, so it
can be more conservative than separate tap tests. The expanded anchor interval stays
inside the swept coordinate range of the whole pixel used by the existing support bound.

Use `--share-collinear-taps` with `--scale 2` and a multiple of 90 degrees for the pan angle.
`perViewTapRebuilds` counts actual front-envelope construction calls in both modes. In sharing
mode a call may serve several taps. The independent final-view audit always solves the
original per-tap problem, then compares reconstructed pixel losses.

The 5% Rounded Cube audit independently completed 46 pruned edge proposals and 257 pruned
edge and placement proposals. The final pixel loss differed from independent per-tap
reconstruction by at most 6.09e-15 across these policies.
An additional 12-edit Rounded Cube check used a negative horizontal pan, radius 0.1, and a
3-by-3 tap grid. This creates gaps between the shifted path windows. The shared interval
conservatively spans the gaps, while each reconstructed tap clips them away. With partial
pixel caching, cached-view pruning, and the line cache enabled, the two policies independently
completed 164 pruned proposals and resumed 20 partial patches. The maximum final pixel loss
difference against independent per-tap reconstruction was 2.23e-16.

At about 20% face removal, the reference and sharing modes used the same 2-by-2 filter,
three vertical pans, and six held-out paths. All 470 selected edges and placements agreed
across the four pairs. The largest absolute per-view score difference was 7.64e-14.
Independent held-out raster reports matched exactly. Timings are single serial Python runs
with one BLAS thread. CPU time includes queue and view setup and excludes held-out renders.

| Mesh and policy | Front solves, independent / shared | CPU seconds, independent / shared |
|---|---:|---:|
| Rounded Cube, edge only | 2,978 / 1,853 | 6.30 / 5.02 |
| Rounded Cube, joint | 10,475 / 6,464 | 26.89 / 13.97 |
| Torus, edge only | 39,376 / 22,459 | 29.45 / 20.98 |
| Torus, joint | 137,152 / 78,255 | 95.42 / 66.22 |

The four-tap edge-only objective lowered Rounded Cube held-out error from 4.35e-6
at a single tap to 2.49e-6, against 3.86e-6 for pure QEM. Torus improved from 1.27e-4
to 1.26e-4, against 1.46e-4 for QEM. At four taps joint selection still regressed relative
to edge-only selection on both meshes, yielding 8.12e-6 and 1.40e-4 respectively. Faster
evaluation makes the filtered objective cheaper but leaves the placement quality problem open.

Reproduce the two paired runs with the following inputs. Use a separate output file and
append `--share-collinear-taps` to each command for the sharing arm.

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$probe = 'tools/mmgeo/probe_global_path_qem.py'
python $probe out/pathloss-captures/rounded_cube.json --remove-fraction .20 --scale 2 --compare-placements --out out/pathloss-captures/tap-pair-rounded-False.json
python $probe out/filter-real-candidates/torus.json --remove-fraction .20 --scale 2 --compare-placements --out out/pathloss-captures/tap-pair-torus-False.json
python $probe out/pathloss-captures/rounded_cube.json --remove-fraction .02 --scale 3 --pan-angle 180 --radius .1 --share-collinear-taps --compare-placements --pixel-order loss --cached-view-bound --retain-partial --ray-cache-lines 2048 --audit-pruning --audit-final-views --score-only --out out/pathloss-captures/shared-taps-rounded-horizontal-audit.json
```

Continuous visibility along projected motion is closely related to
[Continuous from-Segment Visibility](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)
and the shared line visibility in
[High-Quality Spatio-Temporal Rendering using Semi-Analytical Visibility](https://fileadmin.cs.lth.se/graphics/research/papers/2011/spatiotemp/).
The experiment measures the savings from reparameterizing these intervals inside a
dynamic simplification scorer.

## Continuous box filter along the pan axis

The same shared visibility lines can evaluate a different objective. At path time `t`,
integrate each line's coverage, depth, and normal over the full spatial pixel interval
`[t - 0.5, t + 0.5]` along the pan axis. Average over the transverse sample positions before
squaring the source versus current residual. This replaces discrete phases on only one
axis. The camera is orthographic and the filter support is one pixel wide.

Each visibility line has piecewise constant coverage and normals and piecewise affine depth.
A prefix primitive on its intervals gives the box integral by subtracting evaluations at the
two window endpoints. A shifted visibility breakpoint occurs when either endpoint crosses a
line event. Between these shifted events the filtered residual has degree at most two.
Three-point Gauss–Legendre quadrature integrates its squared norm exactly in exact arithmetic.
The conservative pixel support and cache invalidation still cover the swept pixel rectangle.
The score remains a sum of nonnegative pixel terms for early stopping.

An isolated step occlusion with a known energy of 5/6 matched within 1e-14. Twelve synthetic
mixtures of affine depth and visibility changes, with two transverse positions and a normal
channel, agreed within 5.10e-9 with 20,000 time midpoints and separate direct clipping of each
spatial interval. On Rounded Cube, an 18-edit run independently completed 189 pruned
proposals across both policies. A full scoring-view rebuild differed from cached per-pixel
loss by at most 8.06e-18.

The 20% face removal comparison uses two transverse positions in both modes. The control
adds two discrete positions along the pan, giving four box taps per pixel. The new mode
integrates that axis continuously. The queue, candidates, six holdout paths, 80-by-80
evaluation raster, and four evaluation taps per pixel follow the earlier protocol.

| Mesh | Final faces | QEM loss | Edge only, four taps / continuous | Joint, four taps / continuous | Joint CPU seconds, four taps / continuous |
|---|---:|---:|---:|---:|---:|
| Rounded Cube | 960 | 3.86e-6 | 2.49e-6 / 3.55e-6 | 8.12e-6 / 3.04e-6 | 13.97 / 11.94 |
| Torus | 922 | 1.46e-4 | 1.26e-4 / 1.27e-4 | 1.40e-4 / 1.35e-4 | 66.22 / 67.70 |
| Pirate unit 5 | 2,426 | 6.47e-6 | 7.13e-6 / 7.12e-6 | 9.05e-6 / 7.02e-6 | 46.58 / 44.16 |

For joint selection, continuous filtering reduced the mean held-out loss on each mesh
by 62.5%, 3.3%, and 22.4%, respectively, and improved five of six paths on each.
The lowest measured error still comes from four-tap edge-only for Rounded Cube and
Torus, and QEM for Pirate. The timings are single CPU runs. Rounded Cube and Torus
use the earlier archived four-tap control, so timing differences are descriptive.

A second evaluation on the saved Rounded Cube meshes kept the same camera poses and
physical pan length and raised the viewport to 96 by 96 with nine taps per pixel. Mean
loss was 3.02e-6 for the four-tap joint mesh and 2.58e-6 for the continuous joint mesh,
a 14.7% improvement on four of six paths. The four-tap edge-only mesh obtained 2.57e-6,
and pure QEM obtained 1.91e-6. This resolution sensitivity affects the inferred gain
and also which policy is best. The replay is
`out/pathloss-captures/continuous-box-rounded-heldout-96px.json`.

Reproduce with the following commands. Use a separate output path and replace
`--integrate-along-pan` with `--share-collinear-taps` for the four-tap control.

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$probe = 'tools/mmgeo/probe_global_path_qem.py'
python $probe out/pathloss-captures/rounded_cube.json --remove-fraction .20 --scale 2 --compare-placements --integrate-along-pan --out out/pathloss-captures/continuous-box-rounded.json
python $probe out/filter-real-candidates/torus.json --remove-fraction .20 --scale 2 --compare-placements --integrate-along-pan --out out/pathloss-captures/continuous-box-torus.json
python $probe out/filter-real-candidates/pirate.json --unit-index 5 --remove-fraction .20 --scale 2 --compare-placements --integrate-along-pan --out out/pathloss-captures/continuous-box-pirate.json
```

Analytic spatial filtering has direct precedents in
[Analytic Visibility on the GPU](https://www.cg.tuwien.ac.at/research/publications/2013/Auzinger_2013_AnaVis/)
and [Analytic Rasterization of Curves with Polynomial Filters](https://people.engr.tamu.edu/schaefer/research/scanline.pdf).
The experiment tests whether the combination of continuous path loss, local collapse updates,
and a continuous spatial filter generalizes better than discrete taps for placement decisions.

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
