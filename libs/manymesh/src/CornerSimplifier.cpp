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

#include <manymesh/CornerSimplifier.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <queue>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace filament {
namespace manymesh {

namespace {
struct ScopedSeconds {
    double* sink = nullptr;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    explicit ScopedSeconds(double* target)
            : sink(target) {}
    void stop() {
        if (sink != nullptr) {
            *sink +=
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            sink = nullptr;
        }
    }
    ~ScopedSeconds() { stop(); }
    ScopedSeconds(ScopedSeconds const&) = delete;
    ScopedSeconds& operator=(ScopedSeconds const&) = delete;
};

using ProfileClock = std::chrono::steady_clock;

double profileSeconds(ProfileClock::time_point start) {
    return std::chrono::duration<double>(ProfileClock::now() - start).count();
}

struct Quadric {
    float a00 = 0.0f;
    float a01 = 0.0f;
    float a02 = 0.0f;
    float a03 = 0.0f;
    float a11 = 0.0f;
    float a12 = 0.0f;
    float a13 = 0.0f;
    float a22 = 0.0f;
    float a23 = 0.0f;
    float a33 = 0.0f;

    void add(Quadric const& other) noexcept {
        a00 += other.a00;
        a01 += other.a01;
        a02 += other.a02;
        a03 += other.a03;
        a11 += other.a11;
        a12 += other.a12;
        a13 += other.a13;
        a22 += other.a22;
        a23 += other.a23;
        a33 += other.a33;
    }

    float evaluate(math::float3 const& p) const noexcept {
        float const x = p.x;
        float const y = p.y;
        float const z = p.z;
        return a00 * x * x + 2.0f * a01 * x * y + 2.0f * a02 * x * z + 2.0f * a03 * x +
               a11 * y * y + 2.0f * a12 * y * z + 2.0f * a13 * y + a22 * z * z + 2.0f * a23 * z +
               a33;
    }
};

void quadricFromPlane(Quadric* q, math::float3 normal, float d, float weight) {
    q->a00 += weight * normal.x * normal.x;
    q->a01 += weight * normal.x * normal.y;
    q->a02 += weight * normal.x * normal.z;
    q->a03 += weight * normal.x * d;
    q->a11 += weight * normal.y * normal.y;
    q->a12 += weight * normal.y * normal.z;
    q->a13 += weight * normal.y * d;
    q->a22 += weight * normal.z * normal.z;
    q->a23 += weight * normal.z * d;
    q->a33 += weight * d * d;
}

bool trianglePlane(math::float3 const& a, math::float3 const& b, math::float3 const& c,
        math::float3* normal, float* area) {
    math::float3 const ab = b - a;
    math::float3 const ac = c - a;
    math::float3 const crossProduct = cross(ab, ac);
    float const length2 = dot(crossProduct, crossProduct);
    if (!(length2 > 1e-20f)) {
        return false;
    }
    *area = std::sqrt(length2) * 0.5f;
    *normal = crossProduct / std::sqrt(length2);
    return true;
}

//! Squared distance from `point` to the closest point on a triangle (Ericson, Real-Time
//! Collision Detection). The placement search uses it to measure how far a collapse moves the
//! local surface, separately from the quadric cost that drives the priority queue.
float pointTriangleDistance2(math::float3 const& point, std::array<math::float3, 3> const& p) {
    math::float3 const ab = p[1] - p[0];
    math::float3 const ac = p[2] - p[0];
    math::float3 const ap = point - p[0];
    float const d1 = dot(ab, ap);
    float const d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        return dot(ap, ap);
    }

    math::float3 const bp = point - p[1];
    float const d3 = dot(ab, bp);
    float const d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        return dot(bp, bp);
    }

    float const vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        float const v = d1 / (d1 - d3);
        math::float3 const q = p[0] + ab * v;
        return dot(point - q, point - q);
    }

    math::float3 const cp = point - p[2];
    float const d5 = dot(ab, cp);
    float const d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        return dot(cp, cp);
    }

    float const vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        float const w = d2 / (d2 - d6);
        math::float3 const q = p[0] + ac * w;
        return dot(point - q, point - q);
    }

    float const va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        float const w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        math::float3 const q = p[1] + (p[2] - p[1]) * w;
        return dot(point - q, point - q);
    }

    float const denom = 1.0f / (va + vb + vc);
    float const v = vb * denom;
    float const w = vc * denom;
    math::float3 const q = p[0] + ab * v + ac * w;
    return dot(point - q, point - q);
}

math::float3 closestPointOnTriangle(math::float3 const& point,
        std::array<math::float3, 3> const& p) {
    math::float3 const ab = p[1] - p[0];
    math::float3 const ac = p[2] - p[0];
    math::float3 const ap = point - p[0];
    float const d1 = dot(ab, ap);
    float const d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        return p[0];
    }

    math::float3 const bp = point - p[1];
    float const d3 = dot(ab, bp);
    float const d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        return p[1];
    }

    float const vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        return p[0] + ab * (d1 / (d1 - d3));
    }

    math::float3 const cp = point - p[2];
    float const d5 = dot(ab, cp);
    float const d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        return p[2];
    }

    float const vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        return p[0] + ac * (d2 / (d2 - d6));
    }

    float const va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        return p[1] + (p[2] - p[1]) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)));
    }

    float const denom = 1.0f / (va + vb + vc);
    return p[0] + ab * (vb * denom) + ac * (vc * denom);
}

//! Computes the normal and quality of a rewritten triangle with one cross product and one square
//! root. The placement loop used to call triangleQuality() and trianglePlane() back to back, which
//! repeated both operations for every target.
bool triangleNormalAndQuality(math::float3 const& a, math::float3 const& b,
        math::float3 const& c, math::float3* normal, float* quality) {
    math::float3 const ab = b - a;
    math::float3 const ac = c - a;
    math::float3 const crossProduct = cross(ab, ac);
    float const length2 = dot(crossProduct, crossProduct);
    if (!(length2 > 1e-20f)) {
        *quality = 0.0f;
        return false;
    }
    float const area2 = std::sqrt(length2);
    *normal = crossProduct / area2;
    float const denominator = dot(ab, ab) + dot(ac, ac) + dot(c - b, c - b);
    *quality = denominator > 0.0f
                       ? std::clamp(2.0f * std::sqrt(3.0f) * area2 / denominator, 0.0f, 1.0f)
                       : 0.0f;
    return true;
}

float wrappedUvDistance(math::float2 a, math::float2 b) {
    math::float2 delta = a - b;
    delta.x -= std::round(delta.x);
    delta.y -= std::round(delta.y);
    return length(delta);
}

struct BarycentricWeights {
    float u = 1.0f / 3.0f;
    float v = 1.0f / 3.0f;
    float w = 1.0f / 3.0f;
    float outside = 1.0f;
};

//! Raw barycentric coordinates for containment tests plus the clamped weights used to carry
//! chart attributes. The two callers used to repeat the same six dot products per target.
BarycentricWeights barycentricWeights(math::float3 const& point,
        std::array<math::float3, 3> const& positions) {
    math::float3 const v0 = positions[1] - positions[0];
    math::float3 const v1 = positions[2] - positions[0];
    math::float3 const v2 = point - positions[0];
    float const d00 = dot(v0, v0);
    float const d01 = dot(v0, v1);
    float const d11 = dot(v1, v1);
    float const d20 = dot(v2, v0);
    float const d21 = dot(v2, v1);
    float const denom = d00 * d11 - d01 * d01;
    if (std::abs(denom) <= 1e-20f) {
        return {};
    }
    float const rawV = (d11 * d20 - d01 * d21) / denom;
    float const rawW = (d00 * d21 - d01 * d20) / denom;
    float const rawU = 1.0f - rawV - rawW;

    BarycentricWeights weights;
    weights.outside = std::max(
            { 0.0f, -rawU, -rawV, -rawW, rawU - 1.0f, rawV - 1.0f, rawW - 1.0f });
    weights.v = std::clamp(rawV, -8.0f, 9.0f);
    weights.w = std::clamp(rawW, -8.0f, 9.0f);
    weights.u = 1.0f - weights.v - weights.w;
    return weights;
}

struct PositionKey {
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t z = 0;

    bool operator==(PositionKey const& other) const noexcept {
        return x == other.x && y == other.y && z == other.z;
    }
};

struct PositionKeyHash {
    size_t operator()(PositionKey const& key) const noexcept {
        uint64_t hash = uint64_t(key.x) * 0x9E3779B185EBCA87ull;
        hash ^= uint64_t(key.y) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        hash ^= uint64_t(key.z) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        return size_t(hash);
    }
};

PositionKey positionKey(math::float3 position) noexcept {
    // Importers duplicate seam vertices with bit-identical positions. Normalising negative zero
    // keeps the key stable without introducing an epsilon that could weld nearby detail.
    float const x = position.x == 0.0f ? 0.0f : position.x;
    float const y = position.y == 0.0f ? 0.0f : position.y;
    float const z = position.z == 0.0f ? 0.0f : position.z;
    PositionKey key;
    std::memcpy(&key.x, &x, sizeof(float));
    std::memcpy(&key.y, &y, sizeof(float));
    std::memcpy(&key.z, &z, sizeof(float));
    return key;
}

using Edge = std::pair<uint32_t, uint32_t>;

struct EdgeHash {
    size_t operator()(Edge const& edge) const noexcept {
        uint64_t hash = uint64_t(edge.first) * 0x9E3779B185EBCA87ull;
        hash ^= uint64_t(edge.second) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        return size_t(hash);
    }
};

Edge edgeOf(uint32_t a, uint32_t b) { return { std::min(a, b), std::max(a, b) }; }

