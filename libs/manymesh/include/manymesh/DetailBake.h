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

#ifndef TNT_MANYMESH_DETAILBAKE_H
#define TNT_MANYMESH_DETAILBAKE_H

#include <math/vec3.h>

#include <manymesh/Mesh.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * Builds a frame that depends only on the vertex normal. It is the fallback used when a mesh has
 * no UVs, and it is what mm_bench packs for such meshes. Meshes with UVs should use
 * computeUvTangents() instead, because a normal map authored in UV space needs the UV frame.
 */
void computeVertexFrame(math::float3 normal, math::float3* tangent,
        math::float3* bitangent) noexcept;

/**
 * Computes a UV-derived tangent frame for every vertex, using the triangles in `indices`.
 *
 * This is the frame a renderer needs for a tangent-space normal map: it follows the UV
 * parameterization, so mirrored charts get the opposite handedness automatically. `signs`
 * receives +1 or -1 such that the bitangent is cross(normal, tangent) * sign.
 */
void computeUvTangents(Mesh const& mesh, std::vector<uint32_t> const& indices,
        std::vector<math::float3>* tangents, std::vector<float>* signs);

struct DetailBakeOptions {
    //! Width and height of the square tangent-space normal map.
    uint32_t size = 512;

    //! Texels the source normal field is grown across chart borders, to hide seam mismatches.
    uint32_t dilationTexels = 4;
};

struct DetailBakeResult {
    uint32_t size = 0;

    //! Linear RGBA8, row-major, with v increasing with the row index. Alpha stores the angle of
    //! the normal the LOD dropped, normalized to [0,1] (angle / 90 degrees). Neutral texels store
    //! 0, so a shader can widen the specular lobe only where detail was actually removed.
    std::vector<uint8_t> rgba;

    //! Texels covered by the low-poly UV layout.
    size_t lodTexels = 0;

    //! Texels where both the low-poly frame and the high-poly normal are available.
    size_t coveredTexels = 0;

    //! Angle between the baked high-poly normal and the low-poly normal, in degrees.
    float meanAngleDegrees = 0.0f;
    float maxAngleDegrees = 0.0f;

    //! Texels where the high-poly normal was on the back side of the low-poly surface. That is a
    //! UV mismatch, not lost detail, so these texels stay neutral and are excluded from the stats.
    size_t mismatchedTexels = 0;
};

struct DetailHeightOptions {
    //! Width and height of the square height map.
    uint32_t size = 512;

    //! Texels the source height field is grown across chart borders.
    uint32_t dilationTexels = 4;

    //! Largest accepted displacement along the LOD normal, in world units. 0 derives 5% of the
    //! source bounds diagonal. Samples beyond this limit are treated as a UV mismatch instead
    //! of being allowed to fold a distant layer of the model into the map.
    float maximumDistance = 0.0f;
};

struct DetailHeightResult {
    uint32_t size = 0;

    //! One byte per texel, row-major, with v increasing with the row index. 128 is the neutral
    //! (no displacement) value; lower values put the source surface behind the LOD, higher
    //! values put it in front.
    std::vector<uint8_t> values;

    //! Texels covered by the low-poly UV layout.
    size_t lodTexels = 0;

    //! Texels where a source surface point was found along the LOD normal.
    size_t coveredTexels = 0;

    //! LOD texels with no source sample or a displacement beyond maximumDistance.
    size_t missedTexels = 0;

    //! Signed displacement of the source surface relative to the LOD along the LOD normal, in
    //! world units. Positive means the source surface is in front of the LOD.
    float minHeight = 0.0f;
    float maxHeight = 0.0f;
    float meanAbsHeight = 0.0f;

    //! Largest absolute displacement; the map normalizes to this range.
    float heightRange = 0.0f;

    //! Suggested UV-space parallax scale for a shader that treats 0.5 as neutral:
    //! uvOffset = (height - 0.5) * 2 * recommendedUvScale * viewTangent.xy / viewTangent.z.
    float recommendedUvScale = 0.0f;

    //! Wall time of rasterizing both surfaces and building the map, in milliseconds.
    double bakeMs = 0.0;
};

/**
 * Bakes the difference between the source surface normal and the LOD surface normal into a
 * tangent-space normal map.
 *
 * Both meshes must share the same UV parameterization. `lodIndices` indexes `lod.positions`.
 * The result is neutral (0, 0, 1) outside the LOD UV layout. Returns false if either mesh lacks
 * normals or UVs, or if no texel is shared.
 */
bool bakeDetailNormalMap(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& lodIndices, DetailBakeOptions const& options,
        DetailBakeResult* result);

/**
 * Bakes the signed displacement between the source surface and the LOD into the LOD's UV
 * layout.
 *
 * Both meshes are rasterized in the same UV atlas. For every texel covered by both, the source
 * position minus the LOD position is projected onto the interpolated LOD normal. This is the
 * missing piece a tangent-space normal map cannot provide: a normal map changes shading, while
 * this map changes where the shading is sampled. It lets a fragment shader do iterative
 * parallax mapping and recover some of the surface displacement, self-occlusion and
 * high-frequency detail lost by a coarse chord.
 *
 * The source and LOD must share a UV parameterization and every LOD UV must lie in [0,1].
 * Returns false if either mesh lacks UVs, the LOD lacks normals, or no texel is shared.
 * Silhouette coverage still cannot be recovered by shading.
 */
bool bakeDetailHeightMap(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& lodIndices, DetailHeightOptions const& options,
        DetailHeightResult* result);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_DETAILBAKE_H
