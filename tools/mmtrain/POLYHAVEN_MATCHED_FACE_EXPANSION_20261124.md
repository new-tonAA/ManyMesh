# Poly Haven matched-face cohort expansion

Completed 2026-11-24. This report records a pre-score source and geometry
eligibility screen. It contains no image-quality rankings.

## Frozen source screen

The selector froze 56 additional Poly Haven models from six broad classes using
a saved catalog snapshot (SHA-256
`4639038ef32946ec562b03a56086c53c8edde0179a8d7140ffd79232ea4a0c23`). It
excluded the earlier 20 slugs and selected models by type, class, catalog
polygon-count range, and ascending slug. No render or quality data influenced
selection. All 56 API acquisitions succeeded. The declared glTF and binary
buffer sizes and MD5 checksums matched the live file records; their SHA-256
hashes and credits are in the [source receipt](polyhaven_expansion_topology_20261124.json).

The static source topology audit passed 46/56 models. Ten sources failed on
duplicate or degenerate faces or nonmanifold edges. This audit welds exactly
coincident positions, allows open boundaries, and does not test visual
correctness, near-coincident seams, or self-intersections. Four of the selected
rock assets are variations from the same Moon collection; they remain visible
as related models and are grouped for uncertainty estimates.

The saved catalog `files_hash` value differed from the live API value for all
56 selected records. It was not used as a file-integrity check; downloaded
geometry was checked against the live API's per-file size and MD5 values. The
report records both catalog and live metadata so this source-snapshot mismatch
is visible.

## Fixed 50% eligibility screen

For each of the 46 source-topology passes, the pinned ManyMesh build generated
one DAG cut at a nominal 50% face budget (`cluster-tris=128`, `dag-group=4`).
Its actual face count set the exact target for border-preserving QEM and
meshoptimizer LockBorder. A pair was eligible only when all three outputs had
the exact same face count, passed the triangle and edge topology checks, and
preserved the source's directed boundary under a one-float32-ULP endpoint
tolerance. The full-source mesh remains the image-quality reference.

| Gate | Eligible models |
|---|---:|
| ManyMesh cut alone | 42 / 46 |
| QEM control alone | 25 / 46 |
| meshoptimizer control alone | 28 / 46 |
| All three controls at identical faces with valid boundaries | 18 / 46 |

The other 28 assets are ineligible for this comparison and are not ranked by
image quality. The [raw matched-face receipt](polyhaven_matched_face_expansion_20261124.json)
retains each output face count, boundary result, topology error, command,
source hash, build hash, and script hash. Model files and geometry exports
remain in the local `out/` directory.

The 18 new eligible models are:

| Class | Asset | Source faces | Faces in each control | Retention |
|---|---|---:|---:|---:|
| Furniture | Ottoman_01 | 4,240 | 2,120 | 50.00% |
| Furniture | SchoolChair_01 | 5,072 | 2,536 | 50.00% |
| Furniture | Sofa_01 | 4,101 | 2,051 | 50.01% |
| Rock | moon_rock_02 | 3,304 | 1,652 | 50.00% |
| Rock | moon_rock_03 | 5,598 | 2,798 | 49.98% |
| Rock | moon_rock_05 | 9,850 | 4,924 | 49.99% |
| Rock | moon_rock_06 | 6,920 | 3,460 | 50.00% |
| Food | food_pears_asian_01 | 12,572 | 6,286 | 50.00% |
| Food | lemon | 4,012 | 2,006 | 50.00% |
| Tools | Megaphone_01 | 15,814 | 7,906 | 50.00% |
| Tools | drain_cleaner | 4,338 | 2,168 | 49.98% |
| Tools | dustpan | 4,332 | 2,164 | 49.95% |
| Decor | antique_ceramic_vase_01 | 9,408 | 4,704 | 50.00% |
| Decor | brass_vase_01 | 21,440 | 10,720 | 50.00% |
| Decor | bronze_shark_statue | 7,334 | 3,666 | 49.99% |
| Decor | bronze_whale_statue | 3,816 | 1,908 | 50.00% |
| Decor | bull_head | 17,148 | 8,574 | 50.00% |
| Decor | concrete_cat_statue | 11,950 | 5,974 | 49.99% |

Combining these with the three eligible models from the initial screen produced
21 unique source-geometry hashes across six classes. The three initial models
were also selected and matched before image scoring. Their [eligibility receipt](polyhaven_matched_face_20261124.json)
marks image quality as unscored. Shared source collections are treated as
clusters, leaving 16 groups for uncertainty estimates.

## Reproduction and next result

The selector and acquisition scripts are
[select_polyhaven_expansion.py](select_polyhaven_expansion.py) and
[screen_polyhaven_expansion.py](screen_polyhaven_expansion.py). The fixed-face
preflight is [screen_polyhaven_matched_faces.py](screen_polyhaven_matched_faces.py).
It uses the archived `mmgeo` binary SHA-256
`8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e`; the
build and source pin are in `out/cmake-cut-audit/source-pin.json`. Run from the
repository root with the local research dependencies:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/geometry-refinement-pilot/deps').Path
python tools/mmtrain/screen_polyhaven_matched_faces.py `
  --topology-report tools/mmtrain/polyhaven_expansion_topology_20261124.json `
  --mmgeo out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe `
  --out-dir out/polyhaven-matched-face-expansion-20261124 `
  --report tools/mmtrain/polyhaven_matched_face_expansion_20261124.json
Remove-Item Env:PYTHONPATH
```

The resulting 21-model confirmation cohort was scored once at equal face count
with FLIP, PSNR, SSIM, silhouette XOR, and sampled surface/normal metrics. The
[quality report](POLYHAVEN_QUALITY_SCREEN_20261124.md) gives all model results
and the paired collection-group intervals. No image score was used to choose
the cohort or alter the comparison settings.
