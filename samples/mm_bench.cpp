/*
 * Copyright (C) 2026 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 *  ManyMesh render harness.
 *
 *  Renders one mesh from a fixed camera, with a fixed material and lighting, writes a PNG and
 *  reports frame time statistics. It is the measurement half of ManyMesh: feed it the original
 *  asset and a decimated one and the two PNGs are directly comparable, because everything
 *  except the geometry is pinned.
 *
 *  By default it draws no UI: comparing two screenshots then measures the model, not an
 *  overlay. `--ui` enables an interactive DAG LOD viewer with a savings slider, tier buttons
 *  and a distance-aware (near fine / far coarse) toggle. `--distance-lod --screen-error N`
 *  selects the same distance-aware cut without opening a window.
 *
 *  For geometry comparisons use `--no-shadows`: a low-poly renderable can show false
 *  self-shadowing at grazing light angles, which is a shadow-map artifact rather than a
 *  damaged mesh. Keep a shadow-enabled pass only when validating the rendering integration.
 *
 *  Example:
 *      mm_bench --headless --window-size 1280x720 --fixed-timestep 0.0166667 \
 *               --out lod0.png --eye 2.2,-6.7,220 --target 2.2,-6.7,9.8 mesh.obj
 */

#include "common/arguments.h"

#include "generated/resources/resources.h"

#include <imageio/ImageEncoder.h>

#include <image/ColorTransform.h>
#include <image/LinearImage.h>

#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/Quality.h>
#include <manymesh/Streaming.h>

#include <filamentapp/AssetLoader.h>
#include <filamentapp/DesktopAssetLoader.h>
#include <filamentapp/FilamentApp2.h>
#include <filamentapp/MeshAssimp.h>

#include <filament/Camera.h>
#include <filament/Color.h>
#include <filament/Engine.h>
#include <filament/IndexBuffer.h>
#include <filament/LightManager.h>
#include <filament/Material.h>
#include <filament/MaterialInstance.h>
#include <filament/RenderableManager.h>
#include <filament/Renderer.h>
#include <filament/Scene.h>
#include <filament/Skybox.h>
#include <filament/TransformManager.h>
#include <filament/VertexBuffer.h>
#include <filament/View.h>
#include <filament/Viewport.h>

#include <utils/EntityManager.h>
#include <utils/Path.h>

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <imgui.h>

#include <math/mat3.h>

// Capture support is optional: it only compiles in when the RenderDoc in-application header is
// present, and it only does anything when the process was actually launched through RenderDoc.
#if defined(_WIN32) && __has_include("renderdoc_app.h")
// clang-format off
#include <windows.h>
#include <utils/unwindows.h>
#include "renderdoc_app.h"
// clang-format on
#define MM_BENCH_CAN_CAPTURE 1
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>

using namespace filament;
using namespace filament::math;
using namespace image;
using namespace utils;

using filament::app::AssetLoader;
using filament::app::DisplayManager;
namespace mm = filament::manymesh;

namespace {

struct App {
    SampleConfig config;
    FilamentApp2* filamentApp = nullptr;
};

std::unique_ptr<MeshAssimp> g_meshSet;
std::map<utils::CString, MaterialInstance*> g_meshMaterialInstances;
Material* g_material = nullptr;
MaterialInstance* g_materialInstance = nullptr;
Skybox* g_skybox = nullptr;
Camera* g_camera = nullptr;
Entity g_cameraEntity{};
Entity g_lightEntity{};
Scene* g_scene = nullptr;

FilamentApp2* g_filamentApp = nullptr;
AssetLoader* g_assetLoader = nullptr;
SampleConfig g_config;

// Command line state.
std::string g_outPath = "mm_bench.png";
std::string g_materialPath;
float3 g_eye = { 0.0f, 0.0f, 5.0f };
float3 g_target = { 0.0f, 0.0f, 0.0f };
int g_warmup = 30;
int g_measure = 60;
int g_viewCount = 1;
int g_jitter = 1;
float g_panDegrees = 0.0f;
int g_screenHeightForJitter = 360;
int g_totalCaptures = 1;
bool g_shadows = true;
int g_captureFrame = -1;

// Interactive DAG viewer. The hierarchy is built once from the first positional argument;
// moving the slider selects a different non-overlapping cut and updates the index ranges in a
// persistent buffer instead of recreating the renderable.
bool g_ui = false;
bool g_dag = false;
std::string g_tierName = "balanced";
float g_lodSavings = 0.5f;
bool g_showOriginal = false;
bool g_showMaterialColors = false;
bool g_ignoreQualityCeiling = false;
bool g_autoFrame = false;
//! Distance-aware selection keeps the hierarchy's finest clusters near the camera and promotes
//! a cluster only when its accumulated geometric error is small enough on screen.
bool g_distanceLod = false;
float g_lodScreenErrorPx = 1.5f;
double g_lodSelectionMs = 0.0;
mm::Mesh g_lodMesh;
mm::LodGraph g_lodGraph;
mm::LodGraphSelection g_lodSelection;
mm::LodTier g_lodTier = mm::LodTier::Balanced;
mm::ViewCamera g_lodCamera;
mm::TopologyStats g_lodTopology;
VertexBuffer* g_lodVertexBuffer = nullptr;
Entity g_lodRenderable{};
Box g_lodBounds;
uint32_t g_lodSelectedTriangles = 0;
uint32_t g_lodBaseTriangles = 0;
float g_lodMaxScreenError = 0.0f;
uint64_t g_lodStreamingBytes = 0;
uint32_t g_lodStreamingPages = 0;
float g_streamLatencyMs = 0.0f;
std::string g_streamUrl;
std::string g_streamSavePath;

mm::GpuLodBuffer g_lodGpuBuffer;
std::vector<uint32_t> g_lodNodeFirstIndex;
std::vector<uint32_t> g_lodNodeIndexCount;
uint32_t g_lodPrimitiveCapacity = 0;
IndexBuffer* g_lodIndexBuffer = nullptr;
std::vector<MaterialInstance*> g_lodMaterialInstances;
std::vector<uint32_t> g_lodMaterialIdList;

#if defined(MM_BENCH_CAN_CAPTURE)
RENDERDOC_API_1_6_0* g_renderdoc = nullptr;
#endif

// Frame bookkeeping.
int g_frameCounter = 0;
int g_currentView = 0;
int g_viewFrame = 0;
bool g_capturing = false;
bool g_repositionCamera = true;
std::map<uint32_t, Renderer::FrameInfo> g_frameInfo;
std::vector<double> g_gpuFrameMs;

//! Radical inverse, the building block of the Halton sequence used for the sub pixel offsets.
float halton(int index, int base) {
    float result = 0.0f;
    float fraction = 1.0f;
    while (index > 0) {
        fraction /= float(base);
        result += fraction * float(index % base);
        index /= base;
    }
    return result;
}

//! Camera offset that shifts the image by the given fraction of a pixel.
float3 jitterOffset(int index, float screenHeight) {
    // Offsetting the camera perpendicular to the view direction by one pixel's worth of world
    // space at the target distance shifts the image by exactly one pixel, so a sub pixel
    // offset here is a sub pixel shift there.
    float const fovY = 45.0f * 3.14159265358979323846f / 180.0f;
    float const distance = length(g_eye - g_target);
    float const pixel = 2.0f * distance * std::tan(0.5f * fovY) / std::max(screenHeight, 1.0f);

    float3 const forward = normalize(g_target - g_eye);
    float3 const right = normalize(cross(forward, float3{ 0.0f, 1.0f, 0.0f }));
    float3 const up = cross(right, forward);

    float const x = halton(index + 1, 2) - 0.5f;
    float const y = halton(index + 1, 3) - 0.5f;
    return right * (x * pixel) + up * (y * pixel);
}

float3 eyeForView(int capture) {
    int const view = g_jitter > 1 ? capture / g_jitter : capture;
    int const jitterIndex = g_jitter > 1 ? capture % g_jitter : 0;

    // A pan keeps the eye fixed and turns the view, which is the useful temporal case: with no
    // translation there is no parallax, so the image displacement between two frames is an
    // exact homography that does not depend on depth. History can then be reprojected without
    // a depth buffer at all.
    if (g_panDegrees != 0.0f) {
        // The pan supplies the sub frame variation, so the eye is just this view's orbit
        // position.
        if (g_viewCount <= 1) {
            return g_eye;
        }
        float3 const offset = g_eye - g_target;
        float const angle = 2.0f * 3.14159265358979323846f * float(view) / float(g_viewCount);
        float const c = std::cos(angle);
        float const s = std::sin(angle);
        return g_target +
               float3{ offset.x * c - offset.z * s, offset.y, offset.x * s + offset.z * c };
    }

    if (g_viewCount <= 1) {
        return g_eye + (g_jitter > 1 ? jitterOffset(jitterIndex, float(g_screenHeightForJitter))
                                     : float3{});
    }
    // Orbit around the world up axis through the target, keeping the elevation and distance
    // the caller asked for, so a sweep is a pure azimuthal rotation.
    float3 const offset = g_eye - g_target;
    float const angle = 2.0f * 3.14159265358979323846f * float(view) / float(g_viewCount);
    float const c = std::cos(angle);
    float const s = std::sin(angle);
    float3 const base =
            g_target + float3{ offset.x * c - offset.z * s, offset.y, offset.x * s + offset.z * c };
    if (g_jitter <= 1) {
        return base;
    }
    // Same azimuth, nudged by a sub pixel offset: consecutive frames differ only in where
    // within a pixel they sample, which is what accumulation has to work with.
    float3 const saved = g_eye;
    g_eye = base;
    float3 const jittered = base + jitterOffset(jitterIndex, float(g_screenHeightForJitter));
    g_eye = saved;
    return jittered;
}

float3 targetForView(int capture) {
    if (g_panDegrees == 0.0f) {
        return g_target;
    }
    // The pan runs across the sub frames *within* a view, so one run yields one sequence per
    // azimuth: --views V --jitter N --pan D gives V sequences of N frames, all from a single
    // mesh load.
    int const sub = g_jitter > 1 ? capture % g_jitter : 0;
    float const t = g_jitter > 1 ? float(sub) / float(g_jitter - 1) : 0.5f;
    float const angle = (t - 0.5f) * g_panDegrees * 3.14159265358979323846f / 180.0f;

    float3 const eye = eyeForView(capture);
    float3 const offset = g_target - eye;
    float const c = std::cos(angle);
    float const s = std::sin(angle);
    return eye + float3{ offset.x * c - offset.z * s, offset.y, offset.x * s + offset.z * c };
}

std::string pathForView(std::string const& base, int capture) {
    if (g_viewCount <= 1 && g_jitter <= 1) {
        return base;
    }
    // Insert the indices before the extension: renders_v00.png, or with jitter
    // renders_v00_j03.png, where the view is the camera and j is the sub pixel offset.
    char suffix[24];
    if (g_jitter > 1) {
        snprintf(suffix, sizeof(suffix), "_v%02d_j%02d", capture / g_jitter, capture % g_jitter);
    } else {
        snprintf(suffix, sizeof(suffix), "_v%02d", capture);
    }
    size_t const dot = base.find_last_of('.');
    return dot == std::string::npos ? base + suffix
                                    : base.substr(0, dot) + suffix + base.substr(dot);
}

bool parseVec3(const char* text, float3* out) {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    if (sscanf(text, "%f,%f,%f", &x, &y, &z) != 3) {
        return false;
    }
    *out = { x, y, z };
    return true;
}

double medianOf(std::vector<double> values) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    return values[values.size() / 2];
}