using TriangleKey = std::array<uint32_t, 3>;

struct TriangleKeyHash {
    size_t operator()(TriangleKey const& key) const noexcept {
        uint64_t hash = uint64_t(key[0]) * 0x9E3779B185EBCA87ull;
        hash ^= uint64_t(key[1]) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        hash ^= uint64_t(key[2]) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        return size_t(hash);
    }
};

struct Corner {
    math::float3 normal{};
    math::float2 uv{};
    float ao = 1.0f;
    uint32_t sourceVertex = UINT32_MAX;
};

struct WeldVertex {
    uint32_t positionSource = 0;
    math::float3 position{};
    Quadric quadric;
    uint32_t version = 0;
    bool border = false;
    bool locked = false;
    bool removed = false;
    bool moved = false;
    std::vector<uint32_t> members;
};

struct Triangle {
    std::array<uint32_t, 3> vertices{};
    std::array<Corner, 3> corners{};
    TriangleKey key{};
    bool alive = true;
};

std::array<math::float2, 3> wrappedCornerUvs(std::array<Corner, 3> const& corners) {
    // Keep the three UVs in the same wrap before interpolating; otherwise a chart that crosses
    // u=0/1 would interpolate 0.98 towards 0.02 through 0.5, which is a visible smear.
    std::array<math::float2, 3> uv;
    math::float2 const reference = corners[0].uv;
    for (int i = 0; i < 3; ++i) {
        uv[i] = corners[i].uv;
        uv[i].x -= std::round(uv[i].x - reference.x);
        uv[i].y -= std::round(uv[i].y - reference.y);
    }
    return uv;
}

struct Unit {
    Mesh const& mesh;
    std::vector<WeldVertex> vertices;
    std::vector<std::vector<uint32_t>> incident;
    std::vector<Triangle> triangles;
    std::unordered_set<TriangleKey, TriangleKeyHash> triangleKeys;
    std::unordered_map<Edge, uint32_t, EdgeHash> edgeUse;
    std::vector<Edge> borderEdges;
    std::set<Edge> lockedEdges;
    size_t aliveTriangles = 0;
    math::float3 extent{};
    bool hasNormals = false;
    bool hasUVs = false;
    bool hasAO = false;
    bool hasNonManifold = false;

    explicit Unit(Mesh const& source)
            : mesh(source) {}
};

/**
 * Barycentric coordinates of `point` in the triangle, used to carry chart attributes through a
 * collapse. Extrapolation is clamped to a finite range: a collapse that moves far outside the
 * source triangle is rejected by the attribute gate, but it must never produce NaN/inf first.
 */
Corner interpolateCorner(BarycentricWeights const& weights, std::array<Corner, 3> const& corners,
        std::array<math::float2, 3> const& wrappedUvs, float* outNormalLength = nullptr) {
    Corner result;
    result.normal = corners[0].normal * weights.u + corners[1].normal * weights.v +
                    corners[2].normal * weights.w;
    float const normalLength = length(result.normal);
    if (normalLength > 1e-12f) {
        result.normal /= normalLength;
    }
    if (outNormalLength != nullptr) {
        *outNormalLength = length(result.normal);
    }
    result.uv = wrappedUvs[0] * weights.u + wrappedUvs[1] * weights.v +
                wrappedUvs[2] * weights.w;
    // Barycentric extrapolation is allowed for positions and UVs, but AO is a visibility
    // fraction: a moved vertex outside its source triangle must not darken past 0 or brighten
    // past 1.
    result.ao = std::clamp(corners[0].ao * weights.u + corners[1].ao * weights.v +
                            corners[2].ao * weights.w, 0.0f, 1.0f);
    return result;
}

Corner interpolateCorner(math::float3 const& point, std::array<math::float3, 3> const& positions,
        std::array<Corner, 3> const& corners) {
    return interpolateCorner(barycentricWeights(point, positions), corners,
            wrappedCornerUvs(corners));
}

void addNeighbors(Unit const& unit, uint32_t vertex, std::vector<uint32_t>* neighbors) {
    for (uint32_t t: unit.incident[vertex]) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        for (uint32_t other: triangle.vertices) {
            if (other != vertex) {
                neighbors->push_back(other);
            }
        }
    }
}

bool isBorderEdge(Unit const& unit, uint32_t a, uint32_t b) {
    auto const it = unit.edgeUse.find(edgeOf(a, b));
    return it != unit.edgeUse.end() && it->second == 1;
}

bool containsVertex(Triangle const& triangle, uint32_t vertex) {
    return triangle.vertices[0] == vertex || triangle.vertices[1] == vertex ||
           triangle.vertices[2] == vertex;
}

int cornerIndex(Triangle const& triangle, uint32_t vertex) {
    for (int i = 0; i < 3; ++i) {
        if (triangle.vertices[i] == vertex) {
            return i;
        }
    }
    return -1;
}

struct CollapseEvaluation {
    bool valid = false;
    float cost = 0.0f;
    //! Dimensionless ranking score for the priority queue. It is the same combination of
    //! surface deviation, UV/normal loss and QEM cost that selects the placement, so the
    //! simplifier removes the least damaging edge first instead of the cheapest quadric first.
    float priority = 0.0f;
    //! Worst normalized quality among the triangles this placement rewrites. Keeping it in the
    //! ranking prevents a surface-cheap collapse from leaving a near-sliver that the global
    //! topology gate has to reject later.
    float minQuality = 1.0f;
    float positionError = 0.0f;
    float worldError = 0.0f;
    //! Local bidirectional surface deviation implied by this placement. Unlike the distance
    //! between the two endpoints and the target, this also notices that a moved vertex may end
    //! up away from the source surface, which is what the global position gate measures.
    float surfaceError = 0.0f;
    //! How far outside its source triangle the target lies, in barycentric units. A target far
    //! outside extrapolates the chart attributes and can no longer follow an affine UV mapping.
    float barycentricOutside = 0.0f;
    //! Largest distance from the target to the plane of a triangle it rewrites. A target can be
    //! on one neighbour's surface and still be off another's plane on a curved chart; the
    //! resulting barycentric projection is what makes affine UVs drift.
    float planeDeviation = 0.0f;
    float normalError = 0.0f;
    float uvError = 0.0f;
    math::float3 targetPosition{};
    std::vector<std::pair<uint32_t, TriangleKey>> replacements;
};

//! Weight of the worst-triangle-quality term in the placement priority. The sweep on torus and
//! monkey showed 0.25 is the best balance: 0.10 keeps about 4% more monkey triangles at the same
//! target, while 0.50 over-penalizes coarse levels and produces a shallower DAG. The term is
//! dimensionless and does not change any acceptance gate; it only decides which legal collapse
//! is attempted first.
constexpr float kTriangleQualityPriorityWeight = 0.25f;

struct CornerAffectedTriangle {
    uint32_t index = UINT32_MAX;
    int removeIndex = -1;
    int keepIndex = -1;
    std::array<math::float3, 3> positions{};
    std::array<math::float3, 3> replacedPositions{};
    std::array<math::float2, 3> wrappedUvs{};
    std::array<float, 3> cornerNormalLengths{};
    math::float3 oldNormal{};
    math::float3 shadingNormal{};
    math::float3 replacedNormal{};
    float replacedPlaneOffset = 0.0f;
};

struct PlaneTriangle {
    std::array<math::float3, 3> positions{};
    math::float3 normal{};
    float offset = 0.0f;
    bool hasPlane = false;
};

//! Scratch reused by every candidate evaluation on a thread. Corner evaluation runs tens of
//! thousands of times for a large import; keeping these vectors alive removes six allocations
//! from the inner loop without changing the result.
struct CollapseScratch {
    std::vector<uint32_t> affected;
    std::vector<PlaneTriangle> affectedTriangles;
    std::vector<math::float3> deletedCentroids;
    std::vector<CornerAffectedTriangle> moved;
    std::vector<TriangleKey> newKeys;
    std::vector<std::pair<uint32_t, TriangleKey>> replacements;
    std::vector<uint32_t> localTriangles;
    std::vector<uint32_t> deletedTriangles;
    std::vector<uint32_t> triangleStamp;
    std::vector<uint32_t> replacementStamp;
    std::vector<uint32_t> replacementSlot;
    std::vector<uint32_t> removeNeighborStamp;
    std::vector<uint32_t> keepNeighborStamp;
    std::vector<uint64_t> edgeKeys;
    std::vector<int32_t> edgeUses;
    std::vector<uint32_t> edgeGenerations;
    std::vector<uint32_t> edgeSlots;
    uint32_t triangleGeneration = 0;
    uint32_t replacementGeneration = 0;
    uint32_t neighborGeneration = 0;
    uint32_t edgeGeneration = 0;
};

uint32_t nextStamp(std::vector<uint32_t>* stamps, size_t size, uint32_t* generation) {
    if (stamps->size() < size) {
        stamps->assign(size, 0u);
    }
    uint32_t next = ++(*generation);
    if (next == 0) {
        std::fill(stamps->begin(), stamps->end(), 0u);
        next = ++(*generation);
    }
    return next;
}

/**
 * Minimises the symmetric quadric `p^T A p + 2 b^T p + c`. A singular system (flat or
 * collinear neighbourhoods) has no unique optimum, so the caller falls back to the edge
 * endpoints and midpoint.
 */
