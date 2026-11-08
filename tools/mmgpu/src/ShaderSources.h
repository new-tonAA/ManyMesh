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

#ifndef TNT_MMGPU_SHADERSOURCES_H
#define TNT_MMGPU_SHADERSOURCES_H

namespace mmgpu {

//! GPU cut selection. One invocation per DAG node walks its parent chain; no global queue and
//! no synchronization between nodes, so the result is deterministic and the shader is a direct
//! mirror of collectCutAtError in LodGraph.cpp.
inline constexpr char const* LOD_SELECT_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;

// Scalar fields keep the std430 layout identical to the packed C++ GpuLodNode.
struct GpuNode {
    float centerX;
    float centerY;
    float centerZ;
    float radius;
    float apexX;
    float apexY;
    float apexZ;
    float axisX;
    float axisY;
    float axisZ;
    float cutoff;
    float accumulatedError;
    uint indexOffset;
    uint indexCount;
    uint childOffset;
    uint childCount;
    uint level;
    uint materialId;
    uint submeshId;
    uint flags;
    uint parent;
    uint baseTriangles;
};

layout(std430, set = 0, binding = 0) readonly buffer Nodes { GpuNode nodes[]; };
layout(std430, set = 0, binding = 1) writeonly buffer SelectedNodes {
    uint values[];
} selectionOutput;
layout(std430, set = 0, binding = 2) buffer Counters {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
    uint compactedIndexCount;
    uint commandCount;
} counters;

layout(std430, set = 0, binding = 3) readonly buffer MeshIndices {
    uint indices[];
} meshIndices;

layout(std430, set = 0, binding = 4) writeonly buffer CompactedIndices {
    uint indices[];
} compactedIndices;

struct DrawCommand {
    uint indexCount;
    uint instanceCount;
    uint firstIndex;
    uint vertexOffset;
    uint firstInstance;
};
layout(std430, set = 0, binding = 5) writeonly buffer DrawCommands {
    DrawCommand commands[];
} drawCommands;

layout(push_constant) uniform Params {
    float eyeX;
    float eyeY;
    float eyeZ;
    float nearPlane;
    float forwardX;
    float forwardY;
    float forwardZ;
    float farPlane;
    float rightX;
    float rightY;
    float rightZ;
    float tanHalfFov;
    float upX;
    float upY;
    float upZ;
    float aspect;
    float threshold;
    float pixelsPerRadian;
    uint nodeCount;
    uint padding;
} pc;

bool outsideFrustum(GpuNode node) {
    vec3 center = vec3(node.centerX, node.centerY, node.centerZ);
    vec3 eye = vec3(pc.eyeX, pc.eyeY, pc.eyeZ);
    vec3 forward = vec3(pc.forwardX, pc.forwardY, pc.forwardZ);
    vec3 right = vec3(pc.rightX, pc.rightY, pc.rightZ);
    vec3 up = vec3(pc.upX, pc.upY, pc.upZ);
    vec3 d = center - eye;
    float depth = dot(d, forward);
    if (depth + node.radius < pc.nearPlane || depth - node.radius > pc.farPlane) {
        return true;
    }
    float tanX = pc.tanHalfFov * pc.aspect;
    float tanY = pc.tanHalfFov;
    return abs(dot(d, right)) - depth * tanX > node.radius * sqrt(1.0 + tanX * tanX) ||
           abs(dot(d, up)) - depth * tanY > node.radius * sqrt(1.0 + tanY * tanY);
}

float screenError(GpuNode node) {
    vec3 center = vec3(node.centerX, node.centerY, node.centerZ);
    vec3 eye = vec3(pc.eyeX, pc.eyeY, pc.eyeZ);
    vec3 forward = vec3(pc.forwardX, pc.forwardY, pc.forwardZ);
    float depth = dot(center - eye, forward) - node.radius;
    float distance = max(depth, max(pc.nearPlane, 1e-6));
    return node.accumulatedError / distance * pc.pixelsPerRadian;
}

void main() {
    uint nodeId = gl_GlobalInvocationID.x;
    if (nodeId >= pc.nodeCount) {
        return;
    }

    GpuNode self = nodes[nodeId];
    bool ancestorCulled = false;
    bool isSelected = true;
    uint current = nodeId;
    for (uint depth = 0u; depth < 64u; ++depth) {
        uint parent = nodes[current].parent;
        if (parent == 0xFFFFFFFFu) {
            break;
        }
        GpuNode ancestor = nodes[parent];
        if (outsideFrustum(ancestor)) {
            ancestorCulled = true;
            isSelected = false;
            break;
        }
        if (ancestor.childCount == 0u || screenError(ancestor) <= pc.threshold) {
            isSelected = false;
            break;
        }
        current = parent;
    }

    const bool selfCulled = outsideFrustum(self);
    if (selfCulled) {
        isSelected = false;
    }
    if (self.childCount != 0u && screenError(self) > pc.threshold) {
        // The node itself is too coarse, so the cut must continue through its children.
        isSelected = false;
    }
    if (isSelected) {
        uint slot = atomicAdd(counters.selectedCount, 1u);
        selectionOutput.values[slot] = nodeId;
        atomicAdd(counters.selectedTriangles, self.indexCount / 3u);

        // Reserve one contiguous range in the compacted index buffer and one indirect command.
        // The subsequent draw reads these buffers directly; no CPU compaction or command build
        // is needed on the runtime path.
        uint compactedOffset = atomicAdd(counters.compactedIndexCount, self.indexCount);
        uint commandSlot = atomicAdd(counters.commandCount, 1u);
        for (uint i = 0u; i < self.indexCount; ++i) {
            compactedIndices.indices[compactedOffset + i] =
                    meshIndices.indices[self.indexOffset + i];
        }
        DrawCommand command;
        command.indexCount = self.indexCount;
        command.instanceCount = 1u;
        command.firstIndex = compactedOffset;
        command.vertexOffset = 0u;
        command.firstInstance = nodeId;
        drawCommands.commands[commandSlot] = command;
    }
    if (selfCulled && !ancestorCulled) {
        // One count per culled subtree root, matching the CPU accounting.
        atomicAdd(counters.culledTriangles, self.baseTriangles);
    }
}
)GLSL";

