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

#ifndef TNT_MANYMESH_CLUSTERIZER_H
#define TNT_MANYMESH_CLUSTERIZER_H

#include <manymesh/Cluster.h>
#include <manymesh/Mesh.h>

#include <stdint.h>

namespace filament {
namespace manymesh {

struct ClusterizeOptions {
    //! meshopt_buildMeshlets hard limits: maxVertices <= 255 and maxTriangles <= 512.
    uint32_t maxVertices = 128;
    uint32_t maxTriangles = 128;

    //! 0 makes clusters purely size driven, 1 makes meshoptimizer favour cone-cullable ones.
    float coneWeight = 0.0f;
};

/**
 * Splits a mesh into clusters (meshlets) and computes their bounding sphere and normal cone.
 *
 * Clusters are the unit of everything that follows: simplification, error measurement and
 * per-view selection. The union of all clusters is exactly the input triangle set, with no
 * duplicates and no omissions.
 */
ClusterSet clusterize(Mesh const& mesh, ClusterizeOptions const& options = {});

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_CLUSTERIZER_H
