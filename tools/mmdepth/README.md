# mmdepth

Software depth rasterizer for temporal reprojection.

`samples/mm_bench --camera-out <file>` writes the exact eye and target of every capture. This
tool reads that list, rasterizes the mesh the renderer actually drew, and writes one depth file
per capture. `tools/mmtemporal/temporal.py` uses those files to reproject history when the
camera translates, and to reject history across depth discontinuities.

The camera list is the point: deriving the camera path a second time in Python lets a half-pixel
disagreement turn into ghosting, which is hard to tell apart from a reprojection bug. The file
format is versioned and contains the render resolution and FOV as well.

## Usage

```shell
out/cmake-release/tools/mmdepth/mmdepth.exe <mesh> \
    --cameras out/parallax/cameras.txt --out out/parallax/depth
```

Options:

```text
  --cameras <file>  camera list written by mm_bench --camera-out (required)
  --out <dir>       output directory (required)
  --quiet           do not print per-frame progress
```

## Depth format

```text
"MMDEPTH1\n"
"<width> <height>\n"
width * height little-endian float32, row major, top-down
```

The value is view-space z: the component along the camera forward vector, in world units, not
normalised depth. Zero means no geometry covered the pixel. Files are named like the renders:
`depth_v00_j03.depth` belongs to `lr_v00_j03.png`.

The rasterizer interpolates inverse depth across the triangle, which is linear in screen space
under perspective projection. It does not cull back faces (the renderer does not either) and
skips triangles with a vertex behind the camera; the test assets stay well inside the near
plane.

## Relationship to the renderer

The tool is deliberately independent of Filament: it only needs the mesh and the camera list.
That keeps it usable in headless data generation and makes the depth buffer reproducible
without a GPU readback path, which Filament's public API does not expose for depth attachments.
It is a data-generation tool, not a visibility-buffer renderer; `tools/mmgpu` is the GPU
visibility prototype.
