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
#include <manymesh/AttributeSimplifier.h>
#include <manymesh/GeometryError.h>
#include <manymesh/GpuLod.h>
#include <manymesh/Grouper.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/Quality.h>
#include <manymesh/Simplifier.h>
#include <manymesh/Streaming.h>
#include <manymesh/VisibilityBuffer.h>

#include <math/vec3.h>

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
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

std::set<std::pair<uint32_t, uint32_t>> boundaryEdgeSet(
        std::vector<uint32_t> const& indices) {
    std::map<std::pair<uint32_t, uint32_t>, int> edgeUse;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const v[3] = { indices[i], indices[i + 1], indices[i + 2] };
        for (int e = 0; e < 3; ++e) {
            edgeUse[{ std::min(v[e], v[(e + 1) % 3]),
                    std::max(v[e], v[(e + 1) % 3]) }] += 1;
        }
    }
    std::set<std::pair<uint32_t, uint32_t>> result;
    for (auto const& [edge, count] : edgeUse) {
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

    for (Cluster const& cluster : clusters.clusters) {
        bool inFirstChart = false;
        bool inSecondChart = false;
        for (uint32_t index : cluster.indices) {
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
    EXPECT_GE(groups.clusters.size(),
            (clusters.clusters.size() + groupSize - 1) / groupSize);
    EXPECT_LE(groups.clusters.size(), clusters.clusters.size());

    // The merged sphere has to contain every vertex of the group, otherwise selection would
    // under estimate how close the unit comes to the camera.
    for (size_t g = 0; g < groups.clusters.size(); ++g) {
        Sphere const& group = groups.clusters[g].bounds;
        for (uint32_t index : groups.clusters[g].indices) {
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

    for (Cluster const& group : groups.clusters) {
        bool first = false;
        bool second = false;
        for (uint32_t index : group.indices) {
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
    for (Cluster const& cluster : clusters.clusters) {
        memberBorderTotal += borderVertices(cluster.indices).size();
    }
    size_t groupBorderTotal = 0;
    for (Cluster const& group : groups.clusters) {
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
                { float(tile % 2) * 60.0f, float(tile / 2) * 60.0f, float(tile) * 4.0f },
                1.0f, 0.8f);
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
        for (ClusterLods const& unit : lods) {
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
        for (ClusterLods const& unit : lods) {
            level = level == 0 ? unit.levels.size() : std::min(level, unit.levels.size());
        }
        return level;
    };
    size_t const level = std::min(commonLevel(alone), commonLevel(grouped)) - 1;
    ASSERT_GE(level, 1u);

    auto totalTrianglesAtLevel = [level](std::vector<ClusterLods> const& lods) {
        uint64_t triangles = 0;
        for (ClusterLods const& unit : lods) {
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
        0, 1, 2,
        0, 1, 2,  // duplicate
        0, 0, 3,  // degenerate
        1, 2, 3,
        1, 2, 3,  // duplicate that also makes edge 1-2 non-manifold
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
    simplifyIndices(mesh, mesh.indices,
            (mesh.indices.size() / 2 / 3) * 3, options, &level);
    ASSERT_TRUE(level.simplified);
    EXPECT_LT(level.indices.size(), mesh.indices.size());
    EXPECT_EQ(boundaryEdgeSet(level.indices), boundaryEdgeSet(mesh.indices));
    EXPECT_EQ(level.topology.flippedTriangles, 0u);
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
    for (Cluster const& cluster : clusters.clusters) {
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
        for (LodLevel const& level : lods[c].levels) {
            EXPECT_EQ(level.materialId, clusters.clusters[c].materialId);
            EXPECT_EQ(level.submeshId, clusters.clusters[c].submeshId);
        }
    }

    std::vector<LodLevel> const chain = simplifyChain(mesh, options);
    ASSERT_FALSE(chain.empty());
    for (LodLevel const& level : chain) {
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
        for (uint32_t child : graph.nodes[node].children) {
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
    for (uint32_t leaf : graph.leaves) {
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
    for (uint32_t node : selection.nodes) {
        uint32_t parent = graph.nodes[node].parent;
        while (parent != UINT32_MAX) {
            EXPECT_EQ(selected.count(parent), 0u);
            parent = graph.nodes[parent].parent;
        }
    }
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
            ? double(selection.selectedTriangles)
                    / double(graph.baseTriangles - selection.culledTriangles)
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
    for (size_t i = 0; i < graph.nodes.size(); ++i) {
        EXPECT_EQ(restored.nodes[i].children, graph.nodes[i].children);
        EXPECT_EQ(restored.nodes[i].indices, graph.nodes[i].indices);
        EXPECT_FLOAT_EQ(restored.nodes[i].accumulatedError, graph.nodes[i].accumulatedError);
        EXPECT_EQ(restored.nodes[i].topology.boundaryEdges,
                graph.nodes[i].topology.boundaryEdges);
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
    std::vector<LodStreamingPage> const pages = streaming.planPages(512);
    ASSERT_FALSE(pages.empty());
    for (LodStreamingPage const& page : pages) {
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
    for (uint32_t node : selection.nodes) {
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
    std::vector<GpuDrawIndexedIndirectCommand> const draws = buildIndirectDraws(gpu, selection);
    EXPECT_EQ(draws.size(), selection.nodes.size());

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
            EXPECT_LT(visibility.triangleIds[pixel],
                    gpu.indices.size() / 3);
            EXPECT_EQ(visibility.materialIds[pixel], graph.nodes[cluster].materialId);
            EXPECT_EQ(visibility.submeshIds[pixel], graph.nodes[cluster].submeshId);
        }
    }
    EXPECT_TRUE(sawCluster);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
