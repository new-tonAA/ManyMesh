from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
start = s.index('void compactVerticesOnGpu(')
end = s.index('struct GpuVisibility {', start)
new = r'''void compactVerticesOnGpu(Context const& context, mm::Mesh const& mesh, GpuCut* cut) {
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
    std::memset(compactedPositions.mapped, 0, size_t(sourceVertexCount) * sizeof(float3));
    Buffer counter = createBuffer(context, 2u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memset(counter.mapped, 0, 2u * sizeof(uint32_t));

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
    VkDescriptorSetLayout markSetLayout = VK_NULL_HANDLE;
    VkDescriptorSetLayout gatherSetLayout = VK_NULL_HANDLE;
    VkDescriptorSetLayout rewriteSetLayout = VK_NULL_HANDLE;
    makeSetLayout(3, &markSetLayout);
    makeSetLayout(4, &gatherSetLayout);
    makeSetLayout(2, &rewriteSetLayout);

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
    VkPipelineLayout markPipelineLayout = makePipelineLayout(markSetLayout);
    VkPipelineLayout gatherPipelineLayout = makePipelineLayout(gatherSetLayout);
    VkPipelineLayout rewritePipelineLayout = makePipelineLayout(rewriteSetLayout);

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
    VkShaderModule markModule = VK_NULL_HANDLE;
    VkShaderModule gatherModule = VK_NULL_HANDLE;
    VkShaderModule rewriteModule = VK_NULL_HANDLE;
    VkPipeline markPipeline = makePipeline(mmgpu::COMPACT_MARK_GLSL, "compact_mark",
            markPipelineLayout, &markModule);
    VkPipeline gatherPipeline = makePipeline(mmgpu::COMPACT_GATHER_GLSL, "compact_gather",
            gatherPipelineLayout, &gatherModule);
    VkPipeline rewritePipeline = makePipeline(mmgpu::COMPACT_REWRITE_GLSL, "compact_rewrite",
            rewritePipelineLayout, &rewriteModule);

    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 9 };
    VkDescriptorPoolCreateInfo poolInfo{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    poolInfo.maxSets = 3;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = &poolSize;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    check(api->CreateDescriptorPool(context.device, &poolInfo, nullptr, &descriptorPool),
            "vkCreateDescriptorPool (compaction) failed");

    auto allocateSet = [&](VkDescriptorSetLayout layout) {
        VkDescriptorSetAllocateInfo allocate{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
        allocate.descriptorPool = descriptorPool;
        allocate.descriptorSetCount = 1;
        allocate.pSetLayouts = &layout;
        VkDescriptorSet set = VK_NULL_HANDLE;
        check(api->AllocateDescriptorSets(context.device, &allocate, &set),
                "vkAllocateDescriptorSets (compaction) failed");
        return set;
    };
    VkDescriptorSet markSet = allocateSet(markSetLayout);
    VkDescriptorSet gatherSet = allocateSet(gatherSetLayout);
    VkDescriptorSet rewriteSet = allocateSet(rewriteSetLayout);

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
    VkDescriptorBufferInfo markInfos[3] = {
        { cut->compactedIndexBuffer.buffer, 0, VK_WHOLE_SIZE },
        { vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { counter.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(markSet, markInfos, 3);
    VkDescriptorBufferInfo gatherInfos[4] = {
        { vertexMap.buffer, 0, VK_WHOLE_SIZE },
        { sourcePositions.buffer, 0, VK_WHOLE_SIZE },
        { compactedPositions.buffer, 0, VK_WHOLE_SIZE },
        { counter.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(gatherSet, gatherInfos, 4);
    VkDescriptorBufferInfo rewriteInfos[2] = {
        { cut->compactedIndexBuffer.buffer, 0, VK_WHOLE_SIZE },
        { vertexMap.buffer, 0, VK_WHOLE_SIZE },
    };
    updateSet(rewriteSet, rewriteInfos, 2);

    CompactParams params{};
    params.indexCount = indexCount;
    params.vertexCount = sourceVertexCount;
    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);

    auto barrier = [&](VkAccessFlags src, VkAccessFlags dst) {
        VkMemoryBarrier memoryBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
        memoryBarrier.srcAccessMask = src;
        memoryBarrier.dstAccessMask = dst;
        api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &memoryBarrier, 0, nullptr, 0,
                nullptr);
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
    params.mode = 0;
    dispatch(markPipeline, markPipelineLayout, markSet, indexCount);
    barrier(VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT);
    params.mode = 1;
    dispatch(gatherPipeline, gatherPipelineLayout, gatherSet, sourceVertexCount);
    barrier(VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT);
    params.mode = 2;
    dispatch(rewritePipeline, rewritePipelineLayout, rewriteSet, indexCount);

    VkMemoryBarrier readbackBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    readbackBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readbackBarrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &readbackBarrier, 0, nullptr, 0, nullptr);
    submitAndWait(context, commandBuffer);

    uint32_t const* counts = static_cast<uint32_t const*>(counter.mapped);
    uint32_t const compactedCount = std::min(counts[1], sourceVertexCount);
    if (counts[0] != counts[1]) {
        std::fprintf(stderr, "mmgpu: GPU vertex compaction marked %u but assigned %u\n",
                counts[0], counts[1]);
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
    cut->compactedVertexCount = compactedCount;
    cut->compactedVertexBuffer = compactedPositions;

    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
    api->DestroyPipeline(context.device, markPipeline, nullptr);
    api->DestroyPipeline(context.device, gatherPipeline, nullptr);
    api->DestroyPipeline(context.device, rewritePipeline, nullptr);
    api->DestroyShaderModule(context.device, markModule, nullptr);
    api->DestroyShaderModule(context.device, gatherModule, nullptr);
    api->DestroyShaderModule(context.device, rewriteModule, nullptr);
    api->DestroyPipelineLayout(context.device, markPipelineLayout, nullptr);
    api->DestroyPipelineLayout(context.device, gatherPipelineLayout, nullptr);
    api->DestroyPipelineLayout(context.device, rewritePipelineLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, markSetLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, gatherSetLayout, nullptr);
    api->DestroyDescriptorSetLayout(context.device, rewriteSetLayout, nullptr);
    destroyBuffer(context, &counter);
    destroyBuffer(context, &vertexMap);
    destroyBuffer(context, &sourcePositions);
}

'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')
print('three-pass function replaced')
