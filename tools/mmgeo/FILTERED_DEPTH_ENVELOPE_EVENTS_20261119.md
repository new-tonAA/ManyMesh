# Filtered depth-envelope events along an orthographic camera segment (2026-11-19)

## Motivation and prior-art limit

The current camera-path event prototype tracks coverage changes, while a measured learned
proposal had depth-only sampled error. A possible extension is to track, for each subpixel sample,
the frontmost triangle's affine depth as the camera translates orthographically. Coverage endpoints
and pairwise depth-line crossings partition the path into intervals where each sample's visible
surface is fixed. A spatial reconstruction filter forms weighted sums of those sample residuals;
within each path interval the filtered depth residual is affine, so its squared error has a closed
form integral.

This underlying interval visibility problem is already adjacent to *Continuous from-Segment
Visibility* (TVCG 2025), which computes coverage and depth visibility intervals along a camera
translation segment ([primary paper](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)).
Local image-error mesh simplification and local redraw are also established in *Image-Driven
Simplification* (SIGGRAPH/TOG 2000, [primary paper](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)).
Camera-trajectory-aware mesh representations are also an active established direction: *Temporally
Smooth Mesh Extraction for Procedural Scenes with Long-Range Camera Trajectories using Spacetime
Octrees* (SIGGRAPH Asia 2025) constructs temporally coherent view-dependent meshes along known
long trajectories ([proceedings record](https://doi.org/10.1145/3757377.3763832)). Its procedural
occupancy extraction setting differs from legal edge collapse on a fixed connected input mesh, but
it further rules out camera-path mesh adaptation itself as a novelty claim.
Reich et al.'s *Illumination-Driven Mesh Reduction* (CGF 2015) already traces camera paths to
compute mesh importance and drives standard edge collapses with that signal
([primary paper](https://diglib.eg.org/bitstream/handle/10.1111/cgf12688/v34i4pp165-174.pdf?sequence=1)).
Zhang, Wang, and Kaufman's *Image-Space-Guided Simplification* (TVCG 1997) already combines edge
collapse merge trees, image-space feedback, visibility, and incremental frame-coherent updates
([primary paper](https://www.cs.umd.edu/gvil/papers/av_vd.pdf)). These close camera-path weighting,
image-space feedback, and incremental view-dependent simplification as broad novelty claims; they
do not by themselves establish exact filtered loss integration for a legal collapse along a path.
The only possible distinction to investigate is efficient **filtered source-versus-legal-collapse
loss updating** with depth events and common-scene visibility, not event integration or image-driven
simplification in general.

## Synthetic analytic screen

`probe_filtered_depth_envelope_events.py` constructs a scene with two triangles sharing a projected
footprint but having depth planes `z=0.25x+0.4` and `z=-0.25x+0.4`. Under orthographic translation,
the source visibility switches at the depth crossing; the candidate keeps only the first layer.
Three weighted subpixel samples model a reconstruction filter.

- Piecewise event integration: `0.007111979166666666`.
- Direct midpoint integration with 400,000 path samples: `0.007111979166537503` (relative
  difference `1.82e-11`).
- If depth-crossing events are omitted and only coverage endpoints are used, the integral becomes
  `0.004126302083333333`, a `41.98%` relative error on this case.
- Twelve randomized layer subsets, checked against 50,000 dense path samples each, had worst
  relative difference `1.76e-4`.

These are synthetic affine-plane checks. They do not evaluate a legal edge collapse, real mesh
occlusion, perspective, actual filter kernels, image loss over a real trajectory, or runtime cost.
They validate the piecewise-affine envelope calculation only and establish no novelty.

## One real legal-collapse slice

I then applied the same calculation to legal Monkey candidate 5852 from the frozen capture. The
source has 15,744 triangles; the collapse removes two degenerate faces and changes ten incident
faces. In the camera basis at angle 2.3, I translated orthographically along the horizontal axis
through the affected patch and used three weighted filter samples. The union contained 94 events,
including six pairwise depth-crossing records. The analytic integral was `1.2944540110569714e-4`;
two-point Gauss evaluation on every event interval agreed within `1.7e-15` relative error. A
uniform 500,000-step midpoint integral differed by `2.44e-4`, consistent with sampling across
piecewise visibility transitions. For this particular slice, omitting depth crossings did not
change the filtered loss: those six crossings switched common source/candidate visibility alike.

This is only one projected slice and an artificial translation path; it does not reproduce the
captured camera rotation path or full image filter. The prototype also scans all 15,744 triangles
to build its line lists for each of three filter samples. It therefore has **no measured cost
advantage** over local redraw and likely fails the intended cost gate as written. The result shows
the arithmetic can handle an actual legal-collapse mesh and also identifies the missing algorithmic
part: update common-scene depth envelopes without a per-candidate full-mesh scan.

## Decision and next gate

This makes depth-order events mathematically tractable for orthographic translation and confirms
that coverage-only integration can materially miss path error. It does not yet justify extending
the production simplifier. The next gate is a single captured legal collapse on a real mesh: use a
fixed camera segment and a small deterministic set of filter samples, compare event integration
against dense direct source/candidate depth and coverage evaluation, then measure total CPU work
against local redraw. Include shared unchanged occluders. If the algorithm must enumerate most of
the full mesh or is not cheaper than local redraw, close it. Keep the experiment small and check
available memory before any renderer or build run.

Reproduce the synthetic screen with:

```powershell
python tools/mmgeo/probe_filtered_depth_envelope_events.py
```

The output is written to ignored `out/filtered-depth-envelope-events-20261119.json`.

Reproduce the real-collapse slice with:

```powershell
python tools/mmgeo/probe_real_collapse_depth_events.py --candidate 5852 --angle 2.3 --steps 500000 --out out/real-collapse-depth-events-5852-angle230.json
```

## Shared-envelope batch screen

To test whether the missing per-candidate full-mesh scan could be removed, I selected 12 legal
collapses from the one-ring around candidate 5852 and formed the union of all incident faces. The
fixed local tile and orthographic path are shared by every candidate. The unchanged 15,725 faces
build one source depth envelope; each candidate then overlays only its changed faces plus source
faces in the batch union that are unchanged for that candidate.

- Full reference: 566,712 candidate face-sample visits (15,742 valid post-collapse faces per
  candidate × three filter samples); cached overlay: 372 candidate-local face-slot visits.
- All 12 cached energies matched the full-mesh reference exactly at double precision
  (`max relative difference = 0`). Four candidates had nonzero loss on this tile; the other eight
  were zero in both methods.
- Including the shared source-line construction and envelope build, measured probe time was
  `0.6875 s` full versus `0.0735 s` cached (`9.36x` for this 12-candidate batch). This is a single
  Python timing run, not a stable benchmark.
- The common source setup was `0.0513 s`; envelope construction was `0.00032 s` in this case.

Reproduce with:

```powershell
python tools/mmgeo/probe_shared_depth_envelope_batch.py --candidate-limit 12
```

The detailed per-candidate results are in the ignored output
`out/shared-depth-envelope-batch-20261119.json`. This is evidence that a shared envelope can
preserve the probe's exact result while avoiding repeated line construction for a local batch. It
does **not** show a speedup over the renderer's local redraw: the workload is a one-dimensional
filter tile, orthographic translation, and Python event code; it excludes pixel rasterization,
full-image filter support, perspective, camera rotation, memory traffic in a production data
structure, and repeated timing. Eight zero-loss cases also make this batch a weak quality screen.
The next gate is to test diverse nonzero candidates/tiles and compare the total shared update against
the actual local redraw cost. If that advantage does not persist, close this branch. No SIGGRAPH
novelty claim is established; the potentially distinct question remains exact filtered visibility
loss updates for legal collapses with shared occluders, and needs a broader prior-art search.

### Spatial and camera-angle replication

I repeated the same 12-candidate experiment for three additional seed IDs (0, 15000, 30000,
44000) in the frozen 45,746-candidate Monkey capture, then repeated seed 44000 at camera angles
1.1 and 4.6 (the original was 2.3). Across 72 candidate-angle evaluations, the maximum relative
energy difference was `3.46e-16`. The one-run Python speedups ranged from `5.81x` to `10.48x`, with
median `7.95x` across the four spatial seed batches at the original angle. Each batch scanned
566,712 post-collapse face-sample slots in the full reference and 360 local face slots in the
cached update. However, only 11/72 candidate-angle evaluations had nonzero loss on their selected
1D tile; the three added angles for the seed-44000 neighborhood all produced zero loss. Therefore
the replication supports the cache
decomposition's arithmetic on these samples, but it does not establish broad useful coverage or
robust runtime benefit. It also remains a one-mesh, one-path-axis experiment and still lacks the
actual local-redraw baseline. Per-run raw outputs are ignored under `out/shared-depth-envelope-batch-seed*.json`.

### Dense local-redraw surrogate comparison

I added `probe_shared_envelope_dense_redraw.py` to compare the exact overlay with a stronger
software baseline. At each midpoint on the same path, it depth-tests the candidate's local
triangles against the cached common envelope, evaluates the three-tap filtered loss, and sums the
samples. The run uses the seed-44000 batch at angle 2.3, where 11 of 12 candidates have nonzero
loss. Both methods share the same source/common-envelope and local-line setup; only dense point
evaluation versus exact event evaluation differs.

- Shared setup: `0.0460 s`; all candidate-local line setup: `0.0037 s`; exact event solves for 12
  candidates: `0.0658 s` (total `0.1155 s`).
- Dense midpoint evaluation for all candidates: 128 steps `0.0217 s`, with summed absolute energy
  error `2.27e-5`; 512 steps `0.0890 s`, error `7.62e-6`; 2,048 steps `0.3503 s`, error
  `2.67e-7`; 8,192 steps `1.4057 s`, error `2.05e-7`.
- At 8,192 steps the worst per-candidate relative error is `0.94%`; it is on a very small exact
  loss (`2.08e-8`). At 128 steps the worst relative error is `22.2%`, on a larger loss.
- Including the common and local setup, 8,192-step dense evaluation costs `1.455 s` versus
  `0.1155 s` for exact events (`12.6x` in this Python 1D surrogate). At 128 steps, dense evaluation
  is cheaper but substantially less accurate.

Reproduce with:

```powershell
python tools/mmgeo/probe_shared_envelope_dense_redraw.py --seed-candidate 44000 --candidate-limit 12 --angle 2.3 --steps 128 512 2048 8192
```

This establishes a quality/work tradeoff against sampled local depth evaluation for one scanline;
it is still not a production rasterizer or GPU local-redraw comparison. The analytic event
calculation is a plausible component, not a complete algorithm or SIGGRAPH contribution. Prior
art for event visibility, path-aware LOD, and image-driven simplification remains a hard novelty
boundary.

### Small 2D tile screen

I extended the comparison to an 8-by-8 output tile, 2-by-2 regular subpixel taps, and the same 12
Monkey candidates at angle 2.3. This produced 256 pixel sample paths and 4,030,464 common-mesh
triangle-line scan visits during one-time shared setup. Nine candidates had nonzero tile loss.
Source events are cached across candidate collapses; on the first candidate, the cached solver
matched the original exact overlay to zero difference.

- Common setup took `4.182 s`, shared source-event preparation `0.0160 s`, and candidate-local line
  setup for all 12 candidates `0.0675 s`.
- Cached exact event integration for all candidates took `5.405 s`; total including the shared and
  local setup was `9.670 s`.
- Dense local depth redraw for all candidates took `0.541 s` at 128 path samples (summed absolute
  energy error `3.79e-4`, worst relative error `36.1%`), `2.078 s` at 512 (`2.57e-5`, `5.81%`),
  and `8.274 s` at 2,048 (`1.12e-5`, `1.36%`). The 2,048-step summed absolute error is `0.96%`
  of the total exact energy across candidates.
- Including common and local setup, 512-step dense redraw totals `6.328 s` and is faster than exact
  events but has visible integration error. At 2,048 steps it totals `12.523 s`; exact events are
  `1.29x` faster. The outcome is a quality/work tradeoff, not an unconditional speedup.

Reproduce with:

```powershell
python tools/mmgeo/probe_shared_envelope_2d_tile.py --seed-candidate 44000 --candidate-limit 12 --angle 2.3 --grid 8 --subpixels 2 --steps 128 512 2048
```

This is still a CPU scanline-envelope surrogate: no GPU rasterizer, color/material channels,
perspective, or actual ManyMesh simplification loop was measured. The tile covers only a small
region, and timing is one run. It improves on the 1D evidence by showing that exact event updates
can trade more work for lower path-integration error in a 2D filtered tile, but the margin is small
and specialized. The next gate is a matched local-redraw run in an existing rasterizer; if exact
events do not improve the total quality/work frontier there, close this branch. No SIGGRAPH-level
contribution is established.

### Pixel-aligned existing-rasterizer comparison and scanline reuse

To remove the surrogate gap, I aligned the event rays to the existing CPU rasterizer's actual
pixel centers and 2×2 subpixel samples. The dense baseline uses
`depth_candidate_pilot.raster`: it renders the common scene once per horizontal-pan sample, then
redraws only each candidate's shared local face patch against that common depth buffer. The event
method uses the same projected pixels, depth values, 2×2 box filter, tile, and pan path.

The initial implementation rebuilt triangle/path lines independently at every x sample. Since all
pixels in a row share the same y coordinate, I added a scanline coefficient cache: intersect each
triangle and solve its affine depth plane once per distinct y, then instantiate only the x-dependent
interval and intercept per pixel. On the 32×8 tile with 2×2 samples, this cut full-mesh triangle
visits from 16,121,856 to 251,904 (64× fewer); cached and legacy line coefficients differed by at
most `4.44e-16`, with no face-set mismatch. The source-event cache also matched the legacy exact
overlay on the audited candidate to zero difference.

I then replaced linear common-envelope segment lookup during every event interval with binary
search. For Monkey seed 30000 at 64 raster samples, candidate line setup plus exact event solving
dropped from `3.60 s` to `1.69 s`; source/common preparation was `1.24 s`. The cached solver still
matched the legacy exact overlay within `3.8e-18` total energy difference.

Results at a 64×64 viewport, scale 2, 12 Monkey candidates:

- Seed 44000, angle 2.3: exact event setup plus all candidate solves took `4.48 s`. A 512-sample
  local-raster path took `36.77 s`, with summed absolute loss error `0.000458` (`0.74%` of the
  total exact loss; worst per-candidate relative error `0.74%`). Only 2/12 candidates had nonzero
  loss in this tile. Even the 64-sample path took `4.60 s`, while exact event scores preserved the
  candidate ordering.
- Seed 30000, angle 2.3: exact took `2.93 s`. The 512-sample local-raster path took `30.26 s`,
  with summed absolute error `1.67e-5` (`3.42%` of exact total; worst per-candidate relative error
  `10.36%`). Here 8/12 candidates had nonzero loss. At 256 samples raster took `14.97 s` but had
  `12.4%` aggregate error and `23.5%` worst relative error; at 64 samples its aggregate error was
  about `39.9%`. The 64-sample ordering reversed 4 of the 56 non-tied candidate pairs (top-4
  overlap was 2/4); 256- and 512-sample rankings matched the exact ordering. Exact events therefore
  recovered the sampled path ranking at lower cost than both raster settings while returning the
  exact score.
- Other screens were mostly null: seed 15000 at angle 2.3 and seed 44000 at angles 1.1 and 4.6
  had zero or numerical-noise loss for all 12 candidates.

The matching and timing are stronger evidence than the synthetic redraw surrogate: exact path
integration beat a high-sample existing CPU raster path on two nonzero neighborhood/angle cases,
and scanline caching made event setup practical. This is still one mesh, low resolution, one-
dimensional camera translation, two output tiles, and single-run Python timing. It has no GPU
comparison, perspective, material error, or end-to-end simplification evaluation; several tested
configurations were null. This does not establish a general speedup or novelty. Raw results are
ignored under `out/shared-envelope-raster-tile*.json`; each result binds capture and script hashes.

Reproduce the two nonzero screens with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --seed-candidate 44000 --candidate-limit 12 --angle 2.3 --size 64 --scale 2 --tile-width 32 --tile-height 8 --steps 512
python tools/mmgeo/probe_shared_envelope_raster_tile.py --seed-candidate 30000 --candidate-limit 12 --angle 2.3 --size 64 --scale 2 --tile-width 32 --tile-height 8 --steps 512 --out out/shared-envelope-raster-tile-seed30000-512.json
```

Next gate: repeat across additional assets and paths, then compare against a real-time GPU local
redraw if the low-resolution CPU advantage persists. If it loses at matched image error or the
benefit remains restricted to rare candidate neighborhoods, close the branch. SIGGRAPH readiness
is not claimed.

### Cross-asset screen

I added `--unit-index` so the same harness can process multi-unit captures and screened Torus and
Pirate with the identical 64×64 viewport, 2× scale, 32×8 tile, 12-candidate batch, and 64 path
samples. These prevent reading the Monkey cases as a general result:

- Torus unit 0, seed 2500: all 12 candidates had nonzero loss. Exact took `1.82 s`; local raster
  took `1.16 s` and already matched aggregate exact energy within `0.0036%` (worst candidate
  relative error `0.158%`); both methods ranked all candidate pairs identically, so dense redraw is
  the better tradeoff here.
- Pirate unit 5, seed 3000: all 12 candidates had nonzero loss. Exact took `0.96 s`; local raster
  took `2.39 s`, with aggregate error `0.10%` and worst candidate error `0.235%`; candidate order
  was identical. Exact evaluation was faster but the raster scores were already close.
- The 64-frame Monkey screens remain mixed: on seed 44000 the nonzero errors were too localized
  for broad evidence; seed 30000 still had about `39.9%` aggregate sampling error.

Reproduce the cross-asset screens with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/filter-real-candidates/torus.json --unit-index 0 --seed-candidate 2500 --candidate-limit 12 --angle 2.3 --size 64 --scale 2 --tile-width 32 --tile-height 8 --steps 64 --out out/shared-envelope-raster-torus-seed2500.json
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/filter-real-candidates/pirate.json --unit-index 5 --seed-candidate 3000 --candidate-limit 12 --angle 2.3 --size 64 --scale 2 --tile-width 32 --tile-height 8 --steps 64 --out out/shared-envelope-raster-pirate-unit5-seed3000.json
```

The exact evaluator can improve candidate ordering when coarse temporal sampling misses visibility
events, as in Monkey seed 30000. It does not dominate across assets: raster is faster and already
accurate on Torus, while exact events are faster on Pirate but do not change the ordering. Current
evidence supports a useful exact candidate-scoring kernel, not yet a universally better
simplifier. A next algorithmic candidate would need to prove that this ranking gain survives larger
candidate pools, held-out assets, and matched full-resolution image loss. The combination also
needs a focused novelty search before it can be claimed; no SIGGRAPH-level contribution is
established.

### Arbitrary image-plane pan and conservative ray bins (2026-11-19)

I extended the event solver from horizontal-only camera translation to any fixed-direction
orthographic translation in the image plane. For each projected triangle, the generalized solver
caches its three affine barycentric functions and affine depth plane. A pixel sample moving along
the pan direction clips those barycentric functions against zero to obtain the exact path interval;
depth along the interval is linear, so the existing upper-envelope and filtered squared-error
integration still apply. Camera orientation stays fixed; perspective and camera rotation are not
implemented.

The first generalized version scanned every source triangle for every subpixel path ray. A
conservative screen-space uniform grid now bins each triangle by its projected bounding box and
queries cells intersecting the swept ray-segment AABB before exact barycentric clipping. On the
9,428-triangle Material Sphere, 12 candidates, 128 output pixels, scale 1, pan direction 90 degrees,
and path half-length 1 pixel:

- Unbinned source setup took `2.471 s` and tested `1,206,784` triangle-ray records.
- Binned source setup took `0.325 s` and tested `36,544` records (about 33x fewer); candidate
  scoring took `0.056 s`.
- All 12 exact candidate energies matched the unbinned solver exactly in the saved double values.
- Total exact setup and scoring fell from `2.536 s` to `0.380 s` (about 6.7x).

At 45 degrees on the same asset, binned exact setup plus 12 candidate scores took `0.408 s`; the
64- and 256-sample raster paths took `0.873 s` and `3.463 s`. Their candidate-pair ordering matched
exact on all 61 non-tied pairs at 256 samples and 60/61 at 64; the 64-sample aggregate energy error
was `25.9%`, falling to `4.1%` at 256. At 90 degrees, exact ranking matched all 43 non-tied pairs
at both raster settings, while aggregate raster energy errors were `15.4%` and `6.4%`.

Cross-mesh 45-degree screens show both the promise and the remaining weakness:

- Cube (48 triangles): exact took `0.141 s`; 64/256 raster took `0.417/1.620 s`, both with identical
  ordering across 57 non-tied pairs and below `0.17%` aggregate energy error.
- Camera unit 1 (426 triangles): exact took `0.407 s`; 64/256 raster took `0.569/2.259 s`, again
  with identical ordering across 48 pairs.
- Rounded Cube (1,200 triangles): exact took `0.770 s`. Raster took `0.581 s` at 64 samples with
  `73.3%` pair accuracy and `40.0%` aggregate error; 256 samples took `2.327 s` with `86.7%` pair
  accuracy and `27.2%` aggregate error. At 1,024 samples, raster took `9.285 s`, reached `93.3%`
  pair accuracy, and still had `14.0%` aggregate energy error. Exact top-1 had `3.35%` normalized
  regret for the raster's selected candidate; exact top-4 found an exact minimizer.

As an independent formula check, the generalized, binned solver on the same horizontal Cube path
matched the original scanline solver within `1.15e-13` per candidate for all 12 candidates. This
checks the general ray clipping against the legacy horizontal implementation; the diagonal results
also agree with dense raster integration as sample count increases.

Reproduce the high-detail binned direction screens and rank audit with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/material_sphere.json --seed-candidate 16518 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --pan-angle 45 --path-radius 1 --out out/pathloss-captures/material-sphere-seed16518-pan45-binned.json
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/material_sphere.json --seed-candidate 16518 --candidate-limit 12 --angle 2.3 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --pan-angle 90 --path-radius 1 --out out/pathloss-captures/material-sphere-seed16518-pan90-binned.json
python -I tools/mmgeo/audit_pan_path_raster_ranking.py out/pathloss-captures/material-sphere-seed16518-pan45-binned.json out/pathloss-captures/material-sphere-seed16518-pan90-binned.json
```

This broadens the exact kernel beyond a horizontal path and substantially reduces its generic-ray
setup cost. It remains a Python prototype on tiny, localized tiles; the spatial grid is a standard
acceleration structure, and continuous segment visibility is established prior art. The candidate
research distinction remains exact **filtered source-versus-legal-collapse** loss with shared
occluders along a path. It still needs full-frame RGB/material validation, larger candidate pools,
perspective or camera-rotation paths, sequential mesh simplification, and a focused novelty search.
No SIGGRAPH-level claim is established.
