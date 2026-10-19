# mmscene

Builds a large scene out of one mesh, for measuring ManyMesh at level scale rather than object
scale.

A single object under a camera has its whole geometry on screen, so per-cluster level of
detail selection has nothing to exploit beyond distance. A level is different: most of it is
off screen or far away, and what matters is how selection behaves across a large, spatially
spread set of clusters — and how much of the frame the geometry actually covers, because that
decides whether a frame is geometry bound at all.

## Usage

```shell
python tools/mmscene/make_scene.py <prop.ply> <scene.ply> \
    --rows 5 --cols 5 --spacing 420 --ground 500
```

| Option | Meaning |
|-|-|
| `--rows`, `--cols` | instance grid size |
| `--spacing` | distance between instance centres, in the prop's units |
| `--yaw-step` | degrees of yaw added per instance |
| `--scale-step` | fractional scale added per instance |
| `--ground N` | add a ground plane of `2*N²` triangles spanning the grid |

The prop must be a binary little-endian PLY with triangle faces, which is what
`tools/mmgeo` writes. The layout is deterministic, so two runs produce identical geometry.

## Why synthetic

The public scene archives (Bistro, San Miguel, Powerplant, the Sponzas) are hundreds of
megabytes to a gigabyte each, and the machine this was built on has a slow link and has to
stay usable for other work. Tiling an existing mesh gives a scene of any size, immediately,
with no network and fully reproducible.

That is a weaker test than a real scanned level: it has no walls, no interior, no
architectural depth complexity. `--ground` is there to put something large and close in the
frame, because without it the scene occupies two percent of the picture and any image metric
ends up measuring empty background.

> **Winding.** The ground plane is wound so its normals point up. The obvious ordering gives
> `(0, -dx*dz, 0)`, which faces down and is backface culled from any camera above it — the
> scene then renders with no ground at all and looks like a much sparser scene than it is.

## What it showed

A 5×5 grid of a 416k triangle mesh plus a 500k triangle ground: **10,903,075 triangles**,
extent 2100 × 123 × 2100.

From a camera at ground level looking along the scene, at 640×360 on an Intel Iris Xe:

| | |
|-|-|
| culled by the frustum | 49.0% |
| drawn | 1,333,651 (12.2% of the scene, 24.0% of what survives culling) |
| GPU frame time | ~52.8 ms → 8.82 ms (about 6×) |
| PSNR / SSIM against full detail | 30.29 dB / 0.9297 |

The frame time is the interesting number. Drawing an eighth of the triangles bought about 6×
(measured runs varied from 4.7× to 7.1×), which tracks the 8.2× reduction in drawn triangles.
The 30.29 dB is worse than the same test on a single object (35.7 dB) because the errors show
up across a large near surface rather than at a few silhouettes.
