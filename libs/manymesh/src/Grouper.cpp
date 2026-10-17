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

#include <manymesh/Grouper.h>

#include <algorithm>
#include <queue>
#include <utility>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

//! Smallest sphere containing both inputs. Standard pairwise merge of two spheres.
Sphere mergeSpheres(Sphere const& a, Sphere const& b) {
    float const distance = length(b.center - a.center);

    if (distance + b.radius <= a.radius) {
        return a;  // b is inside a
    }
    if (distance + a.radius <= b.radius) {
        return b;  // a is inside b
    }
    if (!(distance > 0.0f)) {
        return a;  // concentric, the radius check above already covered the larger one
    }

    Sphere result;
    result.radius = (distance + a.radius + b.radius) * 0.5f;
    result.center = a.center + (b.center - a.center) * ((result.radius - a.radius) / distance);
    return result;
}

//! Cone that contains both inputs: the widest of the two, which is the smallest cutoff.
Cone mergeCones(Cone const& a, Cone const& b) {
    math::float3 const axis = a.axis + b.axis;
    float const axisLength = length(axis);

    Cone result;
    result.apex = a.apex;
    result.axis = axisLength > 0.0f ? axis / axisLength : a.axis;
    result.cutoff = std::min(a.cutoff, b.cutoff);
    return result;
}

} // anonymous namespace

ClusterSet groupClusters(ClusterSet const& clusters, GroupOptions const& options) {
    ClusterSet result = clusters;

    if (options.clustersPerGroup <= 1 || clusters.clusters.empty()) {
        return result;
    }

    size_t const groupSize = options.clustersPerGroup;
    size_t const clusterCount = clusters.clusters.size();

    // Build the cluster adjacency graph from shared vertices. Two clusters that share a vertex
    // are spatially connected; chaining the owners of each vertex links all clusters that meet
    // there, without an edge hash table proportional to the whole triangle count.
    uint32_t maxVertex = 0;
    for (Cluster const& cluster : clusters.clusters) {
        for (uint32_t index : cluster.indices) {
            maxVertex = std::max(maxVertex, index);
        }
    }

    std::vector<int32_t> lastOwner(size_t(maxVertex) + 1, -1);
    std::vector<std::vector<uint32_t>> neighbors(clusterCount);
    std::vector<uint32_t> vertices;
    for (size_t c = 0; c < clusterCount; ++c) {
        vertices = clusters.clusters[c].indices;
        std::sort(vertices.begin(), vertices.end());
        vertices.erase(std::unique(vertices.begin(), vertices.end()), vertices.end());

        for (uint32_t vertex : vertices) {
            int32_t const previous = lastOwner[vertex];
            if (previous >= 0 && size_t(previous) != c) {
                neighbors[c].push_back(uint32_t(previous));
                neighbors[size_t(previous)].push_back(uint32_t(c));
            }
            lastOwner[vertex] = int32_t(c);
        }
    }

    for (std::vector<uint32_t>& list : neighbors) {
        std::sort(list.begin(), list.end());
        list.erase(std::unique(list.begin(), list.end()), list.end());
    }

    // Grow each group from a seed, always taking the closest unassigned neighbour. This keeps
    // groups connected and spatially compact, instead of merging arbitrary runs of clusters.
    std::vector<uint8_t> assigned(clusterCount, 0);
    result.clusters.clear();
    result.clusters.reserve(clusterCount);

    using Candidate = std::pair<float, uint32_t>;
    std::priority_queue<Candidate, std::vector<Candidate>, std::greater<Candidate>> candidates;

    for (size_t seed = 0; seed < clusterCount; ++seed) {
        if (assigned[seed] != 0) {
            continue;
        }

        std::vector<uint32_t> members;
        members.push_back(uint32_t(seed));
        assigned[seed] = 1;

        auto enqueueNeighbors = [&](uint32_t c) {
            for (uint32_t neighbor : neighbors[c]) {
                if (assigned[neighbor] != 0) {
                    continue;
                }
                if (clusters.clusters[neighbor].materialId != clusters.clusters[c].materialId
                        || clusters.clusters[neighbor].submeshId
                                != clusters.clusters[c].submeshId) {
                    continue;
                }
                math::float3 const delta = clusters.clusters[neighbor].bounds.center
                        - clusters.clusters[c].bounds.center;
                candidates.emplace(dot(delta, delta), neighbor);
            }
        };

        enqueueNeighbors(uint32_t(seed));

        while (members.size() < groupSize && !candidates.empty()) {
            uint32_t const next = candidates.top().second;
            candidates.pop();
            if (assigned[next] != 0) {
                continue;
            }
            assigned[next] = 1;
            members.push_back(next);
            enqueueNeighbors(next);
        }

        // Drop candidates left over from this group. The next seed rebuilds its own frontier,
        // and stale entries would otherwise leak across groups.
        while (!candidates.empty()) {
            candidates.pop();
        }

        Cluster group;
        size_t triangleCount = 0;
        for (uint32_t member : members) {
            triangleCount += clusters.clusters[member].indices.size();
        }
        group.indices.reserve(triangleCount);

        group.bounds = clusters.clusters[members[0]].bounds;
        group.cone = clusters.clusters[members[0]].cone;
        group.materialId = clusters.clusters[members[0]].materialId;
        group.submeshId = clusters.clusters[members[0]].submeshId;
        group.indices.insert(group.indices.end(),
                clusters.clusters[members[0]].indices.begin(),
                clusters.clusters[members[0]].indices.end());

        for (size_t i = 1; i < members.size(); ++i) {
            Cluster const& member = clusters.clusters[members[i]];
            group.bounds = mergeSpheres(group.bounds, member.bounds);
            group.cone = mergeCones(group.cone, member.cone);
            group.indices.insert(group.indices.end(),
                    member.indices.begin(), member.indices.end());
        }

        result.clusters.push_back(std::move(group));
    }

    return result;
}

} // namespace manymesh
} // namespace filament
