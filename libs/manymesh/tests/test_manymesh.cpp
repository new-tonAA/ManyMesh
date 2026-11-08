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

#include <manymesh/AmbientOcclusion.h>
#include <manymesh/AttributeSimplifier.h>
#include <manymesh/Clusterizer.h>
#include <manymesh/CornerSimplifier.h>
#include <manymesh/DetailBake.h>
#include <manymesh/GeometryError.h>
#include <manymesh/GpuLod.h>
#include <manymesh/Grouper.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/Quality.h>
#include <manymesh/ShadingNormals.h>
#include <manymesh/Simplifier.h>
#include <manymesh/Streaming.h>
#include <manymesh/VisibilityBuffer.h>

#include <math/vec3.h>

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <thread>
#include <vector>

namespace math = filament::math;
using namespace filament::manymesh;

namespace {

// A wavy grid in the XY plane. amplitude 0 gives a perfectly flat sheet, which QEM can
// collapse almost for free; a non zero amplitude gives it something to lose.
Mesh makeGrid(uint32_t nx, uint32_t ny, math::float3 origin, float spacing, float amplitude) {
    Mesh mesh;
    mesh.positions.reserve((nx + 1) * (ny + 1));

    for (uint32_t j = 0; j <= ny; ++j) {
        for (uint32_t i = 0; i <= nx; ++i) {
            float const z = amplitude * std::sin(float(i) * 0.7f) * std::cos(float(j) * 0.9f);
            mesh.positions.push_back(
                    origin + math::float3{ float(i) * spacing, float(j) * spacing, z });
        }
    }

    auto index = [nx](uint32_t i, uint32_t j) { return j * (nx + 1) + i; };
    mesh.indices.reserve(size_t(nx) * size_t(ny) * 6);
    for (uint32_t j = 0; j < ny; ++j) {
        for (uint32_t i = 0; i < nx; ++i) {
            mesh.indices.push_back(index(i, j));
            mesh.indices.push_back(index(i + 1, j));
            mesh.indices.push_back(index(i + 1, j + 1));

            mesh.indices.push_back(index(i, j));
            mesh.indices.push_back(index(i + 1, j + 1));
            mesh.indices.push_back(index(i, j + 1));
        }
    }

    return mesh;
}

// Appends `source` to `destination`, offsetting its indices.
void append(Mesh* destination, Mesh const& source) {
    uint32_t const offset = uint32_t(destination->positions.size());
    destination->positions.insert(destination->positions.end(), source.positions.begin(),
            source.positions.end());
    for (uint32_t index: source.indices) {
        destination->indices.push_back(offset + index);
    }
}

// Three pie-slice charts cover a full disk. Every chart has its own centre vertex at the same
// position and its own radial seam, so the centre has three attribute copies while the welded
// surface is a closed disk. The charts use different UV islands and normals and the surface is
// deliberately non-planar; this is the regression shape for 3+ seam copies.
Mesh makeThreeSectorDisk(std::array<uint32_t, 3>* centres) {
    Mesh mesh;
    auto appendSector = [&mesh](float angleBegin, float angleEnd, float uOffset, float vOffset,
                                float uvScale, math::float3 normal) {
        constexpr uint32_t kRadialSteps = 8;
        constexpr uint32_t kAngularSteps = 12;
        constexpr float kRadius = 1.0f;
        uint32_t const base = uint32_t(mesh.positions.size());

        auto positionAt = [](float radius, float angle) {
            float const x = radius * std::cos(angle);
            float const y = radius * std::sin(angle);
            float const z = 0.12f * std::sin(x * 2.1f) * std::cos(y * 1.7f);
            return math::float3{ x, y, z };
        };
        auto uvAt = [uOffset, vOffset, uvScale](math::float3 const& position) {
            float const u = uOffset + (position.x / kRadius + 1.0f) * 0.5f * uvScale;
            float const v = vOffset + (position.y / kRadius + 1.0f) * 0.5f * uvScale;
            return math::float2{ u, v };
        };

        mesh.positions.push_back(positionAt(0.0f, 0.0f));
        mesh.normals.push_back(normal);
        mesh.uvs.push_back(uvAt(mesh.positions.back()));

        for (uint32_t ring = 1; ring <= kRadialSteps; ++ring) {
            float const radius = kRadius * float(ring) / float(kRadialSteps);
            for (uint32_t step = 0; step <= kAngularSteps; ++step) {
                float const t = float(step) / float(kAngularSteps);
                float const angle = angleBegin + (angleEnd - angleBegin) * t;
                math::float3 const position = positionAt(radius, angle);
                mesh.positions.push_back(position);
                mesh.normals.push_back(normal);
                mesh.uvs.push_back(uvAt(position));
            }
        }

        uint32_t const firstRing = base + 1;
        for (uint32_t step = 0; step < kAngularSteps; ++step) {
            mesh.indices.insert(mesh.indices.end(),
                    { base, firstRing + step, firstRing + step + 1 });
        }
        for (uint32_t ring = 1; ring < kRadialSteps; ++ring) {
            uint32_t const inner = base + 1 + (ring - 1) * (kAngularSteps + 1);
            uint32_t const outer = inner + (kAngularSteps + 1);
            for (uint32_t step = 0; step < kAngularSteps; ++step) {
                mesh.indices.insert(mesh.indices.end(),
                        { inner + step, outer + step, outer + step + 1 });
                mesh.indices.insert(mesh.indices.end(),
                        { inner + step, outer + step + 1, inner + step + 1 });
            }
        }
        return base;
    };

    (*centres)[0] = appendSector(0.0f, 2.0943951f, 0.02f, 0.03f, 0.30f,
            normalize(math::float3{ 0.04f, 0.0f, 1.0f }));
    (*centres)[1] = appendSector(2.0943951f, 4.1887902f, 0.36f, 0.03f, 0.28f,
            normalize(math::float3{ -0.02f, 0.03f, 1.0f }));
    (*centres)[2] = appendSector(4.1887902f, 6.2831853f, 0.70f, 0.03f, 0.27f,
            normalize(math::float3{ 0.01f, -0.04f, 1.0f }));
    return mesh;
}

using Triangle = std::array<uint32_t, 3>;

std::vector<Triangle> trianglesOf(Mesh const& mesh) {
    std::vector<Triangle> result;
    result.reserve(mesh.triangleCount());
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        Triangle triangle = { mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2] };
        std::sort(triangle.begin(), triangle.end());
        result.push_back(triangle);
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<Triangle> trianglesOf(ClusterSet const& clusters) {
    std::vector<Triangle> result;
    for (Cluster const& cluster: clusters.clusters) {
        for (size_t i = 0; i + 2 < cluster.indices.size(); i += 3) {
            Triangle triangle = { cluster.indices[i], cluster.indices[i + 1],
                cluster.indices[i + 2] };
            std::sort(triangle.begin(), triangle.end());
            result.push_back(triangle);
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

// Vertices sitting on an edge that only one triangle of the cluster uses, i.e. the cluster's
// outer boundary.
std::set<uint32_t> borderVertices(std::vector<uint32_t> const& indices) {
    std::map<std::pair<uint32_t, uint32_t>, int> edgeUse;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const v[3] = { indices[i], indices[i + 1], indices[i + 2] };
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = std::min(v[e], v[(e + 1) % 3]);
            uint32_t const b = std::max(v[e], v[(e + 1) % 3]);
            edgeUse[{ a, b }] += 1;
        }
    }

    std::set<uint32_t> result;
    for (auto const& [edge, count]: edgeUse) {
        if (count == 1) {
            result.insert(edge.first);
            result.insert(edge.second);
        }
    }
    return result;
}

std::set<std::pair<uint32_t, uint32_t>> boundaryEdgeSet(std::vector<uint32_t> const& indices) {
    std::map<std::pair<uint32_t, uint32_t>, int> edgeUse;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const v[3] = { indices[i], indices[i + 1], indices[i + 2] };
        for (int e = 0; e < 3; ++e) {
            edgeUse[{ std::min(v[e], v[(e + 1) % 3]), std::max(v[e], v[(e + 1) % 3]) }] += 1;
        }
    }
    std::set<std::pair<uint32_t, uint32_t>> result;
    for (auto const& [edge, count]: edgeUse) {
        if (count == 1) {
            result.insert(edge);
        }
    }
    return result;
}

using WeldedEdge = std::pair<std::array<int64_t, 3>, std::array<int64_t, 3>>;

std::set<WeldedEdge> weldedBoundarySet(Mesh const& mesh, std::vector<uint32_t> const& indices) {
    auto position = [&mesh](uint32_t vertex) {
        math::float3 const p = mesh.positions[vertex];
        return std::array<int64_t, 3>{ int64_t(std::llround(p.x * 100000.0f)),
            int64_t(std::llround(p.y * 100000.0f)), int64_t(std::llround(p.z * 100000.0f)) };
    };
    std::map<std::pair<std::array<int64_t, 3>, std::array<int64_t, 3>>, int> use;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        std::array<std::array<int64_t, 3>, 3> const v = { position(indices[i + 0]),
            position(indices[i + 1]), position(indices[i + 2]) };
        for (int e = 0; e < 3; ++e) {
            std::array<int64_t, 3> a = v[e];
            std::array<int64_t, 3> b = v[(e + 1) % 3];
            if (b < a) {
                std::swap(a, b);
            }
            use[{ a, b }] += 1;
        }
    }
    std::set<WeldedEdge> result;
    for (auto const& [edge, count]: use) {
        if (count == 1) {
            result.insert(edge);
        }
    }
    return result;
}

double meanLevel(std::vector<uint32_t> const& levels, std::vector<size_t> const& clusterIndices) {
    if (clusterIndices.empty()) {
        return 0.0;
    }
    double total = 0.0;
    for (size_t index: clusterIndices) {
        total += double(levels[index]);
    }
    return total / double(clusterIndices.size());
}

} // anonymous namespace

TEST(ManyMesh, ClusterizeCoversEveryTriangleExactlyOnce) {
    Mesh const mesh = makeGrid(16, 16, {}, 1.0f, 0.2f);

    ClusterizeOptions options;
    options.maxVertices = 64;
    options.maxTriangles = 64;

    ClusterSet const clusters = clusterize(mesh, options);
    ASSERT_FALSE(clusters.clusters.empty());

    EXPECT_EQ(trianglesOf(clusters), trianglesOf(mesh));
}

TEST(ManyMesh, ClusterizeIsDeterministic) {
    Mesh const mesh = makeGrid(16, 16, {}, 1.0f, 0.2f);

    ClusterizeOptions options;
    options.maxVertices = 64;
    options.maxTriangles = 64;

    ClusterSet const first = clusterize(mesh, options);
    ClusterSet const second = clusterize(mesh, options);

    ASSERT_EQ(first.clusters.size(), second.clusters.size());
    for (size_t c = 0; c < first.clusters.size(); ++c) {
        EXPECT_EQ(first.clusters[c].indices, second.clusters[c].indices);
        EXPECT_FLOAT_EQ(first.clusters[c].bounds.radius, second.clusters[c].bounds.radius);
    }
}

TEST(ManyMesh, ClusterizeSeparatesAttributeCharts) {
    // Two grids that touch geometrically but do not share vertex indices. This is how an
    // importer represents a UV or normal seam: the positions coincide, the vertices do not.
    Mesh mesh = makeGrid(16, 16, {}, 1.0f, 0.2f);
    uint32_t const chartVertexCount = uint32_t(mesh.positions.size());
    append(&mesh, makeGrid(16, 16, { 16.0f, 0.0f, 0.0f }, 1.0f, 0.2f));

    ClusterizeOptions options;
    options.maxVertices = 64;
    options.maxTriangles = 64;
    options.splitCharts = true;

    ClusterSet const clusters = clusterize(mesh, options);
    ASSERT_GE(clusters.clusters.size(), 2u);

    for (Cluster const& cluster: clusters.clusters) {
        bool inFirstChart = false;
        bool inSecondChart = false;
        for (uint32_t index: cluster.indices) {
            if (index < chartVertexCount) {
                inFirstChart = true;
            } else {
                inSecondChart = true;
            }
        }
        EXPECT_FALSE(inFirstChart && inSecondChart)
                << "a cluster crossed an attribute seam, so the border lock cannot protect it";
    }
}

TEST(ManyMesh, ChainLosesTrianglesAndGainsError) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);

    SimplifyOptions options;
    options.levels = 5;
    options.ratio = 0.7f;

    std::vector<LodLevel> const levels = simplifyChain(mesh, options);
    ASSERT_GE(levels.size(), 2u);

    EXPECT_EQ(levels[0].indices, mesh.indices);

    for (size_t l = 1; l < levels.size(); ++l) {
        EXPECT_LT(levels[l].triangleCount(), levels[l - 1].triangleCount()) << "level " << l;
        EXPECT_GE(levels[l].worldError, levels[l - 1].worldError) << "level " << l;
    }

    // The surface was curved, so coarsening it cannot have been free.
    EXPECT_GT(levels.back().worldError, 0.0f);
    EXPECT_LT(levels.back().triangleCount(), levels.front().triangleCount());
}

TEST(ManyMesh, ClusterLodsAreMonotonicAndStartFromTheCluster) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    SimplifyOptions options;
    options.levels = 4;
    options.ratio = 0.7f;
    options.lockBorder = true;

    std::vector<ClusterLods> const lods = simplifyClusters(mesh, clusters, options);
    ASSERT_EQ(lods.size(), clusters.clusters.size());

    size_t simplifiedClusters = 0;
    for (size_t c = 0; c < lods.size(); ++c) {
        ASSERT_FALSE(lods[c].levels.empty());
        EXPECT_EQ(lods[c].levels[0].indices, clusters.clusters[c].indices);

        if (lods[c].levels.size() > 1) {
            simplifiedClusters += 1;
        }
        for (size_t l = 1; l < lods[c].levels.size(); ++l) {
            EXPECT_LT(lods[c].levels[l].triangleCount(), lods[c].levels[l - 1].triangleCount());
            EXPECT_GE(lods[c].levels[l].worldError, lods[c].levels[l - 1].worldError);
        }
    }

    EXPECT_GT(simplifiedClusters, 0u) << "no cluster could be simplified at all";
}

TEST(ManyMesh, ScreenSpaceErrorScalesWithDistanceAndError) {
    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 0.0f };
    camera.target = { 0.0f, 0.0f, -1.0f };
    camera.fovY = 1.5707963f; // 90 degrees, so tan(fov/2) == 1
    camera.screenHeight = 1000;

    // pixelsPerRadian == 1000 / (2 * 1) == 500, so a unit error at depth 10 covers 50 pixels.
    EXPECT_NEAR(screenSpaceError(1.0f, { 0.0f, 0.0f, -10.0f }, camera), 50.0f, 0.01f);
    EXPECT_NEAR(screenSpaceError(1.0f, { 0.0f, 0.0f, -20.0f }, camera), 25.0f, 0.01f);
    EXPECT_NEAR(screenSpaceError(2.0f, { 0.0f, 0.0f, -10.0f }, camera), 100.0f, 0.01f);
}

TEST(ManyMesh, ScreenSpaceErrorForSphereUsesNearestDepth) {
    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 0.0f };
    camera.target = { 0.0f, 0.0f, -1.0f };
    camera.fovY = 1.5707963f; // 90 degrees, so tan(fov/2) == 1
    camera.screenHeight = 1000;
    camera.near = 0.01f;

    ScreenErrorProjection const projection = makeScreenErrorProjection(camera);
    ASSERT_TRUE(projection.valid);

    // The sphere centre is 10 units away, but its nearest point is 8 units away. The error must
    // use 8, matching screenSpaceError() at the nearest surface point.
    Sphere const sphere{ { 0.0f, 0.0f, -10.0f }, 2.0f };
    EXPECT_NEAR(screenSpaceErrorForSphere(1.0f, sphere, projection), 62.5f, 0.01f);
    EXPECT_NEAR(screenSpaceError(1.0f, { 0.0f, 0.0f, -8.0f }, camera), 62.5f, 0.01f);

    // A sphere that crosses the near plane is clamped to the near distance instead of being
    // treated as infinitely far away or being allowed to divide by zero.
    Sphere const crossing{ { 0.0f, 0.0f, 0.05f }, 0.1f };
    EXPECT_NEAR(screenSpaceErrorForSphere(1.0f, crossing, projection), 50000.0f, 1.0f);
}

TEST(ManyMesh, LodGraphCutUsesNearestSphereDepth) {
    // Root centre is 10 units away and its radius is 2, so the nearest surface is at depth 8.
    // With a 1-unit accumulated error and 500 pixels/radian this is 62.5 px, not 50 px.
    LodGraph graph;
    graph.levelCount = 2;
    graph.nodes.resize(3);
    graph.nodes[0].level = 1;
    graph.nodes[0].children = { 1, 2 };
    graph.nodes[0].bounds = { { 0.0f, 0.0f, -10.0f }, 2.0f };
    graph.nodes[0].accumulatedError = 1.0f;
    for (uint32_t child: { 1u, 2u }) {
        graph.nodes[child].level = 0;
        graph.nodes[child].bounds = { { 0.0f, 0.0f, -10.0f }, 0.5f };
    }
    graph.roots = { 0 };
    graph.leaves = { 1, 2 };

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 0.0f };
    camera.target = { 0.0f, 0.0f, -1.0f };
    camera.fovY = 1.5707963f;
    camera.screenHeight = 1000;
    camera.near = 0.01f;

    // A centre-depth implementation would see 50 px and accept the root at 55 px.
    LodGraphCut const fine = selectLodGraphCut(graph, camera, 55.0f);
    ASSERT_EQ(fine.nodes.size(), 2u);
    EXPECT_EQ(fine.nodes[0], 1u);
    EXPECT_EQ(fine.nodes[1], 2u);

    LodGraphCut const coarse = selectLodGraphCut(graph, camera, 70.0f);
    ASSERT_EQ(coarse.nodes.size(), 1u);
    EXPECT_EQ(coarse.nodes[0], 0u);
}

