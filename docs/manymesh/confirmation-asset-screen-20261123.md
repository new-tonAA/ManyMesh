# Independent asset screen: first Khronos candidates

**Status: one candidate passes a geometry preflight; no confirmation set is frozen.** This is a source, provenance, extraction, and topology screen only. No images were scored and no simplifier or differentiable optimizer was run.

**Historical status:** this describes the initial 2026-11-23 screen. The current
30-model confirmation pool and evaluation protocol were frozen on 2026-11-25;
see the [current pool report](../../tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md)
and [protocol](../../tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

## Pinned source and licenses

Both files came from Khronos glTF Sample Assets at commit [`e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea`](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models). The model bytes are not included in this repository.

| Model | Per-model source and license | Attribution | Geometry screen |
|---|---|---|---|
| [CarConcept](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CarConcept) | [README](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CarConcept/README.md), [license](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CarConcept/LICENSE.md), [metadata](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CarConcept/metadata.json). CC BY 4.0 model files; Khronos and 3D Commerce marks are separately identified and excluded from the model license. | Eric Chadwick; Darmstadt Graphics Group GmbH. The README also describes the public-domain Unity Fan source; those source terms do not replace the final asset's license. | **Fail.** 213,347 triangles, 4 duplicate geometric faces, 146 nonmanifold edges, 22 inconsistently oriented edges. Do not score. |
| [CommercialRefrigerator](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CommercialRefrigerator) | [README](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CommercialRefrigerator/README.md), [license](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CommercialRefrigerator/LICENSE.md), [metadata](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/CommercialRefrigerator/metadata.json). CC BY 4.0. | Eric Chadwick / Darmstadt Graphics Group GmbH and Sean Thomas, whose source Sketchfab model is also listed as CC BY 4.0. | **Provisional pass.** 208,679 triangles; 377 exact-welded components; 6,625 boundary edges; zero duplicate or degenerate faces; zero nonmanifold or inconsistently oriented edges. One node animation is ignored; the extraction uses the default scene transforms. |

The GLB SHA-256 values are `c272098089d78c5cd9fd9f24ff50ee8acf8d932c55f2d55fc10adb6c8998966b` (CarConcept) and `ef8da8b144e650c277ac953e6d9e50ac1689ff1ee88c2c5bd9551ae8bccb6065` (CommercialRefrigerator). A bounded scan of 477 first-party text artifacts found no filename, stem, or exact-hash matches for either source binary. This scan cannot prove that an asset was never used in unarchived or non-text experiments.

## Receipts and limits

- The [pinned source manifest](../../tools/mmtrain/asset_reuse_audits/khronos_source_manifest_20261123.json) records GLB, README, license, and metadata hashes for both assets.
- CarConcept: [source-use receipt](../../tools/mmtrain/asset_reuse_audits/car_concept_20261123.json), [extraction receipt](../../tools/mmtrain/asset_reuse_audits/car_concept_geometry_extraction_20261123.json), [topology receipt](../../tools/mmtrain/asset_reuse_audits/car_concept_topology_20261123.json).
- CommercialRefrigerator: [source-use receipt](../../tools/mmtrain/asset_reuse_audits/commercial_refrigerator_20261123.json), [extraction receipt](../../tools/mmtrain/asset_reuse_audits/commercial_refrigerator_geometry_extraction_20261123.json), [topology receipt](../../tools/mmtrain/asset_reuse_audits/commercial_refrigerator_topology_20261123.json).
- The [multi-instance static GLB extractor](../../tools/mmtrain/extract_static_gltf_geometry.py) merges default-scene triangle primitives in world space, omitting materials and animation channels and rejecting skinning or morph targets. The [OBJ topology auditor](../../tools/mmtrain/audit_static_obj_topology.py) uses exact-coordinate welding and records open boundaries; it does not assess semantics, visual quality, or near-coincident seams.

At the time of this initial screen, CommercialRefrigerator was the only provisional asset; CarConcept failed and must not be repaired after inspection and counted as a pass. Later pinned-source work added ScatterPlant and seven more geometry-pass candidates, documented in the [follow-up screens](khronos-followup-candidates-20261123.md) and [expanded candidate screen](khronos-expanded-candidate-screen-20261123.md). The combined pool is still not a frozen training/validation/test split, and no image-quality result exists. Do not call it a held-out benchmark. The remaining data gate is to finish per-asset source records, freeze category/exclusion rules, and build the required 20-asset, five-category set before method scores are examined.
