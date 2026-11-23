from pathlib import Path
p = Path('tools/mmgpu/src/ShaderSources.h')
s = p.read_text(encoding='utf-8')
marker = '''} // namespace mmgpu
'''
addition = '''//! First pass of GPU vertex compaction: claim one compact id per referenced source vertex and
//! rewrite every compacted index to that id. The claim uses a sentinel and atomic exchange so
//! concurrent references to one vertex agree without reserving wasted slots.
inline constexpr char const* COMPACT_INDICES_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;

layout(std430, set = 0, binding = 0) buffer Indices {
    uint indices[];
} indexData;
layout(std430, set = 0, binding = 1) buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 2) buffer Counter {
    uint vertexCount;
} counter;

layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;

const uint EMPTY = 0xFFFFFFFFu;
const uint CLAIMING = 0xFFFFFFFEu;

void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= pc.indexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source >= pc.vertexCount) {
        return;
    }
    uint compact;
    while (true) {
        uint current = atomicCompSwap(vertexMap.map[source], EMPTY, CLAIMING);
        if (current == EMPTY) {
            compact = atomicAdd(counter.vertexCount, 1u);
            atomicExchange(vertexMap.map[source], compact);
            break;
        }
        if (current != CLAIMING) {
            compact = current;
            break;
        }
    }
    indexData.indices[index] = compact;
}
)GLSL";

//! Second pass: gather the claimed vertices into a dense buffer. Unreferenced source vertices
//! keep their EMPTY map entry and are skipped.
inline constexpr char const* COMPACT_VERTICES_GLSL = R"GLSL(
#version 450
layout(local_size_x = 64) in;

layout(std430, set = 0, binding = 0) readonly buffer Positions {
    float positions[];
} sourcePositions;
layout(std430, set = 0, binding = 1) readonly buffer VertexMap {
    uint map[];
} vertexMap;
layout(std430, set = 0, binding = 2) writeonly buffer CompactedPositions {
    float positions[];
} compactedPositions;
layout(std430, set = 0, binding = 3) buffer Counter {
    uint vertexCount;
} counter;

layout(push_constant) uniform Params {
    uint indexCount;
    uint vertexCount;
    uint mode;
    uint padding;
} pc;

void main() {
    uint source = gl_GlobalInvocationID.x;
    if (source >= pc.vertexCount) {
        return;
    }
    uint compact = vertexMap.map[source];
    if (compact == 0xFFFFFFFFu) {
        return;
    }
    compactedPositions.positions[compact * 3u + 0u] = sourcePositions.positions[source * 3u + 0u];
    compactedPositions.positions[compact * 3u + 1u] = sourcePositions.positions[source * 3u + 1u];
    compactedPositions.positions[compact * 3u + 2u] = sourcePositions.positions[source * 3u + 2u];
}
)GLSL";

} // namespace mmgpu
'''
assert marker in s
s = s.replace(marker, addition, 1)
p.write_text(s, encoding='utf-8')
print('vertex compaction shaders added')
