# Geometry eligibility screen for four more Khronos assets

Four original meshes passed the source topology audit. Zero supplied a
complete set of legal, exact-face ManyMesh, border-preserving QEM, and
meshoptimizer LockBorder meshes near 30% retention. This was a geometry
preflight. It measured neither image quality nor runtime.

| Asset | Original faces | ManyMesh faces and retention | QEM | meshoptimizer |
|---|---:|---:|---|---|
| Avocado | 682 | 312 (45.75%) | 204 of 205 requested | 204 of 205 requested |
| BarramundiFish | 3,864 | 1,146 (29.66%) | 1,146, eligible | 1,146, duplicate geometric triangle |
| Corset | 18,324 | 5,498 (30.00%) | Duplicate geometric triangle | 5,498, duplicate geometric triangle |
| WaterBottle | 4,510 | 1,284 (28.47%) | 1,352 of 1,353 requested | 1,352 of 1,353 requested |

All four ManyMesh cuts passed the recorded topology and oriented-boundary
checks. Avocado and WaterBottle fell outside the 29% to 31% band, so their
controls targeted the nearest integer to 30% of the source face count.
BarramundiFish and Corset controls targeted the actual ManyMesh counts. The
screen used the original input indices and the same boundary tolerance and
`mmgeo` executable as the [two-asset preflight](APPEARANCE_INPUT_PREFLIGHT_20261123.md).
The results apply to this one operating point and these control settings.

## Source and reproduction

The [pinned Khronos revision](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/e124e8d8d7330a5372bc2b4d00d39a4a9d7997ea/Models)
provides each source in `Models/<asset>/glTF/`. Use the `.gltf` and its single
associated `.bin`. All four geometries are CC0 1.0, credited to Microsoft
with UX3D listed as the copyright holder for Corset. Use the model's own
`LICENSE.md` and `README.md` for attribution. The
[receipts](khronos_separate_buffer_preflight_20261124.json) preserve Git blob
IDs and SHA-256 hashes for both inputs and the source notices. They also
include the exported OBJ digest, source topology, runner versions, and
preflight output. No original assets or mesh binaries are included here.

From the repository root, point `asset` at a directory containing the two
source files, then run this extraction with the research Python dependencies
from the [quality screen](KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md).

```python
import json
from pathlib import Path
import sys

sys.path.insert(0, "tools/mmtrain")
from extract_static_gltf_geometry import extract, write_obj

asset = Path("out/appearance-asset-intake-20261124/BarramundiFish")
document = json.loads((asset / f"{asset.name}.gltf").read_bytes())
binary = (asset / f"{asset.name}.bin").read_bytes()
buffer, = document["buffers"]
assert buffer["uri"] == f"{asset.name}.bin"
assert len(binary) == buffer["byteLength"]
positions, triangles, _ = extract(document, binary)
write_obj(asset / "geometry.obj", positions, triangles)
```

Verify the OBJ digest against the receipt. Reuse the 30% commands in the
[two-asset preflight](APPEARANCE_INPUT_PREFLIGHT_20261123.md#protocol-and-reproduction)
with the corresponding source path, digest, and output directory. These are
provisional inputs for geometry feasibility, not an independent test set.
