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

#include <manymesh/AmbientOcclusion.h>

#include "Parallel.h"
#include "UvRasterizer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>

namespace filament {
namespace manymesh {

namespace {

using math::float3;
using math::float2;

constexpr float kPi = 3.14159265358979323846f;
constexpr uint32_t kInvalidNode = std::numeric_limits<uint32_t>::max();

inline float3 normalizedOr(float3 value, float3 fallback) noexcept {
    float const length2 = dot(value, value);
    return length2 > 1e-20f ? value * (1.0f / std::sqrt(length2)) : fallback;
}

inline uint32_t hash32(uint32_t value) noexcept {
    value ^= value >> 16;
    value *= 0x7feb352dU;
    value ^= value >> 15;
    value *= 0x846ca68bU;
    value ^= value >> 16;
    return value;
}

inline uint32_t effectiveSampleCount(uint32_t samples) noexcept {
    // Directions are generated in opposite-azimuth pairs. That makes the sum of all directions
    // lie exactly on the normal, so an unoccluded vertex cannot acquire Monte-Carlo tilt.
    return std::max(2u, samples & ~1u);
}

struct Rng {
    uint32_t state = 1;

    explicit Rng(uint32_t seed) noexcept : state(seed == 0 ? 0x9e3779b9U : seed) {}

    float next() noexcept {
        state = state * 1664525U + 1013904223U;
        return float(state >> 8) * (1.0f / 16777216.0f);
    }
};

struct Bounds {
    float3 lo{ std::numeric_limits<float>::max() };
    float3 hi{ std::numeric_limits<float>::lowest() };

    void expand(float3 point) noexcept {
        lo = min(lo, point);
        hi = max(hi, point);
    }

    void expand(Bounds const& bounds) noexcept {
        lo = min(lo, bounds.lo);
        hi = max(hi, bounds.hi);
    }

    bool valid() const noexcept { return hi.x >= lo.x && hi.y >= lo.y && hi.z >= lo.z; }
};

struct Triangle {
    float3 v0{};
    float3 v1{};
    float3 v2{};
    float3 centroid{};
    Bounds bounds;
};

struct BvhNode {
    Bounds bounds;
    uint32_t left = kInvalidNode;
    uint32_t right = kInvalidNode;
    uint32_t first = 0;
    uint32_t count = 0;
};

struct Bvh {
    std::vector<Triangle> triangles;
    std::vector<uint32_t> order;
    std::vector<BvhNode> nodes;

