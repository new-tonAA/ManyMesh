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

#ifndef TNT_MANYMESH_QUALITY_H
#define TNT_MANYMESH_QUALITY_H

#include <manymesh/Mesh.h>

#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * Topology and triangle-shape measurements for one index list.
 *
 * `boundaryEdges` exists in the source mesh as well (open meshes are legal), so quality gates
 * compare a simplified level against its own base instead of requiring a closed surface.
 * Duplicate and degenerate triangles are counted before the edge histogram is built; they are
 * never useful output geometry and inflate apparent coverage.
 */
struct TopologyStats {
    uint64_t triangles = 0;
    uint64_t uniqueTriangles = 0;
    uint64_t edges = 0;
    uint64_t boundaryEdges = 0;
    uint64_t nonManifoldEdges = 0;
    uint64_t duplicateTriangles = 0;
    uint64_t degenerateTriangles = 0;
    //! Triangles whose geometric normal opposes the source vertex normals at their corners.
    //! This catches folds produced by an over-aggressive collapse even when the edge histogram
    //! still looks manifold.
    uint64_t flippedTriangles = 0;
    float minTriangleQuality = 1.0f;
    float meanTriangleQuality = 1.0f;
};

/**
 * Attribute loss measured on the vertices of a source unit.
 *
 * For every source vertex we find the closest vertex retained by the simplified index list and
 * compare its normal and UV. This is intentionally a conservative validation metric rather
 * than a replacement for meshoptimizer's position QEM: it answers "did the collapse remove a
 * vertex whose normal or UV a renderer would visibly miss?", not "is the surface exact?".
 */
struct AttributeStats {
    float meanNormalErrorRadians = 0.0f;
    float maxNormalErrorRadians = 0.0f;
    float meanUvError = 0.0f;
    float maxUvError = 0.0f;
    uint32_t samples = 0;

    //! True when the metric used nearest retained vertices instead of closest points on the
    //! simplified triangles. Large meshes use this path to keep validation affordable.
    bool approximated = false;

    //! Reference vertex and simplified triangle that produced the maxima. These are diagnostic
    //! only; they let a verbose quality-gate report identify a seam or chart outlier without
    //! changing the measured values or the acceptance decision.
    uint32_t worstNormalVertex = UINT32_MAX;
    uint32_t worstNormalTriangle = UINT32_MAX;
    uint32_t worstUvVertex = UINT32_MAX;
    uint32_t worstUvTriangle = UINT32_MAX;
};

/**
 * One-sided geometric error between a source index list and a simplified one: for every
 * sampled source vertex, the distance to the closest point on the simplified surface.
 */
struct PositionStats {
    float meanError = 0.0f;
    float maxError = 0.0f;
    uint32_t samples = 0;
    bool approximated = false;
};

/**
 * Position and attribute loss from one shared closest-triangle query.
 *
 * The quality gate needs both metrics for the same candidate. Measuring them separately built
 * the same acceleration structure twice and repeated every nearest-point query.
 */
struct CandidateErrorStats {
    PositionStats position;
    AttributeStats attributes;
};

/**
 * The reference vertices for repeated candidate measurements.
 *
 * A simplification unit evaluates several candidates against the same source triangle list.
 * Extracting, sorting and sampling those source vertices once per unit avoids repeating that
 * work for every candidate and every quality-gate retry.
 */
struct CandidateReference {
    std::vector<uint32_t> vertices;
};

CandidateReference makeCandidateReference(
        std::vector<uint32_t> const& referenceIndices, uint32_t maxSamples = 0);

TopologyStats measureTopology(Mesh const& mesh, std::vector<uint32_t> const& indices);

/**
 * Same topology metrics, but vertices that share an exact position are welded first.
 *
 * Use this for any mesh whose index list may contain attribute-chart splits (UV/normal seams)
 * or generated vertices. An id-based boundary count reports a false boundary down every seam;
 * the welded count answers whether the rendered surface actually has a hole.
 */
TopologyStats measureWeldedTopology(Mesh const& mesh, std::vector<uint32_t> const& indices);

AttributeStats measureAttributeError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices);

/**
 * Same metric with explicit sampling and approximation controls.
 *
 * `maxSamples` limits how many reference vertices are checked (0 checks all of them).
 * `approximateTriangles` selects the nearest-vertex path once the simplified index list has
 * more triangles than this; pass 0 to always use the exact closest-triangle search.
 */
AttributeStats measureAttributeError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices,
        uint32_t maxSamples,
        size_t approximateTriangles);

PositionStats measurePositionError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices,
        uint32_t maxSamples = 0,
        size_t approximateTriangles = 0);

CandidateErrorStats measureCandidateErrors(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices,
        uint32_t maxSamples = 0,
        size_t approximateTriangles = 0);

CandidateErrorStats measureCandidateErrors(Mesh const& mesh,
        CandidateReference const& reference,
        std::vector<uint32_t> const& simplifiedIndices,
        size_t approximateTriangles = 0);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_QUALITY_H
