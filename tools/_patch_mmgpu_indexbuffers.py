from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
old = '''    Buffer indexBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(buffer.indices.size(), 1)) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
'''
new = '''    Buffer sourceIndexBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(buffer.indices.size(), 1)) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    Buffer compactedIndexBuffer = createBuffer(context,
            VkDeviceSize(std::max<size_t>(buffer.indices.size(), 1)) * sizeof(uint32_t),
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
'''
assert old in s
s = s.replace(old, new, 1)
old = '''    std::memcpy(indexBuffer.mapped, buffer.indices.data(),
            size_t(buffer.indices.size()) * sizeof(uint32_t));
'''
new = '''    std::memcpy(sourceIndexBuffer.mapped, buffer.indices.data(),
            size_t(buffer.indices.size()) * sizeof(uint32_t));
'''
assert old in s
s = s.replace(old, new, 1)
old = '''    bufferInfos[3] = { indexBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[4] = { indexBuffer.buffer, 0, VK_WHOLE_SIZE };
'''
new = '''    bufferInfos[3] = { sourceIndexBuffer.buffer, 0, VK_WHOLE_SIZE };
    bufferInfos[4] = { compactedIndexBuffer.buffer, 0, VK_WHOLE_SIZE };
'''
assert old in s
s = s.replace(old, new, 1)
old = '''    uint32_t const* compacted = static_cast<uint32_t const*>(indexBuffer.mapped);
'''
new = '''    uint32_t const* compacted = static_cast<uint32_t const*>(compactedIndexBuffer.mapped);
'''
assert old in s
s = s.replace(old, new, 1)
old = '''    result.compactedIndexBuffer = indexBuffer;
    result.indirectBuffer = indirectBuffer;
'''
new = '''    result.compactedIndexBuffer = compactedIndexBuffer;
    result.indirectBuffer = indirectBuffer;
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
    destroyBuffer(context, &sourceIndexBuffer);
    destroyBuffer(context, &nodeBuffer);
    return result;
'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('index buffers split')