    uint32_t build(uint32_t begin, uint32_t end, uint32_t depth) {
        uint32_t const nodeIndex = uint32_t(nodes.size());
        nodes.push_back({});

        Bounds bounds;
        for (uint32_t i = begin; i < end; ++i) {
            bounds.expand(triangles[order[i]].bounds);
        }
        nodes[nodeIndex].bounds = bounds;

        uint32_t const count = end - begin;
        if (count <= 8 || depth >= 28) {
            nodes[nodeIndex].first = begin;
            nodes[nodeIndex].count = count;
            return nodeIndex;
        }

        Bounds centroids;
        for (uint32_t i = begin; i < end; ++i) {
            centroids.expand(triangles[order[i]].centroid);
        }
        float3 const extent = centroids.hi - centroids.lo;
        int axis = 0;
        if (extent.y > extent.x) {
            axis = 1;
        }
        if ((axis == 0 ? extent.x : extent.y) < extent.z) {
            axis = 2;
        }
        float const axisExtent = axis == 0 ? extent.x : (axis == 1 ? extent.y : extent.z);
        if (axisExtent < 1e-9f) {
            nodes[nodeIndex].first = begin;
            nodes[nodeIndex].count = count;
            return nodeIndex;
        }

        uint32_t const middle = begin + count / 2;
        auto const centroidAxis = [this, axis](uint32_t lhs, uint32_t rhs) {
            float const a = axis == 0 ? triangles[lhs].centroid.x
                                      : (axis == 1 ? triangles[lhs].centroid.y
                                                   : triangles[lhs].centroid.z);
            float const b = axis == 0 ? triangles[rhs].centroid.x
                                      : (axis == 1 ? triangles[rhs].centroid.y
                                                   : triangles[rhs].centroid.z);
            return a < b;
        };
        std::nth_element(order.begin() + begin, order.begin() + middle, order.begin() + end,
                centroidAxis);

        uint32_t const left = build(begin, middle, depth + 1);
        uint32_t const right = build(middle, end, depth + 1);
        nodes[nodeIndex].left = left;
        nodes[nodeIndex].right = right;
        return nodeIndex;
    }
};

inline float safeInverse(float value) noexcept {
    return 1.0f / (std::abs(value) < 1e-20f ? 1e-20f : value);
}

inline bool intersectsBounds(Bounds const& bounds, float3 const& origin,
        float3 const& inverseDirection, float maximumDistance) noexcept {
    float tMin = 0.0f;
    float tMax = maximumDistance;

    auto testAxis = [&](float originAxis, float inverse, float lo, float hi) {
        float const t0 = (lo - originAxis) * inverse;
        float const t1 = (hi - originAxis) * inverse;
        tMin = std::max(tMin, std::min(t0, t1));
        tMax = std::min(tMax, std::max(t0, t1));
    };
    testAxis(origin.x, inverseDirection.x, bounds.lo.x, bounds.hi.x);
    testAxis(origin.y, inverseDirection.y, bounds.lo.y, bounds.hi.y);
    testAxis(origin.z, inverseDirection.z, bounds.lo.z, bounds.hi.z);
    return tMax >= tMin;
}

inline bool intersectsTriangle(Triangle const& triangle, float3 const& origin,
        float3 const& direction, float maximumDistance) noexcept {
    constexpr float kEpsilon = 1e-9f;
    float3 const edge1 = triangle.v1 - triangle.v0;
    float3 const edge2 = triangle.v2 - triangle.v0;
    float3 const p = cross(direction, edge2);
    float const determinant = dot(edge1, p);
    if (std::abs(determinant) < kEpsilon) {
        return false;
    }
    float const inverseDeterminant = 1.0f / determinant;
    float3 const t = origin - triangle.v0;
    float const u = dot(t, p) * inverseDeterminant;
    if (u < -1e-6f || u > 1.0f + 1e-6f) {
        return false;
    }
    float3 const q = cross(t, edge1);
    float const v = dot(direction, q) * inverseDeterminant;
    if (v < -1e-6f || u + v > 1.0f + 1e-6f) {
        return false;
    }
    float const distance = dot(edge2, q) * inverseDeterminant;
    // Anything behind the offset origin is not an occluder. The tiny lower bound rejects the
    // triangle the sample point belongs to without needing per-vertex adjacency.
    return distance > 1e-6f && distance < maximumDistance;
}

bool isOccluded(Bvh const& bvh, float3 const& origin, float3 const& direction,
        float maximumDistance) {
    if (bvh.nodes.empty()) {
        return false;
    }
    float3 const inverseDirection{ safeInverse(direction.x), safeInverse(direction.y),
        safeInverse(direction.z) };

    uint32_t stack[64];
    uint32_t stackSize = 0;
    stack[stackSize++] = 0;
    while (stackSize > 0) {
        BvhNode const& node = bvh.nodes[stack[--stackSize]];
        if (!intersectsBounds(node.bounds, origin, inverseDirection, maximumDistance)) {
            continue;
        }
        if (node.count > 0) {
            for (uint32_t i = 0; i < node.count; ++i) {
                Triangle const& triangle = bvh.triangles[bvh.order[node.first + i]];
                if (intersectsTriangle(triangle, origin, direction, maximumDistance)) {
                    return true;
                }
            }
        } else {
            if (stackSize + 2 <= 64) {
                stack[stackSize++] = node.left;
                stack[stackSize++] = node.right;
            }
        }
    }
    return false;
}

inline float3 closestPointOnTriangle(float3 const& point, Triangle const& triangle) noexcept {
    float3 const a = triangle.v0;
    float3 const b = triangle.v1;
    float3 const c = triangle.v2;
    float3 const ab = b - a;
    float3 const ac = c - a;
    float3 const ap = point - a;
    float const d1 = dot(ab, ap);
    float const d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        return a;
    }

    float3 const bp = point - b;
    float const d3 = dot(ab, bp);
    float const d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        return b;
    }

    float const vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        return a + ab * (d1 / (d1 - d3));
    }

