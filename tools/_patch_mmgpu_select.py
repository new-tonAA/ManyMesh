from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')

old = '''struct GpuCut {
    std::vector<uint32_t> nodes;
    uint64_t triangles = 0;
    uint64_t culledTriangles = 0;
    double milliseconds = 0.0;
};
'''
new = '''struct GpuCut {
    std::vector<uint32_t> nodes;
    uint64_t triangles = 0;
    uint64_t culledTriangles = 0;
    double milliseconds = 0.0;

    // Buffers written by the compute shader. The draw path consumes these directly.
    Buffer compactedIndexBuffer;
    Buffer indirectBuffer;
    uint32_t compactedIndexCount = 0;
    uint32_t commandCount = 0;

    // Host-side copies used for validation and reporting. The render path does not need them.
    std::vector<uint32_t> compactedIndices;
    std::vector<mm::GpuDrawIndexedIndirectCommand> commands;
};

void destroyGpuCut(Context const& context, GpuCut* cut) {
    destroyBuffer(context, &cut->indirectBuffer);
    destroyBuffer(context, &cut->compactedIndexBuffer);
}
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    Buffer counterBuffer = createBuffer(context, 3u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
'''
new = '''    Buffer counterBuffer = createBuffer(context, 5u * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer indexBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(buffer.indices.size(), 1)) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer indirectBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(nodeCount, 1)) * sizeof(mm::GpuDrawIndexedIndirectCommand),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    std::memcpy(nodeBuffer.mapped, buffer.nodes.data(),
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
'''
new = '''    std::memcpy(nodeBuffer.mapped, buffer.nodes.data(),
            VkDeviceSize(nodeCount) * sizeof(mm::GpuLodNode));
    std::memcpy(indexBuffer.mapped, buffer.indices.data(),
            size_t(buffer.indices.size()) * sizeof(uint32_t));
    std::memset(selectedBuffer.mapped, 0, VkDeviceSize(nodeCount) * sizeof(uint32_t));
    std::memset(counterBuffer.mapped, 0, 5u * sizeof(uint32_t));
    std::memset(indirectBuffer.mapped, 0,
            VkDeviceSize(nodeCount) * sizeof(mm::GpuDrawIndexedIndirectCommand));

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
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3 };
'''
new = '''    VkDescriptorPoolSize poolSize{ VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 6 };
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    VkDescriptorBufferInfo bufferInfos[3]{};
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
'''
new = '''    VkDescriptorBufferInfo bufferInfos[6]{};
    bufferInfos[0] = { nodeBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[1] = { selectedBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[2] = { counterBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[3] = { indexBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[4] = { indexBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[5] = { indirectBuffer.buffer, 0, VK_WHOLE_SIZE };
    // Bindings 4 and 5 write to buffers that the following draw consumes as index and indirect
    // input. They are kept alive in GpuCut instead of being read back and reuploaded.
    VkWriteDescriptorSet writes[6]{};
    for (uint32_t i = 0; i < 6; ++i) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = descriptorSet;
        writes[i].dstBinding = i;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        writes[i].pBufferInfo = &bufferInfos[i];
    }
    api->UpdateDescriptorSets(context.device, 6, writes, 0, nullptr);
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    result.nodes.assign(selected, selected + selectedCount);
    std::sort(result.nodes.begin(), result.nodes.end());
    result.triangles = counters[1];
    result.culledTriangles = counters[2];

    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
'''
new = '''    result.nodes.assign(selected, selected + selectedCount);
    std::sort(result.nodes.begin(), result.nodes.end());
    result.triangles = counters[1];
    result.culledTriangles = counters[2];
    result.compactedIndexCount = std::min(counters[3], uint32_t(buffer.indices.size()));
    result.commandCount = std::min(counters[4], selectedCount);

    uint32_t const* compacted = static_cast<uint32_t const*>(indexBuffer.mapped);
    result.compactedIndices.assign(compacted, compacted + result.compactedIndexCount);
    auto const* commands = static_cast<mm::GpuDrawIndexedIndirectCommand const*>(
            indirectBuffer.mapped);
    result.commands.assign(commands, commands + result.commandCount);
    result.compactedIndexBuffer = indexBuffer;
    result.indirectBuffer = indirectBuffer;

    api->DestroyDescriptorPool(context.device, descriptorPool, nullptr);
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    destroyBuffer(context, &counterBuffer);
    destroyBuffer(context, &selectedBuffer);
    destroyBuffer(context, &nodeBuffer);
    return result;
'''
new = '''    destroyBuffer(context, &counterBuffer);
    destroyBuffer(context, &selectedBuffer);
    destroyBuffer(context, &nodeBuffer);
    return result;
'''
assert old in s

p.write_text(s, encoding='utf-8')
print('select patched')
