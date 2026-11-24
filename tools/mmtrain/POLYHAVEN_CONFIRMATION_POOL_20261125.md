# Poly Haven Confirmation Candidate Pool — 2026-11-25

## Status

This is a **reserved, unscored candidate pool**, not a result and not yet the
final camera/view test protocol. It contains 30 source models that pass the
pre-score source and matched-face checks, representing 25 slug-family groups
across nine top-level categories. No rendered images, image-quality metrics,
or method rankings were used to choose or retain these assets.

The pool is reserved for a later independent confirmation after the frozen
two-asset placement control and final method configuration are resolved. Before
any quality scoring, freeze the camera split, renderer, lighting, reference,
metrics, and practical-effect margins. If the control fails and the method
changes, these assets remain unscored.

## Selection and eligibility

Two deterministic batches were selected from the pinned Poly Haven catalog
snapshot, excluding the previously selected 76 asset slugs. The first batch
contained 57 models from six catalog classes; the second contained 90 models,
six per category across 15 catalog top-level categories. Both selection rules
used category, catalog face-count range (250–250,000), and ascending slug only.
All are CC0 under the pinned Poly Haven terms; acquisition receipts retain the
per-asset source URLs, credits, API checksums, and SHA-256 values.

| Candidate batch | Selected | Geometry extracted | Source topology pass | Exact-face triplets |
|---|---:|---:|---:|---:|
| Fresh six-class batch | 57 | 57 | 48 | 14 |
| Broad category batch | 90 | 87 | 65 | 16 |

For each source-topology pass, the pinned `mmgeo` build generated one ManyMesh
cut near 50% retention. QEM and meshoptimizer were then required to match that
cut's exact face count. A model qualified only when all three outputs passed
the recorded triangle/edge topology checks and preserved the source boundary.
No face, boundary, or topology gate was relaxed to increase the sample count.

The two batches contribute 30 exact-face triplets. After grouping numeric slug
variants as one source-family unit, 25 groups remain. The six-model-class batch
contributes food, tools, and decor assets; the broad batch adds containers,
lighting, electronics, apparel, vehicles, and leisure, for nine top-level
categories overall. Across the 222 source-file records retained for the
previous and new candidate screens, all 222 glTF hashes and all 222 binary
buffer hashes are unique. The 30 reserved assets also have unique extracted
geometry hashes.

The deterministic family rule removes a trailing underscore and digits from
the slug. It groups `brass_vase_03/04`, `ceramic_vase_01–04`, and
`brass_pot_01/02`; all other reserved assets form individual groups. The pool
has 30 models across 25 groups, so uncertainty should be paired and aggregated
over those groups rather than treating same-series variants as independent.

## Reserved assets

| Category | Asset | Source faces | Faces in each control | Family group |
|---|---|---:|---:|---|
| Food & Kitchen | `croissant` | 1,990 | 992 | `croissant` |
| Food & Kitchen | `sweet_potato` | 2,042 | 1,014 | `sweet_potato` |
| Food & Kitchen | `wooden_cutting_board` | 3,520 | 1,748 | `wooden_cutting_board` |
| Tools & Equipment | `Drill_01` | 2,926 | 1,462 | `Drill` |
| Tools & Equipment | `cross_pein_hammer` | 2,124 | 1,060 | `cross_pein_hammer` |
| Tools & Equipment | `crowbar_01` | 2,300 | 1,142 | `crowbar` |
| Decor & Art | `brass_vase_03` | 2,616 | 1,302 | `brass_vase` |
| Decor & Art | `brass_vase_04` | 2,760 | 1,378 | `brass_vase` |
| Decor & Art | `bronze_ray_statue` | 1,844 | 922 | `bronze_ray_statue` |
| Decor & Art | `carved_wooden_elephant` | 2,752 | 1,376 | `carved_wooden_elephant` |
| Decor & Art | `ceramic_vase_01` | 10,296 | 5,148 | `ceramic_vase` |
| Decor & Art | `ceramic_vase_02` | 11,128 | 5,564 | `ceramic_vase` |
| Decor & Art | `ceramic_vase_03` | 11,136 | 5,568 | `ceramic_vase` |
| Decor & Art | `ceramic_vase_04` | 9,000 | 4,500 | `ceramic_vase` |
| Containers & Storage | `all_purpose_cleaner` | 4,624 | 2,312 | `all_purpose_cleaner` |
| Containers & Storage | `bleach_bottle` | 4,052 | 2,024 | `bleach_bottle` |
| Lighting | `Chandelier_02` | 21,514 | 10,756 | `Chandelier` |
| Lighting | `Lantern_01` | 33,902 | 16,950 | `Lantern` |
| Electronics & Appliances | `barrel_stove` | 9,216 | 4,608 | `barrel_stove` |
| Apparel & Personal Items | `garden_gloves_01` | 6,822 | 3,410 | `garden_gloves` |
| Food & Kitchen | `brass_goblets` | 9,600 | 4,800 | `brass_goblets` |
| Food & Kitchen | `brass_pot_01` | 3,760 | 1,880 | `brass_pot` |
| Food & Kitchen | `brass_pot_02` | 3,344 | 1,670 | `brass_pot` |
| Food & Kitchen | `ceramic_pot` | 3,592 | 1,794 | `ceramic_pot` |
| Decor & Art | `hanging_picture_frame_03` | 24,348 | 12,174 | `hanging_picture_frame` |
| Decor & Art | `horse_head` | 12,068 | 6,034 | `horse_head` |
| Decor & Art | `katana_stand_01` | 3,780 | 1,890 | `katana_stand` |
| Vehicles & Transport | `lifebuoy` | 10,728 | 5,364 | `lifebuoy` |
| Leisure | `baseball_01` | 10,848 | 5,424 | `baseball` |
| Leisure | `baseball_bat` | 2,672 | 1,336 | `baseball_bat` |

## Reproduction and evidence

The source selection, acquisition/topology receipts, matched-face receipts, and
assembled pool manifest are checked in alongside this report:

- [Fresh six-class selection](polyhaven_fresh_asset_pool_selection_20261125.json),
  [source screen](polyhaven_fresh_asset_source_screen_20261125.json), and
  [matched-face preflight](polyhaven_fresh_asset_matched_face_screen_20261125.json).
- [Broad category selection](polyhaven_category_pool_selection_20261125.json),
  [source screen](polyhaven_category_pool_source_screen_20261125.json), and
  [matched-face preflight](polyhaven_category_pool_matched_face_screen_20261125.json).
- [Machine-readable reserved pool](polyhaven_confirmation_pool_20261125.json)
  and [selection/preflight assembler](assemble_polyhaven_confirmation_pool.py).
- Selection tools: [six-class selector](select_polyhaven_fresh_asset_pool.py)
  and [broad-category selector](select_polyhaven_category_pool.py).

The acquisition script verified the live Poly Haven API file size and MD5 for
each downloaded glTF and declared geometry buffer. The geometry extractor
does not support every glTF feature: two selected assets could not be extracted
because of morph targets or skinning, and one asset lacked a 1K glTF. These
three are absent from the qualifying pool; their failures remain visible in the
source-screen receipt. The topology preflight also does not test geometric
self-intersections. No image scoring has been run on this pool.
