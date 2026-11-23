from pathlib import Path
p = Path('tools/mmgpu/src/ShaderSources.h')
s = p.read_text(encoding='utf-8')
old = '''layout(std430, set = 0, binding = 2) buffer Counters {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
} counters;
'''
new = '''layout(std430, set = 0, binding = 2) buffer Counters {
    uint selectedCount;
    uint selectedTriangles;
    uint culledTriangles;
    uint compactedIndexCount;
    uint commandCount;
} counters;

layout(std430, set = 0, binding = 3) readonly buffer MeshIndices {
    uint indices[];
} meshIndices;

layout(std430, set = 0, binding = 4) writeonly buffer CompactedIndices {
    uint indices[];
} compactedIndices;

struct DrawCommand {
    uint indexCount;
    uint instanceCount;
    uint firstIndex;
    uint vertexOffset;
    uint firstInstance;
};
layout(std430, set = 0, binding = 5) writeonly buffer DrawCommands {
    DrawCommand commands[];
} drawCommands;
'''
assert old in s
s = s.replace(old, new, 1)
old2 = '''    if (isSelected) {
        uint slot = atomicAdd(counters.selectedCount, 1u);
        selectionOutput.values[slot] = nodeId;
        atomicAdd(counters.selectedTriangles, self.indexCount / 3u);
    }
'''
new2 = '''    if (isSelected) {
        uint slot = atomicAdd(counters.selectedCount, 1u);
        selectionOutput.values[slot] = nodeId;
        atomicAdd(counters.selectedTriangles, self.indexCount / 3u);

        // Reserve one contiguous range in the compacted index buffer and one indirect command.
        // The subsequent draw reads these buffers directly; no CPU compaction or command build
        // is needed on the runtime path.
        uint compactedOffset = atomicAdd(counters.compactedIndexCount, self.indexCount);
        uint commandSlot = atomicAdd(counters.commandCount, 1u);
        for (uint i = 0u; i < self.indexCount; ++i) {
            compactedIndices.indices[compactedOffset + i] =
                    meshIndices.indices[self.indexOffset + i];
        }
        DrawCommand command;
        command.indexCount = self.indexCount;
        command.instanceCount = 1u;
        command.firstIndex = compactedOffset;
        command.vertexOffset = 0u;
        command.firstInstance = nodeId;
        drawCommands.commands[commandSlot] = command;
    }
'''
assert old2 in s
s = s.replace(old2, new2, 1)
p.write_text(s, encoding='utf-8')
print('shader patched')
