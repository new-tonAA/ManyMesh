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

#include <manymesh/Quality.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

using Edge = std::pair<uint32_t, uint32_t>;
using TriangleKey = std::array<uint32_t, 3>;

uint64_t edgeKey(Edge edge) {
    return (uint64_t(edge.first) << 32) | uint64_t(edge.second);
}

Edge edgeOf(uint32_t a, uint32_t b) {
    return { std::min(a, b), std::max(a, b) };
}

TriangleKey triangleKey(uint32_t a, uint32_t b, uint32_t c) {
    TriangleKey key = { a, b, c };
    std::sort(key.begin(), key.end());
    return key;
}

float triangleQuality(Mesh const& mesh, uint32_t a, uint32_t b, uint32_t c) {
    math::float3 const ab = mesh.positions[b] - mesh.positions[a];
    math::float3 const ac = mesh.positions[c] - mesh.positions[a];
    float const area2 = length(cross(ab, ac));
    float const denominator = dot(ab, ab) + dot(ac, ac)
            + dot(mesh.positions[c] - mesh.positions[b], mesh.positions[c] - mesh.positions[b]);
    if (!(denominator > 0.0f) || !(area2 > 0.0f)) {
        return 0.0f;
    }
    return std::clamp(2.0f * std::sqrt(3.0f) * area2 / denominator, 0.0f, 1.0f);
}

// UV charts usually wrap at 1.0. A collapse from u=0.99 to u=0.01 is a 0.02 step on the
// texture, not a 0.98 step, and comparing the raw values would reject perfectly good seam
// collapses (the torus is a compact example: every chart wraps).
float wrappedUvDistance(math::float2 a, math::float2 b) {
    math::float2 delta = a - b;
    delta.x -= std::round(delta.x);
    delta.y -= std::round(delta.y);
    return length(delta);
}

std::vector<uint32_t> referencedVertices(std::vector<uint32_t> const& indices) {
    std::vector<uint32_t> result = indices;
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    return result;
}

std::vector<uint32_t> sampledVertices(std::vector<uint32_t> const& vertices, uint32_t maxSamples) {
    if (maxSamples == 0 || vertices.size() <= maxSamples) {
        return vertices;
    }
    std::vector<uint32_t> result;
    result.reserve(maxSamples);
    double const step = double(vertices.size() - 1) / double(maxSamples - 1);
    for (uint32_t i = 0; i < maxSamples; ++i) {
        result.push_back(vertices[size_t(std::llround(double(i) * step))]);
    }
    return result;
}

struct CellKey {
    int32_t x = 0;
    int32_t y = 0;
    int32_t z = 0;

    bool operator==(CellKey const& other) const noexcept {
        return x == other.x && y == other.y && z == other.z;
    }
};

struct CellKeyHash {
    size_t operator()(CellKey const& key) const noexcept {
        uint64_t const h = (uint64_t(uint32_t(key.x)) << 42)
                ^ (uint64_t(uint32_t(key.y)) << 21) ^ uint64_t(uint32_t(key.z));
        return std::hash<uint64_t>()(h);
    }
};

//! A uniform grid over the retained vertices, used only for the large-mesh gate path.
class VertexGrid {
public:
    VertexGrid(Mesh const& mesh, std::vector<uint32_t> const& vertices) {
        if (vertices.empty()) {
            return;
        }
        mMin = mesh.positions[vertices[0]];
        mMax = mMin;
        for (uint32_t vertex : vertices) {
            mMin = min(mMin, mesh.positions[vertex]);
            mMax = max(mMax, mesh.positions[vertex]);
        }
        math::float3 const extent = mMax - mMin;
        float const largest = std::max(extent.x, std::max(extent.y, extent.z));
        mCellSize = std::max(largest / 64.0f, 1e-6f);
        mInverseCellSize = 1.0f / mCellSize;
        for (uint32_t vertex : vertices) {
            mCells[cellOf(mesh.positions[vertex])].push_back(vertex);
        }
    }

    bool nearest(Mesh const& mesh, math::float3 point, uint32_t* outVertex,
            float* outDistance2) const {
        if (mCells.empty()) {
            return false;
        }
        CellKey const origin = cellOf(point);
        float bestDistance2 = std::numeric_limits<float>::max();
        uint32_t bestVertex = UINT32_MAX;
        int const maxRadius = 64;
        for (int radius = 0; radius <= maxRadius; ++radius) {
            for (int x = origin.x - radius; x <= origin.x + radius; ++x) {
                for (int y = origin.y - radius; y <= origin.y + radius; ++y) {
                    for (int z = origin.z - radius; z <= origin.z + radius; ++z) {
                        bool const onShell = std::abs(x - origin.x) == radius
                                || std::abs(y - origin.y) == radius
                                || std::abs(z - origin.z) == radius;
                        if (!onShell) {
                            continue;
                        }
                        auto const it = mCells.find({ x, y, z });
                        if (it == mCells.end()) {
                            continue;
                        }
                        for (uint32_t vertex : it->second) {
                            math::float3 const delta = mesh.positions[vertex] - point;
                            float const distance2 = dot(delta, delta);
                            if (distance2 < bestDistance2) {
                                bestDistance2 = distance2;
                                bestVertex = vertex;
                            }
                        }
                    }
                }
            }
            float const shellDistance = float(radius) * mCellSize;
            if (bestVertex != UINT32_MAX && shellDistance * shellDistance > bestDistance2) {
                break;
            }
        }
        if (bestVertex == UINT32_MAX) {
            return false;
        }
        *outVertex = bestVertex;
        *outDistance2 = bestDistance2;
        return true;
    }

private:
    CellKey cellOf(math::float3 point) const noexcept {
        math::float3 const local = (point - mMin) * mInverseCellSize;
        return { int32_t(std::floor(local.x)), int32_t(std::floor(local.y)),
            int32_t(std::floor(local.z)) };
    }

