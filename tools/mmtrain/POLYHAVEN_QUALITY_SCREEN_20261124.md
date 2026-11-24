# Poly Haven matched-face image-quality screen

Completed 2026-11-24. This is a fixed-view desktop geometry-quality
screen, not a SIGGRAPH contribution or mobile-performance result.
All 21 models were selected by source topology and exact-face/boundary
eligibility before any image quality was scored. No model was used for
training or parameter tuning. The 21 unique source meshes form 16
collection groups for uncertainty estimates.

## Protocol

- 21 CC0 Poly Haven models in six classes, each at an exact common face
  count near 50% retention. ManyMesh, border-preserving QEM, and
  meshoptimizer LockBorder all preserve the source directed boundary and
  pass the recorded triangle/edge topology audit.
- Iris Xe, D3D12, 640x360 offscreen rasterization. The reference is the
  original source at 2x resolution with 4x MSAA and a linear box resolve.
  Each model uses 12 fixed perspective directions at two distances
  (24 view-distance pairs). Candidate renders use native sampling and
  4x MSAA.
- Reported image metrics are LDR-FLIP (67 pixels/degree), pooled-MSE
  PSNR, SSIM, and binary silhouette XOR. Sampled bidirectional surface
  distance and normal consistency are also recorded.
- Paired uncertainty resamples the 16 connected source-collection groups
  10,000 times. All individual model results are listed below and in the
  machine-readable receipt.

## Result

**Across the cohort, group-mean ManyMesh quality was worse than both
deterministic controls on all four image metrics in both sampling
modes.** The paired 95% group-bootstrap intervals exclude zero for every
metric. Four of 16 metric/control/mode comparisons show one group win
against QEM; the other 12 show none. ManyMesh had no wins against
meshoptimizer. This closes this fixed 50% ManyMesh configuration as a
quality-improving method on this eligible cohort.

Delta is ManyMesh minus the named control. Lower FLIP and silhouette XOR
are better; higher PSNR and SSIM are better. Therefore positive FLIP/XOR
and negative PSNR/SSIM deltas favor the control.

| Candidate mode | Control | Metric | Mean paired delta | 95% group-bootstrap CI | ManyMesh wins / 16 groups |
|---|---|---:|---:|---:|---:|
| native | qem_preserve_border | flip | +0.001465 | [+0.000924, +0.001974] | 1/16 |
| native | qem_preserve_border | psnr_db | -2.097678 | [-2.583499, -1.615749] | 0/16 |
| native | qem_preserve_border | ssim | -0.003263 | [-0.004346, -0.002110] | 1/16 |
| native | qem_preserve_border | silhouette_xor_fraction | +0.000354 | [+0.000262, +0.000448] | 0/16 |
| native | meshoptimizer_lock_border | flip | +0.002072 | [+0.001597, +0.002539] | 0/16 |
| native | meshoptimizer_lock_border | psnr_db | -2.270253 | [-2.692075, -1.831514] | 0/16 |
| native | meshoptimizer_lock_border | ssim | -0.005155 | [-0.006288, -0.003977] | 0/16 |
| native | meshoptimizer_lock_border | silhouette_xor_fraction | +0.000315 | [+0.000240, +0.000392] | 0/16 |
| msaa4 | qem_preserve_border | flip | +0.001581 | [+0.000984, +0.002122] | 1/16 |
| msaa4 | qem_preserve_border | psnr_db | -4.454503 | [-5.369003, -3.455207] | 0/16 |
| msaa4 | qem_preserve_border | ssim | -0.003170 | [-0.004252, -0.002047] | 1/16 |
| msaa4 | qem_preserve_border | silhouette_xor_fraction | +0.000387 | [+0.000301, +0.000477] | 0/16 |
| msaa4 | meshoptimizer_lock_border | flip | +0.002290 | [+0.001766, +0.002798] | 0/16 |
| msaa4 | meshoptimizer_lock_border | psnr_db | -5.396364 | [-6.241136, -4.462515] | 0/16 |
| msaa4 | meshoptimizer_lock_border | ssim | -0.005169 | [-0.006307, -0.004025] | 0/16 |
| msaa4 | meshoptimizer_lock_border | silhouette_xor_fraction | +0.000378 | [+0.000299, +0.000457] | 0/16 |

