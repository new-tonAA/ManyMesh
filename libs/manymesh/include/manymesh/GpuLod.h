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

#ifndef TNT_MANYMESH_GPULOD_H
#define TNT_MANYMESH_GPULOD_H

#include <manymesh/LodGraph.h>

#include <vector>

#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * std430-friendly node record for a GPU cluster-selection pass.
 *
 * The fields are deliberately plain scalars: upload `nodes` and `children` as storage buffers
 * and run a compute shader that walks the DAG from `roots`, emitting either a node or its
 * children. The CPU selection in LodGraph.h is the reference for the same decision.
 */
struct GpuLodNode {
    float boundsCenter[3] = {};
    float boundsRadius = 0.0f;
    float coneApex[3] = {};
    float coneAxis[3] = {};
    float coneCutoff = 0.0f;
    float accumulatedError = 0.0f;
    uint32_t indexOffset = 0;
    uint32_t indexCount = 0;
    uint32_t childOffset = 0;
    uint32_t childCount = 0;
    uint32_t level = 0;
    uint32_t materialId = UINT32_MAX;
    uint32_t submeshId = UINT32_MAX;
    uint32_t flags = 0;
};

enum : uint32_t {
    GPU_LOD_NODE_ROOT = 1u << 0,
    GPU_LOD_NODE_LEAF = 1u << 1,
    GPU_LOD_NODE_SIMPLIFIED = 1u << 2,
};

struct GpuLodBuffer {
    std::vector<GpuLodNode> nodes;
    std::vector<uint32_t> children;
    std::vector<uint32_t> indices;
};

GpuLodBuffer flattenLodGraph(LodGraph const& graph);

/**
 * One entry of a draw-indirect buffer. Kept separate from backend-specific types so it can be
 * uploaded directly or converted to a backend's equivalent. Filament's public
 * RenderableManager does not expose an indirect-draw submission API, so this is a portable
 * data contract rather than evidence that a Filament sample can submit it without backend work.
 */
struct GpuDrawIndexedIndirectCommand {
    uint32_t indexCount = 0;
    uint32_t instanceCount = 1;
    uint32_t firstIndex = 0;
    int32_t baseVertex = 0;
    uint32_t baseInstance = 0;
};

std::vector<GpuDrawIndexedIndirectCommand> buildIndirectDraws(GpuLodBuffer const& buffer,
        LodGraphSelection const& selection);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_GPULOD_H