    float3 const cp = point - c;
    float const d5 = dot(ab, cp);
    float const d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        return c;
    }

    float const vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        return a + ac * (d2 / (d2 - d6));
    }

    float const va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)));
    }

    float const denominator = 1.0f / (va + vb + vc);
    float const v = vb * denominator;
    float const w = vc * denominator;
    return a + ab * v + ac * w;
}

inline float distanceSquaredToBounds(Bounds const& bounds, float3 const& point) noexcept {
    float const dx = point.x < bounds.lo.x ? bounds.lo.x - point.x
                                            : (point.x > bounds.hi.x ? point.x - bounds.hi.x : 0.0f);
    float const dy = point.y < bounds.lo.y ? bounds.lo.y - point.y
                                            : (point.y > bounds.hi.y ? point.y - bounds.hi.y : 0.0f);
    float const dz = point.z < bounds.lo.z ? bounds.lo.z - point.z
                                            : (point.z > bounds.hi.z ? point.z - bounds.hi.z : 0.0f);
    return dx * dx + dy * dy + dz * dz;
}

struct ClosestPoint {
    float3 point{};
    float distance2 = std::numeric_limits<float>::max();
};

void findClosestSurfacePoint(Bvh const& bvh, float3 const& point, float maximumDistance2,
        ClosestPoint* closest) {
    if (bvh.nodes.empty()) {
        return;
    }
    uint32_t stack[64];
    uint32_t stackSize = 0;
    stack[stackSize++] = 0;
    while (stackSize > 0) {
        BvhNode const& node = bvh.nodes[stack[--stackSize]];
        if (distanceSquaredToBounds(node.bounds, point) >= closest->distance2) {
            continue;
        }
        if (node.count > 0) {
            for (uint32_t i = 0; i < node.count; ++i) {
                Triangle const& triangle = bvh.triangles[bvh.order[node.first + i]];
                float3 const candidate = closestPointOnTriangle(point, triangle);
                float const distance2 = dot(candidate - point, candidate - point);
                if (distance2 < closest->distance2) {
                    closest->distance2 = distance2;
                    closest->point = candidate;
                    if (distance2 == 0.0f) {
                        return;
                    }
                }
            }
        } else if (stackSize + 2 <= 64) {
            stack[stackSize++] = node.left;
            stack[stackSize++] = node.right;
        }
    }
    if (closest->distance2 > maximumDistance2) {
        closest->distance2 = std::numeric_limits<float>::max();
    }
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

void deriveVertexNormals(Mesh const& mesh, std::vector<float3>* normals) {
    normals->assign(mesh.positions.size(), float3{ 0.0f, 0.0f, 0.0f });
    for (size_t triangle = 0; triangle + 2 < mesh.indices.size(); triangle += 3) {
        uint32_t const i0 = mesh.indices[triangle + 0];
        uint32_t const i1 = mesh.indices[triangle + 1];
        uint32_t const i2 = mesh.indices[triangle + 2];
        if (i0 >= normals->size() || i1 >= normals->size() || i2 >= normals->size()) {
            continue;
        }
        float3 const normal = cross(mesh.positions[i1] - mesh.positions[i0],
                mesh.positions[i2] - mesh.positions[i0]);
        (*normals)[i0] += normal;
        (*normals)[i1] += normal;
        (*normals)[i2] += normal;
    }
    for (float3& normal: *normals) {
        normal = normalizedOr(normal, float3{ 0.0f, 0.0f, 1.0f });
    }
}

bool buildBvh(Mesh const& source, Bvh* bvh, Bounds* sourceBounds) {
    size_t const triangleCount = source.indices.size() / 3;
    bvh->triangles.reserve(triangleCount);
    for (size_t triangle = 0; triangle < triangleCount; ++triangle) {
        uint32_t const i0 = source.indices[triangle * 3 + 0];
        uint32_t const i1 = source.indices[triangle * 3 + 1];
        uint32_t const i2 = source.indices[triangle * 3 + 2];
        if (i0 >= source.positions.size() || i1 >= source.positions.size() ||
                i2 >= source.positions.size()) {
            continue;
        }
        Triangle data;
        data.v0 = source.positions[i0];
        data.v1 = source.positions[i1];
        data.v2 = source.positions[i2];
        data.centroid = (data.v0 + data.v1 + data.v2) * (1.0f / 3.0f);
        data.bounds.expand(data.v0);
        data.bounds.expand(data.v1);
        data.bounds.expand(data.v2);
        sourceBounds->expand(data.bounds);
        bvh->triangles.push_back(data);
    }
    if (bvh->triangles.empty() || !sourceBounds->valid()) {
        return false;
    }
    bvh->order.resize(bvh->triangles.size());
    for (uint32_t i = 0; i < bvh->order.size(); ++i) {
        bvh->order[i] = i;
    }
    bvh->nodes.reserve(bvh->triangles.size() * 2);
    bvh->build(0, uint32_t(bvh->triangles.size()), 0);
    return true;
}

uint32_t sampleVisibility(Bvh const& bvh, float3 const& position, float3 const& normal,
        float radius, float bias, uint32_t samples, uint32_t seed,
        float3* bentNormalSum = nullptr) {
    float3 const axis = std::abs(normal.y) < 0.9f ? float3{ 0.0f, 1.0f, 0.0f }
                                                  : float3{ 1.0f, 0.0f, 0.0f };
    float3 const tangent = normalizedOr(cross(axis, normal), float3{ 1.0f, 0.0f, 0.0f });
    float3 const bitangent = cross(normal, tangent);
    float3 const origin = position + normal * bias;

    uint32_t const sampleCount = effectiveSampleCount(samples);
    uint32_t const pairs = sampleCount / 2;
    Rng rng(hash32(seed));
    float const rotation = 2.0f * kPi * rng.next();
    uint32_t visible = 0;
    for (uint32_t pair = 0; pair < pairs; ++pair) {
        // Cosine-weighted stratified pair. The golden-ratio azimuth keeps successive rings
        // decorrelated, while the opposite ray cancels its tangential contribution exactly.
        float const u1 = (float(pair) + 0.5f) / float(pairs);
        float const r = std::sqrt(u1);
        float const localZ = std::sqrt(std::max(0.0f, 1.0f - u1));
        float const phi = 2.0f * kPi *
                          (0.6180339887498949f * float(pair) + rotation / (2.0f * kPi));
        for (uint32_t side = 0; side < 2; ++side) {
            float const angle = phi + (side == 0 ? 0.0f : kPi);
            float3 const direction = tangent * (r * std::cos(angle)) +
                                     bitangent * (r * std::sin(angle)) + normal * localZ;
            if (!isOccluded(bvh, origin, direction, radius)) {
                ++visible;
                if (bentNormalSum != nullptr) {
                    *bentNormalSum += direction;
                }
            }
        }
    }
    if (bentNormalSum != nullptr && visible == sampleCount) {
        // Remove the last few ulps of pair cancellation. A fully visible vertex has no evidence
        // of a bend, so its result must be the geometric normal exactly.
        *bentNormalSum = normal * float(sampleCount);
    }
    return visible;
}

struct SurfaceTarget {
    std::vector<float3> positions;
    std::vector<float3> normals;
    std::vector<uint8_t> covered;
    uint32_t size = 0;

    void reset(uint32_t texels) {
        size = texels;
        size_t const count = size_t(texels) * texels;
        positions.assign(count, float3{ 0.0f, 0.0f, 0.0f });
        normals.assign(count, float3{ 0.0f, 0.0f, 1.0f });
        covered.assign(count, 0);
    }
};

void rasterizeSurface(Mesh const& mesh, uint32_t size, SurfaceTarget* target) {
    size_t const triangleCount = mesh.indices.size() / 3;
    for (size_t triangle = 0; triangle < triangleCount; ++triangle) {
        uint32_t const i0 = mesh.indices[triangle * 3 + 0];
        uint32_t const i1 = mesh.indices[triangle * 3 + 1];
        uint32_t const i2 = mesh.indices[triangle * 3 + 2];
        math::float2 const uv[3] = { mesh.uvs[i0], mesh.uvs[i1], mesh.uvs[i2] };
        float3 const p[3] = { mesh.positions[i0], mesh.positions[i1], mesh.positions[i2] };
        float3 const n[3] = { mesh.normals[i0], mesh.normals[i1], mesh.normals[i2] };
        detail::rasterizeUvTriangle(uv, size,
                [&](int x, int y, float w0, float w1, float w2) {
                    size_t const texel = size_t(y) * size + size_t(x);
                    target->positions[texel] = p[0] * w0 + p[1] * w1 + p[2] * w2;
                    target->normals[texel] = normalizedOr(n[0] * w0 + n[1] * w1 + n[2] * w2,
                            float3{ 0.0f, 0.0f, 1.0f });
                    target->covered[texel] = 1;
                });
    }
}

// Grows the AO field across uncovered texels so bilinear filtering at a chart border does not
// blend towards the neutral 255 value. Only the value is propagated; coverage stays as
// rasterized so the statistics still describe the real atlas.
size_t dilateAoMap(std::vector<uint8_t>* values, std::vector<uint8_t> const& covered,
        uint32_t size, uint32_t passes) {
    std::vector<uint8_t> current = *values;
    std::vector<uint8_t> currentCovered = covered;
    std::vector<uint8_t> next = current;
    std::vector<uint8_t> nextCovered = currentCovered;
    size_t written = 0;
    for (uint32_t pass = 0; pass < passes; ++pass) {
        bool changed = false;
        for (int y = 0; y < int(size); ++y) {
            for (int x = 0; x < int(size); ++x) {
                size_t const texel = size_t(y) * size + size_t(x);
                if (currentCovered[texel]) {
                    continue;
                }
                uint32_t sum = 0;
                int count = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    int const ny = y + dy;
                    if (ny < 0 || ny >= int(size)) {
                        continue;
                    }
                    for (int dx = -1; dx <= 1; ++dx) {
                        int const nx = x + dx;
                        if (nx < 0 || nx >= int(size) || (dx == 0 && dy == 0)) {
                            continue;
                        }
                        size_t const neighbour = size_t(ny) * size + size_t(nx);
                        if (currentCovered[neighbour]) {
                            sum += current[neighbour];
                            ++count;
                        }
                    }
                }
                if (count > 0) {
                    next[texel] = uint8_t((sum + uint32_t(count) / 2) / uint32_t(count));
                    nextCovered[texel] = 1;
                    ++written;
                    changed = true;
                }
            }
        }
        current.swap(next);
        currentCovered.swap(nextCovered);
        if (!changed) {
            break;
        }
    }
    values->swap(current);
    return written;
}

