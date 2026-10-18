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
  split connected attribute charts          -> UV/normal seams become cluster borders
      |
      v
  clusterize (meshoptimizer meshlets)      -> per-cluster bounding sphere + normal cone
      |
      v
  group adjacent clusters (optional)       -> the unit simplification actually works on
      |
      v
  attribute QEM + quality gate             -> a LOD chain per unit, border locked so that
                                              neighbouring units do not crack apart;
                                              normal/UV cost and world-space error are gated
      |
      v
  screen space error + level selection     -> coarsest level per cluster that fits a pixel
                                              budget, computed from the camera
      |
      v
  clusters.json + error_map.pgm + OBJs/PLYs
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

  --out <dir>           output directory (default: out/mmgeo)
  --mode chain|cluster|dag
                        global chain, per-cluster chain, or hierarchical DAG
  --levels N            number of LOD levels including the original (default: 5)
  --ratio F             fraction of triangles kept per level (default: 0.7)
  --target-error F      relative world-space error ceiling (default: 0.01)
  --cluster-verts N     max vertices per cluster, <= 255 (default: 128)
  --cluster-tris N      max triangles per cluster, <= 512 (default: 128)
  --split-charts 0|1    keep clusters inside connected attribute charts (default: 1)
  --group-size N        clusters merged into one per-cluster unit (default: 1)
  --dag-group N         children merged into one DAG parent (default: 8)
  --tier maximum|balanced|aggressive
                        DAG selection tier (default: balanced)
  --target-ratio F      DAG selection: smallest cut reaching this triangle ratio
  --lock-border 0|1     never move cluster borders (default: 1)
  --attribute-qem 0|1   position + normal + UV QEM for small units (default: 1)
  --quality-gate 0|1    reject cracked/non-manifold/flipped/sliver/over-error candidates
  --quality-debug 0|1   print rejected candidates and their metrics
  --quality-attempts N  retries per unit after a rejection (default: 4)
  --min-quality F       minimum normalized triangle quality (default: 0.02)
  --max-normal-error F  maximum normal deviation in degrees (default: 35)
  --max-uv-error F      maximum mean UV deviation (default: 0.10)
  --write-dag 0|1       write lod_graph.mmb / lod_graph.json (default: 1)
  --visibility 0|1      write the CPU visibility-buffer reference (default: 0)
  --page-bytes N        streaming page size (default: 65536)
  --eye x,y,z           camera position; omit to auto-frame the mesh
  --look-at x,y,z       camera target (default: mesh centre)
  --fov-y <deg>         vertical field of view in degrees (default: 45)
  --screen-height N     screen height in pixels for the error map (default: 1080)
  --threshold-px F      screen-space error budget in pixels (default: 1.0)
