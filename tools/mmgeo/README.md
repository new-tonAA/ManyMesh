# mmgeo

The offline half of ManyMesh's **geometry optimization layer**. It clusters a mesh, builds a
per-cluster LOD chain, and reports the geometric error each level introduces — both in world
units and projected into screen space. The result is the *Geometry Error Map* that the neural
reconstruction stage is meant to consume.

See [`MANYMESH.md`](../../MANYMESH.md) for how this fits into the wider project.

## What it does

```text
high poly mesh
      |
      v
  clusterize (meshoptimizer meshlets)      -> per-cluster bounding sphere + normal cone
      |
      v
  per-cluster QEM simplification           -> a LOD chain per cluster, border locked so that
                                              neighbouring clusters do not crack apart
      |
      v
  screen space error + level selection     -> coarsest level per cluster that fits a pixel
                                              budget, computed from the camera
      |
      v
  clusters.json + error_map.pgm + OBJs
```

Everything runs on the CPU and needs no GPU, no Filament engine and no Android. That is
deliberate: it makes the geometry side testable and lets the error map be studied long before
anything is wired into a renderer.

## Building

`mmgeo` is part of the normal Filament build. On Windows, `build.sh` cannot be used (Filament
refuses MSYS2 environments); configure with the VS toolchain and build the target directly:

```bat
cmake -S . -B out\cmake-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DFILAMENT_BUILD_TESTING=ON
ninja -C out\cmake-release mmgeo
```

Everything is registered in the root `CMakeLists.txt` (`add_subdirectory(${TOOLS}/mmgeo)`).

## Usage

```text
mmgeo <input mesh> [options]

  --out <dir>          output directory (default: out/mmgeo)
  --mode chain|cluster global LOD chain, or per-cluster LOD (default: cluster)
  --levels N           number of LOD levels including the original (default: 5)
  --ratio F            fraction of triangles kept per level (default: 0.7)
  --target-error F     relative error ceiling for simplification (default: 0.01)
  --cluster-verts N    max vertices per cluster, <= 255 (default: 128)
  --cluster-tris N     max triangles per cluster, <= 512 (default: 128)
  --cone-weight F      0 = size driven clusters, 1 = favour cone culling (default: 0)
  --lock-border 0|1    per-cluster mode: never move cluster borders (default: 1)
  --eye x,y,z          camera position; omit to auto-frame the mesh
  --look-at x,y,z      camera target (default: mesh centre)
  --fov-y <deg>        vertical field of view in degrees (default: 45)
  --screen-height N    screen height in pixels for the error map (default: 1080)
  --threshold-px F     screen space error budget in pixels (default: 1.0)
```

Input can be anything assimp reads: OBJ, PLY, FBX, Collada, ... Triangle soup is triangulated,
duplicate vertices are welded and node transforms are baked, so everything downstream lives in
one world space.

Example, on a scan with seven million triangles:

```shell
mmgeo out/models/xyzrgb_dragon.ply --out out/mmgeo-dragon --levels 5 --cluster-tris 128
```

## Outputs

| File | Contents |
|-|-|
| `clusters.json` | per cluster: bounding sphere, normal cone, and per level the triangle count and world space error |
| `lod<N>.obj` | every cluster at level N, clamped to the coarsest level a cluster actually has |
| `selected.obj` | exactly the triangles the given camera and pixel budget would draw |
| `error_map.pgm` | screen space geometry error, software rasterized. Black is untransformed geometry, white is at the pixel budget |

`error_map.pgm` is a plain binary PGM (P5), which every image viewer and most Python stacks
read directly.

## The two LOD modes

- **`--mode chain`** is the classic baseline: one LOD chain for the whole mesh, every level
  simplified from the original. This is what a distance based LOD system would ship.
- **`--mode cluster`** is the architecture ManyMesh is built around. Each cluster gets its own
  chain, so the error a level introduces is *local*. A view can then pick a different level per
  cluster instead of one level for everything, which is what turns a fixed LOD into a budget
  that can be spent where it is visible.

