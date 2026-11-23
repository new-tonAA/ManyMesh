# CPU projective silhouette fitting

Mitsuba's projective silhouette gradients lowered the training loss on both
development assets. Mean LDR-FLIP and SSIM worsened on both across 24 reserved
camera and scale pairs. The candle holder improved binary silhouette XOR and
pooled PSNR. The shoe worsened on both. Keep the fit as a development control.

| Asset | Faces per arm | Accepted steps | Training MSE reduction | Reserved PSNR Δ (dB) | Reserved LDR-FLIP Δ | Reserved SSIM Δ | Reserved XOR Δ (percentage points) |
|---|---:|---:|---:|---:|---:|---:|---:|
| GlassHurricaneCandleHolder | 2,062 | 16 | 57.5% | +0.0429 | +0.0002085 | −0.0001098 | −0.003956 |
| MaterialsVariantsShoe | 11,350 | 6 | 54.0% | −0.0920 | +0.0000370 | −0.0000016 | +0.000226 |

Deltas are fitted minus unchanged meshoptimizer LockBorder. PSNR comes from
MSE pooled across the reserved frames. Lower FLIP and silhouette XOR are
better. Both initializations and fits passed the directed boundary and edge
topology checks. The optimizer kept triangle indices fixed and open boundary
vertices locked. These checks do not cover self-intersections or mixed DAG
cuts.

## Protocol

- Use the original 4,126- and 22,700-triangle Khronos meshes as references.
  Initialize at half the face count with meshoptimizer LockBorder. These are
  two legal, previously used development inputs. The 30% preflights did not
  supply a complete matched set. This comparison isolates placement by
  holding initialization and triangle indices fixed.
- Fit projected foreground coverage with Mitsuba 3.9.0 `direct_projective`
  and Dr.Jit 1.4.0 `llvm_ad_rgb`. Use 16 perspective camera and scale pairs,
  128 × 128 images, 64 samples per pixel, and a black diffuse mesh against a
  constant white background. Optimize squared image error with shared source
  and candidate sample seeds. Use the same Laplacian preconditioner, step,
  displacement, and triangle normal bounds as the
  [local coverage fit](VISIBLE_CONTOUR_FIT_20261124.md).
- Score distinct directions at two projected scales using the prior CPU
  scoring renderer, with 192 × 192 orthographic flat-shaded frames, four
  coverage samples per pixel, and LDR-FLIP at 67 pixels per degree. These are
  held-out views of reused assets. This screen supplies no independent asset
  generalization, physical-phone result, or measured interaction with a
  hardware AA or temporal upscaling pipeline. Its fit isolates coverage,
  while scoring includes shading and uses a different projection.

## Reproduce

See the [successful public workflow run](https://github.com/new-tonAA/ManyMesh/actions/runs/45217088176)
on Ubuntu 24.04 standard GitHub CPU runners. The workflow pins the source GLBs,
their extracted geometry hashes, and main dependencies. For the commands and
the pinned source revision, open the workflow at the
[experiment commit](https://github.com/new-tonAA/ManyMesh/blob/8a284aa3bc63d81362670ce8958cb902fe056333/.github/workflows/manymesh-projective-cpu.yml).
The [summary receipt](projective_silhouette_cpu_20261124.json) preserves the
check annotations, initial gradient norms, run IDs, metrics, and hashes of the
per-view JSON files. The script writes the full per-view scores and training
trace when rerun. This CPU coverage fit is a separate control from
[Hasselgren et al.'s mesh and shading optimization](https://diglib.eg.org/items/82ec8df1-d62a-40f0-a007-90374b5140dc),
which still requires a matched CUDA run.