bool solveOptimalPosition(Quadric const& q, math::float3* position) {
    float const a00 = q.a00;
    float const a01 = q.a01;
    float const a02 = q.a02;
    float const a11 = q.a11;
    float const a12 = q.a12;
    float const a22 = q.a22;
    float const c0 = -q.a03;
    float const c1 = -q.a13;
    float const c2 = -q.a23;
    float const det = a00 * (a11 * a22 - a12 * a12) - a01 * (a01 * a22 - a12 * a02) +
                      a02 * (a01 * a12 - a11 * a02);
    if (!(std::abs(det) > 1e-12f)) {
        return false;
    }
    float const inv = 1.0f / det;
    float const i00 = (a11 * a22 - a12 * a12) * inv;
    float const i01 = (a02 * a12 - a01 * a22) * inv;
    float const i02 = (a01 * a12 - a02 * a11) * inv;
    float const i11 = (a00 * a22 - a02 * a02) * inv;
    float const i12 = (a01 * a02 - a00 * a12) * inv;
    float const i22 = (a00 * a11 - a01 * a01) * inv;

    position->x = i00 * c0 + i01 * c1 + i02 * c2;
    position->y = i01 * c0 + i11 * c1 + i12 * c2;
    position->z = i02 * c0 + i12 * c1 + i22 * c2;
    return std::isfinite(position->x) && std::isfinite(position->y) && std::isfinite(position->z);
}

