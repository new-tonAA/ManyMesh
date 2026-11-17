# Controlled RGB check beyond coverage and depth

2026-11-15. Added after the geometry experiments, on already-inspected development assets.
This is NOT a preregistered independent validation or a complete appearance gate.

The preceding scores contain opaque coverage and normalized premultiplied depth. They cannot
measure normal interpolation, highlights or texture shading. This audit adds a minimal controlled
RGB renderer: area-weighted vertex normals derived separately from each mesh, barycentric
interpolation and renormalization, two-sided normals facing the orthographic camera, ambient .06,
three fixed directional diffuse lights, and exponent-64 Blinn-Phong highlights of strength .2.
The light directions/powers are fixed in the implementation; no result-driven adjustment occurs.
It compares source/QEM/source contours/visible contours/cumulative image controls at the same
actual face count, same source-normalized twelve-camera orbit, 128px, sample scale3 and sigma.9.
Errors use linear floating-point RGB, before any display tone mapping or clipping.

This is deliberately restricted: NO authored normals, UVs, textures, normal maps, shadows,
material/BRDF fitting or GI. A derived-normal degradation is not proof that an attribute-aware
Corner output or a normal-map-baked renderer would degrade by the same amount. Reusing
geometrically unrelated source vertex normals would also require correspondence validation.
Passing this audit still would not establish final visual quality or a publication contribution.

Source rasterization supplies frontmost face IDs. Each low-mesh normal is interpolated on the
actual winning triangle, not copied from a reference image. The same established linear Gaussian
and box-downsample operator filters all three color channels; it is reused without changing the
live geometry experiment's two-channel implementation. There is no temporal accumulation.

## First measured outcome

Torus at 288 triangles (25%): the cumulative coverage/depth image control improved geometry SSE
from 182.37097 to 159.07894 (12.77%), but its summed RGB SSE is 79.25757 against QEM 73.83943,
which is 7.34% worse. Source-contour and visible-contour RGB SSE are 81.97945 and 111.51120.
This directly demonstrates a proxy/controlled-shading mismatch on one development asset. It
does not establish that this mismatch is universal or that a new joint objective is itself novel.

Pirate's full continuous run is now complete (5010 -> 1314 triangles). Its cumulative image
control reduces geometry SSE 9.42% against QEM at the final checkpoint and reduces controlled
RGB SSE 22.90% (265.27425 -> 204.51852), improving all twelve RGB views. Source-contour and
visible-contour RGB sums are 224.36340 and 229.29724. Thus Torus's mismatch must not be
generalized to all assets: the method helps RGB on Pirate while hurting it on Torus.

All three completed assets are summarized, with the asset list explicit, in
`out/shading-controls/summary.json`. `quality-proxy-tradeoff.png` places each policy's geometry
and RGB error relative to QEM. Before aggregating, the script checks equal actual face counts,
source/mesh manifests, matching raster hashes and identical camera populations. Monkey's three
classical policies and completed image policy were rendered in separate jobs with exactly the
same implementation, source and view set; their merge records and checks that provenance.

At the final checkpoint, controlled RGB reductions relative to QEM (negative means worse):

| Asset | Source contours | Visible contours | Cumulative image control | Worse image-control RGB views / 12 |
|---|---:|---:|---:|---:|
| Torus | -11.02% | -51.02% | -7.34% | 7 |
| Monkey | -5.30% | -0.53% | -0.13% | 6 |
| Pirate | +15.42% | +13.56% | +22.90% | 0 |

Monkey RGB sums are QEM 8.43627, source-contour 8.88359, visible-contour 8.48140 and image
control 8.44742. The image-control regression is small in aggregate and must not be inflated
into a broad failure claim; it nonetheless fails to demonstrate an appearance improvement.
The original geometry proxy improved 5.22% on this same fixed-face comparison. These results
expose a specific limitation of the present proxy/control, not a universal theorem about depth
metrics or an established novel solution. No normal-map or authored-attribute baseline was tested.

The existing image control fits three geometry-only views. It never sees these RGB scores, and
the source contour controls use eight construction views. Do not silently choose a different
policy per RGB test view. Report worse views and all asset-level outcomes, not only these sums.

Two new analytic rendering checks: planar retriangulation leaves smooth shading unchanged,
and reversing planar winding leaves two-sided shading unchanged. Background remains zero.
Python suite now passes 56 tests. No native/GPU or production material validation is implied.

```sh
python -I tools/mmgeo/evaluate_shading_controls.py out/filter-real-candidates/torus.json out/progressive-baseline/torus out/source-contour-control/torus out/visible-contour-control/torus out/progressive-image-control/torus --out out/shading-controls/torus.json
```

Output records every source/mesh/manifest/raster/shading implementation hash and all per-view
RGB metrics. Geometry artifacts are input-only. Repeat only after each asset's final manifest
exists and its checkpoint full-raster checks pass.

Recreate the full merged Monkey audit and final quality plot from its completed jobs:

```sh
python -I tools/mmgeo/merge_shading_audits.py out/shading-controls/monkey-classical.json out/shading-controls/monkey-image.json --out out/shading-controls/monkey.json
python -I tools/mmgeo/summarize_image_quality.py
```

The subsequent [fixed-geometry normal attribution](NORMAL_TRANSFER_ATTRIBUTION.md) replays the
actual collapse histories and compares source-moment normal transfer on both QEM and image
geometry. The image/QEM error changes remain mixed: +16.73% Torus, +0.81% Monkey, -26.93% Pirate.
That transfer does not explain away the mismatch. This is a restricted moment-averaging control,
not an optimal attribute transfer or evidence against normal-map optimization.

A subsequent [normal-fitting stationarity audit](APPEARANCE_COMPENSATION_V1_STOP.md) found that
this renderer's sample-facing rule can create value discontinuities when optimized shading
normals cross the viewer horizon. The earlier fixed-normal numbers remain reproducible for
their stated contract, but they cannot be used as evidence about an optimized-normal minimum
or an otherwise identical renderer using triangle-facing orientation. The compensation probe
therefore freezes a separate v2 contract and rebuilds its source references; it does not replace
these numbers silently. This further limits any physical appearance interpretation of this audit.
