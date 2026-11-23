# Silhouette Error Attribution at Matched Face Budgets

This diagnostic checks whether the historical single-view Monkey result
(0.11% silhouette-XOR pixels, 68.3% of squared error) generalizes to the
geometry-only Thingi10K screen. The protocol is related, not a reproduction:
it uses 12 orthographic views, flat shading, a 256 x 256 image, and 4x box
sampling. The original measurement used a different camera, resolution, and
rendering path.

## Definition and protocol

A pixel is in the silhouette-XOR set when reference and candidate have
different nonzero-coverage status. The pixel fraction is the size of that set
divided by the image area. The error share is RGB squared error summed inside
those pixels divided by total RGB squared error. This is a raster-space error
attribution, not a perceptual metric. It excludes partially covered pixels when
both meshes cover the pixel, so it is narrower than a multi-pixel contour band.

QEM and meshoptimizer outputs use matched face counts at 50% source-face
retention. The screen covers the eight validation assets and the 16 training
assets separately; no final-test assets were read. Results are averages over
views within each asset. Intervals are 95% asset-bootstrap percentile intervals
from 10,000 paired-resampling iterations. The train/validation corpus has
already informed prior experiments, so this remains development evidence.

## Results

| Split and method | Paired assets | Silhouette-XOR pixels (% of image), mean [95% CI] | Squared-error share (%), mean [95% CI] |
|---|---:|---:|---:|
| Validation, QEM | 7 | 0.442 [0.022, 1.269] | 36.95 [26.68, 49.38] |
| Validation, meshoptimizer | 7 | 0.0347 [0.0107, 0.0724] | 28.02 [19.47, 35.66] |
| Train, QEM | 11 | 0.0859 [0.0195, 0.1744] | 33.01 [23.97, 42.32] |
| Train, meshoptimizer | 11 | 0.0525 [0.0058, 0.1291] | 26.80 [17.57, 37.26] |

At this 50% face budget, silhouette-XOR sites account for roughly 27-37% of
the squared error in these split-level means, not the 68.3% observed in the
historical Monkey view. The result does not refute that individual measurement;
it shows that it should not be generalized to all assets or budgets. The lower
share also does not mean the remaining error is perceptually unimportant.

Topology failures increase at this reduction. QEM was rejected on 1/8 validation
and 5/16 training inputs after simplification; meshoptimizer passed strict
topology and directed-boundary checks on 5/7 and 7/11 paired outputs respectively.
All source meshes passed their input topology checks. These invalid outputs are
retained in the raw image screen and separated from valid-output analysis.

| 70%-retention split and method | Assets | Silhouette-XOR pixels (%), mean | Squared-error share (%), mean |
|---|---:|---:|---:|
| Validation, QEM | 8 | 0.0583 | 27.68 |
| Validation, meshoptimizer | 8 | 0.0172 | 24.21 |
| Train, QEM | 15 | 0.0239 | 30.08 |
| Train, meshoptimizer | 14 finite pairs | 0.0102 | 23.97 |

See the 70% [validation report](CLUSTER_DECODER_BASELINE_70PCT_VALIDATION_20261122.md)
and [training report](CLUSTER_DECODER_BASELINE_70PCT_TRAIN_20261122.md). Across
these two budgets, error attribution depends on asset, simplifier, and retention.
They do not identify a universal silhouette-dominant regime.

## Per-asset distribution

To show how often the split averages conceal silhouette-dominant assets, the
table below computes each asset's arithmetic mean of its 12 per-view
silhouette-XOR error shares, then counts how many of those asset means exceed
50%. The fraction uses all finite recorded outputs, including outputs with
topology failures, matching the split-level all-output summary above. The same
assets appear at both retention levels, so these rows are not independent
replicates.

| Split | Retention | Method | Assets | Asset means above 50% | Median asset mean | Range |
|---|---:|---|---:|---:|---:|---:|
| Validation | 50% | QEM | 7 | 1/7 | 35.7% | 16.5–69.7% |
| Validation | 50% | meshoptimizer | 7 | 0/7 | 32.5% | 9.6–42.0% |
| Train | 50% | QEM | 11 | 1/11 | 34.3% | 7.6–63.4% |
| Train | 50% | meshoptimizer | 11 | 1/11 | 21.0% | 4.3–63.5% |
| Validation | 70% | QEM | 8 | 1/8 | 23.9% | 13.3–60.9% |
| Validation | 70% | meshoptimizer | 8 | 0/8 | 29.2% | 0.0–35.5% |
| Train | 70% | QEM | 15 | 3/15 | 31.0% | 7.9–56.2% |
| Train | 70% | meshoptimizer | 14 | 0/14 | 25.4% | 0.0–45.7% |

The summarizer is [`summarize_silhouette_attribution.py`](summarize_silhouette_attribution.py).
It reads the four JSON receipts linked above, prints each input hash, and reports
its own SHA-256 (`5d5c55aee05868c5230265d5661b42fe7a63ca9f030e03b426ac49d0126d0eb4`).
These descriptive counts reinforce the aggregate result: at these budgets,
silhouette-XOR is not the majority of squared error for most meshoptimizer
assets in this development set. This does not measure perceptual importance or
the residual after a temporal upscaler.

The full per-view results, all image and sampled-surface metrics, failed outputs,
input hashes, and code hashes are in the
[50% validation receipt](cluster_decoder_qem_meshopt_validation_50pct_20261122.json)
and [50% training receipt](cluster_decoder_qem_meshopt_train_50pct_20261122.json).
LPIPS, authored materials, temporal behavior, frame time, and mobile hardware
were not measured.
