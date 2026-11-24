# Poly Haven score replay audit

Completed 2026-11-24. This checks reproducibility of the fixed image-scoring
stage for the frozen 21-model cohort. It does not rebuild the simplification
geometry or add an independent test set.

## Frozen comparison

Re-score the same source, ManyMesh, border-preserving QEM, and meshoptimizer OBJ
exports from the [original cohort](polyhaven_quality_cohort_20261124.json),
using the original camera schedule, reference, native and 4x MSAA modes, FLIP,
PSNR, SSIM, silhouette XOR, surface metrics, D3D12 backend, and Iris Xe adapter.
Before rendering, the replay script checks the manifest hash, original receipt
hashes, scorer hash, and all 105 frozen OBJ/material file hashes. A mismatch
stops the run. The runner compares scored fields per asset; after the full
replay, each replay JSON's SHA-256 was checked against the original raw
renderer receipt.

## Result

All **21/21** asset scores reproduced exactly. Each replay JSON had the same
SHA-256 as its original raw receipt; therefore every per-view value and the
aggregate image and surface metrics were identical. Recomputing the paired
10,000-sample bootstrap with seed `20261124` produced the same group deltas and
95% intervals as the published metrics file. The negative result for the
tested ManyMesh cut is unchanged.

The environment matched the recorded run: Intel Iris Xe, D3D12, wgpu 0.33.0,
NumPy 2.3.4, scikit-image 0.25.2, and flip-evaluator 1.7. The replay runner is
`replay_polyhaven_quality_screen.py`; its SHA-256 was
`cc7b599ba62afa05b5e72530bd32c7b696c658949086441602e0f300b6e984b2`.
The full local receipt SHA-256 was
`99f78c09766b462225258abfb803dd1b7eb74d4921e74c8c783999c8582946f4`.
The checked-in [compact replay manifest](polyhaven_quality_score_replay_audit_20261124.json)
records per-asset input and output hashes and the aggregate-metric digest.
The per-asset replay JSON files and receipt are under the ignored local path
`out/polyhaven-quality-replay-audit-20261124/`.

## Limits and reproduction

This replay verifies only the scoring pipeline on the exact same geometry
exports, hardware, driver, and software. It is not an independent replication,
does not increase the number of statistical units, and does not establish
mobile, equal-time, preference, or temporal quality. The original `mmgeo`
binary hash and partial source hashes are recorded, but its exact source delta
and build command remain unrecovered; a clean geometry-generation build is
still unverified. The archived stash contains the exact pinned hashes for two
of the three modified source files. The expected hash for
`tools/mmgeo/src/main.cpp` was not found in `main`, the archive tag, the stash,
or any of the 15 reachable revisions of that path. Original source assets and
renderer receipts remain local.

```powershell
$env:PYTHONPATH = 'out/manymesh-research-pydeps-20261123;out/geometry-refinement-pilot/deps;out/geometry-refinement-pilot/deps/wgpu'
python tools/mmtrain/replay_polyhaven_quality_screen.py `
  --manifest tools/mmtrain/polyhaven_quality_cohort_20261124.json `
  --original-receipt tools/mmtrain/polyhaven_quality_screen_20261124.json `
  --original-raw-dir out/polyhaven-quality-screen-20261124 `
  --out-dir out/polyhaven-quality-replay-audit-20261124
```

The replay can resume completed assets when run again with the same manifest,
receipt, scorer, replay script, and package versions. Use a new output directory
if any of those inputs change.