    math::float3 mMin{};
    math::float3 mMax{};
    float mCellSize = 1.0f;
    float mInverseCellSize = 1.0f;
    std::unordered_map<CellKey, std::vector<uint32_t>, CellKeyHash> mCells;
};

float normalAngle(math::float3 const& a, math::float3 const& b) {
    float const la = length(a);
    float const lb = length(b);
    if (!(la > 0.0f) || !(lb > 0.0f)) {
        return 0.0f;
    }
    return std::acos(std::clamp(dot(a, b) / (la * lb), -1.0f, 1.0f));
}

//! Barycentric coordinates of the closest point on a triangle (Ericson, Real-Time Collision Detection).
void closestPointBarycentric(math::float3 const& a, math::float3 const& b,
        math::float3 const& c, math::float3 const& point,
        float* wa, float* wb, float* wc) {
    math::float3 const ab = b - a;
    math::float3 const ac = c - a;
    math::float3 const ap = point - a;
    float const d1 = dot(ab, ap);
    float const d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        *wa = 1.0f; *wb = 0.0f; *wc = 0.0f;
        return;
    }

    math::float3 const bp = point - b;
    float const d3 = dot(ab, bp);
    float const d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        *wa = 0.0f; *wb = 1.0f; *wc = 0.0f;
        return;
    }

    float const vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        float const v = d1 / (d1 - d3);
        *wa = 1.0f - v; *wb = v; *wc = 0.0f;
        return;
    }

    math::float3 const cp = point - c;
    float const d5 = dot(ab, cp);
    float const d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        *wa = 0.0f; *wb = 0.0f; *wc = 1.0f;
        return;
    }

    float const vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        float const w = d2 / (d2 - d6);
        *wa = 1.0f - w; *wb = 0.0f; *wc = w;
        return;
    }

    float const va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        float const w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        *wa = 0.0f; *wb = 1.0f - w; *wc = w;
        return;
    }

    float const sum = va + vb + vc;
    if (!(std::abs(sum) > 1e-20f)) {
        *wa = 1.0f; *wb = 0.0f; *wc = 0.0f;
        return;
    }
    float const inv = 1.0f / sum;
    *wa = va * inv;
    *wb = vb * inv;
    *wc = vc * inv;
}

} // anonymous namespace