TEST(ManyMesh, FrustumCutKeepsSpheresIntersectingSidePlanes) {
    using filament::math::float3;
    LodGraph graph;
    graph.levelCount = 1;
    graph.baseTriangles = 1;
    graph.roots = { 0 };
    graph.leaves = { 0 };
    graph.nodes.resize(1);
    LodGraphNode& node = graph.nodes.front();
    node.indices = { 0, 1, 2 };
    node.baseTriangles = 1;

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 0.0f };
    camera.target = { 0.0f, 0.0f, -1.0f };
    camera.fovY = 1.5707963f;
    camera.screenWidth = camera.screenHeight = 720;

    // At z = -10 the side planes are at x and y = +/-10. An axis offset of 1.2 is
    // only 1.2 / sqrt(2) from the plane, so a unit sphere still intersects the frustum.
    float3 const axes[] = { { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 }, { 0, -1, 0 } };
    for (float3 const axis: axes) {
        node.bounds = { float3{ 0, 0, -10 } + axis * 11.2f, 1.0f };
        EXPECT_EQ(selectLodGraphCut(graph, camera, 2.0f).selectedTriangles, 1u);
        EXPECT_EQ(selectLodGraph(graph, camera, 2.0f).selectedTriangles, 1u);

        node.bounds.center += axis * 0.3f;
        EXPECT_EQ(selectLodGraphCut(graph, camera, 2.0f).culledTriangles, 1u);
        EXPECT_EQ(selectLodGraph(graph, camera, 2.0f).culledTriangles, 1u);
    }
}

TEST(ManyMesh, AssembleLodSelectionMatchesTheGreedyCut) {
    Mesh const mesh = makeGrid(20, 20, { 0.0f, 0.0f, 0.0f }, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 4;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 3.0f };
    camera.target = { 0.0f, 0.0f, 0.0f };
    LodGraphSelection const expected = selectLodGraph(graph, camera, 1.0f);

    std::vector<uint32_t> nodes = expected.nodes;
    std::sort(nodes.begin(), nodes.end());
    LodGraphSelection const assembled = assembleLodSelection(graph, camera, nodes);
    EXPECT_EQ(assembled.nodes.size(), expected.nodes.size());
    EXPECT_EQ(assembled.selectedTriangles, expected.selectedTriangles);
    EXPECT_EQ(assembled.indices, expected.indices);
    EXPECT_EQ(assembled.materialIds, expected.materialIds);
    EXPECT_EQ(assembled.submeshIds, expected.submeshIds);
}

TEST(ManyMesh, SelectionRespectsThePixelBudgetAndPrefersCoarserWhenFar) {
    // Two copies of the same sheet: one close to the camera, one far along the view axis.
    Mesh mesh = makeGrid(20, 20, { 0.0f, 0.0f, 0.0f }, 1.0f, 0.3f);
    Mesh const distant = makeGrid(20, 20, { 0.0f, 0.0f, -80.0f }, 1.0f, 0.3f);
    append(&mesh, distant);

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    SimplifyOptions options;
    options.levels = 5;
    options.lockBorder = true;
    std::vector<ClusterLods> const lods = simplifyClusters(mesh, clusters, options);

    ViewCamera camera;
    camera.eye = { 10.0f, 10.0f, 30.0f };
    camera.target = { 10.0f, 10.0f, 0.0f };
    camera.fovY = 1.0f;
    camera.screenHeight = 1080;
    float const thresholdPx = 1.0f;

    Selection const selection = selectClusters(clusters.clusters, lods, camera, thresholdPx);
    ASSERT_EQ(selection.levelPerCluster.size(), clusters.clusters.size());

    std::vector<size_t> nearClusters;
    std::vector<size_t> farClusters;
    for (size_t c = 0; c < clusters.clusters.size(); ++c) {
        if (clusters.clusters[c].bounds.center.z < -40.0f) {
            farClusters.push_back(c);
        } else {
            nearClusters.push_back(c);
        }
    }
    ASSERT_FALSE(nearClusters.empty());
    ASSERT_FALSE(farClusters.empty());

    for (size_t c = 0; c < selection.levelPerCluster.size(); ++c) {
        uint32_t const level = selection.levelPerCluster[c];
        if (level > 0) {
            // A cluster only leaves full detail when its error fits the pixel budget.
            EXPECT_LE(selection.screenErrorPerCluster[c], thresholdPx) << "cluster " << c;
        }
    }

    EXPECT_LE(selection.selectedTriangles, selection.baseTriangles);
    EXPECT_GT(meanLevel(selection.levelPerCluster, farClusters),
            meanLevel(selection.levelPerCluster, nearClusters));
}

TEST(ManyMesh, LockBorderKeepsClusterBoundaryVertices) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    SimplifyOptions options;
    options.levels = 4;
    options.ratio = 0.5f;
    options.lockBorder = true;

    std::vector<ClusterLods> const lods = simplifyClusters(mesh, clusters, options);

    size_t checked = 0;
    for (size_t c = 0; c < lods.size(); ++c) {
        if (lods[c].levels.size() < 2) {
            continue;
        }
        std::set<uint32_t> const border = borderVertices(clusters.clusters[c].indices);
        std::vector<uint32_t> const& simplified = lods[c].levels.back().indices;
        std::set<uint32_t> present(simplified.begin(), simplified.end());

        for (uint32_t vertex: border) {
            EXPECT_TRUE(present.count(vertex) > 0)
                    << "cluster " << c << " lost border vertex " << vertex;
        }
        checked += 1;
    }

    EXPECT_GT(checked, 0u);
}

TEST(ManyMesh, GroupingCoversEveryTriangleAndEnclosesItsMembers) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    uint32_t const groupSize = 4;
    GroupOptions groupOptions;
    groupOptions.clustersPerGroup = groupSize;
    ClusterSet const groups = groupClusters(clusters, groupOptions);

    // Grouping rebundles triangles, it neither adds nor drops any.
    EXPECT_EQ(trianglesOf(groups), trianglesOf(mesh));
    // Adjacency can force an extra partial group at the end of a connected patch, so the
    // contiguous-run lower bound is not an exact count anymore; it is still the minimum.
    EXPECT_GE(groups.clusters.size(), (clusters.clusters.size() + groupSize - 1) / groupSize);
    EXPECT_LE(groups.clusters.size(), clusters.clusters.size());

    // The merged sphere has to contain every vertex of the group, otherwise selection would
    // under estimate how close the unit comes to the camera.
    for (size_t g = 0; g < groups.clusters.size(); ++g) {
        Sphere const& group = groups.clusters[g].bounds;
        for (uint32_t index: groups.clusters[g].indices) {
            EXPECT_LE(length(mesh.positions[index] - group.center), group.radius + 1e-3f)
                    << "group " << g << " does not contain vertex " << index;
        }
    }
}

TEST(ManyMesh, GroupingDoesNotMergeDisconnectedCharts) {
    Mesh mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);
    append(&mesh, makeGrid(24, 24, { 1000.0f, 0.0f, 0.0f }, 1.0f, 0.4f));

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    GroupOptions groupOptions;
    groupOptions.clustersPerGroup = 64;
    ClusterSet const groups = groupClusters(clusters, groupOptions);

    ASSERT_GE(groups.clusters.size(), 2u)
            << "disconnected charts must not be merged into one simplification unit";

    for (Cluster const& group: groups.clusters) {
        bool first = false;
        bool second = false;
        for (uint32_t index: group.indices) {
            if (mesh.positions[index].x < 500.0f) {
                first = true;
            } else {
                second = true;
            }
        }
        EXPECT_FALSE(first && second);
    }
}

TEST(ManyMesh, GroupingTurnsMemberBordersIntoInteriorEdges) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.4f);

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    GroupOptions groupOptions;
    groupOptions.clustersPerGroup = 8;
    ClusterSet const groups = groupClusters(clusters, groupOptions);

    // The border lock is what makes independent simplification expensive: a locked vertex can
    // never be removed. Grouping is only worth it if it demonstrably unlocks vertices, by
    // turning the members' shared edges into edges interior to the group.
    size_t memberBorderTotal = 0;
    for (Cluster const& cluster: clusters.clusters) {
        memberBorderTotal += borderVertices(cluster.indices).size();
    }
    size_t groupBorderTotal = 0;
    for (Cluster const& group: groups.clusters) {
        groupBorderTotal += borderVertices(group.indices).size();
    }

    EXPECT_LT(groupBorderTotal, memberBorderTotal);
}

TEST(ManyMesh, GroupingLowersErrorAtAComparableReduction) {
    // A mesh large enough that clusters are genuinely small patches: on a tiny grid the
    // triangle budget, not the border lock, decides the outcome and grouping changes nothing.
    Mesh mesh;
    for (int tile = 0; tile < 4; ++tile) {
        Mesh const patch = makeGrid(40, 40,
                { float(tile % 2) * 60.0f, float(tile / 2) * 60.0f, float(tile) * 4.0f }, 1.0f,
                0.8f);
        append(&mesh, patch);
    }

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);

    SimplifyOptions options;
    options.levels = 4;
    options.ratio = 0.5f;
    options.lockBorder = true;

    std::vector<ClusterLods> const alone = simplifyClusters(mesh, clusters, options);

    GroupOptions groupOptions;
    groupOptions.clustersPerGroup = 16;
    ClusterSet const groups = groupClusters(clusters, groupOptions);
    std::vector<ClusterLods> const grouped = simplifyClusters(mesh, groups, options);

    // Triangle-weighted mean, which is far more stable than the worst single unit.
    auto meanErrorAtLevel = [](std::vector<ClusterLods> const& lods, size_t level) {
        double weighted = 0.0;
        uint64_t triangles = 0;
        for (ClusterLods const& unit: lods) {
            if (level < unit.levels.size()) {
                uint64_t const count = unit.levels[level].triangleCount();
                weighted += double(unit.levels[level].worldError) * double(count);
                triangles += count;
            }
        }
        return triangles > 0 ? weighted / double(triangles) : 0.0;
    };

    // Compare at the coarsest level that *every* unit in both configurations reached. Using
    // the coarsest level of any single unit would silently drop the units that the quality
    // gate stopped early, and those are exactly the hard ones, which makes the mean
    // optimistic for whichever configuration stopped more units.
    auto commonLevel = [](std::vector<ClusterLods> const& lods) {
        size_t level = 0;
        for (ClusterLods const& unit: lods) {
            level = level == 0 ? unit.levels.size() : std::min(level, unit.levels.size());
        }
        return level;
    };
    size_t const level = std::min(commonLevel(alone), commonLevel(grouped)) - 1;
    ASSERT_GE(level, 1u);

    auto totalTrianglesAtLevel = [level](std::vector<ClusterLods> const& lods) {
        uint64_t triangles = 0;
        for (ClusterLods const& unit: lods) {
            triangles += unit.levels[level].triangleCount();
        }
        return triangles;
    };
    // A fair comparison also needs the same amount of reduction, not just the same level
    // index: the quality gate may have shortened some chains. Allow a few percent of slack.
    uint64_t const aloneTriangles = totalTrianglesAtLevel(alone);
    uint64_t const groupedTriangles = totalTrianglesAtLevel(grouped);
    double const ratio = double(groupedTriangles) / double(aloneTriangles);
    EXPECT_GT(ratio, 0.90) << "grouped=" << groupedTriangles << " alone=" << aloneTriangles;
    EXPECT_LT(ratio, 1.10) << "grouped=" << groupedTriangles << " alone=" << aloneTriangles;

    EXPECT_LT(meanErrorAtLevel(grouped, level), meanErrorAtLevel(alone, level));
}

TEST(ManyMesh, TopologyMetricsFindDuplicatesDegeneratesAndNonManifoldEdges) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 1.0f, 1.0f, 0.0f },
    };
    mesh.indices = {
        0, 1, 2, 0, 1, 2, // duplicate
        0, 0, 3,          // degenerate
        1, 2, 3, 1, 2, 3, // duplicate that also makes edge 1-2 non-manifold
    };
    TopologyStats const stats = measureTopology(mesh, mesh.indices);
    EXPECT_EQ(stats.triangles, 5u);
    EXPECT_EQ(stats.duplicateTriangles, 2u);
    EXPECT_EQ(stats.degenerateTriangles, 1u);
    EXPECT_GE(stats.nonManifoldEdges, 1u);
}

TEST(ManyMesh, TopologyMetricsCountFlippedTriangles) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
    };
    mesh.normals.assign(3, { 0.0f, 0.0f, 1.0f });
    mesh.indices = { 0, 2, 1 };
    TopologyStats const flipped = measureTopology(mesh, mesh.indices);
    EXPECT_EQ(flipped.flippedTriangles, 1u);

    mesh.indices = { 0, 1, 2 };
    TopologyStats const upright = measureTopology(mesh, mesh.indices);
    EXPECT_EQ(upright.flippedTriangles, 0u);
}

TEST(ManyMesh, PositionAndAttributeMetricsSeeRemovedDetail) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 1.0f, 1.0f, 0.0f },
    };
    mesh.normals = {
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, -1.0f },
    };
    mesh.uvs = {
        { 0.0f, 0.0f },
        { 1.0f, 0.0f },
        { 0.0f, 1.0f },
        { 0.8f, 0.2f },
    };
    mesh.indices = { 0, 1, 2, 1, 3, 2 };

    std::vector<uint32_t> const simplified = { 0, 1, 2 };
    PositionStats const position = measurePositionError(mesh, mesh.indices, simplified);
    EXPECT_GT(position.maxError, 0.0f);
    EXPECT_GT(position.meanError, 0.0f);

    AttributeStats const attributes = measureAttributeError(mesh, mesh.indices, simplified);
    EXPECT_GT(attributes.maxNormalErrorRadians, 0.0f);
    EXPECT_GT(attributes.maxUvError, 0.0f);
}

TEST(ManyMesh, AttributeMetricsSelectTheSourceChartAtADuplicatePosition) {
    // Two charts share the origin but carry different normals and UVs. The position error is
    // zero for both origin copies; the attribute comparison must pick each copy's own chart
    // instead of whichever coincident triangle the BVH happened to visit first.
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 0.0f, 0.0f },
        { -1.0f, 0.0f, 0.0f },
        { 0.0f, -1.0f, 0.0f },
    };
    mesh.normals = {
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
    };
    mesh.uvs = {
        { 0.1f, 0.1f },
        { 0.2f, 0.1f },
        { 0.1f, 0.2f },
        { 0.9f, 0.9f },
        { 0.8f, 0.9f },
        { 0.9f, 0.8f },
    };
    mesh.indices = { 0, 1, 2, 3, 4, 5 };

    AttributeStats const attributes = measureAttributeError(mesh, mesh.indices, mesh.indices);
    EXPECT_EQ(attributes.samples, 6u);
    EXPECT_NEAR(attributes.maxNormalErrorRadians, 0.0f, 1.0e-4f);
    EXPECT_NEAR(attributes.maxUvError, 0.0f, 1.0e-4f);
}

TEST(ManyMesh, AttributeQemKeepsTopologyCleanAndRespectsTheTarget) {
    Mesh mesh = makeGrid(12, 12, {}, 1.0f, 0.6f);
    mesh.normals.assign(mesh.positions.size(), { 0.0f, 0.0f, 1.0f });
    mesh.uvs.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.uvs[i] = { mesh.positions[i].x * 0.1f, mesh.positions[i].y * 0.1f };
    }
    // One vertex whose normal is deliberately wrong: removing it must cost more than removing
    // a vertex on the smooth part of the surface.
    mesh.normals[12 * 13 / 2] = { 0.0f, 0.0f, -1.0f };

    AttributeSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = false;
    options.maxNormalErrorDegrees = 20.0f;
    options.minTriangleQuality = 0.02f;
    std::vector<uint32_t> simplified;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithAttributes(mesh, mesh.indices, options, &simplified, &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());
    EXPECT_GE(worldError, 0.0f);

    TopologyStats const stats = measureTopology(mesh, simplified);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
}

TEST(ManyMesh, QualityGatePreservesTheExactBoundaryEdgeSet) {
    Mesh mesh = makeGrid(12, 12, {}, 1.0f, 0.6f);
    mesh.normals.assign(mesh.positions.size(), { 0.0f, 0.0f, 1.0f });
    mesh.uvs.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.uvs[i] = { mesh.positions[i].x * 0.1f, mesh.positions[i].y * 0.1f };
    }

    SimplifyOptions options;
    options.qualityGate = true;
    options.attributeQem = true;
    options.lockBorder = true;
    LodLevel level;
    simplifyIndices(mesh, mesh.indices, (mesh.indices.size() / 2 / 3) * 3, options, &level);
    ASSERT_TRUE(level.simplified);
    EXPECT_LT(level.indices.size(), mesh.indices.size());
    EXPECT_EQ(boundaryEdgeSet(level.indices), boundaryEdgeSet(mesh.indices));
    EXPECT_EQ(level.topology.flippedTriangles, 0u);
}

