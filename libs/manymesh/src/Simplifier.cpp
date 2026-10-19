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

#include "Parallel.h"

#include <manymesh/AttributeSimplifier.h>
#include <manymesh/Simplifier.h>

#include <meshoptimizer.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

void removeDegenerateAndDuplicateTriangles(Mesh const& mesh, std::vector<uint32_t>* indices) {
    std::vector<uint32_t> cleaned;
    cleaned.reserve(indices->size());

    for (size_t i = 0; i + 2 < indices->size(); i += 3) {
        uint32_t const a = (*indices)[i + 0];
        uint32_t const b = (*indices)[i + 1];
        uint32_t const c = (*indices)[i + 2];
        if (a == b || b == c || c == a) {
            continue;
        }
        math::float3 const ab = mesh.positions[b] - mesh.positions[a];
        math::float3 const ac = mesh.positions[c] - mesh.positions[a];
        if (!(length(cross(ab, ac)) > 1e-12f)) {
            continue;
        }
        cleaned.push_back(a);
        cleaned.push_back(b);
        cleaned.push_back(c);
    }

    // Remove duplicate faces while keeping the first occurrence, which preserves the original
    // winding and therefore the visible side of the surface.
    std::vector<std::array<uint32_t, 3>> keys;
    keys.reserve(cleaned.size() / 3);
    for (size_t i = 0; i + 2 < cleaned.size(); i += 3) {
        std::array<uint32_t, 3> key = { cleaned[i], cleaned[i + 1], cleaned[i + 2] };
        std::sort(key.begin(), key.end());
        keys.push_back(key);
    }

    std::vector<size_t> order(keys.size());
    for (size_t i = 0; i < order.size(); ++i) {
        order[i] = i;
    }
    std::sort(order.begin(), order.end(),
            [&keys](size_t a, size_t b) { return keys[a] < keys[b]; });

    std::vector<uint8_t> keep(keys.size(), 1);
    for (size_t i = 1; i < order.size(); ++i) {
        size_t const current = order[i];
        size_t const previous = order[i - 1];
        if (keys[current] == keys[previous] && keep[previous] != 0) {
            keep[current] = 0;
        }
    }

    std::vector<uint32_t> deduplicated;
    deduplicated.reserve(cleaned.size());
    for (size_t t = 0; t < keep.size(); ++t) {
        if (keep[t] == 0) {
            continue;
        }
        deduplicated.push_back(cleaned[t * 3 + 0]);
        deduplicated.push_back(cleaned[t * 3 + 1]);
        deduplicated.push_back(cleaned[t * 3 + 2]);
    }
    indices->swap(deduplicated);
}

float normalizedTriangleQuality(Mesh const& mesh, uint32_t a, uint32_t b, uint32_t c) {
    math::float3 const ab = mesh.positions[b] - mesh.positions[a];
    math::float3 const ac = mesh.positions[c] - mesh.positions[a];
    float const area2 = length(cross(ab, ac));
    float const bc2 =
            dot(mesh.positions[c] - mesh.positions[b], mesh.positions[c] - mesh.positions[b]);
    float const denominator = dot(ab, ab) + dot(ac, ac) + bc2;
    if (!(denominator > 0.0f) || !(area2 > 0.0f)) {
        return 0.0f;
    }
    return std::clamp(2.0f * std::sqrt(3.0f) * area2 / denominator, 0.0f, 1.0f);
}

bool collapseSliverEdge(Mesh const& mesh, std::vector<uint32_t>* indices, uint32_t remove,
        uint32_t keep, std::set<uint32_t> const& borderVertices,
        std::set<std::pair<uint32_t, uint32_t>> const& borderEdges,
        std::vector<uint8_t> const* lockedVertices) {
    if (remove == keep || borderVertices.count(remove) != 0) {
        return false;
    }
    if (lockedVertices != nullptr && remove < lockedVertices->size() &&
            (*lockedVertices)[remove] != 0) {
        return false;
    }

    std::vector<std::pair<size_t, math::float3>> affected;
    std::set<uint32_t> removeNeighbors;
    std::set<uint32_t> keepNeighbors;
    for (size_t i = 0; i + 2 < indices->size(); i += 3) {
        uint32_t const triangle[3] = { (*indices)[i], (*indices)[i + 1], (*indices)[i + 2] };
        bool hasRemove = false;
        bool hasKeep = false;
        for (uint32_t vertex: triangle) {
            hasRemove = hasRemove || vertex == remove;
            hasKeep = hasKeep || vertex == keep;
        }
        if (hasRemove && !hasKeep) {
            if (lockedVertices != nullptr && keep < lockedVertices->size() &&
                    (*lockedVertices)[keep] != 0) {
                for (uint32_t vertex: triangle) {
                    if (vertex != remove && vertex != keep && vertex < lockedVertices->size() &&
                            (*lockedVertices)[vertex] != 0) {
                        return false;
                    }
                }
            }
            // Removing this triangle must not delete a boundary edge, otherwise the repair
            // would trade a sliver for a crack along the unit's outline.
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = triangle[e];
                uint32_t const b = triangle[(e + 1) % 3];
                if (borderEdges.count({ std::min(a, b), std::max(a, b) }) != 0) {
                    return false;
                }
            }
            math::float3 const ab = mesh.positions[triangle[1]] - mesh.positions[triangle[0]];
            math::float3 const ac = mesh.positions[triangle[2]] - mesh.positions[triangle[0]];
            affected.emplace_back(i, normalize(cross(ab, ac)));
        }
        if (hasRemove || hasKeep) {
            for (uint32_t vertex: triangle) {
                if (vertex == remove) {
                    continue;
                }
                if (hasRemove && vertex != keep) {
                    removeNeighbors.insert(vertex);
                }
            }
            for (uint32_t vertex: triangle) {
                if (vertex == keep) {
                    continue;
                }
                if (hasKeep && vertex != remove) {
                    keepNeighbors.insert(vertex);
                }
            }
        }
    }

    std::vector<uint32_t> common;
    std::set_intersection(removeNeighbors.begin(), removeNeighbors.end(), keepNeighbors.begin(),
            keepNeighbors.end(), std::back_inserter(common));
    if (common.size() != 2) {
        return false;
    }

    for (auto const& [offset, oldNormal]: affected) {
        uint32_t replaced[3] = { (*indices)[offset + 0], (*indices)[offset + 1],
            (*indices)[offset + 2] };
        for (uint32_t& vertex: replaced) {
            if (vertex == remove) {
                vertex = keep;
            }
        }
        math::float3 const ab = mesh.positions[replaced[1]] - mesh.positions[replaced[0]];
        math::float3 const ac = mesh.positions[replaced[2]] - mesh.positions[replaced[0]];
        math::float3 const newNormal = cross(ab, ac);
        if (!(length(newNormal) > 1e-12f) || dot(normalize(newNormal), oldNormal) < 0.1f) {
            return false;
        }
    }

    std::vector<uint32_t> cleaned;
    cleaned.reserve(indices->size());
    for (size_t i = 0; i + 2 < indices->size(); i += 3) {
        uint32_t a = (*indices)[i + 0];
        uint32_t b = (*indices)[i + 1];
        uint32_t c = (*indices)[i + 2];
        a = a == remove ? keep : a;
        b = b == remove ? keep : b;
        c = c == remove ? keep : c;
        if (a == b || b == c || c == a) {
            continue;
        }
        cleaned.push_back(a);
        cleaned.push_back(b);
        cleaned.push_back(c);
    }
    indices->swap(cleaned);
    return true;
}

bool triangleNormal(Mesh const& mesh, uint32_t a, uint32_t b, uint32_t c, math::float3* normal) {
    math::float3 const ab = mesh.positions[b] - mesh.positions[a];
    math::float3 const ac = mesh.positions[c] - mesh.positions[a];
    *normal = cross(ab, ac);
    float const length2 = dot(*normal, *normal);
    if (!(length2 > 1e-20f)) {
        return false;
    }
    *normal /= std::sqrt(length2);
    return true;
}

