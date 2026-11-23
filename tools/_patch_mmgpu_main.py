from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)

rep('''        GpuCut const gpuCut = selectOnGpu(context, buffer, computeParams);
''', '''        GpuCut gpuCut = selectOnGpu(context, buffer, computeParams);
''')
rep('''        mm::LodGraphSelection cpuSelection;
        cpuSelection.nodes = cpuCut.nodes;
        mm::VisibilityBuffer const cpuVisibility =
                mm::rasterizeVisibility(mesh, buffer, cpuSelection, camera);
        GpuVisibility const gpuVisibility = rasterizeOnGpu(context, mesh, buffer, gpuCut.nodes,
                camera, options.width, options.height);
''', '''        mm::LodGraphSelection cpuSelection;
        cpuSelection.nodes = cpuCut.nodes;
        mm::LodGraphCutGeometry const cpuCompact = mm::compactLodSelection(graph, cpuSelection);
        std::vector<uint32_t> cpuCompacted = cpuCompact.indices;
        std::vector<uint32_t> gpuCompacted = gpuCut.compactedIndices;
        std::sort(cpuCompacted.begin(), cpuCompacted.end());
        std::sort(gpuCompacted.begin(), gpuCompacted.end());
        bool const compactedMatch = cpuCompacted == gpuCompacted;
        bool const commandsMatch = gpuCut.commandCount == gpuCut.nodes.size();
        mm::VisibilityBuffer const cpuVisibility =
                mm::rasterizeVisibility(mesh, buffer, cpuSelection, camera);
        GpuVisibility const gpuVisibility = rasterizeOnGpu(context, mesh, buffer, gpuCut,
                camera, options.width, options.height);
''')
rep('''        std::printf("selection: nodes %s, triangles %s, culled %s (cpu %llu, gpu %llu)\\n",
                nodesMatch ? "match" : "MISMATCH", trianglesMatch ? "match" : "MISMATCH",
                culledMatch ? "match" : "MISMATCH", (unsigned long long) cpuCut.culledTriangles,
                (unsigned long long) gpuCut.culledTriangles);
''', '''        std::printf("selection: nodes %s, triangles %s, culled %s (cpu %llu, gpu %llu)\\n",
                nodesMatch ? "match" : "MISMATCH", trianglesMatch ? "match" : "MISMATCH",
                culledMatch ? "match" : "MISMATCH", (unsigned long long) cpuCut.culledTriangles,
                (unsigned long long) gpuCut.culledTriangles);
        std::printf("compaction: cpu %zu indices, gpu %u indices, gpu %u commands (%s, %s)\\n",
                cpuCompact.indices.size(), gpuCut.compactedIndexCount, gpuCut.commandCount,
                compactedMatch ? "match" : "MISMATCH", commandsMatch ? "match" : "MISMATCH");
''')
rep('''        destroyContext(&context);
        glslang::FinalizeProcess();
        return nodesMatch && trianglesMatch ? 0 : 2;
''', '''        destroyGpuCut(context, &gpuCut);
        destroyContext(&context);
        glslang::FinalizeProcess();
        return nodesMatch && trianglesMatch && compactedMatch && commandsMatch ? 0 : 2;
''')
p.write_text(s, encoding='utf-8')
print('main patched')
