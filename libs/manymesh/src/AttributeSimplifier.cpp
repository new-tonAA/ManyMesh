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

#include <manymesh/AttributeSimplifier.h>

#include <algorithm>
#include <array>
#include <cmath>
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

bool triangleNormal(Mesh const& mesh, math::float3 const& a, math::float3 const& b,
        math::float3 const& c, math::float3* normal, float* area) {
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

float triangleQuality(math::float3 const& a, math::float3 const& b, math::float3 const& c) {
    math::float3 const ab = b - a;
    math::float3 const ac = c - a;
    float const area2 = length(cross(ab, ac));
    float const denominator = dot(ab, ab) + dot(ac, ac) + dot(c - b, c - b);
    if (!(denominator > 0.0f) || !(area2 > 0.0f)) {
        return 0.0f;
    }
    return std::clamp(2.0f * std::sqrt(3.0f) * area2 / denominator, 0.0f, 1.0f);
}

float normalAngle(math::float3 a, math::float3 b) {
    float const la = length(a);
    float const lb = length(b);
    if (!(la > 0.0f) || !(lb > 0.0f)) {
        return 0.0f;
    }
    return std::acos(std::clamp(dot(a, b) / (la * lb), -1.0f, 1.0f));
}

float wrappedUvDistance(math::float2 a, math::float2 b) {
    math::float2 delta = a - b;
    delta.x -= std::round(delta.x);
    delta.y -= std::round(delta.y);
    return length(delta);
}

using TriangleKey = std::array<uint32_t, 3>;
using Edge = std::pair<uint32_t, uint32_t>;

struct TriangleKeyHash {
    size_t operator()(TriangleKey const& key) const noexcept {
        uint64_t hash = uint64_t(key[0]) * 0x9E3779B185EBCA87ull;
        hash ^= uint64_t(key[1]) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        hash ^= uint64_t(key[2]) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        return size_t(hash);
    }
};

struct EdgeHash {
    size_t operator()(Edge const& edge) const noexcept {
        uint64_t hash = uint64_t(edge.first) * 0x9E3779B185EBCA87ull;
        hash ^= uint64_t(edge.second) + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        return size_t(hash);
    }
};

Edge edgeOf(uint32_t a, uint32_t b) { return { std::min(a, b), std::max(a, b) }; }

TriangleKey triangleKey(std::array<uint32_t, 3> triangle) {
    std::sort(triangle.begin(), triangle.end());
    return triangle;
}

struct Vertex {
    uint32_t global = 0;
    math::float3 position{};
    math::float3 normal{};
    math::float2 uv{};
    Quadric quadric;
    uint32_t version = 0;
    bool border = false;
    bool locked = false;
    bool removed = false;
};

struct Triangle {
    std::array<uint32_t, 3> vertices{};
    TriangleKey key{};
    bool alive = true;
};

struct Candidate {
    float error = 0.0f;
    uint32_t remove = 0;
    uint32_t keep = 0;
    uint32_t removeVersion = 0;
    uint32_t keepVersion = 0;

    bool operator>(Candidate const& other) const noexcept { return error > other.error; }
};

struct Unit {
    Mesh const& mesh;
    std::vector<Vertex> vertices;
    std::vector<uint32_t> localToGlobal;
    std::vector<Triangle> triangles;
    std::vector<std::vector<uint32_t>> incident;
    std::unordered_set<TriangleKey, TriangleKeyHash> triangleKeys;
    //! Sorted and unique. Membership is a binary search, while iteration order stays
    //! deterministic for the quadric accumulation below.
    std::vector<Edge> borderEdges;
    size_t aliveTriangles = 0;
    math::float3 extent{};

    explicit Unit(Mesh const& source)
            : mesh(source) {}
};

uint32_t localVertex(Unit* unit, std::unordered_map<uint32_t, uint32_t>* globalToLocal,
        uint32_t global) {
    auto const inserted = globalToLocal->emplace(global, uint32_t(unit->vertices.size()));
    if (!inserted.second) {
        return inserted.first->second;
    }
    Vertex vertex;
    vertex.global = global;
    vertex.position = unit->mesh.positions[global];
    if (unit->mesh.hasNormals()) {
        vertex.normal = unit->mesh.normals[global];
    }
    if (unit->mesh.hasUVs()) {
        vertex.uv = unit->mesh.uvs[global];
    }
    unit->vertices.push_back(vertex);
    return uint32_t(unit->vertices.size() - 1);
}

void rebuildGeometry(Unit* unit, std::vector<uint32_t> const& source) {
    std::unordered_map<uint32_t, uint32_t> globalToLocal;
    globalToLocal.reserve(source.size());
    unit->vertices.clear();
    unit->triangles.clear();
    unit->aliveTriangles = 0;

    for (size_t i = 0; i + 2 < source.size(); i += 3) {
        std::array<uint32_t, 3> const triangle = {
            localVertex(unit, &globalToLocal, source[i + 0]),
            localVertex(unit, &globalToLocal, source[i + 1]),
            localVertex(unit, &globalToLocal, source[i + 2]),
        };
        if (triangle[0] == triangle[1] || triangle[1] == triangle[2] ||
                triangle[2] == triangle[0]) {
            continue;
        }
        Triangle entry;
        entry.vertices = triangle;
        entry.key = triangleKey(triangle);
        if (!unit->triangleKeys.insert(entry.key).second) {
            continue;
        }
        unit->triangles.push_back(entry);
        unit->aliveTriangles += 1;
    }

    unit->localToGlobal.clear();
    unit->localToGlobal.reserve(unit->vertices.size());
    for (Vertex const& vertex: unit->vertices) {
        unit->localToGlobal.push_back(vertex.global);
    }

    unit->incident.assign(unit->vertices.size(), {});
    math::float3 lo = unit->vertices.empty() ? math::float3{} : unit->vertices[0].position;
    math::float3 hi = lo;
    for (size_t t = 0; t < unit->triangles.size(); ++t) {
        Triangle const& triangle = unit->triangles[t];
        for (uint32_t vertex: triangle.vertices) {
            unit->incident[vertex].push_back(uint32_t(t));
            lo = min(lo, unit->vertices[vertex].position);
            hi = max(hi, unit->vertices[vertex].position);
        }
    }
    unit->extent = hi - lo;

    std::vector<Edge> edgeUses;
    edgeUses.reserve(unit->triangles.size() * 3);
    for (Triangle const& triangle: unit->triangles) {
        for (int e = 0; e < 3; ++e) {
            edgeUses.push_back(edgeOf(triangle.vertices[e], triangle.vertices[(e + 1) % 3]));
        }
    }
    std::sort(edgeUses.begin(), edgeUses.end());
    unit->borderEdges.reserve(edgeUses.size() / 2);
    for (size_t i = 0; i < edgeUses.size();) {
        size_t j = i + 1;
        while (j < edgeUses.size() && edgeUses[j] == edgeUses[i]) {
            ++j;
        }
        if (j - i == 1) {
            Edge const& edge = edgeUses[i];
            unit->borderEdges.push_back(edge);
            unit->vertices[edge.first].border = true;
            unit->vertices[edge.second].border = true;
        }
        i = j;
    }

    std::vector<Quadric> quadrics(unit->vertices.size());
    for (Triangle const& triangle: unit->triangles) {
        math::float3 normal{};
        float area = 0.0f;
        if (!triangleNormal(unit->mesh, unit->vertices[triangle.vertices[0]].position,
                    unit->vertices[triangle.vertices[1]].position,
                    unit->vertices[triangle.vertices[2]].position, &normal, &area)) {
            continue;
        }
        float const d = -dot(normal, unit->vertices[triangle.vertices[0]].position);
        for (uint32_t vertex: triangle.vertices) {
            quadricFromPlane(&quadrics[vertex], normal, d, area);
        }
    }

    // Boundary edges get a second, perpendicular plane so that open surfaces keep their
    // outline even when the caller allows border collapses.
    for (Edge const& edge: unit->borderEdges) {
        math::float3 const a = unit->vertices[edge.first].position;
        math::float3 const b = unit->vertices[edge.second].position;
        math::float3 direction = b - a;
        float const length2 = dot(direction, direction);
        if (!(length2 > 1e-20f)) {
            continue;
        }
        direction /= std::sqrt(length2);
        // Any direction perpendicular to the edge works; use the triangle normal's cross
        // product when possible so the constraint faces outward from the surface.
        math::float3 normal{};
        for (uint32_t t: unit->incident[edge.first]) {
            float area = 0.0f;
            if (triangleNormal(unit->mesh, unit->vertices[unit->triangles[t].vertices[0]].position,
                        unit->vertices[unit->triangles[t].vertices[1]].position,
                        unit->vertices[unit->triangles[t].vertices[2]].position, &normal, &area)) {
                bool const containsBoth = std::find(unit->triangles[t].vertices.begin(),
                                                  unit->triangles[t].vertices.end(), edge.first) !=
                                                  unit->triangles[t].vertices.end() &&
                                          std::find(unit->triangles[t].vertices.begin(),
                                                  unit->triangles[t].vertices.end(),
                                                  edge.second) != unit->triangles[t].vertices.end();
                if (containsBoth) {
                    break;
                }
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

    for (size_t i = 0; i < unit->vertices.size(); ++i) {
        unit->vertices[i].quadric = quadrics[i];
    }
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
    return std::binary_search(unit.borderEdges.begin(), unit.borderEdges.end(), edgeOf(a, b));
}

struct CollapseEvaluation {
    bool valid = false;
    float cost = 0.0f;
    float normalError = 0.0f;
    float uvError = 0.0f;
    float positionError = 0.0f;
    float worldError = 0.0f;
    std::vector<std::pair<uint32_t, std::array<uint32_t, 3>>> replacements;
};

CollapseEvaluation evaluateCollapse(Unit const& unit, uint32_t remove, uint32_t keep,
        AttributeSimplifyOptions const& options) {
    CollapseEvaluation result;
    if (remove == keep || unit.vertices[remove].removed || unit.vertices[keep].removed) {
        return result;
    }
    if (unit.vertices[remove].locked) {
        return result;
    }
    if (options.lockBorder && unit.vertices[remove].border) {
        return result;
    }
    if (unit.vertices[keep].locked) {
        // A locked vertex must not gain an edge to another locked vertex: that edge would cut
        // across the seam shared with the neighbouring unit. The other side can create the
        // same chord, which leaves overlapping triangles after the cut is assembled.
        for (uint32_t t: unit.incident[remove]) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive) {
                continue;
            }
            bool hasKeep = false;
            for (uint32_t vertex: triangle.vertices) {
                hasKeep = hasKeep || vertex == keep;
            }
            if (hasKeep) {
                continue;
            }
            for (uint32_t vertex: triangle.vertices) {
                if (vertex != remove && unit.vertices[vertex].locked) {
                    return result;
                }
            }
        }
    }

    // Keeping border *vertices* is not enough: collapsing an interior vertex into a border
    // vertex can delete a triangle that owns a border edge, which shortens or shifts the
    // outline and leaves a crack against the neighbouring cluster. Reject any collapse that
    // would remove a triangle containing a border edge. Border vertices are never moved by a
    // collapse, so this preserves the outline exactly.
    if (options.lockBorder) {
        for (uint32_t t: unit.incident[remove]) {
            Triangle const& triangle = unit.triangles[t];
            if (!triangle.alive) {
                continue;
            }
            bool hasKeep = false;
            for (uint32_t vertex: triangle.vertices) {
                hasKeep = hasKeep || vertex == keep;
            }
            if (hasKeep) {
                // This triangle survives, but if it owns a border edge through `remove` that
                // edge is either rewritten as (keep, x) or collapses to (keep, keep). Both
                // change the outline. Edges not touching `remove` are unaffected.
                for (int e = 0; e < 3; ++e) {
                    uint32_t const a = triangle.vertices[e];
                    uint32_t const b = triangle.vertices[(e + 1) % 3];
                    if ((a == remove || b == remove) && isBorderEdge(unit, a, b)) {
                        return result;
                    }
                }
                continue;
            }
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = triangle.vertices[e];
                uint32_t const b = triangle.vertices[(e + 1) % 3];
                if (isBorderEdge(unit, a, b)) {
                    return result;
                }
            }
        }
    }

    std::vector<uint32_t> removeNeighbors;
    std::vector<uint32_t> keepNeighbors;
    removeNeighbors.reserve(unit.incident[remove].size() * 3);
    keepNeighbors.reserve(unit.incident[keep].size() * 3);
    addNeighbors(unit, remove, &removeNeighbors);
    addNeighbors(unit, keep, &keepNeighbors);
    auto sortUnique = [](std::vector<uint32_t>* values) {
        std::sort(values->begin(), values->end());
        values->erase(std::unique(values->begin(), values->end()), values->end());
    };
    sortUnique(&removeNeighbors);
    sortUnique(&keepNeighbors);
    uint32_t sharedEdgeTriangles = 0;
    uint32_t commonNeighbors = 0;
    for (size_t i = 0, j = 0; i < removeNeighbors.size() && j < keepNeighbors.size();) {
        if (removeNeighbors[i] == keepNeighbors[j]) {
            commonNeighbors += 1;
            ++i;
            ++j;
        } else if (removeNeighbors[i] < keepNeighbors[j]) {
            ++i;
        } else {
            ++j;
        }
    }
    for (uint32_t t: unit.incident[remove]) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        bool hasKeep = false;
        for (uint32_t vertex: triangle.vertices) {
            hasKeep = hasKeep || vertex == keep;
        }
        if (hasKeep) {
            sharedEdgeTriangles += 1;
        }
    }
    if (sharedEdgeTriangles == 0 || sharedEdgeTriangles > 2) {
        return result;
    }
    uint32_t const requiredCommon = sharedEdgeTriangles == 2 ? 2u : 1u;
    if (commonNeighbors != requiredCommon && !(sharedEdgeTriangles == 1 && !options.lockBorder)) {
        return result;
    }

    math::float3 const oldRemoveNormal = unit.vertices[remove].normal;
    math::float3 const oldKeepNormal = unit.vertices[keep].normal;
    result.normalError = normalAngle(oldRemoveNormal, oldKeepNormal);
    result.uvError = wrappedUvDistance(unit.vertices[remove].uv, unit.vertices[keep].uv);
    result.worldError = length(unit.vertices[remove].position - unit.vertices[keep].position);
    float const maxNormal = options.maxNormalErrorDegrees * 3.14159265358979323846f / 180.0f;
    if (result.normalError > maxNormal || result.uvError > options.maxUvError) {
        return result;
    }

    Quadric combined = unit.vertices[remove].quadric;
    combined.add(unit.vertices[keep].quadric);
    result.positionError = std::max(0.0f, combined.evaluate(unit.vertices[keep].position));

    std::vector<TriangleKey> newKeys;
    newKeys.reserve(unit.incident[remove].size());
    result.replacements.reserve(unit.incident[remove].size());
    bool const keepIsBorder = unit.vertices[keep].border;
    for (uint32_t t: unit.incident[remove]) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        std::array<uint32_t, 3> replaced = triangle.vertices;
        bool containsKeep = false;
        for (uint32_t& vertex: replaced) {
            containsKeep = containsKeep || vertex == keep;
        }
        if (containsKeep) {
            continue; // collapses to a degenerate triangle
        }
        for (uint32_t& vertex: replaced) {
            if (vertex == remove) {
                vertex = keep;
            }
        }
        if (replaced[0] == replaced[1] || replaced[1] == replaced[2] ||
                replaced[2] == replaced[0]) {
            return result;
        }
        if (options.lockBorder && keepIsBorder) {
            // Replacing a vertex of a border-adjacent triangle with another border vertex can
            // create a shortcut chord across the unit's outline. The neighbouring cluster can
            // make the same shortcut from its side, which leaves two overlapping triangles and
            // a non-manifold edge after the cut is assembled. Interior targets are safe.
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = triangle.vertices[e];
                uint32_t const b = triangle.vertices[(e + 1) % 3];
                if (isBorderEdge(unit, a, b)) {
                    return result;
                }
            }
        }
        float const quality = triangleQuality(unit.vertices[replaced[0]].position,
                unit.vertices[replaced[1]].position, unit.vertices[replaced[2]].position);
        if (quality < options.minTriangleQuality) {
            return result;
        }

        math::float3 const oldNormal = cross(unit.vertices[triangle.vertices[1]].position -
                                                     unit.vertices[triangle.vertices[0]].position,
                unit.vertices[triangle.vertices[2]].position -
                        unit.vertices[triangle.vertices[0]].position);
        math::float3 const newNormal =
                cross(unit.vertices[replaced[1]].position - unit.vertices[replaced[0]].position,
                        unit.vertices[replaced[2]].position - unit.vertices[replaced[0]].position);
        if (!(length(oldNormal) > 1e-20f) || !(length(newNormal) > 1e-20f) ||
                dot(normalize(oldNormal), normalize(newNormal)) < 0.1f) {
            return result;
        }

        TriangleKey const key = triangleKey(replaced);
        if (unit.triangleKeys.count(key) != 0 ||
                std::find(newKeys.begin(), newKeys.end(), key) != newKeys.end()) {
            return result;
        }
        newKeys.push_back(key);
        result.replacements.emplace_back(t, replaced);
    }

    // Validate the resulting one-ring locally. The global quality gate catches an increase in
    // non-manifold edges after the fact, but rejecting the collapse here keeps the QEM from
    // walking into a topology dead end where every later candidate also fails.
    std::vector<uint32_t> const& seeds = unit.incident[remove];
    std::vector<uint32_t> localTriangles;
    localTriangles.reserve(seeds.size() * 4);
    for (uint32_t t: unit.incident[remove]) {
        if (unit.triangles[t].alive) {
            localTriangles.push_back(t);
        }
    }
    // Only the triangles touching the removed vertex's one-ring participate. Iterating the
    // set while inserting would walk the whole connected component on every candidate.
    for (uint32_t t: seeds) {
        if (!unit.triangles[t].alive) {
            continue;
        }
        for (uint32_t vertex: unit.triangles[t].vertices) {
            for (uint32_t incident: unit.incident[vertex]) {
                if (unit.triangles[incident].alive) {
                    localTriangles.push_back(incident);
                }
            }
        }
    }
    std::sort(localTriangles.begin(), localTriangles.end());
    localTriangles.erase(std::unique(localTriangles.begin(), localTriangles.end()),
            localTriangles.end());

    std::vector<Edge> localEdges;
    localEdges.reserve(localTriangles.size() * 3);
    for (uint32_t t: localTriangles) {
        std::array<uint32_t, 3> vertices = unit.triangles[t].vertices;
        bool replacedTriangle = false;
        for (auto const& [triangleIndex, replacement]: result.replacements) {
            if (triangleIndex == t) {
                vertices = replacement;
                replacedTriangle = true;
                break;
            }
        }
        if (!replacedTriangle) {
            bool touchesRemovedVertex = false;
            for (uint32_t vertex: vertices) {
                touchesRemovedVertex = touchesRemovedVertex || vertex == remove;
            }
            if (touchesRemovedVertex) {
                continue; // this triangle is removed by the collapse
            }
        }
        for (int e = 0; e < 3; ++e) {
            localEdges.push_back(edgeOf(vertices[e], vertices[(e + 1) % 3]));
        }
    }
    std::sort(localEdges.begin(), localEdges.end());
    for (size_t i = 0; i < localEdges.size();) {
        size_t j = i + 1;
        while (j < localEdges.size() && localEdges[j] == localEdges[i]) {
            ++j;
        }
        size_t const use = j - i;
        if (use > 2) {
            return result;
        }
        if (options.lockBorder && use != 1 &&
                std::binary_search(unit.borderEdges.begin(), unit.borderEdges.end(),
                        localEdges[i])) {
            // A border edge belongs to exactly one triangle of this unit; the other side is the
            // neighbouring unit. Any extra use here is a fold that becomes non-manifold later.
            return result;
        }
        i = j;
    }

    float const extent2 = std::max(dot(unit.extent, unit.extent), 1e-12f);
    float const positionTerm = result.positionError / extent2;
    float const normalTerm = result.normalError * result.normalError;
    float const uvTerm = result.uvError * result.uvError;
    result.cost = options.positionWeight * positionTerm + options.normalWeight * normalTerm +
                  options.uvWeight * uvTerm;
    result.valid = true;
    return result;
}

