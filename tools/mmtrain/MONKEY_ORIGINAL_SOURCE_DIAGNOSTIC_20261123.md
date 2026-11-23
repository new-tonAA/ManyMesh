# Monkey original-source diagnostic

Run on 2026-11-23. This corrects the reference mesh for a development
diagnostic; it does **not** establish a held-out method win.

## Source and protocol

- Reference: `assets/models/monkey/monkey.obj`, SHA-256
  `7b754119aa286ff618b9ac30038c8aa9a093e2820242913728c8b20d8000ca88`;
  15,744 triangles. No asset license record was found beside this local file,
  so retain it as internal development data pending provenance review.
- `mmgeo` imported 9,908 vertices and built a 426-node, 10-level DAG. The
  source has 168 boundary edges and no non-manifold edges under the recorded
  topology check. See the archived [build log](asset_reuse_audits/monkey_source_mmgeo_20261123.log).
- Requested face retentions were 30%, 50%, and 70%; actual cuts contained
  4,724, 7,870, and 11,020 faces. The `score_mmgeo_obj_diagnostic_controls.py`
  script compared each against the original full-resolution OBJ using eight
  orthographic views, flat shading, 192 x 192 output, four software samples per
  pixel, and LDR-FLIP at 67 pixels per degree. These samples are not hardware
  MSAA. Exact-face controls were fast-simplification QEM and whole-mesh
  meshoptimizer with `LockBorder`.
- The raw receipt pins source, binary, scorer, helper, package and per-view
  hashes and records surface as well as image metrics:
  [JSON receipt](monkey_source_reference_diagnostic_20261123.json).

## Eligibility and results

All three cuts failed the scorer's exact directed-boundary edge-set comparison.
The geometric-curve audit found 168 source and candidate boundary edges and
unique vertices, with 78 vertices matching bit-for-bit. A one-to-one nearest
vertex map matched all 168 oriented edges and reversed none. Its maximum
vertex displacement was `6.19e-8` normalized units; maximum sampled symmetric
curve distance was `6.08e-8`, and relative total-length error was `3.3e-9`.
At unit radius, the vertex displacement is 0.52 float32 epsilon (`1.19e-7`),
consistent with output-coordinate quantization rather than a meaningful
boundary shift. The exact-edge flag remains false in the raw receipt; this
precision interpretation is retrospective and must be frozen as a criterion
before any confirmation test. See the [boundary audit](monkey_boundary_curve_audit_20261123.json)
and [audit script](audit_cut_boundary_geometry.py).

The candidate has no topology error under the scorer's manifold/orientation
check. A follow-up rescoring pass made the geometric tolerance explicit at one
float32 ULP in normalized coordinates, while retaining the one-to-one oriented
edge-map requirement. All three cuts pass that retrospective gate, as do QEM
and meshoptimizer at 30% and 50%; at 70%, meshoptimizer passes and QEM remains
rejected for duplicate geometric triangles. The exact-edge result remains
false. The repeat receipt is
[monkey_source_float32_boundary_diagnostic_20261123.json](monkey_source_float32_boundary_diagnostic_20261123.json).
This tolerance was selected after inspecting the first run, so it is not a
preregistered confirmation rule.

Silhouette-XOR pixels accounted for 34.75%, 25.84%, and 25.88% of the
ManyMesh candidate's squared image error at the three requested retentions.
This is substantially below the historical single-view 68.3% figure, which
used a DAG cut rather than the original source as reference. It is still one
asset and a fixed diagnostic view set, not a general silhouette-error law.

At every budget with an eligible control, ManyMesh lost on all listed image
metrics. Deltas below are ManyMesh minus control; lower is better for FLIP,
silhouette XOR, and coverage MAE, while higher is better for PSNR and SSIM.

| Retention | Faces | Control | FLIP delta | PSNR delta | SSIM delta | Silhouette-XOR delta | Coverage-MAE delta |
|---:|---:|---|---:|---:|---:|---:|---:|
| 30% | 4,724 | QEM | +0.006346 | -3.336 dB | -0.012998 | +0.000817 | +0.000819 |
| 30% | 4,724 | Meshoptimizer | +0.008770 | -5.663 dB | -0.019270 | +0.001129 | +0.001131 |
| 50% | 7,870 | QEM | +0.004526 | -5.183 dB | -0.008001 | +0.000522 | +0.000564 |
| 50% | 7,870 | Meshoptimizer | +0.005729 | -7.391 dB | -0.009845 | +0.000627 | +0.000653 |
| 70% | 11,020 | Meshoptimizer | +0.003255 | -9.511 dB | -0.004304 | +0.000329 | +0.000291 |

This does not support a SIGGRAPH contribution claim: it is one reused asset,
the tolerance was chosen retrospectively, the local source license is
unresolved, and ManyMesh loses to eligible controls on the measured image
metrics under the one-ULP rule. Do not use the 70% QEM row because no eligible
QEM control was produced. The complete per-view and surface records are in the
[original diagnostic receipt](monkey_source_reference_diagnostic_20261123.json)
and the [one-ULP rescore receipt](monkey_source_float32_boundary_diagnostic_20261123.json).

## Reproduction

The current dirty-source binary and recoverable patch are documented in the
[source provenance record](CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md). From
the repository root in PowerShell:

```powershell
out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  assets/models/monkey/monkey.obj `
  --out out/monkey-source-reference-screen-20261123 `
  --mode dag --levels 8 --target-ratio 0.3 `
  --target-ratio-cut 0.3,0.5,0.7 --quality-gate 1 `
  --dump-format ply --visibility 0 --write-dag 0

$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path + ';' + (Resolve-Path 'out/image-quality-deps').Path
python tools/mmtrain/score_mmgeo_obj_diagnostic_controls.py `
  --source-obj assets/models/monkey/monkey.obj `
  --cut-dir out/monkey-source-reference-screen-20261123 `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out tmp/monkey-source-controls-diagnostic-20261123 `
  --score-ineligible-controls
```
