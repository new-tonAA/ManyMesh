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
} counters;

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
    float halfHeight = depth * pc.tanHalfFov;
    float halfWidth = halfHeight * pc.aspect;
    if (abs(dot(d, right)) - node.radius > halfWidth) {
        return true;
    }
    if (abs(dot(d, up)) - node.radius > halfHeight) {
        return true;
    }
    return false;
}

float screenError(GpuNode node) {
    vec3 center = vec3(node.centerX, node.centerY, node.centerZ);
    vec3 eye = vec3(pc.eyeX, pc.eyeY, pc.eyeZ);
    vec3 forward = vec3(pc.forwardX, pc.forwardY, pc.forwardZ);
    float depth = dot(center - eye, forward);
    if (depth <= pc.nearPlane) {
        return 3.402823466e+38;
    }
    return node.accumulatedError / depth * pc.pixelsPerRadian;
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

} // namespace mmgpu

#endif // TNT_MMGPU_SHADERSOURCES_H
