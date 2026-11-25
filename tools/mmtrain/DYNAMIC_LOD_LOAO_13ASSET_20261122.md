# Dynamic LOD: 13-Asset Leave-One-Asset-Out Screen

Updated 2026-11-22. This is a controlled desktop research screen, not a SIGGRAPH result.

## Protocol

Thirteen Khronos glTF Sample Assets use the existing component/source mesh pairs.
For each test asset, the shared direction/scale profile is built from the other twelve assets' 24-frame training turntables. Cross-validation selects the profile family using leave-one-asset-out folds within those twelve assets; training errors are normalized to unit mean SSE per asset. The outer test asset contributes no profile or ranker-selection data. Four other
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
in earlier fitting-view experiments. Each outer asset fold excludes that asset from profile fitting and ranker selection, but this reused corpus is not a fresh confirmation set.
Profile fitting and ranker-selection time are not included in runtime.

## Results

Positive values favor the shared, cross-validated policy. A ranker that selects area is
identical to the control for that asset.

| Asset | Ranker | Triangles/frame | PSNR change (dB) | SSIM change | Silhouette IoU change | Pixel SSE reduction |
|---|---|---:|---:|---:|---:|---:|
| AntiqueCamera | scale-direction | 128,344 | +0.332 | +0.000092 | -0.000177 | +7.33% |
| Avocado | scale-direction | 4,348 | +0.387 | +0.000378 | -0.000059 | +8.64% |
| BarramundiFish | direction | 24,720 | -0.053 | -0.000164 | -0.000201 | -1.15% |
| CesiumMilkTruck | direction | 23,832 | +0.354 | +0.000396 | -0.000013 | +7.76% |
| FlightHelmet | scale-direction | 606,204 | +0.110 | -0.000093 | -0.000017 | +2.56% |
| GlassVaseFlowers | scale-direction | 89,816 | -0.026 | -0.000608 | -0.000855 | -0.56% |
| IridescenceLamp | scale-direction | 120,728 | -0.111 | -0.000061 | -0.000021 | -2.62% |
| Lantern | scale-direction | 41,376 | +0.300 | -0.000035 | -0.000162 | +6.72% |
| SheenChair | direction | 255,588 | -0.049 | -0.000072 | +0.000029 | -1.02% |
| SheenCloth | scale-direction | 737,268 | -0.183 | -0.000052 | -0.000137 | -4.32% |
| StainedGlassLamp | scale-direction | 224,840 | +0.161 | -0.000286 | -0.000566 | +3.63% |
| ToyCar | direction | 697,188 | -0.072 | +0.000031 | -0.000394 | -2.12% |
| WaterBottle | direction | 28,852 | -0.066 | +0.000046 | -0.000091 | -1.79% |

Asset-bootstrap mean (95% percentile CI): PSNR **0.083 dB [-0.019, 0.190]**; SSIM **-0.000033 [-0.000171, 0.000098]**; silhouette IoU **-0.000205 [-0.000351, -0.000085]**; pixel SSE reduction **1.774% [-0.549, 4.166]**.

The selected ranker improves PSNR on 6/13 assets, SSIM on 5/13, and silhouette IoU on 1/13.
The median across assets of each asset's p95 GPU pass time is 0.576 ms for area hysteresis and 0.276 ms for the calibration-selected policy. Median asset p95 CPU selection/upload/submission is 0.706 ms for area and 0.690 ms for the selected policy; selector-only p95 is 0.076 ms and 0.152 ms. GPU pass timestamps do not include presentation or frame pacing.

## Interpretation and Limits

This shared profile did not show a reliable quality gain: its PSNR and SSIM intervals include zero, while silhouette IoU declines.
The asset set and component pairs are reused development data, so the folds are not fresh confirmation.
This does not establish a new LOD allocation method. Cost-benefit allocation
across multiple LOD objects and hysteresis for temporal stability are established
directions; see [Funkhouser and Sequin (1993)](https://gfx.cs.princeton.edu/gfx/pubs/Funkhouser_1993_ADA/index.php). The workload is non-overlapping
and stylized, and the policies share the same simple resident-mesh setup. A SIGGRAPH
claim requires a sharper novelty boundary, stronger real-scene baselines, richer image
metrics/materials, and a fresh licensed confirmation set. No mobile result is measured.

Raw benchmark receipts are `out/geometry-refinement-pilot/dynamic-13asset-1080-{initial,alternate}-loao-20261122.json`.
