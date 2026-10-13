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

#ifndef TNT_MANYMESH_CLUSTER_H
#define TNT_MANYMESH_CLUSTER_H

#include <math/vec3.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

//! Bounding sphere of a cluster, in world space.
struct Sphere {
    math::float3 center{};
    float radius = 0.0f;
};

/**
 * Normal cone of a cluster, as produced by meshopt_computeMeshletBounds.
 *
 * Used for backface culling of whole clusters; also a useful spatial descriptor for free.
 */
struct Cone {
    math::float3 apex{};
    math::float3 axis{};
    float cutoff = 0.0f;  //!< cos(half angle) within which the cone is guaranteed to contain the normals
};

/**
 * One group of triangles that is simplified, selected and (eventually) culled as a unit.
 *
 * Indices point directly at the owning Mesh's vertex buffer, three per triangle. The
 * micro-index indirection that meshoptimizer uses internally is expanded away, so consumers
 * never have to know about it.
 */
struct Cluster {
    std::vector<uint32_t> indices;
    Sphere bounds;
    Cone cone;

    size_t triangleCount() const noexcept { return indices.size() / 3; }
};

struct ClusterSet {
    uint32_t maxVertices = 0;
    uint32_t maxTriangles = 0;
    std::vector<Cluster> clusters;
};

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_CLUSTER_H
