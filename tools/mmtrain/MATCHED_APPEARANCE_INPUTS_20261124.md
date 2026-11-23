# Equal-face inputs for the appearance baseline

Four Khronos assets have eligible ManyMesh, border-preserving QEM, and
meshoptimizer LockBorder cuts at the fixed 50% request. All three controls
have the same triangle count on each asset and match the source's directed
boundary under the recorded tolerance. None of the five requests near 30%
supplied an eligible set. These are geometry results collected before scoring
images or running an optimizer.

| Asset | Source faces | Faces per control | Retention | Source boundary edges |
|---|---:|---:|---:|---:|
| Avocado | 682 | 338 | 49.56% | 38 |
| BarramundiFish | 3,864 | 1,932 | 50.00% | 0 |
| Corset | 18,324 | 9,162 | 50.00% | 1,144 |
| WaterBottle | 4,510 | 2,254 | 49.98% | 264 |

Use BarramundiFish and Corset for the first CUDA baseline. This pair covers
distinct object classes and takes the largest source in each of the closed
and open boundary classes. Avocado and WaterBottle remain additional
development cases. The asset and face-count choices are frozen in the
[receipts](matched_appearance_inputs_20261124.json). The experiment still
needs a fixed optimizer protocol and a separate confirmation cohort. The
assets come from the [geometry-only CC0 screen](KHRONOS_SEPARATE_BUFFER_PREFLIGHT_20261124.md).

## Reproduce the inputs

Reuse the [30% preflight](APPEARANCE_INPUT_PREFLIGHT_20261123.md#protocol-and-reproduction)
build command and Python environment. Set `--target-ratio` on `mmgeo` to
`0.29` and set `--target-ratio-cut` to
`0.29,0.295,0.3,0.305,0.31,0.49,0.495,0.5,0.505,0.51`. The DAG build and
boundary gate are unchanged. Audit the 30% and 50% windows separately, each
with a one-percentage-point retention band. For the frozen input, adapt
`selected_ratio_0.5.ply`, then run this from the repository root with the
working paths and source OBJ hash from the geometry receipt.

```powershell
python tools/mmtrain/adapt_position_ply.py --input "$runDir/selected_ratio_0.5.ply" `
  --output "$runDir/adapted_0.5.ply" --receipt "$runDir/adapter_0.5.json"
python tools/mmtrain/preflight_appearance_meshes.py --source $sourceObj `
  --source-sha256 $sourceSha --candidate "$runDir/adapted_0.5.ply" `
  --target-ratio 0.5 --mmgeo $mmgeo --output "$runDir/export-receipt.json" `
  --export-obj-dir "$runDir/exports"
```

The script writes the reference and three controls only when the face and
boundary checks pass. All meshes use the reference mesh's normalization.
The OBJ representation supplies a shared neutral material, face normals,
and three placeholder texture coordinates per triangle. The exported
files were read back and checked for face counts, directed boundaries,
valid normal and UV indices, and exact position and index round trips for
the reference and ManyMesh. The files remain local. The receipts retain
source, build, script, and output hashes for reproduction. The topology
audit covers duplicate and degenerate faces and edge incidence and
orientation. Self-intersections and consistency of mixed cuts remain to
be checked separately.

## Reserved-view scoring

Use [bench_appearance_controls.py](bench_appearance_controls.py) with the
frozen manifest and exported directory. It tests 12 perspective directions
at distances 3.3 and 5.2 in the shared source frame. It uses flat shading,
640 × 360 captures, and native sampling or hardware 4× MSAA. The reference
is the full source rendered at 2× resolution with 4× MSAA and a linear box
resolve. The JSON includes per-view, mean, and worst LDR-FLIP, SSIM, and
silhouette XOR, as well as pooled-MSE PSNR and sampled surface and normal
errors. This comparison measures quality at equal face count.

```powershell
python tools/mmtrain/bench_appearance_controls.py `
  --manifest tools/mmtrain/matched_appearance_inputs_20261124.json `
  --asset BarramundiFish --geometry-dir "$runDir/exports" `
  --fitted "$runDir/fitted.obj" --out "$runDir/quality.json"
```

Pin the training camera schedule before fitting and keep the scoring
cameras reserved. The scorer audits the candidate against the unchanged
meshoptimizer topology and locked boundary before rendering. Record
training wall time and memory on the CUDA host separately.

The identity check used Avocado on Intel Iris Xe with D3D12 and wgpu 0.33.0.
It passed all 48 view and AA comparisons by supplying the unchanged
meshoptimizer file as `--fitted`. The per-view and summary metrics matched
exactly, as did the sampled surface metrics. Reproduce with `--asset Avocado`
and `--fitted "$runDir/exports/meshoptimizer_lock_border.obj"` on its export.
The raw JSON remained local, with SHA-256
`6efe7777ef8ef8aa24f50b2f20065c79436bf8147aeaf29a9f1ee6ae5da43231`.
The CUDA pair was left unscored.

## CUDA experiment boundary

The exports match the file fields used by NVIDIA's
[OBJ loader](https://github.com/NVlabs/nvdiffmodeling/blob/main/src/obj.py).
They describe geometry under a neutral material. The shared UV coordinates
serve as placeholders for the geometry comparison. The upstream
[training script](https://github.com/NVlabs/nvdiffmodeling/blob/main/train.py)
optimizes both positions and material maps by default and aligns the base
mesh to the reference. For a placement-only comparison, the harness still
needs to hold materials fixed, preserve the common source frame, and enforce
boundary constraints. Record such adaptations separately from any run of
the upstream joint optimization. CUDA loading and optimization have yet to
run on these assets.
