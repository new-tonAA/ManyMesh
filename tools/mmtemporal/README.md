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
learns. That model, and a recurrent history buffer, are the remaining step.
