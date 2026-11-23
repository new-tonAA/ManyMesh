# Control indexing and face target checks

Exact position welding recovered legal whole mesh controls for
DiffuseTransmissionTeacup at 8,456 faces. The corresponding ManyMesh cut
still failed the source boundary check. At about 30% retention,
MaterialsVariantsShoe remains the only one of the nine screened development
assets with a legal, exact face comparison across all three methods.

This screen kept the same source geometry, candidate cuts, and face
targets as the prior runs. Both controls were run twice with their existing
preserve border flags. One run retained the original indices. The other
merged positions that were exactly equal in the normalized float32
coordinate frame. The reference geometry and boundary gate stayed fixed.

| Asset | Target faces for controls | Original indexing | Exact position welding |
|---|---:|---|---|
| AnisotropyBarnLamp | 3,061 | Neither control eligible | Neither control eligible |
| CommercialRefrigerator | 62,603 | QEM only | QEM only |
| DiffuseTransmissionTeacup | 8,456 | Both returned 28,184 faces | Both eligible |
| GlassBrokenWindow | 296 | Neither control eligible | Neither control eligible |
| GlassHurricaneCandleHolder | 1,234 | meshoptimizer only | meshoptimizer only |
| MaterialsVariantsShoe | 6,810 | Both eligible | Both eligible |
| PotOfCoals | 5,467 | Both returned 18,223 faces | Both rejected for duplicate geometric triangles |
| ScatterPlant | 16,347 | Neither control eligible | Both rejected for duplicate geometric triangles |
| SpecularSilkPouf | 24,374 | meshoptimizer only | meshoptimizer only |

GlassBrokenWindow and ScatterPlant missed the 29% to 31% band. Their
controls targeted the nearest integer to 30% of the source. The older
seven asset screen compared controls to the exported candidate count for
GlassBrokenWindow, which was 381 faces at the requested 30% setting.

The two assets with otherwise eligible ManyMesh and meshoptimizer cuts
but duplicate triangles in QEM were checked again at requested 29.5%
and 30.5%. Both GlassHurricaneCandleHolder requests returned the same
1,190 face cut, below the 29% band. SpecularSilkPouf had legal 23,972
and 24,790 face ManyMesh and meshoptimizer cuts. QEM continued to return
duplicate geometric triangles on both. These extra cuts used the controls'
original indexing.

To reproduce, use the [preflight command](APPEARANCE_INPUT_PREFLIGHT_20261123.md)
with and without `--weld-controls`. The source and cut hashes,
exact face counts, and eligibility failures for every arm are recorded in
the [JSON receipt](appearance_control_indexing_20261123.json). The first
two asset preflight remains pinned to its original
[script revision](https://github.com/new-tonAA/ManyMesh/blob/7b815599b3d167a151822bc95a996b5dbc1fd893/tools/mmtrain/preflight_appearance_meshes.py).
This comparison measured input eligibility. Image scores and the CUDA
appearance fitting experiment remain separate.
