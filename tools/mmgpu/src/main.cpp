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

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <glslang/Public/ResourceLimits.h>
#include <glslang/Public/ShaderLang.h>
#include <SPIRV/GlslangToSpv.h>

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
};

uint32_t findMemoryType(Context const& context, uint32_t typeBits,
        VkMemoryPropertyFlags properties) {
    for (uint32_t i = 0; i < context.memoryProperties.memoryTypeCount; ++i) {
        if ((typeBits & (1u << i)) != 0 &&
                (context.memoryProperties.memoryTypes[i].propertyFlags & properties) == properties) {
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
    result.aspect = format == VK_FORMAT_D32_SFLOAT ? VK_IMAGE_ASPECT_DEPTH_BIT
                                                   : VK_IMAGE_ASPECT_COLOR_BIT;
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
    allocate.memoryTypeIndex =
            findMemoryType(context, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
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
    check(mmgpu::api()->BeginCommandBuffer(commandBuffer, &begin),
            "vkBeginCommandBuffer failed");
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

void hostBarrier(VkCommandBuffer commandBuffer) {
    VkMemoryBarrier barrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    barrier.srcAccessMask = VK_ACCESS_HOST_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT |
                            VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT | VK_ACCESS_INDEX_READ_BIT |
                            VK_ACCESS_INDIRECT_COMMAND_READ_BIT | VK_ACCESS_TRANSFER_READ_BIT;
    mmgpu::api()->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_HOST_BIT,
            VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, &barrier, 0, nullptr, 0, nullptr);
}

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
    float const depth = dot(float3{ node.boundsCenter[0], node.boundsCenter[1],
                                          node.boundsCenter[2] } - camera.eye,
            basis.forward);
    if (depth <= camera.near) {
        return std::numeric_limits<float>::max();
    }
    float const pixelsPerRadian = float(camera.screenHeight) / (2.0f * basis.tanHalfFov);
    return node.accumulatedError / depth * pixelsPerRadian;
}

struct GpuCut {
    std::vector<uint32_t> nodes;
    uint64_t triangles = 0;
    uint64_t culledTriangles = 0;
    double milliseconds = 0.0;
};

GpuCut selectOnGpu(Context const& context, mm::GpuLodBuffer const& buffer,
        ComputeParams const& params) {
    auto* api = mmgpu::api();
    GpuCut result;
    uint32_t const nodeCount = uint32_t(buffer.nodes.size());
    if (nodeCount == 0) {
        return result;
    }

    Buffer nodeBuffer = createBuffer(context, VkDeviceSize(nodeCount) * sizeof(mm::GpuLodNode),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer selectedBuffer = createBuffer(context, VkDeviceSize(nodeCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer counterBuffer = createBuffer(context, 3u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(nodeBuffer.mapped, buffer.nodes.data(),
            VkDeviceSize(nodeCount) * sizeof(mm::GpuLodNode));
    std::memset(selectedBuffer.mapped, 0, VkDeviceSize(nodeCount) * sizeof(uint32_t));
    std::memset(counterBuffer.mapped, 0, 3u * sizeof(uint32_t));

    VkDescriptorSetLayoutBinding bindings[3]{};
    for (uint32_t i = 0; i < 3; ++i) {
        bindings[i].binding = i;
        bindings[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        bindings[i].descriptorCount = 1;
        bindings[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    }
    VkDescriptorSetLayoutCreateInfo setLayoutInfo{
        VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO
    };
    setLayoutInfo.bindingCount = 3;
    setLayoutInfo.pBindings = bindings;
    VkDescriptorSetLayout setLayout = VK_NULL_HANDLE;
    check(api->CreateDescriptorSetLayout(context.device, &setLayoutInfo, nullptr, &setLayout),
            "vkCreateDescriptorSetLayout failed");

    VkPushConstantRange range{};
    range.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    range.offset = 0;
    range.size = sizeof(ComputeParams);
    VkPipelineLayoutCreateInfo pipelineLayoutInfo{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &setLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &range;
    VkPipelineLayout pipelineLayout = VK_NULL_HANDLE;
    check(api->CreatePipelineLayout(context.device, &pipelineLayoutInfo, nullptr, &pipelineLayout),
            "vkCreatePipelineLayout failed");

    std::vector<uint32_t> const spirv =
            compileGlsl(EShLangCompute, mmgpu::LOD_SELECT_GLSL, "lod_select");
    VkShaderModule module = createShaderModule(context, spirv);
    VkComputePipelineCreateInfo pipelineInfo{ VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO };
    pipelineInfo.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    pipelineInfo.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    pipelineInfo.stage.module = module;
    pipelineInfo.stage.pName = "main";
    pipelineInfo.layout = pipelineLayout;
    VkPipeline pipeline = VK_NULL_HANDLE;
    check(api->CreateComputePipelines(context.device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr,
                  &pipeline),
            "vkCreateComputePipelines failed");

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 1;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr, &descriptorPool),
            "vkCreateDescriptorPool failed");
    VkDescriptorSetAllocateInfo allocateInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    allocateInfo.descriptorPool = descriptorPool;
    allocateInfo.descriptorSetCount = 1;
    allocateInfo.pSetLayouts = &setLayout;
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
    check(api->AllocateDescriptorSets(context.device, &allocateInfo, &descriptorSet),
            "vkAllocateDescriptorSets failed");

    VkDescriptorBufferInfo bufferInfos[3]{};
    bufferInfos[0] = { nodeBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[1] = { selectedBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[2] = { counterBuffer.buffer, 0, VK_WHOLE_SIZE };
    VkWriteDescriptorSet writes[3]{};
    for (uint32_t i = 0; i < 3; ++i) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = descriptorSet;
        writes[i].dstBinding = i;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        writes[i].pBufferInfo = &bufferInfos[i];
    }
    api->UpdateDescriptorSets(context.device, 3, writes, 0, nullptr);

    auto const start = std::chrono::steady_clock::now();
    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipelineLayout, 0, 1,
            &descriptorSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, pipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
            sizeof(ComputeParams), &params);
    api->CmdDispatch(commandBuffer, (nodeCount + 63u) / 64u, 1, 1);
    VkMemoryBarrier readbackBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    readbackBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readbackBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &readbackBarrier, 0, nullptr, 0, nullptr);
    submitAndWait(context, commandBuffer);
    auto const end = std::chrono::steady_clock::now();
    result.milliseconds = std::chrono::duration<double, std::milli>(end - start).count();

    uint32_t const* counters = static_cast<uint32_t const*>(counterBuffer.mapped);
    uint32_t const selectedCount = std::min(counters[0], nodeCount);
    uint32_t const* selected = static_cast<uint32_t const*>(selectedBuffer.mapped);
    result.nodes.assign(selected, selected + selectedCount);
    std::sort(result.nodes.begin(), result.nodes.end());
    result.triangles = counters[1];
    result.culledTriangles = counters[2];

    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
    api->DestroyPipeline(context.device, pipeline, nullptr);
    api->DestroyShaderModule(context.device, module, nullptr);
    api->DestroyPipelineLayout(context.device, pipelineLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, setLayout, nullptr);
    destroyBuffer(context, &counterBuffer);
    destroyBuffer(context, &selectedBuffer);
    destroyBuffer(context, &nodeBuffer);
    return result;
}

struct GpuVisibility {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint32_t> nodeIds;
    std::vector<uint32_t> triangleIds;
    std::vector<float> depth;
    uint32_t coveredPixels = 0;
    uint32_t drawCommands = 0;
};

GpuVisibility rasterizeOnGpu(Context const& context, mm::Mesh const& mesh,
        mm::GpuLodBuffer const& buffer, std::vector<uint32_t> const& nodes,
        mm::ViewCamera const& camera, uint32_t width, uint32_t height) {
    auto* api = mmgpu::api();
    GpuVisibility result;
    result.width = width;
    result.height = height;
    size_t const pixelCount = size_t(width) * height;
    result.nodeIds.assign(pixelCount, UINT32_MAX);
    result.triangleIds.assign(pixelCount, UINT32_MAX);
    result.depth.assign(pixelCount, 1.0f);

    CameraBasis const basis = makeBasis(camera);
    if (!basis.valid || mesh.positions.empty() || nodes.empty()) {
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

    Buffer vertexBuffer = createBuffer(context,
            VkDeviceSize(mesh.positions.size()) * sizeof(float3),
            VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(vertexBuffer.mapped, mesh.positions.data(),
            size_t(mesh.positions.size()) * sizeof(float3));
    Buffer indexBuffer = createBuffer(context,
            VkDeviceSize(buffer.indices.size()) * sizeof(uint32_t),
            VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(indexBuffer.mapped, buffer.indices.data(),
            size_t(buffer.indices.size()) * sizeof(uint32_t));

    Buffer nodeDataBuffer = createBuffer(context,
            VkDeviceSize(buffer.nodes.size()) * sizeof(mm::GpuLodNode),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(nodeDataBuffer.mapped, buffer.nodes.data(),
            size_t(buffer.nodes.size()) * sizeof(mm::GpuLodNode));

    mm::LodGraphSelection drawSelection;
    drawSelection.nodes = nodes;
    std::vector<mm::GpuDrawIndexedIndirectCommand> const commands =
            mm::buildIndirectDraws(buffer, drawSelection);
    result.drawCommands = uint32_t(commands.size());
    Buffer indirectBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(commands.size(), 1)) *
                    sizeof(mm::GpuDrawIndexedIndirectCommand),
            VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (!commands.empty()) {
        std::memcpy(indirectBuffer.mapped, commands.data(),
                size_t(commands.size()) * sizeof(mm::GpuDrawIndexedIndirectCommand));
    }

    Image color0 = createImage(context, width, height, VK_FORMAT_R32_UINT,
            VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
    Image color1 = createImage(context, width, height, VK_FORMAT_R32_UINT,
            VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
    Image depth = createImage(context, width, height, VK_FORMAT_D32_SFLOAT,
            VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);

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
    dependencies[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                    VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    dependencies[1].srcSubpass = 0;
    dependencies[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                                   VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    dependencies[1].dstStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    dependencies[1].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                    VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    dependencies[1].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    VkRenderPassCreateInfo renderPassInfo{ VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO };
    renderPassInfo.attachmentCount = 3;
    renderPassInfo.pAttachments = attachments;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;
    renderPassInfo.dependencyCount = 2;
    renderPassInfo.pDependencies = dependencies;
    VkRenderPass renderPass = VK_NULL_HANDLE;
    check(api->CreateRenderPass(context.device, &renderPassInfo, nullptr, &renderPass),
            "vkCreateRenderPass failed");

    VkImageView views[3] = { color0.view, color1.view, depth.view };
    VkFramebufferCreateInfo framebufferInfo{ VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO };
    framebufferInfo.renderPass = renderPass;
    framebufferInfo.attachmentCount = 3;
    framebufferInfo.pAttachments = views;
    framebufferInfo.width = width;
    framebufferInfo.height = height;
    framebufferInfo.layers = 1;
    VkFramebuffer framebuffer = VK_NULL_HANDLE;
    check(api->CreateFramebuffer(context.device, &framebufferInfo, nullptr, &framebuffer),
            "vkCreateFramebuffer failed");

    std::vector<uint32_t> const vertexSpirv =
            compileGlsl(EShLangVertex, mmgpu::VISIBILITY_VERT_GLSL, "visibility.vert");
    std::vector<uint32_t> const fragmentSpirv =
            compileGlsl(EShLangFragment, mmgpu::VISIBILITY_FRAG_GLSL, "visibility.frag");
    VkShaderModule vertexModule = createShaderModule(context, vertexSpirv);
    VkShaderModule fragmentModule = createShaderModule(context, fragmentSpirv);

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
    VkDescriptorSetLayout setLayout = VK_NULL_HANDLE;
    check(api->CreateDescriptorSetLayout(context.device, &setLayoutInfo, nullptr, &setLayout),
            "vkCreateDescriptorSetLayout failed");

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 1;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr, &descriptorPool),
            "vkCreateDescriptorPool failed");
    VkDescriptorSetAllocateInfo allocateInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    allocateInfo.descriptorPool = descriptorPool;
    allocateInfo.descriptorSetCount = 1;
    allocateInfo.pSetLayouts = &setLayout;
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
    check(api->AllocateDescriptorSets(context.device, &allocateInfo, &descriptorSet),
            "vkAllocateDescriptorSets failed");
    VkDescriptorBufferInfo nodeInfo{ nodeDataBuffer.buffer, 0, VK_WHOLE_SIZE };
    VkWriteDescriptorSet write{ VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET };
    write.dstSet = descriptorSet;
    write.dstBinding = 0;
    write.descriptorCount = 1;
    write.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    write.pBufferInfo = &nodeInfo;
    api->UpdateDescriptorSets(context.device, 1, &write, 0, nullptr);

    VkPushConstantRange pushRange{};
    pushRange.stageFlags = VK_SHADER_STAGE_VERTEX_BIT;
    pushRange.offset = 0;
    pushRange.size = sizeof(VisibilityParams);
    VkPipelineLayoutCreateInfo pipelineLayoutInfo{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &setLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &pushRange;
    VkPipelineLayout pipelineLayout = VK_NULL_HANDLE;
    check(api->CreatePipelineLayout(context.device, &pipelineLayoutInfo, nullptr, &pipelineLayout),
            "vkCreatePipelineLayout failed");

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vertexModule;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = fragmentModule;
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
    pipelineInfo.layout = pipelineLayout;
    pipelineInfo.renderPass = renderPass;
    pipelineInfo.subpass = 0;
    VkPipeline pipeline = VK_NULL_HANDLE;
    check(api->CreateGraphicsPipelines(context.device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr,
                  &pipeline),
            "vkCreateGraphicsPipelines failed");

    Buffer nodeReadback = createBuffer(context, VkDeviceSize(pixelCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer triangleReadback = createBuffer(context, VkDeviceSize(pixelCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer depthReadback = createBuffer(context, VkDeviceSize(pixelCount) * sizeof(float),
            VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);
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
    api->CmdBeginRenderPass(commandBuffer, &begin, VK_SUBPASS_CONTENTS_INLINE);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, pipelineLayout, 0,
            1, &descriptorSet, 0, nullptr);
    api->CmdPushConstants(commandBuffer, pipelineLayout, VK_SHADER_STAGE_VERTEX_BIT, 0,
            sizeof(VisibilityParams), &params);
    VkDeviceSize const vertexOffset = 0;
    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &vertexBuffer.buffer, &vertexOffset);
    api->CmdBindIndexBuffer(commandBuffer, indexBuffer.buffer, 0, VK_INDEX_TYPE_UINT32);
    if (!commands.empty()) {
        api->CmdDrawIndexedIndirect(commandBuffer, indirectBuffer.buffer, 0,
                uint32_t(commands.size()), sizeof(mm::GpuDrawIndexedIndirectCommand));
    }
    api->CmdEndRenderPass(commandBuffer);

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

    std::memcpy(result.nodeIds.data(), nodeReadback.mapped, pixelCount * sizeof(uint32_t));
    std::memcpy(result.triangleIds.data(), triangleReadback.mapped, pixelCount * sizeof(uint32_t));
    std::memcpy(result.depth.data(), depthReadback.mapped, pixelCount * sizeof(float));
    for (uint32_t id: result.nodeIds) {
        result.coveredPixels += id == UINT32_MAX ? 0u : 1u;
    }

    destroyBuffer(context, &depthReadback);
    destroyBuffer(context, &triangleReadback);
    destroyBuffer(context, &nodeReadback);
    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
    api->DestroyPipeline(context.device, pipeline, nullptr);
    api->DestroyPipelineLayout(context.device, pipelineLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, setLayout, nullptr);
    api->DestroyShaderModule(context.device, fragmentModule, nullptr);
    api->DestroyShaderModule(context.device, vertexModule, nullptr);
    api->DestroyFramebuffer(context.device, framebuffer, nullptr);
    api->DestroyRenderPass(context.device, renderPass, nullptr);
    destroyImage(context, &depth);
    destroyImage(context, &color1);
    destroyImage(context, &color0);
    destroyBuffer(context, &indirectBuffer);
    destroyBuffer(context, &nodeDataBuffer);
    destroyBuffer(context, &indexBuffer);
    destroyBuffer(context, &vertexBuffer);
    return result;
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
    file.write(reinterpret_cast<char const*>(pixels.data()),
            std::streamsize(pixels.size()));
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
    file.write(reinterpret_cast<char const*>(pixels.data()),
            std::streamsize(pixels.size()));
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
    bool hasEye = false;
    bool hasTarget = false;
    float3 eye{ 0.0f, 0.0f, 3.0f };
    float3 target{ 0.0f, 0.0f, 0.0f };
};

void printUsage() {
    std::printf(
            "Usage: mmgpu <mesh> [options]\n"
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
            "  --ratio F            Parent triangle ratio (default: 0.5)\n");
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
            options.width = uint32_t(std::strtoul(nextValue(argc, argv, &i, "--width"),
                    nullptr, 10));
        } else if (argument == "--height") {
            options.height = uint32_t(std::strtoul(nextValue(argc, argv, &i, "--height"),
                    nullptr, 10));
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
            options.thresholdPx =
                    std::strtof(nextValue(argc, argv, &i, "--threshold-px"), nullptr);
        } else if (argument == "--levels") {
            options.levels = uint32_t(std::strtoul(nextValue(argc, argv, &i, "--levels"),
                    nullptr, 10));
        } else if (argument == "--clusters") {
            options.clustersPerNode = uint32_t(std::strtoul(
                    nextValue(argc, argv, &i, "--clusters"), nullptr, 10));
        } else if (argument == "--ratio") {
            options.ratio = std::strtof(nextValue(argc, argv, &i, "--ratio"), nullptr);
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
            options.ratio <= 0.0f || options.ratio > 1.0f) {
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
        auto const graphStart = std::chrono::steady_clock::now();
        mm::LodGraph const graph = mm::buildLodGraph(mesh, lodOptions);
        auto const graphEnd = std::chrono::steady_clock::now();
        if (graph.nodes.empty()) {
            std::fprintf(stderr, "mmgpu: DAG construction produced no nodes\n");
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
        mm::LodGraphCut const cpuCut = mm::selectLodGraphCut(graph, camera, options.thresholdPx);
        auto const cpuEnd = std::chrono::steady_clock::now();
        double const cpuMilliseconds =
                std::chrono::duration<double, std::milli>(cpuEnd - cpuStart).count();

        ComputeParams const computeParams = makeComputeParams(camera, basis,
                options.thresholdPx, uint32_t(buffer.nodes.size()));
        GpuCut const gpuCut = selectOnGpu(context, buffer, computeParams);

        std::vector<uint32_t> cpuNodes = cpuCut.nodes;
        std::sort(cpuNodes.begin(), cpuNodes.end());
        bool const nodesMatch = cpuNodes == gpuCut.nodes;
        bool const trianglesMatch = cpuCut.selectedTriangles == gpuCut.triangles;
        bool const culledMatch = cpuCut.culledTriangles == gpuCut.culledTriangles;

        mm::LodGraphSelection cpuSelection;
        cpuSelection.nodes = cpuCut.nodes;
        mm::VisibilityBuffer const cpuVisibility =
                mm::rasterizeVisibility(mesh, buffer, cpuSelection, camera);
        GpuVisibility const gpuVisibility = rasterizeOnGpu(context, mesh, buffer, gpuCut.nodes,
                camera, options.width, options.height);

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

        std::printf("mesh: %s (%zu vertices, %zu triangles)\n", options.meshPath.c_str(),
                mesh.positions.size(), mesh.indices.size() / 3);
        std::printf("dag: %zu nodes, %zu indices, %zu levels (%.2f ms)\n", graph.nodes.size(),
                buffer.indices.size(), size_t(graph.levelCount),
                std::chrono::duration<double, std::milli>(graphEnd - graphStart).count());
        std::printf("camera: eye %.3f,%.3f,%.3f target %.3f,%.3f,%.3f fov %.2f deg\n",
                camera.eye.x, camera.eye.y, camera.eye.z, camera.target.x, camera.target.y,
                camera.target.z, options.fovDegrees);
        std::printf("cut: cpu %zu nodes / %llu tris (%.3f ms), gpu %zu nodes / %llu tris "
                    "(%.3f ms)\n",
                cpuNodes.size(), (unsigned long long) cpuCut.selectedTriangles, cpuMilliseconds,
                gpuCut.nodes.size(), (unsigned long long) gpuCut.triangles,
                gpuCut.milliseconds);
        std::printf("selection: nodes %s, triangles %s, culled %s (cpu %llu, gpu %llu)\n",
                nodesMatch ? "match" : "MISMATCH", trianglesMatch ? "match" : "MISMATCH",
                culledMatch ? "match" : "MISMATCH", (unsigned long long) cpuCut.culledTriangles,
                (unsigned long long) gpuCut.culledTriangles);
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
        std::printf("visibility: only cpu %llu, only gpu %llu\n",
                (unsigned long long) onlyCpu, (unsigned long long) onlyGpu);
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
                            node.accumulatedError,
                            gpuNodeScreenError(node, camera, basis));
                    current = node.parent;
                }
                inspected += 1;
            }
        }

        destroyContext(&context);
        glslang::FinalizeProcess();
        return nodesMatch && trianglesMatch ? 0 : 2;
    } catch (std::exception const& exception) {
        std::fprintf(stderr, "mmgpu: %s\n", exception.what());
        return 1;
    }
}
