# Current-source cluster LOD parameter sweep

Run on 2026-11-23. A fixed build-parameter grid recovered two topology-valid,
exact-face pairs against stock meshoptimizer cluster LOD. Both candidates lost
the image-quality comparison on every reported metric. This is a small,
exploratory development screen, not evidence of a SIGGRAPH contribution.

## Protocol

- Reused all eight validation assets from the pinned meshoptimizer v1.2 screen.
- Swept `--cluster-tris` in `{64, 128, 256}` and `--dag-group` in `{4, 8}`;
  all other mmgeo build settings were fixed at the defaults recorded by the
  script. This produced 48 builds and 96 candidate cuts. Every row, including
  failures and over-budget cuts, is preserved in the [eligibility receipt](cluster_cut_parameter_sweep_20261123.json).
- An exact-face candidate was eligible only when its triangle count exactly
  matched the stock cut and it passed strict closed-topology and source-directed
  boundary checks. No image metric was consulted to select candidates.
- All eligible pairs were then compared against the corresponding stock
  meshoptimizer cluster cut. The reference was the original full-resolution
  source mesh. The eight views were orthographic at 192 x 192, flat shaded, with
  four software samples per pixel; LDR-FLIP used 67 pixels per degree. These
  software samples are not hardware MSAA. Surface distances use 10,000 sampled
  points per direction.
- Assets were reused validation inputs, not an independent test set. Per-view
  observations are correlated within each asset; no significance test or
  generalization claim is made. The grid was exploratory and its outcomes must
  not be used to tune quality parameters.
- The current-source mmgeo binary and source hashes, the full commands, every
  candidate count, topology/boundary status, and candidate hashes are in the
  [eligibility receipt](cluster_cut_parameter_sweep_20261123.json). Per-view
  quality measurements and both raw sides of every eligible pair are in the
  [score receipt](cluster_cut_parameter_score_20261123.json).
- The source tree was dirty when the executable was built. The relevant source
  patch, parent revision, binary hash, build-cache metadata, and remaining
  reproducibility gap are documented in the [mmgeo provenance record](CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md).

## Results

Only two of 96 cuts were exact-face, topology-valid, boundary-preserving pairs.
Both matched stock depth 1:

| Asset | Settings (`cluster-tris`, `dag-group`) | Faces | FLIP delta | PSNR delta | SSIM delta | Silhouette-XOR delta |
|---:|---:|---:|---:|---:|---:|---:|
| 191968 | 256, 4 | 530 | +0.013160 | -16.304 dB | -0.02313 | +0.003937 |
| 100894 | 256, 8 | 2,910 | +0.014229 | -14.271 dB | -0.02699 | +0.001804 |

Deltas are ManyMesh minus stock; lower FLIP and silhouette XOR, and higher PSNR
and SSIM, are better. Both exact-budget ManyMesh cuts lose on every listed
metric. The two assets are the independent units for this descriptive screen,
and two assets are far too few for a quality or generalization claim. No
candidate was found for stock depth 2 in this fixed parameter grid.

Sampled surface metrics also favor stock. Distances are in the normalized
source-mesh coordinate system; normal consistency is the absolute dot product.

| Asset | Method | Mean bidirectional distance | 95th percentile distance | Mean normal consistency |
|---:|---|---:|---:|---:|
| 191968 | ManyMesh | 0.01552 | 0.03101 | 0.95470 |
| 191968 | Stock cluster LOD | 0.01505 | 0.02939 | 0.95981 |
| 100894 | ManyMesh | 0.02379 | 0.09207 | 0.88751 |
| 100894 | Stock cluster LOD | 0.01229 | 0.02370 | 0.95897 |

This closes the tested cluster-size/DAG-group combinations as a promising route
to the missing matched-budget stock comparison. It does not prove that all
ManyMesh parameterizations lose, and it does not establish a general quality
ordering. Do not expand the grid to hunt for a quality win on these same reused
assets; use a new, predeclared mechanism and an independent confirmation set if
the geometry method is reopened.

## Reproduction

The required local dependencies and pinned source inputs are described by the
earlier [cluster LOD screen](UPSTREAM_CLUSTERLOD_SCREEN_20261122.md). From the
repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path + ';' + (Resolve-Path 'out/image-quality-deps').Path
python tools/mmtrain/sweep_cluster_cut_eligibility.py `
  --manifest out/thingi10k-metadata/meshes/download_manifest.json `
  --upstream-receipt tools/mmtrain/upstream_clusterlod_20261122.json `
  --upstream-cut-dir out/upstream-clusterlod/validation `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out tmp/cluster-cut-parameter-sweep-20261123-all
python tools/mmtrain/score_cluster_cut_eligibility_sweep.py `
  --manifest out/thingi10k-metadata/meshes/download_manifest.json `
  --upstream-receipt tools/mmtrain/upstream_clusterlod_20261122.json `
  --upstream-cut-dir out/upstream-clusterlod/validation `
  --eligibility-receipt tmp/cluster-cut-parameter-sweep-20261123-all/receipt.json `
  --out tmp/cluster-cut-parameter-score-20261123
```

The second command scores every eligible exact-face row from the first receipt;
it does not choose a configuration by image quality.
