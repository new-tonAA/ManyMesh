# ManyMesh research status

Updated 2026-11-27. **No SIGGRAPH-ready contribution is established.** The 21-model matched-face screen found ManyMesh worse than QEM and meshoptimizer. No optimization has established an asset-held-out win.

## Image quality evidence

There is no single image-quality score that should decide this result. Our
static-render protocol combines graphics-oriented LDR-FLIP with PSNR and SSIM,
plus task-specific silhouette XOR and sampled surface/normal errors; LPIPS is
reported as a complementary learned metric. The existing screen covers 21
licensed meshes from six classes and 16 source groups, with native and 4x-MSAA
renders. ManyMesh loses to both matched-face controls on all four original
image metrics in both modes; the post-hoc LPIPS supplement has the same
direction. These are fixed-view desktop results, not human-preference or
mobile-performance evidence. See the [protocol and per-model results](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md),
[LPIPS supplement](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md),
and [multiplicity audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).

For a moving-camera or temporal-upscaling claim, retain the frame metrics and
add a graphics-video metric such as [CGVQM](https://doi.org/10.1111/cgf.70221)
and a switch-local temporal diagnostic. That metric has not yet been run on
ManyMesh sequences. Metric scores remain proxies; preference claims require a
user study.

## Evidence

- A local D3D12 Deliot-style fixed-topology fit now exercises that non-CUDA route on one reused Thingi10K train asset. A deterministic diagnostic replay confirms all 40/40 candidate trials failed the face-normal guard before loss evaluation; every trial had a negative minimum signed normal ratio. Both outputs stayed unchanged, and ManyMesh trails the fitted meshoptimizer control by 6.686 dB PSNR and 0.001732 mean LDR-FLIP on 24 previously examined views. This exact optimizer configuration is closed; it is not asset-held-out evidence. [Fit result](tools/mmtrain/DELIOT_MSAA_PER_PIXEL_FIT_DEV_20261127.md) · [rejection diagnostic](tools/mmtrain/DELIOT_FIT_REJECTION_DIAGNOSTIC_20261127.md) · [raw diagnostic receipt](tools/mmtrain/deliot_fit_rejection_diagnostic_20261127.json).
- The follow-up Hildreth active-normal projection control converged on all eight updates but only accepted 1/4 ManyMesh steps and 0/4 meshoptimizer steps. The one ManyMesh step improved PSNR by 0.343 dB but worsened mean FLIP by 0.000980; against projected meshoptimizer it remained 6.343 dB lower in PSNR and 0.002712 worse in FLIP. This established numerical control does not pass its frozen gate and is closed: [protocol](tools/mmtrain/DELIOT_ACTIVE_NORMAL_PROJECTION_DEV_PROTOCOL_20261127.md) · [result](tools/mmtrain/DELIOT_ACTIVE_NORMAL_PROJECTION_DEV_20261127.md) · [receipts](tools/mmtrain/deliot_active_normal_projection_raw_20261127.json).
- A frozen progressive-LOD byte/quality pilot on one licensed train asset found the current raw `.mmb` page layout dominated by an exact-face-count static control: at 5,290 faces, the page candidate used 298,612 bytes and mean LDR-FLIP 0.003739, while Draco 1.5.7 encoded from an exact-face meshoptimizer cut used 11,386 bytes and FLIP 0.001009. This closes the tested raw-page representation only; it is not a network or general streaming result: [protocol](tools/mmtrain/STREAM_RATE_DISTORTION_PILOT_PROTOCOL_20261127.md), [report](tools/mmtrain/STREAM_RATE_DISTORTION_PILOT_20261127.md), [per-view and codec receipt](tools/mmtrain/STREAM_RATE_DISTORTION_PILOT_20261127.json).

- Matched-quality protocol and results, post-hoc LPIPS, and multiplicity audit: [screen](tools/mmtrain/POLYHAVEN_QUALITY_SCREEN_20261124.md) · [LPIPS](tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md) · [audit](tools/mmtrain/POLYHAVEN_MULTIPLICITY_AUDIT_20261125.md).
- Tested residual decoders, budgeted refinement, and contour controls did not beat their controls: [decoder study](tools/mmtrain/CLUSTER_DECODER_RANK_SWEEP_20261122.md) · [contour study](tools/mmtrain/CONTOUR_IMPORTANCE_QEM_20261123.md).
- A CPU projective silhouette fit lowered training loss on two reused assets, but LDR-FLIP worsened on both reserved-view sets; PSNR changed by +0.043 dB on one asset and −0.092 dB on the other. This is not asset-generalization evidence: [report](tools/mmtrain/PROJECTIVE_SILHOUETTE_CPU_20261124.md).
- A separate PyTorch3D CPU soft-coverage fit ran locally without CUDA or neural-network training. On two reused assets, it reduced training coverage MSE by only 0.192% and 0.035%; mean LDR-FLIP worsened on BarramundiFish with native sampling and on both assets with 4× MSAA. It fails the frozen gate and is closed; do not score the reserved 30-model pool with it. WGPU quality scoring used Vulkan llvmpipe software, not hardware timing: [protocol](tools/mmtrain/PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_PROTOCOL_20261127.md), [report](tools/mmtrain/PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_20261127.md), [per-view receipt](tools/mmtrain/PYTORCH3D_CPU_SILHOUETTE_PLACEMENT_20261127.json).
- The original CPU projective-RGB fit had mixed exact-face QEM results. A QEM-initialized variant improved raw QEM on both reused models, but the stronger same-host comparison against the meshoptimizer-initialized fit failed on MaterialsVariantsShoe by 5.421 dB PSNR, 0.001038 SSIM, and 0.001950 mean LDR-FLIP. It does not advance to the unscored 30-model pool: [QEM control](tools/mmtrain/PROJECTIVE_RGB_CPU_QEM_CONTROL_DEV_20261126.md); [frozen QEM-fit protocol](tools/mmtrain/PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_PROTOCOL_20261127.md); [four-arm result](tools/mmtrain/PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.md); [raw receipt](tools/mmtrain/PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_20261127.json).
- A CPU cluster-boundary-locked fit on Thingi10K 84736 (train asset, 5,290 faces) improved on raw ManyMesh, but did not beat the same optimizer applied to exact-face meshoptimizer: held-out-view mean LDR-FLIP was 0.005035 versus 0.004710, PSNR was 1.617 dB lower, and SSIM was 0.001158 lower. The 1,109 locked vertices and all 5,290 faces passed topology/boundary checks. This single-asset screen is closed and is not asset-held-out evidence: [protocol](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_PROTOCOL_20261127.md), [report](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_20261127.md), [raw per-view receipt](tools/mmtrain/CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_20261127.json), [independent verifier](tools/mmtrain/verify_cluster_dag_projective_cpu.py).
- A shared-position CPU fit across three cuts of that same DAG lost to fitted exact-face controls at all cuts. A post-hoc recheck of those fits on the local Iris Xe D3D12 renderer with 4x MSAA did not reverse the ranking: candidate PSNR was lower by 6.86, 5.72, and 2.71 dB, and mean FLIP was worse by 0.002449, 0.002105, and 0.001019 at 2,286, 5,290, and 7,934 faces. This is one reused train asset, 24 correlated views, a flat grayscale shader, and no frame-time comparison; it closes this fit configuration, not the broader final-AA optimization question. [CPU fit report](tools/mmtrain/CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.md), [MSAA protocol and result](tools/mmtrain/CLUSTER_DAG_MULTICUT_FINAL_MSAA_RECHECK_20261127.md), [per-view metrics](tools/mmtrain/cluster_dag_multicut_final_msaa_quality_20261127.json).
- Silhouette attribution revises the old 68.3% Monkey result, which used a DAG cut rather than the source mesh as reference: [attribution](tools/mmtrain/POLYHAVEN_SILHOUETTE_ATTRIBUTION_20261125.md) · [reference audit](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md).
- The 10,000-instance desktop screen found coarser meshoptimizer rasterizing faster; it did not establish a ManyMesh, full-frame, or mobile win: [report](tools/mmtrain/INSTANCE_SCALE_BARRAMUNDIFISH_SCREEN_20261125.md).

## Next gate

The frozen nvdiffmodeling placement control still requires CUDA and has not run. The alternative local Deliot-style D3D12 fit has now run, but no update was accepted and it lost to exact-face meshoptimizer; that fixed-topology optimizer configuration is closed. The local CPU PyTorch3D alternative, the single-cut boundary fit and the shared-position three-cut fit also failed their strongest eligible baseline gates. The D3D12 4x MSAA recheck used actual desktop hardware, but only rescored already-fitted geometry on one reused asset; it did not establish an asset-held-out or frame-time win. Full [DiffSimp](https://arxiv.org/abs/2611.31018) review closes differentiable optimization through QEM collapses as a standalone contribution; broader constrained-hierarchy objectives remain unresolved, not established as novel. The 30-model confirmation pool remains unscored because tested fit variants fail development gates. Its frozen camera samples are not region-held-out, so a superseding view manifest is required before any new Gate 2 run: [experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md); [confirmation protocol](tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

On this laptop, the D-drive WSL2 Clang build ran `test_manymesh` (94 passed, 1 skipped) and Vulkan `compute_test` (7/7 passed on CPU llvmpipe). Software OpenGL aborted in 3 tests; the Iris Xe D3D12 OpenGL route skipped all 7 compute tests because it exposes only Filament feature level 1. This does not qualify the hardware GPU compute path. Native Windows execution remains blocked by Smart App Control. [Local verification report](tools/mmtrain/LOCAL_WORKSTATION_VERIFICATION_20261126.md) · [hosted Windows/MSVC CI](https://github.com/new-tonAA/ManyMesh/actions/runs/45622515351).

## Claims not established

No asset-held-out optimization win, equal-frame-time quality win, on-device result, temporal-quality gain, compression gain, or user study. Desktop results do not establish mobile performance.

## Research index

[SIGGRAPH direction](SIGGRAPH_2027_DIRECTION.md) · [Roadmap](MANYMESH_RESEARCH_ROADMAP.md) · [Prior art](docs/manymesh/siggraph-prior-art-screen-20261123.md) · [History](MANYMESH_HISTORY.md) · [Learned LOD](MANYMESH_LEARNED_LOD_RESEARCH.md) · [Filament docs](filament/README.md)