double percentileOf(std::vector<double> const& sorted, double fraction) {
    if (sorted.empty()) {
        return 0.0;
    }
    size_t const index = size_t(fraction * double(sorted.size() - 1) + 0.5);
    return sorted[std::min(index, sorted.size() - 1)];
}

void reportTiming() {
    // Only the GPU duration is reported. The driver thread span is not meaningful here:
    // rendering to an offscreen swap chain never presents, so there is no frame pacing to
    // measure against and the begin/end timestamps are not comparable.
    g_gpuFrameMs.clear();
    for (auto const& [frameId, info]: g_frameInfo) {
        if (info.gpuFrameDuration > 0) {
            g_gpuFrameMs.push_back(double(info.gpuFrameDuration) / 1.0e6);
        }
    }

    if (g_gpuFrameMs.empty()) {
        std::cout << "frame time: no samples (GPU timing unavailable)" << std::endl;
        return;
    }
    std::vector<double> sorted = g_gpuFrameMs;
    std::sort(sorted.begin(), sorted.end());

    printf("frame time over %zu measured frames from %d view(s):\n", g_gpuFrameMs.size(),
            g_viewCount);
    printf("  GPU   median %.3f ms  p99 %.3f ms  max %.3f ms\n", medianOf(g_gpuFrameMs),
            percentileOf(sorted, 0.99), sorted.back());
}

// Reads a compiled material from a file if one was given, otherwise falls back to the lit
// material baked into the sample resources so the harness has no external dependencies.
void createMaterial(Engine* engine, char const* materialPath) {
    if (materialPath == nullptr || materialPath[0] == '\0') {
        // No explicit material: keep what MeshAssimp built for the asset, which is the pairing
        // the geometry was loaded for.
        if (!g_ui && !g_dag) {
            return;
        }
    }
    {
        if (materialPath != nullptr && materialPath[0] != '\0') {
            std::ifstream in(materialPath, std::ifstream::in | std::ios::binary);
            if (in.is_open()) {
                std::vector<char> buffer((std::istreambuf_iterator<char>(in)),
                        std::istreambuf_iterator<char>());
                if (!buffer.empty()) {
                    g_material = Material::Builder()
                                         .package(buffer.data(), buffer.size())
                                         .build(*engine);
                }
            }
            if (g_material == nullptr) {
                std::cerr << "Could not load material '" << materialPath
                          << "', using the built-in one" << std::endl;
            }
        }
    }

    if (g_material == nullptr) {
        g_material = Material::Builder()
                             .package(RESOURCES_AIDEFAULTMAT_DATA, RESOURCES_AIDEFAULTMAT_SIZE)
                             .build(*engine);
    }

    g_materialInstance = g_material->createInstance();

    // Pin every shading input: the comparison is only meaningful if nothing but the geometry
    // changes between two runs.
    if (g_material->hasParameter("baseColor")) {
        g_materialInstance->setParameter("baseColor", RgbType::sRGB, { 0.8f, 0.8f, 0.8f });
    }
    if (g_material->hasParameter("metallic")) {
        g_materialInstance->setParameter("metallic", 0.0f);
    }
    if (g_material->hasParameter("roughness")) {
        g_materialInstance->setParameter("roughness", 0.5f);
    }
    if (g_material->hasParameter("reflectance")) {
        g_materialInstance->setParameter("reflectance", 0.5f);
    }
}

