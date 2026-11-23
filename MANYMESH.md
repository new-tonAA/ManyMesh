# ManyMesh research status

Updated 2026-11-24. **No SIGGRAPH-ready contribution is established.** The
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
- A seven-asset Khronos screen compares current cuts with the original source
  meshes. Under a retrospective one-float32-ULP boundary rule, 15 of 21 cuts
  were eligible. Across 18 exact-face pairs, ManyMesh lost all five image
  metrics in 15, won all five in two meshoptimizer comparisons on the 987-face
  GlassBrokenWindow, and had one mixed result; it did not beat any eligible QEM
  pair. The boundary rule was chosen after an initial run, and these reused
  assets are development data, not held-out confirmation. No timing, phone, or
  upscaler result was measured. The two GlassBrokenWindow wins are against
  meshoptimizer only: border-preserving QEM returned 859 faces at all requested
  targets (381, 491, and 569), so it supplied no eligible exact-face pair.
  [Report](tools/mmtrain/KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md) ·
  [metrics and hashes](tools/mmtrain/khronos_equal_face_quality_screen_20261123.json)
- Khronos geometry preflight has nine provisional candidates across several
  object classes, including many disconnected components and a low-detail
  window case. The pool is unfrozen and is not held out. [Expanded screen](docs/manymesh/khronos-expanded-candidate-screen-20261123.md) and
  [earlier screens](docs/manymesh/khronos-followup-candidates-20261123.md)
- Six source meshes across two preflights supplied zero complete sets of
  legal, exact-face ManyMesh, QEM, and meshoptimizer meshes near 30% retention.
  [Two-asset screen](tools/mmtrain/APPEARANCE_INPUT_PREFLIGHT_20261123.md) and
  [four-asset screen](tools/mmtrain/KHRONOS_SEPARATE_BUFFER_PREFLIGHT_20261124.md)
- A 64-view source contour priority raised mean PSNR by 0.167 dB over the
  same unweighted QEM on seven development assets at equal faces. FLIP
  was mixed, and the only all-metric win over meshoptimizer also occurred
  with plain QEM. [Contour priority report](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md)
- On Iris Xe, the same seven mesh pairs showed no consistent FLIP gain
  with hardware MSAA, SMAA, or bicubic upscaling. Native FLIP worsened
  on all seven. [Desktop AA follow-up](tools/mmtrain/CONTOUR_PRIORITY_AA_20261123.md)
- Fixed topology silhouette fitting improved training coverage, but the
  separate Mitsuba projective fit worsened reserved-view FLIP and SSIM on
  both development assets. [Projective fit](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md) and
  [local fit](tools/mmtrain/VISIBLE_CONTOUR_FIT_20261124.md)

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
