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
#include "TrianglePrimitive.h"

#include <private/backend/DriverApi.h>

#include <backend/DriverEnums.h>

#include <array>
#include <cstdint>
#include <cstring>

using namespace filament;
using namespace filament::backend;

namespace {

// Matches the layout consumed by vkCmdDrawIndexedIndirect, glDrawElementsIndirect and
// DrawIndexedIndirect. Keeping the assertion local makes the backend contract explicit.
struct DrawIndexedIndirectCommand {
    uint32_t indexCount = 0;
    uint32_t instanceCount = 1;
    uint32_t firstIndex = 0;
    int32_t baseVertex = 0;
    uint32_t baseInstance = 0;
};

static_assert(sizeof(DrawIndexedIndirectCommand) == 20);

} // namespace

TEST_F(ComputeTest, drawIndexedIndirect) {
    if (getBackend() != Backend::VULKAN && getBackend() != Backend::OPENGL) {
        GTEST_SKIP() << "The indirect-draw regression requires Vulkan or OpenGL.";
    }

    auto& driver = getDriverApi();

    std::string const vertex = R"(
#version 450 core
layout(location = 0) in vec2 position;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
}
)";

    std::string const fragment = R"(
#version 450 core
layout(location = 0) out vec4 fragColor;
void main() {
    fragColor = vec4(0.0, 1.0, 0.0, 1.0);
}
)";

    auto const swapChain = driver.createSwapChainHeadless(4, 4, 0);
    driver.makeCurrent(swapChain, swapChain);

    test::ShaderGenerator graphicsShader(vertex, fragment,
            static_cast<test::Backend>(getBackend()), isMobile());
    Program graphicsProgram = graphicsShader.getProgram(driver);
    auto const program = driver.createProgram(std::move(graphicsProgram));

    DrawIndexedIndirectCommand const command = {
        .indexCount = 3,
        .instanceCount = 1,
        .firstIndex = 0,
        .baseVertex = 0,
        .baseInstance = 0,
    };
    auto const indirectBuffer = driver.createBufferObject(
            sizeof(command), BufferObjectBinding::INDIRECT, BufferUsage::STATIC);
    driver.updateBufferObject(indirectBuffer, { &command, sizeof(command) }, 0);

    auto const texture = driver.createTexture(SamplerType::SAMPLER_2D, 1,
            TextureFormat::RGBA8, 1, 4, 4, 1,
            TextureUsage::COLOR_ATTACHMENT | TextureUsage::SAMPLEABLE);
    auto const renderTarget = driver.createRenderTarget(TargetBufferFlags::COLOR, 4, 4, 1, 0,
            {{ texture, 0 }}, {}, {});

    std::array<uint8_t, 4 * 4 * 4> pixels{};

    {
        test::TrianglePrimitive triangle(driver);

        PipelineState state;
        state.program = program;
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
        driver.beginRenderPass(renderTarget, params);
        driver.bindPipeline(state);
        driver.bindRenderPrimitive(triangle.getRenderPrimitive());
        driver.drawIndexedIndirect(indirectBuffer, 0, 1, 0);
        driver.endRenderPass();
        driver.readPixels(renderTarget, 0, 0, 4, 4,
                PixelBufferDescriptor(pixels.data(), pixels.size(),
                        PixelDataFormat::RGBA, PixelDataType::UBYTE));
        driver.commit(swapChain);
        driver.endFrame(0);
    }

    driver.destroyBufferObject(indirectBuffer);
    driver.destroyProgram(program);
    driver.destroyRenderTarget(renderTarget);
    driver.destroyTexture(texture);
    driver.destroySwapChain(swapChain);
    driver.finish();

    executeCommands();
    getDriver().purge();

    // readPixels flips the image vertically, so the triangle can land anywhere depending on the
    // backend's clip-space convention. Look for any green pixel instead of assuming an orientation.
    bool covered = false;
    for (size_t i = 0; i < pixels.size(); i += 4) {
        covered |= pixels[i + 1] > 127 && pixels[i] < 32 && pixels[i + 2] < 32;
    }
    EXPECT_TRUE(covered) << "The indirect draw did not reach the fragment shader.";
}
