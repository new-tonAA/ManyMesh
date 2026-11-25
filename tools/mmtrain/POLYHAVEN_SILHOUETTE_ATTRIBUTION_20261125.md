# Post-hoc silhouette error attribution across 21 models

Completed 2026-11-25. This is a diagnostic on the already-scored Poly Haven cohort, not independent confirmation or a new method result.

## Measurement

For each of the 21 frozen meshes, compare the candidate render with the full-source reference at the same 24 perspective view-distance pairs. The reference is rendered at 2x resolution with 4x MSAA and linear box resolve. Candidate renders use native sampling or 4x MSAA at 640 x 360. All geometry was rechecked against the frozen face-count and directed-boundary receipt before rendering.

Define the contour-error region as the binary coverage XOR (`gray > 0`) between the candidate and resolved source reference. The reported error share is the sum of squared **linear grayscale** render differences inside this XOR region divided by total squared grayscale error. Pixel shares and error shares are pooled over all 24 views within each asset. We then average assets within each of the 16 pre-existing source-collection groups and bootstrap those groups 10,000 times (seed 20261125).

This is a geometric attribution diagnostic, not a perceptual metric. The cohort had already been examined for quality, the rendering is flat grayscale and fixed-view, and the grouping does not make it independent confirmation.

## Results

No source group assigns more than half of total squared image error to silhouette-XOR pixels in any arm or sampling mode. For ManyMesh, the group-mean share is 31.0% (95% group-bootstrap CI 27.4%–34.8%) with native sampling, falling to 16.3% (13.7%–19.1%) with 4x MSAA. The median asset's XOR region covers 0.171% of native pixels and 0.084% with 4x MSAA. Thus contour disagreement is overrepresented in the error, but it is not the majority of image error under this protocol; MSAA reduces its contribution substantially.

| Candidate | Native error share, group mean (95% CI) | 4x MSAA error share, group mean (95% CI) | Groups above 50%, native / 4x |
|---|---:|---:|---:|
| ManyMesh | 31.01% (27.37%–34.84%) | 16.25% (13.66%–19.09%) | 0 / 0 |
| Border-preserving QEM | 22.32% (19.20%–25.50%) | 4.56% (3.56%–5.66%) | 0 / 0 |
| meshoptimizer LockBorder | 26.44% (22.37%–30.26%) | 5.66% (4.61%–6.65%) | 0 / 0 |

The screen's matched-face image-quality result still favors QEM and meshoptimizer over ManyMesh. The energy decomposition below shows why contour share alone is insufficient: 4x MSAA removes 38.8% of ManyMesh's native total squared error, versus 58.0% for QEM and 67.1% for meshoptimizer. For ManyMesh, 20.7 percentage points of native total error are removed inside the XOR mask and 18.1 points outside it. The component intervals are descriptive, not multiplicity-corrected.

### What 4x MSAA removes

The table below decomposes each arm's change in pooled squared error after enabling 4x MSAA. Each component is normalized by that arm's native total error; positive values are reductions, negative values are increases. The XOR mask is computed separately for each mode, so this is a descriptive partition rather than a tracked-pixel causal attribution. Intervals resample the 16 source groups; the three related intervals are descriptive and are not multiplicity corrected.

| Candidate | Total error removed | XOR-region error removed | Non-XOR error removed |
|---|---:|---:|---:|
| ManyMesh | 38.8% (33.0%–45.9%) | 20.7% (17.7%–23.9%) | 18.1% (13.1%–23.5%) |
| Border-preserving QEM | 58.0% (52.0%–64.2%) | 20.4% (17.4%–23.6%) | 37.5% (33.2%–41.9%) |
| meshoptimizer LockBorder | 67.1% (61.3%–72.6%) | 24.7% (20.8%–28.3%) | 42.4% (37.3%–46.9%) |

### Per-asset error share

Each value is the pooled XOR-region share of squared error. These per-asset values expose the spread hidden by the group mean.

