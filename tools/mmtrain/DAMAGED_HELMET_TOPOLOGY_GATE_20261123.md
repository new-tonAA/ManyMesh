# Damaged Helmet asset and topology gate

Run on 2026-11-23. This is a development-asset preflight, not a quality result
or a clean confirmation-asset qualification.

## Asset and license provenance

- Local input: `third_party/models/DamagedHelmet/DamagedHelmet.glb`, SHA-256
  `a1e3b04de97b11de564ce6e53b95f02954a297f0008183ac63a4f5974f6b32d8`.
- The tracked local README states that the earlier model is under a Creative
  Commons Attribution-NonCommercial license but omits the version. The current
  Khronos catalog credits the earlier model under CC BY-NC 4.0 and a later
  rebuild/conversion under CC BY 4.0. The [catalog entry](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/Models/Models-core.md)
  and [REUSE manifest](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/REUSE.toml)
  corroborate that provenance, but do not map this local file hash to a pinned
  upstream revision. Treat it as a research/development lead; do not redistribute
  it or call it cleared confirmation data.
- The bounded [reuse audit](asset_reuse_audits/damaged_helmet_20261123.json)
  found no exact hash or name match in 469 scanned text artifacts. This does not
  prove that the model was never used in unarchived runs.

## Geometry extraction and feasibility

The revised [GLB extractor](extract_static_gltf_geometry.py) applies the default
scene's node world transform and exports one static triangle-list primitive.
It omits animation, skinning, materials, and textures. The
[extraction receipt](asset_reuse_audits/damaged_helmet_geometry_extraction_20261123.json)
pins the local input, extractor, and OBJ output: 14,556 exported positions and
15,452 triangles. `mmgeo` imported 8,661 welded positions and the same face
count, then built 513 DAG nodes across nine levels. See the archived
[mmgeo log](asset_reuse_audits/damaged_helmet_mmgeo_20261123.log).

The source has 1,820 boundary edges and seven non-manifold or inconsistently
oriented edges under the recorded topology check. The selected 30% cut still
has four such edges. The exact-face control scorer therefore rejected the
source at its strict topology-validation stage, before rendering or computing
image metrics. No QEM/meshoptimizer quality comparison was produced. The
[topology-gate receipt](asset_reuse_audits/damaged_helmet_topology_gate_20261123.json)
records the binary, scripts, archived logs, face counts, and rejection reason.
The scorer's [failure log](asset_reuse_audits/damaged_helmet_control_rejection_20261123.log)
shows that it stopped before image metrics.

**Decision:** keep this input only for importer and development diagnostics.
Do not repair or exclude components after seeing quality results and then report
the modified asset as the original-source comparison. Any future use needs a
predeclared topology policy, a byte-specific license/provenance record, and a
new eligibility screen before metrics are scored.
