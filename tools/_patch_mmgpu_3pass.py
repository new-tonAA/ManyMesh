from pathlib import Path
p = Path('tools/mmgpu/src/ShaderSources.h')
s = p.read_text(encoding='utf-8')
start = s.index('//! First pass of GPU vertex compaction')
end = s.index('} // namespace mmgpu')
new = r'''//! Vertex compaction pass A: mark every referenced source vertex. One invocation per index;
//! the first reference to a vertex wins the CAS, so no spin loop is needed.
inline constexpr char const* COMPACT_MARK_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) readonly buffer Indices {
    uint indices[];
} indexData;
layout(std430, set = 0, binding = 1) buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 2) buffer Counter {
    uint uniqueCount;
    uint assignedCount;
} counter;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
const uint EMPTY = 0xFFFFFFFFu;
const uint MARK = 0xFFFFFFFEu;
void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= pc.indexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source < pc.vertexCount &&
            atomicCompSwap(vertexMap.map[source], EMPTY, MARK) == EMPTY) {
        atomicAdd(counter.uniqueCount, 1u);
    }
}
)GLSL";

//! Pass B: assign dense ids and gather positions. Iterating every source vertex keeps the
//! assignment deterministic and avoids a second indirection list.
inline constexpr char const* COMPACT_GATHER_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 1) readonly buffer Positions {
    float positions[];
} sourcePositions;
layout(std430, set = 0, binding = 2) writeonly buffer CompactedPositions {
    float positions[];
} compactedPositions;
layout(std430, set = 0, binding = 3) buffer Counter {
    uint uniqueCount;
    uint assignedCount;
} counter;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
const uint MARK = 0xFFFFFFFEu;
void main() {
    uint source = gl_GlobalInvocationID.x;
    if (source >= pc.vertexCount || vertexMap.map[source] != MARK) {
        return;
    }
    uint compact = atomicAdd(counter.assignedCount, 1u);
    vertexMap.map[source] = compact;
    compactedPositions.positions[compact * 3u + 0u] = sourcePositions.positions[source * 3u + 0u];
    compactedPositions.positions[compact * 3u + 1u] = sourcePositions.positions[source * 3u + 1u];
    compactedPositions.positions[compact * 3u + 2u] = sourcePositions.positions[source * 3u + 2u];
}
)GLSL";

//! Pass C: rewrite the compacted index buffer in place. Each invocation owns exactly one index.
inline constexpr char const* COMPACT_REWRITE_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;
layout(std430, set = 0, binding = 0) buffer Indices {
    uint indices[];
} indexData;
layout(std430, set = 0, binding = 1) readonly buffer VertexMap {
    uint map[];
} vertexMap;
layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;
void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= pc.indexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source < pc.vertexCount) {
        indexData.indices[index] = vertexMap.map[source];
    }
}
)GLSL";

'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')
print('three-pass shaders installed')
