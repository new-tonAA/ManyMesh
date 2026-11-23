from pathlib import Path
p = Path('tools/mmgpu/src/ShaderSources.h')
s = p.read_text(encoding='utf-8')
start = s.index('void main() {\n    uint index = gl_GlobalInvocationID.x;')
end = s.index('\n}\n)GLSL";', start) + len('\n}\n)GLSL";')
new = '''void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= pc.indexCount) {
        return;
    }
    uint source = indexData.indices[index];
    if (source >= pc.vertexCount) {
        return;
    }
    // Reserve first, then atomically claim the source vertex. A losing claim leaves an unused
    // reserved slot but removes all cross-invocation spinning, which is important on tile-based
    // mobile GPUs and avoids a forward-progress dependency between unrelated invocations.
    uint reserved = atomicAdd(counter.vertexCount, 1u);
    uint previous = atomicCompSwap(vertexMap.map[source], EMPTY, reserved);
    uint compact = previous == EMPTY ? reserved : previous;
    indexData.indices[index] = compact;
}
)GLSL";'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')
print('shader loop removed')
