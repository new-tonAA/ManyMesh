# Khronos follow-up asset screen

Updated 2026-11-23. **This is an asset-feasibility screen, not a quality experiment.** The five model directories were fetched from the pinned Khronos glTF Sample Assets commit [`e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea`](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models). GLB binaries are not redistributed here. The source manifest records each downloaded file's byte size and SHA-256, including the model README, license, and metadata.

**Historical status:** these candidates were screened before the current
30-model confirmation pool was frozen. For current inclusion, split, and
scoring status, see the [pool report](../../tools/mmtrain/POLYHAVEN_CONFIRMATION_POOL_20261125.md)
and [evaluation protocol](../../tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md).

| Model | Source credit and model-file terms | GLB bytes / SHA-256 | Geometry-only static screen | Bounded prior-use scan |
|---|---|---|---|---|
| [DiffuseTransmissionPlant](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/DiffuseTransmissionPlant/LICENSE.md) | Original asset: Rico Cilliers, CC0-1.0. Materials and animation: Eric Chadwick, CC BY 4.0. Preserve both credits. | 5,759,100 / `1748be8847e24bdd5cb6c5ac2bfd0afe8f11efc4f85091148550555e47c7ee83` | 50,369 vertices, 68,409 triangles; 219 components, 1,715 boundary edges, 8 nonmanifold edges. **Fail.** | [0 / 277](../../tools/mmtrain/asset_reuse_audits/khronos_diffusetransmissionplant_20261123.json). |
| [MosquitoInAmber](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/MosquitoInAmber/LICENSE.md) | Model: Loic Norgeot, CC BY 4.0. Real-time refraction: Sketchfab, CC BY 4.0. | 24,229,904 / `1c0b49000650e8a8c00d69bc8d64e46d33527871a47d74e4f2278887325cc35f` | 18,678 vertices, 14,349 triangles; 1,208 components, 4,208 boundary edges, 157 nonmanifold edges, 99 inconsistently oriented edges. **Fail.** | [0 / 277](../../tools/mmtrain/asset_reuse_audits/khronos_mosquitoinamber_20261123.json). |
| [ScatterPlant](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/ScatterPlant/LICENSE.md) | Original asset: Rico Cilliers, CC0-1.0. Materials and animation: Eric Chadwick, CC BY 4.0. Preserve both credits. | 9,409,444 / `4d6d44c61c8986706b56cfe41a96cd19b28389924507ea24e982a2f9d1cd4150` | 132,222 vertices, 54,491 triangles; 517 components and 14,829 boundary edges; no duplicate/degenerate faces, nonmanifold edges, or orientation conflicts in the exact-weld audit. **Provisional geometry pass.** The large number of components and open edges still needs semantic inspection. | [0 / 277](../../tools/mmtrain/asset_reuse_audits/khronos_scatterplant_20261123.json). |
| [SheenWoodLeatherSofa](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/SheenWoodLeatherSofa/LICENSE.md) | Original asset: Fran Calvente, CC0-1.0. Improvements: Eric Chadwick, CC BY 4.0. Preserve both credits. | 10,107,912 / `5349e042ad41e695e89f1110230c4ee0c75b2bc62ef830c7016be6ecf665bfb6` | 139,476 vertices, 46,492 triangles; 1,224 duplicate faces, 3,025 nonmanifold edges, and 415 orientation conflicts. **Fail.** | [0 / 277](../../tools/mmtrain/asset_reuse_audits/khronos_sheenwoodleathersofa_20261123.json). |
| [ToyCar](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models/ToyCar/LICENSE.md) | Initial model: Guido Odendahl, CC0-1.0. Extensions and scene composition: Eric Chadwick, CC0-1.0. Preserve both credits. | 5,422,412 / `01a60862de55cd4b9f3acfab0b0def86451800f9c42467fcd61052c16cb9838c` | Not extracted. | [Exclude: 4 stem matches](../../tools/mmtrain/asset_reuse_audits/khronos_toycar_20261123.json); these are not byte-hash matches, but require resolving prior use before reuse. |

## What this establishes

ScatterPlant is a second provisional topology-pass geometry candidate alongside CommercialRefrigerator from the earlier screen. This does not make a held-out pair: both are source-feasibility candidates, the same dataset policy has not been frozen, and no rendered quality or optimization comparison was performed. ScatterPlant's 517 connected components and 14,829 boundary edges warrant inspecting what is being simplified before treating the model as a meaningful test object. The other three new assets failed the recorded strict geometry gate; do not repair or filter them after seeing scores and then count them as passes.

The reuse scan used [`audit_asset_reuse.py`](../../tools/mmtrain/audit_asset_reuse.py) on the public research checkout at commit `d00cd8b68fd9ac5635af9afde22a6471dd2aaba3`, scanning 277 text artifacts for each source GLB's exact SHA-256, filename, or stem. No match is bounded evidence only: it cannot rule out unarchived use, different filenames, or geometric derivatives. ToyCar had four stem matches and no claim of exact-byte identity.

The extractor combines all default-scene static triangle primitives at default node transforms. It ignores animation channels and materials and does not support skinning or morph targets. The topology check welds exact-coordinate vertices; it is not a semantic or visual-quality judgment and does not check near-coincident seams. A topology pass alone does not qualify an asset for training, validation, or confirmation.

## Receipts

- [Pinned source manifest: file sizes and hashes](../../tools/mmtrain/asset_reuse_audits/khronos_followup_source_manifest_20261123.json)
- ScatterPlant [extraction receipt](../../tools/mmtrain/asset_reuse_audits/khronos_scatterplant_geometry_20261123.json) and [topology receipt](../../tools/mmtrain/asset_reuse_audits/khronos_scatterplant_topology_20261123.json)
- The other three geometry failures: [DiffuseTransmissionPlant](../../tools/mmtrain/asset_reuse_audits/khronos_diffusetransmissionplant_topology_20261123.json), [MosquitoInAmber](../../tools/mmtrain/asset_reuse_audits/khronos_mosquitoinamber_topology_20261123.json), and [SheenWoodLeatherSofa](../../tools/mmtrain/asset_reuse_audits/khronos_sheenwoodleathersofa_topology_20261123.json)
- Earlier [CommercialRefrigerator and CarConcept screen](confirmation-asset-screen-20261123.md)

There are still only two provisional geometry-pass assets, concentrated in two object categories, and no licensed, category-balanced, frozen 20-asset confirmation set. No image metric or SIGGRAPH method claim follows from this screen.
