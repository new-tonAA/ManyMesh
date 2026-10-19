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

#ifndef TNT_MANYMESH_GROUPER_H
#define TNT_MANYMESH_GROUPER_H

#include <manymesh/Cluster.h>
#include <manymesh/Mesh.h>

#include <stdint.h>

namespace filament {
namespace manymesh {

struct GroupOptions {
    //! Number of clusters merged into one simplification unit. 1 disables grouping.
    uint32_t clustersPerGroup = 1;
};

/**
 * Merges spatially adjacent clusters into larger units.
 *
 * Simplifying clusters on their own is expensive in quality terms: with the border locked, a
 * cluster can only remove triangles inside its own patch, and the error it accumulates cannot
 * be redistributed the way a global simplification would. Measured on a 7.2M triangle scan,
 * independent clusters paid 4.6x the error of a global chain for 36% more triangles.
 *
 * Merging neighbours before simplifying removes most of that penalty. The border lock then
 * only applies to the *group's* outer boundary: edges the members share become interior to
 * the group and are free to collapse, so the error budget can be spent where the group can
 * actually spare it. This is the idea Nanite calls a cluster group.
 *
 * Clusters are connected through shared vertex indices, so groups cannot jump across an
 * attribute seam or between disconnected components. Starting from a seed, each group grows
 * toward its nearest unassigned neighbour, which keeps the members connected and spatially
 * compact instead of relying on meshlet output order.
 *
 * The result is a ClusterSet like any other, so everything downstream — simplification, screen
 * space error, selection, the error map — works on groups unchanged. The trade-off is that
 * selection granularity becomes the group: a group has one error, not one per member.
 */
ClusterSet groupClusters(ClusterSet const& clusters, GroupOptions const& options = {});

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_GROUPER_H
