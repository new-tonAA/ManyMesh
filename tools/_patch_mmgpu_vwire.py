from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
def rep(old, new):
    global s
    assert old in s, old[:100]
    s = s.replace(old, new, 1)
rep('''    if (!basis.valid || mesh.positions.empty() || cut.nodes.empty() ||
            cut.compactedIndexBuffer.buffer == VK_NULL_HANDLE) {
        return result;
    }
''', '''    if (!basis.valid || mesh.positions.empty() || cut.nodes.empty() ||
            cut.compactedIndexBuffer.buffer == VK_NULL_HANDLE ||
            cut.compactedVertexBuffer.buffer == VK_NULL_HANDLE) {
        return result;
    }
''')
rep('''    Buffer vertexBuffer = createBuffer(context,
            VkDeviceSize(mesh.positions.size()) * sizeof(float3),
            VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(vertexBuffer.mapped, mesh.positions.data(),
            size_t(mesh.positions.size()) * sizeof(float3));
    Buffer nodeDataBuffer = createBuffer(context,
''', '''    Buffer nodeDataBuffer = createBuffer(context,
''')
rep('''    computeBarrier.dstAccessMask = VK_ACCESS_INDEX_READ_BIT |
                                   VK_ACCESS_INDIRECT_COMMAND_READ_BIT;
''', '''    computeBarrier.dstAccessMask = VK_ACCESS_INDEX_READ_BIT |
                                   VK_ACCESS_INDIRECT_COMMAND_READ_BIT |
                                   VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT;
''')
rep('''    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &vertexBuffer.buffer, &vertexOffset);
''', '''    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &cut.compactedVertexBuffer.buffer,
            &vertexOffset);
''')
rep('''    destroyBuffer(context, &nodeDataBuffer);
    destroyBuffer(context, &vertexBuffer);
''', '''    destroyBuffer(context, &nodeDataBuffer);
''')
rep('''        GpuCut gpuCut = selectOnGpu(context, buffer, computeParams);
''', '''        GpuCut gpuCut = selectOnGpu(context, buffer, computeParams);
        compactVerticesOnGpu(context, mesh, &gpuCut);
''')
rep('''        std::printf("compaction: cpu %zu indices, gpu %u indices, gpu %u commands (%s, %s)\\n",
                cpuCompact.indices.size(), gpuCut.compactedIndexCount, gpuCut.commandCount,
                compactedMatch ? "match" : "MISMATCH", commandsMatch ? "match" : "MISMATCH");
''', '''        std::printf("compaction: cpu %zu indices, gpu %u indices, gpu %u commands "
                    "(%s, %s), gpu %u vertices (source %zu)\\n",
                cpuCompact.indices.size(), gpuCut.compactedIndexCount, gpuCut.commandCount,
                compactedMatch ? "match" : "MISMATCH", commandsMatch ? "match" : "MISMATCH",
                gpuCut.compactedVertexCount, mesh.positions.size());
''')
p.write_text(s, encoding='utf-8')
print('raster/main vertex compaction wired')
