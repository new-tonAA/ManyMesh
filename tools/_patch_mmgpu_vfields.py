from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
def rep(old, new):
    global s
    assert old in s, old[:100]
    s = s.replace(old, new, 1)
rep('''    Buffer compactedIndexBuffer;
    Buffer indirectBuffer;
    uint32_t compactedIndexCount = 0;
    uint32_t commandCount = 0;
''', '''    Buffer compactedIndexBuffer;
    Buffer compactedVertexBuffer;
    Buffer indirectBuffer;
    uint32_t compactedIndexCount = 0;
    uint32_t compactedVertexCount = 0;
    uint32_t commandCount = 0;
''')
rep('''void destroyGpuCut(Context const& context, GpuCut* cut) {
    destroyBuffer(context, &cut->indirectBuffer);
    destroyBuffer(context, &cut->compactedIndexBuffer);
}
''', '''void destroyGpuCut(Context const& context, GpuCut* cut) {
    destroyBuffer(context, &cut->indirectBuffer);
    destroyBuffer(context, &cut->compactedVertexBuffer);
    destroyBuffer(context, &cut->compactedIndexBuffer);
}
''')
rep('''struct VisibilityParams {
''', '''struct CompactParams {
    uint32_t indexCount;
    uint32_t vertexCount;
    uint32_t mode;
    uint32_t padding;
};

struct VisibilityParams {
''')
rep('''static_assert(sizeof(ComputeParams) == 80, "push constant layout must match lod_select.comp");
''', '''static_assert(sizeof(ComputeParams) == 80, "push constant layout must match lod_select.comp");
static_assert(sizeof(CompactParams) == 16, "push constant layout must match the compaction shaders");
''')
p.write_text(s, encoding='utf-8')
print('cut fields patched')