TEST(ManyMesh, CachedExtendedMeshDoesNotChangeSimplifiedOutput) {
    Mesh mesh = makeGrid(20, 20, {}, 1.0f, 0.45f);
    mesh.normals.assign(mesh.positions.size(), { 0.0f, 0.0f, 1.0f });
    mesh.uvs.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.uvs[i] = { mesh.positions[i].x * 0.05f, mesh.positions[i].y * 0.05f };
    }

    SimplifyOptions options;
    options.qualityGate = true;
    options.attributeQem = true;
    options.cornerSimplify = true;
    options.meshCacheEpoch = 0xC0FFEEu;
    size_t const target = (mesh.indices.size() / 2 / 3) * 3;

    LodLevel first;
    LodLevel reused;
    simplifyIndices(mesh, mesh.indices, target, options, &first);
    simplifyIndices(mesh, mesh.indices, target, options, &reused);

    options.meshCacheEpoch = 0;
    LodLevel uncached;
    simplifyIndices(mesh, mesh.indices, target, options, &uncached);

    ASSERT_TRUE(first.simplified);
    EXPECT_EQ(first.indices, reused.indices);
    EXPECT_EQ(first.indices, uncached.indices);
    EXPECT_EQ(first.generatedVertices, reused.generatedVertices);
    EXPECT_EQ(first.generatedVertices, uncached.generatedVertices);
    EXPECT_FLOAT_EQ(first.worldError, uncached.worldError);
}

TEST(ManyMesh, SeamPairCollapseKeepsTheWeldedSurfaceClosed) {
    // Two 16x8 grids meet at x=16. The importer duplicates the seam column because the UVs
    // jump from u=1 to u=0 there. Per-index topology therefore has a 17-edge boundary down the
    // middle even though the welded surface is one open rectangle.
    Mesh mesh;
    auto appendGrid = [&mesh](uint32_t offsetX, float uOffset) {
        uint32_t const nx = 16;
        uint32_t const ny = 8;
        uint32_t const base = uint32_t(mesh.positions.size());
        for (uint32_t j = 0; j <= ny; ++j) {
            for (uint32_t i = 0; i <= nx; ++i) {
                float const x = float(offsetX + i);
                float const y = float(j);
                mesh.positions.push_back({ x, y, 0.18f * std::sin(x * 0.7f) * std::cos(y * 0.9f) });
                mesh.uvs.push_back({ float(i) / float(nx) + uOffset, float(j) / float(ny) });
            }
        }
        auto index = [base, nx](uint32_t i, uint32_t j) { return base + j * (nx + 1) + i; };
        for (uint32_t j = 0; j < ny; ++j) {
            for (uint32_t i = 0; i < nx; ++i) {
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j), index(i + 1, j + 1) });
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j + 1), index(i, j + 1) });
            }
        }
    };
    appendGrid(0, 0.0f);
    appendGrid(16, 0.0f);

    std::set<WeldedEdge> const baseBoundary = weldedBoundarySet(mesh, mesh.indices);
    ASSERT_FALSE(baseBoundary.empty());

    AttributeSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = true;
    options.seamCollapse = true;
    std::vector<uint32_t> simplified;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithAttributes(mesh, mesh.indices, options, &simplified, &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());
    EXPECT_EQ(weldedBoundarySet(mesh, simplified), baseBoundary);
    TopologyStats const stats = measureTopology(mesh, simplified);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
}

TEST(ManyMesh, MaterialAndSubmeshIdsSurviveClusteringAndLods) {
    Mesh mesh = makeGrid(12, 12, {}, 1.0f, 0.3f);
    Mesh const second = makeGrid(12, 12, { 100.0f, 0.0f, 0.0f }, 1.0f, 0.3f);
    uint32_t const firstTriangles = uint32_t(mesh.triangleCount());
    append(&mesh, second);
    mesh.materialIds.assign(mesh.triangleCount(), 0);
    mesh.submeshIds.assign(mesh.triangleCount(), 0);
    for (size_t t = firstTriangles; t < mesh.triangleCount(); ++t) {
        mesh.materialIds[t] = 3;
        mesh.submeshIds[t] = 7;
    }

    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = 64;
    clusterizeOptions.maxTriangles = 64;
    ClusterSet const clusters = clusterize(mesh, clusterizeOptions);
    for (Cluster const& cluster: clusters.clusters) {
        for (size_t t = 0; t < cluster.triangleCount(); ++t) {
            EXPECT_TRUE(cluster.materialId == 0 || cluster.materialId == 3);
            EXPECT_TRUE(cluster.submeshId == 0 || cluster.submeshId == 7);
        }
    }

    SimplifyOptions options;
    options.levels = 3;
    options.ratio = 0.6f;
    std::vector<ClusterLods> const lods = simplifyClusters(mesh, clusters, options);
    for (size_t c = 0; c < clusters.clusters.size(); ++c) {
        for (LodLevel const& level: lods[c].levels) {
            EXPECT_EQ(level.materialId, clusters.clusters[c].materialId);
            EXPECT_EQ(level.submeshId, clusters.clusters[c].submeshId);
        }
    }

    std::vector<LodLevel> const chain = simplifyChain(mesh, options);
    ASSERT_FALSE(chain.empty());
    for (LodLevel const& level: chain) {
        EXPECT_EQ(level.materialIds.size(), level.triangleCount());
        EXPECT_EQ(level.submeshIds.size(), level.triangleCount());
    }
}

TEST(ManyMesh, LodGraphCoversLeavesAndSelectsANonOverlappingCut) {
    Mesh const mesh = makeGrid(32, 32, {}, 1.0f, 0.5f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.qualityGate = true;

    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.nodes.empty());
    ASSERT_FALSE(graph.leaves.empty());
    EXPECT_EQ(graph.baseTriangles, mesh.triangleCount());

    // Every node must be reachable from a root. A singleton group is easy to mis-index during
    // hierarchy construction, which leaves orphan nodes and silently makes them unselectable.
    std::set<uint32_t> reachable;
    std::vector<uint32_t> stack = graph.roots;
    while (!stack.empty()) {
        uint32_t const node = stack.back();
        stack.pop_back();
        ASSERT_LT(node, graph.nodes.size());
        EXPECT_TRUE(reachable.insert(node).second) << "node " << node << " is reachable twice";
        for (uint32_t child: graph.nodes[node].children) {
            stack.push_back(child);
        }
    }
    EXPECT_EQ(reachable.size(), graph.nodes.size());
    for (uint32_t node = 0; node < graph.nodes.size(); ++node) {
        uint32_t const parent = graph.nodes[node].parent;
        if (parent == UINT32_MAX) {
            EXPECT_NE(std::find(graph.roots.begin(), graph.roots.end(), node), graph.roots.end());
        } else {
            ASSERT_LT(parent, graph.nodes.size());
            auto const& children = graph.nodes[parent].children;
            EXPECT_NE(std::find(children.begin(), children.end(), node), children.end());
        }
    }

    std::vector<Triangle> leafTriangles;
    for (uint32_t leaf: graph.leaves) {
        for (size_t i = 0; i + 2 < graph.nodes[leaf].indices.size(); i += 3) {
            Triangle triangle = { graph.nodes[leaf].indices[i], graph.nodes[leaf].indices[i + 1],
                graph.nodes[leaf].indices[i + 2] };
            std::sort(triangle.begin(), triangle.end());
            leafTriangles.push_back(triangle);
        }
    }
    std::sort(leafTriangles.begin(), leafTriangles.end());
    EXPECT_EQ(leafTriangles, trianglesOf(mesh));

    ViewCamera camera;
    camera.eye = { 16.0f, 16.0f, 80.0f };
    camera.target = { 16.0f, 16.0f, 0.0f };
    camera.screenHeight = 720;
    camera.screenWidth = 1280;
    camera.near = 0.1f;
    camera.far = 1000.0f;

    LodGraphSelection const selection = selectLodGraphTier(graph, camera, LodTier::Balanced);
    EXPECT_FALSE(selection.nodes.empty());
    EXPECT_EQ(selection.indices.size(), selection.selectedTriangles * 3);
    EXPECT_EQ(selection.materialIds.size(), selection.selectedTriangles);
    EXPECT_EQ(selection.submeshIds.size(), selection.selectedTriangles);
    EXPECT_LE(selection.selectedTriangles, graph.baseTriangles);

    // A selected parent must never coexist with one of its children or grandchildren.
    std::set<uint32_t> selected(selection.nodes.begin(), selection.nodes.end());
    for (uint32_t node: selection.nodes) {
        uint32_t parent = graph.nodes[node].parent;
        while (parent != UINT32_MAX) {
            EXPECT_EQ(selected.count(parent), 0u);
            parent = graph.nodes[parent].parent;
        }
    }
}

TEST(ManyMesh, LodGraphBuildIsDeterministicAcrossSerialAndParallelWork) {
    Mesh mesh = makeGrid(32, 32, {}, 1.0f, 0.5f);
    mesh.normals.assign(mesh.positions.size(), { 0.0f, 0.0f, 1.0f });
    mesh.uvs.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.uvs[i] = { mesh.positions[i].x * 0.05f, mesh.positions[i].y * 0.05f };
    }

    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.qualityGate = true;
    options.simplify.attributeQem = true;

    auto setBuildThreads = [](char const* value) {
#if defined(_WIN32)
        _putenv_s("MANYMESH_BUILD_THREADS", value);
#else
        if (value[0] == '\0') {
            unsetenv("MANYMESH_BUILD_THREADS");
        } else {
            setenv("MANYMESH_BUILD_THREADS", value, 1);
        }
#endif
    };
    auto expectSameGraph = [](LodGraph const& a, LodGraph const& b) {
        EXPECT_EQ(a.nodes.size(), b.nodes.size());
        if (a.nodes.size() != b.nodes.size()) {
            return;
        }
        EXPECT_EQ(a.roots, b.roots);
        EXPECT_EQ(a.leaves, b.leaves);
        EXPECT_EQ(a.vertexCount, b.vertexCount);
        EXPECT_EQ(a.levelCount, b.levelCount);
        EXPECT_EQ(a.baseTriangles, b.baseTriangles);
        for (size_t i = 0; i < a.nodes.size(); ++i) {
            LodGraphNode const& left = a.nodes[i];
            LodGraphNode const& right = b.nodes[i];
            EXPECT_EQ(left.level, right.level) << "node " << i;
            EXPECT_EQ(left.parent, right.parent) << "node " << i;
            EXPECT_EQ(left.children, right.children) << "node " << i;
            EXPECT_EQ(left.indices, right.indices) << "node " << i;
            EXPECT_EQ(left.materialId, right.materialId) << "node " << i;
            EXPECT_EQ(left.submeshId, right.submeshId) << "node " << i;
            EXPECT_EQ(left.selfError, right.selfError) << "node " << i;
            EXPECT_EQ(left.accumulatedError, right.accumulatedError) << "node " << i;
            EXPECT_EQ(left.topology.boundaryEdges, right.topology.boundaryEdges) << "node " << i;
            EXPECT_EQ(left.topology.nonManifoldEdges, right.topology.nonManifoldEdges)
                    << "node " << i;
            EXPECT_EQ(left.topology.duplicateTriangles, right.topology.duplicateTriangles)
                    << "node " << i;
            EXPECT_EQ(left.topology.flippedTriangles, right.topology.flippedTriangles)
                    << "node " << i;
            EXPECT_EQ(left.attributes.maxNormalErrorRadians, right.attributes.maxNormalErrorRadians)
                    << "node " << i;
            EXPECT_EQ(left.attributes.maxUvError, right.attributes.maxUvError) << "node " << i;
            EXPECT_EQ(left.simplified, right.simplified) << "node " << i;
            EXPECT_EQ(left.baseTriangles, right.baseTriangles) << "node " << i;
        }
    };

    // Cluster chains and independent groups are simplified on worker threads. Pin one run to a
    // single worker, then compare two parallel runs against it field by field. This catches both
    // lost updates between jobs and any worker-count-dependent tie breaking.
    setBuildThreads("1");
    LodGraph const serial = buildLodGraph(mesh, options);
    setBuildThreads("0");
    LodGraph const parallel = buildLodGraph(mesh, options);
    LodGraph const parallelAgain = buildLodGraph(mesh, options);
    expectSameGraph(serial, parallel);
    expectSameGraph(parallel, parallelAgain);
}

TEST(ManyMesh, LodGraphRatioSelectionHitsTheRequestedBudget) {
    Mesh const mesh = makeGrid(32, 32, {}, 1.0f, 0.5f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    options.ratio = 0.5f;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 16.0f, 16.0f, 80.0f };
    camera.target = { 16.0f, 16.0f, 0.0f };
    camera.screenHeight = 720;
    camera.screenWidth = 1280;
    camera.near = 0.1f;
    camera.far = 1000.0f;

    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 0.5f, 1000.0f);
    double const ratio = graph.baseTriangles > selection.culledTriangles
                                 ? double(selection.selectedTriangles) /
                                           double(graph.baseTriangles - selection.culledTriangles)
                                 : 1.0;
    // The cut is discrete, so it can miss the exact ratio, but it must be a genuine saving and
    // must not overshoot the request by more than one hierarchy step.
    EXPECT_LT(ratio, 0.9);
    EXPECT_LE(ratio, 0.75);
}

TEST(ManyMesh, DistanceAwareSelectionKeepsNearGeometryDetailed) {
    Mesh const mesh = makeGrid(32, 32, {}, 1.0f, 0.5f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    options.ratio = 0.5f;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera nearCamera;
    nearCamera.eye = { 16.0f, 16.0f, 30.0f };
    nearCamera.target = { 16.0f, 16.0f, 0.0f };
    nearCamera.screenHeight = 720;
    nearCamera.screenWidth = 1280;
    nearCamera.near = 0.1f;
    nearCamera.far = 1000.0f;

    ViewCamera farCamera = nearCamera;
    farCamera.eye = { 16.0f, 16.0f, 300.0f };

    LodGraphSelection const nearSelection = selectLodGraph(graph, nearCamera, 1.5f);
    LodGraphSelection const farSelection = selectLodGraph(graph, farCamera, 1.5f);
    LodGraphCut const nearCut = selectLodGraphCut(graph, nearCamera, 1.5f);
    EXPECT_GT(nearSelection.selectedTriangles, 0u);
    EXPECT_GT(farSelection.selectedTriangles, 0u);
    EXPECT_GE(nearSelection.selectedTriangles, farSelection.selectedTriangles);
    EXPECT_EQ(nearCut.nodes, nearSelection.nodes);
    EXPECT_EQ(nearCut.selectedTriangles, nearSelection.selectedTriangles);
    EXPECT_EQ(nearCut.culledTriangles, nearSelection.culledTriangles);
    EXPECT_LE(nearSelection.selectedTriangles, graph.baseTriangles);
    EXPECT_LE(farSelection.selectedTriangles, graph.baseTriangles);
}

TEST(ManyMesh, AggressiveDagCutKeepsTopologyClean) {
    Mesh mesh = makeGrid(32, 32, {}, 1.0f, 0.5f);
    mesh.normals.assign(mesh.positions.size(), { 0.0f, 0.0f, 1.0f });
    mesh.uvs.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.uvs[i] = { mesh.positions[i].x * 0.05f, mesh.positions[i].y * 0.05f };
    }

    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.qualityGate = true;
    options.simplify.attributeQem = true;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 16.0f, 16.0f, 80.0f };
    camera.target = { 16.0f, 16.0f, 0.0f };
    camera.screenHeight = 720;
    camera.screenWidth = 1280;
    camera.near = 0.1f;
    camera.far = 1000.0f;

    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 0.25f, 1000.0f);
    TopologyStats const base = measureTopology(mesh, mesh.indices);
    TopologyStats const cut = measureTopology(mesh, selection.indices);
    EXPECT_EQ(cut.duplicateTriangles, 0u);
    EXPECT_EQ(cut.degenerateTriangles, 0u);
    EXPECT_EQ(cut.nonManifoldEdges, 0u);
    EXPECT_EQ(cut.flippedTriangles, 0u);
    EXPECT_LE(cut.boundaryEdges, base.boundaryEdges);
}

TEST(ManyMesh, LodGraphCutRemovesOnlyCrossNodeDuplicateFaces) {
    // Two independently simplified nodes share vertices 0, 1 and 2, and both generated the
    // same face from them. The dedup pass must drop one copy while keeping both unique faces.
    LodGraph graph;
    graph.vertexCount = 5;
    graph.levelCount = 1;
    graph.baseTriangles = 4;

    LodGraphNode first;
    first.level = 0;
    first.indices = { 0, 1, 2, 0, 2, 3 };
    first.bounds.center = { 0.0f, 0.0f, 0.0f };
    first.bounds.radius = 10.0f;
    first.materialId = 7;
    first.submeshId = 1;
    first.baseTriangles = 2;

    LodGraphNode second;
    second.level = 0;
    second.indices = { 0, 1, 2, 1, 2, 4 };
    second.bounds = first.bounds;
    second.materialId = 7;
    second.submeshId = 1;
    second.baseTriangles = 2;

    graph.nodes = { first, second };
    graph.roots = { 0, 1 };
    graph.leaves = { 0, 1 };

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 5.0f };
    camera.target = { 0.0f, 0.0f, 0.0f };
    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 1.0f, 1000.0f);

    EXPECT_EQ(selection.nodes.size(), 2u);
    ASSERT_EQ(selection.indices.size(), 9u);
    EXPECT_EQ(selection.selectedTriangles, 3u);
    EXPECT_EQ(selection.materialIds.size(), 3u);
    EXPECT_EQ(selection.submeshIds.size(), 3u);

    std::vector<Triangle> triangles;
    for (size_t i = 0; i + 2 < selection.indices.size(); i += 3) {
        Triangle triangle = { selection.indices[i], selection.indices[i + 1],
            selection.indices[i + 2] };
        std::sort(triangle.begin(), triangle.end());
        triangles.push_back(triangle);
    }
    std::sort(triangles.begin(), triangles.end());
    std::vector<Triangle> const expected = {
        { 0, 1, 2 },
        { 0, 2, 3 },
        { 1, 2, 4 },
    };
    EXPECT_EQ(triangles, expected);

    // The distance-aware entry point must share the same cut cleanup. Before this regression
    // test it traversed the DAG in a separate function and emitted both copies of (0, 1, 2).
    LodGraphSelection const distanceSelection = selectLodGraph(graph, camera, 1000.0f);
    EXPECT_EQ(distanceSelection.nodes, selection.nodes);
    EXPECT_EQ(distanceSelection.selectedTriangles, selection.selectedTriangles);
    EXPECT_EQ(distanceSelection.indices.size(), 9u);
}