bool flipEdgeIfBetter(Mesh const& mesh, std::vector<uint32_t>* indices,
        std::map<std::pair<uint32_t, uint32_t>, std::vector<size_t>> const& edgeUse, uint32_t edgeA,
        uint32_t edgeB, float minQuality, std::vector<uint8_t> const* lockedVertices) {
    uint32_t const u = std::min(edgeA, edgeB);
    uint32_t const v = std::max(edgeA, edgeB);
    auto const it = edgeUse.find({ u, v });
    if (it == edgeUse.end() || it->second.size() != 2) {
        return false;
    }

    size_t const t0 = it->second[0];
    size_t const t1 = it->second[1];
    if (lockedVertices != nullptr) {
        for (size_t t: { t0, t1 }) {
            for (int i = 0; i < 3; ++i) {
                uint32_t const vertex = (*indices)[t * 3 + i];
                if (vertex < lockedVertices->size() && (*lockedVertices)[vertex] != 0) {
                    return false;
                }
            }
        }
    }
    auto opposite = [&](size_t triangle) {
        for (int i = 0; i < 3; ++i) {
            uint32_t const vertex = (*indices)[triangle * 3 + i];
            if (vertex != u && vertex != v) {
                return vertex;
            }
        }
        return UINT32_MAX;
    };
    uint32_t const p = opposite(t0);
    uint32_t const q = opposite(t1);
    if (p == UINT32_MAX || q == UINT32_MAX || p == q ||
            edgeUse.count({ std::min(p, q), std::max(p, q) }) != 0) {
        return false;
    }

    math::float3 oldNormal0{};
    math::float3 oldNormal1{};
    bool const oldValid0 = triangleNormal(mesh, (*indices)[t0 * 3 + 0], (*indices)[t0 * 3 + 1],
            (*indices)[t0 * 3 + 2], &oldNormal0);
    bool const oldValid1 = triangleNormal(mesh, (*indices)[t1 * 3 + 0], (*indices)[t1 * 3 + 1],
            (*indices)[t1 * 3 + 2], &oldNormal1);
    if (!oldValid0 || !oldValid1) {
        return false;
    }

    float const oldMin = std::min(normalizedTriangleQuality(mesh, (*indices)[t0 * 3 + 0],
                                          (*indices)[t0 * 3 + 1], (*indices)[t0 * 3 + 2]),
            normalizedTriangleQuality(mesh, (*indices)[t1 * 3 + 0], (*indices)[t1 * 3 + 1],
                    (*indices)[t1 * 3 + 2]));

    struct Flip {
        uint32_t a[3];
        uint32_t b[3];
    };
    Flip const flips[2] = {
        { { p, u, q }, { q, v, p } },
        { { p, v, q }, { q, u, p } },
    };

    for (Flip const& flip: flips) {
        float const newQuality =
                std::min(normalizedTriangleQuality(mesh, flip.a[0], flip.a[1], flip.a[2]),
                        normalizedTriangleQuality(mesh, flip.b[0], flip.b[1], flip.b[2]));
        if (newQuality < minQuality || newQuality <= oldMin + 1e-4f) {
            continue;
        }

        math::float3 normalA{};
        math::float3 normalB{};
        if (!triangleNormal(mesh, flip.a[0], flip.a[1], flip.a[2], &normalA) ||
                !triangleNormal(mesh, flip.b[0], flip.b[1], flip.b[2], &normalB) ||
                dot(normalA, oldNormal0) < 0.1f || dot(normalB, oldNormal1) < 0.1f) {
            continue;
        }

        // Keep the shared edge orientation consistent with the original triangles. If the two
        // input triangles had the same winding across the edge they were already non-manifold,
        // and a flip cannot repair that.
        auto directedEdge = [&](size_t triangle) {
            for (int i = 0; i < 3; ++i) {
                uint32_t const a = (*indices)[triangle * 3 + i];
                uint32_t const b = (*indices)[triangle * 3 + (i + 1) % 3];
                if ((a == u && b == v) || (a == v && b == u)) {
                    return std::pair<uint32_t, uint32_t>{ a, b };
                }
            }
            return std::pair<uint32_t, uint32_t>{ UINT32_MAX, UINT32_MAX };
        };
        auto const edge0 = directedEdge(t0);
        auto const edge1 = directedEdge(t1);
        bool const oppositeWinding = edge0.first == edge1.second && edge0.second == edge1.first;
        if (!oppositeWinding) {
            continue;
        }

        for (int i = 0; i < 3; ++i) {
            (*indices)[t0 * 3 + i] = flip.a[i];
            (*indices)[t1 * 3 + i] = flip.b[i];
        }
        return true;
    }
    return false;
}

void repairSlivers(Mesh const& mesh, std::vector<uint32_t>* indices, float minQuality,
        std::vector<uint8_t> const* lockedVertices) {
    size_t const maxIterations = indices->size() / 3 + 1;
    for (size_t iteration = 0; iteration < maxIterations; ++iteration) {
        std::map<std::pair<uint32_t, uint32_t>, std::vector<size_t>> edgeUse;
        for (size_t i = 0; i + 2 < indices->size(); i += 3) {
            uint32_t const vertices[3] = { (*indices)[i], (*indices)[i + 1], (*indices)[i + 2] };
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = std::min(vertices[e], vertices[(e + 1) % 3]);
                uint32_t const b = std::max(vertices[e], vertices[(e + 1) % 3]);
                edgeUse[{ a, b }].push_back(i / 3);
            }
        }
        std::set<uint32_t> borderVertices;
        std::set<std::pair<uint32_t, uint32_t>> borderEdges;
        for (auto const& [edge, triangles]: edgeUse) {
            if (triangles.size() == 1) {
                borderVertices.insert(edge.first);
                borderVertices.insert(edge.second);
                borderEdges.insert(edge);
            }
        }

        bool repaired = false;
        for (size_t i = 0; i + 2 < indices->size() && !repaired; i += 3) {
            uint32_t const a = (*indices)[i + 0];
            uint32_t const b = (*indices)[i + 1];
            uint32_t const c = (*indices)[i + 2];
            if (normalizedTriangleQuality(mesh, a, b, c) >= minQuality) {
                continue;
            }

            struct Candidate {
                uint32_t remove;
                uint32_t keep;
                float length2;
            };
            Candidate candidates[3] = {
                { a, b,
                    dot(mesh.positions[a] - mesh.positions[b],
                            mesh.positions[a] - mesh.positions[b]) },
                { b, c,
                    dot(mesh.positions[b] - mesh.positions[c],
                            mesh.positions[b] - mesh.positions[c]) },
                { c, a,
                    dot(mesh.positions[c] - mesh.positions[a],
                            mesh.positions[c] - mesh.positions[a]) },
            };
            std::sort(candidates, candidates + 3,
                    [](Candidate const& x, Candidate const& y) { return x.length2 < y.length2; });
            for (Candidate const& candidate: candidates) {
                if (collapseSliverEdge(mesh, indices, candidate.remove, candidate.keep,
                            borderVertices, borderEdges, lockedVertices)) {
                    repaired = true;
                    break;
                }
                if (collapseSliverEdge(mesh, indices, candidate.keep, candidate.remove,
                            borderVertices, borderEdges, lockedVertices)) {
                    repaired = true;
                    break;
                }
            }
            if (!repaired) {
                // A flip keeps the vertex count but can split a long sliver edge into two
                // better-shaped triangles, which is common where a locked border fan meets
                // an interior collapse.
                Candidate flips[3] = { candidates[0], candidates[1], candidates[2] };
                std::sort(flips, flips + 3, [](Candidate const& x, Candidate const& y) {
                    return x.length2 > y.length2;
                });
                for (Candidate const& candidate: flips) {
                    if (flipEdgeIfBetter(mesh, indices, edgeUse, candidate.keep, candidate.remove,
                                minQuality, lockedVertices)) {
                        repaired = true;
                        break;
                    }
                }
            }
        }
        if (!repaired) {
            break;
        }
    }
    removeDegenerateAndDuplicateTriangles(mesh, indices);
}

float attributeComplexity(Mesh const& mesh, std::vector<uint32_t> const& indices) {
    if (!mesh.hasNormals() && !mesh.hasUVs()) {
        return 1.0f;
    }

    std::vector<uint32_t> vertices = indices;
    std::sort(vertices.begin(), vertices.end());
    vertices.erase(std::unique(vertices.begin(), vertices.end()), vertices.end());
    if (vertices.empty()) {
        return 1.0f;
    }

    float normalSpread = 0.0f;
    if (mesh.hasNormals()) {
        math::float3 meanNormal{};
        for (uint32_t vertex: vertices) {
            meanNormal += mesh.normals[vertex];
        }
        float const meanLength = length(meanNormal);
        if (meanLength > 0.0f) {
            meanNormal /= meanLength;
            for (uint32_t vertex: vertices) {
                float const n = length(mesh.normals[vertex]);
                if (n > 0.0f) {
                    float const cosine =
                            std::clamp(dot(mesh.normals[vertex] / n, meanNormal), -1.0f, 1.0f);
                    normalSpread = std::max(normalSpread, std::acos(cosine));
                }
            }
        }
    }

    float uvSpread = 0.0f;
    if (mesh.hasUVs()) {
        math::float2 lo = mesh.uvs[vertices[0]];
        math::float2 hi = lo;
        for (uint32_t vertex: vertices) {
            lo = min(lo, mesh.uvs[vertex]);
            hi = max(hi, mesh.uvs[vertex]);
        }
        uvSpread = length(hi - lo);
    }

    // A flat unit pays 1x, while a unit with normals spread over a hemisphere or a large UV
    // chart pays up to roughly 3x. This tightens the error cap where an attribute collapse is
    // most likely to be visible, before the hard quality gate is even consulted.
    return 1.0f + normalSpread / 3.14159265358979323846f + uvSpread;
}

bool topologyAcceptable(TopologyStats const& candidate, TopologyStats const& base,
        SimplifyOptions const& options) {
    if (candidate.duplicateTriangles != 0 || candidate.degenerateTriangles != 0 ||
            candidate.flippedTriangles != 0) {
        return false;
    }
    if (candidate.nonManifoldEdges > base.nonManifoldEdges) {
        return false;
    }
    if (candidate.boundaryEdges > base.boundaryEdges) {
        return false;
    }
    float const requiredQuality = std::min(options.minTriangleQuality, base.minTriangleQuality);
    return candidate.minTriangleQuality >= requiredQuality;
}