bool loadLodMesh(char const* path, mm::Mesh* mesh) {
    Assimp::Importer importer;
    unsigned int const flags = aiProcess_Triangulate | aiProcess_JoinIdenticalVertices |
                               aiProcess_PreTransformVertices | aiProcess_GenSmoothNormals;
    aiScene const* scene = importer.ReadFile(path, flags);
    if (scene == nullptr || scene->mNumMeshes == 0) {
        std::cerr << "Could not load '" << path << "': " << importer.GetErrorString() << std::endl;
        return false;
    }

    bool hasUVs = false;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        hasUVs = hasUVs || scene->mMeshes[m]->HasTextureCoords(0);
    }

    uint32_t vertexOffset = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        aiMesh const* source = scene->mMeshes[m];
        for (unsigned int v = 0; v < source->mNumVertices; ++v) {
            aiVector3D const& p = source->mVertices[v];
            mesh->positions.push_back({ p.x, p.y, p.z });
            aiVector3D const& n = source->mNormals[v];
            mesh->normals.push_back({ n.x, n.y, n.z });
            if (hasUVs) {
                if (source->HasTextureCoords(0)) {
                    aiVector3D const& uv = source->mTextureCoords[0][v];
                    mesh->uvs.push_back({ uv.x, uv.y });
                } else {
                    mesh->uvs.push_back({ 0.0f, 0.0f });
                }
            }
        }
        for (unsigned int f = 0; f < source->mNumFaces; ++f) {
            aiFace const& face = source->mFaces[f];
            for (unsigned int i = 0; i < face.mNumIndices && i < 3; ++i) {
                mesh->indices.push_back(vertexOffset + face.mIndices[i]);
            }
            mesh->materialIds.push_back(source->mMaterialIndex);
            mesh->submeshIds.push_back(m);
        }
        vertexOffset += source->mNumVertices;
    }
    return !mesh->empty();
}

void destroyLodRenderable(Engine* engine) {
    if (g_scene != nullptr && g_lodRenderable) {
        g_scene->remove(g_lodRenderable);
    }
    if (engine != nullptr) {
        if (g_lodRenderable) {
            engine->destroy(g_lodRenderable);
        }
        if (g_lodIndexBuffer != nullptr) {
            engine->destroy(g_lodIndexBuffer);
        }
    }
    g_lodRenderable = {};
    g_lodIndexBuffer = nullptr;
    g_lodGpuBuffer = {};
    g_lodNodeFirstIndex.clear();
    g_lodNodeIndexCount.clear();
    g_lodPrimitiveCapacity = 0;
}

// One material instance per source material id. The ids themselves are preserved by the
// cluster/LOD pipeline; this only gives them a visible colour so `--show-materials` can prove
// that a selection did not silently merge primitives from different source materials.
void createLodMaterialInstances() {
    g_lodMaterialIdList.clear();
    g_lodMaterialInstances.clear();
    if (g_material == nullptr) {
        return;
    }

    std::vector<uint32_t> ids;
    ids.reserve(g_lodMesh.materialIds.size());
    for (uint32_t id: g_lodMesh.materialIds) {
        if (id != UINT32_MAX) {
            ids.push_back(id);
        }
    }
    std::sort(ids.begin(), ids.end());
    ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
    g_lodMaterialIdList = ids;

    static float3 const palette[] = {
        { 0.85f, 0.35f, 0.30f },
        { 0.30f, 0.65f, 0.35f },
        { 0.25f, 0.45f, 0.85f },
        { 0.85f, 0.70f, 0.25f },
        { 0.65f, 0.35f, 0.75f },
        { 0.25f, 0.75f, 0.80f },
    };
    for (size_t i = 0; i < g_lodMaterialIdList.size(); ++i) {
        MaterialInstance* instance = g_material->createInstance();
        if (instance != nullptr && g_material->hasParameter("baseColor")) {
            float3 const color = palette[i % (sizeof(palette) / sizeof(palette[0]))];
            instance->setParameter("baseColor", RgbType::sRGB, color);
        }
        g_lodMaterialInstances.push_back(instance);
    }
}

MaterialInstance* lodMaterialFor(uint32_t materialId) {
    auto const it = std::find(g_lodMaterialIdList.begin(), g_lodMaterialIdList.end(), materialId);
    if (g_showMaterialColors && it != g_lodMaterialIdList.end()) {
        size_t const index = size_t(std::distance(g_lodMaterialIdList.begin(), it));
        if (index < g_lodMaterialInstances.size()) {
            return g_lodMaterialInstances[index];
        }
    }
    return g_materialInstance;
}

// Flatten every DAG node's index list into one static GPU buffer. A cut then only changes draw
// ranges; unlike the previous path it never rebuilds or re-uploads the index buffer.
void createLodNodeTable() {
    if (!g_lodNodeFirstIndex.empty() || g_lodGraph.nodes.empty()) {
        return;
    }
    g_lodGpuBuffer = mm::flattenLodGraph(g_lodGraph);
    g_lodNodeFirstIndex.resize(g_lodGpuBuffer.nodes.size());
    g_lodNodeIndexCount.resize(g_lodGpuBuffer.nodes.size());
    for (size_t i = 0; i < g_lodGpuBuffer.nodes.size(); ++i) {
        g_lodNodeFirstIndex[i] = g_lodGpuBuffer.nodes[i].indexOffset;
        g_lodNodeIndexCount[i] = g_lodGpuBuffer.nodes[i].indexCount;
    }
    g_lodPrimitiveCapacity = uint32_t(
            std::max<size_t>({ g_lodGraph.leaves.size(), g_lodSelection.nodes.size(), 1 }));
}

void createLodRenderable(Engine* engine) {
    if (engine == nullptr || g_materialInstance == nullptr || g_scene == nullptr ||
            g_lodRenderable) {
        return;
    }
    createLodNodeTable();
    if (g_lodGpuBuffer.indices.empty() || g_lodPrimitiveCapacity == 0) {
        return;
    }

    bool const wide = g_lodMesh.positions.size() > 65535;
    size_t const capacity = std::max<size_t>(g_lodGpuBuffer.indices.size(), 3);
    g_lodIndexBuffer = IndexBuffer::Builder()
                               .indexCount(uint32_t(capacity))
                               .bufferType(wide ? IndexBuffer::IndexType::UINT
                                                : IndexBuffer::IndexType::USHORT)
                               .build(*engine);

    if (wide) {
        auto* const indexData = new uint32_t[capacity]();
        std::copy(g_lodGpuBuffer.indices.begin(), g_lodGpuBuffer.indices.end(), indexData);
        g_lodIndexBuffer->setBuffer(*engine,
                IndexBuffer::BufferDescriptor(indexData, capacity * sizeof(uint32_t),
                        [](void* buffer, size_t, void*) {
                            delete[] static_cast<uint32_t*>(buffer);
                        }));
    } else {
        auto* const indexData = new uint16_t[capacity]();
        for (size_t i = 0; i < g_lodGpuBuffer.indices.size(); ++i) {
            indexData[i] = uint16_t(g_lodGpuBuffer.indices[i]);
        }
        g_lodIndexBuffer->setBuffer(*engine,
                IndexBuffer::BufferDescriptor(indexData, capacity * sizeof(uint16_t),
                        [](void* buffer, size_t, void*) {
                            delete[] static_cast<uint16_t*>(buffer);
                        }));
    }

    g_lodRenderable = utils::EntityManager::get().create();
    RenderableManager::Builder builder(g_lodPrimitiveCapacity);
    builder.boundingBox(g_lodBounds).culling(false).receiveShadows(true).castShadows(g_shadows);
    uint32_t const fallbackMaterial =
            g_lodGraph.nodes.empty() ? UINT32_MAX
                                     : g_lodGraph.nodes[g_lodGraph.leaves.front()].materialId;
    for (uint32_t i = 0; i < g_lodPrimitiveCapacity; ++i) {
        uint32_t const nodeId = i < g_lodGraph.leaves.size() ? g_lodGraph.leaves[i] : 0;
        builder.material(i,
                lodMaterialFor(g_lodGraph.nodes.empty() ? fallbackMaterial
                                                        : g_lodGraph.nodes[nodeId].materialId));
        builder.geometry(uint32_t(i), RenderableManager::PrimitiveType::TRIANGLES,
                g_lodVertexBuffer, g_lodIndexBuffer, g_lodNodeFirstIndex[nodeId],
                g_lodNodeIndexCount[nodeId]);
    }
    builder.build(*engine, g_lodRenderable);
    // A lit material needs a world transform to build its normal matrix. Renderables without a
    // Transform component are fine for unlit draws but leave the normal path undefined here.
    engine->getTransformManager().create(g_lodRenderable);
    g_scene->addEntity(g_lodRenderable);
}

