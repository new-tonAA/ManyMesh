# mmtrain

## Equal-triangle LOD experiment

`lod_oracle.py` measures whether an image reconstruction model changes which parts of a mesh
benefit most from additional triangles. Capture needs Python 3.11 or later and native builds of
`mmgeo` and `mm_bench`.
Scoring needs NumPy and Pillow. To score with a frozen reconstruction model, also install
PyTorch and supply a three-channel, 32-wide `Tiny` checkpoint trained with
`--model tiny --scale 1 --no-error-map` on separate assets.

```sh
python tools/mmtrain/lod_oracle.py capture \
    --mmgeo out/cmake-release/tools/mmgeo/mmgeo \
    --mm-bench out/cmake-release/samples/mm_bench \
    --mesh assets/models/monkey/monkey.obj assets/models/cloth/cloth.obj \
    --out out/lod-oracle --ratio 0.60 --height 360 --views 8 --swaps 32
python tools/mmtrain/lod_oracle.py score --capture out/lod-oracle \
    --checkpoint out/m3/models/tiny_s1_no.pt --out out/lod-oracle/score.json
```

Pass the Windows `.exe` paths when using native Windows builds. Use a new capture directory
for each geometry export. To prepare geometry before the renderer is built, omit
`--mm-bench` from `capture` and then run
`lod_oracle.py render --capture out/lod-oracle --mm-bench <renderer>`.
Omit `--checkpoint` from `score` to measure identity reconstruction as a control.

Each view starts from `selectLodGraphAtRatio`. A candidate splits a selected node and merges
a disjoint set of selected siblings. Both changes must exchange the same number of triangles,
and the exported triangle count is checked again after assembly and deduplication.
`mmgeo --oracle-swaps N` samples candidates from both ends of a geometric ranking based on
the change in projected error multiplied by projected bounding-sphere radius squared.
The experiment is limited to these sampled one-step swaps. A view can yield zero swaps.

Capture records binary, asset, graph, and camera hashes. Every candidate and its baseline use
the same camera and an untextured material with shadows disabled. Scoring compares the
baseline, the geometric choice, the raw image oracle, and the reconstruction oracle over the
same candidate set. The oracles include the baseline as a legal no-op. They use full-frame RGB
MSE against the full-detail mesh rendered at the same resolution. The score also records
foreground-union MSE and the raw silhouette XOR divided by its union. For these
flat-background captures, foreground
is estimated by comparing RGB against the clear color.

Two separate effects are reported. The gain over the baseline measures the opportunity for
local triangle reallocation. The gain over the **raw oracle's choice evaluated after
reconstruction** measures the additional opportunity specifically from reconstruction-aware
ranking. These are offline results at equal submitted triangle counts. This protocol does
not estimate device frame time or temporal stability.

## Camera trajectory experiment

Use `--arc-degrees` below 360 to sample an ordered camera arc while moving closer to the
asset. The following settings reproduce the two budget conditions. Use the same assets and
camera settings at both budgets.

```sh
for ratio in 0.55 0.75; do
    run_dir="out/lod-arc-$ratio"
    python tools/mmtrain/lod_oracle.py capture \
        --mmgeo out/cmake-release/tools/mmgeo/mmgeo \
        --mm-bench out/cmake-release/samples/mm_bench \
        --mesh assets/models/monkey/monkey.obj assets/models/cloth/cloth.obj \
            assets/models/torus/torus.obj assets/models/sphere/sphere.obj \
            assets/models/rounded_cube/rounded_cube.obj \
        --out "$run_dir" --ratio "$ratio" --height 216 --views 8 --swaps 6 \
        --start-degrees 32 --arc-degrees 21
    python tools/mmtrain/lod_oracle.py score --capture "$run_dir" \
        --checkpoint out/m3/models/tiny_s1_no.pt --strengths 0 0.5 1 1.5 \
        --out "$run_dir/score.json"
done
python tools/mmtrain/lod_sequence.py --score out/lod-arc-{0.55,0.75}/score.json \
    --out out/lod-arc-summary.json
```