// A 3x3 Gaussian restricted to covered texels. The AO estimate is a 32-sample Monte Carlo
// average, so without this the map shows texel-level grain that survives bilinear filtering.
void smoothAoMap(std::vector<uint8_t>* values, std::vector<uint8_t> const& covered,
        uint32_t size, uint32_t passes) {
    if (passes == 0) {
        return;
    }
    std::vector<uint8_t> next(values->size());
    for (uint32_t pass = 0; pass < passes; ++pass) {
        for (int y = 0; y < int(size); ++y) {
            for (int x = 0; x < int(size); ++x) {
                size_t const texel = size_t(y) * size + size_t(x);
                if (!covered[texel]) {
                    next[texel] = (*values)[texel];
                    continue;
                }
                uint32_t sum = 0;
                uint32_t weight = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    int const ny = y + dy;
                    if (ny < 0 || ny >= int(size)) {
                        continue;
                    }
                    for (int dx = -1; dx <= 1; ++dx) {
                        int const nx = x + dx;
                        if (nx < 0 || nx >= int(size)) {
                            continue;
                        }
                        size_t const neighbour = size_t(ny) * size + size_t(nx);
                        if (!covered[neighbour]) {
                            continue;
                        }
                        uint32_t const w = (dx == 0 ? 2u : 1u) * (dy == 0 ? 2u : 1u);
                        sum += uint32_t((*values)[neighbour]) * w;
                        weight += w;
                    }
                }
                next[texel] = weight > 0 ? uint8_t((sum + weight / 2) / weight)
                                         : (*values)[texel];
            }
        }
        values->swap(next);
    }
}

} // anonymous namespace