## Per-model image deltas

Each cell is the mean LDR-FLIP delta (ManyMesh minus control) across the
model's 24 view-distance pairs; lower is better.

| Asset | Class | Faces | Native vs QEM | 4x MSAA vs QEM | Native vs meshoptimizer | 4x MSAA vs meshoptimizer |
|---|---|---:|---:|---:|---:|---:|
| crystalline_iceplant | botanical | 6,546 | +0.000041 | +0.000046 | +0.000054 | +0.000099 |
| rock_09 | rock | 6,208 | +0.001813 | +0.002009 | +0.001945 | +0.002191 |
| food_apple_01 | food | 3,506 | +0.001471 | +0.001445 | +0.002403 | +0.002487 |
| Ottoman_01 | furniture | 2,120 | +0.001211 | +0.001232 | +0.002930 | +0.003196 |
| SchoolChair_01 | furniture | 2,536 | +0.001535 | +0.001790 | +0.001710 | +0.001839 |
| Sofa_01 | furniture | 2,051 | -0.001111 | -0.001286 | +0.000563 | +0.000568 |
| moon_rock_02 | rock | 1,652 | +0.002050 | +0.002058 | +0.002273 | +0.002418 |
| moon_rock_03 | rock | 2,798 | +0.002206 | +0.002351 | +0.002096 | +0.002302 |
| moon_rock_05 | rock | 4,924 | +0.001946 | +0.002041 | +0.002025 | +0.002248 |
| moon_rock_06 | rock | 3,460 | +0.002098 | +0.002233 | +0.001999 | +0.002195 |
| food_pears_asian_01 | food | 6,286 | +0.001371 | +0.001502 | +0.002223 | +0.002533 |
| lemon | food | 2,006 | +0.003100 | +0.003164 | +0.003731 | +0.003914 |
| Megaphone_01 | tools | 7,906 | +0.000921 | +0.000923 | +0.002008 | +0.002142 |
| drain_cleaner | tools | 2,168 | +0.000821 | +0.000910 | +0.002003 | +0.002348 |
| dustpan | tools | 2,164 | +0.001218 | +0.001332 | +0.001311 | +0.001464 |
| antique_ceramic_vase_01 | decor | 4,704 | +0.002753 | +0.002971 | +0.002881 | +0.003100 |
| brass_vase_01 | decor | 10,720 | +0.000652 | +0.000817 | +0.000888 | +0.001134 |
| bronze_shark_statue | decor | 3,666 | +0.001304 | +0.001683 | +0.001380 | +0.001792 |
| bronze_whale_statue | decor | 1,908 | +0.000973 | +0.001156 | +0.001295 | +0.001523 |
| bull_head | decor | 8,574 | +0.002607 | +0.002993 | +0.002900 | +0.003376 |
| concrete_cat_statue | decor | 5,974 | +0.003009 | +0.003217 | +0.003481 | +0.003823 |

## Limits and reproducibility

The cohort is conditioned on passing the static source topology and
matched-face boundary gates; it does not represent every mesh. The
renderer and views are fixed and desktop-only. This is not an equal-time
comparison. The pinned scorer did not emit the predeclared coverage-MAE
field, so it is unavailable; it was not reconstructed from other metrics.
LPIPS, temporal behavior, GPU frame time, mobile-device performance, and
human preference were not measured.
The mmgeo executable is pinned by SHA-256, but its exact modified source
delta was not recovered; a clean source rebuild has not been verified.
Treat this as an auditable binary experiment, not a fully reproducible
source build.

The [frozen cohort](polyhaven_quality_cohort_20261124.json), complete
[per-view metrics and geometry metrics](polyhaven_quality_metrics_20261124.json),
and [runner receipt](polyhaven_quality_screen_20261124.json) preserve the
protocol, hashes, commands, all per-asset measurements, and raw receipt
hashes. Raw renderer receipts remain local under
`out/polyhaven-quality-screen-20261124/`.
The source geometry screen and fixed-face eligibility reports are
[here](POLYHAVEN_CANDIDATE_TOPOLOGY_20261124.md) and
[here](POLYHAVEN_MATCHED_FACE_EXPANSION_20261124.md).