TEST(ManyMesh, LodGraphSerializesAndStreamsByPage) {
    Mesh const mesh = makeGrid(20, 20, {}, 1.0f, 0.4f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(blob, &restored));
    ASSERT_EQ(restored.nodes.size(), graph.nodes.size());
    EXPECT_EQ(restored.roots, graph.roots);
    EXPECT_EQ(restored.leaves, graph.leaves);
    EXPECT_EQ(restored.baseTriangles, graph.baseTriangles);
    EXPECT_EQ(restored.vertexCount, graph.vertexCount);
    for (size_t i = 0; i < graph.nodes.size(); ++i) {
        EXPECT_EQ(restored.nodes[i].children, graph.nodes[i].children);
        EXPECT_EQ(restored.nodes[i].indices, graph.nodes[i].indices);
        EXPECT_FLOAT_EQ(restored.nodes[i].accumulatedError, graph.nodes[i].accumulatedError);
        EXPECT_EQ(restored.nodes[i].topology.boundaryEdges, graph.nodes[i].topology.boundaryEdges);
        EXPECT_EQ(restored.nodes[i].topology.nonManifoldEdges,
                graph.nodes[i].topology.nonManifoldEdges);
        EXPECT_EQ(restored.nodes[i].topology.flippedTriangles,
                graph.nodes[i].topology.flippedTriangles);
        EXPECT_FLOAT_EQ(restored.nodes[i].topology.minTriangleQuality,
                graph.nodes[i].topology.minTriangleQuality);
        EXPECT_FLOAT_EQ(restored.nodes[i].attributes.maxNormalErrorRadians,
                graph.nodes[i].attributes.maxNormalErrorRadians);
        EXPECT_FLOAT_EQ(restored.nodes[i].attributes.maxUvError,
                graph.nodes[i].attributes.maxUvError);
        EXPECT_EQ(restored.nodes[i].attributes.samples, graph.nodes[i].attributes.samples);
    }

    StreamingLodGraph streaming(blob);
    ASSERT_TRUE(streaming.valid());
    EXPECT_EQ(streaming.nodeCount(), graph.nodes.size());
    EXPECT_EQ(streaming.vertexCount(), graph.vertexCount);
    std::vector<LodStreamingPage> const pages = streaming.planPages(512);
    ASSERT_FALSE(pages.empty());
    for (LodStreamingPage const& page: pages) {
        // A page never splits one node, so an oversized single node is its own page.
        EXPECT_TRUE(page.byteCount <= 512u || page.nodeCount == 1);
    }

    ViewCamera camera;
    camera.eye = { 10.0f, 10.0f, 60.0f };
    camera.target = { 10.0f, 10.0f, 0.0f };
    camera.screenHeight = 180;
    camera.screenWidth = 320;
    LodGraphSelection const selection = selectLodGraph(graph, camera, 1.5f);

    LodStreamingCache cache(&streaming, 2048, 512);
    ASSERT_TRUE(cache.prepare(selection));
    for (uint32_t node: selection.nodes) {
        LodGraphNode const* loaded = cache.find(node);
        ASSERT_NE(loaded, nullptr) << "node " << node << " was not resident";
        EXPECT_EQ(loaded->indices, graph.nodes[node].indices);
    }
}

TEST(ManyMesh, LodGraphStreamsFromAFileWithoutLoadingTheBlob) {
    Mesh const mesh = makeGrid(20, 20, {}, 1.0f, 0.4f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    std::filesystem::path const path =
            std::filesystem::temp_directory_path() / "manymesh_lod_graph_test.mmb";
    ASSERT_TRUE(writeLodGraphFile(graph, path.string().c_str()));
    {
        StreamingLodGraph streaming(path.string());
        ASSERT_TRUE(streaming.valid());
        EXPECT_TRUE(streaming.fileBacked());
        EXPECT_GT(streaming.byteSize(), 0u);
        EXPECT_EQ(streaming.nodeCount(), graph.nodes.size());
        for (uint32_t i = 0; i < streaming.nodeCount(); ++i) {
            LodGraphNode node;
            ASSERT_TRUE(streaming.readNode(i, &node));
            EXPECT_EQ(node.indices, graph.nodes[i].indices);
            EXPECT_EQ(node.children, graph.nodes[i].children);
            EXPECT_EQ(node.materialId, graph.nodes[i].materialId);
            EXPECT_EQ(node.submeshId, graph.nodes[i].submeshId);
            EXPECT_EQ(node.topology.boundaryEdges, graph.nodes[i].topology.boundaryEdges);
            EXPECT_EQ(node.topology.flippedTriangles, graph.nodes[i].topology.flippedTriangles);
            EXPECT_FLOAT_EQ(node.attributes.maxNormalErrorRadians,
                    graph.nodes[i].attributes.maxNormalErrorRadians);
        }

        // A page read has to parse records from the range it fetched rather than depending on
        // the full graph being resident.
        std::vector<LodStreamingPage> const pages = streaming.planPages(512);
        ASSERT_FALSE(pages.empty());
        std::vector<LodGraphNode> nodes;
        ASSERT_TRUE(streaming.readPage(pages.front(), &nodes));
        ASSERT_EQ(nodes.size(), pages.front().nodeCount);
        EXPECT_EQ(nodes.front().indices, graph.nodes[pages.front().firstNode].indices);
    }
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
}

TEST(ManyMesh, LodGraphReadsVersionTwoWithoutAStoredVertexCount) {
    Mesh const mesh = makeGrid(12, 12, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 3;
    LodGraph const graph = buildLodGraph(mesh, options);
    std::vector<uint8_t> const blob = serializeLodGraph(graph);

    uint32_t nodeCount = 0;
    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    std::memcpy(&nodeCount, blob.data() + 8, sizeof(nodeCount));
    std::memcpy(&rootCount, blob.data() + 12, sizeof(rootCount));
    std::memcpy(&leafCount, blob.data() + 16, sizeof(leafCount));

    // Version 6 is [header with vertexCount][roots][leaves][generated count][generated
    // vertices][position id count][position ids][offsets][records]. Version 2 has the same fixed
    // header without the vertex count and neither of the trailing vertex sections, so drop them
    // and shift every record offset back by the removed bytes.
    constexpr size_t V2_HEADER_SIZE = 32;
    constexpr size_t V6_HEADER_SIZE = 36;
    size_t const generatedCountOffset =
            V6_HEADER_SIZE + (size_t(rootCount) + leafCount) * sizeof(uint32_t);
    ASSERT_LE(generatedCountOffset + sizeof(uint32_t), blob.size());
    uint32_t generatedCount = 0;
    std::memcpy(&generatedCount, blob.data() + generatedCountOffset, sizeof(generatedCount));
    size_t const generatedEnd = generatedCountOffset + sizeof(uint32_t) +
                                size_t(generatedCount) * 10u * sizeof(uint32_t);
    ASSERT_LE(generatedEnd + sizeof(uint32_t), blob.size());
    uint32_t positionIdCount = 0;
    std::memcpy(&positionIdCount, blob.data() + generatedEnd, sizeof(positionIdCount));
    size_t const positionIdsEnd =
            generatedEnd + sizeof(uint32_t) + size_t(positionIdCount) * sizeof(uint32_t);
    ASSERT_LE(positionIdsEnd, blob.size());
    size_t const removedBytes =
            (V6_HEADER_SIZE - V2_HEADER_SIZE) + (positionIdsEnd - generatedCountOffset);
    std::vector<uint8_t> v2;
    v2.insert(v2.end(), blob.begin(), blob.begin() + V2_HEADER_SIZE);
    v2.insert(v2.end(), blob.begin() + V6_HEADER_SIZE,
            blob.begin() + std::ptrdiff_t(generatedCountOffset));
    v2.insert(v2.end(), blob.begin() + std::ptrdiff_t(positionIdsEnd), blob.end());
    uint32_t const version = 2;
    std::memcpy(v2.data() + 4, &version, sizeof(version));

    size_t const offsets = V2_HEADER_SIZE + (size_t(rootCount) + leafCount) * sizeof(uint32_t);
    for (uint32_t i = 0; i <= nodeCount; ++i) {
        uint64_t value = 0;
        std::memcpy(&value, v2.data() + offsets + size_t(i) * sizeof(value), sizeof(value));
        value -= removedBytes;
        std::memcpy(v2.data() + offsets + size_t(i) * sizeof(value), &value, sizeof(value));
    }

    StreamingLodGraph const streaming(v2);
    ASSERT_TRUE(streaming.valid());
    EXPECT_EQ(streaming.vertexCount(), 0u);
    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(v2, &restored));
    EXPECT_EQ(restored.vertexCount, graph.vertexCount);
}

TEST(ManyMesh, AsyncStreamingCachePrefetchesPagesOffTheCallingThread) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 12.0f, 12.0f, 60.0f };
    camera.target = { 12.0f, 12.0f, 0.0f };
    camera.screenHeight = 180;
    camera.screenWidth = 320;
    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 0.5f, 1000.0f);
    ASSERT_FALSE(selection.nodes.empty());

    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    StreamingLodGraph stream(blob);
    ASSERT_TRUE(stream.valid());

    std::atomic<uint32_t> fetches{ 0 };
    AsyncLodStreamingCache cache(
            &stream,
            [&](LodStreamingPage const& page, std::vector<LodGraphNode>* nodes) {
                fetches.fetch_add(1);
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
                return stream.readPage(page, nodes);
            },
            4u * 1024u * 1024u, 4096, 3);

    EXPECT_TRUE(cache.request(selection));
    auto const deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!cache.ready() && std::chrono::steady_clock::now() < deadline) {
        cache.poll();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    cache.poll();

    EXPECT_TRUE(cache.ready());
    EXPECT_GT(fetches.load(), 0u);
    EXPECT_EQ(cache.stats().pageMisses, uint64_t(fetches.load()));
    for (uint32_t nodeId: selection.nodes) {
        EXPECT_NE(cache.find(nodeId), nullptr) << "node " << nodeId << " was not prefetched";
    }
}

TEST(ManyMesh, AsyncStreamingCacheAcceptsRawByteRangesAndCuts) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 12.0f, 12.0f, 60.0f };
    camera.target = { 12.0f, 12.0f, 0.0f };
    camera.screenHeight = 180;
    camera.screenWidth = 320;
    LodGraphCut const cut = selectLodGraphCut(graph, camera, 1000.0f);
    ASSERT_FALSE(cut.nodes.empty());

    StreamingLodGraph stream(serializeLodGraph(graph));
    ASSERT_TRUE(stream.valid());
    std::atomic<uint32_t> fetches{ 0 };
    AsyncLodStreamingCache cache(
            &stream,
            [&](uint64_t offset, size_t size, std::vector<uint8_t>* bytes) {
                fetches.fetch_add(1);
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                return stream.readBytes(offset, size, bytes);
            },
            4u * 1024u * 1024u, 4096, 2);

    EXPECT_TRUE(cache.request(cut));
    auto const deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!cache.ready() && std::chrono::steady_clock::now() < deadline) {
        cache.poll();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    cache.poll();

    EXPECT_TRUE(cache.ready());
    EXPECT_GT(fetches.load(), 0u);
    EXPECT_EQ(cache.stats().failedFetches, 0u);
    EXPECT_GT(cache.stats().bytesFetched, 0u);
    for (uint32_t nodeId: cut.nodes) {
        EXPECT_NE(cache.find(nodeId), nullptr) << "node " << nodeId << " was not prefetched";
    }
}

