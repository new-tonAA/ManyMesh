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

#ifndef TNT_MANYMESH_LODGRAPH_H
#define TNT_MANYMESH_LODGRAPH_H

#include <manymesh/Cluster.h>
#include <manymesh/Clusterizer.h>
#include <manymesh/GeometryError.h>
#include <manymesh/Mesh.h>
#include <manymesh/Simplifier.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * One node of a hierarchical cluster DAG.
 *
 * Level 0 nodes are the original clusters. A node at level L+1 groups several level L nodes and
 * stores a mesh simplified from their union. `indices` always reference the original vertex
 * buffer, so a selection can mix levels freely without re-uploading vertices.
 */
struct LodGraphNode {
    uint32_t level = 0;
    uint32_t parent = UINT32_MAX;
    std::vector<uint32_t> children;
    std::vector<uint32_t> indices;
    Sphere bounds;
    Cone cone;
    uint32_t materialId = UINT32_MAX;
    uint32_t submeshId = UINT32_MAX;

    //! Error introduced by replacing the children with this node, in world units.
    float selfError = 0.0f;

    //! Worst error on the path from the leaves to this node. Selection uses this value so that
    //! a coarse ancestor cannot hide an error accumulated lower in the hierarchy.
    float accumulatedError = 0.0f;

    TopologyStats topology;
    AttributeStats attributes;
    bool simplified = false;

    //! Triangle count of the original leaves under this node, used for culled accounting.
    uint64_t baseTriangles = 0;

    size_t triangleCount() const noexcept { return indices.size() / 3; }
};

struct LodGraph {
    std::vector<LodGraphNode> nodes;
    std::vector<uint32_t> roots;
    std::vector<uint32_t> leaves;
    uint32_t levelCount = 0;
    uint64_t baseTriangles = 0;
};

struct LodGraphOptions {
    ClusterizeOptions clusterize;

    //! Number of child nodes merged into one parent at each hierarchy level.
    uint32_t clustersPerNode = 8;

    //! Total number of hierarchy levels including the leaves.
    uint32_t levels = 5;

    //! Fraction of the children's triangle count the parent should keep.
    float ratio = 0.5f;

    //! Used for every parent simplification. Border locking is important here: a parent must
    //! not move the vertices it shares with a sibling.
    SimplifyOptions simplify;
};

/**
 * Builds a hierarchical cluster DAG from the input mesh.
 *
 * Every level groups spatially adjacent nodes that share material/submesh, simplifies the
 * group as one unit, and links it to its children. A group that cannot be simplified safely is
 * not promoted, which keeps the DAG free of broken geometry while leaving the children
 * selectable.
 */
LodGraph buildLodGraph(Mesh const& mesh, LodGraphOptions const& options = {});

struct LodGraphSelection {
    //! Selected DAG nodes. Their index lists are disjoint and together cover exactly the part
    //! of the mesh that survives the camera frustum.
    std::vector<uint32_t> nodes;
    std::vector<uint32_t> indices;
    std::vector<uint32_t> materialIds;
    std::vector<uint32_t> submeshIds;

    std::vector<float> screenErrorPerNode;
    std::vector<uint32_t> nodesPerLevel;
    std::vector<uint64_t> trianglesPerLevel;

    uint64_t baseTriangles = 0;
    uint64_t selectedTriangles = 0;
    uint64_t culledTriangles = 0;
};

/**
 * The runtime-facing half of a selection: which DAG nodes to draw and their triangle counts,
 * without concatenating every node's index list.
 *
 * A renderer keeps each node's indices in one shared buffer and turns this cut into indirect
 * draws. Avoiding the per-triangle index/material arrays makes the per-frame cost proportional
 * to the number of visited DAG nodes rather than to the number of selected triangles.
 */
struct LodGraphCut {
    std::vector<uint32_t> nodes;
    std::vector<float> screenErrorPerNode;
    std::vector<uint32_t> nodesPerLevel;
    std::vector<uint64_t> trianglesPerLevel;
    uint64_t baseTriangles = 0;
    uint64_t selectedTriangles = 0;
    uint64_t culledTriangles = 0;
};

LodGraphCut selectLodGraphCut(LodGraph const& graph, ViewCamera const& camera,
        float thresholdPx);

/**
 * Picks a non-overlapping cut through the DAG: a node is drawn either whole or replaced by its
 * children, never both. The coarsest node whose accumulated screen error fits `thresholdPx`
 * wins, which is the hierarchy's best quality for that triangle budget.
 */
LodGraphSelection selectLodGraph(LodGraph const& graph, ViewCamera const& camera,
        float thresholdPx);

/**
 * Finds the smallest screen-error threshold that reaches `targetTriangleRatio`, then returns
 * that cut. This is the tier/slider entry point: the caller asks for a saving level and gets
 * the most detailed cut that still meets it.
 */
LodGraphSelection selectLodGraphAtRatio(LodGraph const& graph, ViewCamera const& camera,
        float targetTriangleRatio, float maxThresholdPx);

enum class LodTier {
    MaximumQuality,
    Balanced,
    Aggressive,
};

struct LodTierProfile {
    char const* name;
    float targetTriangleRatio;
    float maxScreenErrorPx;
};

LodTierProfile lodTierProfile(LodTier tier) noexcept;

LodGraphSelection selectLodGraphTier(LodGraph const& graph, ViewCamera const& camera,
        LodTier tier);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_LODGRAPH_H
