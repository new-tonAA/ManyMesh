# Current-source matched-face geometry controls

Run on 2026-11-23. This screen compares valid current ManyMesh DAG cuts with whole-mesh meshoptimizer simplification and fast QEM at the candidate's actual face count. The common reference is the original full-resolution Thingi10K mesh. This is separate from the stock meshoptimizer cluster-LOD comparison: most stock cuts have no valid exact-face ManyMesh counterpart.

## Protocol and provenance

- Eight reused Thingi10K validation assets, with the hash-pinned manifest and upstream cut receipt. No asset is an independent confirmation model.
- Built each ManyMesh cut from the original full source. Only candidates passing strict topology and directed-boundary checks were eligible for a matched-face control. Both controls were simplified from the same original source to the candidate's actual face count; the comparison was scored only if the control also returned that exact count and passed the same topology/boundary checks.
- Controls: meshoptimizer whole-mesh simplification with `LockBorder`; fast-simplification QEM with `preserve_border=True`. These are not meshoptimizer cluster-LOD cuts.
- Eight orthographic views, 192 x 192 pixels, flat shading, four box samples per pixel, and 67 pixels per degree for LDR-FLIP. The reference is the original source, not a DAG full-detail cut. No hardware MSAA or upscaler was involved.
- Reported image deltas are `ManyMesh - control`: lower FLIP, silhouette XOR, and coverage MAE are better; higher PSNR and SSIM are better. Surface distances use 10,000 area-uniform samples per direction and are estimates, not Hausdorff bounds.
- The eight views are repeated measurements of the same asset, not eight independent samples. The result is descriptive; no significance test or generalization claim is made.
- Git HEAD `2d417cacdeb545a13e6bfb7192310191e60670d6`; worktree dirty. ManyMesh binary SHA-256 `8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e`; `main.cpp` SHA-256 `c044d8d026b32ccb335e99a8c9b0ef4e2ffc766e51455647f29f75bdcf6edea4`; script SHA-256 `bc0db94eff1dd2df2c98b9d6fed6b6f12a29abd88acdc1e61dda230cbf72cdf2`.
- Environment: Python 3.12.3, NumPy 2.2.6, fast-simplification 0.2.0, Node v22.16.0. The meshoptimizer helper SHA-256 is `074f04627ad00372403c98a20ac306626a162f474cc27e5a97806cbc76e03136`; its JS module SHA-256 is `5f63c97b83c248d5056c8e67b2464d248cf02b018a3410c5f6cd091938b5428c`.
- The raw per-view receipt is [`current_source_matched_face_controls_20261123.json`](current_source_matched_face_controls_20261123.json), SHA-256 `4954c20c63a60ffa21fb7b23f4da210fd1c260791d7ebffbee8186768401c33d`. It records the source manifest, upstream receipt, commands, candidate hashes, full per-view metrics, and all eligibility failures.

## Results

There were 6 topology- and boundary-valid ManyMesh cuts among the 16 requested stock-budget cuts; 4 also stayed under the stock face cap, on two assets. At the candidate's actual face count, meshoptimizer produced 5 eligible exact-face, topology-valid pairs. Three of those also stayed under the stock cap: two LOD budgets on asset 263198 and one on asset 191968. The two 263198 rows are one asset, not two independent trials.

| Asset | Stock depth | ManyMesh faces | Under stock cap | Meshoptimizer FLIP delta | PSNR delta (dB) | SSIM delta | Silhouette-XOR delta |
|---:|---:|---:|:---:|---:|---:|---:|---:|
| 263198 | 1 | 140 | Yes | -0.003350 | +3.841 | +0.00444 | -0.000573 |
| 263198 | 2 | 108 | Yes | -0.007200 | +4.034 | +0.01025 | -0.001543 |
| 191968 | 1 | 408 | Yes | +0.008539 | -12.838 | -0.01677 | +0.004727 |

ManyMesh improves all listed image metrics over whole-mesh meshoptimizer on both budgets for asset 263198, and loses them on asset 191968. At a fourth under-cap cut (191968, depth 2), the meshoptimizer result failed strict topology, so it is not scored. The exact-face QEM control was eligible only for asset 191968 at depth 1; ManyMesh lost there too (FLIP delta +0.005174, PSNR -7.843 dB, SSIM -0.01215). QEM did not produce the requested exact face count on the other legal candidates.

The remaining two eligible meshoptimizer pairs are on asset 90431 but exceed the corresponding stock face caps (392 faces against caps of 368 and 184). They are exact-face controls at 392 faces, not valid stock-budget comparisons; ManyMesh loses all listed image metrics there as well (FLIP delta +0.008343, PSNR -4.067 dB, SSIM -0.01684).

This is a mixed result on only two assets with usable under-cap controls: two adjacent levels win on one asset and one level loses substantially on the other. It does not establish a repeatable Pareto gain, held-out generalization, or a SIGGRAPH contribution. The fixed-default audit against actual stock cluster cuts had zero valid exact-face pairs; a later parameter sweep recovered two, and both lost to stock on the reported image metrics. Do not conflate this whole-mesh simplifier control with the cluster-LOD comparison. See the [fixed-default audit](CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md) and [parameter-sweep report](CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md).

## Reproduction

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path + ';' + (Resolve-Path 'out/image-quality-deps').Path
python tools/mmtrain/compare_manymesh_clusterlod.py `
  --manifest out/thingi10k-metadata/meshes/download_manifest.json `
  --upstream-receipt tools/mmtrain/upstream_clusterlod_20261122.json `
  --upstream-cut-dir out/upstream-clusterlod/validation `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out tmp/current-mmgeo-clusterlod-20261123-final-controls
```
