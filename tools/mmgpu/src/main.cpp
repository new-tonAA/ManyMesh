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

/*
 * mmgpu - real Vulkan prototypes for the two runtime pieces Filament's public API cannot
 * express: DAG cluster selection on the GPU and a visibility buffer.
 *
 * The tool builds a ManyMesh DAG, uploads the std430 node table, runs a compute shader that
 * mirrors collectCutAtError, then rasterizes the selected cut into R32_UINT visibility targets.
 * It compares both results against the CPU reference and writes PGM previews.
 */

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif

#include "ShaderSources.h"
#include "VulkanApi.h"

#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/VisibilityBuffer.h>

#include <math/vec3.h>

#include <SPIRV/GlslangToSpv.h>
#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>
#include <glslang/Public/ResourceLimits.h>
#include <glslang/Public/ShaderLang.h>
#if defined(MMGPU_HAS_RENDERDOC)
#include <renderdoc_app.h>
#if defined(_WIN32)
#include <windows.h>
// windows.h still defines these in some SDK configurations and the tool uses them as members.
#ifdef near
#undef near
#endif
#ifdef far
#undef far
#endif
#endif
#endif

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <set>
#include <string>
#include <vector>

namespace mm = filament::manymesh;
namespace math = filament::math;

namespace {

using math::float3;

void fail(char const* message, VkResult result = VK_SUCCESS) {
    std::fprintf(stderr, "mmgpu: %s", message);
    if (result != VK_SUCCESS) {
        std::fprintf(stderr, " (VkResult %d)", int(result));
    }
    std::fprintf(stderr, "\n");
    std::exit(1);
}

void check(VkResult result, char const* message) {
    if (result != VK_SUCCESS) {
        fail(message, result);
    }
}
#if defined(MMGPU_HAS_RENDERDOC)
// Opt-in RenderDoc capture. Launch mmgpu through renderdoccmd (or with the capture layer
// enabled), set MMGPU_RENDERDOC_CAPTURE to the output template, and the whole compute-cut +
// visibility frame is recorded for inspection.
class RenderDocCapture {
public:
    explicit RenderDocCapture(RENDERDOC_DevicePointer device) : mDevice(device) {
        char const* templatePath = std::getenv("MMGPU_RENDERDOC_CAPTURE");
        if (templatePath == nullptr || *templatePath == '\0') {
            return;
        }
#if defined(_WIN32)
        HMODULE module = GetModuleHandleA("renderdoc.dll");
        if (module == nullptr) {
            module = LoadLibraryA("renderdoc.dll");
            mOwnLibrary = module != nullptr;
        }
        if (module == nullptr) {
            std::fprintf(stderr, "renderdoc: renderdoc.dll is not loaded\n");
            return;
        }
        auto getApi = reinterpret_cast<pRENDERDOC_GetAPI>(
                reinterpret_cast<void*>(GetProcAddress(module, "RENDERDOC_GetAPI")));
#else
        void* module = nullptr;
        auto getApi = reinterpret_cast<pRENDERDOC_GetAPI>(nullptr);
#endif
        RENDERDOC_API_1_6_0* api = nullptr;
        if (getApi == nullptr ||
                getApi(eRENDERDOC_API_Version_1_6_0, reinterpret_cast<void**>(&api)) != 1 ||
                api == nullptr) {
            std::fprintf(stderr, "renderdoc: RENDERDOC_GetAPI failed\n");
            return;
        }
        mTemplatePath = templatePath;
        std::filesystem::path const directory = std::filesystem::path(mTemplatePath).parent_path();
        if (!directory.empty()) {
            std::filesystem::create_directories(directory);
        }
        api->SetCaptureFilePathTemplate(mTemplatePath.c_str());
        int major = 0, minor = 0, patch = 0;
        api->GetAPIVersion(&major, &minor, &patch);
        std::printf("renderdoc: API %d.%d.%d, capturing to %s\n", major, minor, patch,
                mTemplatePath.c_str());
        char const* mode = std::getenv("MMGPU_RENDERDOC_MODE");
        bool const startImmediately = mode != nullptr && std::strcmp(mode, "start") == 0;
        if (startImmediately) {
            // Headless Vulkan has no present/frame boundary, so TriggerCapture() alone never
            // starts. StartFrameCapture() is the only way to bracket an explicit compute-only
            // frame; callers that pass windowless=false still get the normal next-frame path.
            std::printf("renderdoc: starting capture immediately...\n");
            std::fflush(stdout);
            api->StartFrameCapture(mDevice, nullptr);
            std::printf("renderdoc: StartFrameCapture returned (active=%u)\n",
                    api->IsFrameCapturing());
        } else {
            std::printf("renderdoc: requesting next frame...\n");
            std::fflush(stdout);
            api->TriggerCapture();
            std::printf("renderdoc: capture requested\n");
        }
        std::fflush(stdout);
        mApi = api;
        mModule = module;
    }

    ~RenderDocCapture() {
        end();
    }

    void end() {
        if (mApi == nullptr) {
            return;
        }
        if (!mApi->IsFrameCapturing()) {
            // TriggerCapture() may still be waiting for a frame boundary. There is nothing to
            // close yet; the next submit (if any) would start the capture. Do not call
            // EndFrameCapture() in that state, it reports an error and can leave a half-written
            // capture behind.
            std::printf("renderdoc: no active capture to end\n");
            std::fflush(stdout);
            mApi = nullptr;
            return;
        }
        std::printf("renderdoc: ending capture...\n");
        std::fflush(stdout);
        uint32_t const captureOk = mApi->EndFrameCapture(mDevice, nullptr);
        std::printf("renderdoc: capture finished (ok=%u)\n", captureOk);
        mApi = nullptr;
#if defined(_WIN32)
        if (mOwnLibrary && mModule != nullptr) {
            FreeLibrary(static_cast<HMODULE>(mModule));
            mModule = nullptr;
        }
#endif
    }

