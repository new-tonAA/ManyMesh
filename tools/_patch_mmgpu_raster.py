from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')

def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)

rep('''GpuVisibility rasterizeOnGpu(Context const& context, mm::Mesh const& mesh,
        mm::GpuLodBuffer const& buffer, std::vector<uint32_t> const& nodes,
        mm::ViewCamera const& camera, uint32_t width, uint32_t height) {
''', '''GpuVisibility rasterizeOnGpu(Context const& context, mm::Mesh const& mesh,
        mm::GpuLodBuffer const& buffer, GpuCut const& cut,
        mm::ViewCamera const& camera, uint32_t width, uint32_t height) {
''')
rep('''    if (!basis.valid || mesh.positions.empty() || nodes.empty()) {
        return result;
    }
''', '''    if (!basis.valid || mesh.positions.empty() || cut.nodes.empty() ||
            cut.compactedIndexBuffer.buffer == VK_NULL_HANDLE) {
        return result;
    }
''')
rep('''    Buffer indexBuffer = createBuffer(context,
            VkDeviceSize(buffer.indices.size()) * sizeof(uint32_t),
            VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    std::memcpy(indexBuffer.mapped, buffer.indices.data(),
            size_t(buffer.indices.size()) * sizeof(uint32_t));

    Buffer nodeDataBuffer = createBuffer(context,
''', '''    Buffer nodeDataBuffer = createBuffer(context,
''')
rep('''    mm::LodGraphSelection drawSelection;
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

''', '''    result.drawCommands = cut.commandCount;

''')
rep('''    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);
    VkClearValue clears[3]{};
''', '''    VkCommandBuffer commandBuffer = beginCommands(context);
    hostBarrier(commandBuffer);
    // The compacted index buffer and indirect commands were produced by a previous compute
    // submission. Make those shader writes visible to the index/indirect read stages.
    VkMemoryBarrier computeBarrier{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
    computeBarrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    computeBarrier.dstAccessMask = VK_ACCESS_INDEX_READ_BIT |
                                   VK_ACCESS_INDIRECT_COMMAND_READ_BIT;
    api->CmdPipelineBarrier(commandBuffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT, 0, 1, &computeBarrier, 0, nullptr, 0, nullptr);
    VkClearValue clears[3]{};
''')
rep('''    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &vertexBuffer.buffer, &vertexOffset);
    api->CmdBindIndexBuffer(commandBuffer, indexBuffer.buffer, 0, VK_INDEX_TYPE_UINT32);
    if (!commands.empty()) {
        api->CmdDrawIndexedIndirect(commandBuffer, indirectBuffer.buffer, 0,
                uint32_t(commands.size()), sizeof(mm::GpuDrawIndexedIndirectCommand));
    }
''', '''    api->CmdBindVertexBuffers(commandBuffer, 0, 1, &vertexBuffer.buffer, &vertexOffset);
    api->CmdBindIndexBuffer(commandBuffer, cut.compactedIndexBuffer.buffer, 0,
            VK_INDEX_TYPE_UINT32);
    if (cut.commandCount != 0) {
        api->CmdDrawIndexedIndirect(commandBuffer, cut.indirectBuffer.buffer, 0,
                cut.commandCount, sizeof(mm::GpuDrawIndexedIndirectCommand));
    }
''')
rep('''    destroyBuffer(context, &indirectBuffer);
    destroyBuffer(context, &nodeDataBuffer);
    destroyBuffer(context, &indexBuffer);
    destroyBuffer(context, &vertexBuffer);
''', '''    destroyBuffer(context, &nodeDataBuffer);
    destroyBuffer(context, &vertexBuffer);
''')
p.write_text(s, encoding='utf-8')
print('raster patched')