The sequence tool compares the current selector, a geometric swap score, and the per-frame
RGB oracle. It also uses dynamic programming to find the lowest total RGB MSE across the
sampled candidate paths. The image-guarded path requires RGB and silhouette errors to stay
at or below the corresponding baseline values in every frame. It also limits the
mean squared change in the screen-space RGB residual between consecutive frames to its
baseline value. The all-guarded path adds the same constraint on triangle churn, measured
as the symmetric difference of triangle IDs divided by their union. A baseline path is
always feasible. The oracle sees reference images and the full trajectory.

The temporal image metric subtracts the full-detail reference at each camera pose before
measuring changes in residual. It is sensitive to motion of the error across the screen
and does not track surface correspondences. Each strength scales the same frozen network's
RGB residual before clipping. Report the additional PSNR from ranking at that strength
against the raw oracle's choice evaluated at the same strength.

## Predicting stable swaps

Capture a second arc with the same settings and `--start-degrees 212` in a separate output
directory at each budget. Score it with `lod_oracle.py score`. For predictor training alone,
omit the checkpoint and strength options when scoring both arcs.

```sh
python tools/mmtrain/lod_predictor.py \
    --score out/lod-arc-{0.55,0.75}/score.json out/lod-opposite-{0.55,0.75}/score.json \
    --out out/lod-predictor.json
```

Each fold reserves a whole source asset by content hash. All its cameras and budgets are
held out, including during feature normalization. Training balances assets, then frames,
then swap candidates. The ridge regressor and the 16-unit MLP predict a bounded utility
computed from RGB PSNR gain and a penalty for increased silhouette error. Inputs are the
projected errors and bounding radii for the split and merge, the triangle fraction exchanged,
the requested budget, and the geometric score. The report stores the normalization and
weights from each fold. It requires NumPy, Pillow, and PyTorch.

During replay, the no-op has score zero. The causal policy takes the previous selected cut
and the current candidates. It permits a candidate if its triangle churn from that cut is
at most the churn of falling back to the current baseline. It discounts a candidate's
predicted utility for changing triangles and requires a fixed score margin for swaps.
Only the training and evaluation stages read reference pixels. The same replay also runs
the geometric score under the churn limit and the MLP without history.
The utility oracle uses the same causal rule with measured utility instead of a
prediction. It uses reference images and serves only as a diagnostic.

The churn limit is relative to the feasible fallback from the actual previous selection.
It can differ from the transition between the two baseline frames. The report compares
both paths using the same reference images and metrics. This is a CPU replay with the
sampled candidate sets, before implementation in the live Filament selection loop.

## Visibility feature ablation

Use the same captures and scores as the stable-swap experiment.

```sh
python tools/mmtrain/lod_visibility.py \
    --capture out/lod-arc-{0.55,0.75} out/lod-opposite-{0.55,0.75} \
    --out out/lod-visibility.json
python tools/mmtrain/lod_predictor.py \
    --score out/lod-arc-{0.55,0.75}/score.json out/lod-opposite-{0.55,0.75}/score.json \
    --visibility out/lod-visibility.json --out out/lod-predictor-visibility.json
```

The extractor reads the camera and triangle lists from the current frame. It verifies
that each candidate uses the same vertex space and triangle count as its baseline. It
rasterizes the baseline once, retains the fragments from unchanged triangles, and
rasterizes only the added triangles for each candidate. The resulting features describe
the visible area and occlusion of removed and added triangles, silhouette gain and loss,
boundary contact, and the change in relative depth. Capture manifest hashes and candidate
names tie the features to the scores.

This is a two-sided software depth pass at capture resolution with the same camera
projection as the capture. It expects the framed assets to lie between the camera planes.
It uses geometry and camera data without reading any images. The predictor appends
the visibility features to its existing input and uses the same folds and training settings.
Run the predictor without `--visibility` for the paired geometry-only control.

