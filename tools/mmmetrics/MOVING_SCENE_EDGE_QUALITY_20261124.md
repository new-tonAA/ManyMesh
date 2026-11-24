# Contour error and LPIPS on moving-camera scenes

In three reused synthetic scenes with 1.12–1.24 million source faces each,
binary coverage mismatches accounted for 36–49% of the group-area LOD's
squared image error against a supersampled source. The mismatches plus a
two-pixel contour band accounted for 63–86%. Full-source 4× MSAA had a
similar distribution of error, so this comparison includes raster-sampling
error at contours. The historical 68.3% Monkey number used one view and a
full-detail DAG cut as the reference. [Historical experiment](../../MANYMESH_HISTORY.md#fixed-camera-4525-error-decomposition)

## Protocol

Replay the three 48-frame, 720p sequences at 30 fps from the
[moving-camera screen](../mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md).
The desktop renderer used Iris Xe, D3D12, flat grayscale shading, and
hardware 4× MSAA. Compare to the full source at 2× resolution with 4× MSAA
and a linear box downsample. Compare LOD candidates to the full-source
720p 4× MSAA captures as a separate test at the same sampling rate.
The replay checked MKV hashes, reference frame hashes, and original
per-frame PSNR and silhouette XOR on every decoded frame.

For each comparison, partition all pixels into three disjoint regions.

1. **Silhouette XOR** contains pixels where exactly one image has nonzero
   coverage.
2. **Same-coverage contour band** contains additional pixels within the
   5×5 morphological gradient of either coverage mask. This covers two
   pixels on each side in Chebyshev distance.
3. **Remaining pixels** contains all other pixels.

Pool squared sRGB differences over all 48 frames, then divide each
region's squared error by the total. The image-space mask uses the positive
coverage signal from flat shading against black. Its error share describes
spatial concentration. Occlusion between foreground surfaces and viewer
preference require other measurements.

## Contour error against the supersampled full source

| Scene | Source faces | Group LOD XOR pixels | Group LOD XOR error | Group LOD XOR plus band error | Full-source 720p XOR plus band error |
|---|---:|---:|---:|---:|---:|
| display-wall | 1,182,070 | 0.196% | 49.05% | 83.15% | 81.66% |
| layered-aisles | 1,120,854 | 0.076% | 36.45% | 63.11% | 63.45% |
| mixed-scale | 1,237,896 | 0.222% | 49.16% | 85.87% | 86.22% |

## Contour error at matched sampling

The 720p full-source 4× MSAA reference isolates differences between meshes
under the same raster sampling. Binary coverage mismatch is sparse in this
comparison. The combined contour region contains a majority of the squared
error in all three scenes.

| Scene | Group LOD XOR pixels | Group LOD XOR error | XOR plus band pixels | XOR plus band error |
|---|---:|---:|---:|---:|
| display-wall | 0.0265% | 57.85% | 5.582% | 86.33% |
| layered-aisles | 0.0057% | 34.61% | 2.449% | 57.09% |
| mixed-scale | 0.0167% | 47.24% | 6.095% | 79.06% |

Only display-wall exceeds 50% on XOR alone under group-area LOD. The
boundary-band result supports measuring a neighborhood around contours as
well as binary coverage differences. Both measures use reused scene paths.

## LPIPS on the fixed frame sample

LPIPS uses the calibrated SqueezeNet v0.1 model on every fourth frame
beginning at frame zero. That gives 12 full-resolution frame scores per
scene and policy. It measures frame quality. The report from the original
screen provides CGVQM-5 and adjacent-frame error for the same sequences.

| Scene | Full source | Group area | Instance area | Face-budget-matched instance oracle |
|---|---:|---:|---:|---:|
| display-wall | 0.0075623 | 0.0078706 | 0.0078770 | 0.0078706 |
| layered-aisles | 0.0053550 | 0.0054362 | 0.0054150 | 0.0054362 |
| mixed-scale | 0.0071937 | 0.0073715 | 0.0073197 | 0.0073477 |

Lower is better. Relative to group area, instance area changes mean LPIPS
by −0.0000222 across the three scenes. Its 95% scene-bootstrap percentile
interval is [−0.0000518, +0.0000064]. It uses more faces and more GPU time
in the original timings. The face-budget-matched oracle changes LPIPS by
−0.0000079 [−0.0000237, 0], with identical results in two scenes. Its timing
also exceeds group area. Treat both intervals as descriptive for three
reused scenes. The experiment supplies no equal-frame-time win.

## Reproduction

[Analysis script](analyze_moving_scene_edges.py) ·
[Per-frame receipt](moving_scene_edge_quality_20261124.json) ·
[LPIPS](https://github.com/richzhang/PerceptualSimilarity)

Use the original lossless FFV1 clips, OpenCV 4.10.0, NumPy 2.3.4,
PyTorch 2.7.1 and torchvision 0.22.1, LPIPS 0.1.4, LDR-FLIP 1.7, and
scikit-image 0.25.2. Put the official
[SqueezeNet checkpoint](https://download.pytorch.org/models/squeezenet1_1-b8a52dc0.pth)
in the `checkpoints` subdirectory of the specified Torch Hub path. The
script verifies the checkpoint hash and records the LPIPS calibration
hash. All scoring runs on CPU.

```powershell
python tools/mmmetrics/analyze_moving_scene_edges.py `
  --benchmark tools/mmtrain/mixed_scene_dynamic_instance_lod_validated_720p_20261123.json `
  --captures out/mixed-scene/dynamic-sequences-validated-20261123 `
  --torch-hub out/moving-scene-metrics-20261124/torch-hub `
  --out out/moving-scene-metrics-20261124/report.json
```

The metric and timing receipts are published. The original meshes, scene
geometry, and videos remain local, so the replay requires those inputs.
The two replays produced identical per-frame LPIPS and supersampled-reference
error counts.
