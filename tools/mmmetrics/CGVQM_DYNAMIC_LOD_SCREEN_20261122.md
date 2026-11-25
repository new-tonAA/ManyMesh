# CGVQM-5 dynamic LOD sequence screen

This is a research screen on reused development assets, not an independent confirmation or a SIGGRAPH result.

## Protocol

- 13 Khronos glTF assets; camera paths 1, 2; 640x360; 48 frames per path at 30 fps.
- Both policies use the same per-asset face budget. The cross-validated direction/scale ranker was fit without the held-out asset.
- LOD profile objective: `color-sse`. Quality score: `CGVQM-5`, mean patch pooling, scale 4; CPU inference with 8 threads.
- Upstream model and calibration weights with an OpenCV FFmpeg video adapter; videos are lossless FFV1 grayscale renders. Decoded dimensions, frame rate, frame count, and exact pixels were verified.
- Scores are paired within asset. Path deltas are averaged within each asset before the 95% percentile bootstrap, so the bootstrap unit is 13 assets rather than 26 asset-path pairs.
- Reused development assets and isolated flat-shaded rendering; no authored materials, user ratings, or mobile devices.
- Scoring used IntelLabs CGVQM commit `c4f1222c978e2c853609cf38d240920cfb92d15e`, OpenCV 4.10.0 FFmpeg decoding, PyTorch 2.7.1+cpu, torchvision 0.22.1+cpu, and the upstream calibration and R3D-18 weights. The decoder and model-weight SHA-256 values are recorded per input pair in the tracked receipt.

## Results

Higher CGVQM scores indicate higher predicted quality. Positive deltas favor the selected ranker.

| Asset | Selected ranker | Mean area score | Mean selected score | Mean delta | Path deltas |
|---|---|---:|---:|---:|---|
| AntiqueCamera | scale-direction | 97.7207 | 97.8223 | +0.1016 | 1: +0.0558, 2: +0.1474 |
| Avocado | scale-direction | 97.2435 | 97.3724 | +0.1289 | 1: +0.1599, 2: +0.0979 |
| BarramundiFish | direction | 98.5529 | 98.3151 | -0.2378 | 1: -0.2891, 2: -0.1865 |
| CesiumMilkTruck | direction | 95.3268 | 95.6934 | +0.3666 | 1: +0.3375, 2: +0.3956 |
| FlightHelmet | direction | 96.8489 | 96.7601 | -0.0889 | 1: -0.1063, 2: -0.0715 |
| GlassVaseFlowers | scale-direction | 95.4849 | 95.2616 | -0.2233 | 1: -0.2227, 2: -0.2238 |
| IridescenceLamp | direction | 95.2987 | 95.1446 | -0.1542 | 1: -0.1187, 2: -0.1896 |
| Lantern | direction | 99.3436 | 99.3275 | -0.0161 | 1: +0.0168, 2: -0.0490 |
| SheenChair | direction | 99.0730 | 99.0259 | -0.0472 | 1: -0.0005, 2: -0.0938 |
| SheenCloth | direction | 99.5831 | 99.5900 | +0.0069 | 1: -0.0096, 2: +0.0234 |
| StainedGlassLamp | scale-direction | 94.5386 | 94.2169 | -0.3218 | 1: -0.2906, 2: -0.3530 |
| ToyCar | direction | 97.5750 | 97.4455 | -0.1295 | 1: -0.1603, 2: -0.0987 |
| WaterBottle | direction | 96.9299 | 96.7780 | -0.1519 | 1: -0.2368, 2: -0.0670 |

Mean within-asset delta: **-0.0590** (asset-bootstrap 95% CI [-0.1476, +0.0424]); 4 assets favor the selected ranker and 9 favor area.

## Limits

CGVQM-5 is a published graphics video metric, not a universal or ISO-standard score. OpenCV FFmpeg decoding differs from the paper's PyAV input path, so absolute scores are not a canonical reproduction. Paired comparisons share the same decoder and settings. These reused assets, synthetic renderer, and two paths do not establish general temporal perceptual quality. The profile remains closed unless a distinct novelty claim and repeatable quality-cost gain emerge on fresh licensed assets. No user preference or mobile claim is measured.

The complete compact receipt, including per-asset path scores, all 52 scored input records, video hashes, metric-weight hashes, and both path summaries, is tracked at [`cgvqm_dynamic_lod_screen_20261122.json`](cgvqm_dynamic_lod_screen_20261122.json). Its benchmark input SHA-256 is `2493cd7db1111a63b06492bb8a6e7d19f9dc069e9423db0bbbc02ddf49af5e76`. The original lossless clips and per-score JSON files remain local under `out/geometry-refinement-pilot/`; they are not committed.

Scoring used [`bench_cgvqm_dynamic.py`](bench_cgvqm_dynamic.py) and its upstream adapter [`run_cgvqm.py`](run_cgvqm.py); [`summarize_cgvqm_paths.py`](summarize_cgvqm_paths.py) combines path summaries. Reproduction requires the benchmark JSON, captured lossless clips, IntelLabs checkout at the pinned commit, and the recorded model weights. The canonical video inputs are not in Git, so the tracked hashes document but do not recreate those clips.

References: [CGVQM paper](https://doi.org/10.1111/cgf.70221), [official implementation](https://github.com/IntelLabs/cgvqm).
