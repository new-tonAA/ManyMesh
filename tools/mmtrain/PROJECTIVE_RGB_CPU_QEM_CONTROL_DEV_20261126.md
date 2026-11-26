# CPU projective RGB fit versus exact-face QEM

Completed 2026-11-26 on the two reused development assets. This is a
development-only follow-up, not the frozen 30-model confirmation and not a
SIGGRAPH contribution claim. The original RGB screen compared only against its
meshoptimizer initializer; this adds border-preserving QEM at the same target
face count to check whether that result survives a stronger geometry baseline.

## Results

| Asset | Target faces | QEM boundary | QEM PSNR / SSIM / LDR-FLIP | Fitted PSNR / SSIM / LDR-FLIP | Fit minus QEM |
|---|---:|---|---|---|---|
| GlassHurricaneCandleHolder | 2,062 | 4 edges, preserved | 42.1788 dB / 0.996956 / 0.008627 | 40.9285 dB / 0.996722 / 0.009086 | -1.2503 dB / -0.000234 / +0.000458 |
| MaterialsVariantsShoe | 11,350 | 1,156 edges, preserved | 45.4650 dB / 0.998351 / 0.004016 | 51.0379 dB / 0.999468 / 0.001932 | +5.5729 dB / +0.001116 / -0.002084 |

Lower LDR-FLIP is better. Both QEM outputs passed the recorded exact-face and
source-boundary audit. The means were recomputed from all 24 per-view rows in
each raw QEM receipt and matched the stored means within floating-point
rounding. Fit output hashes and QEM scorer hashes also matched their receipts.

The result is mixed: QEM beats the fit on all three image measures for the
candle holder, while the fit beats QEM on all three for the shoe. These two
development assets do not support a stable advantage over QEM. **Do not advance
this meshoptimizer-initialized CPU RGB configuration to the reserved 30-model
pool.** No confirmation scores were run.

## Provenance and verification limits

- GitHub Actions run
  [45852622096](https://github.com/new-tonAA/ManyMesh/actions/runs/45852622096),
  source commit `296eed6650c10db88aa13f1af368873cde4db245`, completed successfully
  on Ubuntu 24.04 for both models.
- Fit script SHA-256: `b00100f5b2f1af8fa350386e6269795a0d52f576c41148727fd0ceb9ef02cf43`.
- QEM scorer SHA-256:
  `d38ea42ae4fa745db2272b9ac392e27505cd05f6472e4e056fab4465ed6bd2b0`.
- Source OBJ SHA-256 values remain those in the
  [CPU RGB protocol](PROJECTIVE_RGB_CPU_PROTOCOL_20261125.md). Per-asset raw
  result and QEM receipt hashes are in the
  [machine-readable receipt](PROJECTIVE_RGB_CPU_QEM_CONTROL_DEV_20261126.json).
- The first local attempt on 2026-11-26 did not complete the 20,000-sample
  surface audit: Windows NumPy raised `ArrayMemoryError`, and that WSL launch
  returned `COMMITMENT_LIMIT`. On 2026-11-27, the full independent verifier
  completed in the existing D-drive WSL environment for both downloaded fit
  artifacts. It passed their source/hash, fixed-topology, exact-face, boundary,
  surface, and per-view image-metric checks. This fit-artifact verifier audits
  the meshoptimizer initializer and RGB fit; the separate QEM scorer's raw
  receipts were re-aggregated and matched with Python's standard library.
  The workflow also now includes the verifier step, but that change has not yet
  run on a hosted workflow.

The second asset's improvement does not cancel the first asset's loss. There
are only two reused models, no family-level uncertainty estimate, and no
asset-generalization evidence here. The CPU render also does not test MSAA,
SMAA, upscaling, GPU time, mobile behavior, temporal quality, or user
preference.

## Follow-up and decision

The proposed QEM-initialized follow-up was run on 2026-11-27. It improved over
raw QEM on both assets, but the same-host comparison against the already
available meshoptimizer-initialized fit failed on MaterialsVariantsShoe. The
QEM fit lost there by 5.421 dB PSNR, 0.001038 SSIM, and 0.001950 mean LDR-FLIP.
The full development gate therefore fails. Do not score the reserved 30-model
pool with either RGB-fit initialization under this configuration. See the
[frozen protocol](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_PROTOCOL_20261127.md),
[four-arm result](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.md), and
[raw receipt](PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.json). This is a
negative result for this specific CPU fit procedure, not a test of every
render-guided simplifier or of the separate cluster-DAG hypothesis.
