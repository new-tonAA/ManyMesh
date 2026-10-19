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

#ifndef TNT_MANYMESH_GPULODCUTSHADERS_H
#define TNT_MANYMESH_GPULODCUTSHADERS_H

namespace filament {
namespace manymesh {
namespace detail {

inline constexpr char const* kGpuLodCutGlsl450 = R"GLSL(#version 450
layout(local_size_x = 64) in;

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

layout(std430, binding = 0) readonly buffer Nodes { GpuNode nodes[]; } nodeData;
layout(std430, binding = 1) writeonly buffer SelectedNodes { uint values[]; } selectionOutput;
layout(std430, binding = 2) buffer Counters {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
} counters;
layout(std430, binding = 3) readonly buffer Params {
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
    uint maxSelectedNodes;
} params;

bool outsideFrustum(GpuNode node) {
    vec3 center = vec3(node.centerX, node.centerY, node.centerZ);
    vec3 eye = vec3(params.eyeX, params.eyeY, params.eyeZ);
    vec3 forward = vec3(params.forwardX, params.forwardY, params.forwardZ);
    vec3 right = vec3(params.rightX, params.rightY, params.rightZ);
    vec3 up = vec3(params.upX, params.upY, params.upZ);
    vec3 d = center - eye;
    float depth = dot(d, forward);
    if (depth + node.radius < params.nearPlane || depth - node.radius > params.farPlane) {
        return true;
    }
    float halfHeight = depth * params.tanHalfFov;
    float halfWidth = halfHeight * params.aspect;
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
    vec3 eye = vec3(params.eyeX, params.eyeY, params.eyeZ);
    vec3 forward = vec3(params.forwardX, params.forwardY, params.forwardZ);
    float depth = dot(center - eye, forward) - node.radius;
    float distance = max(depth, max(params.nearPlane, 1e-6));
    return node.accumulatedError / distance * params.pixelsPerRadian;
}

void main() {
    uint nodeId = gl_GlobalInvocationID.x;
    if (nodeId >= params.nodeCount) {
        return;
    }

    GpuNode self = nodeData.nodes[nodeId];
    bool ancestorCulled = false;
    bool isSelected = true;
    uint current = nodeId;
    for (uint depth = 0u; depth < 64u; ++depth) {
        uint parent = nodeData.nodes[current].parent;
        if (parent == 0xFFFFFFFFu) {
            break;
        }
        GpuNode ancestor = nodeData.nodes[parent];
        if (outsideFrustum(ancestor)) {
            ancestorCulled = true;
            isSelected = false;
            break;
        }
        if (ancestor.childCount == 0u || screenError(ancestor) <= params.threshold) {
            isSelected = false;
            break;
        }
        current = parent;
    }

    bool selfCulled = outsideFrustum(self);
    if (selfCulled) {
        isSelected = false;
    }
    if (self.childCount != 0u && screenError(self) > params.threshold) {
        isSelected = false;
    }
    if (isSelected) {
        uint slot = atomicAdd(counters.selectedCount, 1u);
        selectionOutput.values[slot] = nodeId;
        atomicAdd(counters.selectedTriangles, self.indexCount / 3u);
    }
    if (selfCulled && !ancestorCulled) {
        atomicAdd(counters.culledTriangles, self.baseTriangles);
    }
}
)GLSL";

inline constexpr char const* kGpuLodCutGles310 = R"GLSL(#version 310 es
layout(local_size_x = 64) in;
precision highp float;
precision highp int;

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

layout(std430) buffer;
layout(binding = 0) readonly buffer Nodes { GpuNode nodes[]; } nodeData;
layout(binding = 1) writeonly buffer SelectedNodes { uint values[]; } selectionOutput;
layout(binding = 2) buffer Counters {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
} counters;
layout(binding = 3) readonly buffer Params {
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
    uint maxSelectedNodes;
} params;

bool outsideFrustum(GpuNode node) {
    vec3 center = vec3(node.centerX, node.centerY, node.centerZ);
    vec3 eye = vec3(params.eyeX, params.eyeY, params.eyeZ);
    vec3 forward = vec3(params.forwardX, params.forwardY, params.forwardZ);
    vec3 right = vec3(params.rightX, params.rightY, params.rightZ);
    vec3 up = vec3(params.upX, params.upY, params.upZ);
    vec3 d = center - eye;
    float depth = dot(d, forward);
    if (depth + node.radius < params.nearPlane || depth - node.radius > params.farPlane) {
        return true;
    }
    float halfHeight = depth * params.tanHalfFov;
    float halfWidth = halfHeight * params.aspect;
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
    vec3 eye = vec3(params.eyeX, params.eyeY, params.eyeZ);
    vec3 forward = vec3(params.forwardX, params.forwardY, params.forwardZ);
    float depth = dot(center - eye, forward) - node.radius;
    float distance = max(depth, max(params.nearPlane, 1e-6));
    return node.accumulatedError / distance * params.pixelsPerRadian;
}

void main() {
    uint nodeId = gl_GlobalInvocationID.x;
    if (nodeId >= params.nodeCount) {
        return;
    }

    GpuNode self = nodeData.nodes[nodeId];
    bool ancestorCulled = false;
    bool isSelected = true;
    uint current = nodeId;
    for (uint depth = 0u; depth < 64u; ++depth) {
        uint parent = nodeData.nodes[current].parent;
        if (parent == 0xFFFFFFFFu) {
            break;
        }
        GpuNode ancestor = nodeData.nodes[parent];
        if (outsideFrustum(ancestor)) {
            ancestorCulled = true;
            isSelected = false;
            break;
        }
        if (ancestor.childCount == 0u || screenError(ancestor) <= params.threshold) {
            isSelected = false;
            break;
        }
        current = parent;
    }

    bool selfCulled = outsideFrustum(self);
    if (selfCulled) {
        isSelected = false;
    }
    if (self.childCount != 0u && screenError(self) > params.threshold) {
        isSelected = false;
    }
    if (isSelected) {
        uint slot = atomicAdd(counters.selectedCount, 1u);
        selectionOutput.values[slot] = nodeId;
        atomicAdd(counters.selectedTriangles, self.indexCount / 3u);
    }
    if (selfCulled && !ancestorCulled) {
        atomicAdd(counters.culledTriangles, self.baseTriangles);
    }
}
)GLSL";

} // namespace detail
} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_GPULODCUTSHADERS_H