TopologyStats measureTopology(Mesh const& mesh, std::vector<uint32_t> const& indices) {
    TopologyStats result;
    result.triangles = indices.size() / 3;

    std::vector<TriangleKey> triangles;
    triangles.reserve(result.triangles);
    std::unordered_map<uint64_t, uint32_t> edgeUse;
    edgeUse.reserve(result.triangles * 3);

    double qualitySum = 0.0;
    result.minTriangleQuality = 1.0f;

    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        uint32_t const a = indices[i + 0];
        uint32_t const b = indices[i + 1];
        uint32_t const c = indices[i + 2];
        triangles.push_back(triangleKey(a, b, c));

        float const quality = triangleQuality(mesh, a, b, c);
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
            math::float3 const vertexNormal = mesh.normals[a] + mesh.normals[b]
                    + mesh.normals[c];
            if (dot(faceNormal, vertexNormal) < 0.0f) {
                result.flippedTriangles += 1;
            }
        }

        Edge const edges[3] = { edgeOf(a, b), edgeOf(b, c), edgeOf(c, a) };
        for (Edge const& edge : edges) {
            edgeUse[edgeKey(edge)] += 1;
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
    for (auto const& [key, count] : edgeUse) {
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

AttributeStats measureAttributeError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices,
        uint32_t maxSamples, size_t approximateTriangles) {
    AttributeStats result;
    if (!mesh.hasNormals() && !mesh.hasUVs()) {
        return result;
    }

    std::vector<uint32_t> const reference = sampledVertices(
            referencedVertices(referenceIndices), maxSamples);
    if (reference.empty() || simplifiedIndices.size() < 3) {
        return result;
    }

    bool const approximate = approximateTriangles != 0
            && simplifiedIndices.size() / 3 > approximateTriangles;
    result.approximated = approximate;

    VertexGrid grid(mesh, referencedVertices(simplifiedIndices));

    double normalSum = 0.0;
    double uvSum = 0.0;
    for (uint32_t vertex : reference) {
        uint32_t a = 0;
        uint32_t b = 0;
        uint32_t c = 0;
        float bestWeights[3] = { 1.0f, 0.0f, 0.0f };

        if (approximate) {
            uint32_t nearestVertex = UINT32_MAX;
            float distance2 = 0.0f;
            if (!grid.nearest(mesh, mesh.positions[vertex], &nearestVertex, &distance2)) {
                continue;
            }
            a = b = c = nearestVertex;
        } else {
            float bestDistance2 = std::numeric_limits<float>::max();
            uint32_t bestTriangle = 0;

            for (size_t i = 0; i + 2 < simplifiedIndices.size(); i += 3) {
                uint32_t const ia = simplifiedIndices[i + 0];
                uint32_t const ib = simplifiedIndices[i + 1];
                uint32_t const ic = simplifiedIndices[i + 2];
                float weights[3];
                closestPointBarycentric(mesh.positions[ia], mesh.positions[ib],
                        mesh.positions[ic], mesh.positions[vertex],
                        &weights[0], &weights[1], &weights[2]);
                math::float3 const closest = mesh.positions[ia] * weights[0]
                        + mesh.positions[ib] * weights[1] + mesh.positions[ic] * weights[2];
                float const distance2 = dot(closest - mesh.positions[vertex],
                        closest - mesh.positions[vertex]);
                if (distance2 < bestDistance2) {
                    bestDistance2 = distance2;
                    bestTriangle = i;
                    bestWeights[0] = weights[0];
                    bestWeights[1] = weights[1];
                    bestWeights[2] = weights[2];
                }
            }

            a = simplifiedIndices[bestTriangle + 0];
            b = simplifiedIndices[bestTriangle + 1];
            c = simplifiedIndices[bestTriangle + 2];
        }

        if (mesh.hasNormals()) {
            math::float3 const normal = mesh.normals[a] * bestWeights[0]
                    + mesh.normals[b] * bestWeights[1] + mesh.normals[c] * bestWeights[2];
            float const angle = normalAngle(mesh.normals[vertex], normal);
            normalSum += double(angle);
            result.maxNormalErrorRadians = std::max(result.maxNormalErrorRadians, angle);
        }
        if (mesh.hasUVs()) {
            math::float2 const uv = mesh.uvs[a] * bestWeights[0]
                    + mesh.uvs[b] * bestWeights[1] + mesh.uvs[c] * bestWeights[2];
            float const error = wrappedUvDistance(mesh.uvs[vertex], uv);
            uvSum += double(error);
            result.maxUvError = std::max(result.maxUvError, error);
        }
        result.samples += 1;
    }

    if (result.samples > 0) {
        result.meanNormalErrorRadians = float(normalSum / double(result.samples));
        result.meanUvError = float(uvSum / double(result.samples));
    }
    return result;
}

AttributeStats measureAttributeError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices) {
    return measureAttributeError(mesh, referenceIndices, simplifiedIndices, 0, 0);
}

PositionStats measurePositionError(Mesh const& mesh,
        std::vector<uint32_t> const& referenceIndices,
        std::vector<uint32_t> const& simplifiedIndices,
        uint32_t maxSamples, size_t approximateTriangles) {
    PositionStats result;
    std::vector<uint32_t> const reference = sampledVertices(
            referencedVertices(referenceIndices), maxSamples);
    if (reference.empty() || simplifiedIndices.size() < 3) {
        return result;
    }

    bool const approximate = approximateTriangles != 0
            && simplifiedIndices.size() / 3 > approximateTriangles;
    result.approximated = approximate;
    VertexGrid grid(mesh, referencedVertices(simplifiedIndices));

    double sum = 0.0;
    for (uint32_t vertex : reference) {
        float distance2 = 0.0f;
        if (approximate) {
            uint32_t nearestVertex = UINT32_MAX;
            if (!grid.nearest(mesh, mesh.positions[vertex], &nearestVertex, &distance2)) {
                continue;
            }
        } else {
            float bestDistance2 = std::numeric_limits<float>::max();
            for (size_t i = 0; i + 2 < simplifiedIndices.size(); i += 3) {
                uint32_t const a = simplifiedIndices[i + 0];
                uint32_t const b = simplifiedIndices[i + 1];
                uint32_t const c = simplifiedIndices[i + 2];
                float weights[3];
                closestPointBarycentric(mesh.positions[a], mesh.positions[b],
                        mesh.positions[c], mesh.positions[vertex],
                        &weights[0], &weights[1], &weights[2]);
                math::float3 const closest = mesh.positions[a] * weights[0]
                        + mesh.positions[b] * weights[1] + mesh.positions[c] * weights[2];
                math::float3 const delta = closest - mesh.positions[vertex];
                bestDistance2 = std::min(bestDistance2, dot(delta, delta));
            }
            distance2 = bestDistance2;
        }
        float const distance = std::sqrt(std::max(distance2, 0.0f));
        sum += double(distance);
        result.maxError = std::max(result.maxError, distance);
        result.samples += 1;
    }
    if (result.samples > 0) {
        result.meanError = float(sum / double(result.samples));
    }
    return result;
}

} // namespace manymesh
} // namespace filament
