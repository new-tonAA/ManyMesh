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

Fixed-view Monkey analyses found that silhouette XOR occupied 0.11–0.19% of
pixels but contributed 66.7–68.3% of squared image error. This is a useful
diagnostic, not evidence that a silhouette method generalizes: contour-weighted
geometry has not shown a repeatable quality/cost win, and antialiasing is a
strong baseline. The research problem is to improve image quality after the
same AA or upscaler at matched geometry and total cost, while keeping cluster
boundaries and topology valid. Report image metrics such as LDR-FLIP, PSNR,
SSIM, and silhouette error alongside geometry and topology checks. The cited
Monkey measurements and failed screens are in the [dated history](MANYMESH_HISTORY.md)
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
tolerance and reused development assets; its two all-metric wins were against
meshoptimizer only, not QEM. [Reports and raw metrics](MANYMESH.md#evidence).
The 21-model scoring replay matches byte-for-byte, but its geometry receipts
record a different `main.cpp` hash from the Khronos run despite sharing the
same `mmgeo` binary hash. A clean Release build of current `main` succeeded,
but Windows application control blocked running it, so source-level
reproduction remains unverified. The archived binary regenerated all 18
expanded-cohort candidate PLYs byte-for-byte at their recorded face counts;
this replay does not resolve the source hash conflict or cover the initial
three models. See the [provenance audit](tools/mmtrain/mmgeo_source_provenance_audit_20261124.json),
[geometry replay receipt](tools/mmtrain/polyhaven_geometry_replay_20261125.json),
and [clean rebuild attempt](tools/mmtrain/MMGEO_CLEAN_REBUILD_ATTEMPT_20261125.json).

## Research documents

- [Current status and next decision](MANYMESH.md)
- [SIGGRAPH 2027 research direction](SIGGRAPH_2027_DIRECTION.md)
- [Next experiment gate](MANYMESH_NEXT_EXPERIMENT_GATE.md)
- [Prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md)
- [Dated experiment history](MANYMESH_HISTORY.md)
- [Filament documentation](filament/README.md)
