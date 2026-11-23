# ManyMesh research status

Updated 2026-11-23. **No SIGGRAPH-ready contribution is established.** The
current candidate is offline appearance optimization for a constrained cluster
LOD hierarchy, evaluated after antialiasing or upscaling, with separate
matched-face and matched-complete-frame-time comparisons. It remains a
hypothesis with close prior art, not a novelty claim.

## Decision-relevant evidence

- The 13-asset silhouette-fusion screen is **0/13** under its joint FLIP/PSNR/
  SSIM criterion at a per-asset GPU-time budget. This means neither prototype
  beat all eligible controls together; it does not mean every metric regressed.
  A cheaper winning mode was selected after seeing results, so this is
  exploratory and post-hoc. [Report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md) · [verified repeat](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json)
- A 48-frame, three-scene moving-camera screen found that per-instance area
  allocation used more faces and was slower on GPU. A face-budget-matched
  offline oracle improved the temporal metric in one scene only and incurred
  CPU selection cost. [Report](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- A pinned Khronos source screen has one provisional topology-pass asset
  (CommercialRefrigerator); CarConcept fails the same gate and contains separately
  licensed marks. No second fresh asset or confirmation set is ready. [Source,
  license, and topology screen](docs/manymesh/confirmation-asset-screen-20261123.md)

The evidence is fixed-view or small desktop development data. There is no
physical-phone performance, power, thermal, user-preference, or independent
held-out generalization result. Metric suites and historical Monkey captures
are documented in the linked reports; older single-view values should not be
read as general claims.

## Next gate

1. Do not promote the tested decoder, silhouette-fusion, or moving-allocation
   variants as contributions.
2. Run the matched-face differentiable simplification baseline on legally
   cleared assets with CUDA. Freeze views, metrics, topology rules, and QEM /
   meshoptimizer controls before scoring.
3. Continue only if the baseline shows repeatable held-out improvement. Then
   test cluster-DAG constraints and compare actual AA/upscalers at equal full
   frame cost. Mobile or preference claims require device measurements or a
   user study.

See the [next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md) and the
[public project homepage](README.md).

The [SIGGRAPH 2027 direction](SIGGRAPH_2027_DIRECTION.md) records the candidate
thesis, closest prior art, source-access limits, and stop criteria.
