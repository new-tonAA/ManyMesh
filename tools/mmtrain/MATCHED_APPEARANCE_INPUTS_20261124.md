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
[receipts](matched_appearance_inputs_20261124.json). The optimizer and training
cameras are pinned in the [CUDA protocol](appearance_cuda_protocol_20261124.json).
The separate confirmation cohort remains pending. The assets come from the
[geometry-only CC0 screen](KHRONOS_SEPARATE_BUFFER_PREFLIGHT_20261124.md).

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

Keep the scoring cameras reserved during fitting. The scorer audits the
candidate against unchanged meshoptimizer topology and the locked boundary
before rendering. Record training wall time and memory on the CUDA host
separately.

The identity check used Avocado on Intel Iris Xe with D3D12 and wgpu 0.33.0.
It passed all 48 view and AA comparisons by supplying the unchanged
meshoptimizer file as `--fitted`. The per-view and summary metrics matched
exactly, as did the sampled surface metrics. Reproduce with `--asset Avocado`
and `--fitted "$runDir/exports/meshoptimizer_lock_border.obj"` on its export.
The raw JSON remained local, with SHA-256
`6efe7777ef8ef8aa24f50b2f20065c79436bf8147aeaf29a9f1ee6ae5da43231`.
The CUDA pair was left unscored.

## CUDA placement-only control

[fit_appearance_cuda.py](fit_appearance_cuda.py) calls the pinned NVIDIA OBJ
loader, mesh operations, and renderer from an external source checkout. It
holds materials fixed and uses the audited source frame. It welds exactly
coincident positions for the differentiable rasterizer, then expands the
fitted positions back to the original indices. This keeps UV seam replicas
together without breaking the topology audit. Open boundary positions are
fixed. The optimizer caps displacement at 0.012 normalized units and
backtracks steps that move a triangle's unnormalized normal below the
recorded dot-product threshold.

Training uses 32 fixed cameras, 128 × 128 images with 2× linear supersampling,
the same diffuse material and camera light on both meshes, and Adam for 128
minibatches. The loss is linear RGB MSE plus a displacement penalty. The
closest training and reserved camera directions differ by 16.8 degrees.
The [protocol receipt](appearance_cuda_protocol_20261124.json) pins camera
vectors, the optimizer settings, both asset hashes, and the scorer. The
[upstream training example](https://github.com/NVlabs/nvdiffmodeling/blob/9b2ba2eff83c7d90127f78c20773b06ddc3ae1db/train.py)
also fits material maps and independently aligns the base mesh. A result
from this placement-only adapter covers the geometry comparison.

Use a CUDA development environment with CUDA-enabled PyTorch, a compiler,
`ninja`, `imageio`, and the research Python dependencies above. Fetch the
[nvdiffmodeling source archive](https://codeload.github.com/NVlabs/nvdiffmodeling/zip/9b2ba2eff83c7d90127f78c20773b06ddc3ae1db)
and set `$upstream` to the extracted directory containing `src/`. Install
[nvdiffrast 0.4.0](https://github.com/NVlabs/nvdiffrast/tree/253ac4fcea7de5f396371124af597e6cc957bfae)
from its pinned revision. NVIDIA's source remains an external dependency
for noncommercial research under its [license](https://github.com/NVlabs/nvdiffmodeling/blob/9b2ba2eff83c7d90127f78c20773b06ddc3ae1db/LICENSE.txt).

```powershell
python -m pip install --no-build-isolation `
  'git+https://github.com/NVlabs/nvdiffrast.git@253ac4fcea7de5f396371124af597e6cc957bfae'
python tools/mmtrain/fit_appearance_cuda.py `
  --manifest tools/mmtrain/matched_appearance_inputs_20261124.json `
  --asset BarramundiFish --geometry-dir "$runDir/exports" `
  --upstream $upstream --out "$runDir"
```

Append `--prepare-only` to check input and upstream hashes and emit the
protocol without CUDA. The full command writes `fitted.obj` and a training
receipt with gradient norm, losses, elapsed time after setup, and PyTorch
CUDA allocator peaks. CUDA allocations outside PyTorch are outside those
memory counters. Pass `fitted.obj` to the reserved-view scorer above.

Preparation passed for both assets. CPU-side tests exercised the upstream
OBJ reader and tangent gradients with tensor allocation redirected to CPU,
and checked camera separation, displacement limits, and step rejection.
The CUDA run stopped at the device check on this host. Compiling the
upstream CUDA extension, rendering, and fitting still require a CUDA run.