CollapseEvaluation evaluateCollapse(Unit const& unit, uint32_t remove, uint32_t keep,
        CornerSimplifyOptions const& options) {
    CollapseEvaluation result;
    ScopedSeconds const evaluateTimer(
            options.profile ? &options.profile->evaluateSeconds : nullptr);
    if (options.profile != nullptr) {
        options.profile->evaluations += 1;
    }
    if (remove == keep || remove >= unit.vertices.size() || keep >= unit.vertices.size()) {
        return result;
    }
    if (unit.vertices[remove].removed || unit.vertices[keep].removed ||
            unit.vertices[remove].locked) {
        return result;
    }
    if (options.lockBorder && unit.vertices[remove].border) {
        return result;
    }

    ScopedSeconds neighborTimer(
            options.profile ? &options.profile->topologyNeighborSeconds : nullptr);

    // A locked target must not gain an edge to another locked vertex. Such a chord is still
    // locally manifold in this unit, but the neighbouring unit can create its mirror image,
    // which leaves overlapping triangles after the cut is assembled.
    if (unit.vertices[keep].locked) {
        for (uint32_t t: unit.incident[remove]) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive || containsVertex(triangle, keep)) {
                continue;
            }
            for (uint32_t vertex: triangle.vertices) {
                if (vertex != remove && unit.vertices[vertex].locked) {
                    return result;
                }
            }
        }
    }

    // With border locking, a collapse may not delete a triangle that owns an outline edge.
    // The welded outline is exactly the unit boundary; keeping it fixed is what lets sibling
    // units be simplified independently without a crack.
    if (options.lockBorder) {
        for (uint32_t t: unit.incident[remove]) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive) {
                continue;
            }
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = triangle.vertices[e];
                uint32_t const b = triangle.vertices[(e + 1) % 3];
                if (isBorderEdge(unit, a, b)) {
                    return result;
                }
            }
            if (unit.vertices[keep].border && !containsVertex(triangle, keep)) {
                return result;
            }
        }
    }

    static thread_local CollapseScratch scratch;
    uint32_t const neighborGeneration = nextStamp(&scratch.removeNeighborStamp,
            unit.vertices.size(), &scratch.neighborGeneration);
    std::vector<uint32_t>& removeNeighborStamp = scratch.removeNeighborStamp;
    std::vector<uint32_t>& keepNeighborStamp = scratch.keepNeighborStamp;
    if (keepNeighborStamp.size() < unit.vertices.size()) {
        keepNeighborStamp.assign(unit.vertices.size(), 0u);
    }
    for (uint32_t t: unit.incident[remove]) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        for (uint32_t other: triangle.vertices) {
            if (other != remove) {
                removeNeighborStamp[other] = neighborGeneration;
            }
        }
    }
    uint32_t sharedEdgeTriangles = 0;
    uint32_t commonNeighbors = 0;
    for (uint32_t t: unit.incident[keep]) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        for (uint32_t other: triangle.vertices) {
            if (other != keep && removeNeighborStamp[other] == neighborGeneration &&
                    keepNeighborStamp[other] != neighborGeneration) {
                keepNeighborStamp[other] = neighborGeneration;
                commonNeighbors += 1;
            }
        }
    }
    for (uint32_t t: unit.incident[remove]) {
        Triangle const& triangle = unit.triangles[t];
        if (triangle.alive && containsVertex(triangle, keep)) {
            sharedEdgeTriangles += 1;
        }
    }
    if (sharedEdgeTriangles == 0 || sharedEdgeTriangles > 2) {
        return result;
    }
    uint32_t const requiredCommon = sharedEdgeTriangles == 2 ? 2u : 1u;
    if (commonNeighbors != requiredCommon) {
        return result;
    }
    neighborTimer.stop();

    Quadric combined = unit.vertices[remove].quadric;
    combined.add(unit.vertices[keep].quadric);
    math::float3 const keepPosition = unit.vertices[keep].position;
    math::float3 const removePosition = unit.vertices[remove].position;
    float const maxNormal = options.maxNormalErrorDegrees * 3.14159265358979323846f / 180.0f;

    // A border or locked target is part of another unit's outline (or is explicitly pinned), so
    // it may not move. Interior targets are free to take the QEM optimum. Trying the endpoints and
    // midpoint as well keeps flat or singular neighbourhoods well behaved. The tangent projection
    // of the QEM optimum is important for thin or strongly curved surfaces: an unconstrained
    // optimum can sit below the surface, which the coarse level's position gate correctly rejects
    // but an endpoint-only fallback would solve by biasing every collapse to one side.
    bool const keepFixed = unit.vertices[keep].border || unit.vertices[keep].locked;
    math::float3 averageNormal{};
    for (int endpoint = 0; endpoint < 2; ++endpoint) {
        uint32_t const vertex = endpoint == 0 ? keep : remove;
        for (uint32_t t: unit.incident[vertex]) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive) {
                continue;
            }
            math::float3 normal{};
            float area = 0.0f;
            if (trianglePlane(unit.vertices[triangle.vertices[0]].position,
                        unit.vertices[triangle.vertices[1]].position,
                        unit.vertices[triangle.vertices[2]].position, &normal, &area)) {
                averageNormal += normal * area;
            }
        }
    }
    if (length(averageNormal) > 1e-12f) {
        averageNormal = normalize(averageNormal);
    } else {
        averageNormal = {};
    }
    math::float3 const edge = removePosition - keepPosition;
    float const edgeLength = length(edge);
    math::float3 lo = min(keepPosition, removePosition) -
                      math::float3(edgeLength * 0.25f);
    math::float3 hi = max(keepPosition, removePosition) +
                      math::float3(edgeLength * 0.25f);
    auto clampToEdge = [&](math::float3 position) {
        position.x = std::clamp(position.x, lo.x, hi.x);
        position.y = std::clamp(position.y, lo.y, hi.y);
        position.z = std::clamp(position.z, lo.z, hi.z);
        return position;
    };
    std::array<math::float3, 8> targets{};
    size_t targetCount = 0;
    targets[targetCount++] = keepPosition;
    if (!keepFixed) {
        targets[targetCount++] = removePosition;
        targets[targetCount++] = (keepPosition + removePosition) * 0.5f;
        math::float3 optimal{};
        if (solveOptimalPosition(combined, &optimal)) {
            optimal = clampToEdge(optimal);
            targets[targetCount++] = optimal;
            if (length(averageNormal) > 0.5f) {
                math::float3 const midpoint = (keepPosition + removePosition) * 0.5f;
                math::float3 const tangent = clampToEdge(optimal -
                        averageNormal * dot(optimal - midpoint, averageNormal));
                if (length(tangent - optimal) > 1e-7f) {
                    targets[targetCount++] = tangent;
                }
            }
            math::float3 projected{};
            float projectedDistance2 = std::numeric_limits<float>::max();
            for (int endpoint = 0; endpoint < 2; ++endpoint) {
                uint32_t const vertex = endpoint == 0 ? keep : remove;
                for (uint32_t t: unit.incident[vertex]) {
                    Triangle const& triangle = unit.triangles[t];
                    if (!triangle.alive) {
                        continue;
                    }
                    std::array<math::float3, 3> const positions = {
                        unit.vertices[triangle.vertices[0]].position,
                        unit.vertices[triangle.vertices[1]].position,
                        unit.vertices[triangle.vertices[2]].position,
                    };
                    math::float3 const candidate = closestPointOnTriangle(optimal, positions);
                    float const distance2 = dot(candidate - optimal, candidate - optimal);
                    if (distance2 < projectedDistance2) {
                        projectedDistance2 = distance2;
                        projected = candidate;
                    }
                }
            }
            if (std::isfinite(projectedDistance2)) {
                projected = clampToEdge(projected);
                bool duplicate = false;
                for (size_t i = 0; i < targetCount; ++i) {
                    duplicate = duplicate || length(targets[i] - projected) < 1e-7f;
                }
                if (!duplicate) {
                    targets[targetCount++] = projected;
                }
            }
        }
    }

    ScopedSeconds topologyTimer(
            options.profile ? &options.profile->evaluateTopologySeconds : nullptr);

    // Connectivity and one-ring topology depend only on which vertices collapse, not on where
    // the merged vertex lands. Building them once per candidate instead of once per placement
    // target removes most of the allocation and sorting work from this inner loop. The corner
    // pass evaluates up to four placements (both endpoints, midpoint and the QEM optimum).
    std::vector<uint32_t>& affected = scratch.affected;
    auto const triangleStart = ProfileClock::now();
    affected.clear();
    affected.resize(unit.incident[remove].size() + unit.incident[keep].size());
    affected.erase(std::set_union(unit.incident[remove].begin(), unit.incident[remove].end(),
                           unit.incident[keep].begin(), unit.incident[keep].end(),
                           affected.begin()),
            affected.end());

    std::vector<CornerAffectedTriangle>& moved = scratch.moved;
    std::vector<TriangleKey>& newKeys = scratch.newKeys;
    std::vector<std::pair<uint32_t, TriangleKey>>& replacements = scratch.replacements;
    moved.clear();
    newKeys.clear();
    replacements.clear();
    std::vector<uint32_t>& deletedTriangles = scratch.deletedTriangles;
    deletedTriangles.clear();
    uint32_t const replacementGeneration = nextStamp(&scratch.replacementStamp,
            unit.triangles.size(), &scratch.replacementGeneration);
    if (scratch.replacementSlot.size() < unit.triangles.size()) {
        scratch.replacementSlot.assign(unit.triangles.size(), 0u);
    }
    moved.reserve(affected.size());
    newKeys.reserve(affected.size());
    replacements.reserve(affected.size());

    for (uint32_t t: affected) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        int const removeIndex = cornerIndex(triangle, remove);
        int const keepIndex = cornerIndex(triangle, keep);
        if (removeIndex >= 0 && keepIndex >= 0) {
            deletedTriangles.push_back(t);
            continue; // this triangle collapses to a line and disappears
        }
        if (removeIndex < 0 && keepIndex < 0) {
            continue;
        }

        CornerAffectedTriangle entry;
        entry.index = t;
        entry.removeIndex = removeIndex;
        entry.keepIndex = keepIndex;
        for (int k = 0; k < 3; ++k) {
            entry.positions[k] = unit.vertices[triangle.vertices[k]].position;
            entry.shadingNormal += triangle.corners[k].normal;
            entry.cornerNormalLengths[k] = length(triangle.corners[k].normal);
        }
        entry.wrappedUvs = wrappedCornerUvs(triangle.corners);
        float oldArea = 0.0f;
        if (!trianglePlane(entry.positions[0], entry.positions[1], entry.positions[2],
                    &entry.oldNormal, &oldArea)) {
            return result;
        }

        // A collapse must not introduce a chord between two seam vertices. The global gate
        // checks this too, but rejecting it here keeps the QEM from walking into a dead end.
        TriangleKey resultingVertices = triangle.vertices;
        if (removeIndex >= 0) {
            resultingVertices[removeIndex] = keep;
        }
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = resultingVertices[e];
            uint32_t const b = resultingVertices[(e + 1) % 3];
            if (unit.vertices[a].locked && unit.vertices[b].locked &&
                    unit.lockedEdges.count(edgeOf(a, b)) == 0) {
                return result;
            }
        }

        if (removeIndex >= 0) {
            TriangleKey replaced = triangle.vertices;
            replaced[removeIndex] = keep;
            std::sort(replaced.begin(), replaced.end());
            if (replaced[0] == replaced[1] || replaced[1] == replaced[2] ||
                    replaced[0] == replaced[2]) {
                return result;
            }
            if (unit.triangleKeys.count(replaced) != 0 ||
                    std::find(newKeys.begin(), newKeys.end(), replaced) != newKeys.end()) {
                return result;
            }
            newKeys.push_back(replaced);
            replacements.emplace_back(t, replaced);
            scratch.replacementStamp[t] = replacementGeneration;
            scratch.replacementSlot[t] = uint32_t(replacements.size() - 1);
        }
        moved.push_back(entry);
    }
    if (options.profile != nullptr) {
        options.profile->topologyTriangleSeconds += profileSeconds(triangleStart);
    }


    static bool const forceFullEdgeCheck =
            std::getenv("MANYMESH_CORNER_FULL_EDGE_CHECK") != nullptr;
    if (unit.hasNonManifold || forceFullEdgeCheck) {
        // Validate the one-ring topology around both endpoints. Moving `keep` deforms every
        // incident triangle, not only the triangles that contained `remove`, so the local check
        // has to include both stars. Like the connectivity checks above this is placement
        // independent.
        std::vector<uint32_t>& localTriangles = scratch.localTriangles;
        auto const localTriangleStart = ProfileClock::now();
        localTriangles.clear();
        localTriangles.reserve(affected.size() * 4);
        uint32_t const triangleGeneration = nextStamp(&scratch.triangleStamp, unit.triangles.size(),
                &scratch.triangleGeneration);
        std::vector<uint32_t>& triangleStamp = scratch.triangleStamp;
        for (uint32_t t: affected) {
            if (!unit.triangles[t].alive) {
                continue;
            }
            if (triangleStamp[t] != triangleGeneration) {
                triangleStamp[t] = triangleGeneration;
                localTriangles.push_back(t);
            }
        }
        for (uint32_t t: affected) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive) {
                continue;
            }
            for (uint32_t vertex: triangle.vertices) {
                for (uint32_t incident: unit.incident[vertex]) {
                    if (unit.triangles[incident].alive &&
                            triangleStamp[incident] != triangleGeneration) {
                        triangleStamp[incident] = triangleGeneration;
                        localTriangles.push_back(incident);
                    }
                }
            }
        }
        if (options.profile != nullptr) {
            options.profile->topologyLocalTriangleSeconds += profileSeconds(localTriangleStart);
        }

        auto const localEdgeStart = ProfileClock::now();
        size_t tableSize = 16;
        size_t const requiredSlots = localTriangles.size() * 6 + 16;
        while (tableSize < requiredSlots) {
            tableSize <<= 1;
        }
        if (scratch.edgeKeys.size() != tableSize) {
            scratch.edgeKeys.assign(tableSize, 0u);
            scratch.edgeUses.assign(tableSize, 0u);
            scratch.edgeGenerations.assign(tableSize, 0u);
            scratch.edgeSlots.clear();
            scratch.edgeGeneration = 0;
        }
        uint32_t const edgeGeneration =
                nextStamp(&scratch.edgeGenerations, tableSize, &scratch.edgeGeneration);
        std::vector<uint64_t>& edgeKeys = scratch.edgeKeys;
        std::vector<int32_t>& edgeUses = scratch.edgeUses;
        std::vector<uint32_t>& edgeGenerations = scratch.edgeGenerations;
        std::vector<uint32_t>& edgeSlots = scratch.edgeSlots;
        edgeSlots.clear();
        size_t const edgeMask = tableSize - 1;
        auto insertEdge = [&](Edge edge) {
            uint64_t key = (uint64_t(edge.first) << 32) | uint64_t(edge.second);
            uint64_t hash = key;
            hash ^= hash >> 33;
            hash *= 0xFF51AFD7ED558CCDull;
            hash ^= hash >> 33;
            size_t slot = size_t(hash) & edgeMask;
            for (;;) {
                if (edgeGenerations[slot] != edgeGeneration) {
                    edgeGenerations[slot] = edgeGeneration;
                    edgeKeys[slot] = key;
                    edgeUses[slot] = 1;
                    edgeSlots.push_back(uint32_t(slot));
                    return;
                }
                if (edgeKeys[slot] == key) {
                    edgeUses[slot] += 1;
                    return;
                }
                slot = (slot + 1) & edgeMask;
            }
        };
        for (uint32_t t: localTriangles) {
            Triangle const& triangle = unit.triangles[t];
            if (cornerIndex(triangle, remove) >= 0 && cornerIndex(triangle, keep) >= 0) {
                continue; // removed by the collapse
            }
            TriangleKey vertices = triangle.key;
            if (scratch.replacementStamp[t] == replacementGeneration) {
                vertices = replacements[scratch.replacementSlot[t]].second;
            }
            for (int e = 0; e < 3; ++e) {
                insertEdge(edgeOf(vertices[e], vertices[(e + 1) % 3]));
            }
        }
        for (uint32_t slot: edgeSlots) {
            uint32_t const use = edgeUses[slot];
            if (use > 2) {
                return result;
            }
            if (options.lockBorder && use != 1) {
                Edge const edge = { uint32_t(edgeKeys[slot] >> 32), uint32_t(edgeKeys[slot]) };
                if (std::binary_search(unit.borderEdges.begin(), unit.borderEdges.end(), edge)) {
                    return result;
                }
            }
        }
        if (options.profile != nullptr) {
            options.profile->topologyLocalEdgeSeconds += profileSeconds(localEdgeStart);
        }
    } else {
        // Only the triangles rewritten by this collapse can change edge incidence. Edges that
        // no rewritten triangle touches keep their previous (already validated) use count, so
        // counting just the deltas avoids walking the whole two-ring for every candidate.
        auto const deltaStart = ProfileClock::now();
        size_t tableSize = 16;
        size_t const requiredSlots = (replacements.size() + deletedTriangles.size()) * 12 + 16;
        while (tableSize < requiredSlots) {
            tableSize <<= 1;
        }
        if (scratch.edgeKeys.size() != tableSize) {
            scratch.edgeKeys.assign(tableSize, 0u);
            scratch.edgeUses.assign(tableSize, 0u);
            scratch.edgeGenerations.assign(tableSize, 0u);
            scratch.edgeSlots.clear();
            scratch.edgeGeneration = 0;
        }
        uint32_t const edgeGeneration =
                nextStamp(&scratch.edgeGenerations, tableSize, &scratch.edgeGeneration);
        std::vector<uint64_t>& edgeKeys = scratch.edgeKeys;
        std::vector<int32_t>& edgeUses = scratch.edgeUses;
        std::vector<uint32_t>& edgeGenerations = scratch.edgeGenerations;
        std::vector<uint32_t>& edgeSlots = scratch.edgeSlots;
        edgeSlots.clear();
        size_t const edgeMask = tableSize - 1;
        auto addDelta = [&](Edge edge, int32_t delta) {
            uint64_t key = (uint64_t(edge.first) << 32) | uint64_t(edge.second);
            uint64_t hash = key;
            hash ^= hash >> 33;
            hash *= 0xFF51AFD7ED558CCDull;
            hash ^= hash >> 33;
            size_t slot = size_t(hash) & edgeMask;
            for (;;) {
                if (edgeGenerations[slot] != edgeGeneration) {
                    edgeGenerations[slot] = edgeGeneration;
                    edgeKeys[slot] = key;
                    edgeUses[slot] = delta;
                    edgeSlots.push_back(uint32_t(slot));
                    return;
                }
                if (edgeKeys[slot] == key) {
                    edgeUses[slot] += delta;
                    return;
                }
                slot = (slot + 1) & edgeMask;
            }
        };
        for (auto const& replacementEntry: replacements) {
            TriangleKey const& oldVertices = unit.triangles[replacementEntry.first].key;
            TriangleKey const& newVertices = replacementEntry.second;
            for (int e = 0; e < 3; ++e) {
                addDelta(edgeOf(oldVertices[e], oldVertices[(e + 1) % 3]), -1);
                addDelta(edgeOf(newVertices[e], newVertices[(e + 1) % 3]), 1);
            }
        }
        for (uint32_t t: deletedTriangles) {
            TriangleKey const& oldVertices = unit.triangles[t].key;
            for (int e = 0; e < 3; ++e) {
                addDelta(edgeOf(oldVertices[e], oldVertices[(e + 1) % 3]), -1);
            }
        }
        for (uint32_t slot: edgeSlots) {
            Edge const edge = { uint32_t(edgeKeys[slot] >> 32), uint32_t(edgeKeys[slot]) };
            auto const before = unit.edgeUse.find(edge);
            int32_t const use =
                    (before == unit.edgeUse.end() ? 0 : int32_t(before->second)) + edgeUses[slot];
            if (use > 2) {
                return result;
            }
            if (use <= 0) {
                continue;
            }
            if (options.lockBorder && use != 1 &&
                    std::binary_search(unit.borderEdges.begin(), unit.borderEdges.end(), edge)) {
                return result;
            }
        }
        if (options.profile != nullptr) {
            options.profile->topologyLocalEdgeSeconds += profileSeconds(deltaStart);
        }
    }
    topologyTimer.stop();

    std::vector<PlaneTriangle>& affectedTriangles = scratch.affectedTriangles;
    affectedTriangles.clear();
    affectedTriangles.reserve(affected.size());
    for (uint32_t t: affected) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        PlaneTriangle planeTriangle;
        planeTriangle.positions = { unit.vertices[triangle.vertices[0]].position,
            unit.vertices[triangle.vertices[1]].position,
            unit.vertices[triangle.vertices[2]].position };
        float area = 0.0f;
        planeTriangle.hasPlane = trianglePlane(planeTriangle.positions[0],
                planeTriangle.positions[1], planeTriangle.positions[2],
                &planeTriangle.normal, &area);
        if (planeTriangle.hasPlane) {
            planeTriangle.offset = dot(planeTriangle.normal, planeTriangle.positions[0]);
        }
        affectedTriangles.push_back(planeTriangle);
    }
    std::vector<math::float3>& deletedCentroids = scratch.deletedCentroids;
    deletedCentroids.clear();
    deletedCentroids.reserve(deletedTriangles.size());
    for (uint32_t t: deletedTriangles) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        deletedCentroids.push_back(
                (unit.vertices[triangle.vertices[0]].position +
                        unit.vertices[triangle.vertices[1]].position +
                        unit.vertices[triangle.vertices[2]].position) *
                (1.0f / 3.0f));
    }

    float const edgeScale = std::max(edgeLength, 1e-6f);
    float const extent2 = std::max(dot(unit.extent, unit.extent), 1e-12f);
    float bestScore = std::numeric_limits<float>::max();
    auto evaluateAt = [&](math::float3 const& target, CollapseEvaluation* out) {
        out->normalError = 0.0f;
        out->uvError = 0.0f;
        out->barycentricOutside = 0.0f;
        out->planeDeviation = 0.0f;
        out->minQuality = 1.0f;
        for (CornerAffectedTriangle& entry: moved) {
            Triangle const& triangle = unit.triangles[entry.index];
            std::array<math::float3, 3> replacedPositions = entry.positions;
            if (entry.removeIndex >= 0) {
                replacedPositions[entry.removeIndex] = target;
            }
            if (entry.keepIndex >= 0) {
                replacedPositions[entry.keepIndex] = target;
            }
            entry.replacedPositions = replacedPositions;
            BarycentricWeights const weights = barycentricWeights(target, entry.positions);
            out->barycentricOutside = std::max(out->barycentricOutside, weights.outside);
            out->planeDeviation = std::max(out->planeDeviation,
                    std::abs(dot(target - entry.positions[0], entry.oldNormal)));
            math::float3 newNormal{};
            float newQuality = 0.0f;
            if (!triangleNormalAndQuality(replacedPositions[0], replacedPositions[1],
                        replacedPositions[2], &newNormal, &newQuality) ||
                    newQuality < options.minTriangleQuality) {
                return false;
            }
            out->minQuality = std::min(out->minQuality, newQuality);
            entry.replacedNormal = newNormal;
            entry.replacedPlaneOffset = dot(newNormal, replacedPositions[0]);
            if (dot(entry.oldNormal, newNormal) < 0.1f) {
                return false;
            }

            int const movedIndices[2] = { entry.removeIndex, entry.keepIndex };
            for (int movedIndex: movedIndices) {
                if (movedIndex < 0) {
                    continue;
                }
                float updatedNormalLength = 0.0f;
                Corner const updated = interpolateCorner(weights, triangle.corners,
                        entry.wrappedUvs, &updatedNormalLength);
                if (unit.hasNormals) {
                    float angle = 0.0f;
                    float const cornerLength = entry.cornerNormalLengths[movedIndex];
                    if (cornerLength > 0.0f && updatedNormalLength > 0.0f) {
                        angle = std::acos(std::clamp(dot(triangle.corners[movedIndex].normal,
                                                            updated.normal) /
                                                    (cornerLength * updatedNormalLength),
                                -1.0f, 1.0f));
                    }
                    out->normalError = std::max(out->normalError, angle);
                    if (options.attributeGate && angle > maxNormal) {
                        return false;
                    }

                    math::float3 const candidateShading = entry.shadingNormal -
                                                          triangle.corners[movedIndex].normal +
                                                          updated.normal;
                    if (dot(newNormal, candidateShading) < 0.0f) {
                        return false;
                    }
                }
                if (unit.hasUVs) {
                    float const distance =
                            wrappedUvDistance(triangle.corners[movedIndex].uv, updated.uv);
                    out->uvError = std::max(out->uvError, distance);
                    if (options.attributeGate && distance > options.maxUvError) {
                        return false;
                    }
                    // Adjacent triangles of one chart interpolate the same corner vertex. When
                    // the collapse target leaves their shared neighbourhood, the barycentric
                    // extrapolations diverge. This is common in coarse hierarchy levels, where
                    // a vertex can be the only survivor of a large patch, and it is exactly the
                    // cross-chart case we want to allow. The output pass keeps such corners in
                    // separate generated vertices instead of averaging their UVs.
                }
            }
        }
        // The global quality gate measures how far every source point can be from the simplified
        // surface. Endpoint displacement is a poor proxy for that: it is small when a collapse
        // stays near both endpoints even if it cuts a chord through a thin shell, and it is large
        // when one endpoint vanishes into a neighbour that already covers the source surface.
        // Measure both directions of the local Hausdorff distance instead. This is only a
        // placement ranking signal; the existing topology, normal and UV gates still decide
        // whether the collapse is legal.
        if (moved.empty()) {
            return false;
        }
        out->positionError = std::max(0.0f, combined.evaluate(target));
        out->worldError = std::max(length(removePosition - target), length(keepPosition - target));
        out->cost = options.positionWeight * (out->positionError / extent2) +
                    options.normalWeight * out->normalError * out->normalError +
                    options.uvWeight * out->uvError * out->uvError;
        float const uv = options.attributeGate && options.maxUvError > 0.0f
                                 ? out->uvError / options.maxUvError
                                 : 0.0f;
        float const normal = options.attributeGate && maxNormal > 0.0f
                                     ? out->normalError / maxNormal
                                     : 0.0f;
        float const cheapScore = out->planeDeviation * 0.5f / edgeScale + uv * 0.25f +
                                 normal * 0.1f + out->barycentricOutside * 0.1f +
                                 out->cost * 1e-6f;
        if (cheapScore > bestScore) {
            return false;
        }
        // Both endpoints are vertices of at least one affected triangle, so their distance is a
        // valid upper bound for the nearest affected triangle. Starting from that bound makes
        // endpoint placements (the common case) skip the whole one-ring scan.
        math::float3 const targetToRemove = target - removePosition;
        math::float3 const targetToKeep = target - keepPosition;
        float targetDistance2 = std::min(dot(targetToRemove, targetToRemove),
                dot(targetToKeep, targetToKeep));
        if (targetDistance2 > 0.0f) {
            for (PlaneTriangle const& triangle: affectedTriangles) {
                if (triangle.hasPlane) {
                    float const planeDistance = dot(target, triangle.normal) - triangle.offset;
                    if (planeDistance * planeDistance >
                            targetDistance2 * 1.000001f + 1e-12f) {
                        continue;
                    }
                }
                targetDistance2 = std::min(targetDistance2,
                        pointTriangleDistance2(target, triangle.positions));
            }
        }
        if (!std::isfinite(targetDistance2)) {
            targetDistance2 = 0.0f;
        }
        // Every surviving one-ring vertex is a vertex of one of the `moved` triangles, so its
        // distance is zero. The two collapsing vertices and the centroids of the two triangles
        // deleted by the collapse are the only source points that can end up uncovered. Checking
        // those instead of every vertex and face keeps the placement search affordable.
        float sourceDistance2 = 0.0f;
        auto sampleSource = [&](math::float3 const& sample) {
            // The target is a vertex of every rewritten triangle, so this is an upper bound for
            // the nearest rewritten triangle. The plane test can then reject most of the ring.
            math::float3 const toTarget = sample - target;
            float bestDistance2 = dot(toTarget, toTarget);
            if (bestDistance2 > 0.0f) {
                for (CornerAffectedTriangle const& entry: moved) {
                    float const planeDistance =
                            dot(sample, entry.replacedNormal) - entry.replacedPlaneOffset;
                    if (planeDistance * planeDistance > bestDistance2 * 1.000001f + 1e-12f) {
                        continue;
                    }
                    bestDistance2 = std::min(bestDistance2,
                            pointTriangleDistance2(sample, entry.replacedPositions));
                    if (bestDistance2 <= 0.0f) {
                        break;
                    }
                }
            }
            sourceDistance2 = std::max(sourceDistance2, bestDistance2);
        };
        sampleSource(removePosition);
        sampleSource(keepPosition);
        for (math::float3 const& centroid: deletedCentroids) {
            sampleSource(centroid);
        }
        out->surfaceError = std::max(std::sqrt(std::max(targetDistance2, sourceDistance2)),
                out->planeDeviation * 0.5f);
        out->targetPosition = target;
        out->valid = true;
        return true;
    };

    // Rank placements by local surface deviation, with attribute loss as a first-class term. The
    // old loop returned the first valid target in QEM order, so a placement that was cheap on the
    // quadric but cut through a thin shell could be selected even when an equally valid tangent
    // projection was available. The terms are dimensionless so a UV jump cannot hide behind a
    // marginally better surface estimate.
    CollapseEvaluation best;
    auto placementScore = [&](CollapseEvaluation const& evaluation) {
        float const surface = evaluation.surfaceError / edgeScale;
        float const uv = options.attributeGate && options.maxUvError > 0.0f
                                 ? evaluation.uvError / options.maxUvError
                                 : 0.0f;
        float const normal = options.attributeGate && maxNormal > 0.0f
                                     ? evaluation.normalError / maxNormal
                                     : 0.0f;
        return surface + uv * 0.25f + normal * 0.1f +
               evaluation.barycentricOutside * 0.1f +
               (1.0f - evaluation.minQuality) * kTriangleQualityPriorityWeight +
               evaluation.cost * 1e-6f;
    };
    for (size_t i = 0; i < targetCount; ++i) {
        if (options.profile != nullptr) {
            options.profile->placementTests += 1;
        }
        ScopedSeconds targetTimer(
                options.profile ? &options.profile->evaluateTargetSeconds : nullptr);
        CollapseEvaluation trial;
        if (evaluateAt(targets[i], &trial)) {
            float const score = placementScore(trial);
            trial.priority = score;
            if (!best.valid || score < bestScore) {
                best = std::move(trial);
                bestScore = score;
            }
        }
    }
    if (best.valid) {
        best.replacements = replacements;
        result = std::move(best);
    }
    return result;
}

