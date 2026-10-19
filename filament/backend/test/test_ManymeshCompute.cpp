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

#include "ComputeTest.h"

#include "ShaderGenerator.h"

#include <private/backend/DriverApi.h>

#include <backend/DriverEnums.h>

#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>

#include <algorithm>
#include <string>
#include <vector>

#include <stddef.h>
#include <stdint.h>

using namespace filament;
using namespace filament::backend;
using namespace filament::manymesh;

namespace {

Mesh makeGrid(uint32_t const nx, uint32_t const ny) {
    Mesh mesh;
    mesh.positions.reserve((nx + 1) * (ny + 1));
    for (uint32_t y = 0; y <= ny; ++y) {
        for (uint32_t x = 0; x <= nx; ++x) {
            mesh.positions.push_back({ float(x), float(y), 0.15f * float((x * 7 + y * 11) % 5) });
        }
    }
    auto index = [nx](uint32_t x, uint32_t y) { return y * (nx + 1) + x; };
    mesh.indices.reserve(nx * ny * 6);
    for (uint32_t y = 0; y < ny; ++y) {
        for (uint32_t x = 0; x < nx; ++x) {
            mesh.indices.push_back(index(x, y));
            mesh.indices.push_back(index(x + 1, y));
            mesh.indices.push_back(index(x + 1, y + 1));
            mesh.indices.push_back(index(x, y));
            mesh.indices.push_back(index(x + 1, y + 1));
            mesh.indices.push_back(index(x, y + 1));
        }
    }
    return mesh;
}

constexpr char const* kComputeGlsl450 = R"(
#version 450 core
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

layout(std430, binding = 0) readonly buffer Nodes { GpuNode nodes[]; } nodeData;
layout(std430, binding = 1) readonly buffer Indices { uint indices[]; } indexData;
layout(std430, binding = 2) writeonly buffer Output { uint values[]; } outputData;
layout(std430, binding = 3) readonly buffer Params { uint nodeCount; } params;

void main() {
    const uint i = gl_GlobalInvocationID.x;
    if (i >= params.nodeCount) {
        return;
    }
    const GpuNode node = nodeData.nodes[i];
    uint checksum = node.parent ^ node.baseTriangles ^ node.indexCount ^ node.indexOffset ^
                    node.level ^ node.flags;
    if (node.indexCount > 0u) {
        checksum ^= indexData.indices[node.indexOffset];
    }
    outputData.values[i] = checksum;
}
)";

constexpr char const* kComputeGles310 = R"(
#version 310 es
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
layout(binding = 1) readonly buffer Indices { uint indices[]; } indexData;
layout(binding = 2) writeonly buffer Output { uint values[]; } outputData;
layout(binding = 3) readonly buffer Params { uint nodeCount; } params;

void main() {
    const uint i = gl_GlobalInvocationID.x;
    if (i >= params.nodeCount) {
        return;
    }
    const GpuNode node = nodeData.nodes[i];
    uint checksum = node.parent ^ node.baseTriangles ^ node.indexCount ^ node.indexOffset ^
                    node.level ^ node.flags;
    if (node.indexCount > 0u) {
        checksum ^= indexData.indices[node.indexOffset];
    }
    outputData.values[i] = checksum;
}
)";

struct ComputeShader {
    std::string text;
    std::vector<char> binary;
    ShaderLanguage language = ShaderLanguage::ESSL3;

    void const* data() const noexcept {
        return binary.empty() ? static_cast<void const*>(text.data())
                              : static_cast<void const*>(binary.data());
    }
    size_t size() const noexcept { return binary.empty() ? text.size() + 1 : binary.size(); }
};

ComputeShader makeComputeShader(Backend backend, bool mobile, std::string const& gl450,
        std::string const& gles310) {
    ComputeShader result;
    if (backend == Backend::VULKAN) {
        auto blob = test::ShaderGenerator::transpileCompute(gl450, test::Backend::VULKAN, mobile);
        result.binary.assign(blob.begin(), blob.end());
        result.language = ShaderLanguage::SPIRV;
    } else {
        result.text = mobile ? gles310 : gl450;
        result.language = ShaderLanguage::ESSL3;
    }
    return result;
}

} // namespace

