# QEM and meshoptimizer quality at 70% face retention

Date: 2026-11-22. This supplemental screen compares two deterministic geometry
baselines on all eight validation assets. Each pair has exactly the same output
face count, targeted at 70% of source faces (30% reduction). It does not evaluate
the cluster decoder or use the held-out test split.

## Protocol

- Reference: each hash-verified validation STL, normalized to unit bounding radius.
- Simplifiers: fast-simplification 0.2.0 QEM with `preserve_border=True`, and
  vendored meshoptimizer 0.18.1 with `LockBorder` and target error `1e6`.
- Images: 12 fixed orthographic views per asset, 256x256, 4x box sampling,
  flat-shaded geometry, 8-bit sRGB. Metrics are PSNR, Gaussian-window SSIM,
  NVIDIA LDR-FLIP at 67 pixels per degree, silhouette XOR, and coverage MAE.
- Surfaces: 20,000 area-uniform samples per direction and nearest sampled-point
  cloud distances. These are estimates, not exact Hausdorff distances.
- Uncertainty: 10,000 paired bootstrap resamples over assets. Views are averaged
  within each asset and are not treated as independent samples.
- LPIPS is not measured in this supplemental screen. The earlier 30%-retention
  decoder screen reports LPIPS on its five usable validation pairs.

The image metrics use each simplifier's raw output. One meshoptimizer output is
topologically invalid; that failure is retained in the all-output image summary.
For sampled surface metrics only, zero-area and duplicate faces are omitted from
the triangle soup before sampling. That cleanup does not repair or certify the
mesh topology.

## Aggregate paired changes

Changes are meshoptimizer minus QEM. Positive PSNR, SSIM, and normal consistency
are better; negative values are better for the other metrics.

| Metric | All raw outputs, N=8: mean [95% asset-bootstrap CI] | Topology-valid subset, N=7: mean [95% asset-bootstrap CI] | Assets favoring meshoptimizer, N=8 / N=7 |
|---|---:|---:|---:|
| PSNR (dB) | +2.003 [-0.395, +4.625] | +1.721 [-0.926, +4.710] | 4 / 3 |
| SSIM | +0.00222 [+0.00037, +0.00566] | +0.00244 [+0.00033, +0.00637] | 7 / 6 |
| LDR-FLIP | -0.000908 [-0.002607, +0.000249] | -0.000954 [-0.002934, +0.000358] | 5 / 4 |
| Silhouette XOR (percentage points) | -0.0410 [-0.1238, +0.0023] | -0.0464 [-0.1411, +0.0031] | 6 / 5 |
| Sampled bidirectional Chamfer L1 | -0.0000294 [-0.0000773, +0.0000079] | -0.0000346 [-0.0000867, +0.0000070] | 4 / 4 |
| Sampled bidirectional distance p95 | -0.0001186 [-0.0002722, +0.0000100] | -0.0001149 [-0.0002906, +0.0000271] | 6 / 5 |
| Sampled maximum distance | -0.0005674 [-0.0010562, -0.0000998] | -0.0006603 [-0.0011793, -0.0001494] | 5 / 5 |
| Normal consistency (absolute dot) | +0.0001695 [-0.0011042, +0.0015314] | +0.0006679 [-0.0001962, +0.0018502] | 3 / 3 |

PSNR, FLIP, silhouette, mean Chamfer, and normal-consistency intervals include
zero. SSIM and sampled maximum distance improve in these screens, but the panel
does not establish an across-metric or topology-valid Pareto win. The only
topology-valid subset also has seven assets, so its intervals remain wide.

## Per-asset image and surface changes

| Validation asset | Returned faces per output | PSNR (dB) | SSIM | LDR-FLIP | Silhouette XOR (pp) | Sampled Chamfer L1 | Meshoptimizer topology |
|---:|---:|---:|---:|---:|---:|---:|---|
| 90431 | 514 | +6.067 | +0.01400 | -0.00648 | -0.32730 | -0.0001716 | Valid; boundary preserved |
| 263198 | 316 | -1.835 | -0.00007 | +0.00037 | +0.00267 | +0.0000268 | Valid; boundary preserved |
| 44710 | 2,220 | -1.144 | +0.00034 | +0.00093 | +0.01005 | +0.0000241 | Valid; boundary preserved |
| 191968 | 742 | -1.497 | +0.00058 | -0.00037 | -0.00114 | +0.0000100 | Valid; boundary preserved |
| 383021 | 9,650 | +8.678 | +0.00105 | -0.00129 | -0.00216 | -0.0000687 | Valid; boundary preserved |
| 100894 | 4,072 | -0.708 | +0.00069 | +0.00045 | -0.00191 | -0.0000432 | Valid; boundary preserved |
| 257594 | 24,112 | +2.488 | +0.00052 | -0.00029 | -0.00509 | -0.0000198 | Valid; boundary preserved |
| 94990 | 19,040 | +3.972 | +0.00063 | -0.00058 | -0.00331 | +0.0000073 | Rejected: degenerate triangles |

Asset 94990's raw meshoptimizer output contains 46 zero-area/sub-threshold
faces. Removing those and one duplicate for surface sampling still leaves a
nonmanifold or inconsistently oriented edge. Its rendered image metrics are
reported from the raw output; it fails the geometry-validity gate and is not a
successful simplification result. Thus its nominal returned face count matches
QEM, but its usable surface does not satisfy the same-face geometry contract.

## Decision and limits

This expands the QEM-versus-meshoptimizer validation baseline from five to eight
assets at one fixed face-retention point. Results remain mixed and do not rescue
the tested decoder, which still loses or makes no change at matched faces. The
8-asset screen is not a novel method result, a rate-distortion curve, a user study,
or a performance comparison. It uses flat-shaded geometry only; authored
materials, temporal stability, runtime cost, device power, and mobile hardware
were not measured. The 32-asset corpus has already informed earlier experiments,
so a paper claim still requires a fresh licensed confirmation set.

## Reproduction artifacts

- [Machine-readable report and per-view metrics](cluster_decoder_qem_meshopt_validation_70pct_20261122.json)
- [Evaluator](compare_qem_meshopt_validation_70pct.py)
- [Earlier matched-face decoder comparison](CLUSTER_DECODER_MESHOPT_20261122.md)
- The generated gallery is under the ignored path `out/qem-meshopt-validation-70pct/validation-gallery.png`.

Run from PowerShell with the locally cached research dependencies:

```powershell
$imageDeps = (Resolve-Path 'out\image-quality-deps').Path
$geometryDeps = (Resolve-Path 'out\geometry-refinement-pilot\deps').Path
$env:PYTHONPATH = "$imageDeps;$geometryDeps"
$env:OMP_NUM_THREADS = '1'
python tools/mmtrain/compare_qem_meshopt_validation_70pct.py `
  --manifest out/thingi10k-metadata/meshes/download_manifest.json `
  --out out/qem-meshopt-validation-70pct `
  --retention 0.70 --views 12 --size 256 --samples 2 `
  --surface-samples 20000 --flip-ppd 67
```
