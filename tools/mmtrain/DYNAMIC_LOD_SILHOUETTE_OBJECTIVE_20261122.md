# Dynamic LOD: 13-Asset Leave-One-Asset-Out Screen

Updated 2026-11-22. This is a controlled desktop research screen, not a SIGGRAPH result.

## Protocol

Thirteen Khronos glTF Sample Assets use the existing component/source mesh pairs.
For each test asset, the shared direction/scale profile is built from the other twelve assets' 24-frame training turntables. Cross-validation selects the profile family using leave-one-asset-out folds within those twelve assets; the training objective is binary silhouette XOR pixel count. The outer test asset contributes no profile or ranker-selection data. 
The 4 held-out paths (1, 2, 3, 4) each contain 48 frames and are split across two benchmark runs. Each frame
shows sixteen isolated instances, with four source meshes and twelve component meshes.
Both policies therefore use the same per-asset triangle count and two indexed-instanced
draws. Rendering is 640x360 on Intel Iris Xe / D3D12. GPU timing uses 1 repetition.

The primary paired comparison is the calibration-selected ranking with fixed hysteresis
against area ranking with the same hysteresis. Each view is rendered as an 8-bit single-
channel flat-shaded image. Canonical
Gaussian-window SSIM and binary silhouette IoU use four fixed, evenly spaced frames per
path. Exact PSNR covers 192 frames per asset. Confidence intervals bootstrap assets, not correlated frames. These measurements
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
| AntiqueCamera | area | 128,344 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| Avocado | area | 4,348 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| BarramundiFish | area | 24,720 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| CesiumMilkTruck | area | 23,832 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| FlightHelmet | area | 606,204 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| GlassVaseFlowers | area | 89,816 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| IridescenceLamp | area | 120,728 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| Lantern | area | 41,376 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| SheenChair | area | 255,588 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| SheenCloth | area | 737,268 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| StainedGlassLamp | area | 224,840 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| ToyCar | area | 697,188 | +0.000 | +0.000000 | +0.000000 | +0.00% |
| WaterBottle | area | 28,852 | +0.000 | +0.000000 | +0.000000 | +0.00% |

Asset-bootstrap mean (95% percentile CI): PSNR **0.000 dB [0.000, 0.000]**; SSIM **0.000000 [0.000000, 0.000000]**; silhouette IoU **0.000000 [0.000000, 0.000000]**; pixel SSE reduction **0.000% [0.000, 0.000]**.

The selected ranker improves PSNR on 0/13 assets, SSIM on 0/13, and silhouette IoU on 0/13.
The median across assets of each asset's p95 GPU pass time is 0.298 ms for area hysteresis and 0.271 ms for the calibration-selected policy. Median asset p95 CPU selection/upload/submission is 0.681 ms for area and 0.607 ms for the selected policy; selector-only p95 is 0.074 ms and 0.071 ms. GPU pass timestamps do not include presentation or frame pacing. Each timing has only 1 repetition; the small differences are measurement noise, not a performance result.

## Interpretation and Limits

Silhouette-XOR profile selection chose the area ranker on all thirteen outer test assets. The evaluated policy therefore exactly matches the control; this screen provides no evidence of a quality gain from the silhouette objective.
The asset set and component pairs are reused development data, so the folds are not fresh confirmation.
This does not establish a new LOD allocation method. Cost-benefit allocation
across multiple LOD objects and hysteresis for temporal stability are established
directions; see [Funkhouser and Sequin (1993)](https://gfx.cs.princeton.edu/gfx/pubs/Funkhouser_1993_ADA/index.php). The workload is non-overlapping
and stylized, and the policies share the same simple resident-mesh setup. A SIGGRAPH
claim requires a sharper novelty boundary, stronger real-scene baselines, richer image
metrics/materials, and a fresh licensed confirmation set. No mobile result is measured.

Raw benchmark receipts:
- `out/geometry-refinement-pilot/dynamic-13asset-silhouette-profile-initial-640-20261122.json`
- `out/geometry-refinement-pilot/dynamic-13asset-silhouette-profile-alternate-640-20261122.json`
