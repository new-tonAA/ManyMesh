# Khronos equal-face quality screen

Run on 2026-11-23. This is a development-pool diagnostic, not a held-out test,
not an equal-frame-time result, and not evidence that a new method works.

## Question and protocol

The earlier screen compared selected DAG cuts with the DAG's own full-detail
cut. This follow-up uses each source asset's extracted full-resolution static
geometry as the reference and compares the current ManyMesh cut with exact-face
whole-mesh controls. It tests seven Khronos glTF Sample Assets at requested
30%, 50%, and 70% face retention. The actual face counts and ratios are listed
below; the GlassBrokenWindow hierarchy could not reach the requested cuts.

For each available candidate: eight fixed orthographic views, flat shading,
192 x 192 pixels, four CPU software samples per pixel, and LDR-FLIP at 67
pixels per degree. These samples are not hardware MSAA. Image metrics are
LDR-FLIP, PSNR, SSIM, silhouette XOR, and coverage MAE. Surface metrics use
10,000 area-uniform samples per direction and include symmetric Chamfer,
95th-percentile distance, and normal consistency. Controls are
fast-simplification QEM and meshoptimizer whole-mesh simplification with
LockBorder, each asked for the candidate's exact face count. A control is
reported only when it has that count and passes the same topology and boundary
eligibility rule.

The initial protocol required an exact directed-boundary edge-set match. A
separate Monkey export diagnostic then showed coordinate-rounding-sized boundary
differences after float32 PLY export. This follow-up therefore also records a
one-float32-epsilon boundary-curve rule: a one-to-one vertex mapping must
preserve every oriented boundary edge and reverse none. The rule was selected
after seeing the strict screen and is **retrospective**, not preregistered. The
original exact-edge receipts remain intact in the linked summary. No result
below should be promoted to confirmation evidence.

## Results

| Asset | Source faces | Actual candidate faces at requested 30 / 50 / 70% | One-ULP candidates | Eligible QEM pairs | Eligible meshoptimizer pairs |
|---|---:|---|---:|---:|---:|
| AnisotropyBarnLamp | 10,203 | 3,061 / 5,101 / 7,143 | 0 / 3 | 0 | 0 |
| DiffuseTransmissionTeacup | 28,184 | 8,456 / 14,092 / 19,728 | 0 / 3 | 0 | 0 |
| GlassBrokenWindow | 987 | 381 / 491 / 569 (38.6 / 49.7 / 57.6%) | 3 / 3 | 0 | 2 |
| GlassHurricaneCandleHolder | 4,126 | 1,234 / 2,062 / 2,888 | 3 / 3 | 2 | 3 |
| MaterialsVariantsShoe | 22,700 | 6,810 / 11,350 / 15,890 | 3 / 3 | 3 | 3 |
| PotOfCoals | 18,223 | 5,467 / 9,111 / 12,757 | 3 / 3 | 0 | 0 |
| SpecularSilkPouf | 81,280 | 24,374 / 40,640 / 56,896 | 3 / 3 | 2 | 3 |

Among the seven eligible QEM pairs, ManyMesh strictly lost on all five image
metrics in six and had a mixed result in one. Among the eleven eligible
meshoptimizer pairs, it strictly lost on all five image metrics in nine and
strictly won on all five in two. Both wins were GlassBrokenWindow at 49.7% and
57.6% retention. That input has only 987 source triangles, the hierarchy missed
the requested 30% and 70% cuts, and no QEM comparison passed the eligibility
gate. It is a narrow development-pool exception, not evidence of generalization
or a competitive method. The other eligible comparisons did not show a broad
quality advantage over the controls.

The QEM exclusion on GlassBrokenWindow is specific and reproducible: the
`fast-simplification` QEM control was asked for each candidate's exact face
count with `preserve_border=True`, but returned 859 faces for all three cuts
(381, 491, and 569 faces). Those rows are therefore not equal-face comparisons;
the recorded QEM image scores are diagnostic only and were not counted as wins
or losses. The two eligible wins above are against meshoptimizer only.