Clusters are simplified with `meshopt_SimplifyLockBorder`, i.e. their outer boundary vertices
are never removed. Without it, independently simplified neighbours would crack apart along
their shared seams. The price is that border triangles can never be collapsed.

### A note on error

`meshopt_simplify` reports error relative to the mesh extent; multiplying by
`meshopt_simplifyScale` gives world units, which is what `clusters.json` records. Screen space
error then projects the world error of a cluster at its nearest depth:

```text
pixels = (error / distance) * screenHeight / (2 * tan(fovY / 2))
```

Because levels are ordered from fine to coarse with non decreasing error, selection simply
walks from the coarsest level down and takes the first one that fits the budget. When even full
detail does not fit, full detail is what is kept.

## Test model

Getting a genuinely high-polygon mesh is part of the point of this tool, so for the initial
experiments we use the **Stanford 3D Scanning Repository**:

| Model | Triangles | File |
|-|-|-|
| Asian Dragon | 7,219,045 | `xyzrgb_dragon.ply.gz` (67 MB compressed) |

Downloaded from <https://graphics.stanford.edu/data/3Dscanrep/> and kept under `out/models/`,
which is gitignored — the model is not redistributed with this repository.

> **Terms of use.** The Stanford models may be used and redistributed for research and other
> non-commercial purposes, with credit to the Stanford Computer Graphics Laboratory; commercial
> use requires permission. The dragon, buddha, Thai statue and Lucy carry an additional
> restriction against animating, morphing, applying Boolean operations to, or running
> destructive simulations on them. Rigid rendering and geometric simplification — what this
> tool does — are ordinary academic use, but obtain permission before any commercial
> application. If that becomes necessary, license-clean alternatives exist (Thingi10k, CC0
> models on Sketchfab).

## Measured behaviour

On the Stanford Asian Dragon (3,609,600 vertices, 7,219,045 triangles) on an Intel 12th gen
laptop CPU, a full per-cluster run takes about 15 seconds: 4.5 s to load, 9.1 s to build
56,399 clusters, 14.0 s to build five levels for every one of them, under a second to select
and rasterize. Memory peaks around 550 MB.

The two modes are not equivalent, and the difference is the interesting part:

| Mode | Coarsest level | Max world error |
|-|-|-|
| `chain` (the classic baseline) | 1,733,244 triangles (24%) | 0.0169 |
| `cluster` (border locked) | 2,366,276 triangles (33%) | 0.0779 |

Simplifying each cluster in isolation costs **4.6x the error for 36% more triangles**: with
its border locked, a cluster can only remove triangles inside its own patch, and error cannot
be redistributed across the mesh the way a global simplification does. This is the same
problem Nanite solves with *cluster groups* — simplifying groups of adjacent clusters together
with a border that is shared inside the group — and it is the next thing to try here. The
per-cluster selection granularity is worth keeping either way.

A second observation: for a densely oversampled scan, screen space error barely binds at all.
Even at the coarsest level the worst cluster sits around 0.46 px against a 1.0 px budget, and
tightening the budget to 0.25 px changes almost nothing. That is the premise ManyMesh is built
on — scans carry far more triangles than the image needs — and it means the win has to come
from reducing *processing cost*, not from chasing visible artefacts.

## Implementation notes

The algorithms are `meshoptimizer`'s, not ours: `meshopt_buildMeshlets` for clustering,
`meshopt_computeMeshletBounds` for the per-cluster bounds, `meshopt_simplify` for the
quadric-based collapse, and `meshopt_simplifyScale` to put the error in world units.
meshoptimizer is already vendored and built as part of Filament, so this tool adds no new
dependency. Note that the vendored version is 0.18, which predates
`meshopt_simplifyWithAttributes`; simplification is therefore driven by positions alone, and
attribute seams would have to be handled with `meshopt_generateShadowIndexBuffer` first.
