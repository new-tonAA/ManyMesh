# Source contour frequency as a QEM priority

This development experiment asks whether a simple source contour priority
improves image quality at the same face count. It uses the existing
geometry only progressive QEM implementation for both arms.

## Method

Sample 64 Fibonacci sphere directions. In each view, mark vertices incident
to an edge whose two incident faces have opposite facing signs. Divide the
number of marked views by 64 to obtain each vertex's importance. This is an
apparent contour test without occlusion filtering. The QEM solver already
locks open boundaries. At each candidate collapse, multiply its existing
queue priority by `1 + max(importance[u], importance[v])`. The surviving
vertex inherits the larger value. Placements and legality checks are shared
with the unweighted arm.

This weight differs from the earlier source contour control, which added
view dependent planes to the quadrics and could change the preferred
placement within a single edge. That prior control had mixed results.
Image driven mesh simplification and silhouette preservation already have
direct precedents. [Earlier contour plane comparison](../mmgeo/CONTOUR_VISIBILITY_ABLATION.md) ·
[Lindstrom and Turk](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf) ·
[Luebke and Erikson](https://techreports.cs.unc.edu/papers/97-005/97-005.pdf)

## Comparison

Use the seven pinned Khronos assets from the earlier development screen.
Each arm targets the face count nearest to half the source while removing
pairs of faces. Only score cuts with the requested counts, the
original directed boundary, and valid edge topology. Exact position welding
occurs in the shared normalized float32 frame. The image reference has all
source faces and uses those same normalized positions.

Evaluate 12 camera directions distinct from the fitting views, at two
orthographic screen scales (1.0 and 0.55). Both arms use the same fixed light,
flat shading, 192 × 192 pixels, four CPU coverage samples per pixel, and
67 pixels per degree for LDR-FLIP. The two scales probe projected size.
They use no perspective distance change. Report both the mean and worst
observed view for each asset. Compute mean PSNR from pooled view MSE.
Raster scores apply to the static geometry only. See the [asset licenses and
source hashes](KHRONOS_EQUAL_FACE_QUALITY_SCREEN_20261123.md).

## Reproduce

Set the same Python dependencies as the [appearance preflight](APPEARANCE_INPUT_PREFLIGHT_20261123.md).
Use each asset's source extraction input and its expected OBJ
hash from the earlier screen. For example:

```powershell
$modelDir = 'out/khronos-curated-screen-20261123/GlassBrokenWindow'
$sourceSha = '0e89c18f6c9c760c3ab8f7ad7487b912c253c4b2ad415ea1b0475fa1e54f7101'
python tools/mmtrain/bench_contour_importance_qem.py `
  --source "$modelDir/geometry.obj" --sha256 $sourceSha `
  --output out/contour-importance-qem-20261123/scored/GlassBrokenWindow.json
```

Each receipt records the source and script hashes, actual geometry eligibility,
timing and every per view score. The first run attempted to audit unused solver
vertices. A rerun compacted the output index buffers before the audit and retained
the same weights, views and face targets. The first run produced no scores.

## Results

All seven paired cuts passed the exact face and boundary checks. Deltas
below are weighted QEM minus plain QEM. Lower FLIP and silhouette XOR
are better. Worst PSNR is the minimum over the 24 views and scales.
The receipt also includes worst FLIP, SSIM, silhouette XOR, and coverage
error for every arm.

| Asset | Actual faces per arm | Mean PSNR delta (dB) | Worst PSNR delta (dB) | Mean FLIP delta | Mean silhouette XOR delta (percentage points) |
|---|---:|---:|---:|---:|---:|
| AnisotropyBarnLamp | 5,101 | +0.260 | +0.569 | +0.000007 | -0.000339 |
| DiffuseTransmissionTeacup | 14,092 | +0.104 | +0.049 | -0.000024 | -0.000113 |
| GlassBrokenWindow | 493 | +0.265 | -0.080 | -0.000005 | 0.000000 |
| GlassHurricaneCandleHolder | 2,062 | +0.177 | +0.224 | -0.000136 | -0.002487 |
| MaterialsVariantsShoe | 11,350 | +0.114 | +0.154 | -0.000004 | -0.000226 |
| PotOfCoals | 9,111 | +0.108 | +0.230 | +0.000450 | -0.001808 |
| SpecularSilkPouf | 40,640 | +0.143 | +0.094 | -0.000030 | +0.000226 |

The mean PSNR change across assets is +0.167 dB (paired asset bootstrap
95% interval +0.123 to +0.218 dB). Mean silhouette XOR falls on five assets,
ties on one, and rises on one. The equal asset mean changes by
−0.000678 percentage points. Mean FLIP falls on five assets and rises on
two, with a small mean increase of 0.000037 (95% interval −0.000062 to
+0.000186). Mean SSIM changes by −0.000133. These intervals resample only
the seven development assets. Timings were collected while runs overlapped
and are recorded for reproduction.

Existing ManyMesh cuts and meshoptimizer whole mesh LockBorder were scored
using the same views and audit where exact faces matched. Both QEM arms
beat all four eligible ManyMesh cuts on each image metric. The weighted
arm beats meshoptimizer on all five image metrics only for
GlassBrokenWindow, where plain QEM also wins all five. It loses all five
on GlassHurricaneCandleHolder and has mixed results on
MaterialsVariantsShoe and SpecularSilkPouf.

The tested priority is a useful small PSNR control. Its mixed FLIP and
stronger baseline results leave a constrained DAG optimizer unjustified by
this experiment. The native comparison below remains a separate test.

Run [the comparator scorer](score_contour_priority_controls.py) with the
same source OBJ, the earlier asset's `scored-one-ulp-diagnostic/receipt.json`
and its adapted 0.5 cut. [The summarizer](summarize_contour_priority.py)
combines the per asset `scored` and `controls` directories, including
10,000 paired asset bootstrap draws. The full [JSON receipt](contour_importance_qem_20261123.json)
contains the geometry eligibility, per view measurements, hashes, and
mean and worst scores for all eligible arms.

## CornerSimplifier comparison design

For a native comparison, attach the source weight to each welded vertex.
Pass the weights into the research build from the full asset so a group
boundary does not become a contour in the precomputation. Use the maximum
weight among coincident source vertices and propagate the maximum on
collapse. Apply the multiplier only to the candidate priority at queue
insertion. Keep the existing geometric and attribute gates, shared boundary
locks, placement selection, and published geometric error bound. Update
the candidate version when its surviving vertex weight changes.

Freeze the mesh and renderer revisions, evaluate `lambda = 0` and the
frozen contour weight at identical output counts, and verify that the zero
weight path has identical indices and positions to the unmodified solver.
Record candidate changes, offline precomputation, construction cost,
movement paths, and full source image scores before evaluating any DAG
level fitting.
