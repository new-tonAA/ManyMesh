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

## Proxy cost and visual audit

`lod_proxy.py --shared-depth` resolves geometry common to all candidates,
interaction cuts and finer references once. This is optional: CPU savings depend
on asset and overlap. By default, frames with no swaps skip rasterization, since
both finer references then equal the baseline and every gain is exactly zero.
`--proxy-height 108` is an experimental smaller scoring grid; image evaluation
still uses the capture resolution. The retained experiment shows worse silhouettes.

```sh
python tools/mmtrain/lod_proxy_benchmark.py --captures out/lod-sequence-075 \
    out/lod-proxy-unseen-055 out/lod-proxy-unseen-075 --repeats 3 --out out/paired.json
python -m unittest discover -s tools/mmtrain -p test_lod_proxy.py
```

Use `lod_audit.py --report <proxy-report.json> --captures <capture-directories...>
--out <directory>` to generate per-asset best and worst PSNR cases, including
no-ops, with full detail, baseline, selected cut, and both absolute RGB errors at
8x. Optional `--exposure 4 --crop` applies a fixed multiplier to the RGB panels,
uses common foreground bounds, and enlarges pixels 2x with nearest sampling.
Metrics use original pixels. JSON records sources and display settings. Supply
every capture referenced by the report. These small frames support debugging;
publication figures need larger, better lit captures.

See [retained results](results/proxy-grid-20261113/summary.json) and research
notes section 19. Benchmarking uses warmup and alternating implementation order;
reported times cover proxy construction, rasterization and scoring, excluding OBJ
loading, validation and Filament rendering.

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

## Reuse reconstruction outside a changed image region

Tiny has four 3-by-3 convolutions and an input skip, with a four-pixel receptive radius.
Compare two inputs on the network's own grid. Outside the changed input bounds expanded
by four pixels, the baseline network output remains valid. Run the network on the affected
output bounds with another four pixels of input context, then copy back only the affected
outputs. At the true image boundary the crop keeps the original zero padding. With a flat
background, the baseline can be computed on a template that accounts for distance to the
frame edges. For TinyUpsample this applies to the low-resolution residual network before
pixel shuffle. Its bicubic pass still covers the full image.

The single-thread CPU benchmark used six native 320-by-180 inputs and 640-by-360 references
from `out/m3t2`, with one input frame per view. These are archived checkpoints, and the
screen does not establish cross-asset generalization. The times are medians of per-view
medians from three warm repeats. Tiny's external bicubic rescale adds about 4.6 ms. The
TinyUpsample times include bicubic and pixel shuffle. Both exclude I/O and GPU rasterization.

| Frozen model | Full inference | Cropped inference | Median PSNR | Bicubic PSNR |
|---|---:|---:|---:|---:|
| Tiny | 133.5 ms | 59.1 ms | 29.66 dB | 30.57 dB |
| TinyUpsample | 45.9 ms | 32.6 ms | 30.11 dB | 30.57 dB |

The largest absolute pixel difference between full and cropped inference was 6.76e-9.
These checkpoints miss both the bicubic quality and a 16.7 ms frame budget in this run.
The laptop path needs the full cost of rendering, reconstruction and transfer measured
together. Use the engine's spatial or temporal upscale as a lightweight control.
The Iris Xe smoke run reached Vulkan device selection and camera export. It stopped
before producing a frame or GPU time sample, so there is no new whole-frame result.

Candidate scoring is a different workload. Rerunning the same checkpoint on
`out/lod-oracle-pilot` reused the reconstructed base cut outside each swap's affected pixels.
All 136 alternate cuts agreed with full network inference within 7.46e-8, and every view
retained the same raw and reconstructed winners as the saved full-frame run. The median
crop covered 0.17% of the frame, and candidate inference including input comparison and
output assembly took 4.78 ms median in the local run. This is a same-resolution capture.
Ranking after the network gave 0.00013 dB over the raw oracle in one view and zero in the
other eleven. For the coupled mesh and upscaling experiment, capture distinct legal mesh
cuts rendered natively at several resolutions. Compare at the same final resolution and
frame budget against native QEM and QEM with the same upscaler. Require improvements in
image quality and motion stability across held-out assets and view sequences.

