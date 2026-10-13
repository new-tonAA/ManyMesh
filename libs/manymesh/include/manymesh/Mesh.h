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

#ifndef TNT_MANYMESH_MESH_H
#define TNT_MANYMESH_MESH_H

#include <math/vec2.h>
#include <math/vec3.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * A plain CPU-side triangle mesh.
 *
 * This is deliberately independent of filament::Engine: the whole geometry optimization
 * layer runs offline, on host memory, before anything is uploaded to the GPU.
 *
 * Positions are the only mandatory attribute; every error metric in this library is derived
 * from them. Normals and UVs are carried along so that LOD results can be written back out
 * for inspection (and, later, re-shaded), but they take no part in simplification.
 */
struct Mesh {
    std::vector<math::float3> positions;
    std::vector<math::float3> normals;  //!< optional, either empty or positions.size() long
    std::vector<math::float2> uvs;      //!< optional, either empty or positions.size() long
    std::vector<uint32_t> indices;      //!< 3 entries per triangle

    size_t vertexCount() const noexcept { return positions.size(); }
    size_t triangleCount() const noexcept { return indices.size() / 3; }

    bool empty() const noexcept { return positions.empty() || indices.empty(); }
};

/**
 * Axis aligned bounds of the positions. For an empty mesh, both are left untouched.
 */
void computeBounds(Mesh const& mesh, math::float3* boundsMin, math::float3* boundsMax) noexcept;

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_MESH_H