void rebuildLodGeometry(Engine* engine) {
    if (engine == nullptr || g_materialInstance == nullptr || g_scene == nullptr) {
        return;
    }
    createLodRenderable(engine);
    if (!g_lodRenderable || g_lodIndexBuffer == nullptr) {
        return;
    }

    std::vector<uint32_t> const& nodes = g_showOriginal ? g_lodGraph.leaves : g_lodSelection.nodes;
    // Each selected DAG node owns a prebuilt index range. Unused primitive slots are hidden with
    // a zero index count, so changing a cut performs no CPU index packing and no GPU upload.
    RenderableManager& rcm = engine->getRenderableManager();
    RenderableManager::Instance const instance = rcm.getInstance(g_lodRenderable);
    for (uint32_t i = 0; i < g_lodPrimitiveCapacity; ++i) {
        if (i < nodes.size()) {
            uint32_t const nodeId = nodes[i];
            mm::LodGraphNode const& node = g_lodGraph.nodes[nodeId];
            rcm.setMaterialInstanceAt(instance, i, lodMaterialFor(node.materialId));
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, g_lodIndexBuffer, g_lodNodeFirstIndex[nodeId],
                    g_lodNodeIndexCount[nodeId]);
        } else {
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, g_lodIndexBuffer, 0, 0);
        }
    }
}

void updateLodSelection() {
    if (g_lodGraph.nodes.empty()) {
        return;
    }
    auto const start = std::chrono::steady_clock::now();
    float const targetKeep = std::clamp(1.0f - g_lodSavings, 0.01f, 1.0f);
    mm::LodTierProfile const profile = mm::lodTierProfile(g_lodTier);
    float const ceiling = g_ignoreQualityCeiling ? std::numeric_limits<float>::infinity()
                                                 : profile.maxScreenErrorPx;
    if (g_distanceLod) {
        // Runtime path: one traversal of the DAG. Error is divided by the node's view depth,
        // so a fixed pixel threshold naturally yields fine geometry near and coarse far.
        g_lodSelection = mm::selectLodGraph(g_lodGraph, g_lodCamera, g_lodScreenErrorPx);
    } else {
        // Editor path: solve for the most detailed cut that fits a triangle budget. This is a
        // binary search over thresholds and is intentionally not the per-frame runtime path.
        g_lodSelection = mm::selectLodGraphAtRatio(g_lodGraph, g_lodCamera, targetKeep, ceiling);
    }
    auto const end = std::chrono::steady_clock::now();
    g_lodSelectionMs = std::chrono::duration<double, std::milli>(end - start).count();
    g_lodSelectedTriangles = uint32_t(g_lodSelection.selectedTriangles);
    g_lodMaxScreenError = 0.0f;
    for (float error: g_lodSelection.screenErrorPerNode) {
        g_lodMaxScreenError = std::max(g_lodMaxScreenError, error);
    }
    g_lodTopology = mm::measureTopology(g_lodMesh, g_lodSelection.indices);
}

void reportLodStats() {
    double const ratio = g_lodBaseTriangles > 0
                                 ? double(g_lodSelectedTriangles) / double(g_lodBaseTriangles)
                                 : 0.0;
    std::printf("dag: nodes=%zu levels=%u leaves=%zu roots=%zu baseTriangles=%llu\n",
            g_lodGraph.nodes.size(), g_lodGraph.levelCount, g_lodGraph.leaves.size(),
            g_lodGraph.roots.size(), (unsigned long long) g_lodGraph.baseTriangles);
    std::printf("dag: selectedTriangles=%u ratio=%.4f worstScreenError=%.3fpx "
                "nonManifold=%llu duplicate=%llu flipped=%llu minQuality=%.4f selectionMs=%.3f "
                "mode=%s\n",
            g_lodSelectedTriangles, ratio, g_lodMaxScreenError,
            (unsigned long long) g_lodTopology.nonManifoldEdges,
            (unsigned long long) g_lodTopology.duplicateTriangles,
            (unsigned long long) g_lodTopology.flippedTriangles, g_lodTopology.minTriangleQuality,
            g_lodSelectionMs, g_distanceLod ? "distance" : "savings");
    std::printf("dag: drawing=%s drawnTriangles=%llu\n",
            g_showOriginal ? "original" : "selectedCut",
            (unsigned long long) (g_showOriginal ? g_lodMesh.triangleCount()
                                                 : g_lodSelectedTriangles));
    if (!g_lodSelection.nodesPerLevel.empty()) {
        std::printf("dag: nodesPerLevel=");
        for (size_t level = 0; level < g_lodSelection.nodesPerLevel.size(); ++level) {
            std::printf("%s%u", level == 0 ? "" : ",", g_lodSelection.nodesPerLevel[level]);
        }
        std::printf("\n");
    }
    std::fflush(stdout);

    // Runtime path: select only the cut nodes, without concatenating index/material arrays.
    // This is the cost a renderer pays when it updates indirect draws instead of rebuilding
    // geometry. A handful of calls is enough to smooth out timer noise.
    int const iterations =
            std::clamp(int(200000 / std::max<size_t>(g_lodGraph.nodes.size(), 1)), 8, 200);
    auto const cutStart = std::chrono::steady_clock::now();
    mm::LodGraphCut runtimeCut;
    for (int i = 0; i < iterations; ++i) {
        runtimeCut = mm::selectLodGraphCut(g_lodGraph, g_lodCamera,
                g_distanceLod ? g_lodScreenErrorPx : g_lodMaxScreenError);
    }
    auto const cutEnd = std::chrono::steady_clock::now();
    double const averageMs = std::chrono::duration<double, std::milli>(cutEnd - cutStart).count() /
                             double(iterations);
    std::printf("dag: runtimeCut nodes=%zu triangles=%llu avg=%.4fms iterations=%d\n",
            runtimeCut.nodes.size(), (unsigned long long) runtimeCut.selectedTriangles, averageMs,
            iterations);
    std::fflush(stdout);

    // Exercise the runtime streaming contract on the graph we just built: serialize it, read
    // it back through both the synchronous page cache and the asynchronous byte-range cache.
    std::vector<uint8_t> const blob = mm::serializeLodGraph(g_lodGraph);
    if (!g_streamSavePath.empty()) {
        bool const wrote = mm::writeLodGraphFile(g_lodGraph, g_streamSavePath.c_str());
        std::printf("dag: streamSave path=%s ok=%d bytes=%zu\n", g_streamSavePath.c_str(),
                wrote ? 1 : 0, blob.size());
        std::fflush(stdout);
    }
    mm::StreamingLodGraph stream(blob);
    std::vector<mm::LodStreamingPage> const pages = stream.planPages(64 * 1024);
    mm::LodStreamingCache cache(&stream, 256 * 1024, 64 * 1024);
    bool const prepared = cache.prepare(g_lodSelection);
    mm::LodStreamingCache::Stats const& stats = cache.stats();
    g_lodStreamingBytes = stream.byteSize();
    g_lodStreamingPages = uint32_t(pages.size());
    std::printf("dag: streaming bytes=%llu pages=%u prepared=%d residentPages=%zu "
                "residentBytes=%zu hits=%llu misses=%llu evictions=%llu\n",
            (unsigned long long) stream.byteSize(), g_lodStreamingPages, prepared ? 1 : 0,
            stats.residentPages, stats.residentBytes, (unsigned long long) stats.pageHits,
            (unsigned long long) stats.pageMisses, (unsigned long long) stats.evictions);
    std::fflush(stdout);

    // The byte-range constructor is the transport-facing path. --stream-url swaps the local
    // reader for the real WinHTTP transport; the cache still schedules and decodes the pages.
    // Simulated latency makes the non-blocking behavior observable during a run.
    std::atomic<uint32_t> asyncFetches{ 0 };
    std::unique_ptr<mm::HttpByteRangeFetcher> httpTransport;
    mm::AsyncLodStreamingCache::ByteRangeFetcher byteRangeFetcher;
    if (!g_streamUrl.empty()) {
        httpTransport = std::make_unique<mm::HttpByteRangeFetcher>(g_streamUrl);
        if (httpTransport->valid()) {
            byteRangeFetcher = httpTransport->asFetcher();
        } else {
            std::fprintf(stderr, "dag: cannot stream '%s': %s; using the local graph\n",
                    g_streamUrl.c_str(), httpTransport->lastError().c_str());
            httpTransport.reset();
        }
    }
    if (!byteRangeFetcher) {
        byteRangeFetcher = [&](uint64_t offset, size_t size, std::vector<uint8_t>* bytes) {
            if (g_streamLatencyMs > 0.0f) {
                std::this_thread::sleep_for(
                        std::chrono::microseconds(int64_t(double(g_streamLatencyMs) * 1000.0)));
            }
            return stream.readBytes(offset, size, bytes);
        };
    }
    auto const asyncStart = std::chrono::steady_clock::now();
    mm::AsyncLodStreamingCache asyncCache(
            &stream,
            [&](uint64_t offset, size_t size, std::vector<uint8_t>* bytes) {
                asyncFetches.fetch_add(1, std::memory_order_relaxed);
                return byteRangeFetcher(offset, size, bytes);
            },
            256 * 1024, 64 * 1024, 4);
    bool const asyncRequested = asyncCache.request(runtimeCut);
    auto const asyncDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!asyncCache.ready() && std::chrono::steady_clock::now() < asyncDeadline) {
        asyncCache.poll();
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    asyncCache.poll();
    auto const asyncEnd = std::chrono::steady_clock::now();
    mm::LodStreamingCache::Stats const& asyncStats = asyncCache.stats();
    std::printf("dag: asyncStreaming transport=%s requested=%d ready=%d fetches=%u pending=%zu "
                "residentPages=%zu residentBytes=%zu hits=%llu misses=%llu failed=%llu "
                "bytesFetched=%llu latencyMs=%.3f wallMs=%.3f\n",
            httpTransport ? "http" : "local", asyncRequested ? 1 : 0, asyncCache.ready() ? 1 : 0,
            asyncFetches.load(), asyncCache.pending(), asyncStats.residentPages,
            asyncStats.residentBytes, (unsigned long long) asyncStats.pageHits,
            (unsigned long long) asyncStats.pageMisses,
            (unsigned long long) asyncStats.failedFetches,
            (unsigned long long) asyncStats.bytesFetched, double(g_streamLatencyMs),
            std::chrono::duration<double, std::milli>(asyncEnd - asyncStart).count());
    std::fflush(stdout);
}