TEST_F(ComputeTest, manymeshGpuLodNodeTable) {
    if (getBackend() != Backend::VULKAN && getBackend() != Backend::OPENGL) {
        GTEST_SKIP() << "The ManyMesh compute regression requires Vulkan or OpenGL.";
    }

    Mesh const mesh = makeGrid(24, 24);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);
    GpuLodBuffer const gpu = flattenLodGraph(graph);

    ASSERT_GT(gpu.nodes.size(), 0u);
    ASSERT_FALSE(gpu.indices.empty());

    std::string const gl450 = kComputeGlsl450;
    std::string const gles310 = kComputeGles310;
    ComputeShader const shader = makeComputeShader(getBackend(), isMobile(), gl450, gles310);
    if (getBackend() == Backend::VULKAN) {
        ASSERT_FALSE(shader.binary.empty()) << "Unable to generate compute SPIR-V.";
    }

    auto& driver = getDriverApi();
    size_t const nodeBytes = gpu.nodes.size() * sizeof(GpuLodNode);
    size_t const indexBytes = gpu.indices.size() * sizeof(uint32_t);
    size_t const outputBytes = gpu.nodes.size() * sizeof(uint32_t);
    uint32_t const nodeCount = uint32_t(gpu.nodes.size());

    auto const nodesBuffer = driver.createBufferObject(nodeBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto const indicesBuffer = driver.createBufferObject(indexBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto const outputBuffer = driver.createBufferObject(outputBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto const paramsBuffer = driver.createBufferObject(sizeof(uint32_t),
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    driver.updateBufferObject(nodesBuffer, { gpu.nodes.data(), nodeBytes }, 0);
    driver.updateBufferObject(indicesBuffer, { gpu.indices.data(), indexBytes }, 0);
    driver.updateBufferObject(paramsBuffer, { &nodeCount, sizeof(uint32_t) }, 0);

    Program program;
    program.shaderLanguage(shader.language);
    program.shader(ShaderStage::COMPUTE, shader.data(), shader.size());
    Program::DescriptorBindingsInfo bindings(4);
    bindings[0] = { "nodeData", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    bindings[1] = { "indexData", DescriptorType::SHADER_STORAGE_BUFFER, 1 };
    bindings[2] = { "outputData", DescriptorType::SHADER_STORAGE_BUFFER, 2 };
    bindings[3] = { "params", DescriptorType::SHADER_STORAGE_BUFFER, 3 };
    program.descriptorBindings(0, std::move(bindings));
    auto const programHandle = driver.createProgram(std::move(program));

    utils::FixedCapacityVector<DescriptorSetLayoutDescriptor> descriptors(4);
    for (uint32_t binding = 0; binding < 4; ++binding) {
        descriptors[binding] = {
            .type = DescriptorType::SHADER_STORAGE_BUFFER,
            .stageFlags = ShaderStageFlags::COMPUTE,
            .binding = descriptor_binding_t(binding),
        };
    }
    auto const layout = driver.createDescriptorSetLayout(
            DescriptorSetLayout{ .descriptors = std::move(descriptors) });
    auto const set = driver.createDescriptorSet(layout);
    driver.updateDescriptorSetBuffer(set, 0, nodesBuffer, 0, nodeBytes);
    driver.updateDescriptorSetBuffer(set, 1, indicesBuffer, 0, indexBytes);
    driver.updateDescriptorSetBuffer(set, 2, outputBuffer, 0, outputBytes);
    driver.updateDescriptorSetBuffer(set, 3, paramsBuffer, 0, sizeof(uint32_t));
    driver.bindDescriptorSet(set, 0, {});

    driver.dispatchCompute(programHandle, { (nodeCount + 63u) / 64u, 1, 1 });

    std::vector<uint32_t> actual(gpu.nodes.size());
    driver.readBufferSubData(outputBuffer, 0, outputBytes, { actual.data(), outputBytes });

    driver.destroyDescriptorSet(set);
    driver.destroyDescriptorSetLayout(layout);
    driver.destroyProgram(programHandle);
    driver.destroyBufferObject(paramsBuffer);
    driver.destroyBufferObject(outputBuffer);
    driver.destroyBufferObject(indicesBuffer);
    driver.destroyBufferObject(nodesBuffer);
    driver.finish();

    executeCommands();
    getDriver().purge();

    for (size_t i = 0; i < gpu.nodes.size(); ++i) {
        GpuLodNode const& node = gpu.nodes[i];
        uint32_t expected = node.parent ^ node.baseTriangles ^ node.indexCount ^ node.indexOffset ^
                            node.level ^ node.flags;
        if (node.indexCount > 0) {
            ASSERT_LT(node.indexOffset, gpu.indices.size());
            expected ^= gpu.indices[node.indexOffset];
        }
        EXPECT_EQ(actual[i], expected) << "node " << i;
    }
}

TEST_F(ComputeTest, manymeshGpuCutMatchesCpu) {
    if (getBackend() != Backend::VULKAN && getBackend() != Backend::OPENGL) {
        GTEST_SKIP() << "The ManyMesh GPU cut regression requires Vulkan or OpenGL.";
    }

    Mesh const mesh = makeGrid(24, 24);
    LodGraphOptions options;
    options.clusterize.maxVertices = 64;
    options.clusterize.maxTriangles = 64;
    options.clustersPerNode = 8;
    options.levels = 4;
    LodGraph const graph = buildLodGraph(mesh, options);
    GpuLodBuffer const gpu = flattenLodGraph(graph);
    ASSERT_GT(gpu.nodes.size(), 0u);

    ViewCamera camera;
    camera.eye = math::float3{ 12.0f, 12.0f, 30.0f };
    camera.target = math::float3{ 12.0f, 12.0f, 0.0f };
    camera.fovY = 0.7853982f;
    camera.screenWidth = 960;
    camera.screenHeight = 720;
    camera.near = 0.1f;
    camera.far = 200.0f;
    float const thresholdPx = 1.0f;

    ComputeShader const shader = makeComputeShader(getBackend(), isMobile(),
            std::string(gpuLodCutShaderSource(false)), std::string(gpuLodCutShaderSource(true)));
    if (getBackend() == Backend::VULKAN) {
        ASSERT_FALSE(shader.binary.empty()) << "Unable to generate GPU cut SPIR-V.";
    }

    auto& driver = getDriverApi();
    uint32_t const nodeCount = uint32_t(gpu.nodes.size());
    size_t const nodeBytes = gpu.nodes.size() * sizeof(GpuLodNode);
    size_t const selectionBytes = gpu.nodes.size() * sizeof(uint32_t);
    GpuLodCutParams const params = makeGpuLodCutParams(camera, nodeCount, thresholdPx);
    GpuLodCutCounters const zeroCounters{};

    auto const nodesBuffer = driver.createBufferObject(nodeBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto const selectionBuffer = driver.createBufferObject(selectionBytes,
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto const counterBuffer = driver.createBufferObject(sizeof(GpuLodCutCounters),
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::DYNAMIC);
    auto const paramsBuffer = driver.createBufferObject(sizeof(GpuLodCutParams),
            BufferObjectBinding::SHADER_STORAGE, BufferUsage::DYNAMIC);
    driver.updateBufferObject(nodesBuffer, { gpu.nodes.data(), nodeBytes }, 0);
    driver.updateBufferObject(counterBuffer, { &zeroCounters, sizeof(zeroCounters) }, 0);
    driver.updateBufferObject(paramsBuffer, { &params, sizeof(params) }, 0);

    Program program;
    program.shaderLanguage(shader.language);
    program.shader(ShaderStage::COMPUTE, shader.data(), shader.size());
    Program::DescriptorBindingsInfo bindings(4);
    bindings[0] = { "nodeData", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    bindings[1] = { "selectionOutput", DescriptorType::SHADER_STORAGE_BUFFER, 1 };
    bindings[2] = { "counters", DescriptorType::SHADER_STORAGE_BUFFER, 2 };
    bindings[3] = { "params", DescriptorType::SHADER_STORAGE_BUFFER, 3 };
    program.descriptorBindings(0, std::move(bindings));
    auto const programHandle = driver.createProgram(std::move(program));

    utils::FixedCapacityVector<DescriptorSetLayoutDescriptor> descriptors(4);
    for (uint32_t binding = 0; binding < 4; ++binding) {
        descriptors[binding] = {
            .type = DescriptorType::SHADER_STORAGE_BUFFER,
            .stageFlags = ShaderStageFlags::COMPUTE,
            .binding = descriptor_binding_t(binding),
        };
    }
    auto const layout = driver.createDescriptorSetLayout(
            DescriptorSetLayout{ .descriptors = std::move(descriptors) });
    auto const set = driver.createDescriptorSet(layout);
    driver.updateDescriptorSetBuffer(set, 0, nodesBuffer, 0, nodeBytes);
    driver.updateDescriptorSetBuffer(set, 1, selectionBuffer, 0, selectionBytes);
    driver.updateDescriptorSetBuffer(set, 2, counterBuffer, 0, sizeof(GpuLodCutCounters));
    driver.updateDescriptorSetBuffer(set, 3, paramsBuffer, 0, sizeof(GpuLodCutParams));
    driver.bindDescriptorSet(set, 0, {});
    driver.dispatchCompute(programHandle, { (nodeCount + 63u) / 64u, 1, 1 });

    GpuLodCutCounters counters{};
    std::vector<uint32_t> selected(nodeCount);
    driver.readBufferSubData(counterBuffer, 0, sizeof(counters), { &counters, sizeof(counters) });
    driver.readBufferSubData(selectionBuffer, 0, selectionBytes,
            { selected.data(), selectionBytes });

    driver.destroyDescriptorSet(set);
    driver.destroyDescriptorSetLayout(layout);
    driver.destroyProgram(programHandle);
    driver.destroyBufferObject(paramsBuffer);
    driver.destroyBufferObject(counterBuffer);
    driver.destroyBufferObject(selectionBuffer);
    driver.destroyBufferObject(nodesBuffer);
    driver.finish();

    executeCommands();
    getDriver().purge();

    ASSERT_LE(counters.selectedCount, nodeCount);
    selected.resize(counters.selectedCount);
    std::vector<uint32_t> gpuNodes = selected;
    LodGraphCut cpu = selectLodGraphCut(graph, camera, thresholdPx);
    std::sort(gpuNodes.begin(), gpuNodes.end());
    std::sort(cpu.nodes.begin(), cpu.nodes.end());
    EXPECT_EQ(gpuNodes, cpu.nodes);
    EXPECT_EQ(counters.culledTriangles, cpu.culledTriangles);

    LodGraphSelection const assembled =
            assembleLodSelection(graph, camera, std::move(selected), counters.culledTriangles);
    EXPECT_EQ(counters.selectedTriangles, assembled.selectedTriangles);
}

TEST_F(ComputeTest, manymeshGpuCutGlesShaderCompiles) {
    if (getBackend() != Backend::VULKAN && getBackend() != Backend::OPENGL) {
        GTEST_SKIP() << "The ManyMesh mobile shader check requires a compute backend.";
    }
    std::string const gles310 = gpuLodCutShaderSource(true);
    // The mobile OpenGL backend consumes this source directly. Transpiling it to SPIR-V
    // validates the ES syntax, buffer qualifiers and binding layout without depending on
    // ShaderGenerator's desktop-only SpvToEs path.
    auto const mobileSpirv =
            test::ShaderGenerator::transpileCompute(gles310, test::Backend::VULKAN, true);
    EXPECT_FALSE(mobileSpirv.empty());
}
