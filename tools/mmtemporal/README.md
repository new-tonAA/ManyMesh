# mmtemporal

Reprojects a history frame for a pure camera rotation and blends it in, which is the core of
temporal accumulation.

Temporal accumulation needs the previous frame aligned with the current one. When the camera
only *rotates* about its own centre there is no parallax, so a pixel's motion depends on the
rotation alone and not on distance. The correspondence is then exact and needs no depth buffer.

`samples/mm_bench --pan D` renders such a sequence: the eye stays fixed and the view turns by a
total of D degrees across the captures. `temporal.py` then reprojects each frame and blends.

```shell
samples/mm_bench --headless --window-size 320x180 --out out/m3pan/lr.png \
    --views 12 --pan 3 --eye ... --target ... coarse.ply
samples/mm_bench --headless --window-size 640x360 --out out/m3pan/hr.png \
    --views 12 --pan 3 --eye ... --target ... full.ply
python tools/mmtemporal/temporal.py --data out/m3pan --pan 3 --blend 0.5
```

## What it showed

Twelve frames, a 3 degree pan, coarse geometry rendered natively at 320x180 against a 640x360
full detail target:

| | PSNR (median, frames 1-11) |
|-|-|
| coarse frame alone | 28.27 dB |
| blend history with **no** reprojection | **26.91 dB** |
| blend history with reprojection | **28.93 dB** |

Blending an unaligned history makes things worse by 1.36 dB - that is ghosting, and it is the
failure mode temporal accumulation is famous for. With the rotation reprojected, the same
blend gains 0.66 dB. Motion compensation is not an optimisation here, it is the difference
between helping and hurting.

The blend is a plain exponential average, the simplest form of what a trained temporal model
learns. The learned variant is trained from `temporal.py --export` by `tools/mmtrain --stack 2`;
see the main document for those numbers.

## Translation and true disocclusion

A pan has no parallax, so nothing is ever disoccluded and a color-difference reject is
guaranteed to throw away signal. Real motion needs camera translation, which makes a pixel's
previous position depend on its depth. `samples/mm_bench --translate D --frames N` renders that
sequence (the eye and target shift laterally by D world units over N frames), and
`--camera-out <file>` writes the exact camera of every capture.

`tools/mmdepth` rasterizes the coarse mesh from that camera list, so reprojection can use the
view-space depth of the frame that was actually rendered:

```shell
samples/mm_bench --headless --window-size 320x180 --out out/parallax/lr.png \
    --views 4 --frames 8 --translate 0.20 --camera-out out/parallax/cameras.txt \
    --eye ... --target ... coarse.ply
samples/mm_bench --headless --window-size 640x360 --out out/parallax/hr.png \
    --views 4 --frames 8 --translate 0.20 --eye ... --target ... full.ply
out/cmake-release/tools/mmdepth/mmdepth.exe coarse.ply \
    --cameras out/parallax/cameras.txt --out out/parallax/depth
python tools/mmtemporal/temporal.py --data out/parallax \
    --cameras out/parallax/cameras.txt --depth-dir out/parallax/depth --blend 0.5
```

`temporal.py` maps each current sample directly into the previous camera using relative pose,
view-space depth, and the two vertical fields of view in degrees. It avoids allocating a
world-space position image. The default gate checks interpolated depth. With
`--history-depth-mode taps`, each of the four bilinear taps has its own depth check. Accepted
taps are renormalized, and at least half of the original bilinear weight must survive.
`--no-reproject` remains the negative control.

`tools/mmtemporal/run_parallax.py` runs the whole pipeline (both renders, depth, reprojection,
export, and the learned single-frame versus stacked comparison) in one command.

## Replay with native low-resolution input

The archived Monkey captures have four eight-frame paths per run. The low-resolution raster
is 160×90 and the full-detail reference is 640×360. Median PSNR over all 32 frames with a
history blend of 0.5 was:

| Capture | Camera translation | Current frame | Mean-depth gate | Per-tap gate |
|---|---:|---:|---:|---:|
| run0 | 0 | 34.38 | 34.38 | 34.38 |
| run1 | 0.6 | 34.51 | 34.36 | 34.38 |
| run12 | 1.2 | 34.13 | 33.57 | 33.57 |
| run26 | 0.6 | 33.96 | 33.98 | 33.99 |

Reproduce either history gate by passing `mean` or `taps`:

```shell
python tools/mmtemporal/temporal.py --data out/parallax/run1 \
    --cameras out/parallax/run1/cameras.txt --depth-dir out/parallax/run1/depth \
    --history-depth-mode taps --blend 0.5 --report out/parallax/run1-temporal.json
```

