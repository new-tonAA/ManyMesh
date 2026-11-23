# Input preflight for appearance driven simplification

CommercialRefrigerator and ScatterPlant both failed to supply legal meshes at a
common face count near 30% of the source. Their original geometry had passed the
source topology audit. This run checked eligibility before any image scoring.

| Asset | Source faces | ManyMesh cut | QEM with preserved border | meshoptimizer LockBorder |
|---|---:|---|---|---|
| CommercialRefrigerator | 208,679 | 62,603 (30.00%). Has 6,623 boundary edges versus 6,625 on the source. Fails the boundary check. | 62,603. Passes both checks. | 62,603. Contains a duplicate geometric triangle. |
| ScatterPlant | 54,491 | 19,791 (36.32%). Missed the target band and triggered the nonmanifold or edge orientation check. | 51,007. Preserves the boundary but exceeds the 16,347 face target. | 50,773. Preserves the boundary but exceeds the 16,347 face target. |

The 6,623 figure is the cut's total boundary edge count. The audit does not
identify which source edges were lost or changed. Each control for the
refrigerator targeted the actual ManyMesh face count. For the plant, the
ManyMesh cut missed the target band, so the controls were run independently
at the nearest integer to 30% of the original face count. Control counts are
outputs of these implementations under the recorded settings.

## Protocol and reproduction

The experiment used one setting per asset. The allowed band for the ManyMesh
cut was 29% to 31%. Control comparisons required identical face counts.
The topology audit uses exact position welding in normalized coordinates and
rejects degenerate faces, duplicate geometric triangles, and nonmanifold or
inconsistently oriented edges. The boundary gate requires a bijection of
oriented endpoints within one float32 epsilon in the common source frame.
That tolerance was chosen after the earlier seven asset screen and fixed for
these two assets. This preflight checks edges and faces. Additional checks
are needed for self intersections and consistency between neighboring DAG cuts.

The assets come from pinned Khronos glTF Sample Assets revision
`e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea`. The source and extraction records
include hashes and credits for geometry from Sean Thomas, Eric Chadwick and
Darmstadt Graphics Group GmbH (CommercialRefrigerator, CC BY 4.0), and Rico
Cilliers and Eric Chadwick (ScatterPlant, CC0 1.0 and CC BY 4.0). The extraction
keeps default scene geometry and omits materials and animation. See the
[refrigerator source record](../../docs/manymesh/confirmation-asset-screen-20261123.md)
and [plant source record](../../docs/manymesh/khronos-followup-candidates-20261123.md).

Use the command below with the isolated research Python environment from the
[earlier quality screen](KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md).
Repeat for ScatterPlant using its extracted OBJ and the expected hash from
the [receipts](appearance_input_preflight_20261123.json).

```powershell
$sourceObj = 'out/khronos-confirmation-assets/extracted/commercial_refrigerator.obj'
$sourceSha = 'b0974c47abf35cc83cb4044791616755cf7309428230bd88389ff4d8368eb786'
$mmgeo = 'out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe'
$runDir = 'out/appearance-input-preflight-20261123/CommercialRefrigerator'
& $mmgeo $sourceObj --out $runDir --mode dag --levels 8 --ratio 0.5 `
  --target-ratio 0.3 --target-ratio-cut 0.3 --quality-gate 1 --cluster-tris 128 `
  --dag-group 4 --dump-format ply --visibility 0 --write-dag 0
python tools/mmtrain/adapt_position_ply.py --input "$runDir/selected_ratio_0.3.ply" `
  --output "$runDir/adapted.ply" --receipt "$runDir/adapter.json"
python tools/mmtrain/preflight_appearance_meshes.py --source $sourceObj `
  --source-sha256 $sourceSha --candidate "$runDir/adapted.ply" `
  --mmgeo $mmgeo --output "$runDir/receipt.json"
```

The mmgeo executable is the same research build used in the seven asset
screen. Its binary hash, archived source delta and rebuild limitations are
recorded in that report. The [preflight script](preflight_appearance_meshes.py)
and [JSON receipts](appearance_input_preflight_20261123.json) record the
host dependency versions, output counts, and hashes. Mesh binaries remain
local.

## Consequence for the CUDA baseline

Both assets lack a complete set of legal inputs at this operating point.
The preflight can be repeated on further cleared geometry before GPU time is
used. The local environment reported PyTorch 2.7.1+cpu, no CUDA build, and
`torch.cuda.is_available() == False`.

The published nvdiffmodeling example jointly fits positions and material maps.
A positions only adaptation needs explicit material and camera controls.
Preserve a common source frame and reserve camera directions before fitting.
The upstream code normalizes the meshes independently before alignment and
samples random training camera rotations. Record any setup changes and
compare the fitted mesh against its own initialization at identical topology.
Report the upstream joint fit separately if it is run. The NVIDIA license
limits upstream use to noncommercial research or evaluation. Keep that source
as an external dependency for the baseline. [Upstream repository](https://github.com/NVlabs/nvdiffmodeling) ·
[Training code](https://github.com/NVlabs/nvdiffmodeling/blob/main/train.py) ·
[License](https://github.com/NVlabs/nvdiffmodeling/blob/main/LICENSE.txt)
