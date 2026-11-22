# ManyMesh

ManyMesh investigates how mesh LOD affects rendered image quality and rendering cost. The repository is a Filament research checkout; the current evidence does not support a submission-ready method or a mobile-performance claim.

![Khronos Suzanne rendered at 3,936 and 982 triangles beside a map of silhouette differences.](docs/manymesh/suzanne-lod.png)

*Khronos Suzanne, flat shaded, 384 × 384 per panel, CPU reference render. The center panel is the depth-2 cut from unmodified meshoptimizer v1.2. The right panel marks binary coverage differences. Asset: UX3D / Norbert Nopper, CC0 1.0. [Figure receipt](docs/manymesh/suzanne-lod.json).*

## Research status

**No current ManyMesh method has passed both the novelty and quality–cost gates.** The tested cross-asset image network adds little beside established antialiasing, and tested geometry decoders lose to meshoptimizer on validation assets. A completed moving-camera LOD screen on three synthetic scenes gives small quality changes, but no equal-face, equal-frame-cost win.

### The central open problem

**I need a method that preserves the image of aggressively simplified meshes at the same frame-time budget as strong rendering controls.** The evidence points toward silhouette error as a useful target, but it does not yet give us a method: one Monkey still attributes 68.3% of squared error to 0.11% of pixels, while the tiny CNN gains only 0.14 dB and 4x MSAA gains 1.43 dB at the cited retention level. Neither tested silhouette-fusion prototype is jointly better in all three image metrics than every eligible control on the 13 assets. Static TAA scores below no AA, and no jittered-LOD temporal-accumulation, mobile-device, or user-preference result exists.

The open research question is how to reduce silhouette-driven error under motion without spending more than MSAA, SMAA, or an upscaler at the same measured frame time. The one new method worth a time-boxed test is jittered LOD cuts with temporal accumulation: the old TAA test used a static image, so it did not test changing geometry or subpixel samples over time. This is a hypothesis, not a result. In the 48-frame moving-camera screen, area-based per-instance allocation used 2.8–12.3% more faces under the same maximum face cap—not the same actual face count—and ran 12–15% slower on GPU p50 in each of three scenes; its gains were only +0.012–0.048 dB PSNR and 0.7–2.1% LDR-FLIP. Its mean CGVQM-5 improvement was +0.058 (three-scene bootstrap 95% interval [+0.001, +0.152]), but at the higher triangle count and GPU cost. A face-budget-matched offline oracle improved CGVQM-5 in one scene only; its interval includes zero, and it required 1.25–8.68 ms selector p50. This does not pass an equal-cost gate. Screen-area LOD already has prior art. **The current decision is Path B unless a real Android device and harness are available in week one:** package the negative result and silhouette analysis for a shorter venue, whose 2027 dates are not all announced. Do not present the benchmark alone as a SIGGRAPH contribution.

### What the image-quality measurements say

- **The tiny CNN adds little beside the AA controls in the historical Monkey stills.** At 38.00% retention, reported PSNR is 37.38 dB without AA, 37.52 dB with the CNN, 38.81 dB with 4× MSAA, and 38.89 dB with MSAA plus the CNN. The network's incremental gain after MSAA is 0.08 dB. At 29.38% retention, the report lists 39.76 dB without AA and 41.40 dB with 4× MSAA. These are fixed-camera grayscale measurements, not temporal or mobile results.
- **Static TAA scores lower in the cited Monkey capture.** At 29.38% retention, the reported values are 37.92 dB with TAA and 39.76 dB without AA; this does not test a changing LOD cut or temporal accumulation over a moving sequence.
- Each AA mode was compared with a full-detail image rendered using the same AA mode. The cross-mode PSNR differences above are the historical reported scores, not a strict same-image-reference ablation.
- **The silhouette-error result used an intermediate reference.** Its 0.11% XOR-pixel / 68.3% squared-error figure compares a 7,124-triangle candidate with an 11,250-triangle full-detail DAG cut. The Monkey source has 15,744 triangles. Do not read this as a measurement against the original source mesh.

The legacy Monkey captures have no recorded GPU model. A broader 13-asset desktop screen compares native cuts, 4× MSAA, SMAA and upscaling: the calibrated cut with 4× MSAA improves average image metrics over half-resolution linear reconstruction but is faster on only 4/13 assets. In the 13-asset silhouette-fusion screen, **0/13 means neither prototype was jointly better in LDR-FLIP, PSNR, and SSIM than every eligible control at or below its per-asset GPU p50**. It does not mean MSAA/SMAA lost on every individual metric or asset; in this receipt, an eligible MSAA mode strictly dominates both fusion variants on all three metrics for all 13 assets. For each asset, a cheaper mode was selected after seeing the results that beat both prototypes on all three metrics. This outcome-selected rule makes the screen exploratory, not a pre-registered head-to-head. It is fixed-view, grayscale Iris Xe desktop data, not a phone or full-frame equal-time result. See the [13-asset report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md), its [repeat receipt](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json), and the [next-experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md).

### Current evidence

| Works | Does not pass | Not measured |
|---|---|---|
| Draw-range merging reduced CPU submission overhead in one historical Iris Xe desktop case. | Tested polynomial cluster decoding and local refinement; cross-asset CNN as an alternative to MSAA; shared-profile and budget-matched moving per-instance LOD. | Android/iOS device performance, power and thermal behavior, user preference, and a fresh licensed confirmation set. |

The 0/13 fusion screen reports LDR-FLIP, PSNR, and SSIM; it has no LPIPS score or user study. Across the broader work, quality screens report PSNR, SSIM, LDR-FLIP and, for moving sequences, CGVQM-5. LPIPS, silhouette, surface distance, normal consistency and topology checks are included where relevant. These metrics answer different questions; none alone establishes visual preference. The reused-asset CGVQM-5 profile screen has a mean change of −0.0590 (95% asset-bootstrap CI [−0.1476, +0.0424]); four assets improve and nine regress. It is inconclusive, not a temporal-quality win. The repeat preserves all per-mode image captures. Across the six reported modes, median per-asset GPU p50 changed by -13.5% to +12.1%; the two fusion candidates changed +2.8% and +4.6%. The eligible-MSAA dominance count stayed 13/13, but desktop timing remains sensitive to run state.

## Project notes

- [Concise research status and next gate](MANYMESH.md)
- [Moving-camera per-instance LOD screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- [CPU-only 0/13 receipt verifier](tools/mmtrain/verify_silhouette_guide_fusion.py)
- [Filament documentation](filament/README.md)

The existing Thingi10K and Khronos assets are development data. Publication claims require an independently licensed confirmation set.
