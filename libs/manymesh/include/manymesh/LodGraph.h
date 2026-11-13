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

    //! Attribute vertices added by `SimplifyOptions::cornerSimplify`. Node indices at or above
    //! the source vertex count reference this array, exactly as described in CornerSimplifier.h.
    //! The builder globally deduplicates them, so a cut can mix levels and still share one
    //! vertex buffer.
    std::vector<GeneratedVertex> generatedVertices;

    //! Canonical position id for every vertex, including generated vertices. Vertices that
    //! occupy exactly the same position share an id. Cut assembly uses it to drop faces that two
    //! nodes produced from different attribute vertices at the same location.
    std::vector<uint32_t> positionIds;

    //! Number of vertices the node index lists may reference, including generatedVertices.
    uint32_t vertexCount = 0;
    uint32_t levelCount = 0;
    uint64_t baseTriangles = 0;

    //! Size of the original source vertex buffer: vertexCount - generatedVertices.size().
    uint32_t sourceVertexCount() const noexcept {
        size_t const generated = generatedVertices.size();
        return vertexCount >= generated ? vertexCount - uint32_t(generated) : 0;
    }
};

//! Observations, not causal labels. Profiles count gate rejections across all backoff attempts.
struct LodGroupObservation {
    uint32_t level = 0;
    uint32_t trial = 0; //!< Zero: production build; otherwise a diagnostic partition id.
    std::vector<uint32_t> members;
    std::vector<uint32_t> inputIndices;
    std::vector<uint32_t> lockedVertices; //!< Explicit mask; lockBorder also applies in simplifier.
    uint64_t inputTriangles = 0;
    uint64_t outputTriangles = 0;
    float accumulatedError = 0;
    bool promoted = false;
    SimplifyProfile profile;
};

struct LodRegroupObservation {
    uint32_t level = 0;
    uint32_t trial = 0;
    uint64_t baselineTriangles = 0;
    uint64_t candidateTriangles = 0;
    float baselineError = 0;
    float candidateError = 0;
    //! Screening result only: fewer assembled faces, same boundary, no nonmanifold edges,
    //! and no increase in maximum accumulated error. Does not identify a causal blocked edge.
    bool improves = false;
};

//! Caller-owned, reset at build entry. No trial geometry is committed or serialized.
struct LodGraphDiagnostics {
    std::vector<LodGroupObservation> groups;
    std::vector<LodRegroupObservation> trials;
    uint64_t trialInputTriangles = 0;
    double trialSeconds = 0;
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

    //! Optional detailed ledger and read-only local counterfactuals. Requires qualityGate.
    LodGraphDiagnostics* diagnostics = nullptr;

    //! Additional input-triangle work budget for the whole build; zero records only the ledger.
    uint64_t diagnosticTriangleBudget = 0;
};

/**
 * Optional build-time measurements. They are not serialized with the graph; they exist so a
 * tool or test can tell whether clustering, per-cluster chains, or group merging dominates.
 */
struct LodGraphBuildStats {
    double clusterizeSeconds = 0.0;
    double leafSetupSeconds = 0.0;
    double clusterChainSeconds = 0.0;
    double groupBuildSeconds = 0.0;
    double groupSimplifySeconds = 0.0;
    double totalSeconds = 0.0;

    uint64_t clusterSimplifyCalls = 0;
    uint64_t clusterSimplifyAccepted = 0;
    uint64_t clusterSimplifyAttempts = 0;
    uint64_t groupCandidates = 0;
    uint64_t groupSimplifyCalls = 0;
    uint64_t groupSimplifyAccepted = 0;
    uint64_t groupSimplifyAttempts = 0;
    uint64_t seamLockedVertices = 0;
    uint64_t generatedVertices = 0;

    SimplifyProfile clusterSimplify;
    SimplifyProfile groupSimplify;
};

/**
 * Builds a hierarchical cluster DAG from the input mesh.
 *
 * Every level groups spatially adjacent nodes that share material/submesh, simplifies the
 * group as one unit, and links it to its children. A group that cannot be simplified safely is
 * not promoted, which keeps the DAG free of broken geometry while leaving the children
 * selectable.
 */