For geometric silhouette supervision, pass `--silhouette-out out/lod-silhouette.json`
to the extractor and `--silhouette out/lod-silhouette.json` to both predictor runs.
The optional label pass rasterizes the full-detail geometry separately and computes
the silhouette XOR divided by the union. It writes those reference-dependent values
to a separate file for training and evaluation. The visibility feature output is
identical in either mode. The earlier RGB mask remains available for comparisons
with previous runs. Shaded pixels can match the clear color even on visible geometry,
so the RGB mask is an approximation of coverage.

## Local finer reference for swap selection

The optional `--composites N` capture argument exports up to N equal-triangle
reallocations with one or two splits and one or two ancestor merges. The exporter
assembles every cut and checks its actual post-deduplication triangle count. It
writes `lod_graph.json` so the proxy can identify all selected descendants of
an ancestor merge. Existing `--swaps N` captures retain their previous format.

```sh
python tools/mmtrain/lod_oracle.py capture --mmgeo /path/to/mmgeo \
    --out out/lod-composites --mesh /path/to/model.obj \
    --ratio 0.75 --views 4 --swaps 4 --composites 8
```

Use captures from a ManyMesh build that writes MMLG v7 graphs. The score files must
come from ordered camera arcs. Create geometric silhouette labels with
`lod_visibility.py --silhouette-out` as above, then run the replay.

```sh
python tools/mmtrain/lod_proxy.py \
    --scores out/lod-arc-{0.55,0.75}/score.json out/lod-opposite-{0.55,0.75}/score.json \
    --silhouette out/lod-silhouette.json --out out/lod-proxy.json
```

For each frame, the proxy refines only the baseline nodes affected by any sampled
swap. One and two refinement steps give two reference cuts shared by every
candidate. Each triangle in the union is rasterized once, and each cut resolves
its own depth buffer. The replay compares silhouette IoU loss and a surface loss
that charges one for foreground/background disagreement and relative depth error
elsewhere on the foreground union. The baseline is a valid no-op in each policy.

The proxy ranks cuts using the camera and LOD graph alone. Full-detail renders and
silhouette labels supply the evaluation. The causal comparison uses the same
triangle churn constraint for the geometric and proxy scores. The report records
each selected path, per-frame quality, and triangle counts for the shared raster
pass. Prototype timings include proxy construction, software rasterization and
scoring for both refinement depths. They exclude capture loading, validation
and Filament image capture. They do not measure GPU runtime or streaming bandwidth.

Pass `--interactions` for a composite capture to compare a complete reallocation
with the sum of its individual operations. It uses a fixed image denominator, so
disjoint screen changes add exactly. Each difference is reported in `work_by_frame`.

After a whole-asset predictor replay, measure how many candidates its ranking
must retain to include the best rendered cut:

```sh
python tools/mmtrain/lod_screening.py --score out/lod-composites/score.json \
    --predictor out/lod-predictor.json --out out/lod-screening.json
```

The full-detail image errors are used only for evaluating candidate recall and
best attainable quality inside each shortlist.

## Image reconstruction training

Trains and compares reconstruction networks for ManyMesh: coarse geometry goes in, a full
quality picture is supposed to come out.

The question this tool exists to answer is whether the **Geometry Error Map** — the per cluster
error the geometry stage already computes — is worth feeding to the network. Everything else
here is scaffolding for that comparison.

## Data

A directory (default `out/m3`) containing, per view:

| File | Contents |
|-|-|
| `lr_vNN.png` | render of the decimated mesh, the observation |
| `hr_vNN.png` | render of the full mesh, the target |
| `err/vNN/error_map.pgm` | the error the geometry stage projected for that view |

Produced by `tools/mmgeo` (which emits the decimated mesh and the per view error map) and
`samples/mm_bench` (which renders both meshes from the same camera list — run it twice with
the same `--views`, and the pairs line up exactly, because the camera is an explicit
parameter).

## Usage

```shell
python tools/mmtrain/train.py --data out/m3 --model tiny --scale 2 --iterations 1500

  --model bicubic|tiny|espcn|fsrcnn|unet
  --scale N          observation is reduced by N; 1 compares at equal resolution
  --iterations N     default 1500
  --no-error-map     ablation: train with the colour input only
  --out <path>       save the weights and a JSON of the metrics
```

