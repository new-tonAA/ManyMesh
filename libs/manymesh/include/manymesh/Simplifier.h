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

#ifndef TNT_MANYMESH_SIMPLIFIER_H
#define TNT_MANYMESH_SIMPLIFIER_H

#include <manymesh/Cluster.h>
#include <manymesh/Mesh.h>
#include <manymesh/Quality.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * One simplified version of a piece of geometry, together with the error it introduced.
 *
 * Indices always reference the *original* Mesh vertex buffer, whichever level they belong
 * to. Levels therefore share one vertex buffer and differ only in their index list, which
 * keeps the whole LOD chain cheap to hold in memory and trivial to compare.
 */
struct LodLevel {
    std::vector<uint32_t> indices;

    //! Material/submesh of every triangle in this level when the whole level belongs to one
    //! primitive. UINT32_MAX means "mixed"; use materialIds/submeshIds in that case.
    uint32_t materialId = UINT32_MAX;
    uint32_t submeshId = UINT32_MAX;

    //! Optional per-triangle primitives, either empty or triangleCount() long. Cluster and
    //! group levels are uniform and only fill the scalar fields; a global chain that spans
    //! several materials fills these vectors instead.
    std::vector<uint32_t> materialIds;
    std::vector<uint32_t> submeshIds;

    //! Fraction of the mesh extent that this simplification moved the surface by (meshopt's
    //! own metric, before scaling).
    float relativeError = 0.0f;

    //! The same error in world units, i.e. relativeError * relativeToWorldScale(mesh).
    float worldError = 0.0f;

    //! Topology and triangle-shape measurements of this level.
    TopologyStats topology;

    //! Normal and UV loss relative to the unit's level 0 geometry.
    AttributeStats attributes;

    //! How many simplification attempts the quality gate needed to accept this level.
    uint32_t attempts = 1;

    //! False when no safe simplification was possible and level 0 was kept.
    bool simplified = false;

    size_t triangleCount() const noexcept { return indices.size() / 3; }
};

/**
 * Optional diagnostics for one or more simplification runs. All fields accumulate, so a caller
 * can reuse one profile for a whole DAG build. This is deliberately separate from the LOD data:
 * it lets a tool answer "is the attribute QEM, meshopt, or the quality gate the bottleneck?"
 * without changing the simplification results.
 */
struct SimplifyProfile {
    double attributeQemSeconds = 0.0;
    double meshoptSeconds = 0.0;
    double candidateGateSeconds = 0.0;
    double boundaryCheckSeconds = 0.0;
    double lockedMaskSeconds = 0.0;
    uint64_t calls = 0;
    uint64_t attempts = 0;
    uint64_t attributeCandidates = 0;
    uint64_t meshoptCandidates = 0;
    uint64_t accepted = 0;
};

struct SimplifyOptions {
    //! Total number of levels *including* level 0, which is always the input geometry.
    uint32_t levels = 5;

    //! Fraction of the previous level's triangle count that each new level keeps.
    float ratio = 0.7f;

    //! Relative error ceiling handed to meshopt_simplify. It is a cap, not a target: the
    //! simplifier stops early rather than exceeding it, so coarse levels may end up with
    //! more triangles than requested.
    float targetError = 1e-2f;

    //! Per-cluster mode only: prevent the simplifier from moving border vertices. Clusters
    //! are simplified independently, so without this their shared seams would crack open.
    //! The cost is that border triangles can never be removed.
    bool lockBorder = true;

    //! Optional global-vertex mask (mesh.positions.size() long). A set entry marks a vertex
    //! shared with a different unit. Such vertices are treated exactly like border vertices:
    //! they are never removed and no collapse may rewrite an edge through them. The graph
    //! builder uses this to keep independently simplified clusters from creating a chord
    //! across the seam they share. The caller must keep the mask alive for the call.
    std::vector<uint8_t> const* lockedVertices = nullptr;

    //! Allow a UV/normal seam to collapse when both copies of the seam vertex move to the
    //! corresponding pair of neighbours in one step. Duplicated positions are paired by exact
    //! position and matching boundary edges, so the two attribute charts shrink together
    //! instead of one side opening a crack. This is used by cluster-group simplification,
    //! where both sides of an internal seam are present in the same unit. It never relaxes
    //! the boundary lock for an open edge that has no paired neighbour.
    bool seamCollapse = false;

