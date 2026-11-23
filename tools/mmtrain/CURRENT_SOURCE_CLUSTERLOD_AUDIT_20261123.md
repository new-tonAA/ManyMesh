# Current-source cluster LOD eligibility audit

Run on 2026-11-23. This reruns the pinned meshoptimizer v1.2 face-budget comparison against the current ManyMesh `mmgeo` binary. It checks whether current cuts are topology-valid, preserve the source directed boundary, stay under the upstream face cap, and form an exact-face comparison. **No current-source cut produced an eligible exact-face pair, so this run makes no matched-budget image-quality claim.**

## Protocol and provenance

- Eight reused Thingi10K validation assets, using the frozen manifest and source hashes from the upstream comparison.
- Reused the unmodified meshoptimizer v1.2 cut outputs at native depth 1 and depth 2 as requested face caps. Verified each staged OBJ against the source asset and upstream receipt.
- Built each ManyMesh DAG from the original full-resolution source mesh. Compared actual cut counts against the upstream cut counts. For each candidate, the script records LDR-FLIP, PSNR, SSIM, silhouette/coverage diagnostics, sampled surface metrics, strict topology checks, and directed-boundary preservation relative to the original source. These source-relative image metrics are diagnostics, not a direct comparison against the upstream cut.
- Render protocol: eight orthographic views, 192 x 192, four samples per pixel, flat shading, 67 pixels per degree for FLIP. The CPU renderer and commands ran on Intel Core i7-13700H / Windows 11. Per-command time includes DAG construction and exports; it is not a selector-only or GPU timing.
- Git HEAD: `2d417cacdeb545a13e6bfb7192310191e60670d6`; the source worktree was dirty. `mmgeo` binary SHA-256: `8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e`; `tools/mmgeo/src/main.cpp` SHA-256: `c044d8d026b32ccb335e99a8c9b0ef4e2ffc766e51455647f29f75bdcf6edea4`; benchmark script SHA-256: `3d2ef64834275446053ee5910de01aa82323100569cc497a779f2e33f66b35b1`.
- The upstream cut receipt is pinned by SHA-256 `a137ccd65357c087ac8f4e845fef1665a53c2c03e2c410f97babd92c166386dc`; the Thingi10K manifest SHA-256 is `3a7cfbd6e652f5fbeade83110c5027e37d05629303580657d444a5bbcd645742`. The raw current-source receipt is [`current_source_clusterlod_audit_20261123.json`](current_source_clusterlod_audit_20261123.json).
- The source worktree was dirty. Its parent revision, archived source patch,
  source/binary hashes, and missing compiler/build command are recorded in the
  [current-source provenance record](CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md).

## Results

| Asset | Source faces | Upstream depth 1 cap / ManyMesh | Upstream depth 2 cap / ManyMesh | Valid topology + boundary cuts | Valid cuts under cap |
|---:|---:|---:|---:|---:|---:|
| 90431 | 736 | 368 / 392 | 184 / 392 | 2/2 | 0/2 |
| 263198 | 452 | 226 / 140 | 112 / 108 | 2/2 | 2/2 |
| 44710 | 3,172 | 1,586 / 1,586 | 792 / 965 | 0/2 | 0/2 |
| 191968 | 1,060 | 530 / 408 | 264 / 238 | 2/2 | 2/2 |
| 383021 | 13,788 | 6,894 / 6,870 | 3,446 / 4,257 | 0/2 | 0/2 |
| 100894 | 5,820 | 2,910 / 2,849 | 1,454 / 2,849 | 0/2 | 0/2 |
| 257594 | 34,448 | 17,222 / 17,032 | 8,608 / 11,332 | 0/2 | 0/2 |
| 94990 | 27,200 | 13,598 / 13,415 | 6,794 / 10,031 | 0/2 | 0/2 |

Across all 16 current-source cuts, **6/16** passed both strict topology and directed-boundary checks. Four of those six also met the requested face cap, on assets 263198 and 191968. One cut had the exact upstream face count (asset 44710, depth 1), but failed the topology/boundary gate. Therefore there are **zero valid exact-face pairs**. This reproduces the practical eligibility failure seen in the older pinned ManyMesh binary; the current run is direct evidence for the current binary hash listed above.

The two assets with valid under-cap cuts are not enough for a quality claim, and they do not have exact face-count matches. The source-relative image metrics in the receipt cannot substitute for an equal-budget head-to-head with the upstream cluster cut. Do not cite them as evidence that ManyMesh beats or loses to meshoptimizer cluster LOD.

## Reproduction

The original helper assumed staged OBJ files lived beside the receipt. The rerun exposed that path assumption; `compare_manymesh_clusterlod.py` now takes the staged cut directory explicitly:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path + ';' + (Resolve-Path 'out/image-quality-deps').Path
python tools/mmtrain/compare_manymesh_clusterlod.py `
  --manifest out/thingi10k-metadata/meshes/download_manifest.json `
  --upstream-receipt tools/mmtrain/upstream_clusterlod_20261122.json `
  --upstream-cut-dir out/upstream-clusterlod/validation `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out tmp/current-mmgeo-clusterlod-20261123
```

This is a geometry-eligibility audit, not a method result. It does not resolve the untested differentiable-geometry hypothesis or the absent CUDA/mobile measurements.

### Follow-up parameter sweep

This fixed-default audit had no eligible exact-face pair. A separate fixed grid
of 48 DAG builds later recovered two eligible exact-face pairs among 96 cuts;
both were at stock depth 1 and both lost to stock on all reported image
metrics. See the [parameter-sweep report](CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md)
and its full eligibility and score receipts. The follow-up does not change the
counts or conclusions above for this default configuration.
