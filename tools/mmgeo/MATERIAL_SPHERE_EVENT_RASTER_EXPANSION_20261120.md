# Material Sphere path-event batch expansion (2026-11-20)

## Question

Does the exact shared-envelope path-event evaluator remain useful on a larger, nonzero legal
collapse pool than the earlier 12-candidate screen? This is a falsification step for the exact
filtered-loss direction, not a novelty claim.

## Frozen setup

- Existing capture: `out/pathloss-captures/material_sphere.json`.
- Candidate seed: 16518; requested limit 48; the capture yielded 38 legal candidates.
- Camera angle 2.3 radians, orthographic image-plane pan 45 degrees.
- Image size 64, scale 1, tile 16x8 (128 pixels).
- Dense reference path samples: 64 and 256.
- No mesh build or renderer run.

## Results

Thirty-four of the 38 candidates had exact tile loss above 1e-12. Shared event setup took 0.5625 s
and exact candidate setup/integration took 1.0567 s, for 1.6192 s total. Pixel-aligned dense raster
cost 3.3310 s at 64 path samples and 11.8343 s at 256 samples.

The summed absolute energy error of the dense raster relative to exact scores was 3.7070 at 64
samples (33.5% of summed exact energy) and 1.4584 at 256 samples (13.2%). Maximum candidate
relative error was 100.0% and 55.7%, respectively. Exact candidate 16533 was the minimum at
1.1393e-14. It ranked third in both raster orderings; each raster's top-ranked candidate had exact
loss 2.4431e-14, effectively tied for this decision.

Thus exact events beat dense integration cost on this tile, while the tested raster rankings
already select an effectively tied choice. This is a small, single-pool result. It establishes
neither a better simplified mesh nor production speed, broad generalization, or novelty. The
current learner also does not improve unseen-path shortlist results, so no learned component is
justified by this screen.

## Reproduction

## Cross-mesh controls

I reused the frozen Torus and Pirate captures with the same image size, tile size, pan direction,
candidate limit, and raster budgets. These are separate candidate pools and no new mesh builds.

| Mesh / unit / seed | Legal candidates | Nonzero exact losses | Event total | Dense 64 | Dense 256 | Winner agreement |
|---|---:|---:|---:|---:|---:|---|
| Material Sphere / 0 / 16518 | 38 | 34 | 1.619 s | 3.331 s | 11.834 s | exact winner ranks 3rd in both raster lists; raster winner is effectively tied |
| Torus / 0 / 2500 | 38 | 38 | 2.284 s | 2.214 s | 9.689 s | both raster lists select the exact winner |
| Pirate / 5 / 3000 | 42 | 42 | 1.404 s | 2.867 s | 11.564 s | both raster lists select the exact winner |

The 64-sample Torus raster's summed absolute error was 0.099% of total exact energy and its
maximum relative error was 0.73%; the exact method was about 3% slower there. Pirate's 64-sample
errors were 0.052% of total exact energy and 0.41% maximum relative, while its exact method was
about 2.0x faster. At 256 samples, both meshes paid substantially more for a score that did not
change the selected collapse. These three local pools support a narrow observation that exact
events can sometimes evaluate the continuous-path objective faster than dense sampling. They do
not show a better collapse sequence, a quality gain at fixed face count, or a robust speedup over
the cheaper 64-sample raster baseline. This is not a SIGGRAPH contribution.

Reproduce the additional controls with:

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/filter-real-candidates/torus.json --seed-candidate 2500 --candidate-limit 48 --angle 2.3 --pan-angle 45 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --out out/pathloss-captures/torus-2500-pan45-tile16x8-n48.json
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/filter-real-candidates/pirate.json --unit-index 5 --seed-candidate 3000 --candidate-limit 48 --angle 2.3 --pan-angle 45 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --out out/pathloss-captures/pirate-unit5-3000-pan45-tile16x8-n48.json
```

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/material_sphere.json --seed-candidate 16518 --candidate-limit 48 --angle 2.3 --pan-angle 45 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --out out/pathloss-captures/material-sphere-16518-pan45-tile16x8-n48.json
```

The probe result is ignored under `out/pathloss-captures/`. The post-run system memory counter
reported about 213 MiB available. No further process-heavy work was started.