//! Triangle rasterization into an R32_UINT visibility buffer. The projection mirrors the CPU
//! reference in VisibilityBuffer.cpp, with the Vulkan Y flip applied explicitly.
inline constexpr char const* VISIBILITY_VERT_GLSL = R"GLSL(
#version 450
layout(location = 0) in vec3 inPosition;
layout(location = 0) out flat uint outNode;
layout(location = 1) out flat uint outTriBase;

struct GpuNode {
    float centerX;
    float centerY;
    float centerZ;
    float radius;
    float apexX;
    float apexY;
    float apexZ;
    float axisX;
    float axisY;
    float axisZ;
    float cutoff;
    float accumulatedError;
    uint indexOffset;
    uint indexCount;
    uint childOffset;
    uint childCount;
    uint level;
    uint materialId;
    uint submeshId;
    uint flags;
    uint parent;
    uint baseTriangles;
};

layout(std430, set = 0, binding = 0) readonly buffer Nodes { GpuNode nodes[]; } nodeData;

layout(push_constant) uniform Params {
    float eyeX;
    float eyeY;
    float eyeZ;
    float nearPlane;
    float forwardX;
    float forwardY;
    float forwardZ;
    float farPlane;
    float rightX;
    float rightY;
    float rightZ;
    float tanHalfFov;
    float upX;
    float upY;
    float upZ;
    float aspect;
} pc;

