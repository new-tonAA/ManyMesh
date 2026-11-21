# Thingi10K split-safe tile-ranking screen (2026-11-21)

## Question

Does the existing compact model that ranks screen tiles for finer mesh LODs generalize to
independent licensed meshes, and does its geometric collapse-witness channel help? This is a
held-out algorithm screen for the existing tile-refinement idea, not a mesh-super-resolution
model and not an end-to-end renderer result.

## Frozen data and task

The dataset contains 32 distinct Thingiverse objects: 16 train, 8 validation, and 8 test Things,
split by a stable hash. It totals 347,976 input triangles. Each asset was rendered from 12
orthographic views with grayscale directional lighting. The pair builder forms source, 20%-face,
and 45%-face QEM meshes. It renders at 96x96 and 384x384, box-filters the source image to 192x192,
and measures 8x8 tile MSE after the same 2x bicubic filter. Each tile gets raster statistics and
one optional geometric witness value from QEM collapse displacement.

The budget task chooses the top 10% or 25% of 8x8 tiles to receive the 45%-face mesh instead of
the 20%-face mesh. The reported quality is the percentage reduction in tile MSE relative to using
the coarse mesh everywhere. This tile replacement does not build or verify one legal mixed mesh
cut; it is a ranking proxy with a fixed, identical geometry budget per view.

The compact models are a 12-hidden-unit ReLU MLP with 97 weights for raster features and 121
weights for raster plus the geometric witness. They train on 16 Things in about 0.15 seconds in
the final run. The validation set selects the ranker separately for each budget; the held-out test
set is then evaluated once with that frozen choice.

## Result

| Tile budget | Validation winner | Validation gain | Test: selected winner | Test: MLP | Test: MLP + witness | Test oracle |
|---:|---|---:|---:|---:|---:|---:|
| 10% | Contrast heuristic | 19.66% | 9.45% | 7.00% | 7.01% | 19.46% |
| 25% | Contrast heuristic | 34.26% | 18.82% | 16.19% | 16.01% | 25.26% |

The validation-selected contrast heuristic is a simple local image statistic, not a learned model.
The MLP with geometry witness lost to contrast on all eight held-out Things at both budgets; the
plain MLP lost on all eight Things at 10% and on seven of eight at 25%. Its mean deficit against
contrast was 2.45 and 2.63 percentage points. The oracle retains substantial headroom, so the
small ranker is not failing because this tile objective is already solved.

This closes a claim that the current 97/121-parameter MLP plus the current witness feature is a
cross-asset improvement on this task. It does not rule out other model inputs, training objectives,
or algorithms. It also does not establish any SIGGRAPH contribution: the task is a raster ranking
proxy, the source is clean and grayscale, and no temporal, textured, perspective, renderer, or
end-to-end frame-time evaluation is included.

The broad novelty space is already occupied by [Neural Mesh Simplification (CVPR 2022)](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html)
and [Appearance-Driven Automatic 3D Model Simplification (EGSR 2021)](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc).
This screen tests only whether ManyMesh's specific compact tile ranker and collapse witness add a
measured benefit beyond simple raster heuristics.

## Reproduction

The downloaded mesh files and generated pairs stay in ignored `out/thingi10k-metadata/`.

```powershell
python tools/mmtrain/index_thingi10k_assets.py `
  out/thingi10k-metadata/meshes/download_manifest.json `
  --out out/thingi10k-metadata/asset-index/sources.json
$env:PYTHONPATH = (Resolve-Path out/geometry-refinement-pilot/deps).Path
$env:NUMBA_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
python tools/mmtrain/make_refinement_pairs.py `
  out/thingi10k-metadata/asset-index `
  --out out/thingi10k-metadata/pairs-96 `
  --views 12 `
  --size 96
python tools/mmtrain/probe_thingi_refinement.py `
  out/thingi10k-metadata/pairs-96 `
  --out out/thingi10k-metadata/model-screen
```

The split, selected ranker, per-asset results, and trained weights are written under the ignored
output directory. Reproduction hashes:

- Download manifest: `3a7cfbd6e652f5fbeade83110c5027e37d05629303580657d444a5bbcd645742`
- Indexed source manifest: `212f011c4bf56530d26f89281ff122d7429694235368f4f2d35b3a1884dcc65a`
- Pair manifest: `e358a91d8a4dcae0e1731faa954a714f5d57c2286dc77c3a85d21e1bd10195c3`
- Aggregate hash of 32 pair NPZ files: `5790805b94639a5a82efca100caf629bfb0ece6b3ac5c4cfd1b666223996c1d5`
- Probe output: `afa2dd4ad54a7617e704ecc5aadc4cd1569bb7b6ce678702c06be13c12a19d4c`
