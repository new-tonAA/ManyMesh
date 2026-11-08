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

#include <manymesh/ShadingNormals.h>

#include <algorithm>
#include <cmath>

#include <stdint.h>

namespace filament {
namespace manymesh {

namespace {

inline math::float3 normalizedOr(math::float3 value, math::float3 fallback) noexcept {
    float const length2 = dot(value, value);
    return length2 > 1e-20f ? value * (1.0f / std::sqrt(length2)) : fallback;
}

inline float cornerAngle(math::float3 const& origin, math::float3 const& a,
        math::float3 const& b) noexcept {
    math::float3 const u = a - origin;
    math::float3 const v = b - origin;
    float const u2 = dot(u, u);
    float const v2 = dot(v, v);
    if (u2 < 1e-20f || v2 < 1e-20f) {
        return 0.0f;
    }
    float const cosine = dot(u, v) / std::sqrt(u2 * v2);
    return std::acos(std::clamp(cosine, -1.0f, 1.0f));
}

struct PositionKey {
    int64_t x = 0;
    int64_t y = 0;
    int64_t z = 0;
    uint32_t vertex = 0;

    bool operator<(PositionKey const& other) const noexcept {
        if (x != other.x) {
            return x < other.x;
        }
        if (y != other.y) {
            return y < other.y;
        }
        if (z != other.z) {
            return z < other.z;
        }
        return vertex < other.vertex;
    }
};

int64_t quantize(float value, float epsilon) noexcept {
    double const scaled = double(value) / double(epsilon);
    // The clamp is only a guard against pathological coordinates; normal assets never get near
    // this range. Keeping the key in int64 avoids collisions without hashing.
    return int64_t(std::clamp(scaled, -9.0e18, 9.0e18));
}

struct Cluster {
    math::float3 sum{};
    float weight = 0.0f;
    math::float3 mean{};
    std::vector<uint32_t> members;
};

} // namespace

float recommendedShadingNormalStrength(float screenErrorPx) noexcept {
    constexpr float kInvisibleErrorPx = 0.25f;
    constexpr float kFullRecommendationPx = 1.0f;
    constexpr float kMeasuredOptimum = 0.5f;
    if (!(screenErrorPx > kInvisibleErrorPx)) {
        return 0.0f;
    }
    if (screenErrorPx >= kFullRecommendationPx) {
        return kMeasuredOptimum;
    }
    float const t = (screenErrorPx - kInvisibleErrorPx) /
                    (kFullRecommendationPx - kInvisibleErrorPx);
    float const smooth = t * t * (3.0f - 2.0f * t);
    return kMeasuredOptimum * smooth;
}

float recommendedShadingCompensationWeight(float screenErrorPx) noexcept {
    constexpr float kInvisibleErrorPx = 0.25f;
    constexpr float kFullRecommendationPx = 1.0f;
    if (!(screenErrorPx > kInvisibleErrorPx)) {
        return 0.0f;
    }
    if (screenErrorPx >= kFullRecommendationPx) {
        return 1.0f;
    }
    float const t = (screenErrorPx - kInvisibleErrorPx) /
                    (kFullRecommendationPx - kInvisibleErrorPx);
    return t * t * (3.0f - 2.0f * t);
}

ShadingCompensationPreset recommendedShadingCompensationPreset(float retainedRatio,
        bool hasCompensationMaterial) noexcept {
    constexpr float kAoThreshold = 0.45f;
    constexpr float kMeasuredAoStrength = 0.5f;
    constexpr float kMeasuredCreaseDegrees = 10.0f;
    constexpr float kMeasuredNormalStrength = 0.5f;

    ShadingCompensationPreset preset;
    preset.normalCreaseDegrees = kMeasuredCreaseDegrees;
    preset.autoNormalStrength = true;
    preset.normalStrength = kMeasuredNormalStrength;
    if (hasCompensationMaterial && retainedRatio >= kAoThreshold) {
        preset.useAmbientOcclusion = true;
        preset.ambientOcclusionStrength = kMeasuredAoStrength;
        return preset;
    }
    preset.enableMsaa = true;
    preset.msaaSamples = 4;
    return preset;
}

void repairShadingNormals(Mesh* mesh, std::vector<uint32_t> const& indices,
        ShadingNormalOptions const& options, ShadingNormalResult* result) {
    ShadingNormalResult stats;
    if (result != nullptr) {
        *result = stats;
    }
    if (mesh == nullptr || !mesh->hasNormals() || mesh->positions.empty() ||
            options.creaseAngleDegrees <= 0.0f) {
        return;
    }

    size_t const vertexCount = mesh->positions.size();
    float epsilon = options.positionEpsilon;
    if (epsilon <= 0.0f) {
        math::float3 lo = mesh->positions[0];
        math::float3 hi = mesh->positions[0];
        for (math::float3 const& p: mesh->positions) {
            lo = min(lo, p);
            hi = max(hi, p);
        }
        float const diagonal = length(hi - lo);
        epsilon = std::max(diagonal * 1e-6f, 1e-7f);
    }

    std::vector<PositionKey> keys(vertexCount);
    for (uint32_t vertex = 0; vertex < vertexCount; ++vertex) {
        math::float3 const& p = mesh->positions[vertex];
        keys[vertex] = { quantize(p.x, epsilon), quantize(p.y, epsilon), quantize(p.z, epsilon),
            vertex };
    }
    std::sort(keys.begin(), keys.end());

    std::vector<float> weights(vertexCount, 0.0f);
    for (size_t triangle = 0; triangle + 2 < indices.size(); triangle += 3) {
        uint32_t const i0 = indices[triangle + 0];
        uint32_t const i1 = indices[triangle + 1];
        uint32_t const i2 = indices[triangle + 2];
        if (i0 >= vertexCount || i1 >= vertexCount || i2 >= vertexCount) {
            continue;
        }
        math::float3 const& p0 = mesh->positions[i0];
        math::float3 const& p1 = mesh->positions[i1];
        math::float3 const& p2 = mesh->positions[i2];
        weights[i0] += cornerAngle(p0, p1, p2);
        weights[i1] += cornerAngle(p1, p2, p0);
        weights[i2] += cornerAngle(p2, p0, p1);
    }

    float const creaseAngle = std::clamp(options.creaseAngleDegrees, 0.0f, 89.0f);
    float const cosineThreshold = std::cos(creaseAngle * 3.14159265358979323846f / 180.0f);
    float const strength = std::clamp(options.strength, 0.0f, 1.0f);

    for (size_t begin = 0; begin < keys.size();) {
        size_t end = begin + 1;
        while (end < keys.size() && keys[end].x == keys[begin].x && keys[end].y == keys[begin].y &&
                keys[end].z == keys[begin].z) {
            ++end;
        }
        size_t const groupSize = end - begin;
        if (groupSize > 1) {
            stats.duplicateVertices += groupSize - 1;
            std::vector<Cluster> clusters;
            for (size_t i = begin; i < end; ++i) {
                uint32_t const vertex = keys[i].vertex;
                math::float3 const normal = normalizedOr(mesh->normals[vertex], {});
                if (dot(normal, normal) < 0.5f) {
                    continue;
                }
                float const weight = std::max(weights[vertex], 1e-6f);
                size_t best = clusters.size();
                float bestDot = -2.0f;
                for (size_t c = 0; c < clusters.size(); ++c) {
                    float const meanDot = dot(clusters[c].mean, normal);
                    if (meanDot < cosineThreshold || meanDot <= bestDot) {
                        continue;
                    }
                    // A chain of small angles must not average across a real crease. Compare
                    // against the members as well as the running mean.
                    bool fits = true;
                    if (clusters[c].members.size() <= 32) {
                        for (uint32_t member: clusters[c].members) {
                            math::float3 const memberNormal =
                                    normalizedOr(mesh->normals[member], {});
                            if (dot(memberNormal, normal) < cosineThreshold) {
                                fits = false;
                                break;
                            }
                        }
                    }
                    if (fits) {
                        best = c;
                        bestDot = meanDot;
                    }
                }
                if (best == clusters.size()) {
                    Cluster cluster;
                    cluster.sum = normal * weight;
                    cluster.weight = weight;
                    cluster.mean = normal;
                    cluster.members.push_back(vertex);
                    clusters.push_back(std::move(cluster));
                } else {
                    Cluster& cluster = clusters[best];
                    cluster.sum += normal * weight;
                    cluster.weight += weight;
                    cluster.mean = normalizedOr(cluster.sum, cluster.mean);
                    cluster.members.push_back(vertex);
                }
            }

            for (Cluster const& cluster: clusters) {
                if (cluster.members.size() < 2) {
                    continue;
                }
                math::float3 const replacement = normalizedOr(cluster.sum, cluster.mean);
                stats.mergedClusters += 1;
                for (uint32_t vertex: cluster.members) {
                    math::float3 const old = normalizedOr(mesh->normals[vertex], replacement);
                    math::float3 const blended =
                            normalizedOr(old * (1.0f - strength) + replacement * strength, old);
                    float const angle = std::acos(std::clamp(dot(old, blended), -1.0f, 1.0f)) *
                                        57.29577951308232f;
                    if (angle > 1e-3f) {
                        stats.changedVertices += 1;
                        stats.maxMergedAngleDegrees = std::max(stats.maxMergedAngleDegrees, angle);
                    }
                    mesh->normals[vertex] = blended;
                }
            }
        }
        begin = end;
    }

    if (result != nullptr) {
        *result = stats;
    }
}

} // namespace manymesh
} // namespace filament