void setupLodViewer(Engine* engine, View* view, Scene* scene) {
    if (g_config.positionalArgs.empty() ||
            !loadLodMesh(g_config.positionalArgs.front().c_str_safe(), &g_lodMesh)) {
        std::cerr << "The LOD viewer needs one readable mesh." << std::endl;
        return;
    }

    mm::LodGraphOptions graphOptions;
    graphOptions.clusterize.maxVertices = 128;
    graphOptions.clusterize.maxTriangles = 128;
    graphOptions.clusterize.splitCharts = true;
    graphOptions.clustersPerNode = 8;
    graphOptions.levels = 5;
    // Build each parent from a moderately reduced child set. Driving every level straight to
    // 50% exhausts the world-space error budget before the root is reached; 70% leaves the
    // seam-pair pass enough quality headroom to hit a deeper final cut. The UI slider still
    // chooses the actual runtime cut, so this does not force a 70% render.
    graphOptions.ratio = 0.7f;
    graphOptions.simplify.attributeQem = true;
    graphOptions.simplify.qualityGate = true;
    g_lodGraph = mm::buildLodGraph(g_lodMesh, graphOptions);
    g_lodBaseTriangles = uint32_t(g_lodMesh.triangleCount());

    math::float3 lo{};
    math::float3 hi{};
    mm::computeBounds(g_lodMesh, &lo, &hi);
    g_lodBounds.center = (lo + hi) * 0.5f;
    g_lodBounds.halfExtent = (hi - lo) * 0.5f;

    if (g_autoFrame) {
        float3 const center = (lo + hi) * 0.5f;
        float const radius = std::max(0.5f * length(hi - lo), 1e-3f);
        float const distance = radius / std::tan(22.5f * 3.14159265358979323846f / 180.0f) * 1.15f;
        g_target = center;
        g_eye = center + normalize(float3{ 0.8f, 0.55f, 1.8f }) * distance;
    }

    createLodMaterialInstances();

    size_t const vertexCount = g_lodMesh.positions.size();
    auto* const positions = new float3[vertexCount];
    auto* const tangents = new float4[vertexCount];
    auto* const uvs = new float2[vertexCount];
    for (size_t i = 0; i < vertexCount; ++i) {
        float3 n = normalize(g_lodMesh.normals[i]);
        float3 const axis =
                std::abs(n.y) < 0.9f ? float3{ 0.0f, 1.0f, 0.0f } : float3{ 1.0f, 0.0f, 0.0f };
        float3 const tangent = normalize(cross(axis, n));
        float3 const bitangent = cross(n, tangent);
        auto const q =
                filament::math::details::TMat33<float>::packTangentFrame({ tangent, bitangent, n });
        positions[i] = g_lodMesh.positions[i];
        tangents[i] = q.xyzw;
        float2 const uv = g_lodMesh.hasUVs() ? g_lodMesh.uvs[i] : float2{ 0.0f, 0.0f };
        uvs[i] = uv;
    }
    g_lodVertexBuffer =
            VertexBuffer::Builder()
                    .vertexCount(uint32_t(vertexCount))
                    .bufferCount(3)
                    .attribute(VertexAttribute::POSITION, 0, VertexBuffer::AttributeType::FLOAT3)
                    .attribute(VertexAttribute::TANGENTS, 1, VertexBuffer::AttributeType::FLOAT4)
                    .attribute(VertexAttribute::UV0, 2, VertexBuffer::AttributeType::FLOAT2)
                    .build(*engine);
    g_lodVertexBuffer->setBufferAt(*engine, 0,
            VertexBuffer::BufferDescriptor(positions, vertexCount * sizeof(float3),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float3*>(buffer); }));
    g_lodVertexBuffer->setBufferAt(*engine, 1,
            VertexBuffer::BufferDescriptor(tangents, vertexCount * sizeof(float4),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float4*>(buffer); }));
    g_lodVertexBuffer->setBufferAt(*engine, 2,
            VertexBuffer::BufferDescriptor(uvs, vertexCount * sizeof(float2),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float2*>(buffer); }));

    Viewport const& vp = view->getViewport();
    g_lodCamera.fovY = 45.0f * 3.14159265358979323846f / 180.0f;
    g_lodCamera.screenWidth = vp.width;
    g_lodCamera.screenHeight = vp.height;
    g_lodCamera.eye = g_eye;
    g_lodCamera.target = g_target;
    updateLodSelection();
    rebuildLodGeometry(engine);
    if (g_dag) {
        reportLodStats();
    }

    g_lightEntity = utils::EntityManager::get().create();
    LightManager::Builder(LightManager::Type::SUN)
            .color(Color::toLinear<ACCURATE>(sRGBColor{ 0.98f, 0.92f, 0.89f }))
            .intensity(110000.0f)
            .direction({ 0.6f, -1.0f, -0.8f })
            .castShadows(g_shadows)
            .build(*engine, g_lightEntity);
    scene->addEntity(g_lightEntity);

    g_cameraEntity = utils::EntityManager::get().create();
    g_camera = engine->createCamera(g_cameraEntity);
    float const aspect = vp.height > 0 ? float(vp.width) / float(vp.height) : 1.0f;
    float const distance = length(g_eye - g_target);
    g_camera->setProjection(45.0, aspect, std::max(distance * 0.01, 1e-3), distance * 20.0);
    g_camera->lookAt(g_eye, g_target, { 0.0f, 1.0f, 0.0f });
    view->setCamera(g_camera);
    view->setPostProcessingEnabled(false);
}

