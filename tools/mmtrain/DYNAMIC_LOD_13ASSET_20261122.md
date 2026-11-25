# Dynamic LOD: 13-Asset Held-Out Motion Screen

Updated 2026-11-22. This is a controlled desktop research screen, not a SIGGRAPH result.

## Protocol

Thirteen Khronos glTF Sample Assets use the existing component/source mesh pairs. The
ranker is calibrated only on the 24-frame training turntable (path 0); four other
48-frame paths are held out (paths 1 through 4, split across two benchmark runs). Each frame
shows sixteen isolated instances, with four source meshes and twelve component meshes.
Both policies therefore use the same per-asset triangle count and two indexed-instanced
draws. Rendering is 1920x1080 on Intel Iris Xe / D3D12. GPU timing uses three repetitions.

The primary paired comparison is the calibration-selected ranking with fixed hysteresis
against area ranking with the same hysteresis. Each view is rendered as an 8-bit single-
channel flat-shaded image. PSNR is exact over all 192 frames per asset. Canonical
Gaussian-window SSIM and binary silhouette IoU use four fixed, evenly spaced frames per
path. Confidence intervals bootstrap assets, not correlated frames. These measurements
do not cover authored materials, occlusion, display motion, FLIP/LPIPS, user preference,
power, mobile GPUs, or a complete application frame. The thirteen assets and their
source/component pairs are reused development data; the component meshes were selected
in earlier fitting-view experiments. These are path-held-out results, not asset-held-out
confirmation. Per-asset profile fitting and calibration time are not included in runtime.

## Results

Positive values favor the calibration-selected policy. A ranker that selects area is
identical to the control for that asset.

| Asset | Ranker | Triangles/frame | PSNR change (dB) | SSIM change | Silhouette IoU change | Pixel SSE reduction |
|---|---|---:|---:|---:|---:|---:|
| AntiqueCamera | direction | 128,344 | +0.425 | +0.000088 | -0.000223 | +9.35% |
| Avocado | direction | 4,348 | +0.649 | +0.000379 | -0.000748 | +14.11% |
| BarramundiFish | direction | 24,720 | +0.363 | +0.000188 | +0.000144 | +8.13% |
| CesiumMilkTruck | direction | 23,832 | +0.777 | +0.001145 | +0.000507 | +16.68% |
| FlightHelmet | direction | 606,204 | +0.117 | -0.000093 | -0.000017 | +2.72% |
| GlassVaseFlowers | scale-direction | 89,816 | +0.084 | +0.000170 | +0.000928 | +1.91% |
| IridescenceLamp | scale-direction | 120,728 | +0.114 | -0.000013 | -0.000013 | +2.60% |
| Lantern | scale-direction | 41,376 | +0.543 | -0.000031 | +0.000149 | +11.95% |
| SheenChair | scale-direction | 255,588 | +0.061 | -0.000041 | +0.000060 | +1.46% |
| SheenCloth | scale-direction | 737,268 | -0.000 | -0.000003 | +0.000005 | -0.02% |
| StainedGlassLamp | direction | 224,840 | +0.166 | -0.000337 | -0.000626 | +3.74% |
| ToyCar | area | 697,188 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| WaterBottle | scale-direction | 28,852 | +0.052 | +0.000007 | -0.000037 | +1.16% |

Asset-bootstrap mean (95% percentile CI): PSNR **0.258 dB [0.128, 0.403]**; SSIM **0.000112 [-0.000041, 0.000319]**; silhouette IoU **0.000010 [-0.000211, 0.000236]**; pixel SSE reduction **5.677% [2.849, 8.767]**.

The selected ranker improves PSNR on 11/13 assets, SSIM on 6/13, and silhouette IoU on 6/13.
The median across assets of each asset's p95 GPU pass time is 0.560 ms for area hysteresis and 0.272 ms for the calibration-selected policy. Median asset p95 CPU selection/upload/submission is 0.664 ms for area and 0.649 ms for the selected policy; selector-only p95 is 0.072 ms and 0.110 ms. GPU pass timestamps do not include presentation or frame pacing.

## Interpretation and Limits

This supports a limited feasibility statement: a frozen per-asset appearance profile can
rank four of sixteen resident instances better than projected area for these synthetic
motion paths. It does not establish a new LOD allocation method. Cost-benefit allocation
across multiple LOD objects and hysteresis for temporal stability are established
directions; see [Funkhouser and Sequin (1993)](https://gfx.cs.princeton.edu/gfx/pubs/Funkhouser_1993_ADA/index.php). Calibration is per asset, the workload is non-overlapping
and stylized, and the policies share the same simple resident-mesh setup. A SIGGRAPH
claim requires a sharper novelty boundary, stronger real-scene baselines, richer image
metrics/materials, and a fresh licensed confirmation set. No mobile result is measured.

Raw benchmark receipts are `out/geometry-refinement-pilot/dynamic-13asset-1080-{initial,alternate}-quality-20261122.json`.
