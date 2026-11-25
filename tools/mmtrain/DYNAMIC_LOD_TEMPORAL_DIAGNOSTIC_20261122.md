# Dynamic LOD temporal image-difference screen

Updated 2026-11-22. This is a temporal signal diagnostic, **not a perceptual video-quality result**.

## Protocol

- 13 Khronos glTF assets; 16 tiled instances per frame; 640x360;
  48 frames on each of camera paths 1, 2, 3, 4.
- Compare the leave-one-asset-out calibrated ranker plus hysteresis against area ranking plus hysteresis
  on two separately captured path pairs. The per-asset policy is fixed before scoring held-out paths;
  both methods use the same face budget.
- For each sequence, compose the actual candidate image from captured low-detail and full-detail instance renders.
  Measure adjacent-frame image derivatives for candidate and full-detail reference, then subtract those derivatives.
- Foreground support is the union of candidate/reference non-black pixels over adjacent frames. Report mean and p95
  absolute derivative error, normalized by 255. Lower is better. Average paths within asset, then bootstrap assets.
- The custom finite-difference diagnostic is sensitive to camera motion and silhouette displacement. It is not motion-compensated,
  perceptually calibrated, or validated against human ratings. Do not call it a standardized flicker score.
- The motion-reference manifest SHA-256 is `328f1efeecfb5b6e0221a2f0665aed1a7e180f50b000f3da5f44a609563ea825`; source and component mesh SHA-256 values are in the raw receipts.

## Paired results

Positive deltas mean the calibrated policy has greater temporal error than area ranking. The CI bootstraps 13 assets.

| Metric | Area mean | Calibrated mean | Paired delta [95% asset-bootstrap CI] | Assets improved / regressed |
|---|---:|---:|---:|---:|
| Foreground temporal-difference MAE | 0.024495 | 0.023554 | -0.000942 [-0.001434, -0.000488] | 12 / 1 |
| Foreground temporal-difference RMSE | 0.079034 | 0.077825 | -0.001209 [-0.002099, -0.000368] | 9 / 4 |
| 95th percentile per-pair foreground MAE | 0.028045 | 0.027165 | -0.000880 [-0.001388, -0.000369] | 10 / 3 |
| Mean foreground MAE on LOD-switch pairs | 0.025727 | 0.024931 | -0.000796 [-0.001258, -0.000367] | 12 / 1 |
| Mean foreground MAE without LOD switches | 0.023948 | 0.023056 | -0.000891 [-0.001374, -0.000439] | 12 / 1 |
| Transitions with at least one instance LOD switch | 14.500000 | 12.423077 | -2.076923 [-2.192308, -1.961538] | 13 / 0 |

## Interpretation and limits

This screen supplements the existing framewise PSNR, SSIM, and silhouette results. It can expose whether the
chosen geometry policy changes temporal image differences on these synthetic isolated-cell paths, but its pixelwise
derivative does not account for optical flow or human temporal sensitivity. The shared-profile policy already lacks
a reliable PSNR gain and reduces silhouette IoU on this reused development corpus; these results do not reopen it as
a contribution candidate or establish temporal stability.

CGVQM, a full-reference computer-graphics video metric with spatial and temporal modeling, remains the required
perceptual follow-up. CGVQM code/weights were not present locally during this screen. No CGVQM score, user preference,
authored-material result, or mobile result is claimed.
See the [temporal quality protocol](../mmmetrics/TEMPORAL_QUALITY_PROTOCOL.md) and [shared-profile screen](DYNAMIC_LOD_LOAO_13ASSET_20261122.md).

Raw receipts:
- `out\geometry-refinement-pilot\dynamic-13asset-temporal-diagnostic-640-20261122.json`
- `out\geometry-refinement-pilot\dynamic-13asset-temporal-diagnostic-alternate-640-20261122.json`