`bicubic` runs no network at all — it is the floor, and it is the number any learned method
has to beat.

## Architectures

| `--model` | Source |
|-|-|
| `tiny` | ours: a few 3×3 convolutions predicting a residual over the observation |
| `tiny_up` | ours, post-upsample: the same conv stack at the low resolution, a PixelShuffle residual over a bicubic base |
| `espcn` | Shi et al., CVPR 2016, sub-pixel convolution |
| `fsrcnn` | Dong et al., ECCV 2016, shrinking / mapping / expanding |
| `unet` | a small encoder-decoder, as a capacity check rather than a proposal |

`espcn` and `fsrcnn` upsample inside the network, so they take the reduced image directly.
`tiny` and `unet` take a bicubically restored image and predict a residual, which is the
cheaper arrangement for same-resolution restoration.

## What it found

On the Stanford dragon, 20.8% of the original triangles, 16 views (12 train / 4 validation),
CPU only:

| Method | scale 1 (pure geometry) | scale 2 (half res) |
|-|-|-|
| coarse / bicubic (floor) | 31.48 dB | 30.59 dB |
| tiny | **33.36 dB** | **31.57 dB** |
| unet | 33.23 dB | 31.67 dB |
| espcn | 31.90 dB | 29.56 dB |
| fsrcnn | 32.07 dB | 28.69 dB |

**Reconstruction works**: at equal resolution a small network recovers +1.88 dB over the
coarse render, and at half resolution it beats bicubic by about +1 dB.

### Cross-asset check

To see whether that prior transfers, `tiny_s1_no.pt` from the dragon run (3-channel, scale 1,
about 20k parameters) was applied unchanged to monkey LOD cuts rendered at 960x720 with
`--no-shadows`:

| Monkey cut | Coarse | + tiny CNN | Delta | Common-coverage PSNR |
|-|-|-|-|-|
| 45.25% (7,124 tris) | 42.50 dB | 42.65 dB | +0.15 dB | 37.24 -> 36.85 dB |
| 38.00% (5,982 tris) | 37.38 dB | 37.52 dB | +0.14 dB | 34.79 -> 34.87 dB |
| 38.00% + 4x MSAA | 38.81 dB | 38.89 dB | +0.09 dB | - |

The full-image gain comes from edge pixels: the silhouette XOR share of squared error falls
from 68.3% to 64.1% at 45.25%, while the common-coverage PSNR drops to 36.85 dB (full-image
SSIM rises from 0.99555 to 0.99583). So this is edge/high-frequency synthesis, not a
replacement for AO or detail-normal shading. The same-asset result is +1.88 dB and the
cross-asset result is +0.15 dB: deployment needs a
diverse training set or per-asset fine-tuning, not a single universal model.

**The error map does not, yet**: its contribution runs from −0.19 dB to +0.13 dB and flips
sign between models and between the two tasks — far below anything visible. It is not a broken
signal, it is a redundant one; the section below has the measurements and the reasoning.

## What else was tried

| Change | Result |
|-|-|
| `kpn` (Bako et al. 2017 kernel prediction) instead of `tiny` | 31.48 dB vs 33.37 — worse |
| `unet` (176k parameters) instead of `tiny` (28k) | 33.23 dB vs 33.37 — no better |
| 6000 iterations instead of 1500 | 33.42 dB vs 33.37 — converged |
| normalising the error map per view | +0.04 dB — no real effect |
| adding an edge (gradient) loss term | 33.37 → **33.50 dB**, SSIM 0.9797 → 0.9800 |

Kernel prediction is the architecture the literature uses when an auxiliary buffer is meant to
guide a reconstruction, and it is the wrong tool here: a normalised filter can only *filter*,
and what is missing is high frequency geometry detail, which has to be synthesised. That the
best result comes from the smallest model trained the shortest says the limits are elsewhere.

The edge term is worth keeping on: plain L1 is minimised by the median, which for a
reconstruction means a blurred answer that would rather hedge an edge than move it.

## Why the error map does not help

