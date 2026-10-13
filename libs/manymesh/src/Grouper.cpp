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
    size_t const groupCount = (clusters.clusters.size() + groupSize - 1) / groupSize;

    result.clusters.clear();
    result.clusters.reserve(groupCount);

    for (size_t g = 0; g < groupCount; ++g) {
        size_t const first = g * groupSize;
        size_t const last = std::min(first + groupSize, clusters.clusters.size());

        Cluster group;
        size_t triangleCount = 0;
        for (size_t c = first; c < last; ++c) {
            triangleCount += clusters.clusters[c].indices.size();
        }
        group.indices.reserve(triangleCount);

        for (size_t c = first; c < last; ++c) {
            Cluster const& member = clusters.clusters[c];

            if (c == first) {
                group.bounds = member.bounds;
                group.cone = member.cone;
            } else {
                group.bounds = mergeSpheres(group.bounds, member.bounds);
                group.cone = mergeCones(group.cone, member.cone);
            }

            group.indices.insert(group.indices.end(),
                    member.indices.begin(), member.indices.end());
        }

        result.clusters.push_back(std::move(group));
    }

    return result;
}

} // namespace manymesh
} // namespace filament