bool attributesAcceptable(AttributeStats const& attributes, SimplifyOptions const& options) {
    float const maxNormal = options.maxNormalErrorDegrees * 3.14159265358979323846f / 180.0f;
    // UV singularities (poles, chart corners) can produce one large outlier while the surface
    // as a whole keeps its texture coordinates. Use the mean as the hard limit and allow a
    // bounded maximum, otherwise a single pole vertex disables simplification for the unit.
    return attributes.maxNormalErrorRadians <= maxNormal &&
           attributes.meanNormalErrorRadians <= maxNormal * 0.5f &&
           attributes.meanUvError <= options.maxUvError &&
           attributes.maxUvError <= options.maxUvError * 8.0f;
}

/**
 * The topology checks above cannot see a valid but heavily dented surface: a collapse can keep
 * every edge manifold and every triangle upright while pulling a patch of the model inward.
 * The position metric is the missing constraint. `targetError` is already the world-space
 * error cap used by the meshoptimizer path, so the same cap applies to the attribute-QEM
 * candidate instead of letting it trade an arbitrary amount of shape for triangle count.
 */
bool geometryAcceptable(LodLevel const& level, SimplifyOptions const& options, float meshScale) {
    if (!options.qualityGate) {
        return true;
    }
    float const cap = std::max(options.targetError, 1e-5f) * std::max(meshScale, 1e-6f);
    return std::isfinite(level.worldError) && level.worldError <= cap;
}

using UndirectedEdge = std::pair<uint32_t, uint32_t>;

std::set<UndirectedEdge> boundaryEdgeSet(std::vector<uint32_t> const& indices) {
    std::map<UndirectedEdge, uint32_t> use;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const v[3] = { indices[i], indices[i + 1], indices[i + 2] };
        for (int e = 0; e < 3; ++e) {
            uint32_t const a = v[e];
            uint32_t const b = v[(e + 1) % 3];
            use[{ std::min(a, b), std::max(a, b) }] += 1;
        }
    }
    std::set<UndirectedEdge> result;
    for (auto const& [edge, count]: use) {
        if (count == 1) {
            result.insert(edge);
        }
    }
    return result;
}

/**
 * A crack in a group is a boundary edge that was not a boundary of the source unit. Comparing
 * only the *number* of boundary edges misses it: collapsing a seam edge on one side can create
 * a new boundary elsewhere and keep the count unchanged. Border locking is supposed to make the
 * sets identical, so any difference means the candidate rewrote the outline.
 */
bool preservesBoundaryEdges(std::vector<uint32_t> const& source,
        std::vector<uint32_t> const& candidate) {
    return boundaryEdgeSet(source) == boundaryEdgeSet(candidate);
}

using WeldedPosition = std::array<uint32_t, 3>;

struct WeldedPositionHash {
    size_t operator()(WeldedPosition const& position) const noexcept {
        uint64_t hash = uint64_t(position[0]) * 0x9E3779B185EBCA87ull;
        auto mix = [&hash](uint64_t value) {
            hash ^= value + 0x9E3779B97F4A7C15ull + (hash << 6) + (hash >> 2);
        };
        mix(position[1]);
        mix(position[2]);
        return size_t(hash);
    }
};

WeldedPosition weldedPosition(math::float3 position) noexcept {
    float const x = position.x == 0.0f ? 0.0f : position.x;
    float const y = position.y == 0.0f ? 0.0f : position.y;
    float const z = position.z == 0.0f ? 0.0f : position.z;
    WeldedPosition key{};
    std::memcpy(&key[0], &x, sizeof(float));
    std::memcpy(&key[1], &y, sizeof(float));
    std::memcpy(&key[2], &z, sizeof(float));
    return key;
}

/**
 * Boundary check for a candidate that is allowed to collapse a paired UV/normal seam.
 *
 * Per-index boundary edges are expected to change: that is exactly what seam pairing does.
 * What must not change is the boundary of the *welded* surface. If both chart copies shrink
 * together, their duplicated edges disappear in pairs and the welded edge set is unchanged.
 * If one side moves first, the position edge becomes a one-use edge and this check rejects it.
 */
bool preservesWeldedBoundaries(Mesh const& mesh, std::vector<uint32_t> const& source,
        std::vector<uint32_t> const& candidate) {
    std::unordered_map<WeldedPosition, uint32_t, WeldedPositionHash> canonical;
    std::unordered_map<uint32_t, uint32_t> welded;
    canonical.reserve(source.size() / 3 + candidate.size() / 3);
    welded.reserve(source.size() / 3 + candidate.size() / 3);
    auto weld = [&](uint32_t vertex) {
        if (vertex >= mesh.positions.size()) {
            return UINT32_MAX;
        }
        auto const [it, inserted] = welded.emplace(vertex, UINT32_MAX);
        if (inserted) {
            uint32_t const id = uint32_t(canonical.size());
            auto const [positionIt, positionInserted] =
                    canonical.emplace(weldedPosition(mesh.positions[vertex]), id);
            (void) positionInserted;
            it->second = positionIt->second;
        }
        return it->second;
    };

    struct Topology {
        std::vector<uint64_t> boundary;
        uint64_t nonManifold = 0;
    };
    auto topologyOf = [&](std::vector<uint32_t> const& indices) {
        std::unordered_map<uint64_t, uint32_t> use;
        use.reserve(indices.size());
        for (size_t i = 0; i + 2 < indices.size(); i += 3) {
            uint32_t const v[3] = { weld(indices[i + 0]), weld(indices[i + 1]),
                weld(indices[i + 2]) };
            if (v[0] == UINT32_MAX || v[1] == UINT32_MAX || v[2] == UINT32_MAX) {
                continue;
            }
            for (int e = 0; e < 3; ++e) {
                uint32_t const a = v[e];
                uint32_t const b = v[(e + 1) % 3];
                uint64_t const lo = std::min(a, b);
                uint64_t const hi = std::max(a, b);
                use[(hi << 32) | lo] += 1;
            }
        }
        Topology result;
        result.boundary.reserve(use.size());
        for (auto const& [edge, count]: use) {
            if (count == 1) {
                result.boundary.push_back(edge);
            } else if (count > 2) {
                result.nonManifold += 1;
            }
        }
        std::sort(result.boundary.begin(), result.boundary.end());
        return result;
    };

    Topology const base = topologyOf(source);
    Topology const simplified = topologyOf(candidate);
    return base.boundary == simplified.boundary && simplified.nonManifold <= base.nonManifold;
}

/**
 * Topology metrics for geometry whose vertices may be split by attribute chart.
 *
 * `measureTopology` counts edges between vertex ids. The corner simplifier deliberately emits
 * several ids at one position (one per chart), so raw ids would report a boundary down every
 * seam even though the welded surface is closed. This variant canonicalises vertices by exact
 * position for the edge/triangle histogram, while still using the real corner normals for the
 * flip test.
 */
TopologyStats measureWeldedTopologyImpl(Mesh const& mesh, std::vector<uint32_t> const& indices) {
    TopologyStats result;
    result.triangles = indices.size() / 3;

    std::unordered_map<WeldedPosition, uint32_t, WeldedPositionHash> canonical;
    std::unordered_map<uint32_t, uint32_t> welded;
    canonical.reserve(indices.size() / 3);
    welded.reserve(indices.size() / 3);
    auto weld = [&](uint32_t vertex) {
        if (vertex >= mesh.positions.size()) {
            return UINT32_MAX;
        }
        auto const [it, inserted] = welded.emplace(vertex, UINT32_MAX);
        if (inserted) {
            uint32_t const id = uint32_t(canonical.size());
            auto const [positionIt, positionInserted] =
                    canonical.emplace(weldedPosition(mesh.positions[vertex]), id);
            (void) positionInserted;
            it->second = positionIt->second;
        }
        return it->second;
    };

    std::unordered_map<uint64_t, uint32_t> edgeUse;
    edgeUse.reserve(indices.size());
    std::vector<std::array<uint32_t, 3>> triangles;
    triangles.reserve(result.triangles);
    double qualitySum = 0.0;
    result.minTriangleQuality = 1.0f;

    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const a = indices[i + 0];
        uint32_t const b = indices[i + 1];
        uint32_t const c = indices[i + 2];
        float const quality = normalizedTriangleQuality(mesh, a, b, c);
        result.minTriangleQuality = std::min(result.minTriangleQuality, quality);
        qualitySum += double(quality);
        if (!(quality > 0.0f)) {
            result.degenerateTriangles += 1;
            continue;
        }
        if (mesh.hasNormals()) {
            math::float3 const& p0 = mesh.positions[a];
            math::float3 const& p1 = mesh.positions[b];
            math::float3 const& p2 = mesh.positions[c];
            math::float3 const faceNormal = cross(p1 - p0, p2 - p0);
            math::float3 const vertexNormal = mesh.normals[a] + mesh.normals[b] + mesh.normals[c];
            if (dot(faceNormal, vertexNormal) < 0.0f) {
                result.flippedTriangles += 1;
            }
        }

        uint32_t const va = weld(a);
        uint32_t const vb = weld(b);
        uint32_t const vc = weld(c);
        if (va == UINT32_MAX || vb == UINT32_MAX || vc == UINT32_MAX) {
            continue;
        }
        std::array<uint32_t, 3> key = { va, vb, vc };
        std::sort(key.begin(), key.end());
        triangles.push_back(key);
        uint32_t const v[3] = { va, vb, vc };
        for (int e = 0; e < 3; ++e) {
            uint32_t const lo = std::min(v[e], v[(e + 1) % 3]);
            uint32_t const hi = std::max(v[e], v[(e + 1) % 3]);
            edgeUse[(uint64_t(lo) << 32) | uint64_t(hi)] += 1;
        }
    }

    std::sort(triangles.begin(), triangles.end());
    for (size_t i = 1; i < triangles.size(); ++i) {
        if (triangles[i] == triangles[i - 1]) {
            result.duplicateTriangles += 1;
        }
    }
    result.uniqueTriangles = result.triangles - result.duplicateTriangles;
    result.edges = edgeUse.size();
    for (auto const& [key, count]: edgeUse) {
        (void) key;
        if (count == 1) {
            result.boundaryEdges += 1;
        } else if (count > 2) {
            result.nonManifoldEdges += 1;
        }
    }
    if (result.triangles > 0) {
        result.meanTriangleQuality = float(qualitySum / double(result.triangles));
    }
    return result;
}

