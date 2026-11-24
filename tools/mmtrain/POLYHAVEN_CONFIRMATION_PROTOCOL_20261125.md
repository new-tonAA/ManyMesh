# Poly Haven confirmation protocol

Frozen 2026-11-25 before image-quality scoring. The method configuration is still pending, so this protocol does not authorize scoring yet.

## Frozen inputs

- 30 licensed Poly Haven CC0 assets, 25 source-family uncertainty groups, and 9 categories.
- ManyMesh, border-preserving QEM, and meshoptimizer inputs have the same per-asset face count (49%-51% source retention). The full source mesh is the image reference.
- Source files, matched-face receipts, OBJ exports, and this manifest are hash-pinned. Geometry-only preflight retained every asset; it did not render or score images.

## Frozen views and rendering

- Per-asset fitting may use the 32 frozen training cameras at 128x128 (rendered at 256x256); evaluation uses 24 reserved view-distance pairs at 640x360. Closest training/evaluation direction: 16.81 degrees.
- The full source reference is rendered at 1280x720 with 4x MSAA, then linearly box-resolved to 640x360. Candidates are evaluated with native rasterization and 4x MSAA, under identical lighting.
- This is matched-face desktop image-quality evidence. It is not an equal-time, mobile, or temporal comparison.

## Metrics and decision rule

- Primary: LDR-FLIP at 67 pixels/degree. Guardrails: pooled-MSE PSNR, SSIM, and silhouette XOR. LPIPS and sampled surface/normal distances are exploratory.
- Use paired uncertainty over the 25 source-family groups: a two-sided 95% max-|t| cluster bootstrap with 200,000 draws and seed 20261125, sharing resamples over the 16 primary metric/control/sampling endpoints.
- Under 4x MSAA, the simultaneous lower bound for LDR-FLIP improvement must exceed both frozen margins: QEM 0.000790368; meshoptimizer 0.001144803. Improvement is control error minus candidate error.
- The margins equal half the corresponding mean ManyMesh deficit in the previously examined 21-model development cohort. They are project-specific challenge thresholds, not universal perceptual just-noticeable differences.
- No supported simultaneous regression is allowed on the three guardrails. A confirmatory pass requires valid outputs for all 30 assets and all frozen topology, boundary, and face-count checks. Keep every failure visible; an incomplete run cannot pass. Resume only the identical frozen configuration after a tooling failure, and never tune from confirmation scores.

## Current gate

Scoring remains disabled until one method configuration passes the two-asset development gate and is frozen. A candidate must be specified as a single procedure before any confirmation score is observed. Per-asset fitting on disjoint views tests this frozen procedure across assets; it does not test transfer of a cross-asset learned model.

This protocol does not establish superiority over SMAA or an upscaler, equal-frame-time quality, mobile performance, temporal stability, or human preference. Coverage MAE is unavailable in the current scorer.

## Reproduction and hashes

Run the geometry-only freeze audit (it verifies every OBJ against its source receipt and does not score images):

```powershell
python tools/mmtrain/freeze_polyhaven_confirmation_protocol.py
```

- Protocol manifest: [JSON](polyhaven_confirmation_protocol_20261125.json) (SHA-256 `301a2e0826b3980b1541a5a29f3a282bf3382a195bae267a18e5c3f5f975febc`).
- Candidate pool: [pool manifest](polyhaven_confirmation_pool_20261125.json) (SHA-256 `879fd9ac68d1116b5623ed63666595e1108cf94190f442c2253c71b043322846`); selection details are in [the report](POLYHAVEN_CONFIRMATION_POOL_20261125.md).
- Development effect source: [21-model quality report](POLYHAVEN_QUALITY_SCREEN_20261124.md) and [metric receipt](polyhaven_quality_metrics_20261124.json) (SHA-256 `e3c15f56f13ea6c0b8f21a131f1d76ed648884e8ff69aca72346a0620e4fd9ad`).
- Freeze generator SHA-256: `e4088f36e607f2779391865617bfde9aea36221842b280f9bc099ac65d833cbe`. Camera, scoring, and multiplicity-analysis source hashes are listed in the JSON manifest.