void applyCollapse(Unit* unit, uint32_t remove, uint32_t keep, math::float3 const& targetPosition) {
    math::float3 const keepPosition = unit->vertices[keep].position;
    std::vector<uint32_t> affected(unit->incident[remove].size() + unit->incident[keep].size());
    affected.erase(std::set_union(unit->incident[remove].begin(), unit->incident[remove].end(),
                           unit->incident[keep].begin(), unit->incident[keep].end(),
                           affected.begin()),
            affected.end());

    for (uint32_t t: affected) {
        Triangle& triangle = unit->triangles[t];
        if (!triangle.alive) {
            continue;
        }
        int const removeIndex = cornerIndex(triangle, remove);
        int const keepIndex = cornerIndex(triangle, keep);
        if (removeIndex < 0 && keepIndex < 0) {
            continue;
        }
        if (removeIndex >= 0 && keepIndex >= 0) {
            unit->aliveTriangles -= 1;
            triangle.alive = false;
            unit->triangleKeys.erase(triangle.key);
            for (int e = 0; e < 3; ++e) {
                Edge const edge = edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3]);
                auto it = unit->edgeUse.find(edge);
                if (it != unit->edgeUse.end() && it->second > 0) {
                    it->second -= 1;
                    if (it->second == 0) {
                        unit->edgeUse.erase(it);
                    }
                }
            }
            continue;
        }

        std::array<math::float3, 3> positions = {
            unit->vertices[triangle.vertices[0]].position,
            unit->vertices[triangle.vertices[1]].position,
            unit->vertices[triangle.vertices[2]].position,
        };
        Corner updated = interpolateCorner(targetPosition, positions, triangle.corners);
        updated.sourceVertex =
                triangle.corners[removeIndex >= 0 ? removeIndex : keepIndex].sourceVertex;

        if (removeIndex >= 0) {
            unit->triangleKeys.erase(triangle.key);
            for (int e = 0; e < 3; ++e) {
                Edge const edge = edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3]);
                auto it = unit->edgeUse.find(edge);
                if (it != unit->edgeUse.end() && it->second > 0) {
                    it->second -= 1;
                    if (it->second == 0) {
                        unit->edgeUse.erase(it);
                    }
                }
            }

            triangle.vertices[removeIndex] = keep;
            triangle.corners[removeIndex] = updated;
            TriangleKey key = { triangle.vertices[0], triangle.vertices[1], triangle.vertices[2] };
            std::sort(key.begin(), key.end());
            triangle.key = key;
            unit->triangleKeys.insert(key);

            for (int e = 0; e < 3; ++e) {
                unit->edgeUse[edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3])] += 1;
            }
            unit->incident[keep].push_back(t);
        } else {
            // `keep` moved; this triangle's connectivity did not change, but the chart value at
            // the moved corner must be re-interpolated at its new position.
            triangle.corners[keepIndex] = updated;
        }
    }

    unit->incident[remove].clear();
    std::sort(unit->incident[keep].begin(), unit->incident[keep].end());
    unit->incident[keep].erase(
            std::unique(unit->incident[keep].begin(), unit->incident[keep].end()),
            unit->incident[keep].end());

    unit->vertices[keep].position = targetPosition;
    if (length(targetPosition - keepPosition) > 1e-9f) {
        unit->vertices[keep].moved = true;
    }
    unit->vertices[keep].quadric.add(unit->vertices[remove].quadric);
    unit->vertices[keep].version += 1;
    unit->vertices[remove].removed = true;
    unit->vertices[remove].version += 1;
}


