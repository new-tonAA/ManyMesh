# m4alloc

First slice of M4: geometry allocation when a reconstruction network is part of the loop.

The geometry stage can spend the same triangle budget in different places:

- **uniform** (`selectLodGraphAtRatio`): every part of the model loses the same fraction.
- **distance** (`selectLodGraph` with a screen-space error threshold): near or high-error
  geometry stays detailed, distant or low-error geometry gets coarser.

`run.py` renders the same camera sweep from both allocations at a matched triangle count, trains
the *same* tiny reconstruction network on each (same seed, iterations, and view split), and
reports PSNR/SSIM before and after reconstruction. The question is whether the ranking survives
the network. If it does, allocation is a pure geometry decision. If it changes, the two stages
are coupled and the joint optimization has something to optimize.

One camera per `mm_bench` invocation is deliberate: the printed `selectedTriangles` belongs to
the cut of that view, while a multi-view run reports only the last one. The script also prints
the actual retained ratio, because `--target-ratio` is a target and the quality gate is allowed
to stop above it.

## Usage

```shell
python tools/m4alloc/run.py --mesh assets/models/monkey/monkey.obj \
    --out out/m4-monkey --ratios 0.35 --views 8 --iterations 2000
```

Useful flags:

```text
  --ratios 0.35,0.25   retained triangle ratios to compare
  --views N            evenly spaced orbit views
  --skip-render        reuse already rendered images
  --skip-train         render and calibrate only
```

Outputs per ratio: `uniform/lr_vNN.png`, `distance/lr_vNN.png`, the shared `hr/hr_vNN.png`, a
`summary.json`, and `<strategy>_tiny.json` / `<strategy>_bicubic`.

## Calibration

The distance allocation has a screen-error threshold rather than a triangle ratio, so the script
bisects the threshold until its measured ratio matches the uniform cut's measured ratio within
the tolerance of the sweep. Both strategies are then compared at the same number of drawn
triangles, which is the constraint that matters on a mobile GPU.

The distance selector is discrete: on monkey at 640x360 its cuts are 4,162 / 5,130 / 5,966 /
6,914 / 7,642 triangles, and a threshold in the middle of a plateau does not move the cut. The
uniform selector can hit values in between, so an arbitrary `--ratios` target can leave the two
strategies a few percent apart. Pick uniform targets equal to one of the distance cuts (0.264,
0.326, 0.379, 0.439, 0.485) when an exactly matched comparison matters. The first run at 0.35
landed at 5,504 uniform versus 5,130 distance; that is why the matched runs use 0.326 and 0.379.

## What it showed

On a single centered object the two strategies are not merely similar: at matched triangle
counts they render **bit-identical images**. There is no allocation freedom to measure, because
every cluster is at the same depth and the ratio bisection lands on the same DAG levels as the
error threshold. This is a property of the benchmark, not of the implementation; M4 has to use a
scene with depth variation.

A three-instance row (3 monkeys along z, 47,232 triangles, camera at the near end) does have a
real difference: at 35% (16,532 versus 16,300 triangles) 0.03–0.46% of pixels differ, and
**uniform wins by 0.56 dB** (38.52 versus 37.96). The tiny network adds only +0.04–0.05 dB at
that quality, so the ranking is unchanged after reconstruction. At the quality floor (31.86%,
15,050 triangles) both strategies again collapse to the same cut and produce identical images.

The honest reading is that "allocate by geometric error" is not a free win, and at 38 dB the
reconstructor has no headroom to reverse it. A joint-optimization result needs a lower-quality
geometry regime or a temporal reconstruction budget; see section 7.10 of `MANYMESH.md`.

## Offline cuts for large assets

Building a DAG inside every `mm_bench` run is practical up to a few hundred thousand triangles;
on the 2M-triangle dragon coarse mesh one build takes minutes. `mmgeo` can now build the DAG
once and export several cuts from it:

```text
--target-ratio-cut 0.262,0.287    uniform cuts -> selected_ratio_<R>.ply
--screen-error-cut 1,2,4         screen-error cuts -> selected_px_<P>.ply
```

The primary `--target-ratio` output is still `selected.ply`. Render the exported meshes with:

```shell
python tools/m4alloc/run_preselected.py \
    --uniform-mesh selected_ratio_0.262.ply --distance-mesh selected_px_2.ply \
    --target-mesh full_detail.ply --out out/run --views 8 --iterations 2000
```

`run_budget_sweep.py` takes a comma-separated list of such meshes and reports PSNR versus
triangle count for bicubic and tiny. It can reuse an existing target set
(`--target-dir out/m3 --camera-list out/m3/views.txt`) so a multi-million-triangle target is
rendered once, not once per sweep. The horizontal gap between the bicubic and tiny curves is
the geometry budget the reconstructor buys; that is the useful M4 quantity.