bool bakeVertexAmbientOcclusion(Mesh const& source, Mesh const& target,
        AmbientOcclusionOptions const& options, AmbientOcclusionResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    if (source.positions.empty() || source.indices.size() < 3 || target.positions.empty() ||
            options.samples == 0) {
        return false;
    }

    auto const start = std::chrono::steady_clock::now();

    Bvh bvh;
    Bounds sourceBounds;
    if (!buildBvh(source, &bvh, &sourceBounds)) {
        return false;
    }

    float const diagonal = length(sourceBounds.hi - sourceBounds.lo);
    if (!(diagonal > 0.0f)) {
        return false;
    }
    float const radius = options.radius > 0.0f ? options.radius : 0.1f * diagonal;
    float const bias = options.bias > 0.0f ? options.bias : 1e-4f * diagonal;

    std::vector<float3> normals;
    if (target.hasNormals()) {
        normals = target.normals;
        for (float3& normal: normals) {
            normal = normalizedOr(normal, float3{ 0.0f, 0.0f, 1.0f });
        }
    } else {
        deriveVertexNormals(target, &normals);
    }

    std::vector<float> values(target.positions.size(), 1.0f);
    std::vector<float3> bentNormalSums(target.positions.size(), float3{});
    uint32_t const sampleCount = effectiveSampleCount(options.samples);
    float const maximumSearchDistance = std::max(2.0f * radius, 0.02f * diagonal);
    float const maximumSearchDistance2 = maximumSearchDistance * maximumSearchDistance;
    detail::parallelFor(values.size(), [&](size_t vertex) {
        float3 const position = target.positions[vertex];
        float3 const normal = normals[vertex];
        // QEM placement can move a generated vertex slightly off, or even inside, the source
        // surface. Sampling from such a point makes every ray hit the surrounding solid, so
        // snap the sample point to the nearest source triangle first. On-surface vertices keep
        // their exact position (distance 0).
        ClosestPoint closest;
        findClosestSurfacePoint(bvh, position, maximumSearchDistance2, &closest);
        float3 const samplePosition = closest.distance2 <= maximumSearchDistance2
                                              ? closest.point
                                              : position;

        float3 bentNormalSum{};
        uint32_t const visible = sampleVisibility(bvh, samplePosition, normal, radius, bias,
                options.samples, options.seed ^ hash32(uint32_t(vertex)), &bentNormalSum);
        values[vertex] = float(visible) / float(sampleCount);
        bentNormalSums[vertex] = bentNormalSum;
    });

    if (options.weldDuplicatePositions && values.size() > 1) {
        float const epsilon = std::max(1e-6f, 1e-6f * diagonal);
        float const inverseEpsilon = 1.0f / epsilon;
        std::vector<PositionKey> keys(values.size());
        for (size_t vertex = 0; vertex < values.size(); ++vertex) {
            float3 const& position = target.positions[vertex];
            keys[vertex] = { int64_t(std::llround(position.x * inverseEpsilon)),
                int64_t(std::llround(position.y * inverseEpsilon)),
                int64_t(std::llround(position.z * inverseEpsilon)), uint32_t(vertex) };
        }
        std::sort(keys.begin(), keys.end());
        for (size_t begin = 0; begin < keys.size();) {
            size_t end = begin + 1;
            while (end < keys.size() && keys[end].x == keys[begin].x &&
                    keys[end].y == keys[begin].y && keys[end].z == keys[begin].z) {
                ++end;
            }
            if (end - begin > 1) {
                double sum = 0.0;
                float3 bentNormalSum{};
                for (size_t i = begin; i < end; ++i) {
                    sum += double(values[keys[i].vertex]);
                    bentNormalSum += bentNormalSums[keys[i].vertex];
                }
                float const average = float(sum / double(end - begin));
                float const inverseCount = 1.0f / float(end - begin);
                for (size_t i = begin; i < end; ++i) {
                    values[keys[i].vertex] = average;
                    bentNormalSums[keys[i].vertex] = bentNormalSum * inverseCount;
                }
                result->weldedGroups += 1;
            }
            begin = end;
        }
    }

    std::vector<float3> bentNormals(values.size());
    size_t tiltedVertices = 0;
    double bendSum = 0.0;
    float maximumBend = 0.0f;
    for (size_t vertex = 0; vertex < values.size(); ++vertex) {
        float3 const normal = normalizedOr(normals[vertex], float3{ 0.0f, 0.0f, 1.0f });
        float3 bent = normalizedOr(bentNormalSums[vertex], normal);
        if (dot(bent, normal) <= 0.0f) {
            // The integral of a cosine-weighted hemisphere can only be empty when every ray was
            // blocked. Keep such a vertex at the geometric normal rather than flipping it.
            bent = normal;
        }
        bentNormals[vertex] = bent;
        float const angle = std::acos(std::clamp(dot(bent, normal), -1.0f, 1.0f)) *
                            57.29577951308232f;
        bendSum += double(angle);
        maximumBend = std::max(maximumBend, angle);
        if (angle > 0.05f) {
            ++tiltedVertices;
        }
    }

    double sum = 0.0;
    float minimum = 1.0f;
    float maximum = 0.0f;
    for (float value: values) {
        sum += double(value);
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }

    auto const endTime = std::chrono::steady_clock::now();
    result->values = std::move(values);
    result->bentNormals = std::move(bentNormals);
    result->bakedVertices = result->values.size();
    result->mean = result->values.empty() ? 1.0f : float(sum / double(result->values.size()));
    result->min = minimum;
    result->max = maximum;
    result->tiltedVertices = tiltedVertices;
    result->meanBendDegrees =
            result->bentNormals.empty() ? 0.0f : float(bendSum / double(result->bentNormals.size()));
    result->maxBendDegrees = maximumBend;
    result->radius = radius;
    result->bias = bias;
    result->bakeMs = std::chrono::duration<double, std::milli>(endTime - start).count();
    return true;
}