void drawLodUi(Engine* engine, View*) {
    if (g_lodGraph.nodes.empty()) {
        return;
    }
    bool selectionChanged = false;
    bool rebuildGeometry = false;
    // Quick A/B while looking at the viewport: toggles the same state as the checkbox.
    if (!ImGui::GetIO().WantTextInput && ImGui::IsKeyPressed(ImGuiKey_D, false)) {
        g_distanceLod = !g_distanceLod;
        selectionChanged = true;
        rebuildGeometry = true;
    }
    ImGui::SetNextWindowSize(ImVec2(360.0f, 260.0f), ImGuiCond_FirstUseEver);
    ImGui::Begin("ManyMesh DAG LOD");

    auto tierButton = [&](char const* label, mm::LodTier tier, float savings) {
        if (ImGui::Button(label)) {
            g_distanceLod = false;
            g_lodTier = tier;
            g_tierName = mm::lodTierProfile(tier).name;
            g_lodSavings = savings;
            selectionChanged = true;
            rebuildGeometry = true;
        }
        ImGui::SameLine();
    };
    tierButton("Maximum", mm::LodTier::MaximumQuality, 0.15f);
    tierButton("Balanced", mm::LodTier::Balanced, 0.50f);
    tierButton("Aggressive", mm::LodTier::Aggressive, 0.75f);
    ImGui::NewLine();

    if (ImGui::Checkbox("Distance-aware (near fine, far coarse)  [D]", &g_distanceLod)) {
        selectionChanged = true;
        rebuildGeometry = true;
    }
    if (g_distanceLod) {
        selectionChanged |=
                ImGui::SliderFloat("Screen error", &g_lodScreenErrorPx, 0.25f, 8.0f, "%.2f px");
        // Rebuilding the index buffer every frame while dragging makes the slider feel
        // laggy. Update the cut and its statistics live, then upload once the drag ends.
        rebuildGeometry |= ImGui::IsItemDeactivatedAfterEdit();
        ImGui::TextUnformatted(
                "A cluster is promoted only while its error stays under this "
                "many pixels. Near geometry therefore keeps more detail than far geometry.");
    } else {
        selectionChanged |= ImGui::SliderFloat("Savings", &g_lodSavings, 0.0f, 0.95f, "%.2f");
        rebuildGeometry |= ImGui::IsItemDeactivatedAfterEdit();
        ImGui::TextUnformatted("A triangle budget picks the most detailed cut that fits it.");
    }
    rebuildGeometry |= ImGui::Checkbox("Show original", &g_showOriginal);
    rebuildGeometry |= ImGui::Checkbox("Material colours", &g_showMaterialColors);
    if (ImGui::Checkbox("Ignore tier ceiling", &g_ignoreQualityCeiling)) {
        selectionChanged = true;
        rebuildGeometry = true;
    }
    if (selectionChanged) {
        updateLodSelection();
    }
    if (rebuildGeometry) {
        rebuildLodGeometry(engine);
    }

    double const ratio = g_lodBaseTriangles > 0 ? 100.0 * double(g_lodSelectedTriangles) /
                                                          double(g_lodBaseTriangles)
                                                : 0.0;
    ImGui::Separator();
    ImGui::Text("mode: %s", g_distanceLod ? "screen-space error" : "triangle savings");
    if (!g_distanceLod) {
        ImGui::Text("tier: %s", g_tierName.c_str());
    }
    ImGui::Text("triangles: %u / %u (%.2f%%)", g_lodSelectedTriangles, g_lodBaseTriangles, ratio);
    ImGui::Text("worst screen error: %.3f px", g_lodMaxScreenError);
    ImGui::Text("selection: %.3f ms", g_lodSelectionMs);
    ImGui::Text("non-manifold: %llu  duplicate: %llu  flipped: %llu",
            (unsigned long long) g_lodTopology.nonManifoldEdges,
            (unsigned long long) g_lodTopology.duplicateTriangles,
            (unsigned long long) g_lodTopology.flippedTriangles);
    ImGui::Text("min triangle quality: %.4f", g_lodTopology.minTriangleQuality);
    ImGui::TextWrapped(
            "Both modes only select a non-overlapping cut through the prebuilt DAG; "
            "neither re-runs simplification at runtime. Every node index range lives in one "
            "static buffer, so changing a cut only updates draw ranges.");
    ImGui::End();
}

#if defined(MM_BENCH_CAN_CAPTURE)
// RenderDoc injects itself into the process, so if it is there its DLL is already loaded and
// hands out its API through an exported entry point.
void connectToRenderDoc() {
    HMODULE const module = GetModuleHandleA("renderdoc.dll");
    if (module == nullptr) {
        std::cout << "renderdoc: not injected, --capture-frame will do nothing" << std::endl;
        return;
    }
    auto const getApi =
            reinterpret_cast<pRENDERDOC_GetAPI>(GetProcAddress(module, "RENDERDOC_GetAPI"));
    if (getApi == nullptr) {
        return;
    }
    void* api = nullptr;
    if (getApi(eRENDERDOC_API_Version_1_6_0, &api) == 1 && api != nullptr) {
        g_renderdoc = static_cast<RENDERDOC_API_1_6_0*>(api);
        std::cout << "renderdoc: connected" << std::endl;
    }
}
#endif

void setup(Engine* engine, View* view, Scene* scene) {
    g_scene = scene;
    if (g_ui || g_dag) {
        createMaterial(engine, g_materialPath.c_str());
        setupLodViewer(engine, view, scene);
        return;
    }

    g_meshSet = std::make_unique<MeshAssimp>(*engine, g_assetLoader);
    createMaterial(engine, g_materialPath.c_str());

    for (auto const& fname: g_config.positionalArgs) {
        utils::Path const filename(fname.c_str_safe());
        g_meshSet->addFromFile(filename, g_meshMaterialInstances);
    }

    if (g_meshSet->getRenderables().empty()) {
        std::cerr << "No renderable geometry: the scene would be empty." << std::endl;
        return;
    }

    auto& rcm = engine->getRenderableManager();
    for (auto renderable: g_meshSet->getRenderables()) {
        auto instance = rcm.getInstance(renderable);
        if (!instance) {
            continue;
        }
        rcm.setCastShadows(instance, g_shadows);
        if (g_materialInstance != nullptr) {
            for (size_t i = 0; i < rcm.getPrimitiveCount(instance); i++) {
                rcm.setMaterialInstanceAt(instance, i, g_materialInstance);
            }
        }
        scene->addEntity(renderable);
    }

    g_lightEntity = utils::EntityManager::get().create();
    LightManager::Builder(LightManager::Type::SUN)
            .color(Color::toLinear<ACCURATE>(sRGBColor{ 0.98f, 0.92f, 0.89f }))
            .intensity(110000.0f)
            .direction({ 0.6f, -1.0f, -0.8f })
            .castShadows(g_shadows)
            .build(*engine, g_lightEntity);
    scene->addEntity(g_lightEntity);

    // Own the camera instead of leaving the view on the app's manipulator. The manipulator
    // derives its projection from window events, which never arrive when rendering offscreen,
    // and the resulting view renders nothing at all.
    g_cameraEntity = utils::EntityManager::get().create();
    g_camera = engine->createCamera(g_cameraEntity);

    Viewport const& vp = view->getViewport();
    g_screenHeightForJitter = int(vp.height);
    float const aspect = vp.height > 0 ? float(vp.width) / float(vp.height) : 1.0f;
    float const distance = length(g_eye - g_target);
    g_camera->setProjection(45.0, aspect, std::max(distance * 0.01, 1e-3), distance * 20.0);
    g_camera->lookAt(g_eye, g_target, { 0.0f, 1.0f, 0.0f });

    view->setCamera(g_camera);
    view->setPostProcessingEnabled(false);
}

