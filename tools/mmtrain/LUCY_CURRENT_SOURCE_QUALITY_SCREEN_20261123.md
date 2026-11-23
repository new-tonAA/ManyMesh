# Lucy current-source quality screen

Run on 2026-11-23 using the current `mmgeo` binary. This is a development
diagnostic on an asset already used in older ManyMesh experiments. It is not a
held-out result, a clean confirmation asset, or evidence for a new method.

## Asset and provenance

- Input: `third_party/models/lucy/lucy.obj`, SHA-256
  `689d7c8bc69f3d02d8b2a961b76cd40b154829719e4076fbcea86d498685b42a`.
- The tracked Lucy source note permits research use and publication of images
  with credit to the Stanford University Computer Graphics Laboratory; it
  prohibits commercial use without permission. Do not redistribute the model
  as part of a commercial product.
- A bounded search of 465 text artifacts found exact geometry-hash matches in
  an earlier literature audit and the 2026-11-13 proxy-grid paired receipt.
  The full scan manifest is in the [reuse audit](asset_reuse_audits/lucy_20261123.json).
- The geometry-only OBJ reader sees 16,723 source positions and 33,446 faces;
  `mmgeo` reports 18,455 imported render vertices and the same 33,446 faces.
  The importer-to-OBJ vertex correspondence was not reconstructed, so the
  vertex-count difference is recorded as an unresolved importer detail. The
  quality comparison uses the original OBJ surface as the common reference.
- Binary, source, script, package, and helper hashes, plus all eight per-view
  records for each method, are in the [raw receipt](lucy_current_source_controls_20261123.json).

## Protocol

ManyMesh produced cuts for requested retention ratios 0.3, 0.5, and 0.7.
The first request was infeasible: its legal cut retained 16,222/33,446 faces
(48.50%). The other actual counts were 16,722 (49.997%) and 23,412 (69.999%).
All three passed the recorded topology and source-boundary checks. Every
eligible cut was compared at its actual face count against whole-mesh
fast-simplification QEM and meshoptimizer with `LockBorder`; every control also
had to return the exact count and pass the same checks.

The reference was the full-resolution source OBJ. Rendering used eight
orthographic views, flat shading, 192 x 192 output, four software samples per
pixel, and LDR-FLIP at 67 pixels per degree. These samples are not hardware
MSAA. Surface metrics use 10,000 samples per direction. No AA/upscaler, moving
camera, animation, user study, or physical device was involved.

## Results

Every table entry is ManyMesh minus the exact-face control. For FLIP, silhouette
XOR, and coverage MAE, lower is better; for PSNR and SSIM, higher is better.
ManyMesh loses on every listed image metric at all three budgets.

| Requested retention | Actual faces / retention | Control | FLIP delta | PSNR delta | SSIM delta | Silhouette-XOR delta |
|---:|---:|---|---:|---:|---:|---:|
| 30% | 16,222 / 48.50% | QEM | +0.002482 | -2.940 dB | -0.004970 | +0.000207 |
| 30% | 16,222 / 48.50% | Meshoptimizer | +0.003323 | -5.096 dB | -0.006760 | +0.000315 |
| 50% | 16,722 / 50.00% | QEM | +0.002392 | -2.890 dB | -0.004654 | +0.000203 |
| 50% | 16,722 / 50.00% | Meshoptimizer | +0.003312 | -5.232 dB | -0.006584 | +0.000315 |
| 70% | 23,412 / 70.00% | QEM | +0.001078 | -3.289 dB | -0.002171 | +0.000119 |
| 70% | 23,412 / 70.00% | Meshoptimizer | +0.001709 | -5.361 dB | -0.002688 | +0.000139 |

The 30% row is not a 30%-budget result: ManyMesh could not reach that budget,
and controls were matched to its actual 48.50% cut. Sampled surface metrics are
mixed across the methods and budgets; consult the raw receipt rather than
collapsing image and geometry measures into one score. This single reused asset
does not support a generalization claim.

## Reproduction

The geometry extraction and asset reuse receipts are
[`asset_reuse_audits/lucy_20261123.json`](asset_reuse_audits/lucy_20261123.json).
From the repository root in PowerShell, after building the recorded mmgeo
source and setting the local Python dependencies:

```powershell
out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  third_party/models/lucy/lucy.obj `
  --out out/lucy-current-source-screen-20261123 `
  --mode dag --levels 8 --target-ratio 0.3 `
  --target-ratio-cut 0.3,0.5,0.7 --quality-gate 1 `
  --dump-format ply --visibility 0 --write-dag 0

$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path + ';' + (Resolve-Path 'out/image-quality-deps').Path
python tools/mmtrain/score_mmgeo_obj_controls.py `
  --source-obj third_party/models/lucy/lucy.obj `
  --cut-dir out/lucy-current-source-screen-20261123 `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out tmp/lucy-mmgeo-controls-20261123
```

The currently archived mmgeo build has dirty-source provenance; see
[`CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md`](CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md).