struct GeneratedKey {
    uint32_t positionSource = 0;
    int32_t position[3] = {};
    int32_t normal[3] = {};
    int32_t uv[2] = {};
    int32_t ao = 0;

    bool operator==(GeneratedKey const& other) const noexcept {
        return positionSource == other.positionSource && position[0] == other.position[0] &&
               position[1] == other.position[1] && position[2] == other.position[2] &&
               normal[0] == other.normal[0] && normal[1] == other.normal[1] &&
               normal[2] == other.normal[2] && uv[0] == other.uv[0] && uv[1] == other.uv[1] &&
               ao == other.ao;
    }
};

struct GeneratedKeyHash {
    size_t operator()(GeneratedKey const& key) const noexcept {
        uint64_t hash = uint64_t(key.positionSource) * 0x9E3779B185EBCA87ull;
        auto mix = [&hash](uint64_t value) {
            hash ^= value + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        };
        mix(uint64_t(uint32_t(key.position[0])));
        mix(uint64_t(uint32_t(key.position[1])));
        mix(uint64_t(uint32_t(key.position[2])));
        mix(uint64_t(uint32_t(key.normal[0])));
        mix(uint64_t(uint32_t(key.normal[1])));
        mix(uint64_t(uint32_t(key.normal[2])));
        mix(uint64_t(uint32_t(key.uv[0])));
        mix(uint64_t(uint32_t(key.uv[1])));
        mix(uint64_t(uint32_t(key.ao)));
        return size_t(hash);
    }
};

int32_t quantize(float value) { return int32_t(std::lround(value * 65536.0f)); }

GeneratedKey generatedKey(GeneratedVertex const& vertex) {
    GeneratedKey key;
    // positionSource is only a lock-mask fallback. Identical rendered attributes can share one
    // generated vertex even when they came from different chart vertices.
    key.position[0] = quantize(vertex.position.x);
    key.position[1] = quantize(vertex.position.y);
    key.position[2] = quantize(vertex.position.z);
    key.normal[0] = quantize(vertex.normal.x);
    key.normal[1] = quantize(vertex.normal.y);
    key.normal[2] = quantize(vertex.normal.z);
    key.uv[0] = quantize(vertex.uv.x);
    key.uv[1] = quantize(vertex.uv.y);
    key.ao = quantize(vertex.ao);
    return key;
}