void main() {
    // firstInstance is the DAG node id, so one indirect command carries both the index range and
    // the node identity used by the deferred shading pass.
    uint nodeId = uint(gl_InstanceIndex);
    GpuNode node = nodeData.nodes[nodeId];
    vec3 eye = vec3(pc.eyeX, pc.eyeY, pc.eyeZ);
    vec3 forward = vec3(pc.forwardX, pc.forwardY, pc.forwardZ);
    vec3 right = vec3(pc.rightX, pc.rightY, pc.rightZ);
    vec3 up = vec3(pc.upX, pc.upY, pc.upZ);
    vec3 d = inPosition - eye;
    float depth = dot(d, forward);
    if (depth <= 0.0) {
        gl_Position = vec4(0.0);
        return;
    }
    float x = dot(d, right) / (depth * pc.tanHalfFov * pc.aspect);
    float y = dot(d, up) / (depth * pc.tanHalfFov);
    float z = (depth - pc.nearPlane) / (pc.farPlane - pc.nearPlane);
    gl_Position = vec4(x, -y, z, 1.0);
    outNode = nodeId;
    outTriBase = node.indexOffset / 3u;
}
)GLSL";

inline constexpr char const* VISIBILITY_FRAG_GLSL = R"GLSL(
#version 450
layout(location = 0) in flat uint inNode;
layout(location = 1) in flat uint inTriBase;
layout(location = 0) out uint outNode;
layout(location = 1) out uint outTriangle;

void main() {
    outNode = inNode;
    outTriangle = inTriBase + uint(gl_PrimitiveID);
}
)GLSL";

//! Vertex compaction pass A: mark every referenced source vertex. One invocation per index;
//! the first reference to a vertex wins the CAS, so no spin loop is needed.
inline constexpr char const* COMPACT_MARK_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) readonly buffer Indices {
    uint indices[];
} indexData;
layout(std430, set = 0, binding = 1) buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 2) buffer Counter {
    uint uniqueCount;
    uint assignedCount;
} counter;
layout(std430, set = 0, binding = 3) readonly buffer CutCounter {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
    uint compactedIndexCount;
    uint commandCount;
} cutCounter;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
const uint EMPTY = 0xFFFFFFFFu;
const uint MARK = 0xFFFFFFFEu;
void main() {
    uint index = gl_GlobalInvocationID.x;
    // The cut pass writes a compacted prefix of the index buffer and publishes its length in
    // its counter block. Dispatch this pass over the full source capacity so the whole frame can
    // be recorded without a host readback, then clamp to the prefix that is actually live.
    const uint liveIndexCount = min(cutCounter.compactedIndexCount, pc.indexCount);
    if (index >= liveIndexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source < pc.vertexCount &&
            atomicCompSwap(vertexMap.map[source], EMPTY, MARK) == EMPTY) {
        atomicAdd(counter.uniqueCount, 1u);
    }
}
)GLSL";

//! Pass B: assign dense ids and gather positions. Iterating every source vertex keeps the
//! assignment deterministic and avoids a second indirection list.
inline constexpr char const* COMPACT_GATHER_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 1) readonly buffer Positions {
    float positions[];
} sourcePositions;
layout(std430, set = 0, binding = 2) writeonly buffer CompactedPositions {
    float positions[];
} compactedPositions;
layout(std430, set = 0, binding = 3) buffer Counter {
    uint uniqueCount;
    uint assignedCount;
} counter;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
const uint MARK = 0xFFFFFFFEu;
void main() {
    uint source = gl_GlobalInvocationID.x;
    if (source >= pc.vertexCount || vertexMap.map[source] != MARK) {
        return;
    }
    uint compact = atomicAdd(counter.assignedCount, 1u);
    vertexMap.map[source] = compact;
    compactedPositions.positions[compact * 3u + 0u] = sourcePositions.positions[source * 3u + 0u];
    compactedPositions.positions[compact * 3u + 1u] = sourcePositions.positions[source * 3u + 1u];
    compactedPositions.positions[compact * 3u + 2u] = sourcePositions.positions[source * 3u + 2u];
}
)GLSL";

//! Pass C: rewrite the compacted index buffer in place. Each invocation owns exactly one index.
inline constexpr char const* COMPACT_REWRITE_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) buffer Indices {
    uint indices[];
} indexData;
layout(std430, set = 0, binding = 1) readonly buffer VertexMap {
    uint map[];
} vertexMap;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= pc.indexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source < pc.vertexCount) {
        indexData.indices[index] = vertexMap.map[source];
    }
}
)GLSL";

} // namespace mmgpu

#endif // TNT_MMGPU_SHADERSOURCES_H
