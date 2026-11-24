# Poly Haven geometry candidate preflight

Twelve of twenty preselected CC0 models passed the static source topology
audit across five categories. Seven failed a topology check. One model
requires skinning support. The screen ran before image scoring or method
selection. The assets form a provisional pool for the separate confirmation
set.

| Category | Passes | Candidates that passed |
|---|---:|---|
| Furniture | 2 / 4 | Gothic Cabinet, Coffee Table |
| Botanical | 3 / 4 | Anthurium, Calathea, Crystalline Iceplant |
| Rock | 3 / 4 | Boulder, Rock 09, Stone 01 |
| Food | 3 / 4 | Bananas, Carrot Cake, Food Apple |
| Tools | 1 / 4 | Bunsen Burner |

Failures included degenerate or duplicate faces, nonmanifold edges, and
inconsistent face orientation. Dandelion had 64 inconsistently oriented
edges. Moon Rock 01 had 318 duplicate triangles and 1,154 nonmanifold edges.
The extractor refused the skinned Bench Vice and did not audit its bind-pose
geometry. The full [receipt](polyhaven_candidate_topology_20261124.json)
lists the preselected models, credits, every failure, original file hashes,
and exported geometry counts. Catalogue polygon counts and extracted face
counts have separate fields because the 1K representations can differ.

The literal prior-use scan found no slug or source hash matches for the
twelve passing models in the recorded public research files at the pinned
revision. Renamed duplicates, private captures, and older unrecorded uses
remain outside that check. Geometric duplicates across datasets and final
class balance still need verification.

## Fixed 50% matched-face preflight

Three of the twelve source passes supplied legal exact-face ManyMesh,
QEM, and meshoptimizer cuts. All twelve ManyMesh cuts landed within
the predeclared 49–51% band. Two of those cuts failed the topology audit.
The table lists each failed arm. It contains no image or runtime ranking.

| Asset | Source faces | Target from ManyMesh | Failed arms |
|---|---:|---:|---|
| GothicCabinet_01 | 12,170 | 6,084 | ManyMesh, QEM |
| CoffeeTable_01 | 10,404 | 5,202 | QEM |
| anthurium_botany_01 | 67,152 | 33,576 | ManyMesh, meshoptimizer |
| calathea_orbifolia_01 | 16,688 | 8,344 | meshoptimizer |
| crystalline_iceplant | 13,094 | 6,546 | — |
| boulder_01 | 66,122 | 33,060 | QEM, meshoptimizer |
| rock_09 | 12,416 | 6,208 | — |
| stone_01 | 53,520 | 26,760 | QEM, meshoptimizer |
| bananas | 46,868 | 23,434 | meshoptimizer |
| carrot_cake | 13,790 | 6,894 | QEM, meshoptimizer |
| food_apple_01 | 7,012 | 3,506 | — |
| bunsen_burner | 8,434 | 4,216 | QEM |

Use the [matched-input commands](MATCHED_APPEARANCE_INPUTS_20261124.md#reproduce-the-inputs)
with `--target-ratio 0.5 --target-ratio-cut 0.5` on `mmgeo` to request a
single cut. Then use `--target-ratio 0.5` on the preflight. The run uses
the previously pinned research binary, with the SHA-256 recorded in the
[matched-face receipts](polyhaven_matched_face_20261124.json). Both controls
target each actual ManyMesh face count and use the original input indices.
Use a separate directory and `--export-obj-dir` to reproduce the three
eligible exports. The geometry is reserved and remains unscored.

## Reproduce

Powered by [Poly Haven](https://polyhaven.com/). The catalogue and the 1K
geometry manifest came from the [Poly Haven Public API](https://github.com/Poly-Haven/Public-API).
The [terms](https://github.com/Poly-Haven/Public-API/blob/master/ToS.md) identify
the downloaded 3D assets as CC0. The receipt includes both download URLs,
published checksums, and SHA-256 digests. Fetch the declared `.gltf` and its
single `.bin` buffer, then verify the hashes before reading either. Texture
images were omitted. Source and extracted mesh files remain local.

Use `extract` and `write_obj` from
[extract_static_gltf_geometry.py](extract_static_gltf_geometry.py) as in the
[separate-buffer Khronos preflight](KHRONOS_SEPARATE_BUFFER_PREFLIGHT_20261124.md#source-and-reproduction).
Substitute the input names from the receipt. Run
[audit_static_obj_topology.py](audit_static_obj_topology.py) on the extracted
OBJ. The check welds exact positions and diagnoses triangle and directed-edge
errors. It permits open boundaries and does not measure self-intersections,
near-coincident seams, or image quality.
