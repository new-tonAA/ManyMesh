#ifndef TNT_SAMPLES_MM_GPU_CUT_H
#define TNT_SAMPLES_MM_GPU_CUT_H

#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>

#include <filament/Engine.h>

#include <memory>
#include <string>
#include <vector>

#include <stdint.h>

namespace mmbench {

struct GpuCutResult {
    std::vector<uint32_t> nodes;
    uint64_t selectedTriangles = 0;
    uint64_t culledTriangles = 0;
    double wallMs = 0.0;
};

/**
 * Runs ManyMesh DAG cut selection through Filament's backend compute dispatch.
 *
 * This is the bench-harness integration: it uses the private DriverApi because Filament's
 * public RenderableManager API has no compute entry point. The selection itself is the same
 * parent-chain traversal as selectLodGraph(), so the result can drive the CPU render path via
 * assembleLodSelection().
 */
class GpuLodCut {
public:
    GpuLodCut();
    ~GpuLodCut();

    GpuLodCut(GpuLodCut const&) = delete;
    GpuLodCut& operator=(GpuLodCut const&) = delete;

    bool create(filament::Engine& engine, filament::Engine::Backend backend,
            filament::manymesh::GpuLodBuffer const& buffer, std::string* error);

    bool select(filament::Engine& engine, filament::manymesh::ViewCamera const& camera,
            float thresholdPx, GpuCutResult* result, std::string* error);

    void destroy(filament::Engine& engine);

    bool valid() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> mImpl;
};

} // namespace mmbench

#endif // TNT_SAMPLES_MM_GPU_CUT_H