// Rejects any candidate that creates an edge between two locked (seam) vertices that did not
// exist in the source unit. Per-cluster simplification runs on small units and has a local
// topology check, but a chord between two seam vertices is still locally manifold on one side;
// it only becomes non-manifold when the neighbouring unit creates the mirror chord. This check
// is independent of which simplifier produced the candidate, so it also covers the
struct WeldedEdge {
    WeldedPosition a{};
    WeldedPosition b{};
    bool operator==(WeldedEdge const& other) const noexcept { return a == other.a && b == other.b; }
};

struct WeldedEdgeHash {
    size_t operator()(WeldedEdge const& edge) const noexcept {
        WeldedPositionHash const hash;
        size_t const first = hash(edge.a);
        return first ^ (hash(edge.b) + 0x9E3779B97F4A7C15ull + (first << 6) + (first >> 2));
    }
};

WeldedEdge makeWeldedEdge(WeldedPosition const& a, WeldedPosition const& b) noexcept {
    if (std::lexicographical_compare(b.begin(), b.end(), a.begin(), a.end())) {
        return { b, a };
    }
    return { a, b };
}

void printWeldedPosition(WeldedPosition const& position) noexcept {
    float values[3];
    std::memcpy(values, position.data(), sizeof(values));
    std::fprintf(stderr, "(%.4f,%.4f,%.4f)", values[0], values[1], values[2]);
}

bool inputPosition(Mesh const& mesh, std::vector<uint32_t> const* positionIds, uint32_t vertex,
        WeldedPosition* position) noexcept {
    if (positionIds != nullptr && vertex < positionIds->size()) {
        uint32_t const id = (*positionIds)[vertex];
        if (id < mesh.positions.size()) {
            *position = weldedPosition(mesh.positions[id]);
            return true;
        }
    }
    if (vertex < mesh.positions.size()) {
        *position = weldedPosition(mesh.positions[vertex]);
        return true;
    }
    return false;
}

bool candidatePosition(Mesh const& mesh, std::vector<uint32_t> const* positionIds,
        std::vector<GeneratedVertex> const* generated, uint32_t vertex,
        WeldedPosition* position) noexcept {
    if (positionIds != nullptr && vertex < positionIds->size()) {
        uint32_t const id = (*positionIds)[vertex];
        if (id < mesh.positions.size()) {
            *position = weldedPosition(mesh.positions[id]);
            return true;
        }
    }
    if (vertex < mesh.positions.size()) {
        *position = weldedPosition(mesh.positions[vertex]);
        return true;
    }
    if (generated != nullptr && vertex >= mesh.vertexCount()) {
        size_t const local = size_t(vertex - mesh.vertexCount());
        if (local < generated->size()) {
            GeneratedVertex const& vertexData = (*generated)[local];
            *position = weldedPosition(vertexData.hasPosition
                                               ? vertexData.position
                                               : mesh.positions[vertexData.positionSource]);
            return true;
        }
    }
    return false;
}

/**
 * Precomputed form of the shared-vertex mask check.
 *
 * The previous implementation rebuilt two std::maps and two std::sets for every candidate,
 * and walked every vertex of the mesh each time. Per-cluster simplification calls this for
 * hundreds of candidates, which made mask validation the largest CPU consumer on large
 * imports. The source mesh and its mask do not change across attempts, so the locked
 * positions and locked source edges are built once per simplify unit and every candidate is
 * checked with hash lookups proportional to its own triangle count.
 */
struct LockedMaskContext {
    Mesh const* mesh = nullptr;
    std::vector<uint32_t> const* positionIds = nullptr;
    std::unordered_map<WeldedPosition, uint32_t, WeldedPositionHash> lockedIndex;
    std::unordered_set<WeldedEdge, WeldedEdgeHash> lockedEdges;
    std::vector<WeldedPosition> lockedPositions;
    std::vector<uint32_t> sourceLocked;
    bool enabled = false;
};

void buildLockedMaskContext(Mesh const& mesh, std::vector<uint32_t> const& source,
        SimplifyOptions const& options, LockedMaskContext* context) {
    context->mesh = &mesh;
    context->positionIds = options.vertexPositionIds;
    if (options.lockedVertices == nullptr) {
        return;
    }
    context->enabled = true;
    std::vector<uint8_t> const& mask = *options.lockedVertices;
    // Only locked positions that the unit actually references matter: every candidate is built
    // from these vertices (plus generated vertices interpolated between them). Scanning the
    // whole mesh here made the context build O(mesh vertices) per cluster/group, which dominated
    // large imports. This keeps it O(unit references).
    for (uint32_t vertex: source) {
        if (vertex >= mesh.vertexCount()) {
            continue;
        }
        uint32_t maskIndex = vertex;
        if (context->positionIds != nullptr && vertex < context->positionIds->size()) {
            maskIndex = (*context->positionIds)[vertex];
        }
        if (maskIndex >= mask.size() || mask[maskIndex] == 0) {
            continue;
        }
        WeldedPosition position;
        if (!inputPosition(mesh, context->positionIds, vertex, &position)) {
            continue;
        }
        auto const inserted =
                context->lockedIndex.emplace(position, uint32_t(context->lockedPositions.size()));
        if (inserted.second) {
            context->lockedPositions.push_back(position);
        }
    }
    if (context->lockedIndex.empty()) {
        return;
    }

    std::vector<uint8_t> sourceLocked(context->lockedPositions.size(), 0);
    for (size_t i = 0; i + 2 < source.size(); i += 3) {
        WeldedPosition positions[3];
        uint32_t locked[3] = { UINT32_MAX, UINT32_MAX, UINT32_MAX };
        for (int corner = 0; corner < 3; ++corner) {
            if (!inputPosition(mesh, context->positionIds, source[i + corner],
                        &positions[corner])) {
                continue;
            }
            auto const found = context->lockedIndex.find(positions[corner]);
            if (found != context->lockedIndex.end()) {
                locked[corner] = found->second;
                sourceLocked[locked[corner]] = 1;
            }
        }
        for (int edge = 0; edge < 3; ++edge) {
            int const next = (edge + 1) % 3;
            if (locked[edge] != UINT32_MAX && locked[next] != UINT32_MAX) {
                context->lockedEdges.insert(makeWeldedEdge(positions[edge], positions[next]));
            }
        }
    }
    for (uint32_t i = 0; i < sourceLocked.size(); ++i) {
        if (sourceLocked[i] != 0) {
            context->sourceLocked.push_back(i);
        }
    }
}

// meshoptimizer fallback, which knows nothing about the shared-vertex mask.
bool respectsLockedMask(Mesh const& mesh, std::vector<uint32_t> const& candidate,
        SimplifyOptions const& options, std::vector<GeneratedVertex> const* generated,
        LockedMaskContext const& context) {
    if (!context.enabled || context.lockedIndex.empty()) {
        return true;
    }

    thread_local std::vector<uint32_t> seen;
    thread_local uint32_t generation = 0;
    if (seen.size() < context.lockedPositions.size()) {
        seen.resize(context.lockedPositions.size(), 0);
    }
    ++generation;
    if (generation == 0) {
        std::fill(seen.begin(), seen.end(), 0);
        generation = 1;
    }

    for (size_t i = 0; i + 2 < candidate.size(); i += 3) {
        WeldedPosition positions[3];
        uint32_t locked[3] = { UINT32_MAX, UINT32_MAX, UINT32_MAX };
        for (int corner = 0; corner < 3; ++corner) {
            if (!candidatePosition(mesh, context.positionIds, generated, candidate[i + corner],
                        &positions[corner])) {
                continue;
            }
            auto const found = context.lockedIndex.find(positions[corner]);
            if (found != context.lockedIndex.end()) {
                locked[corner] = found->second;
                seen[locked[corner]] = generation;
            }
        }
        for (int edge = 0; edge < 3; ++edge) {
            int const next = (edge + 1) % 3;
            if (locked[edge] == UINT32_MAX || locked[next] == UINT32_MAX) {
                continue;
            }
            if (context.lockedEdges.count(makeWeldedEdge(positions[edge], positions[next])) == 0) {
                if (options.verbose) {
                    std::fprintf(stderr, "locked-mask reject: new locked edge ");
                    printWeldedPosition(positions[edge]);
                    std::fprintf(stderr, " -> ");
                    printWeldedPosition(positions[next]);
                    std::fprintf(stderr, "\n");
                }
                return false;
            }
        }
    }
    for (uint32_t index: context.sourceLocked) {
        if (seen[index] != generation) {
            if (options.verbose) {
                std::fprintf(stderr, "locked-mask reject: missing locked position ");
                printWeldedPosition(context.lockedPositions[index]);
                std::fprintf(stderr, "\n");
            }
            return false;
        }
    }
    return true;
}