    //! Compare every candidate against the base unit and retry with a larger triangle budget
    //! when the collapse produced a crack, a non-manifold edge, a duplicate/degenerate face or
    //! an attribute jump beyond the limits below. This is what keeps an extreme LOD from
    //! trading a few triangles for a visible hole.
    bool qualityGate = true;

    //! How many times to back off toward the base triangle count before giving up.
    uint32_t qualityAttempts = 4;

    //! Minimum normalized triangle quality. 1 is equilateral; 0 is degenerate. Thin folded
    //! triangles are the source of shading slivers even when the surface has no hole.
    float minTriangleQuality = 0.02f;

    //! Attribute limits for the quality gate. Normals are in degrees, UVs in texture units.
    float maxNormalErrorDegrees = 35.0f;
    float maxUvError = 0.10f;

    //! Relative weights used when ranking failing candidates. Higher weights make the gate
    //! prefer a less reduced level with better normals/UVs.
    float normalWeight = 1.0f;
    float uvWeight = 1.0f;

    //! Print the reason a candidate was rejected. Intended for tuning the offline profiles.
    bool verbose = false;

    //! Run an attribute-aware QEM pass (position + normal + UV quadrics) on units small enough
    //! to afford it. This is what makes normals and UVs part of the collapse decision rather
    //! than only a post-hoc validation. Large global chains fall back to meshoptimizer's
    //! position-only QEM plus the quality gate.
    bool attributeQem = true;

    //! Maximum number of triangles in a unit that the attribute-aware pass is allowed to see.
    //! Cluster groups are far below this; a seven million triangle global chain is far above.
    size_t attributeQemMaxTriangles = 200000;

    //! Weights of the position, normal and UV terms in the attribute-aware cost. Position is
    //! normalized by the unit's extent before weighting, so all three terms are dimensionless.
    float attributePositionWeight = 1.0f;
    float attributeNormalWeight = 1.0f;
    float attributeUvWeight = 1.0f;

    //! Cap the number of reference vertices used by the post-simplification attribute gate.
    //! 0 means "all of them"; large global chains should use a few thousand samples.
    uint32_t attributeSampleLimit = 4096;

    //! Above this many simplified triangles the gate compares against the nearest retained
    //! vertex instead of searching every triangle for the closest point. That keeps a
    //! multi-million triangle chain from turning validation into an O(V*T) operation.
    size_t attributeApproximationTriangles = 250000;
};

/**
 * Classic global LOD chain: level 0 is the mesh itself and every following level is obtained
 * by simplifying the previous one. This is the "distance based LOD" baseline.
 */
std::vector<LodLevel> simplifyChain(Mesh const& mesh, SimplifyOptions const& options = {});

/**
 * Per-cluster LOD: each cluster gets a chain of its own.
 *
 * This is what makes ManyMesh's error map possible. Because clusters are simplified in
 * isolation, the error a level introduces is local to that cluster, and a view can later
 * choose a different level per cluster instead of one level for the whole mesh.
 */
struct ClusterLods {
    std::vector<LodLevel> levels; //!< levels[0] is the cluster's original triangles
};

std::vector<ClusterLods> simplifyClusters(Mesh const& mesh, ClusterSet const& clusters,
        SimplifyOptions const& options = {}, SimplifyProfile* profile = nullptr);

/**
 * Simplifies one arbitrary index list to `targetIndexCount` and records the resulting level.
 * This is the building block of the hierarchical LOD graph: a parent node is just a group of
 * child indices simplified as one unit.
 */
void simplifyIndices(Mesh const& mesh, std::vector<uint32_t> const& indices,
        size_t targetIndexCount, SimplifyOptions const& options, LodLevel* out,
        SimplifyProfile* profile = nullptr);

/**
 * The factor that converts meshoptimizer's relative error into world units
 * (meshopt_simplifyScale). Multiply a relative error by this to get an absolute one.
 */
float relativeToWorldScale(Mesh const& mesh) noexcept;

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_SIMPLIFIER_H
