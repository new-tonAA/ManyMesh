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
#include <manymesh/GeometryError.h>
#include <manymesh/Mesh.h>
#include <manymesh/Simplifier.h>

#include <math/vec3.h>

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <map>
#include <set>
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
            mesh.positions.push_back(origin + math::float3{
                    float(i) * spacing, float(j) * spacing, z });
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
    destination->positions.insert(destination->positions.end(),
            source.positions.begin(), source.positions.end());
    for (uint32_t index : source.indices) {
        destination->indices.push_back(offset + index);
    }
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
    for (Cluster const& cluster : clusters.clusters) {
        for (size_t i = 0; i + 2 < cluster.indices.size(); i += 3) {
            Triangle triangle = { cluster.indices[i], cluster.indices[i + 1], cluster.indices[i + 2] };
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
    for (auto const& [edge, count] : edgeUse) {
        if (count == 1) {
            result.insert(edge.first);
            result.insert(edge.second);
        }
    }
    return result;
}

double meanLevel(std::vector<uint32_t> const& levels, std::vector<size_t> const& clusterIndices) {
    if (clusterIndices.empty()) {
        return 0.0;
    }
    double total = 0.0;
    for (size_t index : clusterIndices) {
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
    camera.fovY = 1.5707963f;  // 90 degrees, so tan(fov/2) == 1
    camera.screenHeight = 1000;

    // pixelsPerRadian == 1000 / (2 * 1) == 500, so a unit error at depth 10 covers 50 pixels.
    EXPECT_NEAR(screenSpaceError(1.0f, { 0.0f, 0.0f, -10.0f }, camera), 50.0f, 0.01f);
    EXPECT_NEAR(screenSpaceError(1.0f, { 0.0f, 0.0f, -20.0f }, camera), 25.0f, 0.01f);
    EXPECT_NEAR(screenSpaceError(2.0f, { 0.0f, 0.0f, -10.0f }, camera), 100.0f, 0.01f);
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

        for (uint32_t vertex : border) {
            EXPECT_TRUE(present.count(vertex) > 0)
                    << "cluster " << c << " lost border vertex " << vertex;
        }
        checked += 1;
    }

    EXPECT_GT(checked, 0u);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
