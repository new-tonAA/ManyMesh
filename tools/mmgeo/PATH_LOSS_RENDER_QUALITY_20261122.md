# Rendered image audit of continuous-pan path-loss simplification

Date: 2026-11-22. This development screen asks whether the existing continuous-pan
silhouette/depth/normal path-loss reranker improves rendered RGB quality over its
same-face QEM baseline. It does not establish a new method or a SIGGRAPH result.

## Protocol

- Four previously used development units: Pirate unit 5, Rounded Cube, Sphere, and
  Torus. Each path-loss result and its QEM control has the same final face count,
  about 80% of that unit's source faces. The assets and views are not a held-out
  confirmation set; some camera directions may overlap the optimization paths.
- Filament `mm_bench`, OpenGL on Intel Iris Xe Graphics, 256 x 256, the same
  importer-default material, fixed light/exposure, no shadows, eight orbit views
  around each source unit, two warmup and two measured frames per view. Each
  source/path/QEM triplet uses identical cameras. This checks geometry-driven
  image changes, not authored materials, textures, animation, or full frame cost.
- Metrics compare each simplified image with its source render. Reported changes
  are path minus QEM. PSNR is computed from mean per-view MSE within each asset;
  SSIM and LDR-FLIP are averaged within each asset. Uncertainty resamples the four
  paired assets 20,000 times, not the correlated camera views.
- Metric implementation: 8-bit sRGB, Gaussian SSIM (sigma 1.5, population
  covariance), NVIDIA LDR-FLIP 1.7 at 67 pixels per degree. The compatible scoring
  environment used Python 3.12.12, NumPy 2.3.4, SciPy 1.16.3, and scikit-image
  0.25.2. LPIPS-SqueezeNet is omitted because its pretrained backbone weights were
  unavailable in the local writable cache.
- The output audit found no duplicate or degenerate faces, nonmanifold edges, or
  inconsistent edge winding in either candidate. Every output preserved the
  source boundary-edge set. This is not a global intersection or vertex-link proof.

## Results

Positive PSNR and SSIM changes favor path loss; negative FLIP changes favor path
loss. All four asset-bootstrap intervals include zero.

| Asset | Faces | PSNR (dB) | Foreground PSNR (dB) | SSIM | LDR-FLIP | Path/QEM build-time ratio |
|---|---:|---:|---:|---:|---:|---:|
| Pirate unit 5 | 2,426 | -0.293 | -0.689 | -0.0000124 | +0.0000027 | 5.64x |
| Rounded Cube | 960 | +1.044 | +1.522 | +0.0000268 | +0.0000155 | 4.51x |
| Sphere | 7,542 | +0.150 | +0.173 | +0.0000355 | -0.0001293 | 12.62x |
| Torus | 922 | -0.003 | -0.326 | -0.0000454 | -0.0000140 | 15.08x |
| **Mean change [95% asset-bootstrap CI]** | — | **+0.224 [-0.182, +0.782]** | **+0.170 [-0.507, +1.060]** | **+0.0000011 [-0.0000289, +0.0000311]** | **-0.0000313 [-0.0000963, +0.0000091]** | — |

The metrics do not agree on a consistent per-asset win: PSNR, foreground PSNR,
SSIM, and FLIP each favor path loss on two of four units. Their aggregate intervals
include zero. The path-loss runs took 4.5x to 15.1x as long as their QEM controls in
the existing single-run construction records. This screen therefore finds no
repeatable rendered-quality improvement that offsets the measured build cost.

## Decision and limits

Do not promote this path-loss reranker as the SIGGRAPH contribution on this
evidence. It remains a research evaluator and a development negative/mixed result.
The experiment uses four previously explored development assets and low-resolution
static renders with one shared importer-default material. It does not measure LPIPS, perceptual
preference, temporal stability, compression bytes, mobile performance, or a fresh
test set. A future version must first show a frozen, multi-asset image-quality
gain at a useful total cost and distinguish itself from image-driven mesh
simplification and view-dependent refinement prior art.

The compact per-view metrics and paired asset bootstrap are in
[PATH_LOSS_RENDER_QUALITY_20261122.json](PATH_LOSS_RENDER_QUALITY_20261122.json).
The render and mesh hashes, commands, face counts, boundary/topology checks, and
camera settings are in
[PATH_LOSS_RENDER_RECEIPT_20261122.json](PATH_LOSS_RENDER_RECEIPT_20261122.json).
The reproduction tools are
[render_path_loss_quality.py](render_path_loss_quality.py) and
[summarize_path_loss_quality.py](summarize_path_loss_quality.py). Source captures,
OBJ files, render logs, and images remain in ignored `out/pathloss-render-audit/`;
the screenshot pixels are not redistributed because the source-model licenses have
not been audited for that purpose.

Re-run from the repository root with the local captures and compatible metric
environment:

```powershell
python tools/mmgeo/render_path_loss_quality.py `
  --repo . --out out/pathloss-render-audit `
  --assets Pirate RoundedCube Sphere Torus --views 8 --size 256 `
  --warmup 2 --measure 2

$env:PYTHONPATH = 'out\image-quality-deps'
python tools/mmgeo/summarize_path_loss_quality.py `
  --renders out/pathloss-render-audit `
  --out out/pathloss-render-audit/quality.json --ppd 67
```