void cleanup(Engine* engine, View*, Scene*) {
    if (engine != nullptr && g_meshSet != nullptr) {
        for (auto renderable: g_meshSet->getRenderables()) {
            if (engine->getRenderableManager().getInstance(renderable)) {
                engine->destroy(renderable);
            }
        }
    }
    destroyLodRenderable(engine);

    if (engine != nullptr) {
        for (auto const& material: g_meshMaterialInstances) {
            engine->destroy(material.second);
        }
        g_meshMaterialInstances.clear();
        for (MaterialInstance* instance: g_lodMaterialInstances) {
            if (instance != nullptr) {
                engine->destroy(instance);
            }
        }
        g_lodMaterialInstances.clear();
        g_lodMaterialIdList.clear();
        if (g_lodVertexBuffer != nullptr) {
            engine->destroy(g_lodVertexBuffer);
            g_lodVertexBuffer = nullptr;
        }
        if (g_skybox != nullptr) {
            engine->destroy(g_skybox);
            g_skybox = nullptr;
        }
        if (g_cameraEntity) {
            engine->destroyCameraComponent(g_cameraEntity);
            utils::EntityManager::get().destroy(g_cameraEntity);
            g_cameraEntity = {};
            g_camera = nullptr;
        }
        if (g_materialInstance != nullptr) {
            engine->destroy(g_materialInstance);
            g_materialInstance = nullptr;
        }
        if (g_material != nullptr) {
            engine->destroy(g_material);
            g_material = nullptr;
        }
        if (g_lightEntity) {
            engine->destroy(g_lightEntity);
            g_lightEntity = {};
        }
    }

    g_meshSet.reset();
    g_scene = nullptr;
}

void preRender(Engine*, View* view, Scene*, Renderer* renderer) {
    // Without an IBL the swap chain has to be cleared explicitly, and the exposure has to be
    // pinned: both are what turns a lit scene into pixels, and both have to be identical across
    // runs for two screenshots to be comparable.
    renderer->setClearOptions({ .clearColor = { 0.0f, 0.0f, 0.0f, 1.0f }, .clear = true });
    if (g_camera != nullptr) {
        g_camera->setExposure(16.0f, 1.0f / 125.0f, 100.0f); // f/16, 1/125s, ISO 100
        if (g_repositionCamera) {
            // The flag rather than a frame counter: the capture callback runs on the backend
            // thread and can land after this callback has already run for the frame, so a
            // counter reset would be incremented past zero before it was ever observed.
            g_camera->lookAt(eyeForView(g_currentView), targetForView(g_currentView),
                    { 0.0f, 1.0f, 0.0f });
            g_repositionCamera = false;
        }
    }
    (void) view;
}

void captureScreenshot(Engine*, View* view, Renderer* renderer) {
    Viewport const& vp = view->getViewport();
    uint8_t* pixels = new uint8_t[vp.width * vp.height * 4];

    struct CaptureState {
        View* view = nullptr;
        std::string path;
    };

    backend::PixelBufferDescriptor buffer(
            pixels, vp.width * vp.height * 4, backend::PixelBufferDescriptor::PixelDataFormat::RGBA,
            backend::PixelBufferDescriptor::PixelDataType::UBYTE,
            [](void* buffer, size_t, void* user) {
                std::unique_ptr<CaptureState> const state(static_cast<CaptureState*>(user));
                Viewport const& v = state->view->getViewport();

                // RGBA, not RGB: the offscreen swap chain is an RGBA8 target and reading it
                // back as three channels yields an empty buffer.
                LinearImage const image(toLinearWithAlpha<uint8_t>(
                        v.width, v.height, v.width * 4, static_cast<uint8_t*>(buffer),
                        [](uint8_t value) { return value; }, sRGBToLinear<float4>));

                utils::Path const out(state->path.c_str());
                std::ofstream stream(out, std::ios::binary | std::ios::trunc);
                ImageEncoder::encode(stream, ImageEncoder::Format::PNG, image, "",
                        state->path.c_str());

                std::cout << "wrote " << state->path << " (" << v.width << "x" << v.height << ")"
                          << std::endl;

                delete[] static_cast<uint8_t*>(buffer);

                // Move on to the next view, or finish. The mesh is loaded once for the whole
                // sweep, which is what makes a multi view dataset practical: loading it again
                // per view costs orders of magnitude more than rendering it.
                ++g_currentView;
                g_viewFrame = 0;
                g_capturing = false;
                g_repositionCamera = true;
                if (g_currentView >= g_totalCaptures) {
                    reportTiming();
                    if (g_filamentApp != nullptr) {
                        g_filamentApp->close();
                    }
                }
            },
            new CaptureState{ view, pathForView(g_outPath, g_currentView) });

    renderer->readPixels(uint32_t(vp.left), uint32_t(vp.bottom), vp.width, vp.height,
            std::move(buffer));
}

void collectFrameInfo(Renderer* renderer) {
    for (auto const& info: renderer->getFrameInfoHistory(renderer->getMaxFrameHistorySize())) {
        if (info.frameId != 0) {
            g_frameInfo.insert_or_assign(info.frameId, info);
        }
    }
}

void postRender(Engine*, View* view, Scene*, Renderer* renderer) {
    if (g_ui) {
        // The interactive viewer stays open: capturing and closing after `measure` frames
        // would make the slider unusable.
        g_viewFrame++;
        g_frameCounter++;
        return;
    }

    if (g_captureFrame >= 0 && g_frameCounter == g_captureFrame) {
#if defined(MM_BENCH_CAN_CAPTURE)
        if (g_renderdoc != nullptr) {
            g_renderdoc->TriggerCapture();
            std::cout << "renderdoc: capture requested at frame " << g_frameCounter << std::endl;
        }
#endif
    }

    // The first frames after startup carry shader compilation and resource uploads, so they are
    // skipped; what is left is steady state. The same applies at the start of every view.
    if (g_viewFrame > g_warmup) {
        collectFrameInfo(renderer);
    }

    if (g_viewFrame >= g_warmup + g_measure && !g_capturing) {
        g_capturing = true;
        captureScreenshot(nullptr, view, renderer);
    }

    g_viewFrame++;
    g_frameCounter++;
}

