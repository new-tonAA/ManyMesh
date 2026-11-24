# Monkey Source-Reference Diagnostic — 2026-11-25

## Result

This exploratory re-scoring compares three frozen ManyMesh cuts against the
original 15,744-face Monkey OBJ, at the exact same face counts as QEM and
meshoptimizer controls. The ManyMesh cut loses to eligible controls on the
reported image metrics at every tested budget. At the 70% request, QEM produced
duplicate geometric triangles and is ineligible; it is excluded from quality
ranking.

| Requested retention | ManyMesh faces | Silhouette-XOR pixels | Silhouette share of squared image error | ManyMesh PSNR minus QEM | ManyMesh PSNR minus meshoptimizer |
|---:|---:|---:|---:|---:|---:|
| 30% | 4,724 | 0.145% | 34.75% | -3.34 dB | -5.66 dB |
| 50% | 7,870 | 0.070% | 25.84% | -5.18 dB | -7.39 dB |
| 70% | 11,020 | 0.034% | 25.88% | Ineligible: duplicate geometric triangles | -9.51 dB |

At all three budgets, eligible controls also have better LDR-FLIP, SSIM,
silhouette XOR, and coverage MAE than the ManyMesh candidate. See per-view raw
values and topology/boundary checks in the [JSON receipt](monkey_source_reference_diagnostic_20261125/receipt.json).

## Protocol and provenance

- Reference: `assets/models/monkey/monkey.obj`, SHA-256
  `7b754119aa286ff618b9ac30038c8aa9a093e2820242913728c8b20d8000ca88`, 7,958
  vertices and 15,744 faces. This is the original source, not a full-detail DAG
  cut.
- Views and rendering: eight orthographic views, 192x192, four samples per
  pixel, FLIP at 67 pixels per degree, 10,000 sampled surface points per
  direction. Metrics are LDR-FLIP, PSNR, SSIM, silhouette XOR, coverage MAE,
  sampled Chamfer distance, 95th-percentile distance, and normal consistency.
- Controls: fast-simplification QEM and meshoptimizer whole-mesh LockBorder,
  both requested at the candidate's exact face count.
- Candidate inputs: the frozen DAG and PLY files are in
  [`fixtures/monkey-source-reference-screen-20261123/`](fixtures/monkey-source-reference-screen-20261123/).
  The original generator binary is unavailable and its hash is not recorded;
  the receipt records this limitation. The scoring script does not regenerate
  those PLYs.
- Boundary check: exact directed-edge comparison failed for the cuts. A
  retrospective one-to-one oriented boundary-vertex tolerance of 0.52 float32
  ULP at normalized unit radius matched all 168 edges. The maximum mapped vertex
  displacement was `6.19e-8`; this tolerance was selected after the candidates
  existed, so the check is exploratory rather than a preregistered gate.
- Software versions, script and helper hashes, input hashes, per-view metrics,
  and control eligibility are recorded in the receipt. No GPU/CPU timing,
  power, mobile-device measurement, LPIPS, or temporal metric was collected;
  the host CPU model was not recorded. Control simplification timings in the
  receipt are incidental and are not used as performance evidence.

## Reproduction

From the repository root, using the recorded Python environment and Node.js
version (see the receipt):

```powershell
$env:PYTHONPATH = "out/manymesh-research-pydeps-20261123"
python tools/mmtrain/score_mmgeo_obj_diagnostic_controls.py `
  --source-obj assets/models/monkey/monkey.obj `
  --cut-dir tools/mmtrain/fixtures/monkey-source-reference-screen-20261123 `
  --out out/monkey-source-reference-reproduction `
  --views 8 --size 192 --seed 20261123 `
  --geometric-boundary-tolerance-ulp 0.52 `
  --score-ineligible-controls
```

The output receipt is expected to match the checked-in measurements within
runtime and floating-point variation. The frozen inputs make scoring
reproducible; they do not make the missing candidate-generation step
reproducible.

## Interpretation

This is one asset and an exploratory diagnostic, not held-out evidence. The
silhouette-error shares differ from the historical 68.3% figure, which used a
single 960x720 view and an 11,250-face DAG cut as its reference. Neither result
supports a general claim that a fixed fraction of image error comes from
silhouettes. These results reject the tested cuts against the stated controls;
they do not reject other silhouette-aware or reconstruction-conditioned
methods. The broader status and next research gate are in [`MANYMESH.md`](../../MANYMESH.md).