// Number of triangles to aim for at a given level of a chain rooted at `baseTriangles`.
size_t targetIndexCountForLevel(size_t baseIndexCount, uint32_t level, float ratio) {
    double const fraction = std::pow(double(ratio), double(level));
    size_t target = size_t(double(baseIndexCount) * fraction);
    return (target / 3) * 3;
}

/**
 * Simplify one unit (a cluster, or a group of them).
 *
 * meshopt_simplify sizes its working memory from `vertex_count`, not from how many vertices
 * the indices actually reference. Handing it the whole mesh's vertex buffer for a unit of 128
 * triangles would make it allocate and initialise a quadric per vertex of the entire model —
 * on a seven million triangle scan that is a few hundred megabytes, per unit, per level.
 * Units therefore get a compacted vertex buffer of their own, and the result is mapped back to
 * the shared one.
 *
 * `remap` is scratch space reused across units: it maps a mesh vertex to its index in the
 * current unit's local buffer, or -1 when unused. Only the vertices the unit actually touched
 * are reset, so the cost stays proportional to the unit, not to the mesh.
 *
 * `meshScale` is `relativeToWorldScale` of the whole mesh, used to rescale the error cap — see
 * below.
 */
struct SimplifyScratch {
    std::vector<math::float3> localPositions;
    std::vector<uint32_t> localToGlobal;
    std::vector<uint32_t> localIndices;
    std::vector<uint32_t> destination;
    //! Base mesh plus the generated vertices of the current corner candidate. The base copy is
    //! made once per simplification call; attempts only rewrite the tail. Copying the whole
    //! shared mesh for every retry was a measurable DAG build cost on assets with many seams.
    Mesh extendedMesh;
    size_t extendedBaseVertexCount = 0;
    uint64_t extendedMeshEpoch = 0;
};

uint64_t nextMeshCacheEpoch() {
    static std::atomic<uint64_t> next{ 1 };
    return next.fetch_add(1, std::memory_order_relaxed);
}

void appendGeneratedVerticesInPlace(Mesh* mesh, size_t baseVertexCount,
        std::vector<GeneratedVertex> const& generated) {
    size_t const count = baseVertexCount + generated.size();
    bool const hasNormals = mesh->hasNormals();
    bool const hasUVs = mesh->hasUVs();
    mesh->positions.resize(count);
    if (hasNormals) {
        mesh->normals.resize(count);
    }
    if (hasUVs) {
        mesh->uvs.resize(count);
    }
    for (size_t i = 0; i < generated.size(); ++i) {
        GeneratedVertex const& vertex = generated[i];
        size_t const index = baseVertexCount + i;
        mesh->positions[index] = vertex.hasPosition
                                         ? vertex.position
                                         : mesh->positions[vertex.positionSource];
        if (hasNormals) {
            mesh->normals[index] = vertex.normal;
        }
        if (hasUVs) {
            mesh->uvs[index] = vertex.uv;
        }
    }
}

