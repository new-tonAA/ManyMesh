# Archived experiment gate: contour-aware LOD under antialiasing

Updated 2026-11-23. This is an archived falsification plan, not the current research queue and not a claim that the method works. The node-level cone-risk selector has now been built and run on 12 repository OBJ fixtures at three budgets. It produced zero equal-face, geometry-distinct candidates; no image-quality comparison was eligible. See the [budget-screen receipt](tools/mmgeo/CONTOUR_SELECTOR_BUDGET_SCREEN_20261123.md). The differentiable DAG question remains untested; its closest-prior-art map is in the [upscaler-aware DAG research plan](MANYMESH_UPSCALER_AWARE_DAG_RESEARCH.md), and the original contour protocol remains [here](MANYMESH_CONTOUR_BUDGET_RESEARCH.md).

## Pre-register before candidate scoring

- Freeze development assets, training/validation/test identities, camera views and paths, geometry hashes, renderer settings, common supersampled source references, AA mode and color transform. Use development assets for choosing cone margin and interior multiplier; reserve the test split for a one-time frozen check.
- Compare uniform screen-error cut + 4× MSAA with contour-weighted cut + 4× MSAA at the same actual face count. If the DAG cannot hit the requested count, state the nearest count and mark the pair infeasible outside a frozen tolerance. Add matched QEM/CornerSimplifier and stock meshoptimizer cluster LOD controls; also report full source + MSAA and no-AA as diagnostics.
- Freeze `k` (interior threshold multiplier) and cone margin on training/validation only. Do not select baselines after seeing results. Report every arm and asset.
- Score common-reference LDR-FLIP, PSNR, SSIM and silhouette/coverage error. Also check sampled surface and normal deviation, boundary cracks, nonmanifold/duplicate faces, and popping on held-out motion paths. For sequences add CGVQM-5 and switch-local diagnostics. Bootstrap over assets, not frames; predeclare practical-effect margins from repeated baseline measurements.
- Report actual faces, tile-touch proxy, selector CPU p50/p95, total CPU update/submission, GPU p50/p95, draws, memory and geometry/sidecar bytes. Tile-touch estimates are not device timings.

## Device phase

Only if the frozen desktop development screen passes, compare the candidate against fixed geometry + 4× MSAA, SMAA and the existing dynamic-resolution/upscaling path at equal complete-frame time on a physical phone. Freeze phone model, GPU/driver, OS, Filament revision, resolution, refresh target, thermal protocol, assets, paths and budget first. Record frame misses, CPU/GPU cost, vendor binning or stage counters, memory, power and thermal drift when available. Emulator and Iris Xe timings do not count as mobile results.

As an architectural rationale, tiled GPUs bin triangles into screen tiles before shading; the exact work and MSAA cost vary by vendor and scene. Use device counters or stage timings where exposed. Do not treat one generic triangle budget or the screen-space tile proxy as a universal phone cost model.

## Four-week stop rule and present environment

| Gate | Required evidence | State |
|---|---|---|
| Week 1: inputs and device | Frozen licensed split; valid common references; physical phone and harness identified | Not ready; no phone is connected and no usable local Android SDK/`adb` was found in the prior preflight |
| Week 2: cone correctness and desktop screen | Prove parent cones conservatively enclose descendants or use a safe fallback, then run the frozen uniform-versus-cone allocation at equal faces with AA on | Budget-only screen completed on 12 internal fixtures and three ratios; zero equal-face, geometry-distinct candidates. No AA or quality metric run; full-DAG cone conservativeness remains unverified |
| Week 3: independent check | Frozen parameters scored once on held-out licensed assets and camera paths | Not run |
| Week 4: decision | Repeatable quality–cost improvement and, for mobile claims, phone result at the same complete-frame budget | Not run |

Stop the candidate if it does not improve the held-out quality–cost frontier against the frozen controls, if improvements disappear after full selector cost, or if topology/boundary constraints fail. If no physical device/harness is available, report only the desktop finding and move to the shorter-paper negative-result path; do not claim mobile performance. Device-lab availability and pricing must be checked before any paid run; this plan does not incur charges.

## Existing evidence

- [13-asset silhouette-profile negative result](tools/mmtrain/DYNAMIC_LOD_SILHOUETTE_OBJECTIVE_20261122.md)
- [SMAA and perfect silhouette-band upper bound](tools/mmtrain/GPU_SMAA_SILHOUETTE_BAND_SCREEN_20261122.md)
- [13-asset silhouette-guide comparison](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- [Moving-camera equal-face oracle](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)
- [Literature and frozen comparison protocol](MANYMESH_CONTOUR_BUDGET_RESEARCH.md)