    RenderDocCapture(RenderDocCapture const&) = delete;
    RenderDocCapture& operator=(RenderDocCapture const&) = delete;

private:
    RENDERDOC_DevicePointer mDevice = nullptr;
    RENDERDOC_API_1_6_0* mApi = nullptr;
    void* mModule = nullptr;
    bool mOwnLibrary = false;
    std::string mTemplatePath;
};
#endif

struct Buffer {
    VkBuffer buffer = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0;
    void* mapped = nullptr;
};

struct Image {
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkImageView view = VK_NULL_HANDLE;
    VkFormat format = VK_FORMAT_UNDEFINED;
    uint32_t width = 0;
    uint32_t height = 0;
    VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT;
};

struct Context {
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physicalDevice = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t queueFamily = 0;
    VkCommandPool commandPool = VK_NULL_HANDLE;
    VkPhysicalDeviceMemoryProperties memoryProperties{};
    char deviceName[256] = {};
    bool timestampSupported = false;
    float timestampPeriod = 0.0f;
};

uint32_t findMemoryType(Context const& context, uint32_t typeBits,
        VkMemoryPropertyFlags properties) {
    for (uint32_t i = 0; i < context.memoryProperties.memoryTypeCount; ++i) {
        if ((typeBits & (1u << i)) != 0 && (context.memoryProperties.memoryTypes[i].propertyFlags &
                                                   properties) == properties) {
            return i;
        }
    }
    fail("no memory type matches the requested properties");
    return 0;
}

Buffer createBuffer(Context const& context, VkDeviceSize size, VkBufferUsageFlags usage,
        VkMemoryPropertyFlags properties) {
    Buffer result;
    result.size = size;
    VkBufferCreateInfo info{ VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
    info.size = size;
    info.usage = usage;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    check(mmgpu::api()->CreateBuffer(context.device, &info, nullptr, &result.buffer),
            "vkCreateBuffer failed");

    VkMemoryRequirements requirements{};
    mmgpu::api()->GetBufferMemoryRequirements(context.device, result.buffer, &requirements);
    VkMemoryAllocateInfo allocate{ VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = findMemoryType(context, requirements.memoryTypeBits, properties);
    check(mmgpu::api()->AllocateMemory(context.device, &allocate, nullptr, &result.memory),
            "vkAllocateMemory failed");
    check(mmgpu::api()->BindBufferMemory(context.device, result.buffer, result.memory, 0),
            "vkBindBufferMemory failed");
    if ((properties & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) != 0) {
        check(mmgpu::api()->MapMemory(context.device, result.memory, 0, VK_WHOLE_SIZE, 0,
                      &result.mapped),
                "vkMapMemory failed");
    }
    return result;
}

void destroyBuffer(Context const& context, Buffer* buffer) {
    if (buffer->mapped != nullptr) {
        mmgpu::api()->UnmapMemory(context.device, buffer->memory);
    }
    if (buffer->buffer != VK_NULL_HANDLE) {
        mmgpu::api()->DestroyBuffer(context.device, buffer->buffer, nullptr);
    }
    if (buffer->memory != VK_NULL_HANDLE) {
        mmgpu::api()->FreeMemory(context.device, buffer->memory, nullptr);
    }
    *buffer = {};
}

Image createImage(Context const& context, uint32_t width, uint32_t height, VkFormat format,
        VkImageUsageFlags usage) {
    Image result;
    result.format = format;
    result.width = width;
    result.height = height;
    result.aspect =
            format == VK_FORMAT_D32_SFLOAT ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT;
    VkImageCreateInfo info{ VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO };
    info.imageType = VK_IMAGE_TYPE_2D;
    info.format = format;
    info.extent = { width, height, 1 };
    info.mipLevels = 1;
    info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = usage;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    info.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    check(mmgpu::api()->CreateImage(context.device, &info, nullptr, &result.image),
            "vkCreateImage failed");

    VkMemoryRequirements requirements{};
    mmgpu::api()->GetImageMemoryRequirements(context.device, result.image, &requirements);
    VkMemoryAllocateInfo allocate{ VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = findMemoryType(context, requirements.memoryTypeBits,
            VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    check(mmgpu::api()->AllocateMemory(context.device, &allocate, nullptr, &result.memory),
            "vkAllocateMemory failed for image");
    check(mmgpu::api()->BindImageMemory(context.device, result.image, result.memory, 0),
            "vkBindImageMemory failed");

    VkImageViewCreateInfo view{ VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO };
    view.image = result.image;
    view.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view.format = format;
    view.subresourceRange = { result.aspect, 0, 1, 0, 1 };
    check(mmgpu::api()->CreateImageView(context.device, &view, nullptr, &result.view),
            "vkCreateImageView failed");
    return result;
}

void destroyImage(Context const& context, Image* image) {
    if (image->view != VK_NULL_HANDLE) {
        mmgpu::api()->DestroyImageView(context.device, image->view, nullptr);
    }
    if (image->image != VK_NULL_HANDLE) {
        mmgpu::api()->DestroyImage(context.device, image->image, nullptr);
    }
    if (image->memory != VK_NULL_HANDLE) {
        mmgpu::api()->FreeMemory(context.device, image->memory, nullptr);
    }
    *image = {};
}

VkShaderModule createShaderModule(Context const& context, std::vector<uint32_t> const& spirv) {
    VkShaderModuleCreateInfo info{ VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
    info.codeSize = spirv.size() * sizeof(uint32_t);
    info.pCode = spirv.data();
    VkShaderModule module = VK_NULL_HANDLE;
    check(mmgpu::api()->CreateShaderModule(context.device, &info, nullptr, &module),
            "vkCreateShaderModule failed");
    return module;
}

std::vector<uint32_t> compileGlsl(EShLanguage stage, char const* source, char const* name) {
    glslang::TShader shader(stage);
    shader.setStrings(&source, 1);
    shader.setEnvInput(glslang::EShSourceGlsl, stage, glslang::EShClientVulkan, 100);
    shader.setEnvClient(glslang::EShClientVulkan, glslang::EShTargetVulkan_1_0);
    shader.setEnvTarget(glslang::EShTargetSpv, glslang::EShTargetSpv_1_0);
    if (!shader.parse(GetDefaultResources(), 450, false, EShMsgDefault)) {
        std::fprintf(stderr, "mmgpu: failed to parse %s:\n%s\n%s\n", name, shader.getInfoLog(),
                shader.getInfoDebugLog());
        std::exit(1);
    }
    glslang::TProgram program;
    program.addShader(&shader);
    if (!program.link(EShMsgDefault)) {
        std::fprintf(stderr, "mmgpu: failed to link %s:\n%s\n", name, program.getInfoLog());
        std::exit(1);
    }
    std::vector<uint32_t> spirv;
    glslang::GlslangToSpv(*program.getIntermediate(stage), spirv);
    return spirv;
}

Context createContext(int requestedDevice, bool listDevices) {
    auto* api = mmgpu::api();
    if (!api->loadInstanceFunctions()) {
        fail("cannot load vulkan-1.dll / vkGetInstanceProcAddr");
    }

    VkApplicationInfo application{ VK_STRUCTURE_TYPE_APPLICATION_INFO };
    application.pApplicationName = "mmgpu";
    application.applicationVersion = 1;
    application.pEngineName = "ManyMesh";
    application.engineVersion = 1;
    application.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo instanceInfo{ VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO };
    instanceInfo.pApplicationInfo = &application;

    Context context;
    check(api->CreateInstance(&instanceInfo, nullptr, &context.instance),
            "vkCreateInstance failed");
    if (!api->loadDeviceFunctions(context.instance)) {
        fail("Vulkan loader is missing required entry points");
    }

    uint32_t deviceCount = 0;
    check(api->EnumeratePhysicalDevices(context.instance, &deviceCount, nullptr),
            "vkEnumeratePhysicalDevices failed");
    std::vector<VkPhysicalDevice> devices(deviceCount);
    check(api->EnumeratePhysicalDevices(context.instance, &deviceCount, devices.data()),
            "vkEnumeratePhysicalDevices failed");
    if (devices.empty()) {
        fail("no Vulkan physical devices");
    }

    int selected = -1;
    VkPhysicalDeviceProperties properties{};
    for (uint32_t i = 0; i < devices.size(); ++i) {
        api->GetPhysicalDeviceProperties(devices[i], &properties);
        if (listDevices) {
            std::printf("device %u: %s (api %u.%u.%u)\n", i, properties.deviceName,
                    VK_VERSION_MAJOR(properties.apiVersion),
                    VK_VERSION_MINOR(properties.apiVersion),
                    VK_VERSION_PATCH(properties.apiVersion));
        }
        if (requestedDevice >= 0 && uint32_t(requestedDevice) != i) {
            continue;
        }
        uint32_t familyCount = 0;
        api->GetPhysicalDeviceQueueFamilyProperties(devices[i], &familyCount, nullptr);
        std::vector<VkQueueFamilyProperties> families(familyCount);
        api->GetPhysicalDeviceQueueFamilyProperties(devices[i], &familyCount, families.data());
        for (uint32_t family = 0; family < familyCount; ++family) {
            VkQueueFlags const required = VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT;
            if ((families[family].queueFlags & required) == required) {
                context.physicalDevice = devices[i];
                context.queueFamily = family;
                context.timestampPeriod = properties.limits.timestampPeriod;
                context.timestampSupported = families[family].timestampValidBits != 0 &&
                                             properties.limits.timestampPeriod > 0.0f;
                selected = int(i);
                break;
            }
        }
        if (selected >= 0) {
            break;
        }
    }
    if (listDevices) {
        std::exit(0);
    }
    if (selected < 0) {
        fail("no physical device with a graphics+compute queue");
    }
    api->GetPhysicalDeviceProperties(context.physicalDevice, &properties);
    std::snprintf(context.deviceName, sizeof(context.deviceName), "%s", properties.deviceName);
    api->GetPhysicalDeviceMemoryProperties(context.physicalDevice, &context.memoryProperties);

    float const priority = 1.0f;
    VkDeviceQueueCreateInfo queueInfo{ VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO };
    queueInfo.queueFamilyIndex = context.queueFamily;
    queueInfo.queueCount = 1;
    queueInfo.pQueuePriorities = &priority;
    VkDeviceCreateInfo deviceInfo{ VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
    deviceInfo.queueCreateInfoCount = 1;
    deviceInfo.pQueueCreateInfos = &queueInfo;
    check(api->CreateDevice(context.physicalDevice, &deviceInfo, nullptr, &context.device),
            "vkCreateDevice failed");
    api->GetDeviceQueue(context.device, context.queueFamily, 0, &context.queue);

    VkCommandPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO };
    poolInfo.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    poolInfo.queueFamilyIndex = context.queueFamily;
    check(api->CreateCommandPool(context.device, &poolInfo, nullptr, &context.commandPool),
            "vkCreateCommandPool failed");
    return context;
}

void destroyContext(Context* context) {
    auto* api = mmgpu::api();
    if (context->commandPool != VK_NULL_HANDLE) {
        api->DestroyCommandPool(context->device, context->commandPool, nullptr);
    }
    if (context->device != VK_NULL_HANDLE) {
        api->DestroyDevice(context->device, nullptr);
    }
    if (context->instance != VK_NULL_HANDLE) {
        api->DestroyInstance(context->instance, nullptr);
    }
    *context = {};
}

VkCommandBuffer beginCommands(Context const& context) {
    VkCommandBufferAllocateInfo allocate{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO };
    allocate.commandPool = context.commandPool;
    allocate.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    allocate.commandBufferCount = 1;
    VkCommandBuffer commandBuffer = VK_NULL_HANDLE;
    check(mmgpu::api()->AllocateCommandBuffers(context.device, &allocate, &commandBuffer),
            "vkAllocateCommandBuffers failed");
    VkCommandBufferBeginInfo begin{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check(mmgpu::api()->BeginCommandBuffer(commandBuffer, &begin), "vkBeginCommandBuffer failed");
    return commandBuffer;
}

void submitAndWait(Context const& context, VkCommandBuffer commandBuffer) {
    check(mmgpu::api()->EndCommandBuffer(commandBuffer), "vkEndCommandBuffer failed");
    VkSubmitInfo submit{ VK_STRUCTURE_TYPE_SUBMIT_INFO };
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &commandBuffer;
    check(mmgpu::api()->QueueSubmit(context.queue, 1, &submit, VK_NULL_HANDLE),
            "vkQueueSubmit failed");
    check(mmgpu::api()->QueueWaitIdle(context.queue), "vkQueueWaitIdle failed");
    mmgpu::api()->FreeCommandBuffers(context.device, context.commandPool, 1, &commandBuffer);
}

// Stages that consume the buffers uploaded by the host in this frame. Keeping this exact avoids
// an ALL_COMMANDS barrier, which would also wait for unrelated graphics/transfer work.
constexpr VkPipelineStageFlags kHostUploadReadStages =
        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT |
        VK_PIPELINE_STAGE_VERTEX_INPUT_BIT;

// The compacted index buffer, vertex buffer and indirect command buffer are produced by compute
// and consumed only by the draw's indirect and vertex-input stages.
constexpr VkPipelineStageFlags kComputeOutputReadStages =
        VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT | VK_PIPELINE_STAGE_VERTEX_INPUT_BIT;

void hostBarrier(VkCommandBuffer commandBuffer) {
    VkMemoryBarrier barrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    barrier.srcAccessMask = VK_ACCESS_HOST_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT |
                            VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT | VK_ACCESS_INDEX_READ_BIT |
                            VK_ACCESS_INDIRECT_COMMAND_READ_BIT;
    mmgpu::api()->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_HOST_BIT,
            kHostUploadReadStages, 0, 1, &barrier, 0, nullptr, 0, nullptr);
}

// Two-query timestamp timer. Timestamps are optional in Vulkan: queues may report zero valid
// bits, and some drivers expose the calls but not usable timestamps. In that case the timer
// stays invalid and the caller falls back to wall-clock timing.
class GpuTimer {
public:
    explicit GpuTimer(Context const& context) : mContext(context) {
        if (!context.timestampSupported) {
            return;
        }
        VkQueryPoolCreateInfo info{ VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO };
        info.queryType = VK_QUERY_TYPE_TIMESTAMP;
        info.queryCount = 2;
        if (mmgpu::api()->CreateQueryPool(context.device, &info, nullptr, &mPool) != VK_SUCCESS) {
            mPool = VK_NULL_HANDLE;
        }
    }

    ~GpuTimer() {
        if (mPool != VK_NULL_HANDLE) {
            mmgpu::api()->DestroyQueryPool(mContext.device, mPool, nullptr);
        }
    }

    GpuTimer(GpuTimer const&) = delete;
    GpuTimer& operator=(GpuTimer const&) = delete;

    void reset(VkCommandBuffer commandBuffer) const {
        if (mPool != VK_NULL_HANDLE) {
            mmgpu::api()->CmdResetQueryPool(commandBuffer, mPool, 0, 2);
        }
    }

    void start(VkCommandBuffer commandBuffer, VkPipelineStageFlagBits stage) const {
        if (mPool != VK_NULL_HANDLE) {
            mmgpu::api()->CmdWriteTimestamp(commandBuffer, stage, mPool, 0);
        }
    }

    void end(VkCommandBuffer commandBuffer, VkPipelineStageFlagBits stage) const {
        if (mPool != VK_NULL_HANDLE) {
            mmgpu::api()->CmdWriteTimestamp(commandBuffer, stage, mPool, 1);
        }
    }

    void read() {
        if (mPool == VK_NULL_HANDLE) {
            return;
        }
        uint64_t timestamps[2]{};
        VkResult const result = mmgpu::api()->GetQueryPoolResults(mContext.device, mPool, 0, 2,
                sizeof(timestamps), timestamps, sizeof(uint64_t),
                VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
        if (result == VK_SUCCESS && timestamps[1] >= timestamps[0]) {
            mMilliseconds = double(timestamps[1] - timestamps[0]) *
                            double(mContext.timestampPeriod) / 1.0e6;
            mValid = true;
        }
    }

    bool valid() const noexcept { return mValid; }
    double milliseconds() const noexcept { return mMilliseconds; }

private:
    Context const& mContext;
    VkQueryPool mPool = VK_NULL_HANDLE;
    double mMilliseconds = 0.0;
    bool mValid = false;
};
bool loadMesh(char const* path, mm::Mesh* mesh) {
    Assimp::Importer importer;
    unsigned int const flags = aiProcess_Triangulate | aiProcess_JoinIdenticalVertices |
                               aiProcess_PreTransformVertices;
    aiScene const* scene = importer.ReadFile(path, flags);
    if (scene == nullptr || scene->mNumMeshes == 0) {
        std::fprintf(stderr, "mmgpu: cannot load '%s': %s\n", path, importer.GetErrorString());
        return false;
    }

    size_t vertexCount = 0;
    size_t triangleCount = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        vertexCount += scene->mMeshes[m]->mNumVertices;
        triangleCount += scene->mMeshes[m]->mNumFaces;
    }
    mesh->positions.reserve(vertexCount);
    mesh->indices.reserve(triangleCount * 3);
    mesh->materialIds.reserve(triangleCount);
    mesh->submeshIds.reserve(triangleCount);

    uint32_t vertexOffset = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        aiMesh const* source = scene->mMeshes[m];
        for (unsigned int v = 0; v < source->mNumVertices; ++v) {
            aiVector3D const& p = source->mVertices[v];
            mesh->positions.push_back({ p.x, p.y, p.z });
        }
        for (unsigned int f = 0; f < source->mNumFaces; ++f) {
            aiFace const& face = source->mFaces[f];
            for (unsigned int i = 0; i < face.mNumIndices && i < 3; ++i) {
                mesh->indices.push_back(vertexOffset + face.mIndices[i]);
            }
            mesh->materialIds.push_back(source->mMaterialIndex);
            mesh->submeshIds.push_back(m);
        }
        vertexOffset += source->mNumVertices;
    }
    return true;
}

struct ComputeParams {
    float eye[3];
    float nearPlane;
    float forward[3];
    float farPlane;
    float right[3];
    float tanHalfFov;
    float up[3];
    float aspect;
    float threshold;
    float pixelsPerRadian;
    uint32_t nodeCount;
    uint32_t padding;
};

struct CompactParams {
    uint32_t indexCount;
    uint32_t vertexCount;
    uint32_t mode;
    uint32_t padding;
};

struct VisibilityParams {
    float eye[3];
    float nearPlane;
    float forward[3];
    float farPlane;
    float right[3];
    float tanHalfFov;
    float up[3];
    float aspect;
};

static_assert(sizeof(ComputeParams) == 80, "push constant layout must match lod_select.comp");
static_assert(sizeof(CompactParams) == 16,
        "push constant layout must match the compaction shaders");
static_assert(sizeof(VisibilityParams) == 64, "push constant layout must match the draw shaders");
static_assert(sizeof(mm::GpuLodNode) == 88, "node layout must match ShaderSources.h");

struct CameraBasis {
    float3 forward;
    float3 right;
    float3 up;
    float tanHalfFov = 1.0f;
    float aspect = 1.0f;
    bool valid = false;
};

CameraBasis makeBasis(mm::ViewCamera const& camera) {
    CameraBasis basis;
    float3 const forward = camera.target - camera.eye;
    float const forwardLength = length(forward);
    if (!(forwardLength > 1e-6f)) {
        return basis;
    }
    basis.forward = forward / forwardLength;
    float3 const right = cross(basis.forward, camera.up);
    float const rightLength = length(right);
    if (!(rightLength > 1e-6f)) {
        return basis;
    }
    basis.right = right / rightLength;
    basis.up = cross(basis.right, basis.forward);
    basis.tanHalfFov = std::max(std::tan(camera.fovY * 0.5f), 1e-4f);
    basis.aspect = float(camera.screenWidth) / float(std::max(camera.screenHeight, 1u));
    basis.valid = true;
    return basis;
}

ComputeParams makeComputeParams(mm::ViewCamera const& camera, CameraBasis const& basis,
        float thresholdPx, uint32_t nodeCount) {
    ComputeParams params{};
    params.eye[0] = camera.eye.x;
    params.eye[1] = camera.eye.y;
    params.eye[2] = camera.eye.z;
    params.nearPlane = camera.near;
    params.forward[0] = basis.forward.x;
    params.forward[1] = basis.forward.y;
    params.forward[2] = basis.forward.z;
    params.farPlane = camera.far;
    params.right[0] = basis.right.x;
    params.right[1] = basis.right.y;
    params.right[2] = basis.right.z;
    params.tanHalfFov = basis.tanHalfFov;
    params.up[0] = basis.up.x;
    params.up[1] = basis.up.y;
    params.up[2] = basis.up.z;
    params.aspect = basis.aspect;
    params.threshold = thresholdPx;
    params.pixelsPerRadian = float(camera.screenHeight) / (2.0f * basis.tanHalfFov);
    params.nodeCount = nodeCount;
    return params;
}

float gpuNodeScreenError(mm::GpuLodNode const& node, mm::ViewCamera const& camera,
        CameraBasis const& basis) {
    float const depth = dot(
            float3{ node.boundsCenter[0], node.boundsCenter[1], node.boundsCenter[2] } - camera.eye,
            basis.forward) - node.boundsRadius;
    float const distance = std::max(depth, std::max(camera.near, 1e-6f));
    float const pixelsPerRadian = float(camera.screenHeight) / (2.0f * basis.tanHalfFov);
    return node.accumulatedError / distance * pixelsPerRadian;
}

struct GpuCut {
    std::vector<uint32_t> nodes;
    uint64_t triangles = 0;
    uint64_t culledTriangles = 0;
    double milliseconds = 0.0;
    double selectionGpuMilliseconds = 0.0;
    double setupMilliseconds = 0.0;
    double dispatchMilliseconds = 0.0;
    double readbackMilliseconds = 0.0;
    double vertexCompactionWallMilliseconds = 0.0;
    double vertexCompactionGpuMilliseconds = 0.0;
    double vertexCompactionSetupMilliseconds = 0.0;
    double vertexCompactionDispatchMilliseconds = 0.0;
    // The single-submission path cannot attribute one queue wait to an individual pass. These
    // fields report the shared frame cost; the per-stage GPU timestamps remain in the fields
    // above and in GpuVisibility.
    double frameSetupMilliseconds = 0.0;
    double frameSubmitMilliseconds = 0.0;
    double frameReadbackMilliseconds = 0.0;
    double frameTotalMilliseconds = 0.0;

    // Buffers written by the compute shader. The draw path consumes these directly.
    Buffer compactedIndexBuffer;
    Buffer compactedVertexBuffer;
    Buffer indirectBuffer;
    // Resident caches own these buffers across frames; only a cut that had to allocate its own
    // buffers is responsible for destroying them.
    bool ownsBuffers = true;
    uint32_t compactedIndexCount = 0;
    uint32_t compactedVertexCount = 0;
    uint32_t commandCount = 0;

    // Host-side copies used for validation and reporting. The render path does not need them.
    std::vector<uint32_t> compactedIndices;
    std::vector<mm::GpuDrawIndexedIndirectCommand> commands;
};

void destroyGpuCut(Context const& context, GpuCut* cut) {
    if (!cut->ownsBuffers) {
        cut->compactedIndexBuffer = {};
        cut->compactedVertexBuffer = {};
        cut->indirectBuffer = {};
        return;
    }
    destroyBuffer(context, &cut->indirectBuffer);
    destroyBuffer(context, &cut->compactedVertexBuffer);
    destroyBuffer(context, &cut->compactedIndexBuffer);
}

// Pipelines are immutable for a given device and shader set, but the prototype used to compile
// and create them for every pass. That made a steady-state frame look far more expensive than the
// GPU work it actually submitted. Keep them alive for the process lifetime; buffers, images and
// descriptor sets still follow the per-frame data.
struct GpuPipelineCache {
    struct ComputePass {
        VkDescriptorSetLayout setLayout = VK_NULL_HANDLE;
        VkPipelineLayout layout = VK_NULL_HANDLE;
        VkShaderModule module = VK_NULL_HANDLE;
        VkPipeline pipeline = VK_NULL_HANDLE;
    };
    ComputePass cut;
    ComputePass mark;
    ComputePass gather;
    ComputePass rewrite;

    VkDescriptorSetLayout visibilitySetLayout = VK_NULL_HANDLE;
    VkPipelineLayout visibilityLayout = VK_NULL_HANDLE;
    VkShaderModule visibilityVertex = VK_NULL_HANDLE;
    VkShaderModule visibilityFragment = VK_NULL_HANDLE;
    VkPipeline visibilityPipeline = VK_NULL_HANDLE;
    VkRenderPass visibilityRenderPass = VK_NULL_HANDLE;
};

GpuPipelineCache gPipelines;

void ensureCutPipeline(Context const& context) {
    if (gPipelines.cut.pipeline != VK_NULL_HANDLE) {
        return;
    }
    auto* api = mmgpu::api();
    VkDescriptorSetLayoutBinding bindings[6]{};
    for (uint32_t i = 0; i < 6; ++i) {
        bindings[i].binding = i;
        bindings[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        bindings[i].descriptorCount = 1;
        bindings[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    }
    VkDescriptorSetLayoutCreateInfo setLayoutInfo{
        VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO
    };
    setLayoutInfo.bindingCount = 6;
    setLayoutInfo.pBindings = bindings;
    check(api->CreateDescriptorSetLayout(context.device, &setLayoutInfo, nullptr,
                  &gPipelines.cut.setLayout),
            "vkCreateDescriptorSetLayout failed");

    VkPushConstantRange range{};
    range.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    range.offset = 0;
    range.size = sizeof(ComputeParams);
    VkPipelineLayoutCreateInfo pipelineLayoutInfo{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &gPipelines.cut.setLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &range;
    check(api->CreatePipelineLayout(context.device, &pipelineLayoutInfo, nullptr,
                  &gPipelines.cut.layout),
            "vkCreatePipelineLayout failed");

    std::vector<uint32_t> const spirv =
            compileGlsl(EShLangCompute, mmgpu::LOD_SELECT_GLSL, "lod_select");
    gPipelines.cut.module = createShaderModule(context, spirv);
    VkComputePipelineCreateInfo pipelineInfo{ VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO };
    pipelineInfo.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    pipelineInfo.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    pipelineInfo.stage.module = gPipelines.cut.module;
    pipelineInfo.stage.pName = "main";
    pipelineInfo.layout = gPipelines.cut.layout;
    check(api->CreateComputePipelines(context.device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr,
                  &gPipelines.cut.pipeline),
            "vkCreateComputePipelines failed");
}

void ensureCompactionPipelines(Context const& context) {
    if (gPipelines.rewrite.pipeline != VK_NULL_HANDLE) {
        return;
    }
    auto* api = mmgpu::api();
    auto makeSetLayout = [&](uint32_t bindingCount, VkDescriptorSetLayout* layout) {
        VkDescriptorSetLayoutBinding bindings[4]{};
        for (uint32_t i = 0; i < bindingCount; ++i) {
            bindings[i].binding = i;
            bindings[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
            bindings[i].descriptorCount = 1;
            bindings[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        }
        VkDescriptorSetLayoutCreateInfo info{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO };
        info.bindingCount = bindingCount;
        info.pBindings = bindings;
        check(api->CreateDescriptorSetLayout(context.device, &info, nullptr, layout),
                "vkCreateDescriptorSetLayout (compaction) failed");
    };
    makeSetLayout(4, &gPipelines.mark.setLayout);
    makeSetLayout(4, &gPipelines.gather.setLayout);
    makeSetLayout(2, &gPipelines.rewrite.setLayout);

    auto makePipelineLayout = [&](VkDescriptorSetLayout setLayout, VkPipelineLayout* layout) {
        VkPushConstantRange range{};
        range.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        range.offset = 0;
        range.size = sizeof(CompactParams);
        VkPipelineLayoutCreateInfo info{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
        info.setLayoutCount = 1;
        info.pSetLayouts = &setLayout;
        info.pushConstantRangeCount = 1;
        info.pPushConstantRanges = &range;
        check(api->CreatePipelineLayout(context.device, &info, nullptr, layout),
                "vkCreatePipelineLayout (compaction) failed");
    };
    makePipelineLayout(gPipelines.mark.setLayout, &gPipelines.mark.layout);
    makePipelineLayout(gPipelines.gather.setLayout, &gPipelines.gather.layout);
    makePipelineLayout(gPipelines.rewrite.setLayout, &gPipelines.rewrite.layout);

    auto makePipeline = [&](char const* glsl, char const* name, GpuPipelineCache::ComputePass* pass) {
        std::vector<uint32_t> const spirv = compileGlsl(EShLangCompute, glsl, name);
        pass->module = createShaderModule(context, spirv);
        VkComputePipelineCreateInfo info{ VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO };
        info.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        info.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        info.stage.module = pass->module;
        info.stage.pName = "main";
        info.layout = pass->layout;
        check(api->CreateComputePipelines(context.device, VK_NULL_HANDLE, 1, &info, nullptr,
                      &pass->pipeline),
                "vkCreateComputePipelines (compaction) failed");
    };
    makePipeline(mmgpu::COMPACT_MARK_GLSL, "compact_mark", &gPipelines.mark);
    makePipeline(mmgpu::COMPACT_GATHER_GLSL, "compact_gather", &gPipelines.gather);
    makePipeline(mmgpu::COMPACT_REWRITE_GLSL, "compact_rewrite", &gPipelines.rewrite);
}

void ensureVisibilityPipeline(Context const& context, uint32_t width, uint32_t height) {
    if (gPipelines.visibilityPipeline != VK_NULL_HANDLE) {
        return;
    }
    auto* api = mmgpu::api();

    VkAttachmentDescription attachments[3]{};
    for (uint32_t i = 0; i < 2; ++i) {
        attachments[i].format = VK_FORMAT_R32_UINT;
        attachments[i].samples = VK_SAMPLE_COUNT_1_BIT;
        attachments[i].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
        attachments[i].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
        attachments[i].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
        attachments[i].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
        attachments[i].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        attachments[i].finalLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    }
    attachments[2].format = VK_FORMAT_D32_SFLOAT;
    attachments[2].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[2].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[2].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[2].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[2].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[2].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[2].finalLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    VkAttachmentReference colorRefs[2] = {
        { 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL },
        { 1, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL },
    };
    VkAttachmentReference depthRef{ 2, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL };
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 2;
    subpass.pColorAttachments = colorRefs;
    subpass.pDepthStencilAttachment = &depthRef;
    VkSubpassDependency dependencies[2]{};
    dependencies[0].srcSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[0].dstSubpass = 0;
    dependencies[0].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                                   VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    dependencies[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                                   VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
                                   VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    dependencies[0].dstAccessMask =
            VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    dependencies[1].srcSubpass = 0;
    dependencies[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                                   VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    dependencies[1].dstStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    dependencies[1].srcAccessMask =
            VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    dependencies[1].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    VkRenderPassCreateInfo renderPassInfo{ VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO };
    renderPassInfo.attachmentCount = 3;
    renderPassInfo.pAttachments = attachments;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;
    renderPassInfo.dependencyCount = 2;
    renderPassInfo.pDependencies = dependencies;
    check(api->CreateRenderPass(context.device, &renderPassInfo, nullptr,
                  &gPipelines.visibilityRenderPass),
            "vkCreateRenderPass failed");

    std::vector<uint32_t> const vertexSpirv =
            compileGlsl(EShLangVertex, mmgpu::VISIBILITY_VERT_GLSL, "visibility.vert");
    std::vector<uint32_t> const fragmentSpirv =
            compileGlsl(EShLangFragment, mmgpu::VISIBILITY_FRAG_GLSL, "visibility.frag");
    gPipelines.visibilityVertex = createShaderModule(context, vertexSpirv);
    gPipelines.visibilityFragment = createShaderModule(context, fragmentSpirv);

    VkDescriptorSetLayoutBinding nodeBinding{};
    nodeBinding.binding = 0;
    nodeBinding.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    nodeBinding.descriptorCount = 1;
    nodeBinding.stageFlags = VK_SHADER_STAGE_VERTEX_BIT;
    VkDescriptorSetLayoutCreateInfo setLayoutInfo{
        VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO
    };
    setLayoutInfo.bindingCount = 1;
    setLayoutInfo.pBindings = &nodeBinding;
    check(api->CreateDescriptorSetLayout(context.device, &setLayoutInfo, nullptr,
                  &gPipelines.visibilitySetLayout),
            "vkCreateDescriptorSetLayout failed");

    VkPushConstantRange pushRange{};
    pushRange.stageFlags = VK_SHADER_STAGE_VERTEX_BIT;
    pushRange.offset = 0;
    pushRange.size = sizeof(VisibilityParams);
    VkPipelineLayoutCreateInfo pipelineLayoutInfo{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &gPipelines.visibilitySetLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &pushRange;
    check(api->CreatePipelineLayout(context.device, &pipelineLayoutInfo, nullptr,
                  &gPipelines.visibilityLayout),
            "vkCreatePipelineLayout failed");

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = gPipelines.visibilityVertex;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = gPipelines.visibilityFragment;
    stages[1].pName = "main";

    VkVertexInputBindingDescription binding{ 0, sizeof(float3), VK_VERTEX_INPUT_RATE_VERTEX };
    VkVertexInputAttributeDescription attribute{ 0, 0, VK_FORMAT_R32G32B32_SFLOAT, 0 };
    VkPipelineVertexInputStateCreateInfo vertexInput{
        VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO
    };
    vertexInput.vertexBindingDescriptionCount = 1;
    vertexInput.pVertexBindingDescriptions = &binding;
    vertexInput.vertexAttributeDescriptionCount = 1;
    vertexInput.pVertexAttributeDescriptions = &attribute;
    VkPipelineInputAssemblyStateCreateInfo inputAssembly{
        VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO
    };
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport viewport{ 0.0f, 0.0f, float(width), float(height), 0.0f, 1.0f };
    VkRect2D scissor{ { 0, 0 }, { width, height } };
    VkPipelineViewportStateCreateInfo viewportState{
        VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO
    };
    viewportState.viewportCount = 1;
    viewportState.pViewports = &viewport;
    viewportState.scissorCount = 1;
    viewportState.pScissors = &scissor;
    VkPipelineRasterizationStateCreateInfo rasterization{
        VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO
    };
    rasterization.polygonMode = VK_POLYGON_MODE_FILL;
    rasterization.cullMode = VK_CULL_MODE_NONE;
    rasterization.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterization.lineWidth = 1.0f;
    VkPipelineMultisampleStateCreateInfo multisample{
        VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO
    };
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    VkPipelineDepthStencilStateCreateInfo depthState{
        VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO
    };
    depthState.depthTestEnable = VK_TRUE;
    depthState.depthWriteEnable = VK_TRUE;
    depthState.depthCompareOp = VK_COMPARE_OP_LESS_OR_EQUAL;
    VkPipelineColorBlendAttachmentState blendAttachments[2]{};
    for (auto& blend: blendAttachments) {
        blend.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                               VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    }
    VkPipelineColorBlendStateCreateInfo blendState{
        VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO
    };
    blendState.attachmentCount = 2;
    blendState.pAttachments = blendAttachments;

    VkGraphicsPipelineCreateInfo pipelineInfo{ VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = stages;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterization;
    pipelineInfo.pMultisampleState = &multisample;
    pipelineInfo.pDepthStencilState = &depthState;
    pipelineInfo.pColorBlendState = &blendState;
    pipelineInfo.layout = gPipelines.visibilityLayout;
    pipelineInfo.renderPass = gPipelines.visibilityRenderPass;
    pipelineInfo.subpass = 0;
    check(api->CreateGraphicsPipelines(context.device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr,
                  &gPipelines.visibilityPipeline),
            "vkCreateGraphicsPipelines failed");
}

void destroyGpuPipelineCache(Context const& context) {
    auto* api = mmgpu::api();
    auto destroyPass = [&](GpuPipelineCache::ComputePass* pass) {
        if (pass->pipeline != VK_NULL_HANDLE) {
            api->DestroyPipeline(context.device, pass->pipeline, nullptr);
        }
        if (pass->module != VK_NULL_HANDLE) {
            api->DestroyShaderModule(context.device, pass->module, nullptr);
        }
        if (pass->layout != VK_NULL_HANDLE) {
            api->DestroyPipelineLayout(context.device, pass->layout, nullptr);
        }
        if (pass->setLayout != VK_NULL_HANDLE) {
            api->DestroyDescriptorSetLayout(context.device, pass->setLayout, nullptr);
        }
        *pass = {};
    };
    destroyPass(&gPipelines.cut);
    destroyPass(&gPipelines.mark);
    destroyPass(&gPipelines.gather);
    destroyPass(&gPipelines.rewrite);
    if (gPipelines.visibilityPipeline != VK_NULL_HANDLE) {
        api->DestroyPipeline(context.device, gPipelines.visibilityPipeline, nullptr);
    }
    if (gPipelines.visibilityVertex != VK_NULL_HANDLE) {
        api->DestroyShaderModule(context.device, gPipelines.visibilityVertex, nullptr);
    }
    if (gPipelines.visibilityFragment != VK_NULL_HANDLE) {
        api->DestroyShaderModule(context.device, gPipelines.visibilityFragment, nullptr);
    }
    if (gPipelines.visibilityLayout != VK_NULL_HANDLE) {
        api->DestroyPipelineLayout(context.device, gPipelines.visibilityLayout, nullptr);
    }
    if (gPipelines.visibilitySetLayout != VK_NULL_HANDLE) {
        api->DestroyDescriptorSetLayout(context.device, gPipelines.visibilitySetLayout, nullptr);
    }
    if (gPipelines.visibilityRenderPass != VK_NULL_HANDLE) {
        api->DestroyRenderPass(context.device, gPipelines.visibilityRenderPass, nullptr);
    }
    gPipelines = {};
}

// The cut pass used to create and free six buffers plus a descriptor pool every frame. Their
// sizes only depend on the mesh, so keep them resident and refresh the few per-frame counters.
struct CutResources {
    void const* owner = nullptr;
    uint32_t nodeCount = 0;
    size_t indexCount = 0;
    uint32_t generation = 0;
    Buffer nodes;
    Buffer selected;
    Buffer counters;
    Buffer sourceIndices;
    Buffer compactedIndices;
    Buffer indirect;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
};

CutResources gCutResources;
uint32_t gCutResourceGeneration = 0;

void resetCutResources(Context const& context) {
    auto* api = mmgpu::api();
    if (gCutResources.descriptorPool != VK_NULL_HANDLE) {
        api->DestroyDescriptorPool(context.device, gCutResources.descriptorPool, nullptr);
    }
    destroyBuffer(context, &gCutResources.indirect);
    destroyBuffer(context, &gCutResources.compactedIndices);
    destroyBuffer(context, &gCutResources.sourceIndices);
    destroyBuffer(context, &gCutResources.counters);
    destroyBuffer(context, &gCutResources.selected);
    destroyBuffer(context, &gCutResources.nodes);
    gCutResources = {};
}

void ensureCutResources(Context const& context, mm::GpuLodBuffer const& buffer) {
    auto* api = mmgpu::api();
    uint32_t const nodeCount = uint32_t(buffer.nodes.size());
    size_t const indexCount = buffer.indices.size();
    bool const resident = gCutResources.descriptorSet != VK_NULL_HANDLE &&
            gCutResources.owner == &buffer && gCutResources.nodeCount >= nodeCount &&
            gCutResources.indexCount >= indexCount;
    if (resident) {
        return;
    }
    resetCutResources(context);
    gCutResources.owner = &buffer;
    gCutResources.generation = ++gCutResourceGeneration;
    gCutResources.nodeCount = std::max(nodeCount, 1u);
    gCutResources.indexCount = std::max<size_t>(indexCount, 1);
    gCutResources.nodes = createBuffer(context,
            VkDeviceSize(gCutResources.nodeCount) * sizeof(mm::GpuLodNode),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCutResources.selected = createBuffer(context,
            VkDeviceSize(gCutResources.nodeCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCutResources.counters = createBuffer(context, 5u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCutResources.sourceIndices = createBuffer(context,
            VkDeviceSize(gCutResources.indexCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCutResources.compactedIndices = createBuffer(context,
            VkDeviceSize(gCutResources.indexCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCutResources.indirect = createBuffer(context,
            VkDeviceSize(gCutResources.nodeCount) * sizeof(mm::GpuDrawIndexedIndirectCommand),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

    std::memcpy(gCutResources.nodes.mapped, buffer.nodes.data(),
            size_t(nodeCount) * sizeof(mm::GpuLodNode));
    std::memcpy(gCutResources.sourceIndices.mapped, buffer.indices.data(),
            indexCount * sizeof(uint32_t));

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 6 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 1;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr,
                  &gCutResources.descriptorPool),
            "vkCreateDescriptorPool failed");
    VkDescriptorSetAllocateInfo allocateInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    allocateInfo.descriptorPool = gCutResources.descriptorPool;
    allocateInfo.descriptorSetCount = 1;
    allocateInfo.pSetLayouts = &gPipelines.cut.setLayout;
    check(api->AllocateDescriptorSets(context.device, &allocateInfo,
                  &gCutResources.descriptorSet),
            "vkAllocateDescriptorSets failed");

    VkDescriptorBufferInfo bufferInfos[6] = {
        { gCutResources.nodes.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.selected.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.counters.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.sourceIndices.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.compactedIndices.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.indirect.buffer, 0, VK_WHOLE_SIZE },
    };
    VkWriteDescriptorSet writes[6]{};
    for (uint32_t i = 0; i < 6; ++i) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = gCutResources.descriptorSet;
        writes[i].dstBinding = i;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        writes[i].pBufferInfo = &bufferInfos[i];
    }
    api->UpdateDescriptorSets(context.device, 6, writes, 0, nullptr);
}

GpuCut selectOnGpu(Context const& context, mm::GpuLodBuffer const& buffer,
        ComputeParams const& params) {
    auto* api = mmgpu::api();
    GpuCut result;
    auto const setupStart = std::chrono::steady_clock::now();
    uint32_t const nodeCount = uint32_t(buffer.nodes.size());
    if (nodeCount == 0) {
        return result;
    }

    ensureCutPipeline(context);
    ensureCutResources(context, buffer);
    Buffer& nodeBuffer = gCutResources.nodes;
    Buffer& selectedBuffer = gCutResources.selected;
    Buffer& counterBuffer = gCutResources.counters;
    Buffer& sourceIndexBuffer = gCutResources.sourceIndices;
    Buffer& compactedIndexBuffer = gCutResources.compactedIndices;
    Buffer& indirectBuffer = gCutResources.indirect;
    std::memset(selectedBuffer.mapped, 0, VkDeviceSize(nodeCount) * sizeof(uint32_t));
    std::memset(counterBuffer.mapped, 0, 5u * sizeof(uint32_t));
    std::memset(indirectBuffer.mapped, 0,
            VkDeviceSize(nodeCount) * sizeof(mm::GpuDrawIndexedIndirectCommand));

    VkDescriptorSet const descriptorSet = gCutResources.descriptorSet;
    VkPipelineLayout const pipelineLayout = gPipelines.cut.layout;
    VkPipeline const pipeline = gPipelines.cut.pipeline;

    auto const start = std::chrono::steady_clock::now();
    result.setupMilliseconds =
            std::chrono::duration<double, std::milli>(start - setupStart).count();
    GpuTimer timer(context);
    VkCommandBuffer commandBuffer = beginCommands(context);
    timer.reset(commandBuffer);
    hostBarrier(commandBuffer);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipelineLayout, 0, 1,
            &descriptorSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, pipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
            sizeof(ComputeParams), &params);
    timer.start(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    api->CmdDispatch(commandBuffer, (nodeCount + 63u) / 64u, 1, 1);
    timer.end(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    VkMemoryBarrier readbackBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    readbackBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readbackBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &readbackBarrier, 0, nullptr, 0, nullptr);
    submitAndWait(context, commandBuffer);
    auto const dispatchEnd = std::chrono::steady_clock::now();
    result.dispatchMilliseconds =
            std::chrono::duration<double, std::milli>(dispatchEnd - start).count();
    auto const end = std::chrono::steady_clock::now();
    result.milliseconds = std::chrono::duration<double, std::milli>(end - start).count();
    result.readbackMilliseconds =
            std::chrono::duration<double, std::milli>(end - dispatchEnd).count();
    timer.read();
    if (timer.valid()) {
        result.selectionGpuMilliseconds = timer.milliseconds();
    }

    uint32_t const* counters = static_cast<uint32_t const*>(counterBuffer.mapped);
    uint32_t const selectedCount = std::min(counters[0], nodeCount);
    uint32_t const* selected = static_cast<uint32_t const*>(selectedBuffer.mapped);
    result.nodes.assign(selected, selected + selectedCount);
    std::sort(result.nodes.begin(), result.nodes.end());
    result.triangles = counters[1];
    result.culledTriangles = counters[2];
    result.compactedIndexCount = std::min(counters[3], uint32_t(buffer.indices.size()));
    result.commandCount = std::min(counters[4], selectedCount);

    uint32_t const* compacted = static_cast<uint32_t const*>(compactedIndexBuffer.mapped);
    result.compactedIndices.assign(compacted, compacted + result.compactedIndexCount);
    auto const* commands =
            static_cast<mm::GpuDrawIndexedIndirectCommand const*>(indirectBuffer.mapped);
    result.commands.assign(commands, commands + result.commandCount);
    result.compactedIndexBuffer = compactedIndexBuffer;
    result.indirectBuffer = indirectBuffer;
    result.ownsBuffers = false;
    return result;
}

// Vertex-compaction buffers follow the same lifetime as the cut buffers: once per mesh, not
// once per frame. Only the caches are recomputed on every cut.
struct CompactionResources {
    void const* owner = nullptr;
    uint32_t vertexCount = 0;
    uint32_t cutGeneration = 0;
    Buffer sourcePositions;
    Buffer vertexMap;
    Buffer compactedPositions;
    Buffer counters;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    VkDescriptorSet markSet = VK_NULL_HANDLE;
    VkDescriptorSet gatherSet = VK_NULL_HANDLE;
    VkDescriptorSet rewriteSet = VK_NULL_HANDLE;
};

CompactionResources gCompactionResources;

void resetCompactionResources(Context const& context) {
    auto* api = mmgpu::api();
    if (gCompactionResources.descriptorPool != VK_NULL_HANDLE) {
        api->DestroyDescriptorPool(context.device, gCompactionResources.descriptorPool, nullptr);
    }
    destroyBuffer(context, &gCompactionResources.counters);
    destroyBuffer(context, &gCompactionResources.compactedPositions);
    destroyBuffer(context, &gCompactionResources.vertexMap);
    destroyBuffer(context, &gCompactionResources.sourcePositions);
    gCompactionResources = {};
}

void ensureCompactionResources(Context const& context, mm::Mesh const& mesh) {
    auto* api = mmgpu::api();
    uint32_t const vertexCount = uint32_t(mesh.positions.size());
    bool const resident = gCompactionResources.rewriteSet != VK_NULL_HANDLE &&
            gCompactionResources.owner == &mesh &&
            gCompactionResources.vertexCount >= vertexCount &&
            gCompactionResources.cutGeneration == gCutResources.generation;
    if (resident) {
        return;
    }
    resetCompactionResources(context);
    gCompactionResources.owner = &mesh;
    gCompactionResources.vertexCount = std::max(vertexCount, 1u);
    gCompactionResources.cutGeneration = gCutResources.generation;
    VkDeviceSize const positionBytes =
            VkDeviceSize(gCompactionResources.vertexCount) * sizeof(float3);
    gCompactionResources.sourcePositions = createBuffer(context, positionBytes,
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCompactionResources.vertexMap = createBuffer(context,
            VkDeviceSize(gCompactionResources.vertexCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCompactionResources.compactedPositions = createBuffer(context, positionBytes,
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    gCompactionResources.counters = createBuffer(context, 2u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(gCompactionResources.sourcePositions.mapped, mesh.positions.data(),
            size_t(vertexCount) * sizeof(float3));

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 10 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 3;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr,
                  &gCompactionResources.descriptorPool),
            "vkCreateDescriptorPool (compaction) failed");

    auto allocateSet = [&](VkDescriptorSetLayout layout, VkDescriptorSet* set) {
        VkDescriptorSetAllocateInfo allocate{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
        allocate.descriptorPool = gCompactionResources.descriptorPool;
        allocate.descriptorSetCount = 1;
        allocate.pSetLayouts = &layout;
        check(api->AllocateDescriptorSets(context.device, &allocate, set),
                "vkAllocateDescriptorSets (compaction) failed");
    };
    allocateSet(gPipelines.mark.setLayout, &gCompactionResources.markSet);
    allocateSet(gPipelines.gather.setLayout, &gCompactionResources.gatherSet);
    allocateSet(gPipelines.rewrite.setLayout, &gCompactionResources.rewriteSet);

    auto updateSet = [&](VkDescriptorSet set, VkDescriptorBufferInfo* infos, uint32_t count) {
        VkWriteDescriptorSet writes[4]{};
        for (uint32_t i = 0; i < count; ++i) {
            writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
            writes[i].dstSet = set;
            writes[i].dstBinding = i;
            writes[i].descriptorCount = 1;
            writes[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
            writes[i].pBufferInfo = &infos[i];
        }
        api->UpdateDescriptorSets(context.device, count, writes, 0, nullptr);
    };
    VkDescriptorBufferInfo markInfos[4] = {
        { gCutResources.compactedIndices.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.counters.buffer, 0, VK_WHOLE_SIZE },
        { gCutResources.counters.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(gCompactionResources.markSet, markInfos, 4);
    VkDescriptorBufferInfo gatherInfos[4] = {
        { gCompactionResources.vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.sourcePositions.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.compactedPositions.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.counters.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(gCompactionResources.gatherSet, gatherInfos, 4);
    VkDescriptorBufferInfo rewriteInfos[2] = {
        { gCutResources.compactedIndices.buffer, 0, VK_WHOLE_SIZE },
        { gCompactionResources.vertexMap.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(gCompactionResources.rewriteSet, rewriteInfos, 2);
}

void compactVerticesOnGpu(Context const& context, mm::Mesh const& mesh, GpuCut* cut) {
    auto* api = mmgpu::api();
    auto const wallStart = std::chrono::steady_clock::now();
    uint32_t const sourceVertexCount = uint32_t(mesh.positions.size());
    uint32_t const indexCount = cut->compactedIndexCount;
    if (indexCount == 0 || sourceVertexCount == 0 ||
            cut->compactedIndexBuffer.buffer == VK_NULL_HANDLE) {
        return;
    }

    ensureCompactionPipelines(context);
    ensureCompactionResources(context, mesh);
    Buffer& vertexMap = gCompactionResources.vertexMap;
    Buffer& compactedPositions = gCompactionResources.compactedPositions;
    Buffer& counter = gCompactionResources.counters;
    std::memset(vertexMap.mapped, 0xFF, size_t(sourceVertexCount) * sizeof(uint32_t));
    std::memset(counter.mapped, 0, 2u * sizeof(uint32_t));
    VkDescriptorSet const markSet = gCompactionResources.markSet;
    VkDescriptorSet const gatherSet = gCompactionResources.gatherSet;
    VkDescriptorSet const rewriteSet = gCompactionResources.rewriteSet;

    VkPipeline const markPipeline = gPipelines.mark.pipeline;
    VkPipeline const gatherPipeline = gPipelines.gather.pipeline;
    VkPipeline const rewritePipeline = gPipelines.rewrite.pipeline;
    VkPipelineLayout const markPipelineLayout = gPipelines.mark.layout;
    VkPipelineLayout const gatherPipelineLayout = gPipelines.gather.layout;
    VkPipelineLayout const rewritePipelineLayout = gPipelines.rewrite.layout;

    auto const setupEnd = std::chrono::steady_clock::now();
    cut->vertexCompactionSetupMilliseconds =
            std::chrono::duration<double, std::milli>(setupEnd - wallStart).count();
    CompactParams params{};
    params.indexCount = indexCount;
    params.vertexCount = sourceVertexCount;
    GpuTimer timer(context);
    VkCommandBuffer commandBuffer = beginCommands(context);
    timer.reset(commandBuffer);
    hostBarrier(commandBuffer);

    auto barrier = [&](VkAccessFlags src, VkAccessFlags dst) {
        VkMemoryBarrier memoryBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
        memoryBarrier.srcAccessMask = src;
        memoryBarrier.dstAccessMask = dst;
        api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &memoryBarrier, 0, nullptr, 0, nullptr);
    };
    auto dispatch = [&](VkPipeline pipeline, VkPipelineLayout layout, VkDescriptorSet set,
                            uint32_t workItems) {
        api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
        api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1,
                &set, 0, nullptr);
        api->CmdPushConstants(commandBuffer, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
                sizeof(CompactParams), &params);
        api->CmdDispatch(commandBuffer, (workItems + 63u) / 64u, 1, 1);
    };
    timer.start(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    params.mode = 0;
    dispatch(markPipeline, markPipelineLayout, markSet, indexCount);
    barrier(VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT);
    params.mode = 1;
    dispatch(gatherPipeline, gatherPipelineLayout, gatherSet, sourceVertexCount);
    barrier(VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT);
    params.mode = 2;
    dispatch(rewritePipeline, rewritePipelineLayout, rewriteSet, indexCount);
    timer.end(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);

    VkMemoryBarrier readbackBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    readbackBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readbackBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &readbackBarrier, 0, nullptr, 0, nullptr);
    submitAndWait(context, commandBuffer);
    auto const dispatchEnd = std::chrono::steady_clock::now();
    cut->vertexCompactionDispatchMilliseconds =
            std::chrono::duration<double, std::milli>(dispatchEnd - setupEnd).count();
    timer.read();
    auto const wallEnd = std::chrono::steady_clock::now();
    cut->vertexCompactionWallMilliseconds =
            std::chrono::duration<double, std::milli>(wallEnd - wallStart).count();
    if (timer.valid()) {
        cut->vertexCompactionGpuMilliseconds = timer.milliseconds();
    }

    uint32_t const* counts = static_cast<uint32_t const*>(counter.mapped);
    uint32_t const compactedCount = std::min(counts[1], sourceVertexCount);
    if (counts[0] != counts[1]) {
        std::fprintf(stderr, "mmgpu: GPU vertex compaction marked %u but assigned %u\n", counts[0],
                counts[1]);
    }
    auto const* rewritten = static_cast<uint32_t const*>(cut->compactedIndexBuffer.mapped);
    for (uint32_t i = 0; i < indexCount; ++i) {
        if (rewritten[i] >= compactedCount) {
            std::fprintf(stderr,
                    "mmgpu: GPU vertex compaction produced index %u >= vertex count %u\n",
                    rewritten[i], compactedCount);
            break;
        }
    }
    // selectOnGpu() read the buffer before this pass rewrote it in place. Refresh the host copy
    // so the legacy A/B path reports the same dense indices the draw actually consumes.
    cut->compactedIndices.assign(rewritten, rewritten + indexCount);
    cut->compactedVertexCount = compactedCount;
    cut->compactedVertexBuffer = compactedPositions;

}

struct GpuVisibility {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint32_t> nodeIds;
    std::vector<uint32_t> triangleIds;
    std::vector<float> depth;
    uint32_t coveredPixels = 0;
    uint32_t drawCommands = 0;
    double gpuDrawMilliseconds = 0.0;
    double wallMilliseconds = 0.0;
    double setupMilliseconds = 0.0;
    double readbackMilliseconds = 0.0;
};

// A shipped renderer allocates the visibility attachments, framebuffer and readback targets
// once and reuses them across frames. The prototype used to create and destroy all of them per
// frame, which made the CPU-side setup dominate the sub-millisecond GPU work. Keep them alive
// for the lifetime of the process, keyed by the viewport size.
struct VisibilityResources {
    uint32_t width = 0;
    uint32_t height = 0;
    Image color0;
    Image color1;
    Image depth;
    VkFramebuffer framebuffer = VK_NULL_HANDLE;
    Buffer nodeReadback;
    Buffer triangleReadback;
    Buffer depthReadback;
    Buffer nodeData;
    VkDeviceSize nodeDataBytes = 0;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
};

VisibilityResources gVisibilityResources;

void resetVisibilityResources(Context const& context) {
    auto* api = mmgpu::api();
    if (gVisibilityResources.descriptorPool != VK_NULL_HANDLE) {
        api->DestroyDescriptorPool(context.device, gVisibilityResources.descriptorPool, nullptr);
    }
    if (gVisibilityResources.framebuffer != VK_NULL_HANDLE) {
        api->DestroyFramebuffer(context.device, gVisibilityResources.framebuffer, nullptr);
    }
    destroyBuffer(context, &gVisibilityResources.depthReadback);
    destroyBuffer(context, &gVisibilityResources.triangleReadback);
    destroyBuffer(context, &gVisibilityResources.nodeReadback);
    destroyBuffer(context, &gVisibilityResources.nodeData);
    destroyImage(context, &gVisibilityResources.depth);
    destroyImage(context, &gVisibilityResources.color1);
    destroyImage(context, &gVisibilityResources.color0);
    gVisibilityResources = {};
}

// Allocate the visibility attachments, framebuffer, readback targets and the node descriptor
// once the viewport size is known, then keep them alive so that steady-state frames only record
// and submit commands.
void ensureVisibilityResources(Context const& context, uint32_t width, uint32_t height,
        mm::GpuLodBuffer const& buffer) {
    auto* api = mmgpu::api();
    if (gVisibilityResources.width != width || gVisibilityResources.height != height) {
        resetVisibilityResources(context);
        gVisibilityResources.width = width;
        gVisibilityResources.height = height;
        size_t const pixelCount = size_t(width) * height;
        gVisibilityResources.color0 = createImage(context, width, height, VK_FORMAT_R32_UINT,
                VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
        gVisibilityResources.color1 = createImage(context, width, height, VK_FORMAT_R32_UINT,
                VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
        gVisibilityResources.depth = createImage(context, width, height, VK_FORMAT_D32_SFLOAT,
                VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT |
                        VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
        gVisibilityResources.nodeReadback = createBuffer(context,
                VkDeviceSize(pixelCount) * sizeof(uint32_t), VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        gVisibilityResources.triangleReadback = createBuffer(context,
                VkDeviceSize(pixelCount) * sizeof(uint32_t), VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        gVisibilityResources.depthReadback = createBuffer(context,
                VkDeviceSize(pixelCount) * sizeof(float), VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

        ensureVisibilityPipeline(context, width, height);
        VkImageView views[3] = { gVisibilityResources.color0.view,
            gVisibilityResources.color1.view, gVisibilityResources.depth.view };
        VkFramebufferCreateInfo framebufferInfo{ VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO };
        framebufferInfo.renderPass = gPipelines.visibilityRenderPass;
        framebufferInfo.attachmentCount = 3;
        framebufferInfo.pAttachments = views;
        framebufferInfo.width = width;
        framebufferInfo.height = height;
        framebufferInfo.layers = 1;
        check(api->CreateFramebuffer(context.device, &framebufferInfo, nullptr,
                      &gVisibilityResources.framebuffer),
                "vkCreateFramebuffer failed");
    }

    VkDeviceSize const nodeBytes =
            VkDeviceSize(buffer.nodes.size()) * sizeof(mm::GpuLodNode);
    bool recreateNodeData = gVisibilityResources.nodeData.buffer == VK_NULL_HANDLE ||
            nodeBytes > gVisibilityResources.nodeDataBytes;
    if (recreateNodeData) {
        destroyBuffer(context, &gVisibilityResources.nodeData);
        gVisibilityResources.nodeDataBytes = std::max<VkDeviceSize>(nodeBytes, 1);
        gVisibilityResources.nodeData = createBuffer(context, gVisibilityResources.nodeDataBytes,
                VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    }
    if (nodeBytes != 0) {
        std::memcpy(gVisibilityResources.nodeData.mapped, buffer.nodes.data(), size_t(nodeBytes));
    }

    if (gVisibilityResources.descriptorPool == VK_NULL_HANDLE) {
        VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1 };
        VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
        poolInfo.maxSets = 1;
        poolInfo.poolSizeCount = 1;
        poolInfo.pPoolSizes = &poolSize;
        check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr,
                      &gVisibilityResources.descriptorPool),
                "vkCreateDescriptorPool failed");
    }
    if (gVisibilityResources.descriptorSet == VK_NULL_HANDLE) {
        VkDescriptorSetAllocateInfo allocateInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
        allocateInfo.descriptorPool = gVisibilityResources.descriptorPool;
        allocateInfo.descriptorSetCount = 1;
        allocateInfo.pSetLayouts = &gPipelines.visibilitySetLayout;
        check(api->AllocateDescriptorSets(context.device, &allocateInfo,
                      &gVisibilityResources.descriptorSet),
                "vkAllocateDescriptorSets failed");
        recreateNodeData = true;
    }
    if (recreateNodeData) {
        VkDescriptorBufferInfo nodeInfo{
            gVisibilityResources.nodeData.buffer, 0, VK_WHOLE_SIZE };
        VkWriteDescriptorSet write{ VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET };
        write.dstSet = gVisibilityResources.descriptorSet;
        write.dstBinding = 0;
        write.descriptorCount = 1;
        write.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        write.pBufferInfo = &nodeInfo;
        api->UpdateDescriptorSets(context.device, 1, &write, 0, nullptr);
    }
}

GpuVisibility& rasterizeOnGpu(Context const& context, mm::Mesh const& mesh,
        mm::GpuLodBuffer const& buffer, GpuCut const& cut, mm::ViewCamera const& camera,
        uint32_t width, uint32_t height, GpuVisibility* output) {
    auto* api = mmgpu::api();
    GpuVisibility& result = *output;
    auto const wallStart = std::chrono::steady_clock::now();
    result.width = width;
    result.height = height;
    result.coveredPixels = 0;
    size_t const pixelCount = size_t(width) * height;
    // The readbacks below overwrite every pixel, so only size the vectors here. Resizing to the
    // same size is a no-op, which keeps steady-state frames free of any 2.7 MB clear per buffer.
    result.nodeIds.resize(pixelCount);
    result.triangleIds.resize(pixelCount);
    result.depth.resize(pixelCount);

    CameraBasis const basis = makeBasis(camera);
    if (!basis.valid || mesh.positions.empty() || cut.nodes.empty() ||
            cut.compactedIndexBuffer.buffer == VK_NULL_HANDLE ||
            cut.compactedVertexBuffer.buffer == VK_NULL_HANDLE) {
        std::fill(result.nodeIds.begin(), result.nodeIds.end(), UINT32_MAX);
        std::fill(result.triangleIds.begin(), result.triangleIds.end(), UINT32_MAX);
        std::fill(result.depth.begin(), result.depth.end(), 1.0f);
        return result;
    }

    VisibilityParams params{};
    params.eye[0] = camera.eye.x;
    params.eye[1] = camera.eye.y;
    params.eye[2] = camera.eye.z;
    params.nearPlane = camera.near;
    params.forward[0] = basis.forward.x;
    params.forward[1] = basis.forward.y;
    params.forward[2] = basis.forward.z;
    params.farPlane = camera.far;
    params.right[0] = basis.right.x;
    params.right[1] = basis.right.y;
    params.right[2] = basis.right.z;
    params.tanHalfFov = basis.tanHalfFov;
    params.up[0] = basis.up.x;
    params.up[1] = basis.up.y;
    params.up[2] = basis.up.z;
    params.aspect = basis.aspect;

    ensureVisibilityResources(context, width, height, buffer);

    result.drawCommands = cut.commandCount;

    VkRenderPass const renderPass = gPipelines.visibilityRenderPass;
    VkFramebuffer const framebuffer = gVisibilityResources.framebuffer;
    VkDescriptorSet const descriptorSet = gVisibilityResources.descriptorSet;
    Image const& color0 = gVisibilityResources.color0;
    Image const& color1 = gVisibilityResources.color1;
    Image const& depth = gVisibilityResources.depth;
    Buffer const& nodeReadback = gVisibilityResources.nodeReadback;
    Buffer const& triangleReadback = gVisibilityResources.triangleReadback;
    Buffer const& depthReadback = gVisibilityResources.depthReadback;

    VkPipelineLayout const pipelineLayout = gPipelines.visibilityLayout;
    VkPipeline const pipeline = gPipelines.visibilityPipeline;

    auto const setupEnd = std::chrono::steady_clock::now();
    result.setupMilliseconds =
            std::chrono::duration<double, std::milli>(setupEnd - wallStart).count();
    GpuTimer timer(context);
    VkCommandBuffer commandBuffer = beginCommands(context);
    timer.reset(commandBuffer);
    hostBarrier(commandBuffer);
    // The compacted index buffer and indirect commands were produced by a previous compute
    // submission. Make those shader writes visible to the index/indirect read stages.
    VkMemoryBarrier computeBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    computeBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    computeBarrier.dstAccessMask = VK_ACCESS_INDEX_READ_BIT | VK_ACCESS_INDIRECT_COMMAND_READ_BIT |
                                   VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            kComputeOutputReadStages, 0, 1, &computeBarrier, 0, nullptr, 0, nullptr);
    VkClearValue clears[3]{};
    for (uint32_t i = 0; i < 2; ++i) {
        clears[i].color.uint32[0] = UINT32_MAX;
        clears[i].color.uint32[1] = UINT32_MAX;
        clears[i].color.uint32[2] = UINT32_MAX;
        clears[i].color.uint32[3] = UINT32_MAX;
    }
    clears[2].depthStencil = { 1.0f, 0 };
    VkRenderPassBeginInfo begin{ VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO };
    begin.renderPass = renderPass;
    begin.framebuffer = framebuffer;
    begin.renderArea.extent = { width, height };
    begin.clearValueCount = 3;
    begin.pClearValues = clears;
    timer.start(commandBuffer, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT);
    api->CmdBeginRenderPass(commandBuffer, &begin, VK_SUBPASS_CONTENTS_INLINE);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, pipelineLayout, 0, 1,
            &descriptorSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, pipelineLayout, VK_SHADER_STAGE_VERTEX_BIT, 0,
            sizeof(VisibilityParams), &params);
    VkDeviceSize const vertexOffset = 0;
    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &cut.compactedVertexBuffer.buffer,
            &vertexOffset);
    api->CmdBindIndexBuffer(commandBuffer, cut.compactedIndexBuffer.buffer, 0,
            VK_INDEX_TYPE_UINT32);
    if (cut.commandCount != 0) {
        api->CmdDrawIndexedIndirect(commandBuffer, cut.indirectBuffer.buffer, 0, cut.commandCount,
                sizeof(mm::GpuDrawIndexedIndirectCommand));
    }
    api->CmdEndRenderPass(commandBuffer);
    timer.end(commandBuffer, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT);

    VkImageMemoryBarrier imageBarriers[3]{};
    for (uint32_t i = 0; i < 2; ++i) {
        imageBarriers[i].sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        imageBarriers[i].oldLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
        imageBarriers[i].newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
        imageBarriers[i].srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        imageBarriers[i].dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        imageBarriers[i].image = i == 0 ? color0.image : color1.image;
        imageBarriers[i].subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 };
        imageBarriers[i].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        imageBarriers[i].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    }
    imageBarriers[2].sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    imageBarriers[2].oldLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    imageBarriers[2].newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    imageBarriers[2].srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    imageBarriers[2].dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    imageBarriers[2].image = depth.image;
    imageBarriers[2].subresourceRange = { VK_IMAGE_ASPECT_DEPTH_BIT, 0, 1, 0, 1 };
    imageBarriers[2].srcAccessMask = VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    imageBarriers[2].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer,
            VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                    VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 3, imageBarriers);

    VkBufferImageCopy region{};
    region.imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 };
    region.imageExtent = { width, height, 1 };
    api->CmdCopyImageToBuffer(commandBuffer, color0.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            nodeReadback.buffer, 1, &region);
    api->CmdCopyImageToBuffer(commandBuffer, color1.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            triangleReadback.buffer, 1, &region);
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    api->CmdCopyImageToBuffer(commandBuffer, depth.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            depthReadback.buffer, 1, &region);
    submitAndWait(context, commandBuffer);
    auto const drawEnd = std::chrono::steady_clock::now();
    timer.read();
    auto const wallEnd = std::chrono::steady_clock::now();
    result.wallMilliseconds = std::chrono::duration<double, std::milli>(wallEnd - wallStart).count();
    result.readbackMilliseconds =
            std::chrono::duration<double, std::milli>(wallEnd - drawEnd).count();
    if (timer.valid()) {
        result.gpuDrawMilliseconds = timer.milliseconds();
    }

    std::memcpy(result.nodeIds.data(), nodeReadback.mapped, pixelCount * sizeof(uint32_t));
    std::memcpy(result.triangleIds.data(), triangleReadback.mapped, pixelCount * sizeof(uint32_t));
    std::memcpy(result.depth.data(), depthReadback.mapped, pixelCount * sizeof(float));
    for (uint32_t id: result.nodeIds) {
        result.coveredPixels += id == UINT32_MAX ? 0u : 1u;
    }

    return result;
}

// Records cut selection, vertex compaction and visibility into one command buffer. The previous
// implementation submitted each pass separately and called vkQueueWaitIdle after every submit,
// which serialized three GPU pipelines and showed up in RenderDoc as three submit/wait pairs per
// frame. The stages now communicate through compute barriers: the mark pass reads the live
// compacted index count from the cut counters, and the indirect draw covers the whole command
// capacity (unused slots stay zeroed). Host readbacks below are diagnostics only.
void runFrameOnGpu(Context const& context, mm::Mesh const& mesh,
        mm::GpuLodBuffer const& buffer, GpuCut* cutOut, ComputeParams const& computeParams,
        mm::ViewCamera const& camera, uint32_t width, uint32_t height,
        GpuVisibility* visibilityOut) {
    auto* api = mmgpu::api();
    GpuCut& cut = *cutOut;
    GpuVisibility& visibility = *visibilityOut;
    auto const frameStart = std::chrono::steady_clock::now();

    uint32_t const nodeCount = uint32_t(buffer.nodes.size());
    uint32_t const indexCapacity = uint32_t(buffer.indices.size());
    uint32_t const vertexCapacity = uint32_t(mesh.positions.size());
    size_t const pixelCount = size_t(width) * size_t(height);

    cut = GpuCut{};
    visibility.width = width;
    visibility.height = height;
    visibility.coveredPixels = 0;
    visibility.drawCommands = 0;
    visibility.nodeIds.resize(pixelCount);
    visibility.triangleIds.resize(pixelCount);
    visibility.depth.resize(pixelCount);

    CameraBasis const basis = makeBasis(camera);
    if (!basis.valid || nodeCount == 0 || indexCapacity == 0 || vertexCapacity == 0) {
        std::fill(visibility.nodeIds.begin(), visibility.nodeIds.end(), UINT32_MAX);
        std::fill(visibility.triangleIds.begin(), visibility.triangleIds.end(), UINT32_MAX);
        std::fill(visibility.depth.begin(), visibility.depth.end(), 1.0f);
        cut.frameTotalMilliseconds = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - frameStart).count();
        return;
    }

    ensureCutPipeline(context);
    ensureCutResources(context, buffer);
    ensureCompactionPipelines(context);
    ensureCompactionResources(context, mesh);
    ensureVisibilityResources(context, width, height, buffer);

    // Only the small per-frame counters are reset on the host. The index buffer keeps its old
    // contents, but the mark pass clamps to the live prefix published by the cut pass.
    std::memset(gCutResources.selected.mapped, 0, VkDeviceSize(nodeCount) * sizeof(uint32_t));
    std::memset(gCutResources.counters.mapped, 0, 5u * sizeof(uint32_t));
    std::memset(gCutResources.indirect.mapped, 0,
            VkDeviceSize(nodeCount) * sizeof(mm::GpuDrawIndexedIndirectCommand));
    std::memset(gCompactionResources.vertexMap.mapped, 0xFF,
            size_t(vertexCapacity) * sizeof(uint32_t));
    std::memset(gCompactionResources.counters.mapped, 0, 2u * sizeof(uint32_t));

    auto const setupEnd = std::chrono::steady_clock::now();
    double const setupMilliseconds =
            std::chrono::duration<double, std::milli>(setupEnd - frameStart).count();

    GpuTimer cutTimer(context);
    GpuTimer compactionTimer(context);
    GpuTimer visibilityTimer(context);
    VkCommandBuffer commandBuffer = beginCommands(context);
    cutTimer.reset(commandBuffer);
    compactionTimer.reset(commandBuffer);
    visibilityTimer.reset(commandBuffer);
    hostBarrier(commandBuffer);

    VkDescriptorSet const cutSet = gCutResources.descriptorSet;
    VkPipelineLayout const cutLayout = gPipelines.cut.layout;
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, gPipelines.cut.pipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, cutLayout, 0, 1,
            &cutSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, cutLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
            sizeof(ComputeParams), &computeParams);
    cutTimer.start(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    api->CmdDispatch(commandBuffer, (nodeCount + 63u) / 64u, 1, 1);
    cutTimer.end(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);

    auto computeBarrier = [&]() {
        VkMemoryBarrier barrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
        barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT;
        api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &barrier, 0, nullptr, 0, nullptr);
    };
    computeBarrier();

    CompactParams compactParams{};
    compactParams.indexCount = indexCapacity;
    compactParams.vertexCount = vertexCapacity;
    auto dispatch = [&](VkPipeline pipeline, VkPipelineLayout layout, VkDescriptorSet set,
                            uint32_t workItems, uint32_t mode) {
        compactParams.mode = mode;
        api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
        api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1,
                &set, 0, nullptr);
        api->CmdPushConstants(commandBuffer, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
                sizeof(CompactParams), &compactParams);
        api->CmdDispatch(commandBuffer, (workItems + 63u) / 64u, 1, 1);
    };
    compactionTimer.start(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    dispatch(gPipelines.mark.pipeline, gPipelines.mark.layout, gCompactionResources.markSet,
            indexCapacity, 0);
    computeBarrier();
    dispatch(gPipelines.gather.pipeline, gPipelines.gather.layout, gCompactionResources.gatherSet,
            vertexCapacity, 1);
    computeBarrier();
    dispatch(gPipelines.rewrite.pipeline, gPipelines.rewrite.layout,
            gCompactionResources.rewriteSet, indexCapacity, 2);
    compactionTimer.end(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);

    VkMemoryBarrier graphicsBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    graphicsBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    graphicsBarrier.dstAccessMask = VK_ACCESS_INDEX_READ_BIT |
                                    VK_ACCESS_INDIRECT_COMMAND_READ_BIT |
                                    VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            kComputeOutputReadStages, 0, 1, &graphicsBarrier, 0, nullptr, 0, nullptr);

    VisibilityParams params{};
    params.eye[0] = camera.eye.x;
    params.eye[1] = camera.eye.y;
    params.eye[2] = camera.eye.z;
    params.nearPlane = camera.near;
    params.forward[0] = basis.forward.x;
    params.forward[1] = basis.forward.y;
    params.forward[2] = basis.forward.z;
    params.farPlane = camera.far;
    params.right[0] = basis.right.x;
    params.right[1] = basis.right.y;
    params.right[2] = basis.right.z;
    params.tanHalfFov = basis.tanHalfFov;
    params.up[0] = basis.up.x;
    params.up[1] = basis.up.y;
    params.up[2] = basis.up.z;
    params.aspect = basis.aspect;

    VkClearValue clears[3]{};
    for (uint32_t i = 0; i < 2; ++i) {
        clears[i].color.uint32[0] = UINT32_MAX;
        clears[i].color.uint32[1] = UINT32_MAX;
        clears[i].color.uint32[2] = UINT32_MAX;
        clears[i].color.uint32[3] = UINT32_MAX;
    }
    clears[2].depthStencil = { 1.0f, 0 };
    VkRenderPassBeginInfo begin{ VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO };
    begin.renderPass = gPipelines.visibilityRenderPass;
    begin.framebuffer = gVisibilityResources.framebuffer;
    begin.renderArea.extent = { width, height };
    begin.clearValueCount = 3;
    begin.pClearValues = clears;
    visibilityTimer.start(commandBuffer, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT);
    api->CmdBeginRenderPass(commandBuffer, &begin, VK_SUBPASS_CONTENTS_INLINE);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS,
            gPipelines.visibilityPipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS,
            gPipelines.visibilityLayout, 0, 1, &gVisibilityResources.descriptorSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, gPipelines.visibilityLayout, VK_SHADER_STAGE_VERTEX_BIT,
            0, sizeof(VisibilityParams), &params);
    VkDeviceSize const vertexOffset = 0;
    api->CmdBindVertexBuffers(commandBuffer, 0, 1,
            &gCompactionResources.compactedPositions.buffer, &vertexOffset);
    api->CmdBindIndexBuffer(commandBuffer, gCutResources.compactedIndices.buffer, 0,
            VK_INDEX_TYPE_UINT32);
    api->CmdDrawIndexedIndirect(commandBuffer, gCutResources.indirect.buffer, 0, nodeCount,
            sizeof(mm::GpuDrawIndexedIndirectCommand));
    api->CmdEndRenderPass(commandBuffer);
    visibilityTimer.end(commandBuffer, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT);

    VkImageMemoryBarrier imageBarriers[3]{};
    for (uint32_t i = 0; i < 2; ++i) {
        imageBarriers[i].sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        imageBarriers[i].oldLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
        imageBarriers[i].newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
        imageBarriers[i].srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        imageBarriers[i].dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        imageBarriers[i].image = i == 0 ? gVisibilityResources.color0.image
                                        : gVisibilityResources.color1.image;
        imageBarriers[i].subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 };
        imageBarriers[i].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        imageBarriers[i].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    }
    imageBarriers[2].sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    imageBarriers[2].oldLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    imageBarriers[2].newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    imageBarriers[2].srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    imageBarriers[2].dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    imageBarriers[2].image = gVisibilityResources.depth.image;
    imageBarriers[2].subresourceRange = { VK_IMAGE_ASPECT_DEPTH_BIT, 0, 1, 0, 1 };
    imageBarriers[2].srcAccessMask = VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    imageBarriers[2].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer,
            VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                    VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 3, imageBarriers);

    VkBufferImageCopy region{};
    region.imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 };
    region.imageExtent = { width, height, 1 };
    api->CmdCopyImageToBuffer(commandBuffer, gVisibilityResources.color0.image,
            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, gVisibilityResources.nodeReadback.buffer, 1,
            &region);
    api->CmdCopyImageToBuffer(commandBuffer, gVisibilityResources.color1.image,
            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, gVisibilityResources.triangleReadback.buffer, 1,
            &region);
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
    api->CmdCopyImageToBuffer(commandBuffer, gVisibilityResources.depth.image,
            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, gVisibilityResources.depthReadback.buffer, 1,
            &region);

    VkMemoryBarrier hostReadBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    hostReadBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT;
    hostReadBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer,
            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hostReadBarrier, 0, nullptr, 0, nullptr);

    auto const submitStart = std::chrono::steady_clock::now();
    submitAndWait(context, commandBuffer);
    auto const submitEnd = std::chrono::steady_clock::now();
    double const submitMilliseconds =
            std::chrono::duration<double, std::milli>(submitEnd - submitStart).count();

    cutTimer.read();
    compactionTimer.read();
    visibilityTimer.read();

    uint32_t const* counters = static_cast<uint32_t const*>(gCutResources.counters.mapped);
    uint32_t const selectedCount = std::min(counters[0], nodeCount);
    uint32_t const* selected = static_cast<uint32_t const*>(gCutResources.selected.mapped);
    cut.nodes.assign(selected, selected + selectedCount);
    std::sort(cut.nodes.begin(), cut.nodes.end());
    cut.triangles = counters[1];
    cut.culledTriangles = counters[2];
    cut.compactedIndexCount = std::min(counters[3], indexCapacity);
    cut.commandCount = std::min(counters[4], selectedCount);

    auto const* compacted = static_cast<uint32_t const*>(gCutResources.compactedIndices.mapped);
    cut.compactedIndices.assign(compacted, compacted + cut.compactedIndexCount);
    auto const* commands =
            static_cast<mm::GpuDrawIndexedIndirectCommand const*>(gCutResources.indirect.mapped);
    cut.commands.assign(commands, commands + cut.commandCount);

    uint32_t const* compactionCounters =
            static_cast<uint32_t const*>(gCompactionResources.counters.mapped);
    uint32_t const compactedVertexCount = std::min(compactionCounters[1], vertexCapacity);
    if (compactionCounters[0] != compactionCounters[1]) {
        std::fprintf(stderr, "mmgpu: GPU vertex compaction marked %u but assigned %u\n",
                compactionCounters[0], compactionCounters[1]);
    }
    for (uint32_t i = 0; i < cut.compactedIndexCount; ++i) {
        if (compacted[i] >= compactedVertexCount) {
            std::fprintf(stderr,
                    "mmgpu: GPU vertex compaction produced index %u >= vertex count %u\n",
                    compacted[i], compactedVertexCount);
            break;
        }
    }
    cut.compactedVertexCount = compactedVertexCount;
    cut.compactedIndexBuffer = gCutResources.compactedIndices;
    cut.compactedVertexBuffer = gCompactionResources.compactedPositions;
    cut.indirectBuffer = gCutResources.indirect;
    cut.ownsBuffers = false;

    std::memcpy(visibility.nodeIds.data(), gVisibilityResources.nodeReadback.mapped,
            pixelCount * sizeof(uint32_t));
    std::memcpy(visibility.triangleIds.data(), gVisibilityResources.triangleReadback.mapped,
            pixelCount * sizeof(uint32_t));
    std::memcpy(visibility.depth.data(), gVisibilityResources.depthReadback.mapped,
            pixelCount * sizeof(float));
    for (uint32_t id: visibility.nodeIds) {
        visibility.coveredPixels += id == UINT32_MAX ? 0u : 1u;
    }
    visibility.drawCommands = cut.commandCount;

    auto const frameEnd = std::chrono::steady_clock::now();
    double const readbackMilliseconds =
            std::chrono::duration<double, std::milli>(frameEnd - submitEnd).count();
    double const totalMilliseconds =
            std::chrono::duration<double, std::milli>(frameEnd - frameStart).count();
    cut.frameSetupMilliseconds = setupMilliseconds;
    cut.frameSubmitMilliseconds = submitMilliseconds;
    cut.frameReadbackMilliseconds = readbackMilliseconds;
    cut.frameTotalMilliseconds = totalMilliseconds;
    cut.setupMilliseconds = setupMilliseconds;
    cut.dispatchMilliseconds = submitMilliseconds;
    cut.readbackMilliseconds = readbackMilliseconds;
    cut.milliseconds = totalMilliseconds;
    cut.vertexCompactionWallMilliseconds = 0.0;
    cut.vertexCompactionSetupMilliseconds = 0.0;
    cut.vertexCompactionDispatchMilliseconds = 0.0;
    if (cutTimer.valid()) {
        cut.selectionGpuMilliseconds = cutTimer.milliseconds();
    }
    if (compactionTimer.valid()) {
        cut.vertexCompactionGpuMilliseconds = compactionTimer.milliseconds();
    }
    if (visibilityTimer.valid()) {
        visibility.gpuDrawMilliseconds = visibilityTimer.milliseconds();
    }
    visibility.setupMilliseconds = setupMilliseconds;
    visibility.wallMilliseconds = totalMilliseconds;
    visibility.readbackMilliseconds = readbackMilliseconds;
}

void writeNodeIdPgm(std::vector<uint32_t> const& nodeIds, uint32_t width, uint32_t height,
        std::filesystem::path const& path) {
    std::ofstream file(path, std::ios::binary);
    if (!file) {
        std::fprintf(stderr, "mmgpu: cannot write '%s'\n", path.string().c_str());
        return;
    }
    file << "P5\n" << width << ' ' << height << "\n255\n";
    std::vector<uint8_t> pixels(nodeIds.size());
    for (size_t i = 0; i < nodeIds.size(); ++i) {
        uint32_t const id = nodeIds[i];
        pixels[i] = id == UINT32_MAX ? 0 : uint8_t((id * 37u) % 254u + 1u);
    }
    file.write(reinterpret_cast<char const*>(pixels.data()), std::streamsize(pixels.size()));
}

void writeDiffPgm(mm::VisibilityBuffer const& cpu, GpuVisibility const& gpu,
        std::filesystem::path const& path) {
    std::ofstream file(path, std::ios::binary);
    if (!file) {
        std::fprintf(stderr, "mmgpu: cannot write '%s'\n", path.string().c_str());
        return;
    }
    file << "P5\n" << cpu.width << ' ' << cpu.height << "\n255\n";
    std::vector<uint8_t> pixels(cpu.clusterIds.size());
    for (size_t i = 0; i < pixels.size(); ++i) {
        bool const inCpu = cpu.clusterIds[i] != UINT32_MAX;
        bool const inGpu = gpu.nodeIds[i] != UINT32_MAX;
        if (!inCpu && !inGpu) {
            pixels[i] = 0;
        } else if (inCpu && !inGpu) {
            pixels[i] = 64;
        } else if (!inCpu && inGpu) {
            pixels[i] = 192;
        } else if (cpu.clusterIds[i] != gpu.nodeIds[i]) {
            pixels[i] = 255;
        } else {
            pixels[i] = 96;
        }
    }
    file.write(reinterpret_cast<char const*>(pixels.data()), std::streamsize(pixels.size()));
}

struct Options {
    std::string meshPath;
    std::filesystem::path outputDirectory = "out/mmgpu";
    int device = 0;
    bool listDevices = false;
    uint32_t width = 640;
    uint32_t height = 360;
    float fovDegrees = 45.0f;
    float nearPlane = 0.01f;
    float farPlane = 1000.0f;
    float thresholdPx = 2.0f;
    uint32_t levels = 5;
    uint32_t clustersPerNode = 8;
    float ratio = 0.5f;
    bool cornerSimplify = true;
    bool cornerSplitUv = true;
    uint32_t frames = 1;
    bool legacySubmit = false;
    bool hasEye = false;
    bool hasTarget = false;
    float3 eye{ 0.0f, 0.0f, 3.0f };
    float3 target{ 0.0f, 0.0f, 0.0f };
};

void printUsage() {
    std::printf("Usage: mmgpu <mesh> [options]\n"
                "\n"
                "Real Vulkan compute cut selection and visibility-buffer prototype.\n"
                "\n"
                "  --out DIR            Output directory (default: out/mmgpu)\n"
                "  --device N           Vulkan physical device index\n"
                "  --list-devices       List Vulkan devices and exit\n"
                "  --width N            Screen width (default: 640)\n"
                "  --height N           Screen height (default: 360)\n"
                "  --eye X,Y,Z          Camera eye\n"
                "  --target X,Y,Z       Camera target\n"
                "  --fov-deg F          Vertical field of view in degrees (default: 45)\n"
                "  --near F             Near plane (default: 0.01)\n"
                "  --far F              Far plane (default: 1000)\n"
                "  --threshold-px F     Maximum cluster screen error (default: 2)\n"
                "  --levels N           DAG levels (default: 5)\n"
                "  --clusters N         Children merged per DAG node (default: 8)\n"
                "  --ratio F            Parent triangle ratio (default: 0.5)\n"
                "  --corner-seam 0|1    Enable corner-aware seam simplification (default: 1)\n"
                "  --corner-split-uv 0|1\n"
                "                       Split divergent UV clusters at a position (default: 1)\n"
                "  --frames N           Repeat the GPU cut/compaction/draw path N times\n"
                "  --legacy-submit      Use the old three-submit path for A/B comparison\n");
}

bool parseFloat3(char const* text, float3* value) {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    if (std::sscanf(text, "%f,%f,%f", &x, &y, &z) != 3) {
        return false;
    }
    *value = { x, y, z };
    return true;
}

char const* nextValue(int argc, char** argv, int* index, char const* option) {
    if (*index + 1 >= argc) {
        std::fprintf(stderr, "mmgpu: %s requires a value\n", option);
        std::exit(1);
    }
    *index += 1;
    return argv[*index];
}

Options parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        std::string const argument = argv[i];
        if (argument == "--help" || argument == "-h") {
            printUsage();
            std::exit(0);
        } else if (argument == "--list-devices") {
            options.listDevices = true;
        } else if (argument == "--out") {
            options.outputDirectory = nextValue(argc, argv, &i, "--out");
        } else if (argument == "--device") {
            options.device = std::atoi(nextValue(argc, argv, &i, "--device"));
        } else if (argument == "--width") {
            options.width =
                    uint32_t(std::strtoul(nextValue(argc, argv, &i, "--width"), nullptr, 10));
        } else if (argument == "--height") {
            options.height =
                    uint32_t(std::strtoul(nextValue(argc, argv, &i, "--height"), nullptr, 10));
        } else if (argument == "--eye") {
            if (!parseFloat3(nextValue(argc, argv, &i, "--eye"), &options.eye)) {
                std::fprintf(stderr, "mmgpu: --eye expects X,Y,Z\n");
                std::exit(1);
            }
            options.hasEye = true;
        } else if (argument == "--target") {
            if (!parseFloat3(nextValue(argc, argv, &i, "--target"), &options.target)) {
                std::fprintf(stderr, "mmgpu: --target expects X,Y,Z\n");
                std::exit(1);
            }
            options.hasTarget = true;
        } else if (argument == "--fov-deg") {
            options.fovDegrees = std::strtof(nextValue(argc, argv, &i, "--fov-deg"), nullptr);
        } else if (argument == "--near") {
            options.nearPlane = std::strtof(nextValue(argc, argv, &i, "--near"), nullptr);
        } else if (argument == "--far") {
            options.farPlane = std::strtof(nextValue(argc, argv, &i, "--far"), nullptr);
        } else if (argument == "--threshold-px") {
            options.thresholdPx = std::strtof(nextValue(argc, argv, &i, "--threshold-px"), nullptr);
        } else if (argument == "--levels") {
            options.levels =
                    uint32_t(std::strtoul(nextValue(argc, argv, &i, "--levels"), nullptr, 10));
        } else if (argument == "--clusters") {
            options.clustersPerNode =
                    uint32_t(std::strtoul(nextValue(argc, argv, &i, "--clusters"), nullptr, 10));
        } else if (argument == "--ratio") {
            options.ratio = std::strtof(nextValue(argc, argv, &i, "--ratio"), nullptr);
        } else if (argument == "--corner-seam") {
            options.cornerSimplify =
                    std::strtol(nextValue(argc, argv, &i, "--corner-seam"), nullptr, 10) != 0;
        } else if (argument == "--corner-split-uv") {
            options.cornerSplitUv =
                    std::strtol(nextValue(argc, argv, &i, "--corner-split-uv"), nullptr, 10) != 0;
        } else if (argument == "--frames") {
            options.frames =
                    uint32_t(std::strtoul(nextValue(argc, argv, &i, "--frames"), nullptr, 10));
        } else if (argument == "--legacy-submit") {
            options.legacySubmit = true;
        } else if (!argument.empty() && argument[0] == '-') {
            std::fprintf(stderr, "mmgpu: unknown option '%s'\n", argument.c_str());
            std::exit(1);
        } else if (options.meshPath.empty()) {
            options.meshPath = argument;
        } else {
            std::fprintf(stderr, "mmgpu: unexpected argument '%s'\n", argument.c_str());
            std::exit(1);
        }
    }
    if (!options.listDevices && options.meshPath.empty()) {
        printUsage();
        std::exit(1);
    }
    if (options.width == 0 || options.height == 0 || options.fovDegrees <= 0.0f ||
            options.nearPlane <= 0.0f || options.farPlane <= options.nearPlane ||
            options.thresholdPx < 0.0f || options.levels == 0 || options.clustersPerNode < 2 ||
            options.ratio <= 0.0f || options.ratio > 1.0f || options.frames == 0) {
        std::fprintf(stderr, "mmgpu: invalid option range\n");
        std::exit(1);
    }
    return options;
}

bool meshBounds(mm::Mesh const& mesh, float3* center, float* radius) {
    if (mesh.positions.empty()) {
        return false;
    }
    float3 minimum = mesh.positions[0];
    float3 maximum = mesh.positions[0];
    for (float3 const& position: mesh.positions) {
        minimum.x = std::min(minimum.x, position.x);
        minimum.y = std::min(minimum.y, position.y);
        minimum.z = std::min(minimum.z, position.z);
        maximum.x = std::max(maximum.x, position.x);
        maximum.y = std::max(maximum.y, position.y);
        maximum.z = std::max(maximum.z, position.z);
    }
    *center = (minimum + maximum) * 0.5f;
    *radius = 0.0f;
    for (float3 const& position: mesh.positions) {
        *radius = std::max(*radius, length(position - *center));
    }
    return *radius > 1e-6f;
}

std::string percent(uint64_t part, uint64_t total) {
    if (total == 0) {
        return "0.00%";
    }
    char text[64];
    std::snprintf(text, sizeof(text), "%.2f%%", 100.0 * double(part) / double(total));
    return text;
}

} // namespace

int main(int argc, char** argv) {
    try {
        Options const options = parseOptions(argc, argv);
        glslang::InitializeProcess();

        Context context = createContext(options.device, options.listDevices);
        std::printf("device: %s\n", context.deviceName);

        mm::Mesh mesh;
        if (!loadMesh(options.meshPath.c_str(), &mesh)) {
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }
        if (mesh.indices.size() % 3 != 0 || mesh.indices.empty()) {
            std::fprintf(stderr, "mmgpu: mesh has no triangles\n");
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }

        mm::LodGraphOptions lodOptions;
        lodOptions.levels = options.levels;
        lodOptions.clustersPerNode = options.clustersPerNode;
        lodOptions.ratio = options.ratio;
        lodOptions.simplify.cornerSimplify = options.cornerSimplify;
        lodOptions.simplify.cornerSplitDivergentUv = options.cornerSplitUv;
        auto const graphStart = std::chrono::steady_clock::now();
        mm::LodGraph const graph = mm::buildLodGraph(mesh, lodOptions);
        auto const graphEnd = std::chrono::steady_clock::now();
        if (graph.nodes.empty()) {
            std::fprintf(stderr, "mmgpu: DAG construction produced no nodes\n");
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }
        // The GPU cut references one vertex space: source vertices followed by the generated
        // vertices that corner simplification introduced. Uploading that tail here keeps the
        // compaction shader, the indirect draw and the CPU visibility reference on the same
        // index space. The graph was already built against the source-only mesh above.
        uint32_t const sourceVertexCount = uint32_t(mesh.positions.size());
        mesh.positions.reserve(mesh.positions.size() + graph.generatedVertices.size());
        for (mm::GeneratedVertex const& generated: graph.generatedVertices) {
            if (generated.hasPosition) {
                mesh.positions.push_back(generated.position);
            } else if (generated.positionSource < mesh.positions.size()) {
                mesh.positions.push_back(mesh.positions[generated.positionSource]);
            } else {
                std::fprintf(stderr,
                        "mmgpu: generated vertex has no position and source %u is out of range\n",
                        generated.positionSource);
                destroyContext(&context);
                glslang::FinalizeProcess();
                return 1;
            }
        }
        if (graph.vertexCount != mesh.positions.size()) {
            std::fprintf(stderr, "mmgpu: graph vertex count %u does not match upload %zu\n",
                    graph.vertexCount, mesh.positions.size());
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }
        mm::GpuLodBuffer const buffer = mm::flattenLodGraph(graph);

        float3 boundsCenter{};
        float boundsRadius = 0.0f;
        if (!meshBounds(mesh, &boundsCenter, &boundsRadius)) {
            std::fprintf(stderr, "mmgpu: mesh has degenerate bounds\n");
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }

        mm::ViewCamera camera;
        camera.screenWidth = options.width;
        camera.screenHeight = options.height;
        camera.fovY = options.fovDegrees * 3.14159265358979323846f / 180.0f;
        camera.near = options.nearPlane;
        camera.far = options.farPlane;
        camera.target = options.hasTarget ? options.target : boundsCenter;
        if (options.hasEye) {
            camera.eye = options.eye;
        } else {
            float const distance = boundsRadius / std::max(std::sin(camera.fovY * 0.5f), 1e-3f);
            camera.eye = camera.target + float3{ 0.0f, 0.0f, distance * 1.1f };
        }

        CameraBasis const basis = makeBasis(camera);
        if (!basis.valid) {
            std::fprintf(stderr, "mmgpu: invalid camera basis\n");
            destroyContext(&context);
            glslang::FinalizeProcess();
            return 1;
        }

        auto const cpuStart = std::chrono::steady_clock::now();
        mm::LodGraphSelection const cpuSelection =
                mm::selectLodGraph(graph, camera, options.thresholdPx);
        auto const cpuEnd = std::chrono::steady_clock::now();
        double const cpuMilliseconds =
                std::chrono::duration<double, std::milli>(cpuEnd - cpuStart).count();

#if defined(MMGPU_HAS_RENDERDOC)
        RenderDocCapture renderDocCapture(RENDERDOC_DEVICEPOINTER_FROM_VKINSTANCE(context.instance));
#endif
        ComputeParams const computeParams = makeComputeParams(camera, basis, options.thresholdPx,
                uint32_t(buffer.nodes.size()));
        GpuCut gpuCut;
        GpuVisibility gpuVisibility;
        double cutSetupTotal = 0.0;
        double cutSubmitTotal = 0.0;
        double compactionWallTotal = 0.0;
        double visibilityWallTotal = 0.0;
        double warmFrames = 0.0;
        double lastCutSetup = 0.0;
        double lastCutSubmit = 0.0;
        double lastCompactionSetup = 0.0;
        double lastVisibilitySetup = 0.0;
        // Reuse the readback vectors across frames: reallocating them every frame zeroes ~11 MB
        // of pixel storage that the GPU overwrites in full anyway.
        GpuVisibility frameVisibility;
        for (uint32_t frame = 0; frame < options.frames; ++frame) {
            GpuCut frameCut;
            if (options.legacySubmit) {
                frameCut = selectOnGpu(context, buffer, computeParams);
                compactVerticesOnGpu(context, mesh, &frameCut);
                rasterizeOnGpu(context, mesh, buffer, frameCut, camera, options.width,
                        options.height, &frameVisibility);
            } else {
                runFrameOnGpu(context, mesh, buffer, &frameCut, computeParams, camera,
                        options.width, options.height, &frameVisibility);
            }
            double const frameSetup = options.legacySubmit
                    ? frameCut.setupMilliseconds + frameCut.vertexCompactionSetupMilliseconds +
                              frameVisibility.setupMilliseconds
                    : frameCut.frameSetupMilliseconds;
            double const frameSubmit = options.legacySubmit
                    ? frameCut.dispatchMilliseconds +
                              frameCut.vertexCompactionDispatchMilliseconds +
                              (frameVisibility.wallMilliseconds -
                                      frameVisibility.readbackMilliseconds)
                    : frameCut.frameSubmitMilliseconds;
            double const frameReadback = options.legacySubmit
                    ? frameCut.readbackMilliseconds + frameVisibility.readbackMilliseconds
                    : frameCut.frameReadbackMilliseconds;
            double const frameTotal = options.legacySubmit
                    ? frameCut.milliseconds + frameCut.vertexCompactionWallMilliseconds +
                              frameVisibility.wallMilliseconds
                    : frameCut.frameTotalMilliseconds;
            // Frame 0 creates the lazy pipelines and grows the driver heaps, so it is not a
            // steady-state sample. Average the frames a shipped renderer would actually run.
            if (frame > 0) {
                cutSetupTotal += frameSetup;
                cutSubmitTotal += frameSubmit;
                compactionWallTotal += frameReadback;
                visibilityWallTotal += frameTotal;
                warmFrames += 1.0;
            }
            lastCutSetup = frameSetup;
            lastCutSubmit = frameSubmit;
            lastCompactionSetup = frameReadback;
            lastVisibilitySetup = frameTotal;
            if (frame + 1 == options.frames) {
                gpuCut = std::move(frameCut);
                gpuVisibility = std::move(frameVisibility);
            } else {
                destroyGpuCut(context, &frameCut);
            }
        }
        double const warmCount = std::max(warmFrames, 1.0);
        std::printf("frames: %u, warm avg (excluding first) %s %.3f ms "
                    "(setup %.3f, readback %.3f), frame %.3f ms\n",
                options.frames, options.legacySubmit ? "legacy submit" : "single submit",
                cutSubmitTotal / warmCount, cutSetupTotal / warmCount,
                compactionWallTotal / warmCount, visibilityWallTotal / warmCount);
        std::printf("frames: last setup %.3f + submit %.3f + readback %.3f = %.3f ms, %s\n",
                lastCutSetup, lastCutSubmit, lastCompactionSetup, lastVisibilitySetup,
                options.legacySubmit ? "three vkQueueSubmit / three vkQueueWaitIdle"
                                     : "one vkQueueSubmit / one vkQueueWaitIdle");

        std::vector<uint32_t> cpuNodes = cpuSelection.nodes;
        std::sort(cpuNodes.begin(), cpuNodes.end());
        bool const nodesMatch = cpuNodes == gpuCut.nodes;
        bool const trianglesMatch = cpuSelection.selectedTriangles == gpuCut.triangles;
        bool const culledMatch = cpuSelection.culledTriangles == gpuCut.culledTriangles;
        // The GPU path always emits a dense cut-local vertex buffer, so the CPU reference has
        // to compact the source range too. The default keeps source ids for renderers that reuse
        // their original vertex buffer, which is a different (and still valid) output layout.
        mm::LodGraphCompactOptions compactOptions;
        compactOptions.compactSourceVertices = true;
        mm::LodGraphCutGeometry const cpuCompact =
                mm::compactLodSelection(graph, cpuSelection, compactOptions);
        std::vector<uint32_t> cpuCompacted = cpuCompact.indices;
        std::vector<uint32_t> gpuCompacted = gpuCut.compactedIndices;
        std::sort(cpuCompacted.begin(), cpuCompacted.end());
        std::sort(gpuCompacted.begin(), gpuCompacted.end());
        bool const compactedMatch = cpuCompacted == gpuCompacted;
        bool const commandsMatch = gpuCut.commandCount == gpuCut.nodes.size();

        // The GPU assigns dense ids in parallel, so the id order is not part of the contract.
        // Reconstruct each side's compact -> source map and compare the referenced vertex set
        // independently of that permutation.
        std::vector<uint32_t> gpuSourceIds(gpuCut.compactedVertexCount, UINT32_MAX);
        auto const* vertexMap = static_cast<uint32_t const*>(gCompactionResources.vertexMap.mapped);
        for (uint32_t source = 0; source < mesh.positions.size(); ++source) {
            uint32_t const dense = vertexMap[source];
            if (dense < gpuCut.compactedVertexCount) {
                gpuSourceIds[dense] = source;
            }
        }
        // The CPU compacted cut uses two dense ranges (source then generated). Reconstruct the
        // original graph-space id for every compacted index so it can be compared with the GPU
        // vertex map, which is indexed by the uploaded source+generated vertex buffer.
        uint32_t const cpuSourceCount = cpuCompact.sourceVertexCount;
        auto const cpuOriginal = [&](uint32_t index) -> uint32_t {
            if (index < cpuSourceCount) {
                if (index < cpuCompact.sourceVertexIds.size()) {
                    return cpuCompact.sourceVertexIds[index];
                }
            } else {
                size_t const generated = size_t(index - cpuSourceCount);
                if (generated < cpuCompact.generatedSourceIds.size()) {
                    return sourceVertexCount + cpuCompact.generatedSourceIds[generated];
                }
            }
            return UINT32_MAX;
        };
        std::vector<uint32_t> cpuGlobalIds;
        cpuGlobalIds.reserve(cpuCompact.indices.size());
        std::vector<uint32_t> cpuSourceIds;
        cpuSourceIds.reserve(cpuCompact.indices.size());
        for (uint32_t index: cpuCompact.indices) {
            uint32_t const original = cpuOriginal(index);
            cpuGlobalIds.push_back(original);
            if (original != UINT32_MAX) {
                cpuSourceIds.push_back(original);
            }
        }
        std::sort(cpuSourceIds.begin(), cpuSourceIds.end());
        cpuSourceIds.erase(std::unique(cpuSourceIds.begin(), cpuSourceIds.end()),
                cpuSourceIds.end());
        std::vector<uint32_t> sortedGpuSourceIds = gpuSourceIds;
        sortedGpuSourceIds.erase(
                std::remove(sortedGpuSourceIds.begin(), sortedGpuSourceIds.end(), UINT32_MAX),
                sortedGpuSourceIds.end());
        std::sort(sortedGpuSourceIds.begin(), sortedGpuSourceIds.end());
        bool const sourceSetMatch = cpuSourceIds == sortedGpuSourceIds;
        std::vector<uint32_t> missingSources;
        std::vector<uint32_t> extraSources;
        std::set_difference(cpuSourceIds.begin(), cpuSourceIds.end(),
                sortedGpuSourceIds.begin(), sortedGpuSourceIds.end(),
                std::back_inserter(missingSources));
        std::set_difference(sortedGpuSourceIds.begin(), sortedGpuSourceIds.end(),
                cpuSourceIds.begin(), cpuSourceIds.end(), std::back_inserter(extraSources));
        std::printf("compaction sources: cpu %zu (vertexCount %u, generated %zu), gpu %zu, "
                    "missing %zu, extra %zu\n",
                cpuSourceIds.size(), cpuCompact.vertexCount, graph.generatedVertices.size(),
                sortedGpuSourceIds.size(), missingSources.size(), extraSources.size());
        if (!missingSources.empty()) {
            std::printf("compaction sources: first missing %u, first extra %u\n",
                    missingSources.front(), extraSources.empty() ? 0u : extraSources.front());
        } else if (!extraSources.empty()) {
            std::printf("compaction sources: first extra %u\n", extraSources.front());
        }

        // Both sides assign dense ids in different orders. Compare the actual compacted
        // geometry instead: each triangle is reduced to its three exact positions, and the
        // vertices inside a triangle are sorted so winding does not matter. This is the
        // renderer-facing contract and it stays valid when corner simplification leaves several
        // attribute vertices at the same position.
        using TriangleKey = std::array<std::array<float, 3>, 3>;
        auto const triangleKey = [](math::float3 const& a, math::float3 const& b,
                                         math::float3 const& c) {
            TriangleKey key{ { { a.x, a.y, a.z }, { b.x, b.y, b.z }, { c.x, c.y, c.z } } };
            std::sort(key.begin(), key.end());
            return key;
        };
        auto const* compactedPositions =
                static_cast<math::float3 const*>(gpuCut.compactedVertexBuffer.mapped);
        std::vector<TriangleKey> cpuTriangles;
        std::vector<TriangleKey> gpuTriangles;
        cpuTriangles.reserve(cpuCompact.indices.size() / 3);
        gpuTriangles.reserve(gpuCut.compactedIndices.size() / 3);
        for (size_t i = 0; i + 2 < cpuCompact.indices.size(); i += 3) {
            uint32_t const a = cpuGlobalIds[i + 0];
            uint32_t const b = cpuGlobalIds[i + 1];
            uint32_t const c = cpuGlobalIds[i + 2];
            if (a == UINT32_MAX || b == UINT32_MAX || c == UINT32_MAX) {
                continue;
            }
            cpuTriangles.push_back(triangleKey(mesh.positions[a], mesh.positions[b],
                    mesh.positions[c]));
        }
        if (compactedPositions != nullptr) {
            for (size_t i = 0; i + 2 < gpuCut.compactedIndices.size(); i += 3) {
                uint32_t const a = gpuCut.compactedIndices[i + 0];
                uint32_t const b = gpuCut.compactedIndices[i + 1];
                uint32_t const c = gpuCut.compactedIndices[i + 2];
                if (a >= gpuCut.compactedVertexCount || b >= gpuCut.compactedVertexCount ||
                        c >= gpuCut.compactedVertexCount) {
                    continue;
                }
                gpuTriangles.push_back(triangleKey(compactedPositions[a], compactedPositions[b],
                        compactedPositions[c]));
            }
        }
        std::sort(cpuTriangles.begin(), cpuTriangles.end());
        std::sort(gpuTriangles.begin(), gpuTriangles.end());
        bool const compactedTopologyMatch = cpuTriangles == gpuTriangles;
        mm::VisibilityBuffer const cpuVisibility =
                mm::rasterizeVisibility(mesh, buffer, cpuSelection, camera);
#if defined(MMGPU_HAS_RENDERDOC)
        renderDocCapture.end();
#endif

        std::filesystem::create_directories(options.outputDirectory);
        std::string const stem = std::filesystem::path(options.meshPath).stem().string();
        std::filesystem::path const cpuPath =
                options.outputDirectory / (stem + "-cpu-visibility.pgm");
        std::filesystem::path const gpuPath =
                options.outputDirectory / (stem + "-gpu-visibility.pgm");
        std::filesystem::path const diffPath =
                options.outputDirectory / (stem + "-visibility-diff.pgm");
        mm::writeVisibilityBufferPgm(cpuVisibility, cpuPath.string().c_str());
        writeNodeIdPgm(gpuVisibility.nodeIds, gpuVisibility.width, gpuVisibility.height, gpuPath);
        writeDiffPgm(cpuVisibility, gpuVisibility, diffPath);

        uint64_t bothCovered = 0;
        uint64_t onlyCpu = 0;
        uint64_t onlyGpu = 0;
        uint64_t sameNode = 0;
        uint64_t sameTriangle = 0;
        uint64_t depthMismatch = 0;
        double depthDifference = 0.0;
        for (size_t i = 0; i < cpuVisibility.clusterIds.size(); ++i) {
            bool const inCpu = cpuVisibility.clusterIds[i] != UINT32_MAX;
            bool const inGpu = gpuVisibility.nodeIds[i] != UINT32_MAX;
            if (inCpu && inGpu) {
                bothCovered += 1;
                if (cpuVisibility.clusterIds[i] == gpuVisibility.nodeIds[i]) {
                    sameNode += 1;
                }
                if (cpuVisibility.triangleIds[i] == gpuVisibility.triangleIds[i]) {
                    sameTriangle += 1;
                }
                if (cpuVisibility.inverseDepth[i] > 0.0f) {
                    float const cpuDepth = 1.0f / cpuVisibility.inverseDepth[i];
                    float const cpuZ = (cpuDepth - camera.near) / (camera.far - camera.near);
                    float const difference = std::abs(cpuZ - gpuVisibility.depth[i]);
                    depthDifference += double(difference);
                    if (difference > 1e-3f) {
                        depthMismatch += 1;
                    }
                }
            } else if (inCpu) {
                onlyCpu += 1;
            } else if (inGpu) {
                onlyGpu += 1;
            }
        }
        uint64_t const coveredUnion = bothCovered + onlyCpu + onlyGpu;

        std::printf("mesh: %s (%u source vertices + %zu generated, %zu triangles)\n",
                options.meshPath.c_str(), sourceVertexCount, graph.generatedVertices.size(),
                mesh.indices.size() / 3);
        std::printf("dag: %zu nodes, %zu indices, %zu levels (%.2f ms)\n", graph.nodes.size(),
                buffer.indices.size(), size_t(graph.levelCount),
                std::chrono::duration<double, std::milli>(graphEnd - graphStart).count());
        std::printf("camera: eye %.3f,%.3f,%.3f target %.3f,%.3f,%.3f fov %.2f deg\n", camera.eye.x,
                camera.eye.y, camera.eye.z, camera.target.x, camera.target.y, camera.target.z,
                options.fovDegrees);
        std::printf("cut: cpu %zu nodes / %llu tris (%.3f ms), gpu %zu nodes / %llu tris "
                    "(frame %.3f ms)\n",
                cpuNodes.size(), (unsigned long long) cpuSelection.selectedTriangles,
                cpuMilliseconds, gpuCut.nodes.size(), (unsigned long long) gpuCut.triangles,
                gpuCut.milliseconds);
        if (context.timestampSupported && gpuCut.selectionGpuMilliseconds > 0.0) {
            std::printf("gpu stages: cut %.4f ms, vertex compaction %.4f ms (wall %.4f), "
                        "visibility draw %.4f ms (wall %.4f)\n",
                    gpuCut.selectionGpuMilliseconds,
                    gpuCut.vertexCompactionGpuMilliseconds,
                    gpuCut.vertexCompactionWallMilliseconds,
                    gpuVisibility.gpuDrawMilliseconds, gpuVisibility.wallMilliseconds);
            std::printf("cpu sync: setup %.2f / submit+wait %.2f / readback %.2f ms "
                        "(one submission for cut + compaction + visibility)\n",
                    gpuCut.frameSetupMilliseconds, gpuCut.frameSubmitMilliseconds,
                    gpuCut.frameReadbackMilliseconds);
        } else {
            std::printf("gpu stages: timestamp queries unavailable on this device/queue\n");
        }        std::printf("selection: nodes %s, triangles %s, culled %s (cpu %llu, gpu %llu)\n",
                nodesMatch ? "match" : "MISMATCH", trianglesMatch ? "match" : "MISMATCH",
                culledMatch ? "match" : "MISMATCH",
                (unsigned long long) cpuSelection.culledTriangles,
                (unsigned long long) gpuCut.culledTriangles);
        std::printf("compaction: cpu %zu indices, gpu %u indices, gpu %u commands "
                    "(ids %s, topology %s, source set %s, commands %s), "
                    "gpu %u vertices (source %u + generated %zu)\n",
                cpuCompact.indices.size(), gpuCut.compactedIndexCount, gpuCut.commandCount,
                compactedMatch ? "match" : "permuted",
                compactedTopologyMatch ? "match" : "MISMATCH",
                sourceSetMatch ? "match" : "MISMATCH",
                commandsMatch ? "match" : "MISMATCH",
                gpuCut.compactedVertexCount, sourceVertexCount, graph.generatedVertices.size());
        std::printf("visibility: cpu %u covered, gpu %u covered, overlap %llu / union %llu "
                    "(%s)\n",
                cpuVisibility.coveredPixels, gpuVisibility.coveredPixels,
                (unsigned long long) bothCovered, (unsigned long long) coveredUnion,
                percent(bothCovered, coveredUnion).c_str());
        std::printf("visibility: %u indirect indexed draws, %u x %u pixels\n",
                gpuVisibility.drawCommands, gpuVisibility.width, gpuVisibility.height);
        std::printf("visibility: node agreement %s, triangle agreement %s, depth mismatch "
                    "%llu (mean %.6f)\n",
                percent(sameNode, bothCovered).c_str(), percent(sameTriangle, bothCovered).c_str(),
                (unsigned long long) depthMismatch,
                bothCovered == 0 ? 0.0 : depthDifference / double(bothCovered));
        std::printf("visibility: only cpu %llu, only gpu %llu\n", (unsigned long long) onlyCpu,
                (unsigned long long) onlyGpu);
        std::printf("output: %s\n", cpuPath.string().c_str());
        std::printf("output: %s\n", gpuPath.string().c_str());
        std::printf("output: %s\n", diffPath.string().c_str());

        if (!nodesMatch) {
            std::set<uint32_t> const cpuSet(cpuNodes.begin(), cpuNodes.end());
            std::set<uint32_t> const gpuSet(gpuCut.nodes.begin(), gpuCut.nodes.end());
            std::printf("selection: first cpu-only nodes:");
            size_t shown = 0;
            for (uint32_t id: cpuSet) {
                if (gpuSet.count(id) == 0 && shown < 8) {
                    std::printf(" %u", id);
                    shown += 1;
                }
            }
            std::printf("\nselection: first gpu-only nodes:");
            shown = 0;
            for (uint32_t id: gpuSet) {
                if (cpuSet.count(id) == 0 && shown < 8) {
                    std::printf(" %u", id);
                    shown += 1;
                }
            }
            std::printf("\n");
            std::printf("selection: cpu nodes:");
            for (uint32_t id: cpuNodes) {
                std::printf(" %u", id);
            }
            std::printf("\nselection: gpu nodes:");
            for (uint32_t id: gpuCut.nodes) {
                std::printf(" %u", id);
            }
            std::printf("\n");
            size_t inspected = 0;
            for (uint32_t id: gpuCut.nodes) {
                if (std::binary_search(cpuNodes.begin(), cpuNodes.end(), id) || inspected >= 4) {
                    continue;
                }
                std::printf("selection: gpu-only node %u chain:\n", id);
                uint32_t current = id;
                for (uint32_t depth = 0; depth < 16 && current < buffer.nodes.size(); ++depth) {
                    mm::GpuLodNode const& node = buffer.nodes[current];
                    std::printf("  node %u level %u indexCount %u children %u parent %u "
                                "error %.6f screen %.6f\n",
                            current, node.level, node.indexCount, node.childCount, node.parent,
                            node.accumulatedError, gpuNodeScreenError(node, camera, basis));
                    current = node.parent;
                }
                inspected += 1;
            }
        }

        destroyGpuCut(context, &gpuCut);
        resetVisibilityResources(context);
        resetCompactionResources(context);
        resetCutResources(context);
        destroyGpuPipelineCache(context);
        destroyContext(&context);
        glslang::FinalizeProcess();
        // Dense vertex ids are a parallel permutation, so compactedMatch (bit-identical ids)
        // is informational only. The contract is the source-vertex set plus triangle topology.
        return nodesMatch && trianglesMatch && compactedTopologyMatch && sourceSetMatch &&
                       commandsMatch
               ? 0
               : 2;
    } catch (std::exception const& exception) {
        std::fprintf(stderr, "mmgpu: %s\n", exception.what());
        return 1;
    }
}
