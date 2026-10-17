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

#include <manymesh/GpuLod.h>

#include <algorithm>

namespace filament {
namespace manymesh {

GpuLodBuffer flattenLodGraph(LodGraph const& graph) {
    GpuLodBuffer buffer;
    buffer.nodes.reserve(graph.nodes.size());
    size_t indexCount = 0;
    size_t childCount = 0;
    for (LodGraphNode const& node : graph.nodes) {
        indexCount += node.indices.size();
        childCount += node.children.size();
    }
    buffer.indices.reserve(indexCount);
    buffer.children.reserve(childCount);

    for (uint32_t id = 0; id < graph.nodes.size(); ++id) {
        LodGraphNode const& source = graph.nodes[id];
        GpuLodNode node;
        node.boundsCenter[0] = source.bounds.center.x;
        node.boundsCenter[1] = source.bounds.center.y;
        node.boundsCenter[2] = source.bounds.center.z;
        node.boundsRadius = source.bounds.radius;
        node.coneApex[0] = source.cone.apex.x;
        node.coneApex[1] = source.cone.apex.y;
        node.coneApex[2] = source.cone.apex.z;
        node.coneAxis[0] = source.cone.axis.x;
        node.coneAxis[1] = source.cone.axis.y;
        node.coneAxis[2] = source.cone.axis.z;
        node.coneCutoff = source.cone.cutoff;
        node.accumulatedError = source.accumulatedError;
        node.indexOffset = uint32_t(buffer.indices.size());
        node.indexCount = uint32_t(source.indices.size());
        node.childOffset = uint32_t(buffer.children.size());
        node.childCount = uint32_t(source.children.size());
        node.level = source.level;
        node.materialId = source.materialId;
        node.submeshId = source.submeshId;
        node.flags = (source.parent == UINT32_MAX ? GPU_LOD_NODE_ROOT : 0u)
                | (source.children.empty() ? GPU_LOD_NODE_LEAF : 0u)
                | (source.simplified ? GPU_LOD_NODE_SIMPLIFIED : 0u);
        buffer.indices.insert(buffer.indices.end(), source.indices.begin(), source.indices.end());
        buffer.children.insert(buffer.children.end(),
                source.children.begin(), source.children.end());
        buffer.nodes.push_back(node);
    }
    return buffer;
}

std::vector<GpuDrawIndexedIndirectCommand> buildIndirectDraws(GpuLodBuffer const& buffer,
        LodGraphSelection const& selection) {
    std::vector<GpuDrawIndexedIndirectCommand> commands;
    commands.reserve(selection.nodes.size());
    for (uint32_t nodeId : selection.nodes) {
        if (nodeId >= buffer.nodes.size()) {
            continue;
        }
        GpuLodNode const& node = buffer.nodes[nodeId];
        if (node.indexCount == 0) {
            continue;
        }
        GpuDrawIndexedIndirectCommand command;
        command.indexCount = node.indexCount;
        command.instanceCount = 1;
        command.firstIndex = node.indexOffset;
        command.baseVertex = 0;
        command.baseInstance = nodeId;
        commands.push_back(command);
    }
    return commands;
}

} // namespace manymesh
} // namespace filament
