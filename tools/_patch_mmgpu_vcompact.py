from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
marker = '''struct GpuVisibility {
'''
addition = '''void compactVerticesOnGpu(Context const& context, mm::Mesh const& mesh, GpuCut* cut) {
    auto* api = mmgpu::api();
    uint32_t const sourceVertexCount = uint32_t(mesh.positions.size());
    uint32_t const indexCount = cut->compactedIndexCount;
    if (indexCount == 0 || sourceVertexCount == 0 ||
            cut->compactedIndexBuffer.buffer == VK_NULL_HANDLE) {
        return;
    }

    Buffer sourcePositions = createBuffer(context, VkDeviceSize(sourceVertexCount) * sizeof(float3),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(sourcePositions.mapped, mesh.positions.data(),
            size_t(sourceVertexCount) * sizeof(float3));

    Buffer vertexMap = createBuffer(context, VkDeviceSize(sourceVertexCount) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memset(vertexMap.mapped, 0xFF, size_t(sourceVertexCount) * sizeof(uint32_t));

    Buffer compactedPositions = createBuffer(context,
            VkDeviceSize(sourceVertexCount) * sizeof(float3),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer counter = createBuffer(context, sizeof(uint32_t), VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memset(counter.mapped, 0, sizeof(uint32_t));

    auto makeSetLayout = [&](uint32_t bindingCount, VkDescriptorSetLayout* layout) {
        VkDescriptorSetLayoutBinding bindings[4]{};
        for (uint32_t i = 0; i < bindingCount; ++i) {
            bindings[i].binding = i;
            bindings[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
            bindings[i].descriptorCount = 1;
            bindings[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        }
        VkDescriptorSetLayoutCreateInfo info{
            VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO
        };
        info.bindingCount = bindingCount;
        info.pBindings = bindings;
        check(api->CreateDescriptorSetLayout(context.device, &info, nullptr, layout),
                "vkCreateDescriptorSetLayout (compaction) failed");
    };
    VkDescriptorSetLayout indexSetLayout = VK_NULL_HANDLE;
    VkDescriptorSetLayout vertexSetLayout = VK_NULL_HANDLE;
    makeSetLayout(3, &indexSetLayout);
    makeSetLayout(4, &vertexSetLayout);

    auto makePipelineLayout = [&](VkDescriptorSetLayout setLayout) {
        VkPushConstantRange range{};
        range.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        range.offset = 0;
        range.size = sizeof(CompactParams);
        VkPipelineLayoutCreateInfo info{ VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
        info.setLayoutCount = 1;
        info.pSetLayouts = &setLayout;
        info.pushConstantRangeCount = 1;
        info.pPushConstantRanges = &range;
        VkPipelineLayout layout = VK_NULL_HANDLE;
        check(api->CreatePipelineLayout(context.device, &info, nullptr, &layout),
                "vkCreatePipelineLayout (compaction) failed");
        return layout;
    };
    VkPipelineLayout indexPipelineLayout = makePipelineLayout(indexSetLayout);
    VkPipelineLayout vertexPipelineLayout = makePipelineLayout(vertexSetLayout);

    auto makePipeline = [&](char const* glsl, char const* name, VkPipelineLayout layout,
                                VkShaderModule* module) {
        std::vector<uint32_t> const spirv = compileGlsl(EShLangCompute, glsl, name);
        *module = createShaderModule(context, spirv);
        VkComputePipelineCreateInfo info{ VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO };
        info.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        info.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        info.stage.module = *module;
        info.stage.pName = "main";
        info.layout = layout;
        VkPipeline pipeline = VK_NULL_HANDLE;
        check(api->CreateComputePipelines(context.device, VK_NULL_HANDLE, 1, &info, nullptr,
                      &pipeline),
                "vkCreateComputePipelines (compaction) failed");
        return pipeline;
    };
    VkShaderModule indexModule = VK_NULL_HANDLE;
    VkShaderModule vertexModule = VK_NULL_HANDLE;
    VkPipeline indexPipeline = makePipeline(mmgpu::COMPACT_INDICES_GLSL, "compact_indices",
            indexPipelineLayout, &indexModule);
    VkPipeline vertexPipeline = makePipeline(mmgpu::COMPACT_VERTICES_GLSL, "compact_vertices",
            vertexPipelineLayout, &vertexModule);

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 7 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 2;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr, &descriptorPool),
            "vkCreateDescriptorPool (compaction) failed");

    VkDescriptorSetAllocateInfo allocate{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    allocate.descriptorPool = descriptorPool;
    allocate.descriptorSetCount = 1;
    allocate.pSetLayouts = &indexSetLayout;
    VkDescriptorSet indexSet = VK_NULL_HANDLE;
    check(api->AllocateDescriptorSets(context.device, &allocate, &indexSet),
            "vkAllocateDescriptorSets (index compaction) failed");
    allocate.pSetLayouts = &vertexSetLayout;
    VkDescriptorSet vertexSet = VK_NULL_HANDLE;
    check(api->AllocateDescriptorSets(context.device, &allocate, &vertexSet),
            "vkAllocateDescriptorSets (vertex compaction) failed");

    VkDescriptorBufferInfo indexInfos[3] = {
        { cut->compactedIndexBuffer.buffer, 0, VK_WHOLE_SIZE },
        { vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { counter.buffer, 0, VK_WHOLE_SIZE },
    };
    VkWriteDescriptorSet indexWrites[3]{};
    for (uint32_t i = 0; i < 3; ++i) {
        indexWrites[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        indexWrites[i].dstSet = indexSet;
        indexWrites[i].dstBinding = i;
        indexWrites[i].descriptorCount = 1;
        indexWrites[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        indexWrites[i].pBufferInfo = &indexInfos[i];
    }
    api->UpdateDescriptorSets(context.device, 3, indexWrites, 0, nullptr);

    VkDescriptorBufferInfo vertexInfos[4] = {
        { sourcePositions.buffer, 0, VK_WHOLE_SIZE },
        { vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { compactedPositions.buffer, 0, VK_WHOLE_SIZE },
        { counter.buffer, 0, VK_WHOLE_SIZE },
    };
    VkWriteDescriptorSet vertexWrites[4]{};
    for (uint32_t i = 0; i < 4; ++i) {
        vertexWrites[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        vertexWrites[i].dstSet = vertexSet;
        vertexWrites[i].dstBinding = i;
        vertexWrites[i].descriptorCount = 1;
        vertexWrites[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        vertexWrites[i].pBufferInfo = &vertexInfos[i];
    }
    api->UpdateDescriptorSets(context.device, 4, vertexWrites, 0, nullptr);

    CompactParams params{};
    params.indexCount = indexCount;
    params.vertexCount = sourceVertexCount;
    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);
    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, indexPipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, indexPipelineLayout,
            0, 1, &indexSet, 0, nullptr);
    params.mode = 0;
    api->CmdPushConstants(commandBuffer, indexPipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
            sizeof(CompactParams), &params);
    api->CmdDispatch(commandBuffer, (indexCount + 63u) / 64u, 1, 1);

    VkMemoryBarrier computeBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    computeBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    computeBarrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &computeBarrier, 0, nullptr, 0, nullptr);

    api->CmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, vertexPipeline);
    api->CmdBindDescriptorSets(commandBuffer, VK_PIPELINE_BIND_POINT_COMPUTE, vertexPipelineLayout,
            0, 1, &vertexSet, 0, nullptr);
    params.mode = 1;
    api->CmdPushConstants(commandBuffer, vertexPipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
            sizeof(CompactParams), &params);
    api->CmdDispatch(commandBuffer, (sourceVertexCount + 63u) / 64u, 1, 1);

    VkMemoryBarrier readbackBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    readbackBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readbackBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &readbackBarrier, 0, nullptr, 0, nullptr);
    submitAndWait(context, commandBuffer);

    uint32_t const compactedCount =
            std::min(*static_cast<uint32_t const*>(counter.mapped), sourceVertexCount);
    auto const* rewritten = static_cast<uint32_t const*>(cut->compactedIndexBuffer.mapped);
    for (uint32_t i = 0; i < indexCount; ++i) {
        if (rewritten[i] >= compactedCount) {
            std::fprintf(stderr,
                    "mmgpu: GPU vertex compaction produced index %u >= vertex count %u\\n",
                    rewritten[i], compactedCount);
            break;
        }
    }
    cut->compactedVertexCount = compactedCount;
    cut->compactedVertexBuffer = compactedPositions;

    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
    api->DestroyPipeline(context.device, indexPipeline, nullptr);
    api->DestroyPipeline(context.device, vertexPipeline, nullptr);
    api->DestroyShaderModule(context.device, indexModule, nullptr);
    api->DestroyShaderModule(context.device, vertexModule, nullptr);
    api->DestroyPipelineLayout(context.device, indexPipelineLayout, nullptr);
    api->DestroyPipelineLayout(context.device, vertexPipelineLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, indexSetLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, vertexSetLayout, nullptr);
    destroyBuffer(context, &counter);
    destroyBuffer(context, &vertexMap);
    destroyBuffer(context, &sourcePositions);
}

struct GpuVisibility {
'''
assert marker in s
s = s.replace(marker, addition, 1)
p.write_text(s, encoding='utf-8')
print('vertex compaction function added')
