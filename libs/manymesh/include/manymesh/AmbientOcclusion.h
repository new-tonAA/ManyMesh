/*
 * Copyright (C) 2026 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef TNT_MANYMESH_AMBIENTOCCLUSION_H
#define TNT_MANYMESH_AMBIENTOCCLUSION_H

#include <manymesh/Mesh.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

struct AmbientOcclusionOptions {
    //! Cosine-weighted hemisphere rays per LOD vertex. 16 is enough for soft cavity shading;
    //! 32 is the quality default. The bake is offline, so this trades only build time.
    uint32_t samples = 32;

    //! Maximum ray length in world units. 0 derives 0.1 * the source bounds diagonal, which
    //! keeps the result local to a cavity instead of darkening a whole closed object.
    float radius = 0.0f;

    //! Ray origin offset along the shading normal. 0 derives 1e-4 * the bounds diagonal.
    float bias = 0.0f;

    //! Average AO across vertices that share a position. LOD seam splitting leaves multiple
    //! vertices at one position; without this the interpolation across those triangles can
    //! show a thin AO seam. Real creases keep their geometry; only the shading term is welded.
    bool weldDuplicatePositions = true;

    //! Changes the deterministic sample sequence. Every run with the same seed produces
    //! bit-identical values, which makes regression tests meaningful.
    uint32_t seed = 0;
};

struct AmbientOcclusionResult {
    //! One value per target vertex, in [0, 1]. 1 is fully visible, 0 fully occluded.
    std::vector<float> values;

    //! World-space direction of the least-occluded hemisphere, one per target vertex.
    //! This is the directional counterpart to `values`: the material can use it to evaluate
    //! diffuse IBL in the direction the source mesh actually saw instead of the LOD normal.
    //! It is exactly the target normal for an unoccluded vertex.
    std::vector<math::float3> bentNormals;

    //! Vertices that actually received a ray-sampled value.
    size_t bakedVertices = 0;

    //! Number of duplicate-position groups welded after sampling.
    size_t weldedGroups = 0;

    float mean = 1.0f;
    float min = 1.0f;
    float max = 0.0f;

    //! Number of vertices whose bent normal differs from the target normal by more than 0.05
    //! degrees, and the mean/maximum of that angle. These are diagnostics, not quality gates.
    size_t tiltedVertices = 0;
    float meanBendDegrees = 0.0f;
    float maxBendDegrees = 0.0f;

    //! Ray length and normal offset that were actually used (the derived values when the
    //! corresponding option was 0).
    float radius = 0.0f;
    float bias = 0.0f;

    //! Wall time of BVH construction plus sampling, in milliseconds.
    double bakeMs = 0.0;
};

/**
 * Bakes source-mesh ambient occlusion onto the vertices of a LOD.
 *
 * Unlike a UV atlas bake this needs no UVs and no atlas in [0,1], so it works for tiled and
 * out-of-range layouts as well as for meshes without UVs. Occluders are the triangles of
 * `source`; sample points are the vertices of `target`. Vertices introduced by simplification
 * lie on the source surface, so they can be sampled directly.
 *
 * The result is low-frequency visibility, not displaced geometry. It brings back contact
 * darkening in eye sockets, folds and crevices that a coarse proxy cannot represent. It cannot
 * recover silhouette coverage, thin features, or the displaced surface itself.
 *
 * Alongside the scalar AO value, the bake returns a bent normal. The two use the same samples:
 * AO says how much light is blocked, while the bent normal says where the unblocked light comes
 * from. Feeding both to the material lets a coarse LOD keep the source mesh's directional
 * self-shadowing under image-based lighting without any runtime ray tracing.
 *
 * Returns false if either mesh is empty, the source has no triangles, or `target` has no
 * positions. Target normals are used when present; otherwise area-weighted normals are derived
 * from `target.indices`.
 */
bool bakeVertexAmbientOcclusion(Mesh const& source, Mesh const& target,
        AmbientOcclusionOptions const& options, AmbientOcclusionResult* result);

struct AmbientOcclusionMapOptions {
    //! Cosine-weighted hemisphere rays per covered texel. 16 is enough for a soft AO map;
    //! 32 is the quality default. The bake is offline, so this trades only build time.
    uint32_t samples = 32;

    //! Square map size in texels. 512 is the quality default.
    uint32_t size = 512;

    //! Maximum ray length in world units. 0 derives 0.1 * the source bounds diagonal.
    float radius = 0.0f;

    //! Ray origin offset along the shading normal. 0 derives 1e-4 * the bounds diagonal.
    float bias = 0.0f;

    //! Grow covered texels across chart borders so bilinear filtering does not reach neutral.
    uint32_t dilationTexels = 4;

    //! 3x3 Gaussian passes over covered texels. The hemisphere estimate is stochastic; one pass
    //! removes most texel-to-texel noise without rounding off the cavity shape. 0 disables it.
    uint32_t smoothingPasses = 1;

    //! Changes the deterministic sample sequence.
    uint32_t seed = 0;
};

struct AmbientOcclusionMapResult {
    uint32_t size = 0;

    //! One byte per texel, row-major, with v increasing with the row index. 255 is fully
    //! visible and 0 fully occluded. Uncovered texels are dilated to their nearest covered
    //! neighbour, or 255 when no covered texel exists nearby.
    std::vector<uint8_t> values;

    //! Texels covered by the source UV layout.
    size_t coveredTexels = 0;

    //! Texels written after dilation.
    size_t writtenTexels = 0;

    float mean = 1.0f;
    float min = 1.0f;
    float max = 0.0f;

    //! Ray length and normal offset that were actually used.
    float radius = 0.0f;
    float bias = 0.0f;

    //! Wall time of BVH construction, rasterization and sampling, in milliseconds.
    double bakeMs = 0.0;
};

/**
 * Bakes source-mesh ambient occlusion into the source's own UV layout.
 *
 * This is the texture-space counterpart to bakeVertexAmbientOcclusion(). It resolves detail
 * that a sparse LOD vertex set cannot: eye sockets, nostrils, folds and other sub-vertex
 * cavities are captured at texel density instead of being interpolated across a coarse
 * triangle. The LOD must keep the same UV parameterization, which every cut produced by this
 * library does.
 *
 * The source UVs must lie in [0,1]. Tiled layouts (several charts sharing one UV rectangle at
 * different integer offsets) are rejected, because they would overwrite each other; unwrap the
 * atlas first. Returns false if the source has no UVs, no triangles, or an out-of-range UV.
 *
 * AO is low-frequency visibility, not displaced geometry. It cannot recover silhouette
 * coverage, thin features, or the displaced surface itself.
 */
bool bakeAmbientOcclusionMap(Mesh const& source, AmbientOcclusionMapOptions const& options,
        AmbientOcclusionMapResult* result);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_AMBIENTOCCLUSION_H