void simplifyClusterInto(std::vector<uint32_t> const& source, Mesh const& mesh,
        std::vector<int32_t>* remap, SimplifyScratch* scratch, size_t targetIndexCount,
        float targetError, float meshScale, SimplifyOptions const& options,
        unsigned int meshoptOptions, LodLevel* out, SimplifyProfile* profile = nullptr) {
    using ProfileClock = std::chrono::steady_clock;
    auto profileSeconds = [](ProfileClock::time_point start) {
        return std::chrono::duration<double>(ProfileClock::now() - start).count();
    };
    if (profile != nullptr) {
        profile->calls += 1;
    }
    std::vector<math::float3>& localPositions = scratch->localPositions;
    std::vector<uint32_t>& localToGlobal = scratch->localToGlobal;
    std::vector<uint32_t>& localIndices = scratch->localIndices;
    std::vector<uint32_t>& destination = scratch->destination;

    localPositions.clear();
    localToGlobal.clear();
    localIndices.resize(source.size());
    destination.resize(source.size());
    if (localPositions.capacity() < source.size()) {
        localPositions.reserve(source.size());
        localToGlobal.reserve(source.size());
    }

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

    // meshopt interprets target_error relative to the extent of the buffer it is handed, which
    // here is the *unit's* extent, not the mesh's. Passed through unchanged, "1% error" would
    // mean a far larger absolute deviation for a big group than for a small cluster, and the
    // cap — not the triangle budget — would be what decides the outcome. Rescaling it fixes the
    // cap in world units so that units of any size are held to the same standard.
    float const localScale = meshopt_simplifyScale(&localPositions[0].x, localPositions.size(),
            sizeof(math::float3));
    float const localTargetError = targetError * meshScale / std::max(localScale, 1e-6f);
    float const complexity = options.qualityGate ? attributeComplexity(mesh, source) : 1.0f;
    TopologyStats const baseTopology =
            options.qualityGate ? measureTopology(mesh, source) : TopologyStats{};
    TopologyStats const baseWeldedTopology =
            options.qualityGate && (options.cornerSimplify || options.seamCollapse)
                    ? measureWeldedTopologyImpl(mesh, source)
                    : TopologyStats{};
    CandidateReference candidateReference;
    if (options.qualityGate) {
        candidateReference = makeCandidateReference(source, options.attributeSampleLimit);
    }
    if (options.cornerSimplify && options.attributeQem &&
            source.size() / 3 <= options.attributeQemMaxTriangles) {
        bool const reuseExtended = options.meshCacheEpoch != 0 &&
                                   scratch->extendedMeshEpoch == options.meshCacheEpoch;
        if (!reuseExtended) {
            auto const extendedStart = ProfileClock::now();
            // The quality gate only reads vertex attributes. Keeping the source index buffer
            // and primitive metadata here would copy them for every unit without ever using
            // them, so the extended mesh is deliberately a vertex-only snapshot plus the
            // generated tail appended below.
            scratch->extendedMesh.positions = mesh.positions;
            scratch->extendedMesh.normals = mesh.normals;
            scratch->extendedMesh.uvs = mesh.uvs;
            scratch->extendedMesh.ao = mesh.ao;
            scratch->extendedMesh.indices.clear();
            scratch->extendedMesh.materialIds.clear();
            scratch->extendedMesh.submeshIds.clear();
            scratch->extendedBaseVertexCount = mesh.positions.size();
            scratch->extendedMeshEpoch = options.meshCacheEpoch;
            if (profile != nullptr) {
                profile->extendedMeshSeconds += profileSeconds(extendedStart);
                profile->extendedMeshCopies += 1;
            }
        }
    }
    LockedMaskContext lockedMaskContext;
    auto const lockedMaskBuildStart = ProfileClock::now();
    buildLockedMaskContext(mesh, source, options, &lockedMaskContext);
    if (profile != nullptr) {
        profile->lockedMaskBuildSeconds += profileSeconds(lockedMaskBuildStart);
    }

    size_t attemptTarget = targetIndexCount;
    bool accepted = false;

    for (uint32_t attempt = 0; attempt < std::max(1u, options.qualityAttempts); ++attempt) {
        if (profile != nullptr) {
            profile->attempts += 1;
        }
        struct Candidate {
            LodLevel level;
            bool acceptable = false;
            uint32_t rejectMask = 0;
        };
        std::vector<Candidate> candidates;

        auto prepareCandidate = [&](std::vector<uint32_t> candidate, float relativeError,
                                        float worldError, Mesh const& geometry, bool repair,
                                        bool measureCandidateTopology = true) {
            LodLevel level;
            auto const cleanupStart = ProfileClock::now();
            removeDegenerateAndDuplicateTriangles(geometry, &candidate);
            if (profile != nullptr) {
                profile->candidateCleanupSeconds += profileSeconds(cleanupStart);
            }
            if (options.qualityGate && repair) {
                auto const sliverStart = ProfileClock::now();
                repairSlivers(geometry, &candidate, options.minTriangleQuality,
                        options.lockedVertices);
                if (profile != nullptr) {
                    profile->candidateSliverSeconds += profileSeconds(sliverStart);
                }
            }
            level.indices = std::move(candidate);
            auto const topologyStart = ProfileClock::now();
            if (options.qualityGate && measureCandidateTopology) {
                level.topology = measureTopology(geometry, level.indices);
            }
            if (profile != nullptr) {
                profile->candidateTopologySeconds += profileSeconds(topologyStart);
            }
            // Topology is far cheaper than the closest-triangle/attribute sampling below, and a
            // candidate that already broke an edge or a face can never become acceptable. Skip
            // the expensive error query for those candidates; their error fields are not used by
            // the acceptance decision or by the selected cut.
            bool const topologyRejected = options.qualityGate && measureCandidateTopology &&
                                          !topologyAcceptable(level.topology, baseTopology,
                                                  options);
            CandidateErrorStats errors;
            if (!topologyRejected) {
                auto const errorStart = ProfileClock::now();
                if (options.qualityGate) {
                    errors = measureCandidateErrors(geometry, candidateReference, level.indices,
                            options.attributeApproximationTriangles);
                }
                if (profile != nullptr) {
                    profile->candidateErrorSeconds += profileSeconds(errorStart);
                }
            }
            PositionStats const& positionStats = errors.position;
            level.worldError = positionStats.samples > 0 ? positionStats.maxError : worldError;
            level.relativeError = positionStats.samples > 0
                                          ? positionStats.maxError / std::max(meshScale, 1e-6f)
                                          : relativeError;
            level.attributes = errors.attributes;
            level.attempts = attempt + 1;
            level.simplified = level.indices.size() < source.size();
            return level;
        };

        auto acceptable = [&](LodLevel const& level, Mesh const& geometry, bool weldedBoundary,
                                  bool weldedTopology,
                                  std::vector<GeneratedVertex> const* generated,
                                  uint32_t* rejectMask) {
            auto const boundaryStart = ProfileClock::now();
            bool boundaryOk =
                    !options.qualityGate || source.size() / 3 > options.attributeQemMaxTriangles;
            if (!boundaryOk) {
                boundaryOk = weldedBoundary
                                     ? preservesWeldedBoundaries(geometry, source, level.indices)
                                     : preservesBoundaryEdges(source, level.indices);
            }
            if (profile != nullptr) {
                profile->boundaryCheckSeconds += profileSeconds(boundaryStart);
            }
            TopologyStats const& topologyBase = weldedTopology ? baseWeldedTopology : baseTopology;
            bool const topologyOk = !options.qualityGate ||
                                    topologyAcceptable(level.topology, topologyBase, options);
            if (!topologyOk && options.verbose) {
                std::fprintf(stderr,
                        "topology detail: candidate boundary=%llu nonManifold=%llu "
                        "duplicate=%llu degenerate=%llu flipped=%llu minQuality=%.6f | "
                        "base boundary=%llu nonManifold=%llu minQuality=%.6f welded=%d\n",
                        (unsigned long long) level.topology.boundaryEdges,
                        (unsigned long long) level.topology.nonManifoldEdges,
                        (unsigned long long) level.topology.duplicateTriangles,
                        (unsigned long long) level.topology.degenerateTriangles,
                        (unsigned long long) level.topology.flippedTriangles,
                        level.topology.minTriangleQuality,
                        (unsigned long long) topologyBase.boundaryEdges,
                        (unsigned long long) topologyBase.nonManifoldEdges,
                        topologyBase.minTriangleQuality, weldedTopology ? 1 : 0);
            }
            bool const geometryOk =
                    !options.qualityGate || geometryAcceptable(level, options, meshScale);
            bool const attributesOk =
                    !options.qualityGate || attributesAcceptable(level.attributes, options);
            bool result = !options.qualityGate ||
                          (topologyOk && geometryOk && attributesOk && boundaryOk);
            uint32_t mask = 0;
            if (!topologyOk) {
                mask |= 1u;
            }
            if (!geometryOk) {
                mask |= 2u;
            }
            if (!attributesOk) {
                mask |= 4u;
            }
            if (!boundaryOk) {
                mask |= 8u;
            }
            if (result && options.qualityGate) {
                auto const lockStart = ProfileClock::now();
                result = respectsLockedMask(geometry, level.indices, options, generated,
                        lockedMaskContext);
                if (!result) {
                    mask |= 16u;
                }
                if (profile != nullptr) {
                    profile->lockedMaskSeconds += profileSeconds(lockStart);
                }
            }
            if (rejectMask != nullptr) {
                *rejectMask = mask;
            }
            if (profile != nullptr && !result) {
                if (!topologyOk) {
                    profile->rejectedTopology += 1;
                } else if (!geometryOk) {
                    profile->rejectedGeometry += 1;
                } else if (!attributesOk) {
                    profile->rejectedAttributes += 1;
                } else if (!boundaryOk) {
                    profile->rejectedBoundary += 1;
                } else {
                    profile->rejectedLocked += 1;
                }
            }
            return result;
        };

        // Attribute-aware QEM first. It is the path that actually lets normals and UVs reject a
        // collapse instead of merely reporting it afterwards. Large global chains are excluded
        // by the triangle limit and fall back to meshoptimizer below.
        if (options.attributeQem && source.size() / 3 <= options.attributeQemMaxTriangles) {
            AttributeSimplifyOptions attributeOptions;
            attributeOptions.targetIndexCount = attemptTarget;
            attributeOptions.lockBorder = options.lockBorder;
            attributeOptions.lockedVertices = options.lockedVertices;
            attributeOptions.seamCollapse = options.seamCollapse;
            attributeOptions.minTriangleQuality = options.minTriangleQuality;
            attributeOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
            attributeOptions.maxUvError = options.maxUvError;
            attributeOptions.positionWeight = options.attributePositionWeight;
            attributeOptions.normalWeight = options.attributeNormalWeight;
            attributeOptions.uvWeight = options.attributeUvWeight;

            std::vector<uint32_t> attributeIndices;
            float attributeWorldError = 0.0f;
            auto const attributeStart = ProfileClock::now();
            bool const attributeSimplified = simplifyWithAttributes(mesh, source, attributeOptions,
                    &attributeIndices, &attributeWorldError);
            if (profile != nullptr) {
                profile->attributeQemSeconds += profileSeconds(attributeStart);
            }
            if (attributeSimplified) {
                Candidate candidate;
                auto const gateStart = ProfileClock::now();
                candidate.level = prepareCandidate(std::move(attributeIndices),
                        attributeWorldError / std::max(meshScale, 1e-6f), attributeWorldError, mesh,
                        true);
                if (profile != nullptr) {
                    profile->candidateGateSeconds += profileSeconds(gateStart);
                }
                candidate.acceptable =
                        candidate.level.simplified &&
                        acceptable(candidate.level, mesh, options.seamCollapse,
                                options.seamCollapse, nullptr, &candidate.rejectMask);
                if (profile != nullptr) {
                    profile->attributeCandidates += 1;
                }
                candidates.push_back(std::move(candidate));
            }
        }

        // Corner-attribute simplification. Welding duplicated positions turns a UV/normal seam
        // into an interior edge, so the surface can keep shrinking once the classic path is
        // pinned by per-chart borders. Any attribute value a chart needs at a welded position
        // that no input vertex has becomes a generated vertex. The quality gate below still sees
        // one vertex buffer, so cracks, flips and attribute jumps are rejected exactly as before.
        if (options.cornerSimplify && options.attributeQem &&
                source.size() / 3 <= options.attributeQemMaxTriangles) {
            CornerSimplifyOptions cornerOptions;
            CornerSimplifyProfile cornerProfile;
            cornerOptions.profile = &cornerProfile;
            cornerOptions.targetIndexCount = attemptTarget;
            cornerOptions.lockBorder = options.lockBorder;
            cornerOptions.lockedVertices = options.lockedVertices;
            cornerOptions.vertexPositionIds = options.vertexPositionIds;
            cornerOptions.minTriangleQuality = options.minTriangleQuality;
            cornerOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
            cornerOptions.maxUvError = options.maxUvError;
            cornerOptions.positionWeight = options.attributePositionWeight;
            cornerOptions.normalWeight = options.attributeNormalWeight;
            cornerOptions.uvWeight = options.attributeUvWeight;
            cornerOptions.splitDivergentUv = options.cornerSplitDivergentUv;

            std::vector<uint32_t> cornerIndices;
            std::vector<GeneratedVertex> generated;
            float cornerWorldError = 0.0f;
            auto const cornerStart = ProfileClock::now();
            bool const cornerSimplified = simplifyWithCornerAttributes(mesh, source, cornerOptions,
                    &cornerIndices, &generated, &cornerWorldError);
            if (profile != nullptr) {
                profile->cornerSeconds += profileSeconds(cornerStart);
                profile->cornerSetupSeconds += cornerProfile.setupSeconds;
                profile->cornerEvaluateSeconds += cornerProfile.evaluateSeconds;
                profile->cornerEvaluateTopologySeconds += cornerProfile.evaluateTopologySeconds;
                profile->cornerTopologyNeighborSeconds += cornerProfile.topologyNeighborSeconds;
                profile->cornerTopologyTriangleSeconds += cornerProfile.topologyTriangleSeconds;
                profile->cornerTopologyLocalTriangleSeconds +=
                        cornerProfile.topologyLocalTriangleSeconds;
                profile->cornerTopologyLocalEdgeSeconds += cornerProfile.topologyLocalEdgeSeconds;
                profile->cornerEvaluateTargetSeconds += cornerProfile.evaluateTargetSeconds;
                profile->cornerApplySeconds += cornerProfile.applySeconds;
                profile->cornerEvaluations += cornerProfile.evaluations;
                profile->cornerPlacementTests += cornerProfile.placementTests;
                profile->cornerApplied += cornerProfile.applied;
            }
            if (cornerSimplified) {
                appendGeneratedVerticesInPlace(&scratch->extendedMesh,
                        scratch->extendedBaseVertexCount, generated);
                Mesh const& extended = scratch->extendedMesh;
                Candidate candidate;
                auto const gateStart = ProfileClock::now();
                candidate.level = prepareCandidate(std::move(cornerIndices),
                        cornerWorldError / std::max(meshScale, 1e-6f), cornerWorldError, extended,
                        false, false);
                // The corner pass is allowed to split one welded position into several chart
                // vertices. Its topology therefore has to be measured on the welded surface,
                // exactly like its boundary check below.
                auto const weldedTopologyStart = ProfileClock::now();
                candidate.level.topology =
                        measureWeldedTopologyImpl(extended, candidate.level.indices);
                if (profile != nullptr) {
                    profile->weldedTopologySeconds += profileSeconds(weldedTopologyStart);
                }
                candidate.level.generatedVertices = std::move(generated);
                if (profile != nullptr) {
                    profile->candidateGateSeconds += profileSeconds(gateStart);
                    profile->cornerCandidates += 1;
                }
                candidate.acceptable =
                        candidate.level.simplified &&
                        acceptable(candidate.level, extended, true, true,
                                &candidate.level.generatedVertices, &candidate.rejectMask);
                candidates.push_back(std::move(candidate));
            }
        }

        {
            float resultError = 0.0f;
            float const attemptError =
                    localTargetError / (1.0f + 0.5f * float(attempt) * complexity);
            auto const meshoptStart = ProfileClock::now();
            size_t const resultCount =
                    meshopt_simplify(destination.data(), localIndices.data(), localIndices.size(),
                            &localPositions[0].x, localPositions.size(), sizeof(math::float3),
                            attemptTarget, attemptError, meshoptOptions, &resultError);
            if (profile != nullptr) {
                profile->meshoptSeconds += profileSeconds(meshoptStart);
            }

            std::vector<uint32_t> candidate(resultCount);
            for (size_t i = 0; i < resultCount; ++i) {
                candidate[i] = localToGlobal[destination[i]];
            }
            Candidate fallback;
            auto const gateStart = ProfileClock::now();
            fallback.level = prepareCandidate(std::move(candidate), resultError,
                    resultError * localScale, mesh, true);
            if (profile != nullptr) {
                profile->candidateGateSeconds += profileSeconds(gateStart);
            }
            fallback.acceptable = fallback.level.simplified &&
                                  acceptable(fallback.level, mesh, options.seamCollapse,
                                          options.seamCollapse, nullptr, &fallback.rejectMask);
            if (profile != nullptr) {
                profile->meshoptCandidates += 1;
            }
            candidates.push_back(std::move(fallback));
        }

        auto attributeScore = [](LodLevel const& level) {
            return level.attributes.maxNormalErrorRadians + level.attributes.maxUvError;
        };
        std::sort(candidates.begin(), candidates.end(),
                [&](Candidate const& a, Candidate const& b) {
                    if (a.acceptable != b.acceptable) {
                        return a.acceptable;
                    }
                    size_t const slack = std::max<size_t>(3, attemptTarget / 20);
                    if (a.level.indices.size() + slack < b.level.indices.size()) {
                        return true;
                    }
                    if (b.level.indices.size() + slack < a.level.indices.size()) {
                        return false;
                    }
                    return attributeScore(a.level) < attributeScore(b.level);
                });

        for (Candidate const& candidate: candidates) {
            LodLevel const& level = candidate.level;
            if (options.verbose && level.simplified && !candidate.acceptable) {
                std::fprintf(stderr,
                        "quality reject: source=%zu target=%zu got=%zu attempt=%u "
                        "boundary=%llu/%llu nonManifold=%llu/%llu minQuality=%.4f/%.4f "
                        "duplicate=%llu degenerate=%llu flipped=%llu "
                        "normal=%.2f/%.2fdeg uv=%.4f/%.4f world=%.6f/%.6f rel=%.6f "
                        "worstN=%u/%u worstUv=%u/%u reason=0x%x\n",
                        source.size(), attemptTarget, level.indices.size(), attempt + 1,
                        (unsigned long long) level.topology.boundaryEdges,
                        (unsigned long long) baseTopology.boundaryEdges,
                        (unsigned long long) level.topology.nonManifoldEdges,
                        (unsigned long long) baseTopology.nonManifoldEdges,
                        level.topology.minTriangleQuality, baseTopology.minTriangleQuality,
                        (unsigned long long) level.topology.duplicateTriangles,
                        (unsigned long long) level.topology.degenerateTriangles,
                        (unsigned long long) level.topology.flippedTriangles,
                        level.attributes.maxNormalErrorRadians * 57.2957795f,
                        level.attributes.meanNormalErrorRadians * 57.2957795f,
                        level.attributes.maxUvError, level.attributes.meanUvError, level.worldError,
                        std::max(options.targetError, 1e-5f) * meshScale, level.relativeError,
                        level.attributes.worstNormalVertex, level.attributes.worstNormalTriangle,
                        level.attributes.worstUvVertex, level.attributes.worstUvTriangle,
                        candidate.rejectMask);
            }
            if (candidate.acceptable) {
                *out = level;
                accepted = true;
                if (profile != nullptr) {
                    profile->accepted += 1;
                }
                break;
            }
        }
        if (accepted) {
            break;
        }

        // Back off toward the base triangle count, and tighten the error cap as we do so.
        size_t const gap = source.size() > attemptTarget ? source.size() - attemptTarget : 0;
        attemptTarget = std::min(source.size(), attemptTarget + std::max<size_t>(3, gap / 3));
        if (attemptTarget >= source.size()) {
            break;
        }
    }

    if (!accepted) {
        // A level that fails the hard gate is worse than no level at all: a visible sliver or a
        // new boundary edge cannot be repaired by the neural stage. Keep level 0 for this unit
        // and let the caller stop its chain instead of emitting a broken mesh.
        out->indices = source;
        out->relativeError = 0.0f;
        out->worldError = 0.0f;
        out->topology = baseTopology;
        out->attributes = {};
        out->attempts = std::max(1u, options.qualityAttempts);
        out->simplified = false;
    }

    for (uint32_t global: localToGlobal) {
        (*remap)[global] = -1;
    }
}