TEST(ManyMesh, AsyncStreamingCacheDropsPagesQueuedForAnOlderCut) {
    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 12.0f, 12.0f, 60.0f };
    camera.target = { 12.0f, 12.0f, 0.0f };
    camera.screenHeight = 180;
    camera.screenWidth = 320;

    // A zero pixel ceiling keeps the finest legal nodes, so `wide` touches many pages. The
    // half-budget cut is much coarser and its page set is mostly disjoint from the leaves.
    LodGraphSelection const wide = selectLodGraphAtRatio(graph, camera, 1.0f, 0.0f);
    LodGraphSelection const narrow = selectLodGraphAtRatio(graph, camera, 0.5f, 0.0f);
    ASSERT_FALSE(wide.nodes.empty());
    ASSERT_FALSE(narrow.nodes.empty());
    ASSERT_LT(narrow.nodes.size(), wide.nodes.size());

    StreamingLodGraph stream(serializeLodGraph(graph));
    ASSERT_TRUE(stream.valid());
    std::vector<LodStreamingPage> const pages = stream.planPages(4096);
    ASSERT_GE(pages.size(), 3u);

    // Resolve each node to its page up front so the expected fetch count is deterministic.
    std::vector<uint32_t> pageOf(stream.nodeCount(), UINT32_MAX);
    for (uint32_t pageId = 0; pageId < pages.size(); ++pageId) {
        for (uint32_t nodeId = pages[pageId].firstNode;
                nodeId < pages[pageId].firstNode + pages[pageId].nodeCount; ++nodeId) {
            pageOf[nodeId] = pageId;
        }
    }
    auto requiredPages = [&](std::vector<uint32_t> const& nodes) {
        std::set<uint32_t> required;
        for (uint32_t nodeId: nodes) {
            required.insert(pageOf[nodeId]);
        }
        return required;
    };
    std::set<uint32_t> const narrowPages = requiredPages(narrow.nodes);

    std::atomic<uint32_t> fetches{ 0 };
    AsyncLodStreamingCache cache(
            &stream,
            [&](LodStreamingPage const& page, std::vector<LodGraphNode>* nodes) {
                fetches.fetch_add(1);
                std::this_thread::sleep_for(std::chrono::milliseconds(40));
                return stream.readPage(page, nodes);
            },
            4u * 1024u * 1024u, 4096, 1);

    EXPECT_TRUE(cache.request(wide));
    auto const deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while ((cache.pending() < 2 || fetches.load() == 0) &&
            std::chrono::steady_clock::now() < deadline) {
        cache.poll();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    ASSERT_GE(cache.pending(), 2u) << "the test needs a non-empty queue to cancel";
    ASSERT_GT(fetches.load(), 0u);

    // The first page is already running. Every other page still in the queue belongs to the old
    // cut and must be dropped when the new one arrives; running work is allowed to finish.
    EXPECT_TRUE(cache.request(narrow));
    EXPECT_LE(cache.pending(), 1u + narrowPages.size());

    while (!cache.ready() && std::chrono::steady_clock::now() < deadline) {
        cache.poll();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    cache.poll();
    ASSERT_TRUE(cache.ready());

    uint32_t const expected = uint32_t(narrowPages.size()) + (narrowPages.count(0) == 0 ? 1u : 0u);
    EXPECT_EQ(fetches.load(), expected);
    EXPECT_LT(fetches.load(), pages.size()) << "queued pages from the old cut were not dropped";
    EXPECT_EQ(cache.stats().failedFetches, 0u);
    for (uint32_t nodeId: narrow.nodes) {
        EXPECT_NE(cache.find(nodeId), nullptr) << "node " << nodeId << " was not prefetched";
    }
}

TEST(ManyMesh, HttpByteRangeFetcherValidatesUrls) {
#if defined(_WIN32) || defined(MANYMESH_HTTP_CIVETWEB)
    HttpByteRangeFetcher const https("https://cdn.example.com/assets/lod_graph.mmb");
    EXPECT_TRUE(https.valid()) << https.lastError();
    EXPECT_EQ(https.url(), "https://cdn.example.com/assets/lod_graph.mmb");

    HttpByteRangeFetcher const hostPort("http://127.0.0.1:8080/lod_graph.mmb?token=1");
    EXPECT_TRUE(hostPort.valid()) << hostPort.lastError();

    HttpByteRangeFetcher const ipv6("http://[::1]:9000/lod_graph.mmb");
    EXPECT_TRUE(ipv6.valid()) << ipv6.lastError();

    EXPECT_FALSE(HttpByteRangeFetcher("ftp://example.com/lod_graph.mmb").valid());
    EXPECT_FALSE(HttpByteRangeFetcher("https://example.com:0/lod_graph.mmb").valid());
    EXPECT_FALSE(HttpByteRangeFetcher("https://example.com:/lod_graph.mmb").valid());
    EXPECT_FALSE(HttpByteRangeFetcher("http://[::1]:/lod_graph.mmb").valid());
    EXPECT_FALSE(HttpByteRangeFetcher("https://example.com:notaport/lod_graph.mmb").valid());
    EXPECT_FALSE(HttpByteRangeFetcher("https:///lod_graph.mmb").valid());
#else
    HttpByteRangeFetcher const fetcher("https://cdn.example.com/assets/lod_graph.mmb");
    EXPECT_FALSE(fetcher.valid());
    EXPECT_FALSE(fetcher.lastError().empty());
#endif
}

TEST(ManyMesh, HttpByteRangeFetcherAcceptsAPlatformTransport) {
    std::vector<uint8_t> source(512);
    for (size_t i = 0; i < source.size(); ++i) {
        source[i] = uint8_t(i & 0xFFu);
    }
    size_t calls = 0;
    HttpByteRangeFetcher transport("https://cdn.example.com/lod_graph.mmb",
            [&](uint64_t offset, size_t size, std::vector<uint8_t>* bytes, std::string* error) {
                calls += 1;
                if (offset > source.size() || size > source.size() - offset) {
                    *error = "range outside the test blob";
                    return false;
                }
                bytes->assign(source.begin() + offset, source.begin() + offset + size);
                return true;
            });
    ASSERT_TRUE(transport.valid()) << transport.lastError();

    std::vector<uint8_t> bytes;
    ASSERT_TRUE(transport.fetch(100, 64, &bytes)) << transport.lastError();
    EXPECT_EQ(calls, 1u);
    ASSERT_EQ(bytes.size(), 64u);
    EXPECT_TRUE(std::equal(bytes.begin(), bytes.end(), source.begin() + 100));

    EXPECT_FALSE(transport.fetch(500, 64, &bytes));
    EXPECT_FALSE(transport.lastError().empty());
    EXPECT_TRUE(bytes.empty());
}

// Opt-in end-to-end check. Point MANYMESH_HTTP_RANGE_TEST_URL at a server that honors Range
// requests for a serialized graph, then the cache fetches its pages over the same transport a
// game would use.
TEST(ManyMesh, HttpByteRangeFetcherFeedsTheAsyncCache) {
    char const* url = std::getenv("MANYMESH_HTTP_RANGE_TEST_URL");
    if (url == nullptr || *url == '\0') {
        GTEST_SKIP() << "set MANYMESH_HTTP_RANGE_TEST_URL to run the HTTP transport test";
    }

    Mesh const mesh = makeGrid(24, 24, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);
    std::vector<uint8_t> const blob = serializeLodGraph(graph);

    // The server is expected to serve this exact file, so the test can compare transport bytes
    // against the locally serialized graph.
    std::filesystem::path const path =
            std::filesystem::temp_directory_path() / "manymesh_http_test_graph.mmb";
    {
        std::ofstream file(path, std::ios::binary | std::ios::trunc);
        ASSERT_TRUE(file.good()) << path;
        file.write(reinterpret_cast<char const*>(blob.data()), std::streamsize(blob.size()));
    }
    std::cout << "serving " << path << " as " << url << std::endl;

    HttpByteRangeFetcher transport(url);
    ASSERT_TRUE(transport.valid()) << transport.lastError();

    std::vector<uint8_t> magic;
    ASSERT_TRUE(transport.fetch(0, 4, &magic)) << transport.lastError();
    ASSERT_EQ(magic.size(), 4u);
    EXPECT_EQ(std::memcmp(magic.data(), "MMLG", 4), 0);

    StreamingLodGraph stream(blob);
    ViewCamera camera;
    camera.eye = { 12.0f, 12.0f, 60.0f };
    camera.target = { 12.0f, 12.0f, 0.0f };
    camera.screenHeight = 180;
    camera.screenWidth = 320;
    LodGraphCut const cut = selectLodGraphCut(graph, camera, 1000.0f);
    ASSERT_FALSE(cut.nodes.empty());

    AsyncLodStreamingCache cache(&stream, transport.asFetcher(), 4u * 1024u * 1024u, 4096, 2);
    ASSERT_TRUE(cache.request(cut));
    auto const deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
    while (!cache.ready() && std::chrono::steady_clock::now() < deadline) {
        cache.poll();
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    cache.poll();
    ASSERT_TRUE(cache.ready());
    EXPECT_EQ(cache.stats().failedFetches, 0u) << transport.lastError();
    for (uint32_t nodeId: cut.nodes) {
        EXPECT_NE(cache.find(nodeId), nullptr) << "node " << nodeId << " was not fetched";
    }
}

TEST(ManyMesh, GpuLayoutAndVisibilityBufferFollowTheSelection) {
    Mesh const mesh = makeGrid(16, 16, {}, 1.0f, 0.4f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);

    ViewCamera camera;
    camera.eye = { 8.0f, 8.0f, 40.0f };
    camera.target = { 8.0f, 8.0f, 0.0f };
    camera.screenHeight = 120;
    camera.screenWidth = 160;
    camera.near = 0.1f;
    camera.far = 1000.0f;
    LodGraphSelection const selection = selectLodGraphTier(graph, camera, LodTier::Balanced);

    GpuLodBuffer const gpu = flattenLodGraph(graph);
    ASSERT_EQ(gpu.nodes.size(), graph.nodes.size());
    for (size_t nodeId = 0; nodeId < graph.nodes.size(); ++nodeId) {
        GpuLodNode const& node = gpu.nodes[nodeId];
        LodGraphNode const& source = graph.nodes[nodeId];
        EXPECT_EQ(node.parent, source.parent);
        EXPECT_EQ(node.baseTriangles,
                uint32_t(std::min<uint64_t>(source.baseTriangles, UINT32_MAX)));
        EXPECT_EQ(node.indexCount, source.indices.size());
        EXPECT_EQ(node.indexOffset + node.indexCount <= gpu.indices.size(), true);
        EXPECT_TRUE(std::equal(source.indices.begin(), source.indices.end(),
                gpu.indices.begin() + node.indexOffset));
    }
    std::vector<GpuDrawIndexedIndirectCommand> const draws = buildIndirectDraws(gpu, selection);
    EXPECT_EQ(draws.size(), selection.nodes.size());
    for (size_t draw = 0; draw < draws.size(); ++draw) {
        uint32_t const nodeId = selection.nodes[draw];
        EXPECT_EQ(draws[draw].indexCount, gpu.nodes[nodeId].indexCount);
        EXPECT_EQ(draws[draw].firstIndex, gpu.nodes[nodeId].indexOffset);
        EXPECT_EQ(draws[draw].baseInstance, nodeId);
    }

    VisibilityBuffer const visibility = rasterizeVisibility(mesh, gpu, selection, camera);
    EXPECT_EQ(visibility.clusterIds.size(), size_t(camera.screenWidth) * camera.screenHeight);
    EXPECT_EQ(visibility.triangleIds.size(), visibility.clusterIds.size());
    EXPECT_EQ(visibility.materialIds.size(), visibility.clusterIds.size());
    EXPECT_EQ(visibility.submeshIds.size(), visibility.clusterIds.size());
    EXPECT_GT(visibility.coveredPixels, 0u);
    bool sawCluster = false;
    for (size_t pixel = 0; pixel < visibility.clusterIds.size(); ++pixel) {
        uint32_t const cluster = visibility.clusterIds[pixel];
        if (cluster != UINT32_MAX) {
            sawCluster = true;
            EXPECT_LT(cluster, graph.nodes.size());
            EXPECT_LT(visibility.triangleIds[pixel], gpu.indices.size() / 3);
            EXPECT_EQ(visibility.materialIds[pixel], graph.nodes[cluster].materialId);
            EXPECT_EQ(visibility.submeshIds[pixel], graph.nodes[cluster].submeshId);
        }
    }
    EXPECT_TRUE(sawCluster);
}

TEST(ManyMesh, CornerSimplifierMovesSeamVerticesAndKeepsWeldedTopology) {
    // Two 16x8 grids meet at x=16 with a UV discontinuity. The welded outline is a rectangle;
    // the importer duplicates the seam column, so only a corner-attribute simplifier can reduce
    // the interior without opening a crack.
    Mesh mesh;
    auto appendGrid = [&mesh](uint32_t offsetX, float uOffset) {
        uint32_t const nx = 16;
        uint32_t const ny = 8;
        uint32_t const base = uint32_t(mesh.positions.size());
        for (uint32_t j = 0; j <= ny; ++j) {
            for (uint32_t i = 0; i <= nx; ++i) {
                float const x = float(offsetX + i);
                float const y = float(j);
                mesh.positions.push_back({ x, y, 0.18f * std::sin(x * 0.7f) * std::cos(y * 0.9f) });
                mesh.normals.push_back({ 0.0f, 0.0f, 1.0f });
                mesh.uvs.push_back({ float(i) / float(nx) + uOffset, float(j) / float(ny) });
            }
        }
        auto index = [base, nx](uint32_t i, uint32_t j) { return base + j * (nx + 1) + i; };
        for (uint32_t j = 0; j < ny; ++j) {
            for (uint32_t i = 0; i < nx; ++i) {
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j), index(i + 1, j + 1) });
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j + 1), index(i, j + 1) });
            }
        }
    };
    appendGrid(0, 0.0f);
    appendGrid(16, 0.0f);

    CornerSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = true;
    std::vector<uint32_t> simplified;
    std::vector<GeneratedVertex> generated;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithCornerAttributes(mesh, mesh.indices, options, &simplified, &generated,
            &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());
    ASSERT_FALSE(generated.empty());
    EXPECT_GT(worldError, 0.0f);

    bool sawMovedVertex = false;
    for (GeneratedVertex const& vertex: generated) {
        EXPECT_TRUE(vertex.hasPosition);
        ASSERT_LT(vertex.positionSource, mesh.positions.size());
        if (length(vertex.position - mesh.positions[vertex.positionSource]) > 1e-6f) {
            sawMovedVertex = true;
        }
    }
    EXPECT_TRUE(sawMovedVertex) << "QEM should move at least one seam vertex";

    Mesh result = mesh;
    appendGeneratedVertices(&result, generated);
    TopologyStats const base = measureWeldedTopology(mesh, mesh.indices);
    TopologyStats const stats = measureWeldedTopology(result, simplified);
    EXPECT_EQ(stats.boundaryEdges, base.boundaryEdges);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.flippedTriangles, 0u);
    for (uint32_t index: simplified) {
        EXPECT_LT(index, result.positions.size());
    }
}

TEST(ManyMesh, CornerSimplifierHandlesFourChartCopiesAtOnePosition) {
    // Four grids meet at a single welded position, so four attribute vertices share that exact
    // point. Pairwise seam handling is not enough here: the welded topology must be reduced as
    // one surface and each chart must get back the attributes it needs.
    Mesh mesh;
    auto appendGrid = [&mesh](uint32_t offsetX, uint32_t offsetY, float uOffset) {
        uint32_t const nx = 16;
        uint32_t const ny = 8;
        uint32_t const base = uint32_t(mesh.positions.size());
        for (uint32_t j = 0; j <= ny; ++j) {
            for (uint32_t i = 0; i <= nx; ++i) {
                float const x = float(offsetX + i);
                float const y = float(offsetY + j);
                mesh.positions.push_back({ x, y, 0.18f * std::sin(x * 0.7f) * std::cos(y * 0.9f) });
                mesh.normals.push_back({ 0.0f, 0.0f, 1.0f });
                mesh.uvs.push_back({ float(i) / float(nx) + uOffset, float(j) / float(ny) });
            }
        }
        auto index = [base, nx](uint32_t i, uint32_t j) { return base + j * (nx + 1) + i; };
        for (uint32_t j = 0; j < ny; ++j) {
            for (uint32_t i = 0; i < nx; ++i) {
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j), index(i + 1, j + 1) });
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j + 1), index(i, j + 1) });
            }
        }
    };
    appendGrid(0, 0, 0.0f);
    appendGrid(16, 0, 0.5f);
    appendGrid(0, 8, 0.0f);
    appendGrid(16, 8, 0.5f);

    CornerSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = true;
    std::vector<uint32_t> simplified;
    std::vector<GeneratedVertex> generated;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithCornerAttributes(mesh, mesh.indices, options, &simplified, &generated,
            &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());

    Mesh result = mesh;
    appendGeneratedVertices(&result, generated);
    TopologyStats const base = measureWeldedTopology(mesh, mesh.indices);
    TopologyStats const stats = measureWeldedTopology(result, simplified);
    EXPECT_EQ(stats.boundaryEdges, base.boundaryEdges);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.flippedTriangles, 0u);
}

TEST(ManyMesh, CornerSimplifierKeepsAttributesOfThreeChartCopiesAtOnePosition) {
    std::array<uint32_t, 3> centres = {};
    Mesh mesh = makeThreeSectorDisk(&centres);

    CornerSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = true;
    std::vector<uint32_t> simplified;
    std::vector<GeneratedVertex> generated;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithCornerAttributes(mesh, mesh.indices, options, &simplified, &generated,
            &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());
    EXPECT_GT(worldError, 0.0f);
    ASSERT_FALSE(generated.empty());
    bool sawMovedVertex = false;
    for (GeneratedVertex const& vertex: generated) {
        EXPECT_TRUE(vertex.hasPosition);
        ASSERT_LT(vertex.positionSource, mesh.positions.size());
        if (length(vertex.position - mesh.positions[vertex.positionSource]) > 1e-6f) {
            sawMovedVertex = true;
        }
    }
    EXPECT_TRUE(sawMovedVertex);

    Mesh result = mesh;
    appendGeneratedVertices(&result, generated);
    TopologyStats const base = measureWeldedTopology(mesh, mesh.indices);
    TopologyStats const stats = measureWeldedTopology(result, simplified);
    EXPECT_EQ(stats.boundaryEdges, base.boundaryEdges);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.flippedTriangles, 0u);


    auto sourceOf = [&generated, &mesh](uint32_t index) {
        return index < mesh.vertexCount() ? index
                                          : generated[index - mesh.vertexCount()].positionSource;
    };
    std::map<uint32_t, std::vector<uint32_t>> sourcesByOutput;
    for (uint32_t index: simplified) {
        sourcesByOutput[index].push_back(sourceOf(index));
    }
    for (auto const& [output, sources]: sourcesByOutput) {
        for (size_t i = 0; i < sources.size(); ++i) {
            for (size_t j = i + 1; j < sources.size(); ++j) {
                if (sources[i] == sources[j]) {
                    continue;
                }
                math::float2 const a = mesh.uvs[sources[i]];
                math::float2 const b = mesh.uvs[sources[j]];
                float const distance = length(a - b);
                EXPECT_LE(distance, 1e-4f)
                        << "output vertex " << output << " merged charts with different UVs";
                float const normalDot = dot(normalize(mesh.normals[sources[i]]),
                        normalize(mesh.normals[sources[j]]));
                EXPECT_GE(normalDot, 1.0f - 1e-6f)
                        << "output vertex " << output << " merged charts with different normals";
            }
        }
    }
    for (uint32_t centre: centres) {
        EXPECT_LT(centre, mesh.vertexCount());
        EXPECT_TRUE(std::any_of(simplified.begin(), simplified.end(), [&](uint32_t index) {
            return sourceOf(index) == centre;
        })) << "chart centre disappeared from the result";
    }
}

TEST(ManyMesh, CornerSimplifierEmitsOneVertexPerDivergentUvCluster) {
    std::array<uint32_t, 3> centres = {};
    Mesh mesh = makeThreeSectorDisk(&centres);

    CornerSimplifyOptions options;
    options.targetIndexCount = (mesh.indices.size() / 2 / 3) * 3;
    options.lockBorder = true;
    std::vector<uint32_t> simplified;
    std::vector<GeneratedVertex> generated;
    float worldError = 0.0f;
    ASSERT_TRUE(simplifyWithCornerAttributes(mesh, mesh.indices, options, &simplified, &generated,
            &worldError));
    EXPECT_LT(simplified.size(), mesh.indices.size());
    ASSERT_FALSE(generated.empty());

    auto uvDistance = [](math::float2 a, math::float2 b) {
        math::float2 delta = a - b;
        delta.x -= std::round(delta.x);
        delta.y -= std::round(delta.y);
        return length(delta);
    };
    // The three sector charts occupy non-overlapping U bands. A triangle must not mix them just
    // because its three corners share a welded position.
    auto chartOfUv = [](math::float2 uv) { return uv.x < 0.34f ? 0 : (uv.x < 0.67f ? 1 : 2); };

    std::map<std::array<float, 3>, std::vector<uint32_t>> generatedByPosition;
    for (uint32_t i = 0; i < generated.size(); ++i) {
        math::float3 const& position = generated[i].position;
        generatedByPosition[{ position.x, position.y, position.z }].push_back(i);
    }
    std::set<uint32_t> referenced;
    for (uint32_t index: simplified) {
        if (index >= mesh.vertexCount()) {
            referenced.insert(index - uint32_t(mesh.vertexCount()));
        }
    }

    bool sawDivergentCluster = false;
    bool sawMultipleCharts = false;
    for (auto const& [position, ids]: generatedByPosition) {
        if (ids.size() < 2 || !std::all_of(ids.begin(), ids.end(),
                                      [&](uint32_t id) { return referenced.count(id) != 0; })) {
            continue;
        }
        float maxDistance = 0.0f;
        std::array<bool, 3> charts = {};
        for (uint32_t id: ids) {
            charts[chartOfUv(generated[id].uv)] = true;
        }
        for (size_t i = 0; i < ids.size(); ++i) {
            for (size_t j = i + 1; j < ids.size(); ++j) {
                maxDistance = std::max(maxDistance,
                        uvDistance(generated[ids[i]].uv, generated[ids[j]].uv));
            }
        }
        if (maxDistance > 0.10f) {
            sawDivergentCluster = true;
            if (charts[0] + charts[1] + charts[2] > 1) {
                sawMultipleCharts = true;
            }
        }
    }
    EXPECT_TRUE(sawDivergentCluster)
            << "a moved position kept one averaged UV instead of chart-specific generated vertices";
    EXPECT_TRUE(sawMultipleCharts)
            << "same-position generated vertices did not preserve distinct chart islands";

    std::vector<math::float2> outputUv(mesh.vertexCount() + generated.size());
    for (uint32_t i = 0; i < mesh.vertexCount(); ++i) {
        outputUv[i] = mesh.uvs[i];
    }
    for (size_t i = 0; i < generated.size(); ++i) {
        outputUv[mesh.vertexCount() + i] = generated[i].uv;
    }
    for (size_t i = 0; i + 2 < simplified.size(); i += 3) {
        int const chart = chartOfUv(outputUv[simplified[i]]);
        EXPECT_EQ(chartOfUv(outputUv[simplified[i + 1]]), chart)
                << "triangle mixes UV charts at vertex 1";
        EXPECT_EQ(chartOfUv(outputUv[simplified[i + 2]]), chart)
                << "triangle mixes UV charts at vertex 2";
    }

    Mesh result = mesh;
    appendGeneratedVertices(&result, generated);
    TopologyStats const base = measureWeldedTopology(mesh, mesh.indices);
    TopologyStats const stats = measureWeldedTopology(result, simplified);
    EXPECT_EQ(stats.boundaryEdges, base.boundaryEdges);
    EXPECT_EQ(stats.nonManifoldEdges, 0u);
    EXPECT_EQ(stats.duplicateTriangles, 0u);
    EXPECT_EQ(stats.degenerateTriangles, 0u);
    EXPECT_EQ(stats.flippedTriangles, 0u);
}