On the laptop, single-thread NumPy/Pillow replay took a p95 of 20.0–28.2 ms across
these runs and methods, measured on the 28 history frames in each run. This is the sum of
history update and bicubic conversion/resize, excluding raster, file I/O, scoring, and
device transfers. It already exceeds the 16.67 ms whole-frame budget for 60 FPS.
This replay measures the quality trade-off and supplies CPU reference timings.

## Changing the mesh cut during a path

`bench_lod_history.py` alternates two native low-resolution captures. Their camera lists
and every full-detail reference PNG must match byte for byte. The policies all use the
same current raster. They use current-frame bicubic, keep depth-gated history, drop the
full history on a cut switch, or drop it only where depth or coverage changes at the
switch. The last policy checks both LODs' depth at the current pose and dilates the mask
by one low-resolution pixel. The extra depth comes from the paired archive and this
policy is an offline diagnostic.

```shell
python tools/mmtemporal/bench_lod_history.py out/parallax/run1 out/parallax/run26 \
    --switch-every 2 --out out/parallax/lod-history-switch-2.json
python tools/mmtemporal/bench_lod_history.py out/parallax/run1 out/parallax/run26 \
    --switch-every 4 --out out/parallax/lod-history-switch-4.json
```

| Frames per cut | Switch frames | Masked pixels | Current only / full reset | Keep history | Depth mask |
|---|---:|---:|---:|---:|---:|
| 2 | 12 | 8.63% | 33.958 dB | 34.192 dB | 34.113 dB |
| 4 | 4 | 8.55% | 34.067 dB | 34.149 dB | 34.183 dB |

The table reports switch-frame median PSNR. The depth mask increased mean squared
screen-space residual change by 0.4% and 1.8% compared with keeping history, respectively.
That metric is the frame-to-frame change of output minus reference at the same screen
coordinate. The small and inconsistent quality difference gives no reason to pay for a
second depth raster in this test. Validation of a GPU reconstruction pass requires a
native frame-time comparison with the full-detail raster at matched output resolution.

## Headroom for selecting history locally

`bench_history_confidence.py` compares the 0.5 history blend with two causal gates.
The support gate tapers that blend from zero at 50% valid bilinear support to 0.5
at full support. The color gate drops history when the largest RGB channel difference
exceeds 12 of 255 code values. Each temporal policy keeps its own recursive color history and
use the same per-tap depth test. Color validation is a conventional temporal AA
control. [Yang et al., A Survey of Temporal Antialiasing Techniques](https://research.nvidia.com/labs/rtr/publication/yang2020survey/)

For each tile the offline comparison can use the high-resolution target to choose the
lower-error output of current-frame bicubic or the fixed 0.5 blend after bicubic.
Choices are made separately on each frame and leave both histories untouched. This
bounds the gain from selecting between these two output images at each tested tile size.
It does not bound gains from another reconstruction filter or from accumulating on a
higher-resolution sample grid.

| Capture | Fixed blend | Support gate | Color gate | Both gates | Best 8×8 tile | Best 1×1 tile |
|---|---:|---:|---:|---:|---:|---:|
| run0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| run1 | -0.032 | -0.033 | -0.009 | -0.007 | +0.176 | +0.280 |
| run12 | -0.312 | -0.292 | -0.006 | -0.006 | +0.147 | +0.264 |
| run26 | +0.032 | +0.031 | +0.001 | +0.002 | +0.182 | +0.320 |

The gains are `10 log10(mean current MSE / mean candidate MSE)` in dB on the 28
frames with history per run. The tile dimensions refer to input raster pixels. Color
validation removed nearly all of the fixed blend loss on the fastest path and left
its frame-to-frame residual change within 0.2% of the single-frame result.

The matched paths in run1 and run26 have byte-identical cameras and target PNGs.
At the same 160×90 raster size, bicubic on the 7,074-triangle input gained 0.370 dB
over bicubic on the 4,162-triangle input. It still led the smaller mesh with hindsight
selection by 0.188 dB at 8×8 tiles and 0.050 dB at 1×1 tiles. Triangle counts are
from the depth capture logs. These results motivate spending geometry where the
low-resolution raster loses coverage instead of funding additional history gates
for this filter. The next comparison needs more assets, matched GPU frame times,
and a spatial upscaler as a control.

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
foreach ($meshRun in 0,1,12,26) {
    python tools/mmtemporal/bench_history_confidence.py "out/parallax/run$meshRun" --out "out/temporal-check/confidence-run$meshRun.json"
}
```