LodGraph buildLodGraph(Mesh const& mesh, LodGraphOptions const& options = {},
        LodGraphBuildStats* stats = nullptr);

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
 * A selected cut whose generated-vertex tail has been compacted to what the cut actually uses.
 *
 * Node index lists reference one global vertex space: the source vertices followed by every
 * generated vertex any simplification produced. A cut typically touches only a fraction of
 * those generated vertices, yet a renderer that uploads the global space pays for all of them.
 * By default this structure keeps source ids unchanged, copies the referenced generated
 * vertices into a dense tail in first-use order, and rewrites every generated index
 * accordingly. LodGraphCompactOptions::compactSourceVertices additionally compacts the source
 * range, so a committed cut can be uploaded as one densely packed buffer.
 *
 * The input selection must already be assembled (and position-deduplicated), as returned by
 * selectLodGraph(). Compaction is O(indices + generatedVertices) and allocation-light, but it
 * still rewrites the index list; use it when a cut is committed, not for every candidate cut in
 * a slider search.
 */

struct LodGraphCompactOptions {
    //! Also compact the source vertex range to the vertices the cut references. The default
    //! keeps source ids unchanged so a renderer can keep its original source buffer. Turn this
    //! on when a cut is committed and the renderer uploads a dedicated cut buffer; then the
    //! upload scales with the visible cut instead of the whole imported mesh.
    bool compactSourceVertices = false;
};
struct LodGraphCutGeometry {
    std::vector<uint32_t> indices;

    //! Generated vertices referenced by the cut, in first-use order.
    std::vector<GeneratedVertex> generatedVertices;

    //! Index into LodGraph::generatedVertices for every entry of generatedVertices. A renderer
    //! that keeps the full source attribute buffer can use this to gather positions, normals,
    //! UVs and ambient occlusion without searching or comparing floating-point attributes.
    std::vector<uint32_t> generatedSourceIds;

    //! Index into the original source buffer for every entry of the compact source range.
    //! Empty means the source range was not compacted and source ids are unchanged.
    std::vector<uint32_t> sourceVertexIds;

    uint32_t sourceVertexCount = 0;

    uint32_t vertexCount = 0;

    uint32_t triangles = 0;
};

LodGraphCutGeometry compactLodSelection(LodGraph const& graph, LodGraphSelection const& selection,
        LodGraphCompactOptions const& options = {});

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

LodGraphCut selectLodGraphCut(LodGraph const& graph, ViewCamera const& camera, float thresholdPx);

/**
 * Replaces `cut` while retaining its vector capacities for subsequent frames. Once the buffers
 * fit the selected nodes and graph levels, selection performs no heap allocations. The same
 * output may be reused with another graph; all counts and lists are reset on every call.
 * Concurrent callers must supply separate outputs.
 */
void selectLodGraphCut(LodGraph const& graph, ViewCamera const& camera, float thresholdPx,
        LodGraphCut& cut);

/**
 * Picks a non-overlapping cut through the DAG: a node is drawn either whole or replaced by its
 * children, never both. The coarsest node whose accumulated screen error fits `thresholdPx`
 * wins, which is the hierarchy's best quality for that triangle budget.
 */
LodGraphSelection selectLodGraph(LodGraph const& graph, ViewCamera const& camera,
        float thresholdPx);

/**
 * Assembles a render selection from node ids chosen by another selector, such as a compute
 * shader traversing the flattened GpuLodBuffer. The node set must already form a valid,
 * non-overlapping DAG cut; this function applies the same cross-node triangle deduplication and
 * per-node screen-error bookkeeping as selectLodGraph().
 *
 * `culledTriangles` is optional accounting for subtrees the caller culled while selecting.
 * Passing a node id outside the graph, or a node that is not part of `graph`, is ignored.
 */
LodGraphSelection assembleLodSelection(LodGraph const& graph, ViewCamera const& camera,
        std::vector<uint32_t> nodes, uint64_t culledTriangles = 0);

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

LodGraphSelection selectLodGraphTier(LodGraph const& graph, ViewCamera const& camera, LodTier tier);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_LODGRAPH_H