bool attributesMatch(Mesh const& mesh, uint32_t global, Corner const& corner) {
    if (mesh.hasNormals()) {
        if (dot(mesh.normals[global], corner.normal) < 1.0f - 1e-5f) {
            return false;
        }
    }
    if (mesh.hasUVs()) {
        if (wrappedUvDistance(mesh.uvs[global], corner.uv) > 1e-5f) {
            return false;
        }
    }
    if (mesh.hasAO()) {
        if (std::abs(mesh.ao[global] - corner.ao) > 1e-5f) {
            return false;
        }
    }
    return true;
}

} // anonymous namespace
bool simplifyWithCornerAttributes(Mesh const& mesh, std::vector<uint32_t> const& source,
        CornerSimplifyOptions const& options, std::vector<uint32_t>* outIndices,
        std::vector<GeneratedVertex>* outGenerated, float* outWorldError) {
    if (outIndices == nullptr || outGenerated == nullptr) {
        return false;
    }
    outIndices->clear();
    outGenerated->clear();
    if (outWorldError != nullptr) {
        *outWorldError = 0.0f;
    }
    if (source.size() < 3 || options.targetIndexCount >= source.size()) {
        *outIndices = source;
        return false;
    }

    auto const setupStart = std::chrono::steady_clock::now();
    Unit unit(mesh);
    unit.hasNormals = mesh.hasNormals();
    unit.hasUVs = mesh.hasUVs();
    unit.hasAO = mesh.hasAO();

    // Weld every position. Seam duplicates therefore become one topological vertex even though
    // the triangles on either side still carry different UVs and normals.
    std::unordered_map<uint32_t, uint32_t> globalToWeld;
    std::unordered_map<PositionKey, uint32_t, PositionKeyHash> positionToWeld;
    globalToWeld.reserve(source.size());
    positionToWeld.reserve(source.size());

    auto weld = [&](uint32_t global) {
        auto inserted = globalToWeld.emplace(global, UINT32_MAX);
        if (!inserted.second) {
            return inserted.first->second;
        }
        PositionKey const key = positionKey(mesh.positions[global]);
        auto const positionInserted = positionToWeld.emplace(key, UINT32_MAX);
        if (positionInserted.second) {
            WeldVertex vertex;
            vertex.positionSource = global;
            vertex.position = mesh.positions[global];
            vertex.members.push_back(global);
            positionInserted.first->second = uint32_t(unit.vertices.size());
            unit.vertices.push_back(std::move(vertex));
        } else {
            unit.vertices[positionInserted.first->second].members.push_back(global);
        }
        inserted.first->second = positionInserted.first->second;
        return inserted.first->second;
    };

    auto cornerOf = [&](uint32_t global) {
        Corner corner;
        corner.sourceVertex = global;
        if (unit.hasNormals) {
            corner.normal = mesh.normals[global];
        }
        if (unit.hasUVs) {
            corner.uv = mesh.uvs[global];
        }
        if (unit.hasAO) {
            corner.ao = mesh.ao[global];
        }
        return corner;
    };

    for (size_t i = 0; i + 2 < source.size(); i += 3) {
        Triangle triangle;
        for (int k = 0; k < 3; ++k) {
            uint32_t const global = source[i + k];
            if (global >= mesh.vertexCount()) {
                *outIndices = source;
                return false;
            }
            triangle.vertices[k] = weld(global);
            triangle.corners[k] = cornerOf(global);
        }
        if (triangle.vertices[0] == triangle.vertices[1] ||
                triangle.vertices[1] == triangle.vertices[2] ||
                triangle.vertices[0] == triangle.vertices[2]) {
            continue;
        }
        triangle.key = { triangle.vertices[0], triangle.vertices[1], triangle.vertices[2] };
        std::sort(triangle.key.begin(), triangle.key.end());
        if (!unit.triangleKeys.insert(triangle.key).second) {
            continue;
        }
        unit.triangles.push_back(triangle);
        unit.aliveTriangles += 1;
    }

    if (unit.triangles.empty()) {
        *outIndices = source;
        return false;
    }

    unit.incident.assign(unit.vertices.size(), {});
    math::float3 lo = unit.vertices[0].position;
    math::float3 hi = lo;
    for (size_t t = 0; t < unit.triangles.size(); ++t) {
        for (uint32_t vertex: unit.triangles[t].vertices) {
            unit.incident[vertex].push_back(uint32_t(t));
            lo = min(lo, unit.vertices[vertex].position);
            hi = max(hi, unit.vertices[vertex].position);
        }
    }
    unit.extent = hi - lo;

    unit.edgeUse.reserve(unit.triangles.size() * 2);
    for (Triangle const& triangle: unit.triangles) {
        for (int e = 0; e < 3; ++e) {
            unit.edgeUse[edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3])] += 1;
        }
    }

    std::vector<Edge> edgeUses;
    edgeUses.reserve(unit.triangles.size() * 3);
    for (Triangle const& triangle: unit.triangles) {
        for (int e = 0; e < 3; ++e) {
            edgeUses.push_back(edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3]));
        }
    }
    std::sort(edgeUses.begin(), edgeUses.end());
    unit.borderEdges.reserve(edgeUses.size() / 2);
    for (size_t i = 0; i < edgeUses.size();) {
        size_t j = i + 1;
        while (j < edgeUses.size() && edgeUses[j] == edgeUses[i]) {
            ++j;
        }
        if (j - i > 2) {
            unit.hasNonManifold = true;
        }
        if (j - i == 1) {
            Edge const& edge = edgeUses[i];
            unit.borderEdges.push_back(edge);
            unit.vertices[edge.first].border = true;
            unit.vertices[edge.second].border = true;
        }
        i = j;
    }

    if (options.lockedVertices != nullptr) {
        std::vector<uint8_t> const& mask = *options.lockedVertices;
        for (WeldVertex& vertex: unit.vertices) {
            for (uint32_t member: vertex.members) {
                uint32_t position = member;
                if (options.vertexPositionIds != nullptr &&
                        member < options.vertexPositionIds->size()) {
                    position = (*options.vertexPositionIds)[member];
                }
                if (position < mask.size() && mask[position] != 0) {
                    vertex.locked = true;
                    vertex.border = true;
                    break;
                }
            }
        }
        for (Triangle const& triangle: unit.triangles) {
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = triangle.vertices[e];
                uint32_t const b = triangle.vertices[(e + 1) % 3];
                if (unit.vertices[a].locked && unit.vertices[b].locked) {
                    unit.lockedEdges.insert(edgeOf(a, b));
                }
            }
        }
    }

    // Position quadrics.
    std::vector<Quadric> quadrics(unit.vertices.size());
    for (Triangle const& triangle: unit.triangles) {
        math::float3 normal{};
        float area = 0.0f;
        if (!trianglePlane(unit.vertices[triangle.vertices[0]].position,
                    unit.vertices[triangle.vertices[1]].position,
                    unit.vertices[triangle.vertices[2]].position, &normal, &area)) {
            continue;
        }
        float const d = -dot(normal, unit.vertices[triangle.vertices[0]].position);
        for (uint32_t vertex: triangle.vertices) {
            quadricFromPlane(&quadrics[vertex], normal, d, area);
        }
    }

    // Boundary edges get a perpendicular plane so that open surfaces keep their outline even
    // when the caller allows border collapses.
    for (Edge const& edge: unit.borderEdges) {
        math::float3 const a = unit.vertices[edge.first].position;
        math::float3 const b = unit.vertices[edge.second].position;
        math::float3 direction = b - a;
        float const length2 = dot(direction, direction);
        if (!(length2 > 1e-20f)) {
            continue;
        }
        direction /= std::sqrt(length2);
        math::float3 normal{};
        for (uint32_t t: unit.incident[edge.first]) {
            if (!unit.triangles[t].alive || !containsVertex(unit.triangles[t], edge.second)) {
                continue;
            }
            math::float3 candidate{};
            float area = 0.0f;
            if (trianglePlane(unit.vertices[unit.triangles[t].vertices[0]].position,
                        unit.vertices[unit.triangles[t].vertices[1]].position,
                        unit.vertices[unit.triangles[t].vertices[2]].position, &candidate, &area)) {
                normal = candidate;
                break;
            }
        }
        math::float3 constraint = cross(direction, normal);
        float const constraintLength = length(constraint);
        if (!(constraintLength > 1e-20f)) {
            continue;
        }
        constraint /= constraintLength;
        float const d = -dot(constraint, a);
        float const weight = std::sqrt(length2) * 0.05f;
        quadricFromPlane(&quadrics[edge.first], constraint, d, weight);
        quadricFromPlane(&quadrics[edge.second], constraint, d, weight);
    }
    for (size_t i = 0; i < unit.vertices.size(); ++i) {
        unit.vertices[i].quadric = quadrics[i];
    }
    struct Candidate {
        float error = 0.0f;
        uint32_t remove = 0;
        uint32_t keep = 0;
        uint32_t removeVersion = 0;
        uint32_t keepVersion = 0;
        bool operator>(Candidate const& other) const noexcept { return error > other.error; }
    };
    using Queue = std::priority_queue<Candidate, std::vector<Candidate>, std::greater<Candidate>>;
    Queue queue;

    auto pushEdge = [&](uint32_t a, uint32_t b) {
        if (a == b || a >= unit.vertices.size() || b >= unit.vertices.size()) {
            return;
        }
        for (int direction = 0; direction < 2; ++direction) {
            uint32_t const remove = direction == 0 ? a : b;
            uint32_t const keep = direction == 0 ? b : a;
            CollapseEvaluation const evaluation = evaluateCollapse(unit, remove, keep, options);
            if (!evaluation.valid) {
                continue;
            }
            Candidate candidate;
            candidate.remove = remove;
            candidate.keep = keep;
            candidate.removeVersion = unit.vertices[remove].version;
            candidate.keepVersion = unit.vertices[keep].version;
            candidate.error = evaluation.priority;
            queue.push(candidate);
        }
    };

    std::unordered_set<Edge, EdgeHash> initialEdges;
    initialEdges.reserve(unit.triangles.size() * 3);
    for (Triangle const& triangle: unit.triangles) {
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = triangle.vertices[e];
            uint32_t const b = triangle.vertices[(e + 1) % 3];
            if (initialEdges.insert(edgeOf(a, b)).second) {
                pushEdge(a, b);
            }
        }
    }
    if (options.profile != nullptr) {
        options.profile->setupSeconds +=
                std::chrono::duration<double>(std::chrono::steady_clock::now() - setupStart)
                        .count();
    }

    float largestWorldError = 0.0f;
    thread_local std::vector<uint64_t> pushedEdges;
    size_t const maxIterations = unit.triangles.size() * 4 + 16;
    for (size_t iteration = 0; iteration < maxIterations; ++iteration) {
        if (unit.aliveTriangles * 3 <= options.targetIndexCount) {
            break;
        }
        bool applied = false;
        while (!queue.empty()) {
            Candidate const candidate = queue.top();
            queue.pop();
            if (candidate.remove >= unit.vertices.size() ||
                    candidate.keep >= unit.vertices.size()) {
                continue;
            }
            if (unit.vertices[candidate.remove].removed || unit.vertices[candidate.keep].removed ||
                    unit.vertices[candidate.remove].version != candidate.removeVersion ||
                    unit.vertices[candidate.keep].version != candidate.keepVersion) {
                continue;
            }
            CollapseEvaluation const evaluation =
                    evaluateCollapse(unit, candidate.remove, candidate.keep, options);
            if (!evaluation.valid) {
                continue;
            }
            {
                ScopedSeconds const applyTimer(
                        options.profile ? &options.profile->applySeconds : nullptr);
                applyCollapse(&unit, candidate.remove, candidate.keep, evaluation.targetPosition);
            }
            if (options.profile != nullptr) {
                options.profile->applied += 1;
            }
            largestWorldError = std::max(largestWorldError, evaluation.worldError);
            // Re-push the edges of every triangle the collapse rewrote. Shared edges occur
            // twice in that set (once per adjacent triangle), so deduplicating here roughly
            // halves the evaluations without changing which candidates enter the queue.
            pushedEdges.clear();
            auto pushUniqueEdge = [&](uint32_t a, uint32_t b) {
                uint64_t const key = (uint64_t(std::min(a, b)) << 32) | uint64_t(std::max(a, b));
                if (std::find(pushedEdges.begin(), pushedEdges.end(), key) != pushedEdges.end()) {
                    return;
                }
                pushedEdges.push_back(key);
                pushEdge(a, b);
            };
            for (auto const& [triangleIndex, replacement]: evaluation.replacements) {
                (void) triangleIndex;
                for (int e = 0; e < 3; ++e) {
                    pushUniqueEdge(replacement[e], replacement[(e + 1) % 3]);
                }
            }
            applied = true;
            break;
        }
        if (!applied) {
            break;
        }
    }

    std::unordered_map<GeneratedKey, uint32_t, GeneratedKeyHash> generatedIds;
    std::vector<std::array<uint32_t, 3>> outputIds(unit.triangles.size(),
            { UINT32_MAX, UINT32_MAX, UINT32_MAX });
    std::vector<std::vector<std::pair<uint32_t, uint8_t>>> cornersOf(unit.vertices.size());
    for (size_t t = 0; t < unit.triangles.size(); ++t) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        for (uint8_t k = 0; k < 3; ++k) {
            cornersOf[triangle.vertices[k]].emplace_back(uint32_t(t), k);
        }
    }

    auto emitGenerated = [&](WeldVertex const& vertex, uint32_t positionSource, math::float3 normal,
                                 math::float2 uv, float ao) {
        GeneratedVertex generated;
        generated.positionSource = positionSource;
        generated.position = vertex.position;
        generated.normal = normal;
        generated.uv = uv;
        generated.ao = ao;
        generated.hasPosition = true;
        GeneratedKey const key = generatedKey(generated);
        auto const inserted = generatedIds.emplace(key, uint32_t(outGenerated->size()));
        if (inserted.second) {
            outGenerated->push_back(generated);
        }
        return uint32_t(mesh.vertexCount()) + inserted.first->second;
    };

    for (size_t v = 0; v < unit.vertices.size(); ++v) {
        WeldVertex const& vertex = unit.vertices[v];
        auto const& corners = cornersOf[v];
        if (corners.empty()) {
            continue;
        }
        if (vertex.moved) {
            // All triangles that belong to one original chart vertex share a generated vertex.
            // Interpolating per triangle instead would split a smooth moved vertex once per
            // incident triangle and multiply the vertex buffer for no visual benefit.
            std::map<uint32_t, std::vector<std::pair<uint32_t, uint8_t>>> groups;
            for (auto const& cornerRef: corners) {
                Triangle const& triangle = unit.triangles[cornerRef.first];
                groups[triangle.corners[cornerRef.second].sourceVertex].push_back(cornerRef);
            }
            for (auto const& [sourceVertex, group]: groups) {
                // A moved vertex can be shared by several charts, or by triangles of one chart
                // that extrapolate the same source corner in different directions. Averaging
                // those UVs would smear the texture and was previously rejected by the gate.
                // Instead, partition the corners into attribute-compatible clusters and emit one
                // generated vertex per cluster. The position is identical, so the surface stays
                // closed, while every chart keeps its own parameterization.
                struct CornerCluster {
                    math::float3 normal{};
                    math::float2 referenceUv{};
                    math::float2 uvDelta{};
                    float ao = 0.0f;
                    size_t count = 0;
                    std::vector<std::pair<uint32_t, uint8_t>> corners;
                };

                std::vector<CornerCluster> clusters;
                float const uvTolerance = std::max(options.maxUvError * 0.1f, 1e-6f);
                bool const splitByUv = unit.hasUVs && options.splitDivergentUv;
                for (auto const& cornerRef: group) {
                    Triangle const& triangle = unit.triangles[cornerRef.first];
                    Corner const& corner = triangle.corners[cornerRef.second];
                    CornerCluster* target = clusters.empty() ? nullptr : &clusters.front();
                    if (splitByUv) {
                        target = nullptr;
                        for (CornerCluster& cluster: clusters) {
                            if (wrappedUvDistance(cluster.referenceUv, corner.uv) <= uvTolerance) {
                                target = &cluster;
                                break;
                            }
                        }
                    }
                    if (target == nullptr) {
                        clusters.emplace_back();
                        target = &clusters.back();
                        target->referenceUv = corner.uv;
                    }
                    math::float2 delta = corner.uv - target->referenceUv;
                    delta.x -= std::round(delta.x);
                    delta.y -= std::round(delta.y);
                    target->uvDelta += delta;
                    target->normal += corner.normal;
                    target->ao += corner.ao;
                    target->count += 1;
                    target->corners.push_back(cornerRef);
                }

                for (CornerCluster const& cluster: clusters) {
                    math::float3 normal = cluster.normal;
                    float const normalLength = length(normal);
                    if (normalLength > 1e-12f) {
                        normal /= normalLength;
                    }
                    float const inverseCount = 1.0f / float(cluster.count);
                    math::float2 const uv = cluster.referenceUv + cluster.uvDelta * inverseCount;
                    float const ao = cluster.ao * inverseCount;
                    uint32_t const id = emitGenerated(vertex, sourceVertex, normal, uv, ao);
                    for (auto const& cornerRef: cluster.corners) {
                        outputIds[cornerRef.first][cornerRef.second] = id;
                    }
                }
            }
        } else {
            for (auto const& cornerRef: corners) {
                Triangle const& triangle = unit.triangles[cornerRef.first];
                Corner const& corner = triangle.corners[cornerRef.second];
                uint32_t id = UINT32_MAX;
                if (corner.sourceVertex < mesh.vertexCount() &&
                        attributesMatch(mesh, corner.sourceVertex, corner)) {
                    id = corner.sourceVertex;
                }
                if (id == UINT32_MAX) {
                    id = emitGenerated(
                            vertex, corner.sourceVertex, corner.normal, corner.uv, corner.ao);
                }
                outputIds[cornerRef.first][cornerRef.second] = id;
            }
        }
    }

    for (size_t t = 0; t < unit.triangles.size(); ++t) {
        if (!unit.triangles[t].alive) {
            continue;
        }
        for (int k = 0; k < 3; ++k) {
            outIndices->push_back(outputIds[t][k]);
        }
    }

    if (outWorldError != nullptr) {
        *outWorldError = largestWorldError;
    }
    return outIndices->size() < source.size();
}

void appendGeneratedVertices(Mesh* mesh, std::vector<GeneratedVertex> const& generated) {
    if (mesh == nullptr || generated.empty()) {
        return;
    }
    size_t const base = mesh->positions.size();
    bool const hasNormals = mesh->hasNormals();
    bool const hasUVs = mesh->hasUVs();
    bool const hasAO = mesh->hasAO();
    mesh->positions.reserve(base + generated.size());
    if (hasNormals) {
        mesh->normals.reserve(base + generated.size());
    }
    if (hasUVs) {
        mesh->uvs.reserve(base + generated.size());
    }
    if (hasAO) {
        mesh->ao.reserve(base + generated.size());
    }
    for (GeneratedVertex const& vertex: generated) {
        mesh->positions.push_back(
                vertex.hasPosition ? vertex.position : mesh->positions[vertex.positionSource]);
        if (hasNormals) {
            mesh->normals.push_back(vertex.normal);
        }
        if (hasUVs) {
            mesh->uvs.push_back(vertex.uv);
        }
        if (hasAO) {
            mesh->ao.push_back(vertex.ao);
        }
    }
}

} // namespace manymesh
} // namespace filament
