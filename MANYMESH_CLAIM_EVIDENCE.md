# Homepage evidence ledger

These are historical development measurements, not new decoder experiments.
Source records are preserved in [the history](MANYMESH_HISTORY.md). Missing hardware
or camera details must remain unknown; do not infer them from another run.

## Reproducibility and source revision

No generating Git commit has been verified for the historical Monkey image-quality
captures or the 1,433-draw to one-draw timing. Their source code or report path is
not enough to establish which exact checkout produced those numbers. Do not use the
current `HEAD` as their run revision: this worktree contains later edits, and no
matching clean commit or archived patch has been identified.

Several newer experiments do preserve useful content-addressed receipts, but their
provenance levels differ:

| Evidence | Pinned artifacts | Missing for commit-level reproduction |
|---|---|---|
| Homepage Suzanne teaser | Khronos source revision and asset hashes; meshoptimizer revision; demo, generator, and output-image SHA-256 in [figure receipt](docs/manymesh/suzanne-lod.json) | A project Git commit is unnecessary for the pinned upstream demo, but the local build recipe and environment should still be archived for exact regeneration. |
| 13-asset silhouette-fusion screen | Script, parent/raster scripts, asset manifest, Bevy files, and input assets are SHA-256 pinned in [run receipts](tools/mmtrain/silhouette_guide_fusion_720p_20261122.json) and its [repeat](tools/mmtrain/silhouette_guide_fusion_720p_repeat_20261123.json) | No ManyMesh Git commit; capture the exact source tree or clean commit for any rerun. |
| Historical cluster-cut topology audit | Historical executable SHA-256 and audit-script SHA-256 in the [audit receipt](tools/mmgeo/historical_cut_topology_audit_20261122.json) | Original ManyMesh source commit for the historical binary. Current modified source was not executable on the recorded host. |
| Current-source fixed-default cluster-cut eligibility | Current `mmgeo` binary, `main.cpp`, comparison script, validation manifest, and upstream receipt hashes in the [current-source receipt](tools/mmtrain/current_source_clusterlod_audit_20261123.json); the relevant dirty-source delta is archived in the [provenance record](tools/mmtrain/CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md) | The fixed-default run had no eligible exact-face pair. The source patch is recoverable, but the exact compiler version and original build command are missing; validation assets are reused, not independent confirmation data. |
| Current-source cluster-LOD parameter sweep | Fixed 48-build grid, all 96 cuts, binary/source/manifest/upstream receipt hashes and every eligibility outcome in the [sweep receipt](tools/mmtrain/cluster_cut_parameter_sweep_20261123.json); metrics for all eligible exact-face pairs in the [score receipt](tools/mmtrain/cluster_cut_parameter_score_20261123.json); relevant dirty-source delta is archived in the [provenance record](tools/mmtrain/CURRENT_SOURCE_MMGeo_PROVENANCE_20261123.md) | Two eligible pairs were found across only two reused assets; both lost to stock on the reported image metrics. Exact compiler version and original build command are still missing; this is not bit-identical build reproduction or held-out evidence. |
| Original-source Monkey diagnostic | Source OBJ hash, current binary/source hashes, diagnostic scorer hash, helper/package versions, protocol, and per-view image/surface metrics in the [raw receipt](tools/mmtrain/monkey_source_reference_diagnostic_20261123.json); boundary geometry in the [curve audit](tools/mmtrain/monkey_boundary_curve_audit_20261123.json); the retrospective one-ULP rerun in the [rescore receipt](tools/mmtrain/monkey_source_float32_boundary_diagnostic_20261123.json); build and scoring logs in the [mmgeo log](tools/mmtrain/asset_reuse_audits/monkey_source_mmgeo_20261123.log) and [scoring log](tools/mmtrain/asset_reuse_audits/monkey_source_controls_20261123.log) | Uses the original 15,744-face OBJ as reference. Silhouette-error shares were 34.75%, 25.84%, and 25.88%. Exact edge-set matching failed, but the one-to-one oriented map passes a retrospectively chosen one-float32-ULP tolerance. All three cuts are eligible under that rule; exact-face controls still beat the image metrics at 30%, 50%, and 70% wherever an eligible control exists. This remains one-asset development evidence, not confirmation. |
| Current-source Lucy matched-face screen | Original OBJ hash, current binary/source hashes, scorer and helper hashes, package versions, protocol, and per-view records in the [Lucy receipt](tools/mmtrain/lucy_current_source_controls_20261123.json); asset reuse and license are recorded in the [reuse audit](tools/mmtrain/asset_reuse_audits/lucy_20261123.json) | Lucy was already used in earlier experiments and is development-only. The requested 30% cut was infeasible (48.50% actual); all three actual cuts lost to both whole-mesh controls on the listed image metrics. Dirty-source build provenance lacks the exact compiler version and original build command; no held-out claim follows. |
| Current-source matched-face geometry controls | Current `mmgeo` binary and source, comparison script, meshoptimizer helper/module, fast-simplification package version, manifest, upstream receipt, and per-view results in the [matched-face receipt](tools/mmtrain/current_source_matched_face_controls_20261123.json) | The source worktree was dirty; only two reused assets produced under-cap eligible meshoptimizer pairs, and both adjacent wins belong to one asset. This is not held-out evidence. |
| Saved-cut rendered reranking | Historical executable, graph/upstream receipts, and reranking-script SHA-256 in the [reranking receipt](tools/mmgeo/saved_cut_view_rerank_20261122.json) | Git commit for the historical executable and scripts. |
| CGVQM dynamic-LOD screen | Benchmark, upstream dependency, and model-weight hashes in the [validated receipt](tools/mmmetrics/mixed_scene_dynamic_cgvqm_validated_20261123.json) | A ManyMesh repository commit and a complete script/environment hash manifest. |

