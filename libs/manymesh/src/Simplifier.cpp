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

#include <manymesh/Simplifier.h>

#include <meshoptimizer.h>

#include <algorithm>
#include <cmath>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

// Simplify `source` down to `targetIndexCount` and store the outcome in `out`, filling in
// both the relative error reported by meshoptimizer and its world space equivalent.
void simplifyInto(std::vector<uint32_t> const& source, float const* positions,
        size_t vertexCount, size_t targetIndexCount, float targetError, unsigned int options,
        float worldScale, LodLevel* out) {
    // meshopt_simplify requires room for index_count elements in the destination, not for
    // target_index_count: it can stop anywhere between the two.
    std::vector<uint32_t> destination(source.size());
    float resultError = 0.0f;

    size_t const resultCount = meshopt_simplify(destination.data(), source.data(), source.size(),
            positions, vertexCount, sizeof(math::float3),
            targetIndexCount, targetError, options, &resultError);

    destination.resize(resultCount);
    out->indices = std::move(destination);
    out->relativeError = resultError;
    out->worldError = resultError * worldScale;
}

// Number of triangles to aim for at a given level of a chain rooted at `baseTriangles`.
size_t targetIndexCountForLevel(size_t baseIndexCount, uint32_t level, float ratio) {
    double const fraction = std::pow(double(ratio), double(level));
    size_t target = size_t(double(baseIndexCount) * fraction);
    return (target / 3) * 3;
}

/**
 * Simplify one cluster.
 *
 * meshopt_simplify sizes its working memory from `vertex_count`, not from how many vertices
 * the indices actually reference. Handing it the whole mesh's vertex buffer for a cluster of
 * 128 triangles would make it allocate and initialise a quadric per vertex of the entire
 * model — on a seven million triangle scan that is a few hundred megabytes, per cluster, per
 * level. Clusters therefore get a compacted vertex buffer of their own, and the result is
 * mapped back to the shared one.
 *
 * `remap` is scratch space reused across clusters: it maps a mesh vertex to its index in the
 * current cluster's local buffer, or -1 when unused. Only the vertices the cluster actually
 * touched are reset, so the cost stays proportional to the cluster, not to the mesh.
 */
void simplifyClusterInto(std::vector<uint32_t> const& source, Mesh const& mesh,
        std::vector<int32_t>* remap, size_t targetIndexCount, float targetError,
        unsigned int options, LodLevel* out) {
    std::vector<math::float3> localPositions;
    std::vector<uint32_t> localToGlobal;
    std::vector<uint32_t> localIndices(source.size());

    localPositions.reserve(source.size());
    localToGlobal.reserve(source.size());

    for (size_t i = 0; i < source.size(); ++i) {
        uint32_t const global = source[i];
        int32_t& local = (*remap)[global];
        if (local < 0) {
            local = int32_t(localPositions.size());
            localPositions.push_back(mesh.positions[global]);
            localToGlobal.push_back(global);
        }
        localIndices[i] = uint32_t(local);
    }

    std::vector<uint32_t> destination(localIndices.size());
    float resultError = 0.0f;

    size_t const resultCount = meshopt_simplify(destination.data(), localIndices.data(),
            localIndices.size(), &localPositions[0].x, localPositions.size(),
            sizeof(math::float3), targetIndexCount, targetError, options, &resultError);

    out->indices.resize(resultCount);
    for (size_t i = 0; i < resultCount; ++i) {
        out->indices[i] = localToGlobal[destination[i]];
    }

    // meshoptimizer reports error relative to the extent of the buffer it was handed, so the
    // conversion to world units has to use the *cluster's* scale, not the whole mesh's. Using
    // the global one would overstate every cluster's error by the ratio of the two extents.
    float const localScale = meshopt_simplifyScale(&localPositions[0].x, localPositions.size(),
            sizeof(math::float3));
    out->relativeError = resultError;
    out->worldError = resultError * localScale;

    for (uint32_t global : localToGlobal) {
        (*remap)[global] = -1;
    }
}

} // anonymous namespace

float relativeToWorldScale(Mesh const& mesh) noexcept {
    if (mesh.positions.empty()) {
        return 1.0f;
    }
    return meshopt_simplifyScale(&mesh.positions[0].x, mesh.positions.size(),
            sizeof(math::float3));
}

std::vector<LodLevel> simplifyChain(Mesh const& mesh, SimplifyOptions const& options) {
    std::vector<LodLevel> levels;

    if (mesh.empty() || options.levels == 0) {
        return levels;
    }

    float const worldScale = relativeToWorldScale(mesh);
    float const* const positions = &mesh.positions[0].x;
    size_t const vertexCount = mesh.positions.size();

    levels.resize(1);
    levels[0].indices = mesh.indices;

    for (uint32_t level = 1; level < options.levels; ++level) {
        size_t const target = targetIndexCountForLevel(mesh.indices.size(), level, options.ratio);
        if (target == 0 || target >= mesh.indices.size()) {
            break;
        }

        LodLevel next;
        // Every level is simplified from the original geometry rather than from the previous
        // level. It costs one extra pass but yields better quality, and it makes the reported
        // error absolute with respect to the input instead of relative to an intermediate.
        simplifyInto(mesh.indices, positions, vertexCount, target, options.targetError, 0,
                worldScale, &next);

        if (next.indices.size() >= levels.back().indices.size()) {
            break;  // no further progress is possible, stop instead of emitting duplicates
        }
        levels.push_back(std::move(next));
    }

    return levels;
}

std::vector<ClusterLods> simplifyClusters(Mesh const& mesh, ClusterSet const& clusters,
        SimplifyOptions const& options) {
    std::vector<ClusterLods> result(clusters.clusters.size());

    if (mesh.empty() || options.levels == 0) {
        return result;
    }

    float const worldScale = relativeToWorldScale(mesh);
    unsigned int const flags = options.lockBorder ? meshopt_SimplifyLockBorder : 0;

    // One remap scratch buffer for the whole run: allocating it per cluster would cost more
    // than the simplification itself for small clusters.
    std::vector<int32_t> remap(mesh.positions.size(), -1);

    for (size_t c = 0; c < clusters.clusters.size(); ++c) {
        std::vector<uint32_t> const& base = clusters.clusters[c].indices;
        ClusterLods& lods = result[c];

        lods.levels.resize(1);
        lods.levels[0].indices = base;

        if (base.empty()) {
            continue;
        }

        for (uint32_t level = 1; level < options.levels; ++level) {
            size_t const target = targetIndexCountForLevel(base.size(), level, options.ratio);
            if (target == 0 || target >= base.size()) {
                break;
            }

            LodLevel next;
            simplifyClusterInto(base, mesh, &remap, target, options.targetError, flags, &next);

            if (next.indices.size() >= lods.levels.back().indices.size()) {
                break;
            }
            lods.levels.push_back(std::move(next));
        }
    }

    return result;
}

} // namespace manymesh
} // namespace filament
