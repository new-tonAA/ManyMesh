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