TEST(ManyMesh, LodGraphRoundTripsPositionIdsAndGeneratedPositions) {
    Mesh mesh;
    auto appendGrid = [&mesh](uint32_t offsetX) {
        uint32_t const nx = 12;
        uint32_t const ny = 8;
        uint32_t const base = uint32_t(mesh.positions.size());
        for (uint32_t j = 0; j <= ny; ++j) {
            for (uint32_t i = 0; i <= nx; ++i) {
                float const x = float(offsetX + i);
                float const y = float(j);
                mesh.positions.push_back({ x, y, 0.15f * std::sin(x * 0.7f) * std::cos(y * 0.9f) });
                mesh.normals.push_back({ 0.0f, 0.0f, 1.0f });
                mesh.uvs.push_back({ float(i) / float(nx), float(j) / float(ny) });
            }
        }
        auto index = [base, nx](uint32_t i, uint32_t j) { return base + j * (nx + 1) + i; };
        for (uint32_t j = 0; j < ny; ++j) {
            for (uint32_t i = 0; i < nx; ++i) {
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j), index(i + 1, j + 1) });
                mesh.indices.insert(mesh.indices.end(),
                        { index(i, j), index(i + 1, j + 1), index(i, j + 1) });
            }
        }
    };
    appendGrid(0);
    appendGrid(12);

    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 4;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.cornerSimplify = true;
    options.simplify.attributeQem = true;
    options.simplify.lockBorder = true;

    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.generatedVertices.empty());
    ASSERT_EQ(graph.positionIds.size(), graph.vertexCount);

    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    StreamingLodGraph const streaming(blob);
    ASSERT_TRUE(streaming.valid());
    EXPECT_EQ(streaming.positionIds(), graph.positionIds);

    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(blob, &restored));
    EXPECT_EQ(restored.positionIds, graph.positionIds);
    ASSERT_EQ(restored.generatedVertices.size(), graph.generatedVertices.size());
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        EXPECT_TRUE(restored.generatedVertices[i].hasPosition);
        EXPECT_TRUE(restored.generatedVertices[i] == graph.generatedVertices[i]);
    }
}

TEST(ManyMesh, LodGraphCarriesAmbientOcclusionThroughSimplification) {
    Mesh mesh = makeGrid(16, 16, {}, 1.0f, 0.35f);
    ASSERT_FALSE(mesh.positions.empty());
    mesh.ao.resize(mesh.positions.size());
    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        mesh.ao[i] = 0.2f + 0.6f * (mesh.positions[i].x * 0.5f + 0.5f);
    }

    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 4;
    options.levels = 3;
    options.ratio = 0.5f;
    options.simplify.cornerSimplify = true;
    options.simplify.attributeQem = true;

    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.generatedVertices.empty());
    float minAO = 1.0f;
    float maxAO = 0.0f;
    for (GeneratedVertex const& vertex: graph.generatedVertices) {
        EXPECT_GE(vertex.ao, 0.0f);
        EXPECT_LE(vertex.ao, 1.0f);
        minAO = std::min(minAO, vertex.ao);
        maxAO = std::max(maxAO, vertex.ao);
    }
    EXPECT_LT(minAO, maxAO);

    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(blob, &restored));
    ASSERT_EQ(restored.generatedVertices.size(), graph.generatedVertices.size());
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        EXPECT_FLOAT_EQ(restored.generatedVertices[i].ao, graph.generatedVertices[i].ao);
    }

    Mesh dagMesh = mesh;
    appendGeneratedVertices(&dagMesh, graph.generatedVertices);
    ASSERT_EQ(dagMesh.ao.size(), dagMesh.positions.size());
    size_t const sourceCount = mesh.positions.size();
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        EXPECT_FLOAT_EQ(dagMesh.ao[sourceCount + i], graph.generatedVertices[i].ao);
    }
}

TEST(ManyMesh, LodGraphKeepsThreeChartCopiesAndTheirUvIslands) {
    // The disk is made of three charts whose centres share a position. A graph builder that
    // fell back to the pairwise AttributeSimplifier seam lock would either refuse to simplify
    // across the charts or weld the three centre attribute copies. Drive the whole pipeline:
    // build the DAG, select a cut, compact it, and verify that every surviving triangle still
    // matches exactly one chart's affine position-to-UV mapping.
    std::array<uint32_t, 3> centres = {};
    Mesh const mesh = makeThreeSectorDisk(&centres);
    for (uint32_t centre: centres) {
        ASSERT_LT(centre, mesh.vertexCount());
        EXPECT_NEAR(length(mesh.positions[centre]), 0.0f, 1e-6f);
    }

    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 16;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.cornerSimplify = true;
    options.simplify.attributeQem = true;
    options.simplify.lockBorder = true;
    options.simplify.qualityGate = true;

    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.generatedVertices.empty());
    ASSERT_EQ(graph.positionIds.size(), graph.vertexCount);
    EXPECT_EQ(graph.sourceVertexCount(), mesh.vertexCount());

    // Some simplified parent must span all three charts; otherwise the test never exercised a
    // cross-chart merge and could pass while the seam logic is still locked.
    auto chartOfUv = [](float u) { return u < 0.34f ? 0 : (u < 0.67f ? 1 : 2); };
    bool sawCrossChartParent = false;
    for (LodGraphNode const& node: graph.nodes) {
        if (node.level == 0 || !node.simplified) {
            continue;
        }
        std::array<bool, 3> chartsSeen = {};
        for (uint32_t index: node.indices) {
            ASSERT_LT(index, graph.vertexCount);
            float const u =
                    index < graph.sourceVertexCount()
                            ? mesh.uvs[index].x
                            : graph.generatedVertices[index - graph.sourceVertexCount()].uv.x;
            chartsSeen[chartOfUv(u)] = true;
        }
        if (chartsSeen[0] && chartsSeen[1] && chartsSeen[2]) {
            sawCrossChartParent = true;
        }
    }
    EXPECT_TRUE(sawCrossChartParent) << "no simplified parent spans all three charts";

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 24.0f };
    camera.target = { 0.0f, 0.0f, 0.0f };
    camera.screenHeight = 720;
    camera.screenWidth = 1280;
    camera.near = 0.1f;
    camera.far = 1000.0f;

    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 0.35f, 1000.0f);
    ASSERT_FALSE(selection.indices.empty());
    EXPECT_LT(selection.selectedTriangles, graph.baseTriangles);

    LodGraphCutGeometry const cut = compactLodSelection(graph, selection);
    ASSERT_EQ(cut.indices.size(), size_t(cut.triangles) * 3);
    ASSERT_EQ(cut.sourceVertexCount, graph.sourceVertexCount());
    ASSERT_EQ(cut.generatedSourceIds.size(), cut.generatedVertices.size());

    Mesh cutMesh;
    cutMesh.positions.reserve(cut.vertexCount);
    cutMesh.normals.reserve(cut.vertexCount);
    cutMesh.uvs.reserve(cut.vertexCount);
    for (uint32_t i = 0; i < cut.sourceVertexCount; ++i) {
        cutMesh.positions.push_back(mesh.positions[i]);
        cutMesh.normals.push_back(mesh.normals[i]);
        cutMesh.uvs.push_back(mesh.uvs[i]);
    }
    for (GeneratedVertex const& vertex: cut.generatedVertices) {
        EXPECT_TRUE(vertex.hasPosition);
        cutMesh.positions.push_back(vertex.position);
        cutMesh.normals.push_back(vertex.normal);
        cutMesh.uvs.push_back(vertex.uv);
    }
    ASSERT_EQ(cutMesh.vertexCount(), cut.vertexCount);

    TopologyStats const baseTopology = measureWeldedTopology(mesh, mesh.indices);
    TopologyStats const cutTopology = measureWeldedTopology(cutMesh, cut.indices);
    EXPECT_EQ(cutTopology.boundaryEdges, baseTopology.boundaryEdges);
    EXPECT_EQ(cutTopology.nonManifoldEdges, 0u);
    EXPECT_EQ(cutTopology.duplicateTriangles, 0u);
    EXPECT_EQ(cutTopology.degenerateTriangles, 0u);
    EXPECT_EQ(cutTopology.flippedTriangles, 0u);

    // Each chart maps position to UV affinely: u = uOffset + scale * x, v = vOffset + scale * y.
    // Every vertex of a triangle must agree with one chart's mapping. A weld that merges copies
    // with different UVs shows up as a residual of nearly a full chart width, which no amount of
    // normal simplification interpolation can produce.
    struct ChartMapping {
        float scale;
        float uOffset;
        float vOffset;
    };
    ChartMapping const charts[3] = {
        { 0.15f, 0.17f, 0.18f },
        { 0.14f, 0.50f, 0.17f },
        { 0.135f, 0.835f, 0.165f },
    };
    std::array<size_t, 3> trianglesPerChart = {};
    for (size_t i = 0; i + 2 < cut.indices.size(); i += 3) {
        uint32_t const ia = cut.indices[i];
        uint32_t const ib = cut.indices[i + 1];
        uint32_t const ic = cut.indices[i + 2];
        ASSERT_LT(ia, cut.vertexCount);
        ASSERT_LT(ib, cut.vertexCount);
        ASSERT_LT(ic, cut.vertexCount);
        math::float3 const& pa = cutMesh.positions[ia];
        math::float3 const& pb = cutMesh.positions[ib];
        math::float3 const& pc = cutMesh.positions[ic];
        math::float2 const& qa = cutMesh.uvs[ia];
        math::float2 const& qb = cutMesh.uvs[ib];
        math::float2 const& qc = cutMesh.uvs[ic];
        size_t const chart = chartOfUv((qa.x + qb.x + qc.x) / 3.0f);
        ChartMapping const& mapping = charts[chart];
        float cost = 0.0f;
        auto accumulate = [&](math::float3 const& position, math::float2 const& uv) {
            cost = std::max(cost, std::abs(uv.x - (mapping.uOffset + mapping.scale * position.x)));
            cost = std::max(cost, std::abs(uv.y - (mapping.vOffset + mapping.scale * position.y)));
        };
        accumulate(pa, qa);
        accumulate(pb, qb);
        accumulate(pc, qc);
        EXPECT_LT(cost, 0.01f) << "triangle " << (i / 3) << " no longer matches chart " << chart
                               << "'s UV mapping: p0=(" << pa.x << "," << pa.y << ") uv0=(" << qa.x
                               << "," << qa.y << ") p1=(" << pb.x << "," << pb.y << ") uv1=("
                               << qb.x << "," << qb.y << ") p2=(" << pc.x << "," << pc.y
                               << ") uv2=(" << qc.x << "," << qc.y << ")";
        ++trianglesPerChart[chart];
    }
    for (size_t chart = 0; chart < 3; ++chart) {
        EXPECT_GT(trianglesPerChart[chart], 0u) << "chart " << chart << " lost its UV island";
    }
}

TEST(ManyMesh, LodGraphReadsVersionFiveWithoutPositionIds) {
    Mesh const mesh = makeGrid(12, 12, {}, 1.0f, 0.3f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 4;
    options.levels = 3;
    options.simplify.cornerSimplify = true;
    options.simplify.attributeQem = true;
    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.generatedVertices.empty());
    std::vector<uint8_t> const blob = serializeLodGraph(graph);

    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    uint32_t generatedCount = 0;
    std::memcpy(&rootCount, blob.data() + 12, sizeof(rootCount));
    std::memcpy(&leafCount, blob.data() + 16, sizeof(leafCount));
    size_t const generatedCountOffset = 36u + (size_t(rootCount) + leafCount) * sizeof(uint32_t);
    std::memcpy(&generatedCount, blob.data() + generatedCountOffset, sizeof(generatedCount));
    size_t const generatedEnd = generatedCountOffset + sizeof(uint32_t) +
                                size_t(generatedCount) * 10u * sizeof(uint32_t);
    ASSERT_LE(generatedEnd + sizeof(uint32_t), blob.size());
    uint32_t positionIdCount = 0;
    std::memcpy(&positionIdCount, blob.data() + generatedEnd, sizeof(positionIdCount));
    size_t const positionIdsEnd =
            generatedEnd + sizeof(uint32_t) + size_t(positionIdCount) * sizeof(uint32_t);
    ASSERT_LE(positionIdsEnd, blob.size());

    size_t const generatedStart = generatedCountOffset + sizeof(uint32_t);
    std::vector<uint8_t> v5;
    v5.insert(v5.end(), blob.begin(), blob.begin() + std::ptrdiff_t(generatedStart));
    for (uint32_t i = 0; i < generatedCount; ++i) {
        uint8_t const* record = blob.data() + generatedStart + size_t(i) * 10u * sizeof(uint32_t);
        // Version 5 stored nine words per generated vertex; version 7 appends the AO word.
        v5.insert(v5.end(), record, record + 9u * sizeof(uint32_t));
    }
    size_t const v5GeneratedEnd = v5.size();
    v5.insert(v5.end(), blob.begin() + std::ptrdiff_t(positionIdsEnd), blob.end());
    uint32_t const version = 5;
    std::memcpy(v5.data() + 4, &version, sizeof(version));
    size_t const removedBytes =
            size_t(positionIdsEnd - generatedEnd) + size_t(generatedCount) * sizeof(uint32_t);
    size_t const offsets = v5GeneratedEnd;
    for (size_t i = 0; i <= graph.nodes.size(); ++i) {
        uint64_t value = 0;
        std::memcpy(&value, v5.data() + offsets + i * sizeof(value), sizeof(value));
        value -= removedBytes;
        std::memcpy(&v5.data()[offsets + i * sizeof(value)], &value, sizeof(value));
    }

    StreamingLodGraph const streaming(v5);
    ASSERT_TRUE(streaming.valid());
    EXPECT_TRUE(streaming.positionIds().empty());
    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(v5, &restored));
    EXPECT_TRUE(restored.positionIds.empty());
    ASSERT_EQ(restored.generatedVertices.size(), graph.generatedVertices.size());
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        EXPECT_TRUE(restored.generatedVertices[i].hasPosition);
        EXPECT_EQ(restored.generatedVertices[i].position, graph.generatedVertices[i].position);
        // Version 5 predates the AO word: decoding it must default to unoccluded.
        EXPECT_FLOAT_EQ(restored.generatedVertices[i].ao, 1.0f);
    }
}