| Asset | ManyMesh native | ManyMesh 4x MSAA | QEM 4x MSAA | meshoptimizer 4x MSAA |
|---|---:|---:|---:|---:|
| crystalline_iceplant | 36.3% | 6.8% | 7.4% | 8.1% |
| rock_09 | 18.0% | 10.5% | 1.8% | 1.8% |
| food_apple_01 | 42.3% | 20.0% | 4.7% | 7.3% |
| Ottoman_01 | 25.8% | 14.4% | 3.7% | 3.7% |
| SchoolChair_01 | 35.2% | 23.4% | 8.5% | 9.1% |
| Sofa_01 | 23.1% | 16.0% | 8.1% | 6.1% |
| moon_rock_02 | 21.0% | 11.1% | 2.8% | 2.9% |
| moon_rock_03 | 29.0% | 17.9% | 2.1% | 3.1% |
| moon_rock_05 | 19.9% | 11.0% | 1.3% | 1.4% |
| moon_rock_06 | 23.3% | 13.6% | 1.6% | 1.9% |
| food_pears_asian_01 | 43.5% | 22.5% | 3.7% | 6.7% |
| lemon | 44.4% | 29.6% | 3.3% | 4.4% |
| Megaphone_01 | 29.9% | 19.1% | 7.1% | 7.3% |
| drain_cleaner | 32.0% | 15.7% | 5.5% | 5.9% |
| dustpan | 16.0% | 8.8% | 3.9% | 6.3% |
| antique_ceramic_vase_01 | 35.7% | 18.8% | 3.0% | 6.4% |
| brass_vase_01 | 30.5% | 11.2% | 4.9% | 7.3% |
| bronze_shark_statue | 29.2% | 13.7% | 4.3% | 5.2% |
| bronze_whale_statue | 33.8% | 16.7% | 5.6% | 8.9% |
| bull_head | 24.5% | 12.2% | 2.1% | 3.9% |
| concrete_cat_statue | 25.4% | 13.3% | 2.6% | 3.5% |

## Reproducibility and limits

The 3,024 candidate/view/mode XOR-area values exactly match the frozen per-view quality metrics. This verifies the rerendered coverage masks; the squared-error attribution itself is newly computed. Source metrics SHA-256: `e3c15f56f13ea6c0b8f21a131f1d76ed648884e8ff69aca72346a0620e4fd9ad`. Diagnostic script SHA-256: `127522519aaa4bfb1907536efa6c0678a9ee1421d422f9d20fffdef170985690`. Summary script SHA-256: `8f343086cc036b0a6620abfbc73d33ee5eaff2642ad2d98ac1666ecd93bbf737`. Receipt SHA-256: `0cf8c53cb41345591aafe4f5baf05b6d86af2b45f05ea3a84898130dbe1ec30a`.

The historical single-view Monkey result reported 68.3% using a DAG cut as reference. This multi-model screen instead uses the original source reference, 24 views per asset, flat grayscale shading, and the explicitly defined XOR mask. The values are not directly interchangeable. The new diagnostic does not invalidate that individual measurement; it shows that it should not be presented as a general property.

The [frozen cohort manifest](polyhaven_quality_cohort_20261124.json) lists the per-asset geometry-export paths. These derived exports and source meshes are not vendored; regenerate them from the licensed CC0 assets using the [topology screen](POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md) and [matched-face export protocol](POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md). The checked-in attribution receipt and [primary per-view metrics](polyhaven_quality_metrics_20261124.json) suffice to recompute the reported tables without rerendering. Replaying the renderer requires the regenerated geometry exports.

No materials, shadows, temporal accumulation, mobile device, equal-frame-time comparison, or human preference were measured. The analysis does not establish how perceptual metrics such as LDR-FLIP or LPIPS partition error spatially.

Reproduce from the repository root with the recorded Python dependencies:

```powershell
$env:PYTHONPATH = 'out/manymesh-research-pydeps-20261123;out/geometry-refinement-pilot/deps;out/geometry-refinement-pilot/deps/wgpu'
python tools/mmtrain/analyze_polyhaven_silhouette_share.py `
  --out tools/mmtrain/polyhaven_silhouette_attribution_20261125.json
python tools/mmtrain/summarize_polyhaven_silhouette_share.py `
  --receipt tools/mmtrain/polyhaven_silhouette_attribution_20261125.json `
  --report tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md
```

Mask-parity audit: 3024/3024 exact matches. The full machine-readable per-asset and per-view receipt is checked in at [polyhaven_silhouette_attribution_20261125.json](polyhaven_silhouette_attribution_20261125.json). Raw image buffers were not retained.
