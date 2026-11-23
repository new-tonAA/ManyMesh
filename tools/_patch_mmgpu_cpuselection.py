from pathlib import Path
p = Path('tools/mmgpu/src/main.cpp')
s = p.read_text(encoding='utf-8')
def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)
rep('''        auto const cpuStart = std::chrono::steady_clock::now();
        mm::LodGraphCut const cpuCut = mm::selectLodGraphCut(graph, camera, options.thresholdPx);
        auto const cpuEnd = std::chrono::steady_clock::now();
        double const cpuMilliseconds =
                std::chrono::duration<double, std::milli>(cpuEnd - cpuStart).count();
''', '''        auto const cpuStart = std::chrono::steady_clock::now();
        mm::LodGraphSelection const cpuSelection =
                mm::selectLodGraph(graph, camera, options.thresholdPx);
        auto const cpuEnd = std::chrono::steady_clock::now();
        double const cpuMilliseconds =
                std::chrono::duration<double, std::milli>(cpuEnd - cpuStart).count();
''')
rep('''        std::vector<uint32_t> cpuNodes = cpuCut.nodes;
        std::sort(cpuNodes.begin(), cpuNodes.end());
        bool const nodesMatch = cpuNodes == gpuCut.nodes;
        bool const trianglesMatch = cpuCut.selectedTriangles == gpuCut.triangles;
        bool const culledMatch = cpuCut.culledTriangles == gpuCut.culledTriangles;

        mm::LodGraphSelection cpuSelection;
        cpuSelection.nodes = cpuCut.nodes;
        mm::LodGraphCutGeometry const cpuCompact = mm::compactLodSelection(graph, cpuSelection);
''', '''        std::vector<uint32_t> cpuNodes = cpuSelection.nodes;
        std::sort(cpuNodes.begin(), cpuNodes.end());
        bool const nodesMatch = cpuNodes == gpuCut.nodes;
        bool const trianglesMatch = cpuSelection.selectedTriangles == gpuCut.triangles;
        bool const culledMatch = cpuSelection.culledTriangles == gpuCut.culledTriangles;

        mm::LodGraphCutGeometry const cpuCompact = mm::compactLodSelection(graph, cpuSelection);
''')
rep('''                cpuNodes.size(), (unsigned long long) cpuCut.selectedTriangles, cpuMilliseconds,
''', '''                cpuNodes.size(), (unsigned long long) cpuSelection.selectedTriangles,
                cpuMilliseconds,
''')
rep('''                culledMatch ? "match" : "MISMATCH", (unsigned long long) cpuCut.culledTriangles,
''', '''                culledMatch ? "match" : "MISMATCH",
                (unsigned long long) cpuSelection.culledTriangles,
''')
p.write_text(s, encoding='utf-8')
print('cpu selection patched')
