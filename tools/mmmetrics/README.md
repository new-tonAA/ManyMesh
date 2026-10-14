# mmmetrics

Image quality metrics for ManyMesh. Compares rendered frames and reports PSNR, SSIM and
optionally LPIPS, so that a geometry reduction can be judged by what it did to the picture
rather than only by what it did to the mesh.

Nothing in Filament provides these. Its own comparators — `tools/diffimg` and
`libs/imagediff` — are absolute-difference and tolerance based, which answers "did this render
change beyond acceptable bounds" but not "how much quality did we give up".

## Usage

```shell
python tools/mmmetrics/compare.py <reference.png> <candidate.png> [more...] [options]

  --labels a,b,c    names for the table (default: file names)
  --json <path>     also write the results as JSON
  --diff <path>     write a difference image for the first candidate
  --gain N          brightness factor for the difference image (default: 4)
  --lpips           also compute LPIPS (needs `pip install lpips`)
```

Example, comparing a mesh against progressively coarser versions of itself:

```shell
python tools/mmmetrics/compare.py \
    out/dragon-renders/lod0.png \
    out/dragon-renders/lod1.png out/dragon-renders/lod2.png \
    out/dragon-renders/lod3.png out/dragon-renders/lod4.png \
    --labels "70pc,49pc,34pc,24pc" \
    --json out/dragon-quality.json --diff out/dragon-diff.png
```

The reference is the first path; every path after it is a candidate, so the reference is
not repeated in `--labels`. Labels are a single comma separated argument.

## Notes on the metrics

- **PSNR** is computed on the 8-bit sRGB values, which is the usual convention, and is
  reported as `inf` for identical frames.
- **SSIM** is the mean of the windowed similarity map rather than skimage's scalar summary.
  A single global number hides exactly the failure mode that matters here: a simplification
  artefact is a small region going wrong while everything around it is untouched.
- **LPIPS** is optional because it needs the `lpips` package and downloads AlexNet weights on
  first use. It is the metric that correlates best with human judgement, so it is worth
  enabling for anything being written up. On a CPU-only machine it is slow but workable.
- `pixels_over_1_255_percent` counts pixels where any channel moved by more than one 8-bit
  step. It is a blunt "did anything change at all" figure, useful for catching a render that
  silently did not load the mesh it was supposed to.

## Producing the images

The frames come from `samples/mm_bench`, which renders a mesh from a fixed camera with a
fixed material, lighting and exposure, and draws no UI. Both properties matter: the stock
samples render their ImGui panels, and a comparison between two such screenshots mostly
measures the overlay.

```shell
out/cmake-release/samples/mm_bench --headless --window-size 1280x720 \
    --fixed-timestep=0.0166667 --out lod0.png \
    --eye 2.220,-6.737,220.771 --target 2.220,-6.737,9.837 \
    --warmup 20 --measure 60 mesh.obj
```

`mm_bench` also reports GPU frame time (median, p99, max) over the measured frames, which is
the performance half of the same comparison.

> **Note for anyone writing a similar harness.** Do not leave the view on Filament's camera
> manipulator. The manipulator derives its projection from window events, which never arrive
> when rendering offscreen, and the resulting view renders *nothing at all* — no error, just an
> empty frame. Creating a camera with `Engine::createCamera` and calling `View::setCamera` is
> what makes headless rendering work. `samples/hellotriangle` does this; `material_sandbox`
> does not, which is why its headless screenshots contain only UI.
