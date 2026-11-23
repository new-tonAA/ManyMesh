# Source contour priority under desktop antialiasing

This follows the [CPU contour priority screen](CONTOUR_IMPORTANCE_QEM_20261123.md).
The question is whether the same geometry change improves LDR-FLIP after
hardware AA or spatial upscaling, and whether the measured quality and GPU
time points improve on ordinary QEM and full source draws.

## Results

On Intel Iris Xe using D3D12 and driver 31.0.101.4502, none of the modes
showed a reliable decrease in mean LDR-FLIP. Native weighted QEM scored
slightly higher FLIP on all seven assets. The paired FLIP intervals for
MSAA, SMAA, and bicubic upscaling span zero. The mean PSNR changes range
from +0.004 to +0.028 dB, with intervals spanning zero in each mode.
These results use a different projection, rasterizer, and projected size
from the earlier CPU screen.

The table reports weighted QEM minus plain QEM with the same filter.
Lower FLIP is better. The last column compares the weighted arm with
all ordinary QEM and full source modes using mean FLIP and pooled GPU
median. Intervals resample the seven development assets.

| Filter | Assets with lower FLIP | Mean FLIP delta and 95% interval (×10⁻⁵) | Mean PSNR delta (dB) | Dominated assets |
|---|---:|---:|---:|---:|
| Native | 0 / 7 | +1.772 [+0.340, +3.376] | +0.014 | 5 / 7 |
| 4× MSAA | 2 / 7 | +0.012 [−6.102, +4.003] | +0.012 | 2 / 7 |
| SMAA Medium | 4 / 7 | +0.281 [−3.144, +4.381] | +0.028 | 7 / 7 |
| Half resolution plus bicubic | 4 / 7 | +0.137 [−4.902, +5.018] | +0.004 | 7 / 7 |

Plain QEM plus 4× MSAA had lower mean FLIP and GPU median than weighted
QEM plus SMAA on all seven assets, including in both timing batches.
Plain native QEM likewise dominated the weighted bicubic arm on all
seven, with a GPU margin below 0.001 ms in the closest case.

### Timing audit

The first run scored images between modes during the second timing
batch. The repeat separated both timing batches from readback and
scoring, and reversed the order of assets. All 504 scored mode images
and 42 references reproduced bit for bit. The measured same-filter
GPU differences changed. For example, the mean per-asset SMAA difference
in the reverse batch moved from −0.212 ms to −0.001 ms. Native and MSAA
differences also changed direction between the two capture-free batches.
These observations support the image comparisons and make a same-filter
speed claim premature.

Keep the contour priority as a measured development control. This
experiment gives no basis to advance it to a production DAG method.
[Full JSON with per-view metrics and GPU timestamps](contour_priority_aa_20261123.json)

## Protocol

- Use all seven models from the earlier development pool. The preparation
  command reruns the same QEM solver and contour weights. The GPU scorer
  checks the source hash, face count, mesh archive hash, and exact equality
  of the per view CPU score replay before uploading an asset.
- Render 16 copies of one asset at a time in a 4 by 4 tiled layout.
  Use six perspective viewpoints with azimuths from 13 degrees in
  60 degree steps. Cycle elevation through −15, 20 and 35 degrees.
  Alternate camera radius between 3.2 and 4.7 normalized source units.
  Both variants have the same face count and use flat normals stored
  per corner, with the same light and transfer function.
- Cross full source, plain QEM and contour priority QEM with four modes.
  The modes are native 1x raster, hardware 4x MSAA, Bevy v0.16.1 SMAA
  Medium with luma edges, and half width and height raster with the
  existing bicubic shader. The output is 640 by 360. The reference
  uses the full source with 4x MSAA at 1,280 by 720, followed by a
  linear light 2 by 2 box resolve and the same sRGB conversion.
- At each view, take two batches of eight timestamped draws or
  raster plus filter passes, using the reverse mode order in the
  second batch. The existing harness warms each batch with eight
  passes. Run both batches before any mode capture or scoring. Issue a
  separate replay for each scored image.
  Timing covers the GPU render path, including resolve or reconstruction.
  The GPU intervals omit CPU encoding, present and image scoring.
- Report mean and worst LDR-FLIP, PSNR from pooled MSE, and mean SSIM.
  The GPU median pools samples over the six views. Resample assets for
  the paired quality intervals. Also report whether an ordinary arm
  has lower or equal mean FLIP and GPU median with at least one strict
  improvement. This is a comparison of observed points. Timing noise can
  change dominance when medians are close.

The development pool contains static geometry with flat shading and opaque
coverage. The two reduced arms are standalone QEM cuts. The experiment does
not measure transitions between cluster DAG levels, animated scenes, or
mobile performance. The earlier CPU report contains separate comparisons
against the available legal ManyMesh and meshoptimizer cuts.

## Reproduce

Use the pinned sources from the [CPU screen](CONTOUR_IMPORTANCE_QEM_20261123.md)
and the same isolated Python dependencies. Add `wgpu==0.33.0` and
`zstandard`. Use the Bevy shader and lookup tables from the
[desktop reconstruction benchmark](SILHOUETTE_GUIDE_FUSION_20261122.md).

```powershell
$asset = 'GlassHurricaneCandleHolder'
$inputs = "out/khronos-curated-screen-20261123/$asset"
$run = 'out/contour-aa-gpu-20261123'
$sha = (Get-Content "$inputs/geometry-receipt.json" -Raw | ConvertFrom-Json).output_sha256
python tools/mmtrain/bench_contour_importance_qem.py `
  --source "$inputs/geometry.obj" --sha256 $sha `
  --output "$run/prepared/$asset.json" --geometry "$run/prepared/$asset.npz"
python tools/mmtrain/bench_contour_priority_aa.py `
  --asset $asset --prepared "$run/prepared" `
  --prior-results tools/mmtrain/contour_importance_qem_20261123.json `
  --shader-root out/deps/bevy-smaa --out "$run/isolated/$asset.json"
```

Repeat for every model. Run `summarize_contour_priority_aa.py` with
`--scored "$run/isolated"` and `--out <receipt.json>`. The initial run
used the same renderer and captured
and scored each mode during the second timing batch. The published
receipt retains its timing order diagnostic and capture verification.
The CPU screen's original script is retained at its
[recorded revision](https://github.com/new-tonAA/ManyMesh/blob/0aaea7a264c911bbbdaf58a9236e68a98a7e2735/tools/mmtrain/bench_contour_importance_qem.py).