The initial exact-edge rule accepted only three of the 21 cuts, all from
GlassHurricaneCandleHolder. The retrospective one-ULP rule accepted 15 of 21.
AnisotropyBarnLamp still fails the manifold/orientation check at every cut;
DiffuseTransmissionTeacup still fails the boundary-curve rule; the other
one-ULP candidates have no topology error. Passing this geometric eligibility
check does not imply that an asset is licensed for redistribution or suitable
for a confirmation set. The model binaries are not committed.

## Interpretation and next decision

This screen corrects the reference to the original source mesh, but it does not
repair the underlying research case. It is still a small, reused development
pool; the boundary tolerance was chosen retrospectively; the view set is fixed;
the CPU renderer is not a phone GPU; and no timing, temporal, user-preference,
or upscaler result was measured. Image metrics are complementary and do not
establish subjective perceptual quality. Do not use this screen to claim a
SIGGRAPH contribution or a general silhouette-error law.

The next method gate remains a faithful matched-face reproduction of
Hasselgren et al.'s appearance-driven simplification on independently cleared
assets and held-out views. Only an improvement that survives QEM, meshoptimizer,
the differentiable baseline, and the actual AA/upscaling pipeline justifies a
constrained-DAG study. The [prior-art screen](../../docs/manymesh/siggraph-prior-art-screen-20261123.md)
records what was and was not read; it is a verification map, not a novelty
verdict.

## Reproduction and provenance

The compact [JSON summary](khronos_equal_face_quality_screen_20261123.json)
records all candidate and eligible-control aggregate image metrics, paired
deltas, source hashes, protocol hashes, and hashes of the raw receipts. Full
per-view receipts and source geometry remain in ignored `out/` paths; they are
not included in the repository. The pinned Khronos source revision and asset
credit/license review are in the
[candidate screen](../../docs/manymesh/confirmation-asset-screen-20261123.md).
The initial strict-run protocol is preserved as
[Markdown](KHRONOS_QUALITY_SCREEN_PROTOCOL_20261123.md) and
[JSON](khronos_quality_screen_protocol_20261123.json). The JSON summary also
hashes the scorer and its local Python dependencies, the
[source extractor](extract_static_gltf_geometry.py), the
[PLY adapter](adapt_position_ply.py), and the vendored meshoptimizer helper.
The recorded package versions are in the
[environment receipt](khronos_quality_screen_environment_20261123.json); wheel
hashes and a lockfile were not saved.
The dirty research source used for the `mmgeo` executable is identified by its
binary and `main.cpp` hashes in the JSON. Its source delta is available as the
[compressed mmgeo source patch](current_mmgeo_source_patch_20261123.zip),
SHA-256 `60eace026d30a9615b5016a607ede5bef6d09f365c0bf9c789f6e06f323c1948`.
The archive contains the text patch with SHA-256
`e22a1a9724dd2c69c7d1baefd4248b36f067aad4f1f4e1f396c9c075b5259ac1`. The
recorded parent revision is `2d417cacdeb545a13e6bfb7192310191e60670d6`; the
original compiler version and build command were not archived, so a bit-identical
binary rebuild has not been demonstrated.

From the repository root, with the isolated research dependencies and generated
cuts present:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/manymesh-research-pydeps-20261123').Path
python tools/mmtrain/score_mmgeo_obj_diagnostic_controls.py `
  --source-obj out/khronos-curated-screen-20261123/GlassHurricaneCandleHolder/geometry.obj `
  --cut-dir out/khronos-quality-screen-20261123/GlassHurricaneCandleHolder/scoring_adapter `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out out/khronos-quality-screen-20261123/GlassHurricaneCandleHolder/reproduced `
  --geometric-boundary-tolerance-ulp 1
```

Repeat for each asset listed in the JSON summary. The
[scorer](score_mmgeo_obj_diagnostic_controls.py) and all local support modules
are included. This command reproduces one asset's follow-up score; the strict
and one-ULP raw receipt hashes in the JSON identify the original runs. The
mmgeo binary came from this dirty research build; it is not identical to a clean
public release build.