bool applyCollapse(Unit* unit, uint32_t remove, uint32_t keep,
        CollapseEvaluation const& evaluation) {
    Vertex& source = unit->vertices[remove];
    Vertex& target = unit->vertices[keep];
    std::vector<uint32_t> const affected = unit->incident[remove];
    std::vector<uint32_t> replacedTriangles;
    replacedTriangles.reserve(evaluation.replacements.size());
    for (auto const& [triangleIndex, replacement]: evaluation.replacements) {
        replacedTriangles.push_back(triangleIndex);
    }
    std::sort(replacedTriangles.begin(), replacedTriangles.end());

    for (auto const& [triangleIndex, replacement]: evaluation.replacements) {
        Triangle& triangle = unit->triangles[triangleIndex];
        unit->triangleKeys.erase(triangle.key);
        triangle.vertices = replacement;
        triangle.key = triangleKey(replacement);
        unit->triangleKeys.insert(triangle.key);
        if (std::find(unit->incident[keep].begin(), unit->incident[keep].end(), triangleIndex) ==
                unit->incident[keep].end()) {
            unit->incident[keep].push_back(triangleIndex);
        }
    }

    for (uint32_t t: affected) {
        if (std::binary_search(replacedTriangles.begin(), replacedTriangles.end(), t)) {
            continue;
        }
        Triangle& triangle = unit->triangles[t];
        if (!triangle.alive) {
            continue;
        }
        triangle.alive = false;
        unit->triangleKeys.erase(triangle.key);
        unit->aliveTriangles -= 1;
        for (uint32_t vertex: triangle.vertices) {
            auto& list = unit->incident[vertex];
            list.erase(std::remove(list.begin(), list.end(), t), list.end());
        }
    }
    unit->incident[remove].clear();
    source.removed = true;
    source.version += 1;
    target.version += 1;
    target.quadric.add(source.quadric);
    return true;
}

} // anonymous namespace

