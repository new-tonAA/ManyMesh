# High-resolution camera-path loss audit on Pirate (2026-11-20)

## Question

Does continuous camera-path ranking improve the resulting mesh over QEM when the fitting and
held-out image evaluation are both raised to a denser raster setting? This is a held-out
cross-view quality screen, not a performance claim for a production implementation.

## Reproduction

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmgeo/probe_global_path_qem.py `
  out/filter-real-candidates/pirate.json `
  --unit-index 5 --remove-fraction .20 `
  --size 96 --scale 2 --radius 1.5 `
  --quality-size 96 --quality-scale 3 --quality-steps 4 `
  --compare-placements --integrate-along-pan --strip-width 4 `
  --out out/pathloss-captures/pirate-96px-exactpath.json
```

Input capture SHA-256: `e63ec2f6749cceb168cc2135467e643715e10afc838c3e1b9e3a91fa7681d28d`.
Driver SHA-256: `4177be64fab00d2f40d76e1a08268db07a440ff0fb014c119801fa064e82c525`.
Output SHA-256: `8fb3877d32831a05e4043eca9f29e3b5cad10d63810866b9ba50483f52233980`.
The JSON output is ignored under `out/`.

## Result

All methods reduce the same unit from 3,032 to 2,426 faces over 303 edits. Held-out quality is
the mean over six orbit views at 96 by 96 pixels, 3x sampling, and four camera-path samples.

| Method | Coverage MSE | Depth MSE | Flat-normal squared distance | CPU seconds |
|---|---:|---:|---:|---:|
| QEM | 1.0605103e-6 | 3.4171573e-7 | 5.2002726e-6 | 1.219 |
| Path-ranked edge, QEM placement | 1.0605103e-6 | 3.4171571e-7 | 5.2817643e-6 | 19.719 |
| Path-ranked edge and placement | 1.2279592e-6 | 4.4471445e-7 | 7.6689371e-6 | 60.078 |

The path-ranked edge sequence ties QEM on coverage and differs in mean depth by only `-5.3e-6%`;
its held-out flat-normal error is `+1.57%` worse. It costs about `16.2x` the QEM CPU time in this
single Python run. Reranking all legal placements is substantially worse on all three quality
metrics and costs about `49.3x` QEM. Per-view results show only 3/6 wins for path edge selection on
depth and normal, with no coverage wins.

This is a negative result for path-based edge and placement ranking on this asset at this raster
setting. It does not close the general camera-path algorithm: it is one mesh, one simplification
budget, and six finite held-out views. It does close any claim that this configuration improves
Pirate over QEM. Future work should require a clear quality gain or cost reduction before extending
this branch. A per-process peak was not preserved for this run. Available system RAM after it was
about 3.25 GiB.