bool bakeAmbientOcclusionMap(Mesh const& source, AmbientOcclusionMapOptions const& options,
        AmbientOcclusionMapResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    if (source.positions.empty() || source.indices.size() < 3 || !source.hasUVs() ||
            !source.hasNormals() || options.samples == 0 || options.size < 2) {
        return false;
    }
    for (uint32_t index: source.indices) {
        if (index >= source.positions.size()) {
            return false;
        }
        math::float2 const uv = source.uvs[index];
        if (!(uv.x >= -1e-3f && uv.x <= 1.0f + 1e-3f && uv.y >= -1e-3f &&
                    uv.y <= 1.0f + 1e-3f)) {
            // A tiled layout would write several surface points into the same texel.
            return false;
        }
    }

    auto const start = std::chrono::steady_clock::now();

    Bvh bvh;
    Bounds sourceBounds;
    if (!buildBvh(source, &bvh, &sourceBounds)) {
        return false;
    }
    float const diagonal = length(sourceBounds.hi - sourceBounds.lo);
    if (!(diagonal > 0.0f)) {
        return false;
    }
    float const radius = options.radius > 0.0f ? options.radius : 0.1f * diagonal;
    float const bias = options.bias > 0.0f ? options.bias : 1e-4f * diagonal;

    uint32_t const size = options.size;
    size_t const texelCount = size_t(size) * size;
    SurfaceTarget target;
    target.reset(size);
    rasterizeSurface(source, size, &target);

    std::vector<uint8_t> values(texelCount, 255);
    uint32_t const sampleCount = effectiveSampleCount(options.samples);
    detail::parallelFor(texelCount, [&](size_t texel) {
        if (!target.covered[texel]) {
            return;
        }
        uint32_t const visible = sampleVisibility(bvh, target.positions[texel],
                target.normals[texel], radius, bias, options.samples,
                options.seed ^ hash32(uint32_t(texel)));
        values[texel] = uint8_t((visible * 255u + sampleCount / 2u) / sampleCount);
    });
    smoothAoMap(&values, target.covered, size, options.smoothingPasses);

    size_t coveredTexels = 0;
    double sum = 0.0;
    float minimum = 1.0f;
    float maximum = 0.0f;
    for (size_t texel = 0; texel < texelCount; ++texel) {
        if (!target.covered[texel]) {
            continue;
        }
        ++coveredTexels;
        float const value = float(values[texel]) / 255.0f;
        sum += double(value);
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }
    if (coveredTexels == 0) {
        return false;
    }
    size_t const dilatedTexels = dilateAoMap(&values, target.covered, size,
            options.dilationTexels);

    auto const end = std::chrono::steady_clock::now();
    result->size = size;
    result->values = std::move(values);
    result->coveredTexels = coveredTexels;
    result->writtenTexels = coveredTexels + dilatedTexels;
    result->mean = float(sum / double(coveredTexels));
    result->min = minimum;
    result->max = maximum;
    result->radius = radius;
    result->bias = bias;
    result->bakeMs = std::chrono::duration<double, std::milli>(end - start).count();
    return true;
}

} // namespace manymesh
} // namespace filament