It is not a broken signal. Measured against the actual per pixel difference between the coarse
and full renders, **99.3% of the total error falls inside the pixels the map covers**, and its
magnitude tracks severity monotonically across quartiles (0.0141 to 0.0235).

It is a redundant one. Those errors are all at edges, and an edge that is in the wrong place is
already visible in the colour image. So the map adds about +0.03 dB over colour alone.

For a conditioning input to earn its place it has to carry something the colour does not — the
*signed direction* of the geometry error, say. That is not available at run time: knowing it
means having the full detail geometry, which is what the pipeline exists to avoid.

Which reframes what this stage is: the gain comes from the network's learned prior over high
frequency detail, not from the conditioning. Improving the prior - more data, a perceptual or
adversarial loss - is the productive direction. A better error map is not.

## Temporal input

`--stack N` feeds N sub pixel frames of the same camera as stacked input channels, which is
what `samples/mm_bench --jitter N` produces. Measured on the held out views, at equal
resolution and with no learning at all:

| frames accumulated | 1 | 2 | 4 | 8 |
|-|-|-|-|-|
| plain average, PSNR | 33.15 | 33.60 | 33.81 | **34.07 dB** |

Averaging eight jittered frames is worth +0.92 dB for free. Stacking them into the network on
top adds only about 0.2 dB over that, because a learned single frame already reaches 34.35 dB,
1.2 dB above the raw single frame. The reason is that this setup has no sampling deficit: the
render resolution matches the target, and jitter only moves samples within a pixel. DLSS and
NSS render at 540p for a 1080p target, a quarter of a sample per output pixel, which is where
temporal accumulation becomes decisive.

### With a real sampling deficit

The equal resolution case above has no sampling deficit, so accumulation buys little. Rendering
natively at 320x180, one sample per pixel, for a 640x360 target does have one. Six views, four
training and two validation, 2000 iterations, the 20k parameter model:

| configuration | PSNR | SSIM |
|-|-|-|
| bicubic, one frame | 30.33 | 0.9629 |
| bicubic, mean of eight frames | 31.11 | 0.9668 |
| learned, one frame | 31.21 | 0.9672 |
| learned, eight frames | **31.68** | **0.9707** |

Learning alone is worth +0.88 dB, accumulation alone +0.78, and together +1.35. The two are
complementary rather than overlapping, which is why every shipping solution pairs them, and it
is the first result here where the temporal half pulls its weight.

Caveat: four training views, two validation views, one seed, one small model. Read the
differences between rows, not the absolute numbers.

### A trap worth knowing about

Simulating low resolution by downscaling a high resolution render does not work:

| source of the 320x180 image | bicubic to 640x360 |
|-|-|
| rendered natively, one sample per pixel | 28.33 dB |
| downscaled from a 640x360 render | 30.12 dB |

A bicubic downscale has already averaged four samples, so it is supersampled rather than low
resolution - 1.8 dB better, and it cannot show a temporal effect at all (measured +0.06 dB
against +0.35 dB for the real thing).

## Post-upsample cost and quality

`tiny_up` exists because the same-resolution `tiny` spends most of its time on the output grid:
at 640x360 the 32-channel stack costs 40 ms on 16 CPU threads and 167 ms on one. `tiny_up` runs
the stack at 320x180 and adds a PixelShuffle residual to a bicubic base, which costs 13.6 ms on
4 threads. That is fast enough to matter, but on the dragon cross-budget data (6.92% of the
triangles) it scores **28.07 dB** against **28.69 dB** for bicubic: the cheap path loses the
quality gain. The same-resolution `tiny` is the one that gains +1.25 to +1.94 dB, and it needs
the full-resolution grid to do so. See section 7.12 of `MANYMESH.md` for the end-to-end numbers.

## Fairness note

`espcn` and `fsrcnn` scoring below bicubic here says nothing about those architectures. Their
papers train for a hundred thousand iterations on tens of thousands of images; this runs 1500
iterations on twelve. Treat those rows as "at an equal, very small budget", which is the point
of the comparison — not as a verdict on the methods.
