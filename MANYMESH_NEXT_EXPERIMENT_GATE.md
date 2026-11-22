# Next experiment gate: jittered LOD accumulation

Updated 2026-11-23. This is a falsifiable research gate, not a claim that temporal jitter will work. The current evidence supports Path B unless the Android harness and a physical device are available by the end of week one. [SIGGRAPH 2027 Technical Papers](https://s2027.siggraph.org/program/technical-papers/) lists a 2027-01-28 deadline; [I3D 2027](https://i3dsymposium.org/) has not announced dates, and [HPG 2027](https://www.highperformancegraphics.org/2027/index.html) has announced its July 7-9 event but not its submission call. Do not infer a deadline from prior years.

## One candidate method

Test a single method: jitter the selected LOD cut across frames and accumulate the resulting subpixel coverage with temporal reprojection and disocclusion rejection. Do not also tune the silhouette CNN or add a second learned method. First check novelty against temporal antialiasing, stochastic LOD, temporal supersampling, and progressive mesh/LOD work. If no distinct contribution can be stated, stop before implementation.

## Baseline qualification, frozen before candidate results

The 13-asset fusion screen is exploratory. Its 0/13 criterion selected a cheaper winning mode after results were measured. The next screen must fix the controls, exclusions, cost budget, image reference, and analysis before running the candidate. Every qualified mode is reported; no mode may be excluded because its quality result is inconvenient.

- Freeze a real Android device model, OS/build, GPU driver, Filament commit, output resolution, refresh rate, thermal state policy, camera paths, assets, and frame budget before the first candidate measurement. Emulator timing is invalid evidence.
- Use the same independently rendered high-quality reference for every mode. Preserve the original source mesh and record each simplified mesh's actual face count, bytes, topology, and boundary checks.
- Predeclare controls: source geometry with native rendering, source with 4x MSAA, the frozen simplified cut with 4x MSAA, SMAA where supported, and the shipping/upscaling path where available. Include no-AA as a diagnostic. Report every mode on every asset.
- Set the full-frame target budget from the intended device refresh rate before testing. Compare the quality-cost Pareto curves and the predeclared target operating point. Include CPU submission, GPU p50/p95, frame misses, memory, and power/thermal drift. Do not define eligibility from the candidate's observed time.
- Use at least 20 independently licensed held-out assets across at least five geometry categories, plus fixed camera paths with translation, rotation, disocclusion, and LOD transitions. Keep all held-out assets out of training and tuning. Reused assets are development data only.
- Report common-reference PSNR, SSIM, LDR-FLIP, LPIPS, silhouette/coverage error, and a temporal metric such as CGVQM-5. State color space, viewing assumptions, normalization, and whether each measure is higher- or lower-is-better. Bootstrap paired effects over assets, not frames. Define practical-effect and regression margins from a baseline repeatability pilot before viewing candidate results.
- Pass only if the frozen candidate improves the predeclared quality endpoint(s) at the fixed full-frame budget on held-out assets, paired uncertainty clears the predeclared margin, no critical topology/boundary violation occurs, and the full-frame p95 and thermal limits hold. Publish failures and per-asset results. If this gate fails at week four, stop Path A.

## Four-week schedule and current environment

| Gate | Required evidence | Current state |
|---|---|---|
| Week 1: Android path | Android Studio/SDK/NDK, `adb`, one USB-debuggable physical phone, and a Filament sample harness that loads the test `.mmb`, replays a fixed Monkey/Dragon path, and logs per-frame CPU/GPU timestamps | Not ready. No Android Studio or SDK was found in the standard location; the bundled emulator SDK has directories but no `adb.exe`; no physical device is connected. The repository has no ManyMesh Android entry point. |
| Week 2: baseline freeze | Device manifest, working harness, qualified baseline list, licenses, held-out split, common reference, and preregistration commit | Not run |
| Week 3: candidate | One jittered-cut accumulation prototype and full baseline sweep | Not run |
| Week 4: decision | Held-out phone results with FLIP/LPIPS/temporal quality, complete frame costs, and uncertainty | Not run; no mobile evidence exists |

A cloud device lab can fill the hardware gap, but no account was checked and no paid device was rented. As of 2026-11-23, Firebase Test Lab lists 30 physical-device test minutes per day at no cost, then $5/device-hour billed by the minute ([official quotas and pricing](https://firebase.google.com/docs/test-lab/usage-quotas-pricing)). AWS Device Farm lists a one-time 1,000 device-minute free trial, then $0.17/device-minute; its unlimited plan starts at $250/month ([official pricing](https://aws.amazon.com/device-farm/pricing/)). Google says Test Lab is being replaced by Developer Device Platform after 2027-04-30, with new pricing after that date ([migration notice](https://firebase.google.com/docs/test-lab/migrate-faq)). Recheck eligibility, device availability, and rates before scheduling; these rates are not an approval to incur charges. If a physical device is unavailable by week one, choose Path B and prepare the desktop 0/13 screen plus silhouette-error analysis for an appropriate shorter venue. A benchmark alone is unlikely to support a SIGGRAPH main-track method claim. I3D 2027 deadlines remain TBD; HPG 2027 currently publishes the event dates only.

## Evidence links

- [13-asset silhouette-fusion report](tools/mmtrain/SILHOUETTE_GUIDE_FUSION_20261122.md)
- [Original measurement receipt](tools/mmtrain/silhouette_guide_fusion_720p_20261122.json)
- [Repeat measurement receipt](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json)
- [Repeat benchmark source](tools/mmtrain/bench_silhouette_guide_fusion.py)
- [CPU-only receipt verifier](tools/mmtrain/verify_silhouette_guide_fusion.py)
- [Moving-camera desktop screen](tools/mmtrain/DYNAMIC_INSTANCE_LOD_MOVING_20261123.md)

The repeat preserves all per-mode image-quality values but GPU p50 measurements shifted. The receipt embeds SHA-256 digests for the benchmark, its parent and raster scripts, the input manifest, and pinned Bevy assets. The original run's recorded source digest differs from the current benchmark file; use the repeat receipt for the frozen source snapshot. Prepared geometry and lossless frame captures remain in ignored local `out/` data, so the report bundle is not a standalone rerun package.