```

Input can be anything assimp reads: OBJ, PLY, FBX, Collada, ... Triangle soup is triangulated,
fully identical vertices are joined, and node transforms are baked, so everything downstream
lives in one world space. UV and normal seams keep their duplicated vertices; those seams are
used to split connected attribute charts before clustering, so a cluster never simplifies
across a seam.

Example, on a scan with seven million triangles:

```shell
mmgeo out/models/xyzrgb_dragon.ply --out out/mmgeo-dragon --levels 5 --cluster-tris 128
```

## Outputs

| File | Contents |
|-|-|
| `clusters.json` | per cluster: bounding sphere, normal cone, and per level the triangle count and world space error |
| `lod<N>.ply/.obj` | every cluster at level N, clamped to the coarsest level a cluster actually has |
| `selected.ply/.obj` | exactly the triangles the given camera and pixel budget would draw |
| `error_map.pgm` | screen space geometry error, software rasterized. Black is untransformed geometry, white is at the pixel budget |

`error_map.pgm` is a plain binary PGM (P5), which every image viewer and most Python stacks
read directly.

## The three LOD modes

- **`--mode chain`** is the classic baseline: one LOD chain for the whole mesh, every level
  simplified from the original. This is what a distance based LOD system would ship.
- **`--mode cluster`** is the architecture ManyMesh is built around. Each cluster gets its own
  chain, so the error a level introduces is *local*. A view can then pick a different level per
  cluster instead of one level for everything, which is what turns a fixed LOD into a budget
  that can be spent where it is visible.
- **`--mode dag`** builds a hierarchical cluster DAG: every cluster keeps its own chain, and
  groups of up to `--dag-group` children are simplified again as parent nodes. A selection is a
  non-overlapping cut through this hierarchy, so near clusters can stay at a fine level while
  far clusters use a coarse ancestor. `--target-ratio` asks for the most detailed cut that fits
  a triangle budget; `--tier` selects the quality/saving profile. The actual ratio is printed,
  because the quality gate may stop above the requested budget.

## Quality gate

With `--quality-gate 1` (the default), a candidate level must keep the exact boundary-edge set
of its source unit, must not add non-manifold edges, must contain no duplicate, degenerate or
flipped triangles, must meet `--min-quality`, and must stay within the world-space error cap
derived from `--target-error`. `--quality-debug 1` prints the reason a candidate was rejected.

This is deliberately conservative, but the gate now understands paired seam copies: the two
sides of a duplicated UV/normal seam can be collapsed together and validated against a welded
position boundary. On the UV-seamed torus this lowers the 50% request from the old 66.32%
floor to **562 / 1,152 = 48.78%**, with no welded boundary and no new non-manifold edges.
More extreme reduction across three or more coincident copies needs generated vertices and
attribute interpolation; do not relax the quality gate to approximate that.

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

## Build performance

DAG construction now uses a BVH for the quality gate, shares one closest-point query between
position and attribute error, and simplifies independent cluster chains and groups in
parallel. Results are merged in deterministic input order, so the graph is bit-for-bit
identical to the serial build.

On the bundled cloth asset (74,976 triangles, group 8, five levels, ratio 0.7), the build went
from **37.02s** to **1.93s** while keeping the same
`1915 nodes / 7 levels / 252 roots / 589 leaves` and
`38098 / 74976 = 50.81%` cut. The BVH/shared-query serial path takes **18.18s**, so parallel
scheduling is a further 9.4x. The 588-node monkey DAG builds in about **0.23s**. Use
`mmgeo --mode dag ...` to print the cluster, chain, group, and quality-gate phase timings, and
set `MANYMESH_BUILD_THREADS=1` to reproduce or A/B the serial build.

## Measured behaviour

On the Stanford Asian Dragon (3,609,600 vertices, 7,219,045 triangles) on an Intel 12th gen
laptop CPU, a full per-cluster run takes about 15 seconds: 4.6 s to load, 9.0 s to build
56,399 clusters, 14.2 s to build five levels for every one of them, under a second to select
and rasterize. Memory peaks around 550 MB.

Each level keeps `ratio^level` of its unit's triangles, so comparing configurations at the
same level index compares them at the same amount of reduction. Level 3 keeps about 34%:

| Configuration | Units | Triangles | Mean world error | Max world error |
|-|-|-|-|-|
| `--group-size 1` | 56,399 | 2,374,748 | 0.013533 | 0.255045 |
| `--group-size 8` | 7,050 | 2,468,995 | 0.009080 | 0.175334 |
| `--group-size 32` | 1,763 | 2,474,497 | 0.007927 | 0.031153 |
| `--group-size 64` | 882 | 2,474,495 | 0.007702 | 0.024651 |
| `--mode chain` | 1 | 2,476,053 | – (a single global bound) | 0.012313 |

Three things fall out of this:

1. **Simplifying clusters alone is structurally expensive.** Even the *mean* error, 0.0135,
   is worse than the global chain's *worst* error, 0.0123. With its border locked a cluster
   can only remove triangles inside its own patch, and error cannot be redistributed the way
   a global simplification redistributes it.
2. **Grouping buys most of that back, monotonically.** Mean error falls 0.01353 → 0.00770
   (43%) from 1 to 64 clusters per group, and the worst error drops from 0.255 to 0.025. The
   lock then only covers the *group's* outer boundary; edges the members share become interior
   and are free to collapse. This is Nanite's cluster group idea, and here it cost one extra
   function — a group is just a bigger cluster, so everything downstream is reused unchanged.
3. **The global chain still wins.** On the only directly comparable number, the chain's worst
   case (0.0123) beats group 64's (0.0247). Grouping narrows the gap but cannot close it,
   because a group's outer boundary is still locked while the chain may move any border it
   likes. Hierarchical groups, or a cluster DAG, are the obvious next step.

A note on reading these numbers: `meshopt_simplify`'s `target_error` is relative to the extent
of the vertex buffer it is handed, so it has to be rescaled to world units per unit — otherwise
the same "1%" would mean a different absolute deformation for a big group than for a small
cluster, and the cap rather than the triangle budget would decide the outcome. `Simplifier.cpp`
does that rescaling.

Finally, for a densely oversampled scan the pixel budget is a weak lever: tightening it from
2.0 px to 0.1 px only moves the drawn triangle count from 27.4% to 36.5%, because most
clusters are already at their coarsest level. That is the premise ManyMesh is built on — scans
carry far more triangles than the image needs — and it means the win has to come from reducing
*processing cost*, not from chasing visible artefacts.

## Visual regression audit

The reduction was checked by rendering each original mesh and its selected LOD from the same
camera, resolution and lit material (`aiDefaultMat.filamat`, 960x720), then measuring PSNR/SSIM
with `tools/mmmetrics/compare.py` and inspecting the frames directly. The 7.2M-triangle dragon
was rerun with the current chart split; the smaller assets cover explicit UV/normal seams.

| Model | Selected / original | Reduction | PSNR | SSIM | Visual verdict |
|-|-|-|-|-|-|
| Stanford dragon | 2,466,045 / 7,219,045 | 34.2% | 35.19 dB | 0.96124 | No holes; scales and horns slightly softened |
| Sphere | 1,808 / 8,064 | 22.4% | 37.32 dB | 0.99163 | Silhouette facets; a thin lit seam line appears in the most extreme level, but topology stays closed |
| Monkey | 3,794 / 15,744 | 24.1% | 28.06 dB | 0.93454 | Eyes, ears and chin clearly coarser; no new boundary edges |
| Torus | 390 / 1,152 | 33.9% | 37.06 dB | 0.99149 | Noticeably polygonal, no cracks |
| Cloth | 43,098 / 74,976 | 57.5% | 44.27 dB | 0.99709 | Visually unchanged at this framing |
| Shapes | 15,064 / 73,728 | 20.4% | 63.10 dB | 0.99995 | Floor and small spheres intact |

The important failure that motivated the chart split was a black triangular hole on a sphere
reduced to 25%: before the fix the render scored 30.75 dB, after it 37.57 dB and the hole was
gone. The boundary-edge check now also agrees with the source meshes: the sphere and torus stay
closed, and the monkey's 168 open edges are exactly the ones the original OBJ already has.

Known limits: per-face material IDs are not carried through this pipeline, and simplification
still uses position-only QEM. Those are separate from geometric tearing, but both matter before
using the output as a production asset.

## Implementation notes

The algorithms are `meshoptimizer`'s, not ours: `meshopt_buildMeshlets` for clustering,
`meshopt_computeMeshletBounds` for the per-cluster bounds, `meshopt_simplify` for the
quadric-based collapse, and `meshopt_simplifyScale` to put the error in world units.
meshoptimizer is already vendored and built as part of Filament, so this tool adds no new
dependency. The vendored version is 0.18, which predates
`meshopt_simplifyWithAttributes`; simplification is therefore driven by positions alone.
`Clusterizer.cpp` protects attribute seams by splitting the mesh into connected charts from the
shared-index graph, then clustering and grouping each chart independently. Normals and UVs are
carried through to the output, but they do not participate in the error metric.