samples::SampleParameters createAppParameters() {
    return {
        samples::Parameter::makeString("material", 'm',
                "Compiled material (.filamat); empty keeps the asset's own", ""),
        samples::Parameter::makeString("out", 'o', "Path of the PNG to write", "mm_bench.png"),
        samples::Parameter::makeString("eye", 'E', "Camera position x,y,z", "0,0,5"),
        samples::Parameter::makeString("target", 'T', "Camera target x,y,z", "0,0,0"),
        samples::Parameter::makeInt("warmup", 'W', "Frames rendered before measuring", 30, 0),
        samples::Parameter::makeInt("measure", 'M', "Frames measured before capture", 60, 1),
        samples::Parameter::makeInt("views", 'V',
                "Evenly spaced views around the model, rendered in one run", 1, 1),
        samples::Parameter::makeBool("shadows", 'S', "Let the sun cast shadows", true),
        samples::Parameter::makeBool("no-shadows", '\0',
                "Disable shadows for geometry-only visual comparisons", false),
        samples::Parameter::makeFloat("pan", 'P',
                "Total degrees of camera pan across the sequence; 0 keeps the camera still", 0.0f),
        samples::Parameter::makeInt("jitter", 'J',
                "Sub pixel frames per view; >1 renders each view that many times", 1, 1),
        samples::Parameter::makeInt("capture-frame", '\0',
                "Ask RenderDoc to capture this frame, if it is running (default: off)", -1),
        samples::Parameter::makeBool("ui", 'u',
                "Open the interactive DAG LOD viewer with the savings slider", false),
        samples::Parameter::makeBool("dag", 'd',
                "Render the hierarchical DAG selection and print its statistics", false),
        samples::Parameter::makeString("tier", 't',
                "LOD tier: maximum, balanced or aggressive (empty keeps --savings)", ""),
        samples::Parameter::makeFloat("savings", 's',
                "Requested triangle saving in [0,0.95]; negative keeps the tier default", -1.0f),
        samples::Parameter::makeBool("distance-lod", '\0',
                "Select clusters by screen-space error (near fine, far coarse)", false),
        samples::Parameter::makeFloat("screen-error", '\0',
                "Screen-space error threshold in pixels; implies --distance-lod", -1.0f),
        samples::Parameter::makeFloat("stream-latency-ms", '\0',
                "Simulated per-page latency for the async streaming demo", 0.0f),
        samples::Parameter::makeString("stream-url", '\0',
                "Fetch the serialized graph with HTTP byte ranges instead of local reads", ""),
        samples::Parameter::makeString("stream-save", '\0',
                "Write the serialized graph to this path so it can be served over HTTP", ""),
        samples::Parameter::makeBool("original", '\0',
                "Draw the source mesh instead of the selected DAG cut", false),
        samples::Parameter::makeBool("show-materials", '\0',
                "Colour each preserved source material id differently", false),
        samples::Parameter::makeBool("auto-frame", '\0',
                "Frame the mesh from its bounds instead of using --eye/--target", false),
        samples::Parameter::makeBool("ignore-ceiling", '\0',
                "Spend the full triangle budget even when the tier pixel ceiling is reached",
                false),
    };
}

std::unique_ptr<FilamentApp2> createSampleApp(SampleConfig config, DisplayManager* dm,
        AssetLoader* loader) {
    auto app = std::make_shared<App>();
    g_config = config;
    g_assetLoader = loader;
    app->config = config;

    g_outPath = config.getString("out").c_str_safe();
    g_materialPath = config.getString("material").c_str_safe();
    g_ui = config.getBool("ui");
    g_dag = config.getBool("dag");
    g_showOriginal = config.getBool("original");
    g_showMaterialColors = config.getBool("show-materials");
    g_autoFrame = config.getBool("auto-frame");
    g_ignoreQualityCeiling = config.getBool("ignore-ceiling");

    utils::CString const tierName = config.getString("tier");
    if (!tierName.empty()) {
        g_tierName = tierName.c_str_safe();
        if (g_tierName == "maximum") {
            g_lodTier = mm::LodTier::MaximumQuality;
        } else if (g_tierName == "aggressive") {
            g_lodTier = mm::LodTier::Aggressive;
        } else {
            g_lodTier = mm::LodTier::Balanced;
        }
        g_lodSavings = 1.0f - mm::lodTierProfile(g_lodTier).targetTriangleRatio;
    }
    float const requestedSavings = config.getFloat("savings", -1.0f);
    if (requestedSavings >= 0.0f) {
        g_lodSavings = std::clamp(requestedSavings, 0.0f, 0.95f);
    }
    g_distanceLod = config.getBool("distance-lod");
    float const requestedScreenError = config.getFloat("screen-error", -1.0f);
    if (requestedScreenError >= 0.0f) {
        g_distanceLod = true;
    }
    g_lodScreenErrorPx =
            std::clamp(requestedScreenError >= 0.0f ? requestedScreenError : 1.5f, 0.05f, 64.0f);
    g_streamLatencyMs = std::max(0.0f, config.getFloat("stream-latency-ms", 0.0f));
    g_streamUrl = config.getString("stream-url").c_str_safe();
    g_streamSavePath = config.getString("stream-save").c_str_safe();

    utils::CString const eye = config.getString("eye");
    if (!eye.empty() && !parseVec3(eye.c_str_safe(), &g_eye)) {
        std::cerr << "Could not parse --eye '" << eye.c_str_safe() << "', expected x,y,z"
                  << std::endl;
        exit(1);
    }
    utils::CString const target = config.getString("target");
    if (!target.empty() && !parseVec3(target.c_str_safe(), &g_target)) {
        std::cerr << "Could not parse --target '" << target.c_str_safe() << "', expected x,y,z"
                  << std::endl;
        exit(1);
    }

    g_warmup = std::max(0, config.getInt("warmup", 30));
    g_measure = std::max(1, config.getInt("measure", 60));
    g_viewCount = std::max(1, config.getInt("views", 1));
    g_shadows = config.getBool("shadows");
    if (config.getBool("no-shadows")) {
        g_shadows = false;
    }
    g_captureFrame = config.getInt("capture-frame", -1);
    g_jitter = std::max(1, config.getInt("jitter", 1));
    g_panDegrees = config.getFloat("pan", 0.0f);
    g_totalCaptures = g_viewCount * g_jitter;

#if defined(MM_BENCH_CAN_CAPTURE)
    connectToRenderDoc();
#endif

    auto filamentApp = samples::getBuilder(config, dm, loader)
                               .setup(setup)
                               .cleanup(cleanup)
                               .preRender(preRender)
                               .postRender(postRender)
                               .imgui(g_ui ? drawLodUi : nullptr)
                               .build();

    app->filamentApp = filamentApp.get();
    g_filamentApp = filamentApp.get();
    return filamentApp;
}

} // namespace

#ifndef __ANDROID__
int main(int argc, char* argv[]) {
    samples::CommandLineSpecification spec = {
        .sampleDescription =
                "SAMPLE_MM_BENCH renders a mesh from a fixed camera and reports frame time.\n\n"
                "It exists so that two meshes can be compared image by image: everything except\n"
                "the geometry - camera, material, lighting, exposure, resolution - is pinned, and\n"
                "no UI is drawn over the result. Typical use is rendering a high polygon asset\n"
                "and a decimated version of it, then diffing the two PNGs.\n\n"
                "Run it with --headless to render offscreen without a window.\n\n"
                "Example:\n"
                "    mm_bench --headless --window-size 1280x720 --fixed-timestep 0.0166667 \\\n"
                "             --out lod0.png --eye 2.2,-6.7,220 --target 2.2,-6.7,9.8 mesh.obj",
        .positionalArgsDescription = { "[mesh files (.obj, .fbx, .ply, .filamesh)]" },
        .requiredPositionalArgCount = 1,
        .parameters = createAppParameters(),
    };

    SampleConfig config;
    config.title = "ManyMesh Render Harness";
    config.headless = true;
    samples::handleCommandLineArguments(argc, argv, &config, spec);

    g_ui = config.getBool("ui");
    g_dag = config.getBool("dag");
    if (g_ui) {
        // A window is the point of --ui; the harness is headless by default so that screenshots
        // are reproducible on machines without a display server.
        config.headless = false;
    }

    auto dm = samples::getDisplayManager(config);
    auto loader = samples::getAssetLoader(config);

    for (auto const& fname: config.positionalArgs) {
        utils::Path const filename(fname.c_str_safe());
        if (!loader->exists(filename)) {
            std::cerr << "file " << filename << " not found!" << std::endl;
            return 1;
        }
    }

    auto app = createSampleApp(config, dm.get(), loader.get());
    app->run();

    return 0;
}
#endif
