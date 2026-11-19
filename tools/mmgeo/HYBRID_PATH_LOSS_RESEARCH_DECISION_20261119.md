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
NumPy ranker, single 64x16 tile, orthographic pan path, and 12 local candidates are an exploratory
prototype, not SIGGRAPH evidence. No full-resolution/color objective, sequential collapse replay,
production integration, broad joint asset/path holdout, or resource-profiled run was performed.

Reproduce the held-out Rounded Cube query with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/rounded_cube.json --seed-candidate 72 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 32 --tile-height 16 --steps 1 --pan-angle 90 --path-radius 1 --loss-cell-width 8 --loss-cell-height 4 --online-pruning --cell-order-policy learned --cell-order-train-captures out/pathloss-captures/material-sphere-cell-pruning.json out/pathloss-captures/pirate-unit5-cell-pan45.json out/pathloss-captures/torus-cell-pan45.json --out out/pathloss-captures/rounded-cube-online-learned-pan90.json
```

The next gate is a frozen model evaluated on several independent meshes and path directions with
paired raster/learned wall-time repeats. Keep the simple raster policy if the learned advantage
does not persist after training is amortized.

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
