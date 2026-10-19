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

#ifndef TNT_MANYMESH_CORNERSIMPLIFIER_H
#define TNT_MANYMESH_CORNERSIMPLIFIER_H

#include <manymesh/Mesh.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * A vertex created by the corner simplifier.
 *
 * A generated vertex is either an attribute split at an existing position, or the result of a
 * QEM-optimal collapse that moved the merged vertex. `positionSource` records the original
 * vertex it started from so lock masks and neighbour queries still work; `position` is the
 * position the renderer must use. Interpolating attributes per chart is what lets a UV or
 * normal seam shrink without opening a hole.
 */
struct GeneratedVertex {
    //! Original vertex whose position this vertex started from. It is used for lock masks and for
    //! reading older graph files that did not store an explicit position.
    uint32_t positionSource = 0;
    math::float3 position{};
    math::float3 normal{};
    math::float2 uv{};
    //! Source-mesh ambient occlusion interpolated to this vertex. 1 means fully visible and is
    //! also the value used by assets that do not carry an AO field.
    float ao = 1.0f;
    //! True when `position` is authoritative. False only for generated vertices read from a
    //! version-4 graph, where the position has to be recovered from `positionSource`.
    bool hasPosition = false;

    bool operator==(GeneratedVertex const& other) const noexcept {
        return positionSource == other.positionSource && position == other.position &&
               normal == other.normal && uv == other.uv && ao == other.ao &&
               hasPosition == other.hasPosition;
    }
};

/**
 * Optional stage timing for the corner simplifier. The fields are accumulated across calls;
 * pass a zero-initialised instance through CornerSimplifyOptions::profile.
 */
struct CornerSimplifyProfile {
    double setupSeconds = 0.0;
    double evaluateSeconds = 0.0;
    double evaluateTopologySeconds = 0.0;
    double topologyNeighborSeconds = 0.0;
    double topologyTriangleSeconds = 0.0;
    double topologyLocalTriangleSeconds = 0.0;
    double topologyLocalEdgeSeconds = 0.0;
    double evaluateTargetSeconds = 0.0;
    double applySeconds = 0.0;
    uint64_t evaluations = 0;
    uint64_t placementTests = 0;
    uint64_t applied = 0;
};

struct CornerSimplifyOptions {
    //! Stop once the result has at most this many indices.
    size_t targetIndexCount = 0;

    //! Never move or remove a vertex on the welded outline of the unit.
    bool lockBorder = true;

    //! Optional global-vertex mask that marks vertices shared with another simplification unit.
    //! Such vertices, and every vertex welded to them, are treated as locked.
    std::vector<uint8_t> const* lockedVertices = nullptr;

    //! Maps a vertex id to the position id used by `lockedVertices`. Generated vertices reuse the
    //! position of an earlier vertex, so this lets the mask apply to them too. nullptr means the
    //! identity mapping.
    std::vector<uint32_t> const* vertexPositionIds = nullptr;

    float minTriangleQuality = 0.02f;
    float maxNormalErrorDegrees = 35.0f;
    float maxUvError = 0.10f;

    float positionWeight = 1.0f;
    float normalWeight = 1.0f;
    float uvWeight = 1.0f;

    //! Reject collapses whose interpolated corner attributes exceed the limits above. When
    //! adjacent triangles interpolate one source vertex to divergent UVs, the output keeps them
    //! in separate generated vertices instead of rejecting the collapse or averaging the charts.
    bool attributeGate = true;

    //! Partition corners that share one moved vertex by their interpolated UV. This is what keeps
    //! a chart's affine parameterization intact when several triangles extrapolate the same
    //! source corner differently. Disable it for A/B measurements that intentionally average the
    //! charts; production output must leave it enabled.
    bool splitDivergentUv = true;

    //! Optional stage timing sink. Null disables profiling.
    CornerSimplifyProfile* profile = nullptr;
};

/**
 * Simplifies `source` while welding vertices that share a position.
 *
 * The input may be a full mesh or one unit (cluster/group) of it. Unlike simplifyWithAttributes,
 * which keeps one normal/UV per vertex, this pass tracks attributes per triangle corner and
 * interpolates them through every collapse. A duplicated UV/normal seam therefore becomes an
 * interior edge of the welded surface and can be simplified, while each chart keeps its own
 * parameterization at the corners that survive.
 *
 * A collapse can move one welded vertex while its adjacent triangles extrapolate different UVs.
 * Such corners are emitted as several generated vertices at the same position, one per UV
 * cluster, so a chart seam never forces the simplifier to keep an otherwise removable triangle.
 *
 * Indices below `mesh.vertexCount()` reference the input vertices. Indices at or above it
 * reference `outGenerated[index - mesh.vertexCount()]`. The caller owns those vertices and must
 * keep them next to the input buffer when the result is rendered or measured.
 *
 * Returns false when the source is already at or below the target, or when no acceptable
 * collapse exists. `outIndices` then contains the best result found (possibly the source).
 */
bool simplifyWithCornerAttributes(Mesh const& mesh, std::vector<uint32_t> const& source,
        CornerSimplifyOptions const& options, std::vector<uint32_t>* outIndices,
        std::vector<GeneratedVertex>* outGenerated, float* outWorldError = nullptr);

/**
 * Appends generated vertices to `mesh`. This is the inverse of the index encoding above and is
 * used by tools that need one self-contained vertex buffer for the result.
 */
void appendGeneratedVertices(Mesh* mesh, std::vector<GeneratedVertex> const& generated);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_CORNERSIMPLIFIER_H