Therefore the README numbers are traceable to reports, but the legacy Monkey
silhouette/AA and draw-range claims are **not yet reproducible from a verified
source commit**. Before paper submission, every retained result needs a clean
source revision (or archived patch), script and binary hashes, asset/license and
view hashes, hardware/software environment, and raw receipt. Rerun or remove any
headline figure that cannot meet that standard. Do not silently treat script SHA
or an upstream dependency commit as the project source commit.

## Silhouette error

History section 7.9 records Monkey at 7,124 triangles versus an 11,250-triangle
full-detail cut of the ManyMesh DAG, 960x720, `--no-shadows`, camera eye
`(1.982729,1.347563,4.480644)`, target
`(0,-0.015564,0.019503)`. Silhouette XOR covers 0.11% of pixels and contributes
68.3% of squared error. Full-image PSNR is 42.50 dB and common-coverage PSNR is
37.24 dB. This is **not** a comparison against the original 15,744-triangle
Monkey source. The paragraph does not identify the hardware. This is one still
image; the fraction of error explained by its silhouette must not be generalized
to other views or assets.

A new eight-view current-source diagnostic uses the original Monkey OBJ as the
reference. Silhouette-XOR shares were 34.75%, 25.84%, and 25.88% at 30%, 50%,
and 70% requested retention. Exact directed-edge matching failed, but a
retrospective sampled curve audit matched all 168 oriented edges under a
one-to-one coordinate map, within 0.52 float32 epsilon at unit radius; maximum
symmetric deviation was 6.08e-8 normalized units and relative
total-length error of 3.3e-9. At equal
actual face counts, eligible QEM and meshoptimizer controls beat the cuts on
all listed image metrics at 30% and 50%; at 70%, the QEM control itself was
ineligible and meshoptimizer beat the cut. This one-asset result is not
held-out evidence; any confirmation protocol must freeze its boundary-curve
tolerance before scoring. See the [Monkey report](tools/mmtrain/MONKEY_ORIGINAL_SOURCE_DIAGNOSTIC_20261123.md),
[raw receipt](tools/mmtrain/monkey_source_reference_diagnostic_20261123.json),
and [boundary audit](tools/mmtrain/monkey_boundary_curve_audit_20261123.json).

The historical static Monkey CNN and AA comparisons in history sections 7.9 and
7.10 also use a DAG-derived high-detail reference, not the original source mesh.
The 38.00%-retention capture reports +0.14 dB from the cross-asset `tiny` CNN,
+1.43 dB from 4x MSAA, and +0.08 dB when adding the CNN after MSAA. At 29.38%
retention, 4x MSAA gains +1.64 dB and TAA loses 1.84 dB against no AA. These are
fixed-camera grayscale image scores; they do not measure moving-camera temporal
quality, device cost, or user preference. Each AA condition uses a matching
full-detail reference rendered with that AA mode, so differences across modes
are not a strict same-reference ablation.

## Simplification order

History section 7.6, entry dated 2026-10-19, compares new 7,084-triangle Monkey
with old 7,124-triangle Monkey at 960x720, the same camera, and `--no-shadows`.
PSNR/SSIM are 35.50/0.98590 versus 34.61/0.98443; mean absolute differences are
0.002235 versus 0.002421. Local outputs are `out/ab-monkey-priority-montage.png`
and `out/ab-torus-priority-montage.png`. The exact camera transform and hardware
are not specified in this comparison. Do not substitute the silhouette camera.

## Current-source matched-face controls

The fixed-default current-source cluster audit tested 16 cuts across eight reused validation assets. Six passed strict topology and directed-boundary checks; four also stayed under the stock face caps. Its sole exact-face match failed topology. A subsequent fixed parameter grid tested 48 builds and all 96 resulting cuts. It found two exact-face candidates that passed topology and directed-boundary checks, each matching a stock depth-1 cut on a different asset. Both candidates lost against stock on FLIP, PSNR, SSIM, and silhouette XOR. The two-asset parameter-sweep result is descriptive, exploratory, and not held out. Full conditions, per-view metrics, hashes, and every eligibility outcome are in the [parameter-sweep report](tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md).

