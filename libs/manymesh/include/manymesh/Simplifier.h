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

    //! Fraction of the mesh extent that this simplification moved the surface by (meshopt's
    //! own metric, before scaling).
    float relativeError = 0.0f;

    //! The same error in world units, i.e. relativeError * relativeToWorldScale(mesh).
    float worldError = 0.0f;

    size_t triangleCount() const noexcept { return indices.size() / 3; }
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
    std::vector<LodLevel> levels;  //!< levels[0] is the cluster's original triangles
};

std::vector<ClusterLods> simplifyClusters(Mesh const& mesh, ClusterSet const& clusters,
        SimplifyOptions const& options = {});

/**
 * The factor that converts meshoptimizer's relative error into world units
 * (meshopt_simplifyScale). Multiply a relative error by this to get an absolute one.
 */
float relativeToWorldScale(Mesh const& mesh) noexcept;

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_SIMPLIFIER_H
