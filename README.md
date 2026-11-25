# ManyMesh

ManyMesh is a Filament-based research prototype for mesh level of detail
(LOD). It studies the image-quality and rendering-cost effects of simplified
geometry. **It is not a validated mobile renderer, compression system, or
SIGGRAPH-ready method.**

## Research question

Can offline optimization improve a cluster-DAG mesh after a specified
antialiasing or upscaling pipeline, at matched face count and complete cost,
without breaking topology or cluster boundaries? This remains an experiment,
not a novelty claim. Differentiable mesh fitting and adaptive geometry LOD have
close prior art; see the [prior-art audit](docs/manymesh/siggraph-prior-art-screen-20261123.md).

![Matched-face image-quality comparison of ManyMesh against QEM and meshoptimizer.](docs/manymesh/polyhaven-quality-metrics.svg)

*Positive values favor ManyMesh; negative values favor the control. Metrics use
their native units. Primary intervals are familywise 95% simultaneous
intervals over 16 source groups and 21 models. LPIPS is a post-hoc supplement
on the same cohort. See the [protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md),
[multiplicity audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md),
and [LPIPS supplement](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md).*

## Measured snapshots

- **Matched geometry quality:** 21 Poly Haven models, 24 views each, rendered
  at 640 × 360 on Intel Iris Xe / D3D12. At 50% face retention, ManyMesh lost
  to border-preserving QEM and meshoptimizer across the primary image metrics,
  both without AA and with 4× MSAA.
- **Silhouette attribution:** In the same 21-model cohort, XOR regions contained 31.0% of squared grayscale
  error without AA and 16.3% with 4× MSAA. The earlier 68.3% Monkey result used
  a DAG cut, not the source mesh, as reference.
- **CPU silhouette fit:** On two reused Khronos assets, Mitsuba lowered training
  loss on an Ubuntu 24.04 hosted runner but worsened LDR-FLIP on 24 reserved
  camera/scale pairs: GlassHurricaneCandleHolder PSNR +0.0429 dB;
  MaterialsVariantsShoe −0.0920 dB. This is not an asset-held-out or final-AA
  result. [Report](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md).
- **Instance raster time:** With 10,000 BarramundiFish instances at 1280 × 720
  on Iris Xe / D3D12 / 4× MSAA, coarser stock meshoptimizer geometry reduced
  raster time from 26.155 ms to 6.657 ms (3.93×). This is not a ManyMesh or
  complete-frame win.

See the full [silhouette attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md),
[Monkey reference audit](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md),
and [instance report](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Evidence status

| Works in measured scope | Does not work in tested scope | Not measured |
|---|---|---|
| Fixed-view desktop quality and topology audits; 21-model post-hoc LPIPS; three-scene moving-camera LPIPS/temporal diagnostics; 10,000-instance raster-time diagnostic. | Current ManyMesh cuts lose to matched-face controls. Tested decoder, contour, and CPU projective-silhouette variants have no repeatable matched-control win. | Phone performance, power, equal-complete-frame-time comparison with MSAA/SMAA/upscaling, an asset-held-out optimized-method win, user preference, and validated temporal-quality gains. |

These labels describe only the listed experiments. The LPIPS supplement reuses
an already-scored cohort; the 30-model confirmation pool is frozen but unscored.
Desktop measurements do not establish mobile performance.

## Next gate

The CPU full-RGB feasibility fit completed on two reused assets and uploaded
raw results, but their metrics have not been audited; no quality conclusion is
available yet ([latest run](https://github.com/new-tonAA/ManyMesh/actions/runs/45640186280)).
The separate frozen nvdiffmodeling placement control still requires CUDA and
has not run. The earlier CPU silhouette fit had mixed held-out-view results;
it does not test the final AA pipeline or asset generalization. See the
[experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md), [matched inputs](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md),
and [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

The hosted Windows/MSVC presubmit ran `test_manymesh.exe` (94 passed, 1
skipped). Smart App Control still blocks the unsigned executable on this
laptop; GPU `compute_test` and CUDA fitting remain unrun. [CI run](https://github.com/new-tonAA/ManyMesh/actions/runs/45622515351).

## Research documents

- [Current research status](MANYMESH.md)
- [SIGGRAPH 2027 direction and evidence gate](SIGGRAPH_2027_DIRECTION.md)
- [Research roadmap](MANYMESH_RESEARCH_ROADMAP.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Learned-LOD research](MANYMESH_LEARNED_LOD_RESEARCH.md)
- [Filament documentation](filament/README.md)
