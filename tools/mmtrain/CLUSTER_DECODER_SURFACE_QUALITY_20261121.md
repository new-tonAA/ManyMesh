# Cluster decoder: sampled surface-quality screen

Date: 2026-11-21. Status: **the frozen rank-8 linear control does not improve
validation surface distance over QEM**. This is a complementary geometry
diagnostic for the same 24-asset development screen, not a final test or a
SIGGRAPH contribution.

## Metrics and protocol

Surface reconstruction papers commonly report bidirectional Chamfer distance
and normal consistency. For example, [Sketch2Mesh (ICCV 2021)](https://openaccess.thecvf.com/content/ICCV2021/papers/Guillard_Sketch2Mesh_Reconstructing_and_Editing_3D_Shapes_From_Sketches_ICCV_2021_paper.pdf)
defines Chamfer distance from sampled mesh surfaces and reports normal
consistency. These metrics have implementation conventions, not a universal
acceptability threshold.

This screen draws 20,000 area-uniform points from each surface using a
deterministic per-asset seed, then uses nearest neighbors in the opposing sampled
point cloud. It reports the mean of the two directed mean distances (Chamfer-L1),
the mean of the two directed mean squared distances (symmetric Chamfer-L2), and
the 95th percentile / maximum of the concatenated directed distances. The normal
metric is the mean absolute dot product between nearest sampled face normals;
absolute value makes it insensitive to inconsistent STL winding. Distances use
the source meshes' unit-bounding-radius coordinate system.

These are sampled point-cloud estimates, **not exact point-to-triangle distances**;
the percentile and maximum are sampled tails, not Hausdorff bounds. Independent
surface sampling adds Monte Carlo variation. The normal convention also differs
from orientation-sensitive normal metrics. Interpret small deltas cautiously and
use the image panel in [the main quality screen](CLUSTER_DECODER_QUALITY_20261121.md)
alongside these geometry values.

## Paired results

Only assets where both QEM and the frozen decoder passed the existing geometry
and boundary checks are paired. Preparation and decode failures remain in the
underlying report. Values below are unweighted means across assets; lower is
better except for normal consistency.

| Split / paired assets | Method | Chamfer-L1 | Symmetric Chamfer-L2 | Distance p95 | Absolute normal consistency |
|---|---|---:|---:|---:|---:|
| Train / 7 | QEM | 0.016476 | 0.00195415 | 0.063368 | 0.934466 |
| Train / 7 | Rank-8 decoder | 0.016512 | 0.00196854 | 0.063451 | 0.934729 |
| Validation / 4 | QEM | 0.012072 | 0.00036491 | 0.033736 | 0.924193 |
| Validation / 4 | Rank-8 decoder | 0.012175 | 0.00036840 | 0.033916 | 0.924254 |

Validation candidate-minus-QEM mean deltas are +0.0001021 Chamfer-L1
(10,000 bootstrap resamples over assets; 95% percentile interval
[+0.0000356, +0.0001518]), +0.00000349 squared Chamfer
([+0.00000067, +0.00000753]), and +0.0001801 distance p95
([+0.0000447, +0.0002963]). These distance measures worsen on the four paired
assets. Absolute normal consistency changes by only +0.000061 (higher is better;
interval [+0.0000051, +0.0001208]); this tiny sampled change does not establish a
meaningful normal-quality improvement. The paired sample is exploratory and small.

The result agrees with the image screen's conclusion: fitting pointwise residual
labels is not evidence of a useful visual or geometric gain. Keep rank-8 as a
negative control. Do not evaluate the final test set until the method, rendering
protocol, and stronger baselines are frozen.

## Reproduction

Use the pinned geometry dependencies (NumPy 2.2.6, SciPy 1.15.3,
fast-simplification 0.2.0) and the existing metric environment:

```powershell
$env:PYTHONPATH = (Resolve-Path out/geometry-refinement-pilot/deps).Path + ';' + (Resolve-Path out/image-quality-deps).Path
$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmtrain/cluster_decoder_surface_quality.py `
  --pairs out/cluster-decoder-pairs/train-pruned/manifest.json `
  --pairs out/cluster-decoder-pairs/validation/manifest.json `
  --fit out/cluster-decoder-fit/rank8 `
  --quality out/cluster-decoder-quality/rank8 `
  --out out/cluster-decoder-surface-quality/rank8 --samples 20000
```

The tracked [compact receipt](cluster_decoder_surface_quality_20261121.json) retains
per-asset metrics, source hashes, decode status, seed policy, runtime versions, and
the hashes of the source manifests, fit report, fixed model, script, and frozen
image-quality report. The full working report is at
`out/cluster-decoder-surface-quality/rank8/report.json`. No production format or
renderer API is changed.
