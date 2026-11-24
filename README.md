# ManyMesh

ManyMesh is a Filament-based research prototype for mesh level of detail
(LOD). It studies the image quality and cost of simplified geometry.
**No SIGGRAPH-ready method or mobile-performance result is established.**

The current 21-model, matched-face screen found that the tested ManyMesh cuts
lost to QEM and meshoptimizer on every reported image metric, both with native
sampling and 4x MSAA. The current research question is whether a specific final
reconstruction pipeline can change that result under legal cluster-DAG
constraints. This is untested and has close prior art.

## The open problem

One fixed 960x720 Monkey view at 45.25% retention measured silhouette XOR at
0.11% of pixels and 68.3% of squared error, but used an 11,250-face DAG cut as
the reference rather than the 15,744-face source mesh. A later eight-view
diagnostic uses the original source and checked-in candidate meshes:
silhouette-XOR pixels account for 34.75%, 25.84%, and 25.88% of squared image
error at 30%, 50%, and 70% retention. At all three budgets the candidate loses
to eligible exact-face QEM and/or meshoptimizer controls on the reported image
metrics. This remains a single-asset exploratory result: its boundary tolerance
was selected retrospectively, the candidate generator binary is unpinned, and
it is not held-out evidence. See the [protocol and results](tools/mmtrain/MONKEY_SOURCE_REFERENCE_DIAGNOSTIC_20261125.md)
and [machine-readable receipt](tools/mmtrain/monkey_source_reference_diagnostic_20261125/receipt.json).
These measurements do not establish a general silhouette-error share.
Silhouette error is important, but its share depends on view and reference;
contour-weighted geometry has not shown a repeatable quality/cost win, and
antialiasing remains a strong baseline. The open question is whether offline
geometry optimization improves image quality after the same AA or upscaler at
matched face count and complete cost, while preserving cluster boundaries and
topology. Report LDR-FLIP, PSNR, SSIM, silhouette, surface, and topology metrics
together. See the [historical decomposition](MANYMESH_HISTORY.md#fixed-camera-4525-error-decomposition),
[source-reference follow-up](MANYMESH_HISTORY.md#12-2026-11-23-original-source-and-asset-feasibility-follow-up),
and [research status](MANYMESH.md).

![Khronos Suzanne at 3,936 and 982 triangles beside a silhouette-difference map.](docs/manymesh/suzanne-lod.png)

*Flat-shaded CPU reference render, 384 x 384 pixels per panel. Center: depth-2
cut from unmodified meshoptimizer v1.2. Right: binary coverage differences.
Asset: UX3D / Norbert Nopper, CC0 1.0. [Figure receipt](docs/manymesh/suzanne-lod.json).*

## Evidence status

| Works in measured scope | Does not pass | Not measured |
|---|---|---|
| Fixed-view desktop image-quality screens and topology/boundary audits. | The tested ManyMesh cut does not beat matched QEM or meshoptimizer controls on the frozen 21-model cohort. | Physical-phone performance, power, equal-frame-time quality, LPIPS, moving-camera temporal quality, user preference, and a held-out optimized method. |

The 21-model result is fixed-view Iris Xe evidence, not mobile or equal-time
evidence. The earlier seven-asset Khronos screen used a retrospective boundary
tolerance and reused development assets; it beat meshoptimizer on two pairs
from one asset and beat no eligible QEM pair. [Reports and raw metrics](MANYMESH.md#evidence-snapshot).
Retained compiler checksums resolve the archived executable's source set:
`main.cpp` matches the Khronos receipt, while `Simplifier.cpp` and
`Simplifier.h` match the Poly Haven pin. A clean Release rebuild from the
reconstructed source commit matches every PE byte except the duplicated build
timestamp fields; `.text` is identical. `Grouper.cpp` lacks an individual
retained source checksum, and the rebuilt executable was not run because
Windows application control blocked it. The archived executable replayed 18
expanded-cohort candidate meshes byte-for-byte at the recorded face counts;
the initial three were not replayed. See the [clean rebuild receipt](tools/mmtrain/mmgeo_clean_rebuild_489_20261125.json),
[compiled-source audit](tools/mmtrain/mmgeo_compiled_source_audit_20261125.json),
[rebuild verifier](tools/mmtrain/verify_mmgeo_clean_rebuild_489_20261125.py),
and [geometry replay receipt](tools/mmtrain/polyhaven_geometry_replay_20261125.json).

## Research documents

- [Current status and next decision](MANYMESH.md)
- [SIGGRAPH 2027 research direction](SIGGRAPH_2027_DIRECTION.md)
- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Filament documentation](filament/README.md)