bool simplifyWithAttributes(Mesh const& mesh, std::vector<uint32_t> const& source,
        AttributeSimplifyOptions const& options, std::vector<uint32_t>* outIndices,
        float* outWorldError) {
    if (outIndices == nullptr) {
        return false;
    }
    outIndices->clear();
    if (outWorldError != nullptr) {
        *outWorldError = 0.0f;
    }
    if (source.size() < 3 || options.targetIndexCount >= source.size()) {
        *outIndices = source;
        return false;
    }

    Unit unit(mesh);
    rebuildGeometry(&unit, source);
    if (unit.triangles.empty()) {
        *outIndices = source;
        return false;
    }
    if (options.lockedVertices != nullptr) {
        for (size_t i = 0; i < unit.vertices.size(); ++i) {
            uint32_t const global = unit.localToGlobal[i];
            if (global < options.lockedVertices->size() && (*options.lockedVertices)[global] != 0) {
                unit.vertices[i].border = true;
                unit.vertices[i].locked = true;
            }
        }
    }

    using Queue = std::priority_queue<Candidate, std::vector<Candidate>, std::greater<Candidate>>;
    Queue queue;
    auto pushEdge = [&](uint32_t a, uint32_t b) {
        if (a == b || unit.vertices[a].removed || unit.vertices[b].removed) {
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
            candidate.error = evaluation.cost;
            queue.push(candidate);
        }
    };

    // Each interior edge is shared by two triangles. Evaluating it once here halves the
    // number of initial collapse candidates without changing which collapses are considered.
    std::unordered_set<Edge, EdgeHash> initialEdges;
    initialEdges.reserve(unit.triangles.size() * 3);
    for (size_t t = 0; t < unit.triangles.size(); ++t) {
        Triangle const& triangle = unit.triangles[t];
        if (!triangle.alive) {
            continue;
        }
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = triangle.vertices[e];
            uint32_t const b = triangle.vertices[(e + 1) % 3];
            if (initialEdges.insert(edgeOf(a, b)).second) {
                pushEdge(a, b);
            }
        }
    }

    float largestWorldError = 0.0f;
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
            applyCollapse(&unit, candidate.remove, candidate.keep, evaluation);
            largestWorldError = std::max(largestWorldError, evaluation.worldError);
            for (auto const& [triangleIndex, replacement]: evaluation.replacements) {
                for (int e = 0; e < 3; ++e) {
                    pushEdge(replacement[e], replacement[(e + 1) % 3]);
                }
            }
            applied = true;
            break;
        }
        if (!applied) {
            break;
        }
    }

    outIndices->clear();
    outIndices->reserve(unit.aliveTriangles * 3);
    for (Triangle const& triangle: unit.triangles) {
        if (!triangle.alive) {
            continue;
        }
        for (uint32_t vertex: triangle.vertices) {
            outIndices->push_back(unit.localToGlobal[vertex]);
        }
    }
    if (outWorldError != nullptr) {
        *outWorldError = largestWorldError;
    }
    return outIndices->size() < source.size();
}

} // namespace manymesh
} // namespace filament
