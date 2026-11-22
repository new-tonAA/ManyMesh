# Moving-camera per-instance LOD screen

Updated 2026-11-23. **This development screen does not show a frame-time-balanced quality win.** The per-instance area policy improves image and CGVQM-5 scores, but it uses more triangles under the shared ceiling and is slower on GPU in all three scenes. When the selected face count is matched per frame, the offline per-instance oracle gives no image-metric change in two scenes and only a small change in one; its selection and draw costs are too high for this implementation.

## Protocol

Three reused synthetic mixed scenes use a smooth 48-frame camera loop at 1280×720 and 30 fps. The LOD candidates and full-source reference use 4× MSAA; the reference is rendered at 2560×1440 and linearly box-downsampled. Every mode sees the same cached reference frames, and their RGB hash matches. The scene face ceilings are 1,029,902 (`display-wall`), 988,053 (`layered-aisles`), and 1,011,033 (`mixed-scale`). The Iris Xe / D3D12 run times each policy in three repetitions after eight warm-up frames. GPU timestamps, CPU selector time, bucket/update/encode/submit time, and synchronized path wall time are recorded separately.

Four policies are measured:

- `group-area`: greedy projected-area ranking at asset-group granularity.
- `instance-area`: the same projected-area ranking at instance granularity, under the same maximum face cap. It can use more faces when group granularity leaves budget unused.
- `instance-matched`: exact subset selection at instance granularity, constrained each frame to at most the actual group-area face count. This is a quality-cost oracle; its CPU dynamic program and additional draw buckets are part of the timing.
- `source`: full source geometry, used as the quality reference. The reference image is the supersampled full-source render described above.

Image quality is averaged over all frames using PSNR, SSIM, LDR-FLIP and silhouette XOR. CGVQM-5 uses the lossless RGB video captures, OpenCV FFmpeg decoding and the pinned IntelLabs model. Its score is higher-is-better. The paired bootstrap resamples the three scenes, not frames. This is too small and too reused a set to support a generalization claim.

## Results

Each cell reports mean faces / median draws per frame / GPU p50 milliseconds / selector CPU p50 milliseconds / LDR-FLIP / PSNR dB / CGVQM-5.

| Scene | Group area | Instance area | Face-budget-matched instance oracle |
|---|---|---|---|
| display-wall | 901,785 / 7 / 1.093 / 0.320 / 0.006817 / 35.880 / 95.0321 | 1,012,468 / 9 / 1.229 / 0.271 / 0.006769 / 35.892 / 95.0331 | 901,785 / 7 / 2.000 / 1.253 / 0.006817 / 35.880 / 95.0321 |
| layered-aisles | 957,366 / 7 / 1.185 / 0.347 / 0.004322 / 39.049 / 97.7924 | 984,614 / 8 / 1.348 / 0.342 / 0.004259 / 39.088 / 97.8119 | 957,366 / 7 / 5.032 / 6.581 / 0.004322 / 39.049 / 97.7924 |
| mixed-scale | 901,554 / 8 / 1.232 / 0.410 / 0.007286 / 35.324 / 96.3084 | 1,004,009 / 11 / 1.420 / 0.291 / 0.007135 / 35.372 / 96.4608 | 901,105 / 12.8 / 5.127 / 8.677 / 0.007237 / 35.336 / 96.4201 |

Against group-area, `instance-area` uses 2.8–12.3% more faces and increases GPU p50 by 12.4–15.2% in each scene. It improves LDR-FLIP by 0.7–2.1%, PSNR by 0.012–0.048 dB, and CGVQM-5 in all three reused scenes. The mean paired CGVQM-5 difference is **+0.0577** with a three-scene bootstrap interval of **[+0.0010, +0.1524]**.

Under the actual group-area per-frame face ceiling, `instance-matched` uses the same mean face count in two scenes and 0.05% fewer in `mixed-scale`. It is identical on LDR-FLIP, PSNR and SSIM in the first two scenes. In `mixed-scale`, its LDR-FLIP improves from 0.007286 to 0.007237, PSNR from 35.324 to 35.336 dB, and CGVQM-5 from 96.3084 to 96.4201. Across the three scenes its paired CGVQM-5 difference is **+0.0372 [0.0000, +0.1117]**. It requires 1.25–8.68 ms selector p50 and 2.00–5.13 ms GPU p50, so it does not meet the measured runtime budget.

The positive CGVQM-5 values for `instance-area` accompany higher triangle counts and GPU time. The same-face oracle has no CGVQM-5 change in two of three scenes and a gain in one; the bootstrap interval includes zero. These data do not establish an equal-cost or held-out improvement. The area metric itself is established prior art, and these three synthetic scenes are development data.

## Reproduction records

The measurement receipt is [mixed_scene_dynamic_instance_lod_validated_720p_20261123.json](mixed_scene_dynamic_instance_lod_validated_720p_20261123.json). The CGVQM-5 scores and paired scene bootstrap are in [mixed_scene_dynamic_cgvqm_validated_20261123.json](../mmmetrics/mixed_scene_dynamic_cgvqm_validated_20261123.json). Lossless frame videos and prepared geometry are local research outputs and are not checked into this report bundle, so the receipt describes the run but is not a standalone reproduction package.
