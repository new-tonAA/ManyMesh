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

#include <manymesh/Clusterizer.h>

#include <meshoptimizer.h>

#include <algorithm>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

// meshopt_buildMeshlets stores micro-indices in a byte, which caps the vertex count of a
// cluster below 256, and refuses more than 512 triangles per cluster.
constexpr size_t MAX_MESHLET_VERTICES = 255;
constexpr size_t MAX_MESHLET_TRIANGLES = 512;

} // anonymous namespace

ClusterSet clusterize(Mesh const& mesh, ClusterizeOptions const& options) {
    ClusterSet result;
    result.maxVertices = options.maxVertices;
    result.maxTriangles = options.maxTriangles;

    if (mesh.empty()) {
        return result;
    }

    size_t const maxVertices = std::clamp<size_t>(options.maxVertices, 1, MAX_MESHLET_VERTICES);
    size_t const maxTriangles = std::clamp<size_t>(options.maxTriangles, 1, MAX_MESHLET_TRIANGLES);

    float const* const positions = &mesh.positions[0].x;
    size_t const vertexCount = mesh.positions.size();
    size_t const vertexStride = sizeof(math::float3);

    size_t const bound = meshopt_buildMeshletsBound(mesh.indices.size(), maxVertices, maxTriangles);

    std::vector<meshopt_Meshlet> meshlets(bound);
    std::vector<unsigned int> meshletVertices(bound * maxVertices);
    std::vector<unsigned char> meshletTriangles(bound * maxTriangles * 3);

    size_t const meshletCount = meshopt_buildMeshlets(meshlets.data(), meshletVertices.data(),
            meshletTriangles.data(), mesh.indices.data(), mesh.indices.size(),
            positions, vertexCount, vertexStride,
            maxVertices, maxTriangles, options.coneWeight);

    meshlets.resize(meshletCount);

    result.clusters.reserve(meshletCount);
    for (meshopt_Meshlet const& meshlet : meshlets) {
        meshopt_Bounds const bounds = meshopt_computeMeshletBounds(
                &meshletVertices[meshlet.vertex_offset],
                &meshletTriangles[meshlet.triangle_offset],
                meshlet.triangle_count,
                positions, vertexCount, vertexStride);

        Cluster cluster;

        // Expand meshoptimizer's byte-sized micro-indices into plain indices into the mesh
        // vertex buffer. Consumers of this library never have to know about the indirection.
        cluster.indices.resize(meshlet.triangle_count * 3);
        for (size_t i = 0; i < cluster.indices.size(); ++i) {
            cluster.indices[i] = meshletVertices[meshlet.vertex_offset
                    + meshletTriangles[meshlet.triangle_offset + i]];
        }

        cluster.bounds.center = { bounds.center[0], bounds.center[1], bounds.center[2] };
        cluster.bounds.radius = bounds.radius;
        cluster.cone.apex = { bounds.cone_apex[0], bounds.cone_apex[1], bounds.cone_apex[2] };
        cluster.cone.axis = { bounds.cone_axis[0], bounds.cone_axis[1], bounds.cone_axis[2] };
        cluster.cone.cutoff = bounds.cone_cutoff;

        result.clusters.push_back(std::move(cluster));
    }

    return result;
}

} // namespace manymesh
} // namespace filament