std::vector<LodLevel> simplifyChainByMaterial(Mesh const& mesh, SimplifyOptions const& options) {
    std::map<std::pair<uint32_t, uint32_t>, std::vector<uint32_t>> partitions;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        uint32_t const material = mesh.hasMaterialIds() ? mesh.materialIds[i / 3] : UINT32_MAX;
        uint32_t const submesh = mesh.hasSubmeshIds() ? mesh.submeshIds[i / 3] : UINT32_MAX;
        auto& indices = partitions[{ material, submesh }];
        indices.push_back(mesh.indices[i + 0]);
        indices.push_back(mesh.indices[i + 1]);
        indices.push_back(mesh.indices[i + 2]);
    }
    if (partitions.size() <= 1) {
        return {};
    }

    float const worldScale = relativeToWorldScale(mesh);
    unsigned int const flags = options.lockBorder ? meshopt_SimplifyLockBorder : 0;
    std::vector<int32_t> remap(mesh.positions.size(), -1);
    SimplifyScratch scratch;
    SimplifyOptions localOptions = options;
    localOptions.meshCacheEpoch = nextMeshCacheEpoch();
    std::vector<std::vector<LodLevel>> chains;
    chains.reserve(partitions.size());

    for (auto const& [primitive, indices]: partitions) {
        std::vector<LodLevel> levels(1);
        levels[0].indices = indices;
        levels[0].materialId = primitive.first;
        levels[0].submeshId = primitive.second;
        levels[0].topology = measureTopology(mesh, indices);

        for (uint32_t level = 1; level < options.levels; ++level) {
            size_t const target = targetIndexCountForLevel(indices.size(), level, options.ratio);
            if (target == 0 || target >= indices.size()) {
                break;
            }
            LodLevel next;
            simplifyClusterInto(indices, mesh, &remap, &scratch, target, options.targetError,
                    worldScale, localOptions, flags, &next, nullptr);
            next.materialId = primitive.first;
            next.submeshId = primitive.second;
            if (!next.simplified || next.indices.size() >= levels.back().indices.size()) {
                break;
            }
            levels.push_back(std::move(next));
        }
        chains.push_back(std::move(levels));
    }

    size_t levelCount = 1;
    for (auto const& chain: chains) {
        levelCount = std::max(levelCount, chain.size());
    }

    std::vector<LodLevel> result(levelCount);
    for (size_t level = 0; level < levelCount; ++level) {
        LodLevel& merged = result[level];
        merged.materialId = UINT32_MAX;
        merged.submeshId = UINT32_MAX;
        merged.simplified = level > 0;
        for (auto const& chain: chains) {
            size_t const clamped = std::min(level, chain.size() - 1);
            LodLevel const& part = chain[clamped];
            size_t const triangleCount = part.triangleCount();
            merged.indices.insert(merged.indices.end(), part.indices.begin(), part.indices.end());
            for (size_t t = 0; t < triangleCount; ++t) {
                merged.materialIds.push_back(part.materialId);
                merged.submeshIds.push_back(part.submeshId);
            }
            merged.worldError = std::max(merged.worldError, part.worldError);
            merged.relativeError = std::max(merged.relativeError, part.relativeError);
            merged.attempts = std::max(merged.attempts, part.attempts);
            if (!part.simplified && level > 0) {
                merged.simplified = false;
            }
        }
        merged.topology = measureTopology(mesh, merged.indices);
    }
    return result;
}

} // anonymous namespace

