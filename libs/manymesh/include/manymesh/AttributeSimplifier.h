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

#ifndef TNT_MANYMESH_ATTRIBUTESIMPLIFIER_H
#define TNT_MANYMESH_ATTRIBUTESIMPLIFIER_H

#include <manymesh/Mesh.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * Options for the attribute-aware edge collapse pass.
 *
 * The pass is intentionally small-unit oriented: it keeps one quadric per retained vertex and
 * re-evaluates only the edges around a collapse, so a cluster group is cheap while a global
 * million-triangle chain is not. The regular Simplifier falls back to meshoptimizer's
 * position-only QEM plus a post-simplification quality gate for those large units.
 */
struct AttributeSimplifyOptions {
    size_t targetIndexCount = 0;
    bool lockBorder = true;
    //! Optional global-vertex mask (mesh.positions.size() long). A set entry means the vertex
    //! is shared with another simplification unit and must not be removed or rewritten. This
    //! is stronger than border-edge locking: two clusters can meet at a single vertex without
    //! sharing an edge, and a collapse through that vertex can create a chord across the seam.
    std::vector<uint8_t> const* lockedVertices = nullptr;
    float minTriangleQuality = 0.02f;
    float maxNormalErrorDegrees = 35.0f;
    float maxUvError = 0.10f;
    float positionWeight = 1.0f;
    float normalWeight = 1.0f;
    float uvWeight = 1.0f;
};

/**
 * Simplifies `source` with a QEM whose cost includes position, normal and UV terms.
 *
 * Indices reference `mesh.positions` (the shared vertex buffer). The result also references
 * that buffer, so attributes are carried through unchanged. Returns false when no safe
 * collapse was possible or when the target could not be reached; `outIndices` then contains
 * the best valid mesh found, which is never worse than the input topology.
 */
bool simplifyWithAttributes(Mesh const& mesh, std::vector<uint32_t> const& source,
        AttributeSimplifyOptions const& options, std::vector<uint32_t>* outIndices,
        float* outWorldError = nullptr);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_ATTRIBUTESIMPLIFIER_H
