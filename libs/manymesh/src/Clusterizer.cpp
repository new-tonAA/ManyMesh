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
#include <functional>
#include <unordered_map>
#include <utility>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

// meshopt_buildMeshlets stores micro-indices in a byte, which caps the vertex count of a
// cluster below 256, and refuses more than 512 triangles per cluster.
constexpr size_t MAX_MESHLET_VERTICES = 255;
constexpr size_t MAX_MESHLET_TRIANGLES = 512;

ClusterSet clusterizeSingle(Mesh const& mesh, ClusterizeOptions const& options,
        uint32_t materialId = UINT32_MAX, uint32_t submeshId = UINT32_MAX) {
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
        cluster.materialId = materialId;
        cluster.submeshId = submeshId;

        result.clusters.push_back(std::move(cluster));
    }

    return result;
}

struct Chart {
    std::vector<uint32_t> indices;
    uint32_t materialId = UINT32_MAX;
    uint32_t submeshId = UINT32_MAX;
};

struct EdgeAttributeKey {
    uint32_t a = 0;
    uint32_t b = 0;
    uint32_t materialId = 0;
    uint32_t submeshId = 0;

    bool operator==(EdgeAttributeKey const& other) const noexcept {
        return a == other.a && b == other.b
                && materialId == other.materialId && submeshId == other.submeshId;
    }
};

struct EdgeAttributeKeyHash {
    size_t operator()(EdgeAttributeKey const& key) const noexcept {
        uint64_t const vertices = (uint64_t(key.a) << 32) | uint64_t(key.b);
        return std::hash<uint64_t>()(vertices)
                ^ (std::hash<uint32_t>()(key.materialId) << 1)
                ^ (std::hash<uint32_t>()(key.submeshId) << 2);
    }
};

// Splits triangles into connected components using edge adjacency within the same material
// and submesh. Importers duplicate vertices at UV and normal seams, so those seams become
// component boundaries here. Material and submesh boundaries are boundaries even when the
// importer shares vertices across them. Clustering each component independently keeps all
// attribute boundaries on cluster borders, where the border lock protects them.
std::vector<Chart> splitCharts(Mesh const& mesh) {
    std::vector<Chart> charts;
    if (mesh.indices.empty()) {
        return charts;
    }

    size_t const triangleCount = mesh.triangleCount();
    std::vector<uint32_t> parent(triangleCount);
    for (uint32_t t = 0; t < triangleCount; ++t) {
        parent[t] = t;
    }

    auto find = [&parent](uint32_t t) {
        while (parent[t] != t) {
            parent[t] = parent[parent[t]];
            t = parent[t];
        }
        return t;
    };

    auto unite = [&parent, &find](uint32_t a, uint32_t b) {
        a = find(a);
        b = find(b);
        if (a != b) {
            parent[b] = a;
        }
    };

    auto materialAt = [&mesh](size_t triangle) {
        return mesh.hasMaterialIds() ? mesh.materialIds[triangle] : 0u;
    };
    auto submeshAt = [&mesh](size_t triangle) {
        return mesh.hasSubmeshIds() ? mesh.submeshIds[triangle] : 0u;
    };

    std::unordered_map<EdgeAttributeKey, uint32_t, EdgeAttributeKeyHash> firstTriangle;
    firstTriangle.reserve(triangleCount * 3);
    for (size_t t = 0; t < triangleCount; ++t) {
        uint32_t const vertices[3] = {
            mesh.indices[t * 3 + 0], mesh.indices[t * 3 + 1], mesh.indices[t * 3 + 2] };
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = std::min(vertices[e], vertices[(e + 1) % 3]);
            uint32_t const b = std::max(vertices[e], vertices[(e + 1) % 3]);
            EdgeAttributeKey const key = {
                a, b, materialAt(t), submeshAt(t)
            };
            auto const [it, inserted] = firstTriangle.emplace(key, uint32_t(t));
            if (!inserted) {
                unite(uint32_t(t), it->second);
            }
        }
    }

    std::vector<int32_t> chartOfRoot(triangleCount, -1);
    for (size_t t = 0; t < triangleCount; ++t) {
        uint32_t const root = find(uint32_t(t));
        int32_t chart = chartOfRoot[root];
        if (chart < 0) {
            chart = int32_t(charts.size());
            chartOfRoot[root] = chart;
            charts.emplace_back();
            charts.back().materialId = materialAt(t);
            charts.back().submeshId = submeshAt(t);
        }
        std::vector<uint32_t>& indices = charts[size_t(chart)].indices;
        size_t const i = t * 3;
        indices.push_back(mesh.indices[i + 0]);
        indices.push_back(mesh.indices[i + 1]);
        indices.push_back(mesh.indices[i + 2]);
    }

    return charts;
}

} // anonymous namespace

ClusterSet clusterize(Mesh const& mesh, ClusterizeOptions const& options) {
    ClusterSet result;
    result.maxVertices = options.maxVertices;
    result.maxTriangles = options.maxTriangles;

    if (mesh.empty()) {
        return result;
    }

    if (!options.splitCharts) {
        return clusterizeSingle(mesh, options);
    }

    std::vector<Chart> const charts = splitCharts(mesh);
    if (charts.empty()) {
        return result;
    }

    std::vector<int32_t> localOfGlobal(mesh.positions.size(), -1);
    std::vector<uint32_t> localToGlobal;

    for (Chart const& chart : charts) {
        Mesh local;
        local.indices = chart.indices;
        local.positions.reserve(chart.indices.size());
        localToGlobal.clear();

        for (uint32_t& index : local.indices) {
            uint32_t const global = index;
            int32_t& localIndex = localOfGlobal[global];
            if (localIndex < 0) {
                localIndex = int32_t(localToGlobal.size());
                localToGlobal.push_back(global);
                local.positions.push_back(mesh.positions[global]);
            }
            index = uint32_t(localIndex);
        }

        ClusterSet const localClusters = clusterizeSingle(local, options,
                chart.materialId, chart.submeshId);
        for (Cluster cluster : localClusters.clusters) {
            for (uint32_t& index : cluster.indices) {
                index = localToGlobal[index];
            }
            result.clusters.push_back(std::move(cluster));
        }

        for (uint32_t global : localToGlobal) {
            localOfGlobal[global] = -1;
        }
    }

    return result;
}

} // namespace manymesh
} // namespace filament