TopologyStats measureWeldedTopology(Mesh const& mesh, std::vector<uint32_t> const& indices) {
    return measureWeldedTopologyImpl(mesh, indices);
}

float relativeToWorldScale(Mesh const& mesh) noexcept {
    if (mesh.positions.empty()) {
        return 1.0f;
    }
    return meshopt_simplifyScale(&mesh.positions[0].x, mesh.positions.size(), sizeof(math::float3));
}

std::vector<LodLevel> simplifyChain(Mesh const& mesh, SimplifyOptions const& options) {
    std::vector<LodLevel> levels;

    if (mesh.empty() || options.levels == 0) {
        return levels;
    }

    if (mesh.hasMaterialIds() || mesh.hasSubmeshIds()) {
        levels = simplifyChainByMaterial(mesh, options);
        if (!levels.empty()) {
            return levels;
        }
    }

    float const worldScale = relativeToWorldScale(mesh);
    unsigned int const flags = options.lockBorder ? meshopt_SimplifyLockBorder : 0;
    std::vector<int32_t> remap(mesh.positions.size(), -1);
    SimplifyScratch scratch;
    SimplifyOptions localOptions = options;
    localOptions.meshCacheEpoch = nextMeshCacheEpoch();

    levels.resize(1);
    levels[0].indices = mesh.indices;
    levels[0].materialId = mesh.hasMaterialIds() ? mesh.materialIds[0] : UINT32_MAX;
    levels[0].submeshId = mesh.hasSubmeshIds() ? mesh.submeshIds[0] : UINT32_MAX;
    for (size_t t = 1; t < mesh.triangleCount(); ++t) {
        if (mesh.hasMaterialIds() && mesh.materialIds[t] != levels[0].materialId) {
            levels[0].materialId = UINT32_MAX;
        }
        if (mesh.hasSubmeshIds() && mesh.submeshIds[t] != levels[0].submeshId) {
            levels[0].submeshId = UINT32_MAX;
        }
    }

    for (uint32_t level = 1; level < options.levels; ++level) {
        size_t const target = targetIndexCountForLevel(mesh.indices.size(), level, options.ratio);
        if (target == 0 || target >= mesh.indices.size()) {
            break;
        }

        LodLevel next;
        // Every level is simplified from the original geometry rather than from the previous
        // level. It costs one extra pass but yields better quality, and it makes the reported
        // error absolute with respect to the input instead of relative to an intermediate.
        simplifyClusterInto(mesh.indices, mesh, &remap, &scratch, target, options.targetError,
                worldScale, localOptions, flags, &next, nullptr);
        next.materialId = levels[0].materialId;
        next.submeshId = levels[0].submeshId;

        if (!next.simplified) {
            break;
        }
        if (next.indices.size() >= levels.back().indices.size()) {
            break; // no further progress is possible, stop instead of emitting duplicates
        }
        levels.push_back(std::move(next));
    }

    return levels;
}

std::vector<ClusterLods> simplifyClusters(Mesh const& mesh, ClusterSet const& clusters,
        SimplifyOptions const& options, SimplifyProfile* profile) {
    std::vector<ClusterLods> result(clusters.clusters.size());

    if (mesh.empty() || options.levels == 0) {
        return result;
    }

    float const worldScale = relativeToWorldScale(mesh);
    unsigned int const flags = options.lockBorder ? meshopt_SimplifyLockBorder : 0;
    SimplifyOptions localOptions = options;
    localOptions.meshCacheEpoch = nextMeshCacheEpoch();

    std::vector<SimplifyProfile> profiles(clusters.clusters.size());
    detail::parallelFor(clusters.clusters.size(), [&](size_t c) {
        thread_local std::vector<int32_t> remap;
        thread_local SimplifyScratch scratch;
        if (remap.size() != mesh.positions.size()) {
            remap.assign(mesh.positions.size(), -1);
        }
        std::vector<uint32_t> const& base = clusters.clusters[c].indices;
        ClusterLods& lods = result[c];

        lods.levels.resize(1);
        lods.levels[0].indices = base;
        lods.levels[0].topology = measureTopology(mesh, base);
        lods.levels[0].materialId = clusters.clusters[c].materialId;
        lods.levels[0].submeshId = clusters.clusters[c].submeshId;

        if (base.empty()) {
            return;
        }

        for (uint32_t level = 1; level < options.levels; ++level) {
            size_t const target = targetIndexCountForLevel(base.size(), level, options.ratio);
            if (target == 0 || target >= base.size()) {
                break;
            }

            LodLevel next;
            simplifyClusterInto(base, mesh, &remap, &scratch, target, options.targetError,
                    worldScale, localOptions, flags, &next, &profiles[c]);
            next.materialId = clusters.clusters[c].materialId;
            next.submeshId = clusters.clusters[c].submeshId;

            if (!next.simplified || next.indices.size() >= lods.levels.back().indices.size()) {
                break;
            }
            // Every level is simplified from the original cluster, so its error is already
            // absolute with respect to level 0. Two different decimation targets can still
            // measure in the opposite order because they explore different collapses, and a
            // non-monotonic chain would let a coarser level look safer than a finer one.
            // Report the conservative envelope of the chain; overestimating a level can only
            // make selection keep more triangles, never fewer.
            next.worldError = std::max(next.worldError, lods.levels.back().worldError);
            next.relativeError = std::max(next.relativeError, lods.levels.back().relativeError);
            lods.levels.push_back(std::move(next));
        }
    });

    if (profile != nullptr) {
        for (SimplifyProfile const& local: profiles) {
            profile->attributeQemSeconds += local.attributeQemSeconds;
            profile->cornerSeconds += local.cornerSeconds;
            profile->cornerSetupSeconds += local.cornerSetupSeconds;
            profile->cornerEvaluateSeconds += local.cornerEvaluateSeconds;
            profile->cornerEvaluateTopologySeconds += local.cornerEvaluateTopologySeconds;
            profile->cornerTopologyNeighborSeconds += local.cornerTopologyNeighborSeconds;
            profile->cornerTopologyTriangleSeconds += local.cornerTopologyTriangleSeconds;
            profile->cornerTopologyLocalTriangleSeconds += local.cornerTopologyLocalTriangleSeconds;
            profile->cornerTopologyLocalEdgeSeconds += local.cornerTopologyLocalEdgeSeconds;
            profile->cornerEvaluateTargetSeconds += local.cornerEvaluateTargetSeconds;
            profile->cornerApplySeconds += local.cornerApplySeconds;
            profile->cornerEvaluations += local.cornerEvaluations;
            profile->cornerPlacementTests += local.cornerPlacementTests;
            profile->cornerApplied += local.cornerApplied;
            profile->meshoptSeconds += local.meshoptSeconds;
            profile->candidateGateSeconds += local.candidateGateSeconds;
            profile->candidateCleanupSeconds += local.candidateCleanupSeconds;
            profile->candidateSliverSeconds += local.candidateSliverSeconds;
            profile->candidateErrorSeconds += local.candidateErrorSeconds;
            profile->candidateTopologySeconds += local.candidateTopologySeconds;
            profile->weldedTopologySeconds += local.weldedTopologySeconds;
            profile->boundaryCheckSeconds += local.boundaryCheckSeconds;
            profile->lockedMaskSeconds += local.lockedMaskSeconds;
            profile->lockedMaskBuildSeconds += local.lockedMaskBuildSeconds;
            profile->extendedMeshSeconds += local.extendedMeshSeconds;
            profile->calls += local.calls;
            profile->attempts += local.attempts;
            profile->attributeCandidates += local.attributeCandidates;
            profile->cornerCandidates += local.cornerCandidates;
            profile->meshoptCandidates += local.meshoptCandidates;
            profile->accepted += local.accepted;
            profile->extendedMeshCopies += local.extendedMeshCopies;
        }
    }

    return result;
}

void simplifyIndices(Mesh const& mesh, std::vector<uint32_t> const& indices,
        size_t targetIndexCount, SimplifyOptions const& options, LodLevel* out,
        SimplifyProfile* profile) {
    if (out == nullptr) {
        return;
    }
    out->indices = indices;
    out->materialId = UINT32_MAX;
    out->submeshId = UINT32_MAX;
    out->simplified = false;
    out->attempts = 0;
    if (mesh.empty() || indices.size() < 3 || targetIndexCount >= indices.size()) {
        return;
    }

    float const worldScale = relativeToWorldScale(mesh);
    unsigned int const flags = options.lockBorder ? meshopt_SimplifyLockBorder : 0;
    // Group simplification runs on worker threads and is called many times per level. Keep the
    // mesh-sized remap and the compacted unit buffers alive per thread; simplifyClusterInto
    // resets every touched remap entry before returning.
    thread_local std::vector<int32_t> remap;
    thread_local SimplifyScratch scratch;
    if (remap.size() != mesh.positions.size()) {
        remap.assign(mesh.positions.size(), -1);
    }
    simplifyClusterInto(indices, mesh, &remap, &scratch, (targetIndexCount / 3) * 3,
            options.targetError, worldScale, options, flags, out, profile);
}

} // namespace manymesh
} // namespace filament
