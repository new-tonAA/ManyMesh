# ManyMesh research status

Updated 2026-11-25. **No SIGGRAPH-ready contribution is established.** Mobile
performance and user preference have not been measured.

## Current question

Can offline optimization improve a triangle-mesh cluster LOD when evaluated
after the same antialiasing or upscaling pipeline, at matched face count and
complete runtime cost? This is an untested hypothesis, not a novelty claim.
Differentiable mesh fitting and image-guided adaptive subdivision have close
prior art, including per-triangle micro-mesh LOD. See the [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
and [SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md).

## Evidence snapshot

- **Current cut:** The 21-model matched-face screen found worse LDR-FLIP, PSNR,
  SSIM, and silhouette XOR than border-preserving QEM and meshoptimizer, with
  native sampling and 4x MSAA. Paired 95% intervals exclude zero across 16
  source groups. This closes the tested cut, not every geometry method. It is
  fixed-view desktop evidence, not an equal-time or mobile result. See the
  [protocol and results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md)
  and [per-view metrics](tools/mmtrain/polyhaven_quality_metrics_20261124.json).
- **Source provenance:** A clean Release build from reconstructed commit
  `489b275` matches the archived PE except for its duplicated build timestamp;
  all other bytes, including `.text`, match. The retained `Grouper.obj` lacks
  an individual `Grouper.cpp` source checksum, and the rebuilt executable was
  not run because Windows application control blocked it. The archived binary
  replayed 18 expanded-cohort meshes exactly; the original three were not
  replayed. See the [rebuild receipt](tools/mmtrain/mmgeo_clean_rebuild_489_20261125.json)
  and [geometry replay receipt](tools/mmtrain/polyhaven_geometry_replay_20261125.json).
- **Earlier controls:** The seven-asset screen used a retrospective boundary
  tolerance and reused development assets; it beat meshoptimizer on two pairs
  from one asset and beat no eligible QEM pair. Fixed-topology placement and
  projective silhouette fits did not establish a repeatable gain. A 64-view
  contour-priority QEM control gained +0.167 dB mean PSNR on seven development
  assets, but had mixed FLIP results and no reliable AA follow-up gain. A
  fixed-topology contour fit regressed on two of three assets. See the
  [CPU screen](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md), [AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md),
  [fit report](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md), and [dated history](MANYMESH_HISTORY.md).
- **Monkey source-reference diagnostic:** The three frozen cuts were re-scored
  against the original 15,744-face source at matched face counts. The candidate
  loses to eligible QEM and meshoptimizer controls on all reported image metrics
  at every tested budget. This closes these cuts as evidence for a silhouette
  benefit; it is one reused asset, uses a retrospectively selected boundary
  tolerance, and has no pinned candidate-generation binary. See the
  [report and receipt](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- **Instance-scale screen:** The 10,000-instance desktop GPU raster interval
  fell 4.31x for stock depth-2 geometry, but the aggregate quality comparison is
  not geometry-eligible: four assets have changed boundary-edge counts and one
  cut has duplicate/nonmanifold faces. Treat image deltas as diagnostic only;
  timing applies to the submitted buffers. See the [report and receipt](tools/mmtrain/INSTANCE_SCALE_SCREEN_20261124.md).

No physical-phone test, equal-frame-time quality comparison, LPIPS evaluation,
moving-camera temporal evaluation, user study, or positive held-out optimized
method is available.

## Next gate

Run the frozen fixed-topology placement control on CUDA with BarramundiFish and
Corset. Their CPU preflight passed at 1,932 and 9,162 comparison faces, but this
host has PyTorch 2.7.1+CPU and no CUDA runtime. The experiment uses a
nvdiffmodeling-based adapter, not a faithful reproduction of Hasselgren et al.;
it disables MSAA during fitting and does not optimize through the final 4x MSAA
or an upscaler. Two reused assets can screen this configuration only. If it
does not show repeatable reserved-view gains at matched face count, close this
configuration and do not advance to a custom DAG optimizer.

On 2026-11-25, `--prepare-only` was repeated for both frozen assets. Each output
protocol matched its earlier per-asset receipt byte-for-byte, and the current
fit script, scorer, and external NVIDIA source tree matched their pinned hashes.
The isolated research environment uses NumPy 2.3.4 and SciPy 1.15.3; both
preflights completed there without warnings and still matched byte-for-byte. A
run through the base Python environment emitted a SciPy/NumPy compatibility
warning, so keep using the isolated environment on the eventual CUDA host. No
fit or quality scoring has run yet.

Frozen assets, controls, scorer, camera split, and limits are in the
[input report](tools/mmtrain/MATCHED_APPEARANCE_INPUTS_20261124.md) and
[protocol receipt](tools/mmtrain/appearance_cuda_protocol_20261124.json).

## Project documents

- [SIGGRAPH 2027 direction](SIGGRAPH_2027_DIRECTION.md)
- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Filament documentation](filament/README.md)
