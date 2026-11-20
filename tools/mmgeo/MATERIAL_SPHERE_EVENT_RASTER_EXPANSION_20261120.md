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

```powershell
python tools/mmgeo/probe_shared_envelope_raster_tile.py --capture out/pathloss-captures/material_sphere.json --seed-candidate 16518 --candidate-limit 48 --angle 2.3 --pan-angle 45 --size 64 --scale 1 --tile-width 16 --tile-height 8 --steps 64 256 --out out/pathloss-captures/material-sphere-16518-pan45-tile16x8-n48.json
```

The probe result is ignored under `out/pathloss-captures/`. The post-run system memory counter
reported about 213 MiB available. No further process-heavy work was started.
