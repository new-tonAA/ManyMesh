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

#include <manymesh/LodGraph.h>

#include <gtest/gtest.h>

#include <vector>

using namespace filament::manymesh;

namespace {

LodGraph makeRuntimeGraph() {
    LodGraph graph;
    graph.vertexCount = 8;
    graph.levelCount = 2;
    graph.baseTriangles = 4;
    graph.nodes.resize(3);
    graph.roots = { 0 };
    graph.leaves = { 1, 2 };
    auto& root = graph.nodes[0];
    root.level = 1;
    root.children = { 1, 2 };
    root.indices = { 0, 4, 7 };
    root.bounds = { { 0.0f, 0.0f, -10.0f }, 2.0f };
    root.accumulatedError = 1.0f;
    root.baseTriangles = 4;
    for (uint32_t child: graph.leaves) {
        auto& node = graph.nodes[child];
        node.parent = 0;
        node.bounds = { { 0.0f, 0.0f, -10.0f }, 1.0f };
        node.accumulatedError = 0.01f;
        node.baseTriangles = 2;
    }
    graph.nodes[1].indices = { 0, 1, 2, 0, 2, 3 };
    graph.nodes[2].indices = { 4, 5, 6, 4, 6, 7 };
    return graph;
}

ViewCamera makeRuntimeCamera() {
    ViewCamera camera;
    camera.eye = { 0.0f, 0.0f, 0.0f };
    camera.target = { 0.0f, 0.0f, -1.0f };
    camera.fovY = 1.5707963f;
    camera.screenWidth = 1000;
    camera.screenHeight = 1000;
    camera.near = 0.01f;
    camera.far = 10000.0f;
    return camera;
}

void expectMatchesFullSelection(LodGraph const& graph, ViewCamera const& camera,
        LodGraphCut const& cut) {
    auto const full = selectLodGraph(graph, camera, 2.0f);
    EXPECT_EQ(cut.nodes, full.nodes);
    EXPECT_EQ(cut.screenErrorPerNode, full.screenErrorPerNode);
    EXPECT_EQ(cut.nodesPerLevel, full.nodesPerLevel);
    EXPECT_EQ(cut.trianglesPerLevel, full.trianglesPerLevel);
    EXPECT_EQ(cut.baseTriangles, full.baseTriangles);
    EXPECT_EQ(cut.selectedTriangles, full.selectedTriangles);
    EXPECT_EQ(cut.culledTriangles, full.culledTriangles);
}

} // namespace

TEST(ManyMesh, ReusedRuntimeCutTracksCameraAndResetsCounts) {
    auto const graph = makeRuntimeGraph();
    auto camera = makeRuntimeCamera();
    LodGraphCut cut;
    for (int frame = 0; frame < 3; ++frame) {
        camera.eye.z = 0.0f;
        camera.target.z = -1.0f;
        selectLodGraphCut(graph, camera, 2.0f, cut);
        EXPECT_EQ(cut.nodes, (std::vector<uint32_t>{ 1, 2 }));
        EXPECT_EQ(cut.selectedTriangles, 4u);
        EXPECT_EQ(cut.culledTriangles, 0u);
        expectMatchesFullSelection(graph, camera, cut);

        camera.eye.z = 1000.0f;
        selectLodGraphCut(graph, camera, 2.0f, cut);
        EXPECT_EQ(cut.nodes, (std::vector<uint32_t>{ 0 }));
        EXPECT_EQ(cut.selectedTriangles, 1u);
        expectMatchesFullSelection(graph, camera, cut);

        camera.target.z = 1001.0f;
        selectLodGraphCut(graph, camera, 2.0f, cut);
        EXPECT_TRUE(cut.nodes.empty());
        EXPECT_TRUE(cut.screenErrorPerNode.empty());
        EXPECT_EQ(cut.selectedTriangles, 0u);
        EXPECT_EQ(cut.culledTriangles, 4u);
        expectMatchesFullSelection(graph, camera, cut);
    }
}

TEST(ManyMesh, ReusedRuntimeCutRetainsBuffersAfterWarmup) {
    auto const graph = makeRuntimeGraph();
    auto camera = makeRuntimeCamera();
    LodGraphCut cut;
    selectLodGraphCut(graph, camera, 2.0f, cut);
    auto const* nodes = cut.nodes.data();
    auto const* errors = cut.screenErrorPerNode.data();
    auto const* levels = cut.nodesPerLevel.data();
    auto const* triangles = cut.trianglesPerLevel.data();
    for (int frame = 0; frame < 12; ++frame) {
        camera.eye.z = frame % 3 == 0 ? 0.0f : 1000.0f;
        camera.target.z = frame % 3 == 2 ? 1001.0f : -1.0f;
        selectLodGraphCut(graph, camera, 2.0f, cut);
        EXPECT_EQ(cut.nodes.data(), nodes);
        EXPECT_EQ(cut.screenErrorPerNode.data(), errors);
        EXPECT_EQ(cut.nodesPerLevel.data(), levels);
        EXPECT_EQ(cut.trianglesPerLevel.data(), triangles);
    }
}

TEST(ManyMesh, ReusedRuntimeCutCanSwitchGraphs) {
    auto graph = makeRuntimeGraph();
    auto const camera = makeRuntimeCamera();
    LodGraphCut cut;
    selectLodGraphCut(graph, camera, 2.0f, cut);
    selectLodGraphCut({}, camera, 2.0f, cut);
    EXPECT_TRUE(cut.nodes.empty());
    EXPECT_TRUE(cut.screenErrorPerNode.empty());
    EXPECT_TRUE(cut.nodesPerLevel.empty());
    EXPECT_TRUE(cut.trianglesPerLevel.empty());
    EXPECT_EQ(cut.baseTriangles, 0u);
    EXPECT_EQ(cut.selectedTriangles, 0u);
    EXPECT_EQ(cut.culledTriangles, 0u);

    graph.nodes.resize(1);
    graph.nodes[0].level = 0;
    graph.nodes[0].children.clear();
    graph.nodes[0].baseTriangles = 1;
    graph.levelCount = 1;
    graph.baseTriangles = 1;
    graph.leaves = { 0 };
    selectLodGraphCut(graph, camera, 2.0f, cut);
    EXPECT_EQ(cut.nodes, (std::vector<uint32_t>{ 0 }));
    EXPECT_EQ(cut.baseTriangles, 1u);
    EXPECT_EQ(cut.nodesPerLevel, (std::vector<uint32_t>{ 1 }));
    EXPECT_EQ(cut.trianglesPerLevel, (std::vector<uint64_t>{ 1 }));
    expectMatchesFullSelection(graph, camera, cut);

    graph = makeRuntimeGraph();
    selectLodGraphCut(graph, camera, 2.0f, cut);
    expectMatchesFullSelection(graph, camera, cut);
}

TEST(ManyMesh, ReusedRuntimeCutPreservesInvalidCameraFallback) {
    auto const graph = makeRuntimeGraph();
    auto camera = makeRuntimeCamera();
    LodGraphCut cut;
    selectLodGraphCut(graph, camera, 2.0f, cut);
    camera.target = camera.eye;
    selectLodGraphCut(graph, camera, 2.0f, cut);
    EXPECT_EQ(cut.nodes, (std::vector<uint32_t>{ 0 }));
    EXPECT_EQ(cut.screenErrorPerNode, (std::vector<float>{ 0.0f }));
    expectMatchesFullSelection(graph, camera, cut);
}