TEST(ManyMesh, LodGraphReadsVersionFourByFallingBackToPositionSource) {
    LodGraph graph;
    graph.vertexCount = 6; // four source vertices plus two generated ones.
    graph.baseTriangles = 1;
    graph.levelCount = 1;
    graph.roots = { 0 };
    graph.leaves = { 0 };
    graph.nodes.resize(1);
    graph.nodes[0].indices = { 0, 1, 4 };
    graph.nodes[0].baseTriangles = 1;
    graph.generatedVertices.resize(2);
    graph.generatedVertices[0].positionSource = 0;
    graph.generatedVertices[0].position = { 7.0f, 0.0f, 0.0f };
    graph.generatedVertices[0].normal = { 0.0f, 0.0f, 1.0f };
    graph.generatedVertices[0].uv = { 0.1f, 0.2f };
    graph.generatedVertices[0].hasPosition = true;
    graph.generatedVertices[1].positionSource = 2;
    graph.generatedVertices[1].position = { 8.0f, 0.0f, 0.0f };
    graph.generatedVertices[1].normal = { 0.0f, 1.0f, 0.0f };
    graph.generatedVertices[1].uv = { 0.3f, 0.4f };
    graph.generatedVertices[1].hasPosition = true;
    graph.positionIds = { 0, 1, 2, 3, 4, 5 };

    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    uint32_t generatedCount = 0;
    std::memcpy(&rootCount, blob.data() + 12, sizeof(rootCount));
    std::memcpy(&leafCount, blob.data() + 16, sizeof(leafCount));
    size_t const generatedCountOffset = 36u + (size_t(rootCount) + leafCount) * sizeof(uint32_t);
    std::memcpy(&generatedCount, blob.data() + generatedCountOffset, sizeof(generatedCount));
    ASSERT_EQ(generatedCount, 2u);
    size_t const generatedStart = generatedCountOffset + sizeof(uint32_t);
    size_t const generatedEnd = generatedStart + size_t(generatedCount) * 10u * sizeof(uint32_t);
    uint32_t positionIdCount = 0;
    std::memcpy(&positionIdCount, blob.data() + generatedEnd, sizeof(positionIdCount));
    size_t const positionIdsEnd =
            generatedEnd + sizeof(uint32_t) + size_t(positionIdCount) * sizeof(uint32_t);

    std::vector<uint8_t> v4;
    v4.insert(v4.end(), blob.begin(), blob.begin() + std::ptrdiff_t(generatedStart));
    for (uint32_t i = 0; i < generatedCount; ++i) {
        uint8_t const* record = blob.data() + generatedStart + size_t(i) * 10u * sizeof(uint32_t);
        // Version 4 stored positionSource, normal and uv but not the explicit position.
        v4.insert(v4.end(), record, record + sizeof(uint32_t));
        v4.insert(v4.end(), record + 4u * sizeof(uint32_t), record + 9u * sizeof(uint32_t));
    }
    size_t const removedBytes =
            size_t(positionIdsEnd - generatedEnd) + size_t(generatedCount) * 4u * sizeof(uint32_t);
    size_t const offsets = v4.size();
    v4.insert(v4.end(), blob.begin() + std::ptrdiff_t(positionIdsEnd), blob.end());
    uint32_t const version = 4;
    std::memcpy(v4.data() + 4, &version, sizeof(version));
    for (size_t i = 0; i <= graph.nodes.size(); ++i) {
        uint64_t value = 0;
        std::memcpy(&value, v4.data() + offsets + i * sizeof(value), sizeof(value));
        value -= removedBytes;
        std::memcpy(&v4.data()[offsets + i * sizeof(value)], &value, sizeof(value));
    }

    LodGraph restored;
    ASSERT_TRUE(deserializeLodGraph(v4, &restored));
    ASSERT_EQ(restored.generatedVertices.size(), 2u);
    EXPECT_TRUE(restored.positionIds.empty());
    for (GeneratedVertex const& vertex: restored.generatedVertices) {
        EXPECT_FALSE(vertex.hasPosition);
    }
    EXPECT_EQ(restored.generatedVertices[0].positionSource, 0u);
    EXPECT_EQ(restored.generatedVertices[0].normal, graph.generatedVertices[0].normal);
    EXPECT_EQ(restored.generatedVertices[0].uv, graph.generatedVertices[0].uv);
    EXPECT_EQ(restored.generatedVertices[1].positionSource, 2u);

    Mesh mesh;
    mesh.positions = { { 0.0f, 0.0f, 0.0f }, { 1.0f, 0.0f, 0.0f }, { 2.0f, 0.0f, 0.0f },
        { 3.0f, 0.0f, 0.0f } };
    mesh.normals.assign(4, { 0.0f, 0.0f, 1.0f });
    mesh.uvs.assign(4, { 0.0f, 0.0f });
    appendGeneratedVertices(&mesh, restored.generatedVertices);
    ASSERT_EQ(mesh.positions.size(), 6u);
    EXPECT_EQ(mesh.positions[4], mesh.positions[0]);
    EXPECT_EQ(mesh.positions[5], mesh.positions[2]);
    EXPECT_EQ(mesh.normals[4], graph.generatedVertices[0].normal);
    EXPECT_EQ(mesh.uvs[4], graph.generatedVertices[0].uv);
}

TEST(ManyMesh, CompactedCutRenumbersOnlyReferencedGeneratedVertices) {
    LodGraph graph;
    graph.vertexCount = 10;
    graph.generatedVertices.resize(6);
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        GeneratedVertex& vertex = graph.generatedVertices[i];
        vertex.positionSource = uint32_t(i);
        vertex.position = { 10.0f + float(i), 0.0f, 0.0f };
        vertex.normal = { 0.0f, 0.0f, 1.0f };
        vertex.uv = { 0.25f * float(i), 0.5f };
        vertex.hasPosition = true;
    }
    graph.positionIds = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 };
    graph.baseTriangles = 2;
    graph.levelCount = 1;
    graph.roots = { 0 };
    graph.leaves = { 0 };
    graph.nodes.resize(1);
    graph.nodes[0].indices = { 0, 1, 9, 2, 9, 7 };
    graph.nodes[0].baseTriangles = 2;

    LodGraphSelection selection;
    selection.indices = { 0, 1, 9, 2, 9, 7 };
    selection.selectedTriangles = 2;
    LodGraphCutGeometry const compacted = compactLodSelection(graph, selection);

    EXPECT_EQ(compacted.sourceVertexCount, 4u);
    EXPECT_EQ(compacted.triangles, 2u);
    ASSERT_EQ(compacted.generatedVertices.size(), 2u);
    EXPECT_EQ(compacted.vertexCount, 6u);
    EXPECT_EQ(compacted.indices, (std::vector<uint32_t>{ 0, 1, 4, 2, 4, 5 }));
    EXPECT_EQ(compacted.generatedSourceIds, (std::vector<uint32_t>{ 5, 3 }));
    EXPECT_TRUE(compacted.sourceVertexIds.empty());
    EXPECT_EQ(compacted.generatedVertices[0].position, graph.generatedVertices[5].position);
    EXPECT_EQ(compacted.generatedVertices[0].normal, graph.generatedVertices[5].normal);
    EXPECT_EQ(compacted.generatedVertices[0].uv, graph.generatedVertices[5].uv);
    EXPECT_EQ(compacted.generatedVertices[1].position, graph.generatedVertices[3].position);
}

TEST(ManyMesh, CompactedCutCanCompactSourceVerticesToo) {
    LodGraph graph;
    graph.vertexCount = 12;
    graph.generatedVertices.resize(2);
    for (size_t i = 0; i < graph.generatedVertices.size(); ++i) {
        GeneratedVertex& vertex = graph.generatedVertices[i];
        vertex.position = { 10.0f + float(i), 0.0f, 0.0f };
        vertex.normal = { 0.0f, 0.0f, 1.0f };
        vertex.uv = { 0.5f, 0.5f };
        vertex.hasPosition = true;
    }

    LodGraphSelection selection;
    selection.indices = { 7, 3, 10, 7, 11, 3 };
    selection.selectedTriangles = 2;
    LodGraphCompactOptions options;
    options.compactSourceVertices = true;
    LodGraphCutGeometry const compacted = compactLodSelection(graph, selection, options);

    EXPECT_EQ(compacted.sourceVertexCount, 2u);
    EXPECT_EQ(compacted.sourceVertexIds, (std::vector<uint32_t>{ 7, 3 }));
    EXPECT_EQ(compacted.generatedSourceIds, (std::vector<uint32_t>{ 0, 1 }));
    EXPECT_EQ(compacted.triangles, 2u);
    EXPECT_EQ(compacted.vertexCount, 4u);
    EXPECT_EQ(compacted.indices, (std::vector<uint32_t>{ 0, 1, 2, 0, 3, 1 }));
}
TEST(ManyMesh, CompactedCutPreservesTheAssembledTriangles) {
    Mesh const mesh = makeGrid(16, 16, {}, 1.0f, 0.4f);
    LodGraphOptions options;
    options.clusterize.maxVertices = 48;
    options.clusterize.maxTriangles = 48;
    options.clustersPerNode = 4;
    options.levels = 4;
    options.ratio = 0.5f;
    options.simplify.cornerSimplify = true;
    options.simplify.attributeQem = true;
    LodGraph const graph = buildLodGraph(mesh, options);
    ASSERT_FALSE(graph.generatedVertices.empty());

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 5.0f };
    camera.target = { 0.0f, 0.0f, 0.0f };
    camera.fovY = 0.78539816339f;
    camera.screenWidth = 1280.0f;
    camera.screenHeight = 720.0f;
    LodGraphSelection const selection = selectLodGraph(graph, camera, 1000.0f);
    ASSERT_FALSE(selection.indices.empty());

    LodGraphCutGeometry const compacted = compactLodSelection(graph, selection);
    ASSERT_EQ(compacted.indices.size(), selection.indices.size());
    EXPECT_LT(compacted.vertexCount, graph.vertexCount);
    EXPECT_EQ(compacted.vertexCount,
            compacted.sourceVertexCount + compacted.generatedVertices.size());

    std::vector<uint8_t> used(compacted.generatedVertices.size(), 0);
    for (size_t triangle = 0; triangle < compacted.indices.size() / 3; ++triangle) {
        for (size_t corner = 0; corner < 3; ++corner) {
            size_t const index = triangle * 3 + corner;
            uint32_t const before = selection.indices[index];
            uint32_t const after = compacted.indices[index];
            ASSERT_LT(after, compacted.vertexCount);
            if (before < graph.sourceVertexCount()) {
                EXPECT_EQ(after, before);
                continue;
            }
            ASSERT_GE(after, compacted.sourceVertexCount);
            size_t const local = size_t(after - compacted.sourceVertexCount);
            ASSERT_LT(local, compacted.generatedVertices.size());
            ASSERT_LT(local, compacted.generatedSourceIds.size());
            used[local] = 1;
            ASSERT_EQ(before - graph.sourceVertexCount(), compacted.generatedSourceIds[local]);
            GeneratedVertex const& expected =
                    graph.generatedVertices[compacted.generatedSourceIds[local]];
            GeneratedVertex const& actual = compacted.generatedVertices[local];
            EXPECT_EQ(actual.position, expected.position);
            EXPECT_EQ(actual.normal, expected.normal);
            EXPECT_EQ(actual.uv, expected.uv);
            EXPECT_EQ(actual.positionSource, expected.positionSource);
        }
    }
    for (uint8_t value: used) {
        EXPECT_EQ(value, 1u);
    }
}

TEST(ManyMesh, SelectedCutDropsFacesDuplicatedAtWeldedPositions) {
    // Two roots supply the same triangle through different attribute vertices. Selection must
    // compare canonical positions, not vertex ids, or the assembled cut contains a duplicate
    // face and three false non-manifold edges.
    LodGraph graph;
    graph.vertexCount = 6;
    graph.baseTriangles = 2;
    graph.levelCount = 1;
    graph.positionIds = { 0, 1, 2, 0, 1, 2 };
    graph.roots = { 0, 1 };
    graph.leaves = { 0, 1 };
    graph.nodes.resize(2);
    for (size_t i = 0; i < graph.nodes.size(); ++i) {
        LodGraphNode& node = graph.nodes[i];
        node.level = 0;
        node.indices = { uint32_t(i * 3), uint32_t(i * 3 + 1), uint32_t(i * 3 + 2) };
        node.baseTriangles = 1;
        node.bounds.center = { 0.0f, 0.0f, 0.0f };
        node.bounds.radius = 1.0f;
        node.cone.apex = { 0.0f, 0.0f, 0.0f };
        node.cone.axis = { 0.0f, 0.0f, 1.0f };
        node.cone.cutoff = -2.0f;
        node.materialId = 0;
        node.submeshId = 0;
    }

    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 5.0f };
    camera.target = { 0.0f, 0.0f, 0.0f };
    camera.screenWidth = 128;
    camera.screenHeight = 128;
    LodGraphSelection const selection = selectLodGraphAtRatio(graph, camera, 1.0f, 1000.0f);
    ASSERT_EQ(selection.nodes.size(), 2u);
    EXPECT_EQ(selection.selectedTriangles, 1u);
    EXPECT_EQ(selection.indices.size(), 3u);
}

namespace {

Mesh makeBakeQuad(math::float3 normal) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
    };
    mesh.normals = { normal, normal, normal, normal };
    mesh.uvs = { { 0.0f, 0.0f }, { 1.0f, 0.0f }, { 1.0f, 1.0f }, { 0.0f, 1.0f } };
    mesh.indices = { 0, 1, 2, 0, 2, 3 };
    return mesh;
}

} // anonymous namespace

TEST(ManyMesh, AmbientOcclusionLeavesAnOpenSurfaceVisible) {
    Mesh const mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    AmbientOcclusionOptions options;
    options.samples = 16;
    AmbientOcclusionResult result;
    ASSERT_TRUE(bakeVertexAmbientOcclusion(mesh, mesh, options, &result));
    ASSERT_EQ(result.values.size(), mesh.positions.size());
    for (float value: result.values) {
        EXPECT_GE(value, 0.0f);
        EXPECT_LE(value, 1.0f);
        EXPECT_GT(value, 0.98f);
    }
    ASSERT_EQ(result.bentNormals.size(), mesh.positions.size());
    for (size_t i = 0; i < result.bentNormals.size(); ++i) {
        EXPECT_GT(dot(result.bentNormals[i], mesh.normals[i]), 0.999f);
    }
    EXPECT_LT(result.maxBendDegrees, 1.0f);
}

TEST(ManyMesh, AmbientOcclusionDarkensInsideACorner) {
    // Floor at y = 0 plus a wall at x = 0. The point near the wall sees the wall in half of
    // its hemisphere; the point far from it sees empty space only.
    Mesh source;
    source.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 1.0f },
    };
    source.indices = { 0, 1, 2, 0, 2, 3, 0, 4, 5, 0, 5, 3 };

    Mesh target;
    target.positions = { { 0.1f, 0.0f, 0.5f }, { 0.9f, 0.0f, 0.5f } };
    target.normals = { { 0.0f, 1.0f, 0.0f }, { 0.0f, 1.0f, 0.0f } };

    AmbientOcclusionOptions options;
    options.samples = 64;
    options.radius = 0.25f;
    options.weldDuplicatePositions = false;
    AmbientOcclusionResult result;
    ASSERT_TRUE(bakeVertexAmbientOcclusion(source, target, options, &result));
    ASSERT_EQ(result.values.size(), 2u);
    EXPECT_LT(result.values[0], 0.9f);
    EXPECT_GT(result.values[1], 0.95f);
    EXPECT_LT(result.values[0], result.values[1]);

    // The wall blocks the -x half of the hemisphere. The surviving light comes from +x, so the
    // bent normal must tilt away from the wall even though the geometric normal stays +y.
    ASSERT_EQ(result.bentNormals.size(), 2u);
    EXPECT_GT(result.bentNormals[0].x, 0.05f);
    EXPECT_GT(dot(result.bentNormals[0], math::float3{ 0.0f, 1.0f, 0.0f }), 0.9f);
    EXPECT_LT(result.bentNormals[1].x, 0.01f);
    EXPECT_GT(dot(result.bentNormals[1], math::float3{ 0.0f, 1.0f, 0.0f }), 0.999f);
    EXPECT_GT(result.tiltedVertices, 0u);
    EXPECT_GT(result.maxBendDegrees, 1.0f);
}

TEST(ManyMesh, AmbientOcclusionIsDeterministicAndWeldsSeams) {
    Mesh const source = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    Mesh target = source;
    target.positions.push_back(source.positions[0]);
    target.normals.push_back(source.normals[0]);

    AmbientOcclusionOptions options;
    options.samples = 16;
    options.weldDuplicatePositions = true;
    AmbientOcclusionResult first;
    AmbientOcclusionResult second;
    ASSERT_TRUE(bakeVertexAmbientOcclusion(source, target, options, &first));
    ASSERT_TRUE(bakeVertexAmbientOcclusion(source, target, options, &second));
    ASSERT_EQ(first.values.size(), second.values.size());
    ASSERT_EQ(first.bentNormals.size(), second.bentNormals.size());
    for (size_t i = 0; i < first.values.size(); ++i) {
        EXPECT_FLOAT_EQ(first.values[i], second.values[i]);
        EXPECT_FLOAT_EQ(first.bentNormals[i].x, second.bentNormals[i].x);
        EXPECT_FLOAT_EQ(first.bentNormals[i].y, second.bentNormals[i].y);
        EXPECT_FLOAT_EQ(first.bentNormals[i].z, second.bentNormals[i].z);
    }
    EXPECT_EQ(first.values.front(), first.values.back());
    EXPECT_FLOAT_EQ(first.bentNormals.front().x, first.bentNormals.back().x);
    EXPECT_FLOAT_EQ(first.bentNormals.front().y, first.bentNormals.back().y);
    EXPECT_FLOAT_EQ(first.bentNormals.front().z, first.bentNormals.back().z);
    EXPECT_GT(first.weldedGroups, 0u);
}

TEST(ManyMesh, AmbientOcclusionSnapsOffSurfaceSamplesToTheSource) {
    // QEM placement can leave a generated vertex slightly below the source floor. Sampling from
    // there would see the floor from behind and report a fully occluded point. The bake must
    // move the origin to the nearest source surface first.
    Mesh source;
    source.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 1.0f },
    };
    source.indices = { 0, 1, 2, 0, 2, 3, 0, 4, 5, 0, 5, 3 };

    Mesh target;
    target.positions = { { 0.1f, -0.05f, 0.5f }, { 0.9f, -0.05f, 0.5f } };
    target.normals = { { 0.0f, 1.0f, 0.0f }, { 0.0f, 1.0f, 0.0f } };

    AmbientOcclusionOptions options;
    options.samples = 64;
    options.radius = 0.25f;
    options.weldDuplicatePositions = false;
    AmbientOcclusionResult result;
    ASSERT_TRUE(bakeVertexAmbientOcclusion(source, target, options, &result));
    EXPECT_GT(result.values[0], 0.01f);
    EXPECT_LT(result.values[0], 0.9f);
    EXPECT_GT(result.values[1], 0.95f);
}

