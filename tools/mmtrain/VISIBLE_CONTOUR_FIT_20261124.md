# Fixed topology silhouette fitting

The local coverage fit reduced training error on all three development
assets. Only GlassHurricaneCandleHolder improved mean LDR-FLIP over its
initialization on the reserved views, by 0.000017. The other two assets
regressed slightly. All four arms kept the same face counts and passed
the directed boundary and edge topology checks.

## Comparison

Use the three assets from the previous contour screen with legal
ManyMesh, plain progressive QEM, and whole mesh meshoptimizer LockBorder
cuts at 50% face retention. Start the fit from the meshoptimizer cut so
the fitted and unchanged arms differ only in vertex positions. The
reference has every original source triangle. Use the same normalization,
24 reserved camera and scale pairs, flat shading, 192 by 192 frames,
and four CPU coverage samples as the [prior quality screen](CONTOUR_IMPORTANCE_QEM_20261123.md).
The reserved views are distinct from the fitting views. Asset identities
are reused development data.

| Asset | Faces per arm | Accepted steps | Training coverage MSE reduction | Reserved PSNR delta (dB) | Reserved LDR-FLIP delta | Reserved silhouette XOR delta (percentage points) |
|---|---:|---:|---:|---:|---:|---:|
| GlassHurricaneCandleHolder | 2,062 | 10 | 21.7% | +0.0118 | −0.0000169 | −0.002939 |
| MaterialsVariantsShoe | 11,350 | 5 | 18.3% | −0.1204 | +0.0000311 | +0.000113 |
| SpecularSilkPouf | 40,640 | 1 | 0.38% | −0.0132 | +0.0000103 | +0.000226 |

Deltas are fitted minus unchanged meshoptimizer. Lower FLIP and
silhouette XOR are better. Among the other controls, plain QEM has lower
FLIP than both meshoptimizer arms on the shoe and pouf. The small gain
on the candle holder does not extend across this pool. The [receipt](visible_contour_fit_20261124.json)
records all per-view PSNR, SSIM, FLIP, silhouette and coverage measures,
acceptance trace, topology audits, file hashes, and elapsed fitting time.
It also includes sampled Chamfer distance and normal agreement for all
arms, using 20,000 area weighted samples per direction. Sampled normal
agreement drops by 0.00009 to 0.00028 across the three fits. Even the
candle holder's small image gain comes with slightly worse sampled
Chamfer distance and normal agreement.

Keep this fit as a development control. Its reserved views and sampled
geometry give no consistent advantage over the strongest matched input.

## Local gradient

The fitting loop uses 16 views from eight Fibonacci sphere directions
at two projected scales. It rasterizes both meshes at 128 by 128 with
a 3 by 3 coverage grid per pixel. Projected face orientation identifies
possible contour edges. A coverage change across the edge and a nearby
depth match select samples that can contribute to this fit. These
checks approximate visibility around occlusions.

At each supported sample, use a five-point strip across the contour.
Approximate the coverage change from an outward edge translation using
a logistic profile, then propagate the derivative to the two incident
vertices using the edge interpolation weights. Match the strip against
source coverage. The current hard coverage offsets the surrogate so
identical rasters produce a zero residual at zero displacement.

Precondition the gradient using the free vertex block of `I + 4L`,
where `L` is the full mesh graph Laplacian. Lock open boundary vertices.
Cap maximum step length at 0.002 and total displacement at 0.012
normalized units. Require the dot product between the current and
initial triangle normals to be at least 20% of the initial normal's
squared length. Use unnormalized normals. Backtrack against training
raster coverage MSE for up to seven step sizes. The run stops
after 16 iterations or when no step passes. The topology audit checks
duplicate or degenerate faces and directed edges. Self-intersection and
legal mixed-cut guarantees require additional checks.

Finite differences of the frozen strip loss agreed with its analytic
derivative within 4.9 × 10⁻¹¹ in the numerical check. An identity
tetrahedron produced zero gradient, and fitting a smaller tetrahedron
reduced its training coverage MSE. These checks cover the local loss
and fitter behavior. The gradient approximates the response near a
fixed edge and does not differentiate visibility changes.

## Reproduce

Use the isolated research dependencies and the geometry preparation step
from the [desktop AA follow-up](CONTOUR_PRIORITY_AA_20261123.md).

```powershell
$asset = 'GlassHurricaneCandleHolder'
$prior = "out/khronos-quality-screen-20261123/$asset"
python tools/mmtrain/fit_visible_contours.py `
  --source "out/khronos-curated-screen-20261123/$asset/geometry.obj" `
  --prepared "out/contour-aa-gpu-20261123/prepared/$asset.npz" `
  --cut "$prior/scoring_adapter/selected_ratio_0.5.ply" `
  --preflight "$prior/scored-one-ulp-diagnostic/receipt.json" `
  --out "out/visible-contour-fit-20261124/scored/$asset.json" `
  --fitted-out "out/visible-contour-fit-20261124/scored/$asset.npz"
```

Repeat for the shoe and pouf. The fit uses the existing CPU rasterizer.
The separate Mitsuba 3.9.0 / Dr.Jit 1.4.0 LLVM probe stopped during
import when Windows Application Control blocked the Dr.Jit extension.
The [Linux CPU follow-up](PROJECTIVE_SILHOUETTE_CPU_20261124.md) ran the
Projective Sampling integrator on two of these assets. The CUDA Hasselgren
baseline remains pending. Prior silhouette gradient and
appearance fitting methods include [OpenDR](https://is.mpg.de/ps/publications/loper-eccv-2014),
[Rasterized Edge Gradients](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11059.pdf),
and [Mitsuba shape optimization](https://mitsuba.readthedocs.io/en/stable/src/inverse_rendering/shape_optimization.html).
