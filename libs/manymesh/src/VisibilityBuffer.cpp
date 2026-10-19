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

#include <manymesh/VisibilityBuffer.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

struct Projected {
    float x = 0.0f;
    float y = 0.0f;
    float inverseDepth = 0.0f;
    bool valid = false;
};

struct Basis {
    math::float3 forward;
    math::float3 right;
    math::float3 up;
    float tanHalfFovY = 1.0f;
    float aspect = 1.0f;
    bool valid = false;
};

Basis makeBasis(ViewCamera const& camera) {
    Basis basis;
    math::float3 const forward = camera.target - camera.eye;
    float const forwardLength = length(forward);
    if (!(forwardLength > 1e-6f)) {
        return basis;
    }
    basis.forward = forward / forwardLength;
    math::float3 const right = cross(basis.forward, camera.up);
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

Projected project(math::float3 const& point, ViewCamera const& camera, Basis const& basis) {
    Projected result;
    math::float3 const delta = point - camera.eye;
    float const depth = dot(delta, basis.forward);
    if (depth <= camera.near || depth > camera.far) {
        return result;
    }
    float const ndcX = dot(delta, basis.right) / depth / (basis.tanHalfFovY * basis.aspect);
    float const ndcY = dot(delta, basis.up) / depth / basis.tanHalfFovY;
    result.x = (ndcX * 0.5f + 0.5f) * float(camera.screenWidth);
    result.y = (1.0f - (ndcY * 0.5f + 0.5f)) * float(camera.screenHeight);
    result.inverseDepth = 1.0f / depth;
    result.valid = true;
    return result;
}

float edge(float ax, float ay, float bx, float by, float px, float py) {
    return (px - ax) * (by - ay) - (py - ay) * (bx - ax);
}

} // anonymous namespace

VisibilityBuffer rasterizeVisibility(Mesh const& mesh, GpuLodBuffer const& buffer,
        LodGraphSelection const& selection, ViewCamera const& camera) {
    VisibilityBuffer result;
    result.width = camera.screenWidth;
    result.height = camera.screenHeight;
    size_t const pixelCount = size_t(result.width) * result.height;
    result.clusterIds.assign(pixelCount, UINT32_MAX);
    result.triangleIds.assign(pixelCount, UINT32_MAX);
    result.materialIds.assign(pixelCount, UINT32_MAX);
    result.submeshIds.assign(pixelCount, UINT32_MAX);
    result.inverseDepth.assign(pixelCount, 0.0f);

    Basis const basis = makeBasis(camera);
    if (!basis.valid || mesh.positions.empty()) {
        return result;
    }

    for (uint32_t nodeId : selection.nodes) {
        if (nodeId >= buffer.nodes.size()) {
            continue;
        }
        GpuLodNode const& node = buffer.nodes[nodeId];
        size_t const end = size_t(node.indexOffset) + node.indexCount;
        if (end > buffer.indices.size()) {
            continue;
        }
        for (size_t i = node.indexOffset; i + 2 < end; i += 3) {
            uint32_t const ia = buffer.indices[i + 0];
            uint32_t const ib = buffer.indices[i + 1];
            uint32_t const ic = buffer.indices[i + 2];
            if (ia >= mesh.positions.size() || ib >= mesh.positions.size()
                    || ic >= mesh.positions.size()) {
                continue;
            }
            Projected const a = project(mesh.positions[ia], camera, basis);
            Projected const b = project(mesh.positions[ib], camera, basis);
            Projected const c = project(mesh.positions[ic], camera, basis);
            if (!a.valid || !b.valid || !c.valid) {
                continue;
            }

            float const area = edge(a.x, a.y, b.x, b.y, c.x, c.y);
            if (std::abs(area) < 1e-6f) {
                continue;
            }
            int minX = std::max(0, int(std::floor(std::min(a.x, std::min(b.x, c.x)))));
            int maxX = std::min(int(result.width) - 1,
                    int(std::ceil(std::max(a.x, std::max(b.x, c.x)))));
            int minY = std::max(0, int(std::floor(std::min(a.y, std::min(b.y, c.y)))));
            int maxY = std::min(int(result.height) - 1,
                    int(std::ceil(std::max(a.y, std::max(b.y, c.y)))));

            for (int y = minY; y <= maxY; ++y) {
                float const py = float(y) + 0.5f;
                for (int x = minX; x <= maxX; ++x) {
                    float const px = float(x) + 0.5f;
                    float const w0 = edge(b.x, b.y, c.x, c.y, px, py) / area;
                    float const w1 = edge(c.x, c.y, a.x, a.y, px, py) / area;
                    float const w2 = 1.0f - w0 - w1;
                    if (w0 < -1e-4f || w1 < -1e-4f || w2 < -1e-4f) {
                        continue;
                    }
                    float const inverseDepth = w0 * a.inverseDepth + w1 * b.inverseDepth
                            + w2 * c.inverseDepth;
                    size_t const pixel = size_t(y) * result.width + size_t(x);
                    if (inverseDepth > result.inverseDepth[pixel]) {
                        if (result.clusterIds[pixel] == UINT32_MAX) {
                            result.coveredPixels += 1;
                        }
                        result.clusterIds[pixel] = nodeId;
                        result.triangleIds[pixel] = uint32_t(i / 3);
                        result.materialIds[pixel] = node.materialId;
                        result.submeshIds[pixel] = node.submeshId;
                        result.inverseDepth[pixel] = inverseDepth;
                    }
                }
            }
        }
    }
    return result;
}

void writeVisibilityBufferPgm(VisibilityBuffer const& buffer, char const* path) {
    if (buffer.width == 0 || buffer.height == 0 || path == nullptr) {
        return;
    }
    std::FILE* file = std::fopen(path, "wb");
    if (file == nullptr) {
        return;
    }
    std::fprintf(file, "P5\n%u %u\n255\n", buffer.width, buffer.height);
    std::vector<uint8_t> pixels(buffer.clusterIds.size());
    for (size_t i = 0; i < buffer.clusterIds.size(); ++i) {
        uint32_t const id = buffer.clusterIds[i];
        pixels[i] = id == UINT32_MAX ? 0 : uint8_t((id * 37u) % 254u + 1u);
    }
    std::fwrite(pixels.data(), 1, pixels.size(), file);
    std::fclose(file);
}

} // namespace manymesh
} // namespace filament