A separate comparison used whole-mesh meshoptimizer simplification at each valid ManyMesh candidate's actual face count. Three exact-face, topology-valid pairs also remained under the stock face caps: two adjacent levels on asset 263198 and one level on asset 191968. ManyMesh improved FLIP, PSNR, and SSIM on both 263198 levels, but lost substantially on 191968. The only eligible fast-QEM pair was also on 191968, and QEM performed better. The two positive rows are one reused asset; the asset-level sample is two, with no independent test set or inferential statistics. These results are mixed development evidence, not a general quality or SIGGRAPH claim.

A later current-source screen on previously used Stanford Lucy compared three legal DAG cuts with exact-face whole-mesh QEM and meshoptimizer controls against the original full-resolution OBJ. The requested 30% target could not be reached: the coarsest legal cut retained 48.50% of source faces. At each actual face count, ManyMesh lost to both controls on FLIP, PSNR, SSIM, and silhouette XOR across eight fixed views. This is one reused development asset, not held-out evidence; the detailed conditions, license note, hashes, and results are in the [Lucy screen report](tools/mmtrain/LUCY_CURRENT_SOURCE_QUALITY_SCREEN_20261123.md) and [raw receipt](tools/mmtrain/lucy_current_source_controls_20261123.json).

The comparison reference is the original full-resolution source mesh, not a DAG full-detail cut. It used eight orthographic views at 192x192, flat shading, four software samples per pixel, and LDR-FLIP at 67 pixels per degree. The software sampling is not hardware MSAA. Full conditions, every asset/view result, failures, and hashes are in the [matched-face report](tools/mmtrain/CURRENT_SOURCE_MATCHED_FACE_CONTROLS_20261123.md) and [raw receipt](tools/mmtrain/current_source_matched_face_controls_20261123.json). The separate [cluster-cut eligibility report](tools/mmtrain/CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md) documents why this does not constitute a stock cluster-LOD comparison.

## Draw merging

History section 7.7.1 records the **4,626**-triangle Monkey cut at 960x540,
OpenGL, Intel Iris Xe. The original path issues 1,433 draws at 72.0 ms CPU
steady-state frame time; contiguous-range merging issues one draw at 7.4 ms.
Images match exactly. The camera transform is not given. This repairs the original
per-node submission path and establishes neither algorithm novelty nor a mobile
GPU speedup. The earlier homepage's 7,626-triangle count was incorrect.

## Teaser asset provenance

The homepage figure uses [Khronos Suzanne](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/f0920f5b32d172a30efe3f9257e965918831e6ea/Models/Suzanne),
credited to © 2017 UX3D and Norbert Nopper and released under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
The [asset license record](https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/f0920f5b32d172a30efe3f9257e965918831e6ea/Models/Suzanne/README.md)
is pinned with the geometry. The figure renders the full 3,936 faces and a
982-face depth 2 cut from the unmodified meshoptimizer v1.2 demo. It uses a
CPU flat-shaded orthographic view with 20° yaw, 10° pitch, and four samples
per pixel at 384x384 per panel. The colored map marks binary coverage
differences between the renders. The [figure receipt](docs/manymesh/suzanne-lod.json)
records asset and binary hashes along with the measured image metrics.

Rebuild from the pinned Suzanne `glTF/Suzanne.gltf` and `glTF/Suzanne.bin` files
using the demo from the [cluster baseline](tools/mmtrain/UPSTREAM_CLUSTERLOD_SCREEN_20261122.md#reproduce).

```powershell
python tools/mmtrain/build_suzanne_teaser.py --gltf out/deps/suzanne-teaser/glTF/Suzanne.gltf --demo out/deps/meshoptimizer-v1.2/meshoptdemo.exe --font C:/Windows/Fonts/segoeui.ttf --figure docs/manymesh/suzanne-lod.png --receipt docs/manymesh/suzanne-lod.json
```

### Historical Monkey records

A tracked proxy-grid Monkey diagnostic is available, with view labels and an
11,808-triangle budget. See [the experiment](MANYMESH_LEARNED_LOD_RESEARCH.md),
[the rendered panel](tools/mmtrain/results/proxy-grid-20261113/monkey-7b754119.png),
and [paired capture hashes](tools/mmtrain/results/proxy-grid-20261113/paired.json).
The source mesh is [assets/models/monkey/monkey.obj](assets/models/monkey/monkey.obj);
its header identifies a Blender 2.74 OBJ export. Blender's [manual identifies
Suzanne as a gift from old NaN](https://docs.blender.org/manual/en/latest/modeling/meshes/primitives.html),
but it does not state a license for this mesh export. No separate source or
asset-license record was found beside the tracked model. The homepage figure uses
the separately licensed Khronos asset. The three historical Monkey measurements
above describe earlier experiments on the repository asset.