Adaptive compute for upscalers has prior art in
[Exploring Sparsity in Image Super-Resolution](https://openaccess.thecvf.com/content/CVPR2021/html/Wang_Exploring_Sparsity_in_Image_Super-Resolution_for_Efficient_Inference_CVPR_2021_paper.html).
The local execution here is an exact receptive-field reuse control for an existing network.

```powershell
$env:OMP_NUM_THREADS = '1'
python tools/mmtrain/bench_local_reconstruction.py --capture out/m3t2 --checkpoint out/m3/models/tiny_no.pt --out out/temporal-check/tiny-local-native-lowres.json
python tools/mmtrain/bench_local_reconstruction.py --capture out/m3t2 --model tiny_up --checkpoint out/m4-dragon/cross/cross2_tiny_up.pt --out out/temporal-check/tiny-up-local-native-lowres.json
python tools/mmtrain/lod_oracle.py score --capture out/lod-oracle-pilot --checkpoint out/m3/models/tiny_s1_no.pt --threads 1 --local-reconstruction --audit-local-reconstruction --out out/lod-oracle-pilot/local-score.json
```

## Learn where to keep geometry

The pilot uses eight public [Khronos glTF sample assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/f0920f5b32d172a30efe3f9257e965918831e6ea/Models).
The downloader pins the revision and retrieves 6.3 MB of geometry buffers plus source and
license metadata. Seven assets are CC0. [Cesium Milk Truck](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/f0920f5b32d172a30efe3f9257e965918831e6ea/Models/CesiumMilkTruck/README.md)
is © 2017 Cesium under CC BY 4.0, rendered here without the material and logo textures.
Assets, generated pairs, and fold weights go under `out/`.

For each of 12 views per asset, a software z-buffer draws a 96-by-96 grayscale image of each
of two QEM simplifications. The requested retained ratios are 20% and 45%. The full-detail
reference renders at 384-by-384 and is box-filtered to 192-by-192. Both LOD outputs use the same
2x bicubic filter. The label for each 8-by-8 input tile is the difference between its coarse
and finer output MSE. Quality scores measure replacement from the pre-rendered finer image,
with the number of selected tiles limited per view. Runtime evaluation needs a legal mixed cut
and matched triangle and frame-time budgets.

The MLP maps seven coarse raster statistics through 12 ReLU units to one score. The second
version adds a mesh-side signal. Replay the collapse trace to recover vertex indices and
verify its final triangle indices against the actual QEM result. Compute the normal component
of displacement using the actual QEM coordinates of each surviving representative. Store at most
128 object-space points with absolute offset, one per occupied spatial cell with the greatest
offsets first. That is at most 2 KiB per asset in float32. At scoring time, project these points,
discard those behind the coarse depth beyond the tolerance, and use the largest remaining offset
in each tile. Conventional view-dependent geometry selection already uses geometric deviation
along the surface normal. The question here is whether a compact cue improves decisions about
error after the chosen upscale filter. [Hoppe, View-Dependent Refinement of Progressive Meshes](https://hhoppe.com/vdrpm.pdf)

One entire asset is held out per fold. The table gives average per-asset MSE reduction from
the coarse-only result. At 10%, the ranker selects 14 of 144 tiles per view. The hindsight
row ranks using the target and shows the headroom under this replacement experiment.

| Ranker | 10% tile capacity | 25% tile capacity |
|---|---:|---:|
| Coarse brightness contrast | 14.80% | 26.95% |
| Collapse cue alone | 17.92% | 22.33% |
| Raster-only MLP, 109 weights and biases | 10.45% | 25.46% |
| Raster + collapse MLP, 121 weights and biases | 17.93% | 27.74% |
| Raster + collapse ridge regression | 19.65% | 28.18% |
| Hindsight | 30.87% | 33.99% |

The mesh cue added the most at 10% for Cesium Milk Truck and Lantern. The ridge model beat
coarse brightness contrast on three of eight assets at 10%, and two of eight at 25%. The
mean improved while the gains were concentrated. Deeper learning has not earned a runtime
place on these data. The comparison uses one dataset, orthographic cameras, a single light
and fixed LOD pairs. Texture, perspective, and motion remain outside the experiment.
The table was recomputed after switching from replayed coordinates to the actual simplifier
output. The eight assets' baseline raster errors matched their previous values.

The laptop generated the pairs in 5.9 s with about 285 MiB peak working set including Numba
and the simplifier. A separate NumPy process ran both model ablations, 8-fold held-out
scoring, and the original array timing benchmarks in 4.4 s with 58 MiB peak working set.
On preloaded data, the geometry-aware MLP forward pass took 0.33 ms p95 for 8,160 tiles
at a 960-by-544 input size. Feature extraction dominates the array implementation. In a
same-process, single-thread comparison, fusing the per-tile reductions into a Numba kernel
reduced feature extraction, point projection, inference and ranking together from 35.0 to
4.1 ms p95 at 960-by-544 and from 4.4 to 0.75 ms p95 at 320-by-184. In a separate CLI run the
fused path took 5.2 ms p95 at 960-by-544. Each timing uses 30 warm measurements on a resized
replay frame. The feature check matches eight native input frames within 1e-6, and the
comparison process peaked at 149 MiB. Full rendering, data transfers, extra geometry draws
and upscaling remain to be timed together on Iris Xe.

```powershell
python tools/mmtrain/fetch_refinement_assets.py --out out/geometry-refinement-pilot/assets
python -m pip install --no-deps --target out/geometry-refinement-pilot/deps numpy==2.2.6 trimesh==5.2.1 fast-simplification==0.2.0
$env:PYTHONPATH = (Resolve-Path out/geometry-refinement-pilot/deps).Path
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:NUMBA_NUM_THREADS = '1'
python tools/mmtrain/make_refinement_pairs.py out/geometry-refinement-pilot/assets --out out/geometry-refinement-pilot/pairs-with-witness
python tools/mmtrain/tile_refinement.py out/geometry-refinement-pilot/pairs-with-witness --out out/geometry-refinement-pilot/study-fused --fused-features
```

The raster generator also uses Pillow and Numba from the local Python environment. The
pipeline emits asset-level error statistics, two weight files per held-out asset, and warm
CPU timings. Omit `--fused-features` to time the NumPy implementation.

## Budgeted mesh cuts under a reconstruction filter

The cut probe selects one QEM version per disconnected mesh component, up to six refinable
components. Each component contributes its actual triangle count to the budget. The components
share no input vertices after welding and are rendered in a fixed order. For two configurations
per view, rasterizing the assembled triangles gives bit-identical color and depth to independently
rasterizing the parts and compositing them by depth. The reference uses the 4x source raster
box-filtered to the final 2x size. Nearest upsampling is the input-resolution MSE control because
its output MSE differs from comparison to the 2x2 block means of the target by a cut-independent
constant.

The grouped solver first marks changed samples for each component. A sample can be ignored if
another component is strictly nearer in every allowed state. A conservative blocker depth is
the minimum over other parts of the farther of their two depth samples. For each filter, expand
the remaining changing samples by its support radius and join components whose expanded supports
overlap. Fixed local filtering makes the output support of separate groups disjoint, so whole-cut
MSE equals the baseline plus one loss delta per group. Enumerate affordable states within each
group, then merge the integer triangle and loss frontiers, dropping dominated combinations.
Image evaluation stays within one group at a time. The probe separately exhausts the full
cut space as a verification control.

We tested the original eight assets and five fresh models. Four fresh models had at least two
refinable components. SheenCloth was excluded by that criterion. Across 144 views at each raster
size, grouped loss agreed with exhaustive scoring within `9e-18`. Every selected cut met its
triangle cap and matched the exhaustive minimum in all four filters and at all three caps.

| Input | Exhaustive filter calls | Grouped filter calls | Median exhaustive scoring | Median grouped scoring and search |
|---|---:|---:|---:|---:|
| 96×96 | 20,544 | 8,717 | 50.1 ms | 18.6 ms |
| 128×128 | 20,544 | 9,223 | 85.7 ms | 31.6 ms |

These wall times exclude the shared component raster passes and include compositing and resizing.
Across all views the summed scoring speedups were 1.88x and 1.76x. The serial experiment
including assets, compilation, rasterization and verification peaked at 268 MiB.

Under the same triangle cap, average bilinear, bicubic, and Lanczos MSE reductions against the
nearest-selected cut on the four fresh assets were 0.103%, 0.033%, and 0.017% at 96×96, and
0.117%, 0.032%, and 0.016% at 128×128. Under the same exact triangle count as the nearest-selected
cut, average reductions across the fresh views and budgets were below 0.01% for each filter at
both sizes. This rules out a large average quality win from reordering these candidate cuts
using these filters. The probe uses grayscale orthographic rasterization and an offline
supersampled target. Runtime frame time, textured perspective views and temporal reconstruction
remain outside these measurements. Image-space simplification is established prior art.
[Lindstrom and Turk, Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)
[Hasselgren et al., Appearance-Driven Automatic 3D Model Simplification](https://arxiv.org/abs/2104.03989)

```powershell
python tools/mmtrain/fetch_refinement_assets.py --asset-set holdout --out out/geometry-refinement-pilot/holdout-assets
foreach ($meshSize in 96,128) {
    python tools/mmtrain/probe_filter_aware_cuts.py out/geometry-refinement-pilot/assets out/geometry-refinement-pilot/holdout-assets --size $meshSize --out "out/geometry-refinement-pilot/filter-frontier-$meshSize.json"
}
```

The fresh [Iridescence Lamp](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/f0920f5b32d172a30efe3f9257e965918831e6ea/Models/IridescenceLamp)
and [Stained Glass Lamp](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/f0920f5b32d172a30efe3f9257e965918831e6ea/Models/StainedGlassLamp)
are by Wayfair, licensed CC BY 4.0 and used here as untextured geometry. The other three fresh
assets are CC0. The pinned manifest records source URLs, geometry hashes and license identifiers.

## New geometry candidates at exactly the same triangle count

The preceding cut study spent geometry on a fixed pool. This experiment constructs two new
candidate families starting from the same 20% QEM baseline. It uses six fitting views and
six interleaved test views. Three raster phases are scored per view. The test changes the
nonzero phases and repeats at both 96-by-96 and 128-by-128 native rendering resolutions.
Reference color and coverage are box-filtered from a 4x raster to the 2x output grid. The
boundary miss metric measures source foreground within one native pixel of the background
that falls outside the reconstructed silhouette.

The contour relocation first samples projected front/back transitions and open edges where
the coarse raster supports a foreground-to-background boundary. An image-space signed-distance
field from the full-detail raster supplies a target and direction for each sample. A sparse
damped fit determines one bounded offset along each coarse vertex normal. The trial scales
are 0.25, 0.5, and 1. A face guard preserves the orientation and at least 20% of the baseline
oriented area. Fitting selects the lowest bicubic MSE among candidates that also improve or
preserve coverage MSE and boundary misses.

At least one displacement scale passed the face guard on four of 13 assets. The fitting
selector moved vertices on two assets. Avocado's test color MSE improved by 2.62% at 96 and
2.15% at 128, with coverage getting worse at 128. WaterBottle's test color MSE increased
by 12.68% and 13.92%. Neither asset provides a robust quality improvement across the three
metrics. The face guard covers per-face orientation and area, and self-intersection remains
outside the test. The full serial run peaked at 317 MiB.

The QEM candidate pool varies aggressiveness (4 or 9 versus the baseline of 7) and stretches
one input axis at a time by 2x before decimation, undoing the stretch on the output. Each
alternative must reach the baseline's exact triangle count. Of 65 alternatives, 34 met the
count. The fit-only chooser uses the same coverage and boundary guard as the relocation
experiment. The held-out oracle applies the guard and chooses using the test images.

| Equal-count QEM choice | All 13, 96 | All 13, 128 | Five fresh assets, 96 | Five fresh assets, 128 |
|---|---:|---:|---:|---:|
| Fit-only bicubic chooser | 9.49% | 11.44% | 3.24% | 3.81% |
| Fit-only native-resolution chooser | 9.49% | 11.44% | 3.24% | 3.81% |
| Held-out guarded oracle | 10.03% | 13.24% | 6.05% | 8.49% |

Entries are mean per-asset reductions in held-out bicubic color MSE over default QEM. The
native-resolution chooser uses the same guards and compares native color against the 2x2
block average of the output reference. It selects the same mesh on all 13 assets, so this
experiment attributes the improvement to the candidate pool. Seven
assets improved at both tested sizes, including one of the five fresh assets. On that fresh
asset (GlassVaseFlowers), the fitted choice retained exactly 2,806 triangles and reduced
color MSE by 16.20% and 19.04%. The fixed aggressiveness-4 preset, chosen by mean fitting
error on the original eight assets, improved the five fresh assets by 0.37% and 1.44% on
average and worsened their mean coverage error. Future comparisons should include the
tuned QEM pool. The serial pool experiment peaked at 306 MiB. These data
cover an orthographic software renderer and a fixed gray material. A native GPU performance
comparison and topology checks beyond exact face counts still remain.
Image-driven silhouette and mesh optimization already have published methods.
[Lindstrom and Turk, Image-Driven Simplification](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)
[Williams et al., Perceptually Guided Simplification of Lit, Textured Meshes](https://pages.jh.edu/dighamm/version2/research/2003_02_perceptually_guided_simplification_of_lit_textured_meshes.pdf)

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
python tools/mmtrain/probe_contour_relocation.py "$pilotRoot/assets" "$pilotRoot/holdout-assets" --out "$pilotRoot/contour-96.json"
python tools/mmtrain/probe_qem_candidate_pool.py "$pilotRoot/assets" "$pilotRoot/holdout-assets" --out "$pilotRoot/qem-pool-control-96.json"
```

## Equal-count candidates within separate components

The component experiment starts from the whole-mesh QEM result and uses its collapse
index mapping to recover source ownership for output triangles. It keeps their actual
output coordinates and verifies that each output vertex has a single source component.
Up to four large components with enough surviving faces receive the same QEM recipe
alternatives as the whole-mesh pool. Each alternative must match the component's exact
face count. With `--anchor selected`, the component counts and starting geometry come
from the fit-selected whole mesh. With `--anchor qem`, they come from default QEM.
Unselected parts retain their anchor geometry. The baseline color and depth, after
splitting and recomposing the parts, match the original anchor on every fitting image.

Two sweeps try one component replacement at a time. Cached per-component color and
depth allow every alternative at that step to share the same composited background.
A move must lower fitting bicubic MSE and meet the anchor's coverage and boundary
miss guards. For bicubic scoring, expand the changed native color rectangle by two
pixels to bound the output change, then add two more pixels of input context for
filtering. The change in squared residual inside that support gives the full-image
score. The audit compares each such calculation with full bicubic on the same view.
The final assembled mesh is re-rasterized on the fitting and held-out views, at
exactly the selected whole-mesh budget.

Keeping the default QEM allocation worsened average held-out bicubic MSE against
the fit-selected whole mesh by 6.70% at 96 and 9.05% at 128 across all 13 models.
Among the five extension assets the same method improved by 1.53% and 0.72% on
average. This shows how strongly the local candidate search depends on the starting
triangle allocation.

Starting from the fit-selected whole mesh improved mean held-out color MSE by 2.08%
at 96 and 2.20% at 128 across all 13 assets. Eight improved and one regressed at
each size. For the five extension assets, the mean reductions were 4.57% and 4.61%.
GlassVaseFlowers improved by 8.08% and 8.56%, and StainedGlassLamp by 12.81% and
12.86%. Both also improved on the two held-out coverage metrics. FlightHelmet
improved color at both sizes and had a small coverage regression at 128.

For the selected-anchor run, the 6,714 audited alternative scores agreed with
full-image filtering within `3.5e-18` MSE. Crops covered 8.1% of the possible input
pixels in aggregate and took 40% of the summed full-image color scoring time.
This timing covers the color-loss query, including support
detection, and excludes the shared raster setup and other metrics. Median offline
fit time per mesh was 3.0 s before held-out rendering. The complete serial
audit peaked at 329 MiB. Native frame-time and intersection checks remain separate
evaluation tasks.

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
python tools/mmtrain/probe_component_candidates.py "$pilotRoot/assets" "$pilotRoot/holdout-assets" --whole-reference "$pilotRoot/qem-pool-control-96.json" --anchor qem --audit --out "$pilotRoot/components-96.json"
python tools/mmtrain/probe_component_candidates.py "$pilotRoot/assets" "$pilotRoot/holdout-assets" --whole-reference "$pilotRoot/qem-pool-control-96.json" --anchor selected --audit --out "$pilotRoot/components-selected-96.json"
```

## Frozen meshes under perspective camera motion

`probe_component_motion.py` rebuilds the default QEM, selected whole-mesh and selected
component meshes from the same inputs, checks their fitting scores and exact face counts,
then tests them on three previously unused perspective paths. The paths translate and
rotate the camera and vary elevation. Geometry stays frozen. The raster interpolates
reciprocal view depth and perspective-correct vertex light. Each 96×96 native input uses
the same bicubic output, and the reference is the full source mesh at 384×384 with a
2×2 output box filter. The optional PLY export includes mesh normals and records content
hashes and face counts.

For the motion-compensated measure, the high-resolution source depth gives the warp.
Only pixels whose four source samples are covered and within 1% in depth are eligible.
Reprojection checks depth at each prior bilinear tap. The same accepted surface pixels
are used for every candidate. A separate screen-space coverage residual difference
tracks changes around boundaries. These measures report changes in errors relative to
the full-detail reference. A perceptual video comparison would require additional
validation. [Jindal et al., Computer Graphics Video Quality Metric and Dataset](https://arxiv.org/abs/2506.11546)

| Mean relative reduction vs selected whole mesh | 13 assets | Five extension assets |
|---|---:|---:|
| Color MSE | 1.303% | 2.659% |
| Coverage MSE | 0.441% | 0.443% |
| Motion-compensated color residual change | 0.352% | 0.773% |
| Screen-space coverage residual change | 0.268% | 0.373% |

The experiment evaluates 468 frames. Reprojection accepts 96.45% of the eligible
surface pixels. Color MSE improves on seven assets and worsens on two. The temporal
color metric improves on six and worsens on three. GlassVaseFlowers gains 6.88% in
color MSE and regresses 0.46% in the temporal color measure. StainedGlassLamp gains
4.78% and 1.36%, respectively. The result supports a modest perspective image-quality
gain and leaves temporal improvement weak. The serial CPU replay including mesh
export took 36.4 s and peaked at 314 MiB.
At 128×128 input the five extension assets were replayed for another 180 frames
on the same paths. Mean reductions were 2.747% for color MSE, 0.513% for coverage
MSE, 0.971% for motion-compensated color residual change and 0.502% for
screen-space coverage residual change.

The release `mm_bench` headless smoke used the exported StainedGlassLamp component
mesh at 160×90, feature level 1, and shadows off. Vulkan and OpenGL both identified
Intel Iris Xe and wrote the camera description. Each run was stopped after 18 seconds
with the first image and timing samples still missing. The quality results above
come from the CPU rasterizer. The native smoke leaves GPU frame cost unmeasured.

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
python tools/mmtrain/probe_component_motion.py "$pilotRoot/assets" "$pilotRoot/holdout-assets" --whole-reference "$pilotRoot/qem-pool-control-96.json" --component-reference "$pilotRoot/components-selected-96.json" --mesh-out "$pilotRoot/motion-meshes" --out "$pilotRoot/motion-96.json"
python tools/mmtrain/probe_component_motion.py "$pilotRoot/holdout-assets" --whole-reference "$pilotRoot/qem-pool-control-96.json" --component-reference "$pilotRoot/components-selected-96.json" --size 128 --out "$pilotRoot/motion-extension-128.json"
```

## Iris Xe offscreen raster and reconstruction timing

`bench_component_gpu.py` draws the exported PLY meshes on a named hardware adapter.
The hardware run used Intel Iris Xe, driver 31.0.101.4502, and D3D12 through wgpu-native.
GPU queries surround rasterization and, when enabled, a 2x reconstruction pass. The queue
reports a timestamp period of 52.083 ns. The program converts the raw ticks and checks
the batch interval against a synchronized host wait.
[wgpu timestamp query documentation](https://wgpu.rs/doc/wgpu_examples/timestamp_queries/index.html)

Each mode has three batches of 48 samples after eight warmup draws per batch, with a
rotated mode order. One fixed perspective camera is used throughout. The four geometry
variants use a grayscale directional light, depth and indexed triangles. The 16-instance
experiment puts copies of the same mesh into a 4×4 grid in one instanced draw. Direct
raster uses 1920×1080. The upscaling modes rasterize at 960×540 and resolve to the same
1920×1080 output. Quality is measured against the full mesh rasterized directly at the
output resolution. The texture readback for quality runs outside the GPU timer.

| Asset | Instances | Full mesh direct p95 | Parts direct p95 | Parts bilinear 2x p95 | Parts cubic 2x p95 |
|---|---:|---:|---:|---:|---:|
| StainedGlassLamp | 1 | 0.283 ms | 0.211 ms | 0.263 ms | 0.441 ms |
| GlassVaseFlowers | 1 | 0.109 ms | 0.091 ms | 0.234 ms | 0.554 ms |
| ToyCar | 1 | 0.247 ms | 0.101 ms | 0.250 ms | 0.453 ms |
| StainedGlassLamp | 16 | 1.338 ms | 0.370 ms | 0.370 ms | 0.573 ms |
| GlassVaseFlowers | 16 | 0.275 ms | 0.190 ms | 0.367 ms | 0.443 ms |
| ToyCar | 16 | 5.765 ms | 0.608 ms | 1.077 ms | 1.253 ms |

Direct raster on the selected component mesh had the lowest median GPU duration among
its three resolution/filter modes in all six cases. At equal triangle counts and with
direct raster, component selection reduced MSE versus the selected whole mesh by 5.05%,
11.95%, and 0.07% in the three single-object runs, respectively. The largest timing
difference uses 1,742,976 input triangles versus 348,592 component-mesh triangles across
16 ToyCar copies.

The cubic shader specializes Catmull–Rom for the two fixed 2x phases and combines the
central positive weights with hardware linear sampling. In all six cases it agrees with
the direct 16-sample shader within one 8-bit code value. Median reconstruction-pass time
was 0.302–0.337 ms for the nine-sample shader and 0.504–0.572 ms for the direct shader.
The two runs peaked at about 396 MiB host process working set. These measurements cover
an offscreen raster and reconstruction workload with fixed lighting. Presentation,
Filament material and scene costs, and a live LOD update still need separate timing.

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
python -m pip install --no-deps --target "$pilotRoot/gpu-deps" wgpu==0.32.0 rendercanvas==2.6.3
$env:PYTHONPATH = (Resolve-Path "$pilotRoot/gpu-deps").Path
foreach ($meshGrid in 1,4) {
    python tools/mmtrain/bench_component_gpu.py "$pilotRoot/motion-meshes" --motion-reference "$pilotRoot/motion-96.json" --asset StainedGlassLamp GlassVaseFlowers ToyCar --size 1920x1080 --frames 48 --repeats 3 --grid $meshGrid --audit-filter --out "$pilotRoot/wgpu-fast-1080-grid$meshGrid.json"
}
```

## Dynamic LOD on Iris Xe at a fixed triangle budget

`bench_dynamic_lod.py` keeps both the full source mesh and the selected component mesh
resident. Sixteen instances occupy isolated screen cells. Their object-space views and
apparent scales change each frame. Each frame gives four instances the source mesh and
twelve the component mesh. All policies therefore submit the same triangle count and
issue two indexed instanced draws. The runtime reorders and uploads 1,280 bytes of
instance transforms and cell identifiers each frame. Shader clipping keeps each instance
inside its cell and allows exact validation against the corresponding isolated pixels.

The area control ranks instances by squared apparent radius. The directional profile
measures the low-versus-source color error per projected area over a 24-frame turntable.
The richer profile bins by three apparent radii as well as twelve azimuths and shrinks its
estimates toward the directional profile. Four contiguous splits of the turntable choose
between the three rankers. The calibration gate switches from area only when the fitted
ranker reduces cross-validation error by at least 0.3%. Runtime rankers interpolate the
profiles without reading the framebuffer.

The fixed hysteresis control adds a constant retention bonus per frame, scaled by the
median priority. The residual switch cost instead uses each instance's predicted
current low-detail error for a demotion and its previous predicted error for a
promotion. The experiment sweeps both types of penalty. The per-frame oracle ranks
using actual GPU images and bounds the possible spatial improvement under the same
four-instance quota. Per-object budgeted LOD and temporal coherence are established
prior art. [Funkhouser and Séquin, Adaptive Display Algorithm](https://gfx.cs.princeton.edu/pubs/Funkhouser_1993_ADA/index.php)

For each holdout frame the source-only and component-only renders give the per-cell
color SSE. A mixed draw is checked against that composition at the middle of each path
for every default policy and the oracle. The switch SSE sums the actual source-versus-low
error on changed cells at the current pose. A second mixed draw with the previous choices
at that same pose verifies the sum and isolates the visual change caused by LOD
switches from the camera motion. CPU selection, transform upload and
submission are timed in the live draw loop, with the input poses precomputed. GPU
timestamps measure the render pass. Presentation, frame pacing, streaming, and
multi-object occlusion remain outside this test.

The final 1080p test uses two held-out paths of 48 frames per asset, with three timing
repetitions per path and eight warmup frames per policy. Policy order rotates between
repetitions and paths. The following compares calibration-selected priorities with the
same fixed hysteresis applied to area priorities.

| Asset | Ranker chosen in calibration | Color SSE reduction | Switch-count reduction | Switch SSE reduction | Calibrated GPU p95 |
|---|---|---:|---:|---:|---:|
| ToyCar | Area | 0.00% | 0.00% | 0.00% | 1.596 ms |
| GlassVaseFlowers | Size and direction | 1.29% | 3.33% | 5.68% | 0.391 ms |
| StainedGlassLamp | Direction | 3.58% | 20.00% | 26.35% | 0.635 ms |

Against area without hysteresis, the calibrated lamp policy reduces switch SSE by
31.90% and color SSE by 2.62%. The pure spatial oracle reduces color SSE by 0.58%
on ToyCar, 3.69% on GlassVaseFlowers, and 3.78% on StainedGlassLamp. This quantifies
the small spatial headroom for the ToyCar policy. The directional residual switch
cost at strength 0.35 reduces switch SSE by 41–53% versus area alone, with increases
in color SSE of 2–9%. The sweep retains that trade-off and the area-only controls.

For the calibrated policy, selection alone took 0.234–0.271 ms p95 and CPU selection,
upload and submission took 1.255–2.010 ms p95. The complete serial audit took 27.1 s
with a 313 MiB host process peak. Rerunning the experiment reproduced the quality
curves exactly. The measurements establish resident-mesh switching and quality
trade-offs for the isolated-cell workload.

```powershell
$pilotRoot = 'out/geometry-refinement-pilot'
$env:PYTHONPATH = (Resolve-Path "$pilotRoot/gpu-deps").Path
python tools/mmtrain/bench_dynamic_lod.py "$pilotRoot/motion-meshes" --motion-reference "$pilotRoot/motion-96.json" --asset ToyCar GlassVaseFlowers StainedGlassLamp --size 1920x1080 --frames 48 --test-pair alternate --timing-repeats 3 --out "$pilotRoot/dynamic-repeat-1080.json"
```

## Fairness note

`espcn` and `fsrcnn` scoring below bicubic here says nothing about those architectures. Their
papers train for a hundred thousand iterations on tens of thousands of images; this runs 1500
iterations on twelve. Treat those rows as "at an equal, very small budget", which is the point
of the comparison — not as a verdict on the methods.

## External mesh corpus pilot

The repository's Khronos sample meshes are too few and too clean to support a held-out learned
simplification study. `curate_thingi10k_subset.py` turns the Thingi10K v1.5.0 geometry and input
summary CSVs into a deterministic pilot manifest. It selects one file per Thing, excludes
non-commercial and no-derivative licenses, requires a single oriented manifold component with no
reported degeneracies, duplicates or self-intersections, and balances four face-count bands. The
32 selected Things are split by a stable hash into 16 train, 8 validation and 8 test assets. The
manifest records both the original source URL and the dataset-hosted individual-file URL, plus the
license needed for attribution. Mesh files are not included in the repository.

The metadata CSVs are small and live in ignored `out/thingi10k-metadata/`. The original per-model
URLs return HTTP 403 in this environment. The dataset repository exposes a 38.8-GB `raw_meshes`
tree, so the manifest points at its individual-file mirror pinned to commit
`1e52df627995ba43b7b91143af4bed86f570037a`. The runner could not connect to Hugging Face from
the shell, so the selected mesh files still need to be fetched when that endpoint is reachable.
Record their hashes and license attribution, then run the same simplification and filtered-raster
pipeline used for existing captures. No mesh geometry has been downloaded and no model has been
trained on this corpus yet.

Download the small, pinned metadata files and recreate the manifest with:

```powershell
New-Item -ItemType Directory -Force out/thingi10k-metadata | Out-Null
Invoke-WebRequest `
  https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/v1.5.0/metadata/geometry_data.csv `
  -OutFile out/thingi10k-metadata/geometry_data.csv
Invoke-WebRequest `
  https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/v1.5.0/metadata/input_summary.csv `
  -OutFile out/thingi10k-metadata/input_summary.csv
python tools/mmtrain/curate_thingi10k_subset.py `
  out/thingi10k-metadata/geometry_data.csv `
  out/thingi10k-metadata/input_summary.csv `
  --out out/thingi10k-metadata/selected-32.json
```

Dataset sources: [Thingi10K dataset repository](https://github.com/Thingi10K/Thingi10K),
[individual raw-mesh mirror](https://huggingface.co/datasets/Thingi10K/Thingi10K/tree/main/raw_meshes).
