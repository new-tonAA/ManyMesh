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

#include "VulkanApi.h"

#if defined(_WIN32)
#include <windows.h>
#endif

namespace mmgpu {

namespace {

void* loader() {
#if defined(_WIN32)
    static HMODULE module = LoadLibraryA("vulkan-1.dll");
    return module;
#else
    return nullptr;
#endif
}

void* symbol(void* handle, char const* name) {
#if defined(_WIN32)
    return handle ? reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(handle), name))
                  : nullptr;
#else
    (void)handle;
    (void)name;
    return nullptr;
#endif
}

} // namespace

bool VulkanApi::loadInstanceFunctions() {
    void* handle = loader();
    if (handle == nullptr) {
        return false;
    }
    GetInstanceProcAddr =
            reinterpret_cast<PFN_vkGetInstanceProcAddr>(symbol(handle, "vkGetInstanceProcAddr"));
    if (GetInstanceProcAddr == nullptr) {
        return false;
    }
    CreateInstance = reinterpret_cast<PFN_vkCreateInstance>(
            GetInstanceProcAddr(nullptr, "vkCreateInstance"));
    return CreateInstance != nullptr;
}

bool VulkanApi::loadDeviceFunctions(VkInstance instance) {
    if (GetInstanceProcAddr == nullptr || instance == VK_NULL_HANDLE) {
        return false;
    }

#define MMGPU_LOAD(name)                                                    \
    name = reinterpret_cast<PFN_vk##name>(GetInstanceProcAddr(instance, "vk" #name)); \
    if (name == nullptr) {                                                  \
        return false;                                                       \
    }

    MMGPU_LOAD(DestroyInstance)
    MMGPU_LOAD(EnumeratePhysicalDevices)
    MMGPU_LOAD(GetPhysicalDeviceProperties)
    MMGPU_LOAD(GetPhysicalDeviceQueueFamilyProperties)
    MMGPU_LOAD(GetPhysicalDeviceMemoryProperties)
    MMGPU_LOAD(CreateDevice)
    MMGPU_LOAD(DestroyDevice)
    MMGPU_LOAD(GetDeviceQueue)

    MMGPU_LOAD(CreateBuffer)
    MMGPU_LOAD(DestroyBuffer)
    MMGPU_LOAD(GetBufferMemoryRequirements)
    MMGPU_LOAD(AllocateMemory)
    MMGPU_LOAD(FreeMemory)
    MMGPU_LOAD(BindBufferMemory)
    MMGPU_LOAD(MapMemory)
    MMGPU_LOAD(UnmapMemory)

    MMGPU_LOAD(CreateShaderModule)
    MMGPU_LOAD(DestroyShaderModule)
    MMGPU_LOAD(CreateDescriptorSetLayout)
    MMGPU_LOAD(DestroyDescriptorSetLayout)
    MMGPU_LOAD(CreatePipelineLayout)
    MMGPU_LOAD(DestroyPipelineLayout)
    MMGPU_LOAD(CreateComputePipelines)
    MMGPU_LOAD(CreateGraphicsPipelines)
    MMGPU_LOAD(DestroyPipeline)

    MMGPU_LOAD(CreateDescriptorPool)
    MMGPU_LOAD(DestroyDescriptorPool)
    MMGPU_LOAD(AllocateDescriptorSets)
    MMGPU_LOAD(UpdateDescriptorSets)

    MMGPU_LOAD(CreateCommandPool)
    MMGPU_LOAD(DestroyCommandPool)
    MMGPU_LOAD(AllocateCommandBuffers)
    MMGPU_LOAD(FreeCommandBuffers)
    MMGPU_LOAD(BeginCommandBuffer)
    MMGPU_LOAD(EndCommandBuffer)
    MMGPU_LOAD(CmdBindPipeline)
    MMGPU_LOAD(CmdBindDescriptorSets)
    MMGPU_LOAD(CmdDispatch)
    MMGPU_LOAD(CmdPipelineBarrier)
    MMGPU_LOAD(CmdPushConstants)
    MMGPU_LOAD(CmdBindVertexBuffers)
    MMGPU_LOAD(CmdBindIndexBuffer)
    MMGPU_LOAD(CmdDrawIndexed)
    MMGPU_LOAD(CmdDrawIndexedIndirect)
    MMGPU_LOAD(CmdBeginRenderPass)
    MMGPU_LOAD(CmdEndRenderPass)
    MMGPU_LOAD(CmdCopyImageToBuffer)

    MMGPU_LOAD(QueueSubmit)
    MMGPU_LOAD(QueueWaitIdle)
    MMGPU_LOAD(CreateFence)
    MMGPU_LOAD(DestroyFence)
    MMGPU_LOAD(WaitForFences)
    MMGPU_LOAD(ResetFences)

    MMGPU_LOAD(CreateImage)
    MMGPU_LOAD(DestroyImage)
    MMGPU_LOAD(GetImageMemoryRequirements)
    MMGPU_LOAD(BindImageMemory)
    MMGPU_LOAD(CreateImageView)
    MMGPU_LOAD(DestroyImageView)
    MMGPU_LOAD(CreateRenderPass)
    MMGPU_LOAD(DestroyRenderPass)
    MMGPU_LOAD(CreateFramebuffer)
    MMGPU_LOAD(DestroyFramebuffer)

#undef MMGPU_LOAD

    return true;
}

VulkanApi* api() {
    static VulkanApi instance;
    return &instance;
}

} // namespace mmgpu
