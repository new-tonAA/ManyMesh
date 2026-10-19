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

`temporal.py` uses the current frame's depth to reconstruct each pixel's world position, projects
it through the previous camera, and rejects history whose previous-frame depth disagrees with
that position. That depth test is the disocclusion mask that a pure rotation could not test.
`--no-reproject` remains the negative control.

`tools/mmtemporal/run_parallax.py` runs the whole pipeline (both renders, depth, reprojection,
export, and the learned single-frame versus stacked comparison) in one command.
