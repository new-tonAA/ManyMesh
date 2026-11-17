# Tangent-frame and authored normal-map novelty audit

2026-11-16. Literature screen for the proposed fixed-UV, no-rebake PBR simplification path.
This is a scope correction, not a claim that every implementation detail has an equivalent prior.

## Question screened

Could a mesh simplifier make a SIGGRAPH contribution by constraining or scoring changes to the
tangent frame induced by geometry and UVs, while preserving the source UVs, materials, and authored
tangent-space normal map without rebaking?

## Direct prior art

1. Cohen, Olano, and Manocha, *Appearance-Preserving Simplification* (SIGGRAPH 1998), track
   parametric surface distortion to bound movement of both texture color and lighting encoded by a
   normal map. This already couples simplification, surface mapping, and normal-map appearance.
   [SIGGRAPH paper DOI](https://doi.org/10.1145/280814.280832),
   [author-hosted PDF](https://gamma-web.iacs.umd.edu/APS/APSlossy.pdf).
2. Williams et al., *Perceptually Guided Simplification of Lit, Textured Meshes* (SI3D 2003),
   evaluates view-dependent simplification under dynamic diffuse/specular lighting and explicitly
   supports per-pixel normal-map lighting. Its hierarchy propagates normal cones and luminance
   bounds from the normal map. Thus normal-map-aware ranking under changing lights is also established.
   [Author-hosted paper](https://pages.jh.edu/dighamm/version2/research/2003_02_perceptually_guided_simplification_of_lit_textured_meshes.pdf).
3. Hasselgren et al., *Appearance-Driven Automatic 3D Model Simplification* (TOG 2021), jointly
   optimize mesh shape and shading representations, explicitly including tangent-space normal maps,
   spatially varying BRDFs, and PBR examples. For deforming geometry they differentiate and update
   the tangent frame derived from positions and UV coordinates. This directly rules out a broad
   claim that accounting for tangent-frame changes during appearance-preserving simplification is
   new. Their method is image-driven nonlinear optimization rather than a local hard gate on a
   fixed authored map; that implementation distinction alone is not sufficient novelty.
   [Paper](https://arxiv.org/abs/2104.03989).
4. Liu, Zhang, and Yuksel, *Simplifying Textured Triangle Meshes in the Wild* (TOG 2025), addresses
   arbitrary textured/non-manifold meshes through source/output correspondence and texture transfer.
   The paper does not establish normal-map-specific handling, so it is cited here only as adjacent
   prior art for the texture-transfer and arbitrary-input parts of the proposed pipeline.
   [Paper](https://www.dgp.toronto.edu/~hsuehtil/pdf/wild_mesh_paper_compressed.pdf).

## Relation to this repository

`CornerSimplifier` stores and interpolates UVs and shading normals per triangle corner, but it does
not carry a tangent frame in `GeneratedVertex`. The frame consumed by a tangent-space normal map is
derived from the output geometry, UVs, and shading normals. Therefore a UV/normal/AO gate does not
certify that the same authored normal map produces the same world-space normals or PBR image after a
collapse. This is a real validation gap in the current narrow asset contract, but the gap itself is
not a novel algorithm.

## Decision

Close “add a tangent-frame angular distortion term/hard gate for fixed authored normal maps” as a
standalone SIGGRAPH novelty candidate. Do not promote it based only on an improved PBR error curve.
The broad appearance objective, normal-map-aware simplification, and tangent-frame updates have
strong direct prior art.

A future reopening would need a distinct mechanism beyond adding another local attribute penalty,
such as a useful certified bound on the rendered error for a defined family of normal maps/materials,
or a demonstrably cheaper dynamic update with matched quality and total-cost gains over both image-
driven simplification and faithful normal-map rebaking. No such mechanism or evidence exists here.
The workspace currently lacks a held-out authored PBR asset set, so no PBR comparison is claimed.

## Reproduction and source inspection

Repository inspection covered `CornerSimplifier.h` and the attribute evaluation/emission paths in
`CornerSimplifier.cpp`. No C++ files were changed and no software tests were run. The literature
claims above were checked against the cited primary papers; the 2025 paper is intentionally not
described as a normal-map method.