TEST(ManyMesh, AmbientOcclusionRejectsAnEmptyMesh) {
    Mesh empty;
    AmbientOcclusionResult result;
    EXPECT_FALSE(bakeVertexAmbientOcclusion(empty, empty, {}, &result));
    EXPECT_TRUE(result.values.empty());
}

TEST(ManyMesh, AmbientOcclusionMapBakesTheUvLayoutAndIsDeterministic) {
    Mesh const mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    AmbientOcclusionMapOptions options;
    options.samples = 16;
    options.size = 32;
    options.dilationTexels = 1;
    AmbientOcclusionMapResult first;
    AmbientOcclusionMapResult second;
    ASSERT_TRUE(bakeAmbientOcclusionMap(mesh, options, &first));
    ASSERT_TRUE(bakeAmbientOcclusionMap(mesh, options, &second));
    EXPECT_EQ(first.size, 32u);
    EXPECT_EQ(first.values.size(), size_t(32) * 32);
    EXPECT_EQ(first.values, second.values);
    EXPECT_GT(first.coveredTexels, 0u);
    EXPECT_GT(first.mean, 0.98f);
    // An open quad must not be darkened by the bake.
    for (uint8_t value: first.values) {
        EXPECT_GE(value, 250);
    }
}

TEST(ManyMesh, AmbientOcclusionMapDarkensTexelsNearAConcaveCorner) {
    // Floor in the left half of the atlas, wall in the right half. The floor texel near x = 0
    // sees half of its hemisphere blocked by the wall; the texel near x = 1 sees open space.
    Mesh source;
    source.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 1.0f },
    };
    source.normals = {
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
    };
    source.uvs = {
        { 0.0f, 0.0f },
        { 0.5f, 0.0f },
        { 0.5f, 1.0f },
        { 0.0f, 1.0f },
        { 0.5f, 0.0f },
        { 1.0f, 0.0f },
    };
    // The wall needs its own bottom vertices: the floor vertices carry floor normals and UVs.
    source.positions.push_back({ 0.0f, 0.0f, 0.0f });
    source.normals.push_back({ 1.0f, 0.0f, 0.0f });
    source.uvs.push_back({ 1.0f, 1.0f });
    source.positions.push_back({ 0.0f, 0.0f, 1.0f });
    source.normals.push_back({ 1.0f, 0.0f, 0.0f });
    source.uvs.push_back({ 0.5f, 1.0f });
    source.indices = { 0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7 };

    AmbientOcclusionMapOptions options;
    options.samples = 64;
    options.size = 32;
    options.radius = 0.25f;
    options.dilationTexels = 0;
    AmbientOcclusionMapResult result;
    ASSERT_TRUE(bakeAmbientOcclusionMap(source, options, &result));
    ASSERT_EQ(result.values.size(), size_t(32) * 32);
    uint8_t const nearWall = result.values[size_t(16) * 32 + 2];
    uint8_t const farFromWall = result.values[size_t(16) * 32 + 14];
    EXPECT_LT(nearWall, 230);
    EXPECT_GT(farFromWall, 245);
    EXPECT_LT(nearWall, farFromWall);
}

TEST(ManyMesh, AmbientOcclusionMapRejectsATiledUvLayout) {
    Mesh mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    for (auto& uv: mesh.uvs) {
        uv = uv * 2.0f;
    }
    AmbientOcclusionMapResult result;
    EXPECT_FALSE(bakeAmbientOcclusionMap(mesh, {}, &result));
    EXPECT_TRUE(result.values.empty());
}

TEST(ManyMesh, DetailBakeIsNeutralForIdenticalGeometry) {
    Mesh const mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    DetailBakeOptions options;
    options.size = 64;
    options.dilationTexels = 1;
    DetailBakeResult bake;
    ASSERT_TRUE(bakeDetailNormalMap(mesh, mesh, mesh.indices, options, &bake));
    EXPECT_EQ(bake.size, 64u);
    EXPECT_GT(bake.coveredTexels, 0u);
    EXPECT_LT(bake.meanAngleDegrees, 0.01f);
    for (size_t texel = 0; texel < size_t(64) * 64; ++texel) {
        ASSERT_LE(std::abs(int(bake.rgba[texel * 4 + 0]) - 128), 1);
        ASSERT_LE(std::abs(int(bake.rgba[texel * 4 + 1]) - 128), 1);
        ASSERT_EQ(bake.rgba[texel * 4 + 2], 255);
        ASSERT_EQ(bake.rgba[texel * 4 + 3], 0);
    }
}

TEST(ManyMesh, DetailBakeCapturesTheLostNormal) {
    Mesh const source = makeBakeQuad(normalize(math::float3{ 0.5f, 0.0f, 1.0f }));
    Mesh const lod = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    DetailBakeOptions options;
    options.size = 64;
    options.dilationTexels = 1;
    DetailBakeResult bake;
    ASSERT_TRUE(bakeDetailNormalMap(source, lod, lod.indices, options, &bake));
    // The residual is 26.57 degrees: atan(0.5).
    EXPECT_NEAR(bake.meanAngleDegrees, 26.565f, 0.1f);

    size_t const center = (size_t(32) * 64 + 32) * 4;
    float const x = (float(bake.rgba[center + 0]) / 255.0f) * 2.0f - 1.0f;
    float const y = (float(bake.rgba[center + 1]) / 255.0f) * 2.0f - 1.0f;
    float const z = (float(bake.rgba[center + 2]) / 255.0f) * 2.0f - 1.0f;
    EXPECT_NEAR(x, 0.4472f, 0.02f);
    EXPECT_NEAR(y, 0.0f, 0.02f);
    EXPECT_NEAR(z, 0.8944f, 0.02f);
    // 26.565 degrees normalized to a 90-degree range.
    EXPECT_NEAR(bake.rgba[center + 3], 75, 2);
}

TEST(ManyMesh, UvTangentsFollowTheParameterization) {
    Mesh const mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    std::vector<math::float3> tangents;
    std::vector<float> signs;
    computeUvTangents(mesh, mesh.indices, &tangents, &signs);
    ASSERT_EQ(tangents.size(), mesh.positions.size());
    for (size_t vertex = 0; vertex < tangents.size(); ++vertex) {
        EXPECT_NEAR(tangents[vertex].x, 1.0f, 1e-4f);
        EXPECT_NEAR(tangents[vertex].y, 0.0f, 1e-4f);
        EXPECT_NEAR(tangents[vertex].z, 0.0f, 1e-4f);
        EXPECT_EQ(signs[vertex], 1.0f);
    }
}

TEST(ManyMesh, DetailBakeRejectsTiledUvLayout) {
    Mesh const source = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    Mesh lod = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    for (math::float2& uv: lod.uvs) {
        uv.x *= 3.0f;
    }
    DetailBakeOptions options;
    options.size = 32;
    DetailBakeResult bake;
    EXPECT_FALSE(bakeDetailNormalMap(source, lod, lod.indices, options, &bake));
}

TEST(ManyMesh, DetailBakeAcceptsSmallUvOvershootFromGeneratedVertices) {
    Mesh const source = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    Mesh lod = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    // A QEM generated vertex can blend chart corners and land just outside the atlas. The raster
    // clips to the texture, so a sub-percent overshoot must not disable the whole bake.
    for (math::float2& uv: lod.uvs) {
        uv.x -= 0.005f;
        uv.y += 0.005f;
    }
    DetailBakeOptions normalOptions;
    normalOptions.size = 32;
    DetailBakeResult normal;
    EXPECT_TRUE(bakeDetailNormalMap(source, lod, lod.indices, normalOptions, &normal));

    DetailHeightOptions heightOptions;
    heightOptions.size = 32;
    heightOptions.maximumDistance = 1.0f;
    DetailHeightResult height;
    EXPECT_TRUE(bakeDetailHeightMap(source, lod, lod.indices, heightOptions, &height));
}

TEST(ManyMesh, DetailHeightIsNeutralForIdenticalGeometry) {
    Mesh const mesh = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    DetailHeightOptions options;
    options.size = 64;
    options.dilationTexels = 1;
    options.maximumDistance = 1.0f;
    DetailHeightResult bake;
    ASSERT_TRUE(bakeDetailHeightMap(mesh, mesh, mesh.indices, options, &bake));
    EXPECT_EQ(bake.size, 64u);
    EXPECT_GT(bake.coveredTexels, 0u);
    EXPECT_FLOAT_EQ(bake.minHeight, 0.0f);
    EXPECT_FLOAT_EQ(bake.maxHeight, 0.0f);
    EXPECT_FLOAT_EQ(bake.heightRange, 0.0f);
    for (uint8_t value: bake.values) {
        EXPECT_EQ(value, 128);
    }
}

TEST(ManyMesh, DetailHeightCapturesSignedDisplacement) {
    Mesh const lod = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    DetailHeightOptions options;
    options.size = 64;
    options.dilationTexels = 1;
    options.maximumDistance = 1.0f;

    Mesh source = lod;
    for (math::float3& position: source.positions) {
        position.z = 0.1f;
    }
    DetailHeightResult above;
    ASSERT_TRUE(bakeDetailHeightMap(source, lod, lod.indices, options, &above));
    EXPECT_NEAR(above.minHeight, 0.1f, 1e-4f);
    EXPECT_NEAR(above.maxHeight, 0.1f, 1e-4f);
    EXPECT_NEAR(above.meanAbsHeight, 0.1f, 1e-4f);
    EXPECT_GT(above.recommendedUvScale, 0.0f);
    size_t const center = (size_t(32) * 64 + 32);
    EXPECT_GT(above.values[center], 128);

    for (math::float3& position: source.positions) {
        position.z = -0.1f;
    }
    DetailHeightResult below;
    ASSERT_TRUE(bakeDetailHeightMap(source, lod, lod.indices, options, &below));
    EXPECT_NEAR(below.minHeight, -0.1f, 1e-4f);
    EXPECT_NEAR(below.maxHeight, -0.1f, 1e-4f);
    EXPECT_LT(below.values[center], 128);
}

TEST(ManyMesh, DetailHeightRejectsTiledUvAndDistantDisplacement) {
    Mesh const source = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    Mesh lod = makeBakeQuad({ 0.0f, 0.0f, 1.0f });
    DetailHeightOptions options;
    options.size = 32;
    DetailHeightResult bake;

    for (math::float2& uv: lod.uvs) {
        uv.x *= 3.0f;
    }
    EXPECT_FALSE(bakeDetailHeightMap(source, lod, lod.indices, options, &bake));

    lod = source;
    lod.positions[0].z = 1.0f;
    lod.positions[1].z = 1.0f;
    lod.positions[2].z = 1.0f;
    lod.positions[3].z = 1.0f;
    options.maximumDistance = 0.01f;
    EXPECT_FALSE(bakeDetailHeightMap(source, lod, lod.indices, options, &bake));
}

TEST(ManyMesh, ShadingNormalsMergeSeamDuplicates) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 0.0f, 0.0f },
    };
    float const angle = 15.0f * 3.14159265358979323846f / 180.0f;
    mesh.normals = {
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, std::sin(angle), std::cos(angle) },
    };
    mesh.indices = { 0, 1, 2, 3, 1, 2 };

    ShadingNormalOptions options;
    options.creaseAngleDegrees = 25.0f;
    ShadingNormalResult result;
    repairShadingNormals(&mesh, mesh.indices, options, &result);

    EXPECT_EQ(result.duplicateVertices, 1u);
    EXPECT_EQ(result.mergedClusters, 1u);
    EXPECT_EQ(result.changedVertices, 2u);
    EXPECT_NEAR(mesh.normals[0].x, mesh.normals[3].x, 1e-5f);
    EXPECT_NEAR(mesh.normals[0].y, mesh.normals[3].y, 1e-5f);
    EXPECT_NEAR(mesh.normals[0].z, mesh.normals[3].z, 1e-5f);
    EXPECT_NEAR(mesh.normals[0].y, std::sin(angle * 0.5f), 2e-3f);
    EXPECT_NEAR(mesh.normals[0].z, std::cos(angle * 0.5f), 2e-3f);
}

TEST(ManyMesh, ShadingNormalsKeepHardEdges) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 0.0f, 0.0f },
    };
    mesh.normals = {
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 1.0f, 0.0f },
    };
    mesh.indices = { 0, 1, 2, 3, 1, 2 };

    ShadingNormalOptions options;
    options.creaseAngleDegrees = 25.0f;
    ShadingNormalResult result;
    repairShadingNormals(&mesh, mesh.indices, options, &result);

    EXPECT_EQ(result.mergedClusters, 0u);
    EXPECT_NEAR(mesh.normals[0].z, 1.0f, 1e-5f);
    EXPECT_NEAR(mesh.normals[3].y, 1.0f, 1e-5f);
}

TEST(ManyMesh, ShadingNormalsStrengthBlendsHalfway) {
    Mesh mesh;
    mesh.positions = {
        { 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f },
        { 0.0f, 0.0f, 0.0f },
    };
    float const angle = 20.0f * 3.14159265358979323846f / 180.0f;
    mesh.normals = {
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, 0.0f, 1.0f },
        { 0.0f, std::sin(angle), std::cos(angle) },
    };
    mesh.indices = { 0, 1, 2, 3, 1, 2 };

    ShadingNormalOptions options;
    options.creaseAngleDegrees = 30.0f;
    options.strength = 0.5f;
    ShadingNormalResult result;
    repairShadingNormals(&mesh, mesh.indices, options, &result);

    EXPECT_EQ(result.mergedClusters, 1u);
    // Half of the way from each source normal toward the 10 degree cluster mean.
    EXPECT_NEAR(mesh.normals[0].y, std::sin(angle * 0.25f), 2e-3f);
    EXPECT_NEAR(mesh.normals[0].z, std::cos(angle * 0.25f), 2e-3f);
    EXPECT_NEAR(mesh.normals[3].y, std::sin(angle * 0.75f), 2e-3f);
    EXPECT_NEAR(mesh.normals[3].z, std::cos(angle * 0.75f), 2e-3f);
}

TEST(ManyMesh, ShadingStrengthRecommendationFadesIn) {
    EXPECT_FLOAT_EQ(recommendedShadingNormalStrength(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(recommendedShadingNormalStrength(0.25f), 0.0f);
    EXPECT_NEAR(recommendedShadingNormalStrength(0.625f), 0.25f, 1e-6f);
    EXPECT_FLOAT_EQ(recommendedShadingNormalStrength(1.0f), 0.5f);
    EXPECT_FLOAT_EQ(recommendedShadingNormalStrength(100.0f), 0.5f);
}

TEST(ManyMesh, ShadingCompensationWeightFadesInWithScreenError) {
    EXPECT_FLOAT_EQ(recommendedShadingCompensationWeight(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(recommendedShadingCompensationWeight(0.25f), 0.0f);
    EXPECT_NEAR(recommendedShadingCompensationWeight(0.625f), 0.5f, 1e-6f);
    EXPECT_FLOAT_EQ(recommendedShadingCompensationWeight(1.0f), 1.0f);
    EXPECT_FLOAT_EQ(recommendedShadingCompensationWeight(100.0f), 1.0f);
}

TEST(ManyMesh, ShadingCompensationPresetFollowsTheMeasuredLadder) {
    ShadingCompensationPreset const low =
            recommendedShadingCompensationPreset(0.3966f, true);
    EXPECT_FALSE(low.useAmbientOcclusion);
    EXPECT_TRUE(low.enableMsaa);
    EXPECT_EQ(low.msaaSamples, 4);
    EXPECT_FLOAT_EQ(low.normalCreaseDegrees, 10.0f);
    EXPECT_TRUE(low.autoNormalStrength);
    EXPECT_FLOAT_EQ(low.normalStrength, 0.5f);

    ShadingCompensationPreset const high = recommendedShadingCompensationPreset(0.50f, true);
    EXPECT_TRUE(high.useAmbientOcclusion);
    EXPECT_FLOAT_EQ(high.ambientOcclusionStrength, 0.5f);
    EXPECT_FALSE(high.enableMsaa);
    EXPECT_FLOAT_EQ(high.normalCreaseDegrees, 10.0f);
    EXPECT_TRUE(high.autoNormalStrength);

    EXPECT_FALSE(recommendedShadingCompensationPreset(0.4499f, true).useAmbientOcclusion);
    EXPECT_TRUE(recommendedShadingCompensationPreset(0.45f, true).useAmbientOcclusion);

    ShadingCompensationPreset const noMaterial =
            recommendedShadingCompensationPreset(0.70f, false);
    EXPECT_FALSE(noMaterial.useAmbientOcclusion);
    EXPECT_TRUE(noMaterial.enableMsaa);
    EXPECT_EQ(noMaterial.msaaSamples, 4);
}

TEST(ManyMesh, ShadingNormalsDisabledByZeroCrease) {
    Mesh mesh;
    mesh.positions = { { 0.0f, 0.0f, 0.0f }, { 0.0f, 0.0f, 0.0f } };
    mesh.normals = { { 0.0f, 0.0f, 1.0f }, { 0.0f, 0.2f, 0.98f } };
    mesh.indices = { 0, 1, 0 };

    ShadingNormalOptions options;
    options.creaseAngleDegrees = 0.0f;
    ShadingNormalResult result;
    repairShadingNormals(&mesh, mesh.indices, options, &result);

    EXPECT_EQ(result.duplicateVertices, 0u);
    EXPECT_NEAR(mesh.normals[1].y, 0.2f, 1e-6f);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
