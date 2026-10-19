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

#include <manymesh/LodGraph.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <functional>
#include <limits>
#include <queue>
#include <unordered_map>
#include <utility>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

struct GeneratedVertexKey {
    uint32_t positionSource = 0;
    int32_t position[3] = {};
    int32_t normal[3] = {};
    int32_t uv[2] = {};
    int32_t ao = 0;

    bool operator==(GeneratedVertexKey const& other) const noexcept {
        return positionSource == other.positionSource && position[0] == other.position[0] &&
               position[1] == other.position[1] && position[2] == other.position[2] &&
               normal[0] == other.normal[0] && normal[1] == other.normal[1] &&
               normal[2] == other.normal[2] && uv[0] == other.uv[0] && uv[1] == other.uv[1] &&
               ao == other.ao;
    }
};

struct GeneratedVertexKeyHash {
    size_t operator()(GeneratedVertexKey const& key) const noexcept {
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

int32_t quantizeGeneratedAttribute(float value) { return int32_t(std::lround(value * 65536.0f)); }

GeneratedVertexKey generatedVertexKey(GeneratedVertex const& vertex) {
    GeneratedVertexKey key;
    // positionSource is a build-time lock hint, not part of the rendered vertex. Two corners
    // with the same position, normal and UV are interchangeable to the GPU, so share them.
    key.position[0] = quantizeGeneratedAttribute(vertex.position.x);
    key.position[1] = quantizeGeneratedAttribute(vertex.position.y);
    key.position[2] = quantizeGeneratedAttribute(vertex.position.z);
    key.normal[0] = quantizeGeneratedAttribute(vertex.normal.x);
    key.normal[1] = quantizeGeneratedAttribute(vertex.normal.y);
    key.normal[2] = quantizeGeneratedAttribute(vertex.normal.z);
    key.uv[0] = quantizeGeneratedAttribute(vertex.uv.x);
    key.uv[1] = quantizeGeneratedAttribute(vertex.uv.y);
    key.ao = quantizeGeneratedAttribute(vertex.ao);
    return key;
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
    float const x = position.x == 0.0f ? 0.0f : position.x;
    float const y = position.y == 0.0f ? 0.0f : position.y;
    float const z = position.z == 0.0f ? 0.0f : position.z;
    PositionKey key;
    std::memcpy(&key.x, &x, sizeof(float));
    std::memcpy(&key.y, &y, sizeof(float));
    std::memcpy(&key.z, &z, sizeof(float));
    return key;
}

uint32_t resolvePositionId(std::vector<uint32_t> const& positionIds, uint32_t vertex) noexcept {
    uint32_t result = vertex;
    for (size_t guard = 0; guard < positionIds.size() && result < positionIds.size(); ++guard) {
        uint32_t const next = positionIds[result];
        if (next == result) {
            break;
        }
        result = next;
    }
    return result;
}

/**
 * Appends one level's generated vertices to the graph-wide buffer and rewrites that level's
 * local index range to the global ids.
 *
 * Every simplification unit starts with the same graph vertex count, so its generated ids are
 * `baseVertexCount + local`. Deduplicating them globally is important: adjacent units and
 * successive hierarchy levels frequently invent the exact same chart corner, and sharing it
 * keeps the single vertex buffer used by a mixed-level cut bounded.
 */
void appendGeneratedVerticesToGraph(LodGraph* graph, Mesh* mesh,
        std::vector<GeneratedVertex> const& generated, uint32_t baseVertexCount,
        std::unordered_map<GeneratedVertexKey, uint32_t, GeneratedVertexKeyHash>* lookup,
        std::unordered_map<PositionKey, uint32_t, PositionKeyHash>* positions,
        std::vector<uint32_t>* positionIds, std::vector<uint32_t>* indices) {
    if (generated.empty()) {
        return;
    }
    bool const hasNormals = mesh->hasNormals();
    bool const hasUVs = mesh->hasUVs();
    bool const hasAO = mesh->hasAO();
    std::vector<uint32_t> localToGlobal;
    localToGlobal.reserve(generated.size());

    for (GeneratedVertex const& source: generated) {
        GeneratedVertex vertex = source;
        vertex.positionSource = resolvePositionId(*positionIds, source.positionSource);
        vertex.position =
                source.hasPosition ? source.position : mesh->positions[vertex.positionSource];
        vertex.hasPosition = true;
        GeneratedVertexKey const key = generatedVertexKey(vertex);
        auto const inserted = lookup->emplace(key, graph->vertexCount);
        if (inserted.second) {
            graph->generatedVertices.push_back(vertex);
            mesh->positions.push_back(vertex.position);
            if (hasNormals) {
                mesh->normals.push_back(vertex.normal);
            }
            if (hasUVs) {
                mesh->uvs.push_back(vertex.uv);
            }
            if (hasAO) {
                mesh->ao.push_back(vertex.ao);
            }
            PositionKey const positionKeyValue = positionKey(vertex.position);
            auto const positionInserted = positions->emplace(positionKeyValue, graph->vertexCount);
            positionIds->push_back(positionInserted.first->second);
            graph->vertexCount += 1;
        }
        localToGlobal.push_back(inserted.first->second);
    }

    for (uint32_t& index: *indices) {
        if (index < baseVertexCount) {
            continue;
        }
        size_t const local = size_t(index - baseVertexCount);
        if (local < localToGlobal.size()) {
            index = localToGlobal[local];
        }
    }
}

Sphere mergeSpheres(Sphere const& a, Sphere const& b) {
    math::float3 const delta = b.center - a.center;
    float const distance = length(delta);
    if (a.radius >= distance + b.radius) {
        return a;
    }
    if (b.radius >= distance + a.radius) {
        return b;
    }
    if (!(distance > 1e-6f)) {
        Sphere result = a;
        result.radius = std::max(a.radius, b.radius);
        return result;
    }
    float const radius = (a.radius + b.radius + distance) * 0.5f;
    Sphere result;
    result.center = a.center + delta * ((radius - a.radius) / distance);
    result.radius = radius;
    return result;
}

Cone mergeCones(Cone const& a, Cone const& b) {
    Cone result;
    result.apex = (a.apex + b.apex) * 0.5f;
    math::float3 const axis = a.axis + b.axis;
    float const axisLength = length(axis);
    result.axis = axisLength > 1e-6f ? axis / axisLength : a.axis;
    result.cutoff = std::min(a.cutoff, b.cutoff);
    return result;
}

std::vector<std::vector<uint32_t>> groupNodes(LodGraph const& graph,
        std::vector<uint32_t> const& current, uint32_t clustersPerNode, size_t vertexCount,
        std::vector<uint32_t> const* positionIds, std::vector<int32_t>* lastOwner,
        std::vector<uint32_t>* touchedOwners) {
    std::vector<std::vector<uint32_t>> groups;
    if (current.empty() || clustersPerNode <= 1) {
        for (uint32_t node: current) {
            groups.push_back({ node });
        }
        return groups;
    }

    size_t const count = current.size();
    std::vector<std::vector<uint32_t>> neighbors(count);
    std::vector<uint32_t> vertices;
    for (size_t c = 0; c < count; ++c) {
        LodGraphNode const& node = graph.nodes[current[c]];
        vertices.clear();
        vertices.reserve(node.indices.size());
        for (uint32_t vertex: node.indices) {
            if (positionIds != nullptr && vertex < positionIds->size()) {
                vertex = (*positionIds)[vertex];
            }
            if (vertex < vertexCount) {
                vertices.push_back(vertex);
            }
        }
        std::sort(vertices.begin(), vertices.end());
        vertices.erase(std::unique(vertices.begin(), vertices.end()), vertices.end());
        for (uint32_t vertex: vertices) {
            int32_t const previous = (*lastOwner)[vertex];
            if (previous < 0) {
                touchedOwners->push_back(vertex);
            }
            if (previous >= 0 && size_t(previous) != c) {
                neighbors[c].push_back(uint32_t(previous));
                neighbors[size_t(previous)].push_back(uint32_t(c));
            }
            (*lastOwner)[vertex] = int32_t(c);
        }
    }
    for (uint32_t vertex: *touchedOwners) {
        (*lastOwner)[vertex] = -1;
    }
    touchedOwners->clear();
    for (std::vector<uint32_t>& list: neighbors) {
        std::sort(list.begin(), list.end());
        list.erase(std::unique(list.begin(), list.end()), list.end());
    }

    std::vector<uint8_t> assigned(count, 0);
    using Candidate = std::pair<float, uint32_t>;
    std::priority_queue<Candidate, std::vector<Candidate>, std::greater<Candidate>> candidates;

    for (size_t seed = 0; seed < count; ++seed) {
        if (assigned[seed] != 0) {
            continue;
        }
        std::vector<uint32_t> members = { current[seed] };
        assigned[seed] = 1;
        auto enqueueNeighbors = [&](uint32_t local) {
            LodGraphNode const& node = graph.nodes[current[local]];
            for (uint32_t neighbor: neighbors[local]) {
                if (assigned[neighbor] != 0) {
                    continue;
                }
                LodGraphNode const& other = graph.nodes[current[neighbor]];
                if (other.materialId != node.materialId || other.submeshId != node.submeshId) {
                    continue;
                }
                math::float3 const delta = other.bounds.center - node.bounds.center;
                candidates.emplace(dot(delta, delta), neighbor);
            }
        };
        enqueueNeighbors(uint32_t(seed));

        while (members.size() < clustersPerNode && !candidates.empty()) {
            uint32_t const next = candidates.top().second;
            candidates.pop();
            if (assigned[next] != 0) {
                continue;
            }
            assigned[next] = 1;
            members.push_back(current[next]);
            enqueueNeighbors(next);
        }
        while (!candidates.empty()) {
            candidates.pop();
        }
        groups.push_back(std::move(members));
    }
    return groups;
}

struct CameraBasis {
    math::float3 forward;
    math::float3 right;
    math::float3 up;
    float tanHalfFovY = 1.0f;
    float aspect = 1.0f;
    bool valid = false;
};

CameraBasis makeBasis(ViewCamera const& camera) {
    CameraBasis basis;
    math::float3 forward = camera.target - camera.eye;
    float const forwardLength = length(forward);
    if (!(forwardLength > 1e-6f)) {
        return basis;
    }
    basis.forward = forward / forwardLength;
    math::float3 right = cross(basis.forward, camera.up);
    float const rightLength = length(right);
    if (!(rightLength > 1e-6f)) {
        return basis;
    }
    basis.right = right / rightLength;
    basis.up = cross(basis.right, basis.forward);
    basis.tanHalfFovY = std::max(std::tan(camera.fovY * 0.5f), 1e-4f);
    basis.aspect = float(camera.screenWidth) / float(std::max(camera.screenHeight, 1u));
    basis.valid = true;
    return basis;
}

bool sphereOutsideFrustum(Sphere const& sphere, ViewCamera const& camera,
        CameraBasis const& basis) {
    math::float3 const d = sphere.center - camera.eye;
    float const depth = dot(d, basis.forward);
    if (depth + sphere.radius < camera.near || depth - sphere.radius > camera.far) {
        return true;
    }
    float const halfHeight = depth * basis.tanHalfFovY;
    float const halfWidth = halfHeight * basis.aspect;
    if (std::abs(dot(d, basis.right)) - sphere.radius > halfWidth) {
        return true;
    }
    if (std::abs(dot(d, basis.up)) - sphere.radius > halfHeight) {
        return true;
    }
    return false;
}

float screenErrorForNode(LodGraphNode const& node, ScreenErrorProjection const& projection) {
    return screenSpaceErrorForSphere(node.accumulatedError, node.bounds, projection);
}

// Per-camera quantities that do not depend on the selected error threshold. The ratio solver
// evaluates dozens of thresholds, so computing these once per selection keeps the binary
// search from repeating the same frustum and projection work for every pass.
struct NodeMetrics {
    std::vector<float> screenError;
    std::vector<uint8_t> culled;
};

NodeMetrics makeNodeMetrics(LodGraph const& graph, ViewCamera const& camera,
        CameraBasis const& basis) {
    NodeMetrics metrics;
    metrics.screenError.resize(graph.nodes.size(), 0.0f);
    metrics.culled.resize(graph.nodes.size(), 0);
    ScreenErrorProjection const projection = makeScreenErrorProjection(camera);
    for (size_t i = 0; i < graph.nodes.size(); ++i) {
        LodGraphNode const& node = graph.nodes[i];
        if (basis.valid && sphereOutsideFrustum(node.bounds, camera, basis)) {
            metrics.culled[i] = 1;
        } else if (basis.valid) {
            metrics.screenError[i] = screenErrorForNode(node, projection);
        }
    }
    return metrics;
}

struct CutAtError {
    std::vector<uint32_t> nodes;
    uint64_t triangles = 0;
    uint64_t culledTriangles = 0;
};

// Adds one node whole, without looking at its children. Used when a cut is expanded: the
// parent is replaced by its immediate children, and each child is either drawn or culled.
void collectWholeNode(LodGraph const& graph, NodeMetrics const& metrics, uint32_t nodeId,
        CutAtError* cut) {
    LodGraphNode const& node = graph.nodes[nodeId];
    if (metrics.culled[nodeId] != 0) {
        cut->culledTriangles += node.baseTriangles;
        return;
    }
    cut->nodes.push_back(nodeId);
    cut->triangles += node.triangleCount();
}

// The minimum-triangle cut whose worst screen error is at most `thresholdPx`. Keeping a node
// is always cheaper than keeping its children, so the greedy decision is exact: descend only
// where the node itself is too coarse for the requested quality.
void collectCutAtError(LodGraph const& graph, NodeMetrics const& metrics, float thresholdPx,
        uint32_t nodeId, CutAtError* cut) {
    LodGraphNode const& node = graph.nodes[nodeId];
    if (metrics.culled[nodeId] != 0) {
        cut->culledTriangles += node.baseTriangles;
        return;
    }
    if (!node.children.empty() && metrics.screenError[nodeId] > thresholdPx) {
        for (uint32_t child: node.children) {
            collectCutAtError(graph, metrics, thresholdPx, child, cut);
        }
        return;
    }
    cut->nodes.push_back(nodeId);
    cut->triangles += node.triangleCount();
}

CutAtError cutAtError(LodGraph const& graph, NodeMetrics const& metrics, float thresholdPx) {
    CutAtError cut;
    for (uint32_t root: graph.roots) {
        collectCutAtError(graph, metrics, thresholdPx, root, &cut);
    }
    return cut;
}

float cutWorstScreenError(NodeMetrics const& metrics, std::vector<uint32_t> const& nodes) {
    float worst = 0.0f;
    for (uint32_t nodeId: nodes) {
        worst = std::max(worst, metrics.screenError[nodeId]);
    }
    return worst;
}

/**
 * Spends the remaining triangle budget on the cut that lowers the worst error least slowly.
 *
 * The binary search above already finds the cut with the optimal worst-case error for a given
 * triangle budget. Because that cut is discrete it often leaves budget unused, so this pass
 * expands nodes one at a time, preferring the expansion that removes the largest local error,
 * and never accepts an expansion that would make the worst error worse. That is what lets a
 * 50% saving request land near 50% instead of at the next coarse hierarchy step.
 */
void refineCutWithinBudget(LodGraph const& graph, NodeMetrics const& metrics, uint64_t budget,
        float stopAtErrorPx, CutAtError* cut) {
    for (size_t iteration = 0; iteration <= graph.nodes.size(); ++iteration) {
        float const currentWorst = cutWorstScreenError(metrics, cut->nodes);
        if (currentWorst <= stopAtErrorPx) {
            break;
        }

        // Only the worst and second worst node matter when one node is replaced: removing any
        // other node leaves the worst untouched. Caching those two avoids rebuilding the cut
        // for every candidate, which would be quadratic on a deep hierarchy.
        float worst = 0.0f;
        float secondWorst = 0.0f;
        size_t worstIndex = SIZE_MAX;
        for (size_t i = 0; i < cut->nodes.size(); ++i) {
            float const error = metrics.screenError[cut->nodes[i]];
            if (error > worst) {
                secondWorst = worst;
                worst = error;
                worstIndex = i;
            } else if (error > secondWorst) {
                secondWorst = error;
            }
        }

        size_t bestIndex = SIZE_MAX;
        float bestLocalGain = -std::numeric_limits<float>::max();
        CutAtError bestExpansion;
        for (size_t i = 0; i < cut->nodes.size(); ++i) {
            LodGraphNode const& node = graph.nodes[cut->nodes[i]];
            if (node.children.empty()) {
                continue;
            }
            CutAtError expanded;
            for (uint32_t child: node.children) {
                collectWholeNode(graph, metrics, child, &expanded);
            }
            int64_t const delta = int64_t(expanded.triangles) - int64_t(node.triangleCount());
            if (delta > 0 && uint64_t(delta) > budget - std::min(budget, cut->triangles)) {
                continue;
            }
            uint64_t const newTriangles =
                    cut->triangles - node.triangleCount() + expanded.triangles;
            if (newTriangles > budget) {
                continue;
            }

            // The node being replaced is no longer in the cut, so the new worst is the larger
            // of the untouched part of the cut and the expanded children.
            float const remainingWorst = i == worstIndex ? secondWorst : worst;
            float const childWorst = cutWorstScreenError(metrics, expanded.nodes);
            if (std::max(remainingWorst, childWorst) > currentWorst + 1e-4f) {
                continue;
            }

            float const nodeError = metrics.screenError[cut->nodes[i]];
            float const localGain = nodeError - childWorst;
            if (localGain > bestLocalGain + 1e-5f) {
                bestLocalGain = localGain;
                bestIndex = i;
                bestExpansion = std::move(expanded);
            }
        }
        if (bestIndex == SIZE_MAX) {
            break;
        }

        cut->triangles = cut->triangles - graph.nodes[cut->nodes[bestIndex]].triangleCount() +
                         bestExpansion.triangles;
        cut->culledTriangles += bestExpansion.culledTriangles;
        cut->nodes.erase(cut->nodes.begin() + bestIndex);
        cut->nodes.insert(cut->nodes.end(), bestExpansion.nodes.begin(), bestExpansion.nodes.end());
    }
}

LodGraphSelection selectionFromCut(LodGraph const& graph, NodeMetrics const& metrics,
        CutAtError const& cut) {
    LodGraphSelection selection;
    selection.baseTriangles = graph.baseTriangles;
    selection.culledTriangles = cut.culledTriangles;
    selection.nodesPerLevel.assign(graph.levelCount, 0);
    selection.trianglesPerLevel.assign(graph.levelCount, 0);
    selection.nodes = cut.nodes;
    for (uint32_t nodeId: cut.nodes) {
        LodGraphNode const& node = graph.nodes[nodeId];
        selection.screenErrorPerNode.push_back(metrics.screenError[nodeId]);
        selection.nodesPerLevel[node.level] += 1;
    }

    // Two independently simplified clusters can both produce the same triangle at a shared
    // border, and a SeamSimplifier output can contain coincident faces built from different
    // attribute vertices at one position. Each node is clean on its own by index, so the
    // per-node quality gate cannot see either case. Deduplicate the assembled cut by canonical
    // position ids: the remaining copy covers the same surface, and removing the extra faces
    // also removes the false non-manifold edges they create.
    auto const positionOf = [&graph](uint32_t vertex) {
        return vertex < graph.positionIds.size() ? graph.positionIds[vertex] : vertex;
    };
    // Open addressing keeps the test allocation-free per face. Keys are sorted so the result
    // ignores winding, matching the previous duplicate definition.
    struct TriangleSet {
        struct Slot {
            uint32_t a = UINT32_MAX;
            uint32_t b = 0;
            uint32_t c = 0;
        };
        std::vector<Slot> slots = std::vector<Slot>(1024);
        size_t count = 0;

        static uint64_t hash(uint32_t a, uint32_t b, uint32_t c) noexcept {
            uint64_t h = uint64_t(a) * 0x9e3779b185ebca87ull;
            h ^= uint64_t(b) * 0xc2b2ae3d27d4eb4full;
            h ^= uint64_t(c) * 0x165667b19e3779f9ull;
            h ^= h >> 33;
            h *= 0xff51afd7ed558ccdull;
            h ^= h >> 33;
            return h;
        }

        bool insert(uint32_t a, uint32_t b, uint32_t c) {
            uint32_t const lo = std::min({ a, b, c });
            uint32_t const hi = std::max({ a, b, c });
            uint32_t const mid = a + b + c - lo - hi;
            if ((count + 1) * 2 > slots.size()) {
                grow();
            }
            size_t const mask = slots.size() - 1;
            size_t index = size_t(hash(lo, mid, hi)) & mask;
            while (true) {
                Slot& slot = slots[index];
                if (slot.a == UINT32_MAX) {
                    slot = { lo, mid, hi };
                    ++count;
                    return true;
                }
                if (slot.a == lo && slot.b == mid && slot.c == hi) {
                    return false;
                }
                index = (index + 1) & mask;
            }
        }

        void clear() {
            std::fill(slots.begin(), slots.end(), Slot{});
            count = 0;
        }

    private:
        void grow() {
            std::vector<Slot> old = std::move(slots);
            slots.assign(old.size() * 2, Slot{});
            count = 0;
            for (Slot const& slot: old) {
                if (slot.a != UINT32_MAX) {
                    insert(slot.a, slot.b, slot.c);
                }
            }
        }
    };

    // Ratio selection evaluates many cuts back to back. Reuse the table so a slider drag does
    // not allocate a fresh hash set for every threshold.
    thread_local TriangleSet seenFaces;
    seenFaces.clear();
    std::vector<uint32_t> indices;
    std::vector<uint32_t> materialIds;
    std::vector<uint32_t> submeshIds;
    indices.reserve(cut.triangles * 3);
    materialIds.reserve(cut.triangles);
    submeshIds.reserve(cut.triangles);
    for (uint32_t nodeId: cut.nodes) {
        LodGraphNode const& node = graph.nodes[nodeId];
        for (size_t t = 0; t < node.triangleCount(); ++t) {
            uint32_t const a = node.indices[t * 3 + 0];
            uint32_t const b = node.indices[t * 3 + 1];
            uint32_t const c = node.indices[t * 3 + 2];
            if (a == b || b == c || c == a) {
                continue;
            }
            if (!seenFaces.insert(positionOf(a), positionOf(b), positionOf(c))) {
                continue;
            }
            indices.push_back(a);
            indices.push_back(b);
            indices.push_back(c);
            materialIds.push_back(node.materialId);
            submeshIds.push_back(node.submeshId);
            selection.trianglesPerLevel[node.level] += 1;
            selection.selectedTriangles += 1;
        }
    }
    selection.indices = std::move(indices);
    selection.materialIds = std::move(materialIds);
    selection.submeshIds = std::move(submeshIds);
    return selection;
}

LodGraphSelection selectImpl(LodGraph const& graph, ViewCamera const& camera, float thresholdPx) {
    CameraBasis const basis = makeBasis(camera);
    NodeMetrics const metrics = makeNodeMetrics(graph, camera, basis);
    return selectionFromCut(graph, metrics, cutAtError(graph, metrics, thresholdPx));
}

} // anonymous namespace

LodGraph buildLodGraph(Mesh const& mesh, LodGraphOptions const& options,
        LodGraphBuildStats* stats) {
    using Clock = std::chrono::steady_clock;
    auto const buildStart = Clock::now();
    auto secondsSince = [](Clock::time_point start) {
        return std::chrono::duration<double>(Clock::now() - start).count();
    };
    if (stats != nullptr) {
        *stats = {};
    }

    LodGraph graph;
    if (mesh.empty() || options.levels == 0) {
        if (stats != nullptr) {
            stats->totalSeconds = secondsSince(buildStart);
        }
        return graph;
    }

    auto const clusterizeStart = Clock::now();
    ClusterSet const clusters = clusterize(mesh, options.clusterize);
    if (stats != nullptr) {
        stats->clusterizeSeconds = secondsSince(clusterizeStart);
    }

    auto const leafSetupStart = Clock::now();
    uint32_t const sourceVertexCount = uint32_t(mesh.positions.size());
    graph.vertexCount = sourceVertexCount;
    Mesh graphMesh = mesh;
    std::vector<uint32_t> graphPositionIds(sourceVertexCount);
    std::unordered_map<PositionKey, uint32_t, PositionKeyHash> graphPositions;
    graphPositions.reserve(sourceVertexCount * 2);
    for (uint32_t i = 0; i < sourceVertexCount; ++i) {
        auto const inserted = graphPositions.emplace(positionKey(graphMesh.positions[i]), i);
        graphPositionIds[i] = inserted.first->second;
    }
    std::unordered_map<GeneratedVertexKey, uint32_t, GeneratedVertexKeyHash> generatedLookup;
    generatedLookup.reserve(1024);
    graph.levelCount = 1;
    graph.nodes.reserve(clusters.clusters.size() * 2);
    graph.leaves.reserve(clusters.clusters.size());
    for (Cluster const& cluster: clusters.clusters) {
        LodGraphNode node;
        node.level = 0;
        node.indices = cluster.indices;
        node.bounds = cluster.bounds;
        node.cone = cluster.cone;
        node.materialId = cluster.materialId;
        node.submeshId = cluster.submeshId;
        node.baseTriangles = cluster.triangleCount();
        node.topology = measureTopology(mesh, node.indices);
        node.simplified = false;
        graph.baseTriangles += node.baseTriangles;
        graph.leaves.push_back(uint32_t(graph.nodes.size()));
        graph.nodes.push_back(std::move(node));
    }

    // A vertex referenced by more than one leaf is a seam vertex. Per-cluster chains must not
    // move or rewrite such a vertex, otherwise both sides can collapse into the same chord and
    // the assembled cut contains overlapping triangles and non-manifold edges.
    std::vector<uint32_t> vertexLeafUse(sourceVertexCount, 0);
    {
        std::vector<uint32_t> vertices;
        for (uint32_t leaf: graph.leaves) {
            vertices = graph.nodes[leaf].indices;
            std::sort(vertices.begin(), vertices.end());
            vertices.erase(std::unique(vertices.begin(), vertices.end()), vertices.end());
            for (uint32_t vertex: vertices) {
                vertexLeafUse[graphPositionIds[vertex]] += 1;
            }
        }
    }
    std::vector<uint8_t> sharedVertexMask(sourceVertexCount, 0);
    for (size_t v = 0; v < vertexLeafUse.size(); ++v) {
        sharedVertexMask[v] = vertexLeafUse[graphPositionIds[v]] > 1 ? 1 : 0;
    }
    if (stats != nullptr) {
        stats->leafSetupSeconds = secondsSince(leafSetupStart);
    }

    // Per-cluster chains. A hierarchy that only merges neighbouring clusters cannot reduce a
    // chart that has no neighbours at all, and imports with many UV/normal seams produce a lot
    // of those (a monkey OBJ is a good example: most of its charts are isolated). Giving each
    // cluster its own coarse variants keeps those charts reducible and, just as importantly,
    // adds fine-grained cuts between the group levels so a triangle budget can be met closely.
    auto const clusterChainStart = Clock::now();
    SimplifyOptions clusterOptions = options.simplify;
    clusterOptions.lockedVertices = &sharedVertexMask;
    std::vector<ClusterLods> const clusterLods = simplifyClusters(mesh, clusters, clusterOptions,
            stats != nullptr ? &stats->clusterSimplify : nullptr);
    std::vector<uint32_t> chainTops;
    chainTops.reserve(graph.leaves.size());
    uint32_t maxChainLevel = 0;
    for (size_t c = 0; c < graph.leaves.size(); ++c) {
        uint32_t previous = graph.leaves[c];
        ClusterLods const& lods = clusterLods[c];
        for (size_t l = 1; l < lods.levels.size(); ++l) {
            LodLevel const& level = lods.levels[l];
            if (!level.simplified || level.indices.size() >= graph.nodes[previous].indices.size()) {
                break;
            }
            std::vector<uint32_t> nodeIndices = level.indices;
            appendGeneratedVerticesToGraph(&graph, &graphMesh, level.generatedVertices,
                    sourceVertexCount, &generatedLookup, &graphPositions, &graphPositionIds,
                    &nodeIndices);
            LodGraphNode node;
            node.level = uint32_t(l);
            node.children = { previous };
            node.indices = std::move(nodeIndices);
            node.bounds = graph.nodes[graph.leaves[c]].bounds;
            node.cone = graph.nodes[graph.leaves[c]].cone;
            node.materialId = level.materialId;
            node.submeshId = level.submeshId;
            // Every cluster level is simplified from the original cluster and measured
            // against it, so the reported error is already absolute with respect to the
            // leaf. Adding the previous level's error would double count it.
            node.accumulatedError = level.worldError;
            node.selfError =
                    std::max(0.0f, level.worldError - graph.nodes[previous].accumulatedError);
            node.topology = level.topology;
            node.attributes = level.attributes;
            node.simplified = true;
            node.baseTriangles = graph.nodes[graph.leaves[c]].baseTriangles;

            uint32_t const id = uint32_t(graph.nodes.size());
            graph.nodes[previous].parent = id;
            graph.nodes.push_back(std::move(node));
            previous = id;
            maxChainLevel = std::max(maxChainLevel, uint32_t(l));
        }
        chainTops.push_back(previous);
        if (stats != nullptr) {
            stats->clusterSimplifyCalls += 1;
            for (LodLevel const& level: lods.levels) {
                if (level.simplified) {
                    stats->clusterSimplifyAccepted += 1;
                    stats->clusterSimplifyAttempts += level.attempts;
                }
            }
        }
    }
    graph.levelCount = std::max(graph.levelCount, maxChainLevel + 1);
    if (stats != nullptr) {
        stats->clusterChainSeconds = secondsSince(clusterChainStart);
    }

    std::vector<uint32_t> current = std::move(chainTops);
    SimplifyOptions simplifyOptions = options.simplify;
    static std::atomic<uint64_t> nextMeshCacheEpoch{ 1 };
    simplifyOptions.meshCacheEpoch = nextMeshCacheEpoch.fetch_add(1, std::memory_order_relaxed);
    simplifyOptions.levels = 1;
    simplifyOptions.qualityAttempts = std::max(1u, options.simplify.qualityAttempts);
    // A group contains both sides of its internal UV/normal seams. Pair their boundary
    // collapses so the group can reduce past the old 1/3-barrier without opening a crack.
    simplifyOptions.seamCollapse = true;

    std::vector<int32_t> groupLastOwner(sourceVertexCount, -1);
    std::vector<uint32_t> groupTouchedOwners;

    for (uint32_t depth = 0; depth < options.levels && !current.empty(); ++depth) {
        uint32_t const level = maxChainLevel + 1 + depth;
        uint32_t const levelVertexCount = graph.vertexCount;
        auto const groupBuildStart = Clock::now();
        std::vector<std::vector<uint32_t>> groups =
                groupNodes(graph, current, std::max(2u, options.clustersPerNode), sourceVertexCount,
                        &graphPositionIds, &groupLastOwner, &groupTouchedOwners);
        struct GroupBuildResult {
            bool candidate = false;
            bool promoted = false;
            uint32_t attempts = 0;
            uint64_t seamLockedVertices = 0;
            std::vector<GeneratedVertex> generatedVertices;
            LodGraphNode parent;
            SimplifyProfile profile;
        };
        std::vector<GroupBuildResult> results(groups.size());

        auto const groupSimplifyStart = Clock::now();
        detail::parallelFor(groups.size(), [&](size_t groupIndex) {
            std::vector<uint32_t> const& members = groups[groupIndex];
            GroupBuildResult& result = results[groupIndex];
            if (members.empty()) {
                return;
            }
            result.candidate = true;

            thread_local std::vector<uint32_t> memberUse;
            thread_local std::vector<uint32_t> memberTouched;
            thread_local std::vector<uint8_t> groupLockMask;
            thread_local std::vector<uint32_t> groupLocked;
            if (memberUse.size() != sourceVertexCount) {
                memberUse.assign(sourceVertexCount, 0);
            }
            if (groupLockMask.size() != levelVertexCount) {
                groupLockMask.assign(levelVertexCount, 0);
            }
            for (uint32_t vertex: groupLocked) {
                groupLockMask[vertex] = 0;
            }
            groupLocked.clear();
            memberTouched.clear();

            std::vector<uint32_t> combined;
            size_t combinedSize = 0;
            for (uint32_t member: members) {
                combinedSize += graph.nodes[member].indices.size();
            }
            combined.reserve(combinedSize);
            for (uint32_t member: members) {
                auto const& indices = graph.nodes[member].indices;
                combined.insert(combined.end(), indices.begin(), indices.end());
            }

            auto positionOf = [&graphPositionIds](uint32_t vertex) {
                return vertex < graphPositionIds.size() ? graphPositionIds[vertex] : vertex;
            };
            std::vector<uint32_t> memberVertices;
            for (uint32_t member: members) {
                std::vector<uint32_t> vertices = graph.nodes[member].indices;
                std::sort(vertices.begin(), vertices.end());
                vertices.erase(std::unique(vertices.begin(), vertices.end()), vertices.end());
                for (uint32_t vertex: vertices) {
                    uint32_t const position = positionOf(vertex);
                    if (position >= sourceVertexCount) {
                        continue;
                    }
                    if (memberUse[position] == 0) {
                        memberTouched.push_back(position);
                    }
                    memberUse[position] += 1;
                    memberVertices.push_back(vertex);
                }
            }
            for (uint32_t vertex: memberVertices) {
                uint32_t const position = positionOf(vertex);
                if (position < sourceVertexCount && vertexLeafUse[position] > memberUse[position]) {
                    groupLockMask[vertex] = 1;
                    groupLocked.push_back(vertex);
                }
            }
            for (uint32_t position: memberTouched) {
                memberUse[position] = 0;
            }
            memberTouched.clear();
            result.seamLockedVertices = groupLocked.size();

            size_t const target = std::max<size_t>(3,
                    (size_t(double(combined.size()) * double(options.ratio)) / 3) * 3);
            SimplifyOptions localOptions = simplifyOptions;
            localOptions.lockedVertices = &groupLockMask;
            localOptions.vertexPositionIds = &graphPositionIds;
            LodLevel simplified;
            simplifyIndices(graphMesh, combined, target, localOptions, &simplified,
                    &result.profile);
            result.attempts = simplified.attempts;
            if (!simplified.simplified || simplified.indices.size() >= combined.size()) {
                return;
            }
            // A single-member group is a chain level: it continues simplifying a node that has
            // no siblings left to merge with. Require a real reduction so a nearly exhausted
            // cluster does not add a level (and a full set of generated vertices) for a handful
            // of triangles. Multi-member groups are still allowed to reduce as little as the
            // quality gate accepts, because their main job is to unlock interior edges.
            if (members.size() == 1 && simplified.indices.size() + 6 > combined.size()) {
                return;
            }
            result.promoted = true;
            result.generatedVertices = std::move(simplified.generatedVertices);

            LodGraphNode parent;
            parent.level = level;
            parent.children = members;
            parent.indices = std::move(simplified.indices);
            parent.bounds = graph.nodes[members[0]].bounds;
            parent.cone = graph.nodes[members[0]].cone;
            parent.materialId = graph.nodes[members[0]].materialId;
            parent.submeshId = graph.nodes[members[0]].submeshId;
            parent.selfError = simplified.worldError;
            parent.accumulatedError = parent.selfError;
            parent.topology = simplified.topology;
            parent.attributes = simplified.attributes;
            parent.simplified = true;
            for (size_t i = 1; i < members.size(); ++i) {
                parent.bounds = mergeSpheres(parent.bounds, graph.nodes[members[i]].bounds);
                parent.cone = mergeCones(parent.cone, graph.nodes[members[i]].cone);
            }
            for (uint32_t member: members) {
                parent.baseTriangles += graph.nodes[member].baseTriangles;
                parent.accumulatedError = std::max(parent.accumulatedError,
                        parent.selfError + graph.nodes[member].accumulatedError);
            }
            result.parent = std::move(parent);
        });
        if (stats != nullptr) {
            stats->groupSimplifySeconds += secondsSince(groupSimplifyStart);
        }

        std::vector<uint32_t> next;
        bool createdParent = false;
        for (size_t groupIndex = 0; groupIndex < groups.size(); ++groupIndex) {
            std::vector<uint32_t> const& members = groups[groupIndex];
            GroupBuildResult& result = results[groupIndex];
            if (!result.candidate) {
                next.insert(next.end(), members.begin(), members.end());
                continue;
            }
            if (stats != nullptr) {
                stats->groupCandidates += 1;
                stats->seamLockedVertices += result.seamLockedVertices;
                stats->groupSimplifyCalls += 1;
                stats->groupSimplifyAttempts += result.attempts;
                stats->groupSimplify.attributeQemSeconds += result.profile.attributeQemSeconds;
                stats->groupSimplify.cornerSeconds += result.profile.cornerSeconds;
                stats->groupSimplify.cornerSetupSeconds += result.profile.cornerSetupSeconds;
                stats->groupSimplify.cornerEvaluateSeconds += result.profile.cornerEvaluateSeconds;
                stats->groupSimplify.cornerEvaluateTopologySeconds +=
                        result.profile.cornerEvaluateTopologySeconds;
                stats->groupSimplify.cornerTopologyNeighborSeconds +=
                        result.profile.cornerTopologyNeighborSeconds;
                stats->groupSimplify.cornerTopologyTriangleSeconds +=
                        result.profile.cornerTopologyTriangleSeconds;
                stats->groupSimplify.cornerTopologyLocalTriangleSeconds +=
                        result.profile.cornerTopologyLocalTriangleSeconds;
                stats->groupSimplify.cornerTopologyLocalEdgeSeconds +=
                        result.profile.cornerTopologyLocalEdgeSeconds;
                stats->groupSimplify.cornerEvaluateTargetSeconds +=
                        result.profile.cornerEvaluateTargetSeconds;
                stats->groupSimplify.cornerApplySeconds += result.profile.cornerApplySeconds;
                stats->groupSimplify.cornerEvaluations += result.profile.cornerEvaluations;
                stats->groupSimplify.cornerPlacementTests += result.profile.cornerPlacementTests;
                stats->groupSimplify.cornerApplied += result.profile.cornerApplied;
                stats->groupSimplify.meshoptSeconds += result.profile.meshoptSeconds;
                stats->groupSimplify.candidateGateSeconds += result.profile.candidateGateSeconds;
                stats->groupSimplify.candidateCleanupSeconds +=
                        result.profile.candidateCleanupSeconds;
                stats->groupSimplify.candidateSliverSeconds +=
                        result.profile.candidateSliverSeconds;
                stats->groupSimplify.candidateErrorSeconds += result.profile.candidateErrorSeconds;
                stats->groupSimplify.candidateTopologySeconds +=
                        result.profile.candidateTopologySeconds;
                stats->groupSimplify.weldedTopologySeconds += result.profile.weldedTopologySeconds;
                stats->groupSimplify.boundaryCheckSeconds += result.profile.boundaryCheckSeconds;
                stats->groupSimplify.lockedMaskSeconds += result.profile.lockedMaskSeconds;
                stats->groupSimplify.extendedMeshSeconds += result.profile.extendedMeshSeconds;
                stats->groupSimplify.calls += result.profile.calls;
                stats->groupSimplify.attempts += result.profile.attempts;
                stats->groupSimplify.attributeCandidates += result.profile.attributeCandidates;
                stats->groupSimplify.cornerCandidates += result.profile.cornerCandidates;
                stats->groupSimplify.meshoptCandidates += result.profile.meshoptCandidates;
                stats->groupSimplify.accepted += result.profile.accepted;
                stats->groupSimplify.extendedMeshCopies += result.profile.extendedMeshCopies;
                stats->groupSimplify.rejectedNotSimplified += result.profile.rejectedNotSimplified;
                stats->groupSimplify.rejectedTopology += result.profile.rejectedTopology;
                stats->groupSimplify.rejectedGeometry += result.profile.rejectedGeometry;
                stats->groupSimplify.rejectedAttributes += result.profile.rejectedAttributes;
                stats->groupSimplify.rejectedBoundary += result.profile.rejectedBoundary;
                stats->groupSimplify.rejectedLocked += result.profile.rejectedLocked;
            }
            if (!result.promoted) {
                next.insert(next.end(), members.begin(), members.end());
                continue;
            }
            if (stats != nullptr) {
                stats->groupSimplifyAccepted += 1;
            }
            appendGeneratedVerticesToGraph(&graph, &graphMesh, result.generatedVertices,
                    levelVertexCount, &generatedLookup, &graphPositions, &graphPositionIds,
                    &result.parent.indices);
            uint32_t const id = uint32_t(graph.nodes.size());
            for (uint32_t member: members) {
                graph.nodes[member].parent = id;
            }
            graph.nodes.push_back(std::move(result.parent));
            next.push_back(id);
            createdParent = true;
        }
        if (stats != nullptr) {
            stats->groupBuildSeconds += secondsSince(groupBuildStart);
        }
        if (!createdParent) {
            break;
        }
        graph.levelCount = std::max(graph.levelCount, level + 1);
        current = std::move(next);
    }

    // Keep one canonical id per exact position. Source seam duplicates and generated vertices
    // that landed on the same point then compare equal during cut assembly, which is what lets
    // selection drop faces produced twice from different attribute vertices.
    graph.positionIds.resize(graph.vertexCount, 0);
    for (uint32_t i = 0; i < sourceVertexCount && i < graph.vertexCount; ++i) {
        auto const position = graphPositions.find(positionKey(mesh.positions[i]));
        graph.positionIds[i] = position != graphPositions.end() ? position->second : i;
    }
    for (size_t g = 0; g < graph.generatedVertices.size(); ++g) {
        uint32_t const vertex = sourceVertexCount + uint32_t(g);
        if (vertex >= graph.vertexCount) {
            break;
        }
        auto const position = graphPositions.find(positionKey(graph.generatedVertices[g].position));
        graph.positionIds[vertex] = position != graphPositions.end() ? position->second : vertex;
    }

    graph.roots = current.empty() ? graph.leaves : current;
    if (stats != nullptr) {
        stats->generatedVertices = graph.generatedVertices.size();
        stats->totalSeconds = secondsSince(buildStart);
    }
    return graph;
}

LodGraphSelection selectLodGraph(LodGraph const& graph, ViewCamera const& camera,
        float thresholdPx) {
    return selectImpl(graph, camera, thresholdPx);
}

LodGraphSelection assembleLodSelection(LodGraph const& graph, ViewCamera const& camera,
        std::vector<uint32_t> nodes, uint64_t culledTriangles) {
    CameraBasis const basis = makeBasis(camera);
    NodeMetrics const metrics = makeNodeMetrics(graph, camera, basis);
    CutAtError cut;
    cut.culledTriangles = culledTriangles;
    cut.nodes.reserve(nodes.size());
    for (uint32_t nodeId: nodes) {
        if (nodeId >= graph.nodes.size()) {
            continue;
        }
        LodGraphNode const& node = graph.nodes[nodeId];
        if (metrics.culled[nodeId] != 0) {
            continue;
        }
        cut.nodes.push_back(nodeId);
        cut.triangles += node.triangleCount();
    }
    return selectionFromCut(graph, metrics, cut);
}

LodGraphCutGeometry compactLodSelection(LodGraph const& graph, LodGraphSelection const& selection,
        LodGraphCompactOptions const& options) {
    LodGraphCutGeometry geometry;
    uint32_t const graphSourceCount = graph.sourceVertexCount();
    geometry.indices = selection.indices;
    geometry.triangles = uint32_t(selection.indices.size() / 3);

    uint32_t sourceCount = graphSourceCount;
    if (options.compactSourceVertices) {
        // Source ids are dense, so a flat table beats a hash map. The table is thread-local to
        // keep a committed cut allocation-light when a renderer rebuilds it repeatedly.
        thread_local std::vector<int32_t> sourceRemap;
        sourceRemap.assign(graphSourceCount, -1);
        geometry.sourceVertexIds.reserve(
                std::min(size_t(graphSourceCount), geometry.indices.size()));
        for (uint32_t& vertex: geometry.indices) {
            if (vertex >= graphSourceCount) {
                continue;
            }
            int32_t& compact = sourceRemap[vertex];
            if (compact < 0) {
                compact = int32_t(geometry.sourceVertexIds.size());
                geometry.sourceVertexIds.push_back(vertex);
            }
            vertex = uint32_t(compact);
        }
        sourceCount = uint32_t(geometry.sourceVertexIds.size());
    }

    size_t const generatedCount = graph.generatedVertices.size();
    if (generatedCount != 0 && !geometry.indices.empty()) {
        thread_local std::vector<int32_t> remap;
        remap.assign(generatedCount, -1);
        geometry.generatedVertices.reserve(std::min(generatedCount, size_t(geometry.triangles)));
        for (uint32_t& vertex: geometry.indices) {
            if (vertex < graphSourceCount) {
                continue;
            }
            size_t const local = size_t(vertex - graphSourceCount);
            if (local >= generatedCount) {
                // Selection assembly only emits ids that exist in the graph. Keep the input intact
                // instead of silently folding a malformed id onto a valid vertex.
                continue;
            }
            int32_t& compact = remap[local];
            if (compact < 0) {
                compact = int32_t(geometry.generatedVertices.size());
                geometry.generatedVertices.push_back(graph.generatedVertices[local]);
                geometry.generatedSourceIds.push_back(uint32_t(local));
            }
            vertex = sourceCount + uint32_t(compact);
        }
    }
    geometry.sourceVertexCount = sourceCount;
    geometry.vertexCount = sourceCount + uint32_t(geometry.generatedVertices.size());
    return geometry;
}
LodGraphCut selectLodGraphCut(LodGraph const& graph, ViewCamera const& camera, float thresholdPx) {
    LodGraphCut cut;
    cut.baseTriangles = graph.baseTriangles;
    cut.nodesPerLevel.assign(graph.levelCount, 0);
    cut.trianglesPerLevel.assign(graph.levelCount, 0);

    CameraBasis const basis = makeBasis(camera);
    ScreenErrorProjection const projection = makeScreenErrorProjection(camera);
    std::function<void(uint32_t)> visit = [&](uint32_t nodeId) {
        LodGraphNode const& node = graph.nodes[nodeId];
        if (basis.valid && sphereOutsideFrustum(node.bounds, camera, basis)) {
            cut.culledTriangles += node.baseTriangles;
            return;
        }
        float const screenError = basis.valid ? screenErrorForNode(node, projection) : 0.0f;
        if (!node.children.empty() && screenError > thresholdPx) {
            for (uint32_t child: node.children) {
                visit(child);
            }
            return;
        }
        cut.nodes.push_back(nodeId);
        cut.screenErrorPerNode.push_back(screenError);
        uint64_t const triangles = node.triangleCount();
        cut.nodesPerLevel[node.level] += 1;
        cut.trianglesPerLevel[node.level] += triangles;
        cut.selectedTriangles += triangles;
    };
    for (uint32_t root: graph.roots) {
        visit(root);
    }
    return cut;
}

LodGraphSelection selectLodGraphAtRatio(LodGraph const& graph, ViewCamera const& camera,
        float targetTriangleRatio, float maxThresholdPx) {
    CameraBasis const basis = makeBasis(camera);
    NodeMetrics const metrics = makeNodeMetrics(graph, camera, basis);
    CutAtError const rootCut = cutAtError(graph, metrics, std::numeric_limits<float>::infinity());
    uint64_t const visibleBase = graph.baseTriangles > rootCut.culledTriangles
                                         ? graph.baseTriangles - rootCut.culledTriangles
                                         : graph.baseTriangles;
    if (visibleBase == 0) {
        return selectionFromCut(graph, metrics, rootCut);
    }

    float const clampedRatio = std::clamp(targetTriangleRatio, 0.0f, 1.0f);
    uint64_t const budget = uint64_t(std::ceil(double(visibleBase) * double(clampedRatio)));
    if (rootCut.triangles >= budget) {
        // The roots are the coarsest legal cut, so no selection can get under this budget.
        return selectionFromCut(graph, metrics, rootCut);
    }

    float const ceiling = std::isfinite(maxThresholdPx) ? maxThresholdPx : 0.0f;
    CutAtError const atCeiling = cutAtError(graph, metrics, ceiling);
    if (atCeiling.triangles <= budget) {
        // The quality ceiling is reachable below the budget: keep the extra saving.
        return selectionFromCut(graph, metrics, atCeiling);
    }

    // Binary search the smallest error threshold whose minimum-triangle cut fits the budget.
    float low = 0.0f;
    float high = cutWorstScreenError(metrics, rootCut.nodes);
    for (int iteration = 0; iteration < 32; ++iteration) {
        float const middle = (low + high) * 0.5f;
        CutAtError const candidate = cutAtError(graph, metrics, middle);
        if (candidate.triangles <= budget) {
            high = middle;
        } else {
            low = middle;
        }
    }

    CutAtError cut = cutAtError(graph, metrics, high);
    refineCutWithinBudget(graph, metrics, budget,
            std::isfinite(maxThresholdPx) ? maxThresholdPx : 0.0f, &cut);
    return selectionFromCut(graph, metrics, cut);
}

LodTierProfile lodTierProfile(LodTier tier) noexcept {
    switch (tier) {
        case LodTier::MaximumQuality:
            return { "maximum", 0.85f, 0.75f };
        case LodTier::Balanced:
            return { "balanced", 0.50f, 1.50f };
        case LodTier::Aggressive:
            return { "aggressive", 0.25f, 3.00f };
    }
    return { "balanced", 0.50f, 1.50f };
}

LodGraphSelection selectLodGraphTier(LodGraph const& graph, ViewCamera const& camera,
        LodTier tier) {
    LodTierProfile const profile = lodTierProfile(tier);
    return selectLodGraphAtRatio(graph, camera, profile.targetTriangleRatio,
            profile.maxScreenErrorPx);
}

} // namespace manymesh
} // namespace filament
