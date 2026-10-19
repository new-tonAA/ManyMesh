/*
 * Copyright (C) 2022 The Android Open Source Project
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
#include "TrianglePrimitive.h"

#include <private/backend/DriverApi.h>

#include <backend/DriverEnums.h>

#include <utils/FixedCapacityVector.h>

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace filament;
using namespace filament::backend;

namespace {

struct ComputeShader {
    std::string text;
    std::vector<char> binary;
    ShaderLanguage language = ShaderLanguage::ESSL3;

    void const* data() const noexcept {
        return binary.empty() ? (void const*) text.data() : (void const*) binary.data();
    }

    size_t size() const noexcept {
        return binary.empty() ? text.size() + 1 : binary.size();
    }
};

ComputeShader makeComputeShader(test::Backend backend, bool isMobile, std::string const& gl450,
        std::string const& gles310, std::string const& msl) {
    ComputeShader result;
    switch (backend) {
        case test::Backend::OPENGL:
            result.text = isMobile ? gles310 : gl450;
            result.language = ShaderLanguage::ESSL3;
            break;
        case test::Backend::VULKAN: {
            auto blob = test::ShaderGenerator::transpileCompute(gl450, test::Backend::VULKAN,
                    isMobile);
            result.binary.assign(blob.begin(), blob.end());
            result.language = ShaderLanguage::SPIRV;
            break;
        }
        case test::Backend::METAL:
            result.text = msl;
            result.language = ShaderLanguage::MSL;
            break;
        default:
            break;
    }
    return result;
}

} // anonymous namespace

TEST_F(ComputeTest, basic) {
    auto& driver = getDriverApi();

    std::string const shader_gl450 = R"(
#version 450 core
layout(local_size_x = 16) in;
void main() {
}
)";

    std::string const shader_gles310 = R"(
#version 310 es
layout(local_size_x = 16) in;
void main() {
}
)";

    std::string const shader_msl = R"(
#include <simd/simd.h>
#include <metal_stdlib>
using namespace metal;
constant uint3 WorkGroupSize [[maybe_unused]] = uint3(16u, 1u, 1u);
kernel void main0() {}
)";

    ComputeShader const shader = makeComputeShader(
            static_cast<test::Backend>(getBackend()), isMobile(), shader_gl450,
            shader_gles310, shader_msl);
    if (getBackend() == Backend::VULKAN) {
        ASSERT_FALSE(shader.binary.empty()) << "Unable to generate compute SPIR-V.";
    }

    Program program;
    program.shaderLanguage(shader.language);
    program.shader(ShaderStage::COMPUTE, shader.data(), shader.size());

    Handle<HwProgram> ph = driver.createProgram(std::move(program));
    driver.dispatchCompute(ph, { 1, 1, 1 });
    driver.destroyProgram(ph);
    driver.finish();

    executeCommands();
    getDriver().purge();
}

TEST_F(ComputeTest, copy) {
    auto& driver = getDriverApi();

    std::string const shader_gl450 = R"(
#version 450 core
layout(local_size_x = 16) in;
layout(std430, binding = 0) writeonly buffer Output { float elements[]; } output_data;
layout(std430, binding = 1) readonly  buffer Input0 { float elements[]; } input_data;
void main() {
    uint ident = gl_GlobalInvocationID.x;
    output_data.elements[ident] = input_data.elements[ident];
}
)";

    std::string const shader_gles310 = R"(
#version 310 es
layout(local_size_x = 16) in;
layout(std430) buffer;
layout(binding = 0) writeonly buffer Output { float elements[]; } output_data;
layout(binding = 1) readonly  buffer Input0 { float elements[]; } input_data;
void main() {
    uint ident = gl_GlobalInvocationID.x;
    output_data.elements[ident] = input_data.elements[ident];
}
)";

    std::string const shader_msl = R"(
#include <simd/simd.h>
#include <metal_stdlib>
using namespace metal;
struct Output_data {
    float elements[1];
};
struct Input_data {
    float elements[1];
};
constant uint3 WorkGroupSize [[maybe_unused]] = uint3(16u, 1u, 1u);
kernel void main0(device Output_data& output_data [[buffer(0)]],
        device Input_data& input_data [[buffer(1)]],
        uint3 GlobalInvocationID [[thread_position_in_grid]]) {
    output_data.elements[GlobalInvocationID.x] = input_data.elements[GlobalInvocationID.x];
}
)";

    ComputeShader const shader = makeComputeShader(
            static_cast<test::Backend>(getBackend()), isMobile(), shader_gl450,
            shader_gles310, shader_msl);
    if (getBackend() == Backend::VULKAN) {
        ASSERT_FALSE(shader.binary.empty()) << "Unable to generate compute SPIR-V.";
    }

    size_t const groupSize = 16;
    size_t const groupCount = 1024;
    size_t const size = groupSize * groupCount * sizeof(float);

    std::vector<float> data(groupSize * groupCount);
    std::generate(data.begin(), data.end(), [v = 0.0f]() mutable {
        v = v + 1.0f;
        return v;
    });

    auto output_data = driver.createBufferObject(
            size, BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    auto input_data = driver.createBufferObject(
            size, BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    driver.updateBufferObject(input_data, { data.data(), size }, 0);

    Program program;
    program.shaderLanguage(shader.language);
    program.shader(ShaderStage::COMPUTE, shader.data(), shader.size());
    Program::DescriptorBindingsInfo bindings(2);
    bindings[0] = { "output_data", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    bindings[1] = { "input_data", DescriptorType::SHADER_STORAGE_BUFFER, 1 };
    program.descriptorBindings(0, std::move(bindings));
    Handle<HwProgram> ph = driver.createProgram(std::move(program));

    utils::FixedCapacityVector<DescriptorSetLayoutDescriptor> descriptors(2);
    descriptors[0] = {
        .type = DescriptorType::SHADER_STORAGE_BUFFER,
        .stageFlags = ShaderStageFlags::COMPUTE,
        .binding = 0,
    };
    descriptors[1] = {
        .type = DescriptorType::SHADER_STORAGE_BUFFER,
        .stageFlags = ShaderStageFlags::COMPUTE,
        .binding = 1,
    };
    auto dsl = driver.createDescriptorSetLayout(
            DescriptorSetLayout{ .descriptors = std::move(descriptors) });
    auto ds = driver.createDescriptorSet(dsl);

    driver.updateDescriptorSetBuffer(ds, 0, output_data, 0, size);
    driver.updateDescriptorSetBuffer(ds, 1, input_data, 0, size);
    driver.bindDescriptorSet(ds, 0, {});

    driver.dispatchCompute(ph, { groupCount, 1, 1 });

    float* const user = (float*) malloc(size);
    driver.readBufferSubData(output_data, 0, size, { user, size });

    driver.destroyDescriptorSet(ds);
    driver.destroyDescriptorSetLayout(dsl);
    driver.destroyProgram(ph);
    driver.destroyBufferObject(input_data);
    driver.destroyBufferObject(output_data);
    driver.finish();

    executeCommands();
    getDriver().purge();

    EXPECT_EQ(memcmp(user, data.data(), size), 0);

    free(user);
}

TEST_F(ComputeTest, graphicsConsumesComputeOutput) {
    // OpenGL has implicit ordering between compute and graphics work. This test exercises the
    // explicit Vulkan barrier and the descriptor-set rebinding that follows it.
    if (getBackend() != Backend::VULKAN) {
        GTEST_SKIP() << "The compute-to-graphics barrier test requires Vulkan.";
    }

    auto& driver = getDriverApi();

    std::string const compute_gl450 = R"(
#version 450 core
layout(local_size_x = 1) in;
layout(std430, binding = 0) writeonly buffer Output { vec4 value; } output_data;
void main() {
    output_data.value = vec4(1.0, 0.0, 0.0, 1.0);
}
)";

    std::string const compute_gles310 = R"(
#version 310 es
layout(local_size_x = 1) in;
layout(std430) buffer;
layout(binding = 0) writeonly buffer Output { vec4 value; } output_data;
void main() {
    output_data.value = vec4(1.0, 0.0, 0.0, 1.0);
}
)";

    ComputeShader const computeShader = makeComputeShader(
            static_cast<test::Backend>(getBackend()), isMobile(), compute_gl450,
            compute_gles310, "");
    if (getBackend() == Backend::VULKAN) {
        ASSERT_FALSE(computeShader.binary.empty()) << "Unable to generate compute SPIR-V.";
    }

    std::string const vertex_gl450 = R"(
#version 450 core
layout(location = 0) in vec2 position;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
}
)";

    std::string const fragment_gl450 = R"(
#version 450 core
layout(std430, binding = 0) readonly buffer Output { vec4 value; } output_data;
layout(location = 0) out vec4 fragColor;
void main() {
    fragColor = output_data.value;
}
)";

    Program computeProgram;
    computeProgram.shaderLanguage(computeShader.language);
    computeProgram.shader(ShaderStage::COMPUTE, computeShader.data(), computeShader.size());
    Program::DescriptorBindingsInfo computeBindings(1);
    computeBindings[0] = { "output_data", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    computeProgram.descriptorBindings(0, std::move(computeBindings));
    auto const computeHandle = driver.createProgram(std::move(computeProgram));

    test::ShaderGenerator graphicsShader(vertex_gl450, fragment_gl450,
            static_cast<test::Backend>(getBackend()), isMobile());
    Program graphicsProgram = graphicsShader.getProgram(driver);
    Program::DescriptorBindingsInfo graphicsBindings(1);
    graphicsBindings[0] = { "output_data", DescriptorType::SHADER_STORAGE_BUFFER, 0 };
    graphicsProgram.descriptorBindings(0, std::move(graphicsBindings));
    auto const graphicsHandle = driver.createProgram(std::move(graphicsProgram));

    utils::FixedCapacityVector<DescriptorSetLayoutDescriptor> descriptors(1);
    descriptors[0] = {
        .type = DescriptorType::SHADER_STORAGE_BUFFER,
        .stageFlags = ShaderStageFlags::COMPUTE | ShaderStageFlags::FRAGMENT,
        .binding = 0,
    };
    auto const dsl = driver.createDescriptorSetLayout(
            DescriptorSetLayout{ .descriptors = std::move(descriptors) });
    auto const ds = driver.createDescriptorSet(dsl);

    constexpr uint32_t bufferSize = sizeof(float) * 4;
    float const zeros[4] = {};
    auto const outputBuffer = driver.createBufferObject(
            bufferSize, BufferObjectBinding::SHADER_STORAGE, BufferUsage::STATIC);
    driver.updateBufferObject(outputBuffer, { zeros, bufferSize }, 0);
    driver.updateDescriptorSetBuffer(ds, 0, outputBuffer, 0, bufferSize);
    driver.bindDescriptorSet(ds, 0, {});

    auto const swapChain = driver.createSwapChainHeadless(4, 4, 0);
    driver.makeCurrent(swapChain, swapChain);

    auto const texture = driver.createTexture(SamplerType::SAMPLER_2D, 1,
            TextureFormat::RGBA8, 1, 4, 4, 1,
            TextureUsage::COLOR_ATTACHMENT | TextureUsage::SAMPLEABLE);
    auto const renderTarget = driver.createRenderTarget(TargetBufferFlags::COLOR, 4, 4, 1, 0,
            {{ texture, 0 }}, {}, {});

    std::array<uint8_t, 4 * 4 * 4> pixels{};

    {
        test::TrianglePrimitive triangle(driver);

        PipelineState state;
        state.program = graphicsHandle;
        state.pipelineLayout.setLayout[0] = { dsl };
        state.primitiveType = PrimitiveType::TRIANGLES;
        state.vertexBufferInfo = triangle.getVertexBufferInfo();
        state.rasterState.culling = CullingMode::NONE;
        state.rasterState.colorWrite = true;
        state.rasterState.depthWrite = false;
        state.rasterState.depthFunc = RasterState::DepthFunc::A;

        RenderPassParams params = {};
        params.flags.clear = TargetBufferFlags::COLOR;
        params.flags.discardStart = TargetBufferFlags::ALL;
        params.flags.discardEnd = TargetBufferFlags::NONE;
        params.clearColor = { 0.0, 0.0, 0.0, 1.0 };
        params.viewport = { 0, 0, 4, 4 };

        driver.beginFrame(0, 0, 0);
        driver.dispatchCompute(computeHandle, { 1, 1, 1 });
        driver.beginRenderPass(renderTarget, params);
        driver.bindPipeline(state);
        driver.bindRenderPrimitive(triangle.getRenderPrimitive());
        driver.draw2(0, 3, 1);
        driver.endRenderPass();
        driver.readPixels(renderTarget, 0, 0, 4, 4,
                PixelBufferDescriptor(pixels.data(), pixels.size(),
                        PixelDataFormat::RGBA, PixelDataType::UBYTE));
        driver.endFrame(0);
    }

    driver.destroyProgram(computeHandle);
    driver.destroyProgram(graphicsHandle);
    driver.destroyDescriptorSet(ds);
    driver.destroyDescriptorSetLayout(dsl);
    driver.destroyBufferObject(outputBuffer);
    driver.destroyRenderTarget(renderTarget);
    driver.destroyTexture(texture);
    driver.destroySwapChain(swapChain);
    driver.finish();

    executeCommands();
    getDriver().purge();

    // The clear color is black. A red pixel proves the draw read the value written by the
    // dispatch, i.e. the compute writes are visible to the fragment stage in the same command
    // buffer.
    EXPECT_GT(pixels[0], 127) << "The fragment shader did not observe the compute output.";
    EXPECT_LT(pixels[1], 32) << "The fragment shader output was not the compute value.";
    EXPECT_LT(pixels[2], 32) << "The fragment shader output was not the compute value.";
}
