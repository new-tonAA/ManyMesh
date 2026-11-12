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
#include "mm_gpu_cut.h"

#include "generated/resources/resources.h"

#include <imageio/ImageDecoder.h>
#include <imageio/ImageEncoder.h>

#include <image/ColorTransform.h>
#include <image/LinearImage.h>

#include <manymesh/AmbientOcclusion.h>
#include <manymesh/DetailBake.h>
#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/Quality.h>
#include <manymesh/ShadingNormals.h>
#include <manymesh/Streaming.h>

#include <filamentapp/AssetLoader.h>
#include <filamentapp/DesktopAssetLoader.h>
#include <filamentapp/FilamentApp2.h>
#include <filamentapp/MeshAssimp.h>

#include <filament/Camera.h>
#include <filament/Color.h>
#include <filament/Engine.h>
#include <filament/IndexBuffer.h>
#include <filament/IndirectLight.h>
#include <filament/LightManager.h>
#include <filament/Material.h>
#include <filament/MaterialInstance.h>
#include <filament/RenderableManager.h>
#include <filament/Renderer.h>
#include <filament/Scene.h>
#include <filament/Skybox.h>
#include <filament/Texture.h>
#include <filament/TextureSampler.h>
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
#include <cstring>
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
// A second, invisible renderable that feeds the shadow map with the source mesh or a finer cut.
// It writes neither colour nor depth to the camera pass, so the visible LOD stays the only
// surface the camera sees while its shadows come from geometry that still has the small
// cavities and thin features the cut removed.
Material* g_shadowProxyMaterial = nullptr;
MaterialInstance* g_shadowProxyMaterialInstance = nullptr;
Texture* g_detailNormalTexture = nullptr;
Texture* g_detailHeightTexture = nullptr;
Texture* g_aoMapTexture = nullptr;
IndirectLight* g_indirectLight = nullptr;
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
std::string g_detailNormalPath;
float g_normalStrength = 1.0f;
std::string g_detailHeightPath;
//! UV-space parallax scale. Negative means "read the sidecar written by mmgeo"; 0 disables it.
float g_pomScale = 0.02f;
bool g_pomScaleAuto = true;
float g_pomStrength = 1.0f;
int g_pomLayers = 8;
// Source-mesh ambient occlusion baked onto the LOD vertices. It needs no UV layout, so it also
// covers the tiled and out-of-range atlases that a texture-space bake rejects.
bool g_bakeAo = false;
//! One-switch LOD shading compensation: a combined material samples a high-poly AO map and a
//! detail normal map baked against the currently selected cut. The maps complement the source
//! normals and AO already carried by the DAG; they do not try to reconstruct geometry.
bool g_shadeCompensate = false;
uint32_t g_compensateSize = 256;
//! Weight AO/detail compensation per cluster by its screen-space error instead of applying the
//! same strength to near and far nodes. The weight is carried in vertex colour alpha, which the
//! combined material multiplies with compensationStrength.
bool g_shadeErrorDriven = false;
//! Global blend for the compensation terms. 0 is exactly the uncompensated LOD even though the
//! combined material is resident; the UI exposes it as an intensity slider.
float g_compensationStrength = 1.0f;
//! True when --shade-compensate selected the AO map size implicitly. The UI can then switch the
//! compensation off again without leaving a bake request behind.
bool g_compensateBakeSizeAuto = false;
//! Detail-normal strength for the combined compensation material. 0 is the conservative default:
//! the measured AO benefit does not require a normal map, and a mis-baked normal map is visible
//! as seam lines on assets with split UV charts.
float g_compensateNormalStrength = 0.0f;
//! Optional roughness increase for specular energy whose normal detail was removed. 0 keeps the
//! authored roughness and is the conservative default; the UI exposes it for art-directed use.
float g_roughnessBoost = 0.0f;
bool g_aoMapHasData = false;
//! Texture-space AO bake. It resolves cavities finer than the LOD vertex spacing, but needs
//! source UVs in [0,1]. 0 disables it; --ao-map loads a prebaked map instead.
uint32_t g_bakeAoMapSize = 0;
std::string g_aoMapPath;
uint32_t g_aoSamples = 32;
float g_aoRadius = 0.0f;
float g_aoStrength = 0.5f;
//! Directional visibility baked alongside AO. 0 reproduces scalar-AO-only shading. It is
//! opt-in: measured against a high-poly reference that also uses bent normals, the LOD's
//! directional response is the right magnitude but does not improve per-pixel PSNR, because
//! source and LOD sample different surface points.
float g_bentNormalStrength = 0.0f;
//! Optional procedural SH environment used to evaluate directional visibility without an
//! external IBL asset. It is off by default so geometry-only comparisons stay unchanged.
bool g_ibl = false;
float g_iblIntensity = 30000.0f;
//! Direct sunlight. Setting this to 0 isolates indirect-light compensation in A/B tests.
float g_sunIntensity = 110000.0f;
bool g_vertexColors = false;
std::vector<float> g_lodAo;
std::vector<float3> g_lodBentNormals;
std::vector<float> g_lodCompensationWeights;
float g_roughness = 0.5f;
// Screen-space ambient occlusion is an independent visibility estimate: unlike baked AO it
// sees the current cut and the rendered depth buffer, so it darkens cavities that survived the
// cut without requiring source UVs or a bake. It only affects indirect light, so --ibl (or
// another ambient source) is required to see it.
bool g_ssao = false;
float g_ssaoRadius = 0.0f;
float g_ssaoIntensity = 1.0f;
float g_ssaoPower = 1.0f;
bool g_ssaoBentNormals = false;
int g_ssaoQuality = 2;
float g_ssaoResolution = 1.0f;
// Screen Space Cone Tracing adds directional contact shadows from the dominant light to the
// SSAO buffer. It is useful when a cut removes the small folds that used to occlude ambient
// light, and it shares the GTAO pass rather than requiring a second full-screen effect.
bool g_ssct = false;
float g_ssctIntensity = 0.8f;
float g_ssctShadowDistance = 0.0f;
float g_ssctContactDistanceMax = 0.0f;
float g_ssctConeAngleRad = 1.0f;
// Screen-space curvature cavity compensation. 0 disables it; curvatureScale is derived from
// the mesh radius so the mean-curvature term is dimensionless.
float g_cavityStrength = 0.0f;
float g_curvatureScale = 1.0f;
//! Derive curvatureScale from the loaded asset bounds when true.
bool g_curvatureScaleAuto = true;
// Shading-side compensation: duplicate-position vertices often carry normals a few degrees
// apart. Unifying them below a crease angle removes visible shading facets without changing a
// single triangle. 0 keeps the asset's normals untouched.
float g_shadeCreaseDegrees = 0.0f;
float g_shadeStrength = 0.5f;
//! Derive the repair blend from the cut's worst screen-space error instead of applying the
//! same strength everywhere. The measured optimum is 0.5 once the error is visible.
bool g_shadeAuto = false;
//! Re-apply the measured shading ladder whenever the selected cut changes. The ladder chooses
//! MSAA + seam normals below 45% retention and source AO + seam normals above it.
bool g_autoShadingPreset = false;
std::vector<float3> g_lodOriginalNormals;
float3 g_eye = { 0.0f, 0.0f, 5.0f };
float3 g_target = { 0.0f, 0.0f, 0.0f };
int g_warmup = 30;
int g_measure = 60;
int g_viewCount = 1;
int g_jitter = 1;
//! Temporal sub frames per view. `--jitter` both creates sub frames and offsets them within a
//! pixel; `--frames` creates sub frames without the sub pixel offset, which is what a
//! translation sequence needs so the high resolution target stays on the same camera.
int g_subFrames = 1;
float g_panDegrees = 0.0f;
//! Total lateral camera translation across the sub frames of one view, in world units. Unlike
//! a pan this has parallax, so history reprojection needs depth.
float g_translateUnits = 0.0f;
//! Optional path for the exact per-capture camera list, consumed by tools/mmdepth and
//! tools/mmtemporal. Writing it here keeps those tools from re-deriving the camera path.
std::string g_cameraOutPath;
int g_screenHeightForJitter = 360;
int g_totalCaptures = 1;
bool g_shadows = true;
//! Use the source mesh (ratio 1) or a finer DAG cut as a shadow-only proxy.
bool g_shadowProxy = false;
//! Target triangle ratio of the proxy cut. 1 keeps the exact source mesh; lower values trade
//! shadow-map detail for rasterisation cost.
float g_shadowProxyRatio = 1.0f;
//! Receiver-side shadow offsets used while the proxy is active. The LOD surface is not exactly
//! the source surface, so the default sun bias (1 mm) makes it shadow itself in the proxy's
//! depth map. These values are in world units and are disabled with the proxy.
float g_shadowProxyConstantBias = 0.010f;
float g_shadowProxyNormalBias = 3.0f;
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
bool g_mergeDraws = true;
bool g_compactCutIndices = false;
bool g_cornerSimplify = true;
bool g_cornerSplitUv = true;
bool g_autoFrame = false;
bool g_compactVertices = false;
int g_msaaSamples = 0;
bool g_taa = false;
//! Distance-aware selection keeps the hierarchy's finest clusters near the camera and promotes
//! a cluster only when its accumulated geometric error is small enough on screen.
bool g_distanceLod = false;
float g_lodScreenErrorPx = 1.5f;
double g_lodSelectionMs = 0.0;
double g_lodCompactMs = 0.0;
mm::Mesh g_lodMesh;
std::vector<float3> g_lodTangents;
std::vector<float> g_lodTangentSigns;
mm::LodGraph g_lodGraph;
mm::LodGraphBuildStats g_lodGraphBuildStats;
mm::LodGraphSelection g_lodSelection;
mm::LodGraphCut g_lodRuntimeCut;
mm::LodTier g_lodTier = mm::LodTier::Balanced;
mm::ViewCamera g_lodCamera;
mm::TopologyStats g_lodTopology;
VertexBuffer* g_lodVertexBuffer = nullptr;
Entity g_lodRenderable{};
Entity g_shadowProxyRenderable{};
IndexBuffer* g_shadowProxyIndexBuffer = nullptr;
mm::LodGraphSelection g_shadowProxySelection;
uint32_t g_shadowProxyTriangles = 0;
bool g_shadowProxyInScene = false;
Box g_lodBounds;
float g_sceneDiagonal = 0.0f;
uint32_t g_lodSelectedTriangles = 0;
uint64_t g_lodDrawnTriangles = 0;
uint32_t g_lodBaseTriangles = 0;
uint32_t g_lodCutVertexCount = 0;
uint32_t g_lodCutGeneratedVertices = 0;
float g_lodMaxScreenError = 0.0f;
uint64_t g_lodStreamingBytes = 0;
uint32_t g_lodStreamingPages = 0;
float g_streamLatencyMs = 0.0f;
std::string g_streamUrl;
std::string g_streamSavePath;

mm::GpuLodBuffer g_lodGpuBuffer;
bool g_gpuCut = false;
bool g_gpuCutActive = false;
bool g_gpuCutVerified = false;
uint32_t g_gpuCutNodeCount = 0;
uint64_t g_gpuCutSelectedTriangles = 0;
uint64_t g_gpuCutCulledTriangles = 0;
uint64_t g_gpuCutNodeMismatch = 0;
uint64_t g_gpuCutTriangleMismatch = 0;
double g_gpuCutMs = 0.0;
std::string g_gpuCutError;
mmbench::GpuLodCut g_gpuCutSelector;
std::vector<uint32_t> g_lodNodeFirstIndex;
std::vector<uint32_t> g_lodNodeIndexCount;
uint32_t g_lodPrimitiveCapacity = 0;
IndexBuffer* g_lodIndexBuffer = nullptr;
VertexBuffer* g_lodCompactVertexBuffer = nullptr;
IndexBuffer* g_lodCompactIndexBuffer = nullptr;
std::vector<uint32_t> g_lodCompactFirstIndex;
std::vector<uint32_t> g_lodCompactIndexCount;
std::vector<uint32_t> g_lodCompactMaterialIds;
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
std::vector<double> g_cpuFrameMs;
std::chrono::steady_clock::time_point g_lastFrameTime;

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

//! Eye position of an orbit view, before the temporal sub frame offset.
float3 baseEyeForView(int capture) {
    int const view = g_subFrames > 1 ? capture / g_subFrames : capture;
    if (g_viewCount <= 1) {
        return g_eye;
    }
    // Orbit around the world up axis through the target, keeping the elevation and distance
    // the caller asked for, so a sweep is a pure azimuthal rotation.
    float3 const offset = g_eye - g_target;
    float const angle = 2.0f * 3.14159265358979323846f * float(view) / float(g_viewCount);
    float const c = std::cos(angle);
    float const s = std::sin(angle);
    return g_target +
           float3{ offset.x * c - offset.z * s, offset.y, offset.x * s + offset.z * c };
}

//! Lateral shift of the eye (and target) across the sub frames of one view. Translation has
//! parallax, so unlike a pan its reprojection depends on depth.
float3 translationOffsetForView(int capture) {
    if (g_translateUnits == 0.0f) {
        return {};
    }
    float3 const base = baseEyeForView(capture);
    float3 const forward = normalize(g_target - base);
    float3 const right = normalize(cross(forward, float3{ 0.0f, 1.0f, 0.0f }));
    int const sub = g_subFrames > 1 ? capture % g_subFrames : 0;
    float const t = g_subFrames > 1 ? float(sub) / float(g_subFrames - 1) : 0.5f;
    return right * ((t - 0.5f) * g_translateUnits);
}

float3 eyeForView(int capture) {
    int const jitterIndex = g_jitter > 1 ? capture % g_jitter : 0;
    float3 const base = baseEyeForView(capture);
    float3 const translated = base + translationOffsetForView(capture);

    // A pan keeps the eye fixed and turns the view. With no translation there is no parallax,
    // so the image displacement between two frames is an exact homography that does not
    // depend on depth, and history can be reprojected without a depth buffer at all.
    if (g_panDegrees != 0.0f) {
        // The pan supplies the sub frame variation, so the eye is just this view's orbit
        // position (plus any translation).
        return translated;
    }

    if (g_viewCount <= 1) {
        return translated + (g_jitter > 1
                ? jitterOffset(jitterIndex, float(g_screenHeightForJitter)) : float3{});
    }
    if (g_jitter <= 1) {
        return translated;
    }
    // Same azimuth, nudged by a sub pixel offset: consecutive frames differ only in where
    // within a pixel they sample, which is what accumulation has to work with.
    float3 const saved = g_eye;
    g_eye = base;
    float3 const jittered = jitterOffset(jitterIndex, float(g_screenHeightForJitter));
    g_eye = saved;
    return translated + jittered;
}

float3 targetForView(int capture) {
    float3 const translation = translationOffsetForView(capture);
    if (g_panDegrees == 0.0f) {
        return g_target + translation;
    }
    // The pan runs across the sub frames *within* a view, so one run yields one sequence per
    // azimuth: --views V --jitter N --pan D gives V sequences of N frames, all from a single
    // mesh load. The rotation is about the un-translated eye, then the whole view shifts.
    int const sub = g_subFrames > 1 ? capture % g_subFrames : 0;
    float const t = g_subFrames > 1 ? float(sub) / float(g_subFrames - 1) : 0.5f;
    float const angle = (t - 0.5f) * g_panDegrees * 3.14159265358979323846f / 180.0f;

    float3 const base = baseEyeForView(capture);
    float3 const offset = g_target - base;
    float const c = std::cos(angle);
    float const s = std::sin(angle);
    return base + float3{ offset.x * c - offset.z * s, offset.y, offset.x * s + offset.z * c }
           + translation;
}

//! Writes the exact camera used for every capture. tools/mmdepth and tools/mmtemporal consume
//! this list instead of re-deriving the orbit / pan / translation maths, which would let a
//! half-pixel disagreement show up as ghosting rather than as an error.
void writeCameraList(int width, int height) {
    if (g_cameraOutPath.empty()) {
        return;
    }
    std::ofstream stream(g_cameraOutPath, std::ios::trunc);
    if (!stream) {
        std::cerr << "Could not write camera list '" << g_cameraOutPath << "'" << std::endl;
        return;
    }
    stream << "manymesh-cameras 1\n"
           << "views " << g_viewCount << "\n"
           << "jitter " << g_subFrames << "\n"
           << "count " << g_totalCaptures << "\n";
    for (int i = 0; i < g_totalCaptures; ++i) {
        float3 const eye = eyeForView(i);
        float3 const target = targetForView(i);
        char line[512];
        std::snprintf(line, sizeof(line),
                "%d %.9g %.9g %.9g %.9g %.9g %.9g 45 %d %d\n", i,
                double(eye.x), double(eye.y), double(eye.z),
                double(target.x), double(target.y), double(target.z), width, height);
        stream << line;
    }
    std::cout << "wrote camera list " << g_cameraOutPath << " (" << g_totalCaptures
              << " captures, " << g_viewCount << " views x " << g_subFrames << " frames)"
              << std::endl;
}

std::string pathForView(std::string const& base, int capture) {
    if (g_viewCount <= 1 && g_subFrames <= 1) {
        return base;
    }
    // Insert the indices before the extension: renders_v00.png, or with sub frames
    // renders_v00_j03.png, where the view is the camera and j is the temporal frame.
    char suffix[24];
    if (g_subFrames > 1) {
        snprintf(suffix, sizeof(suffix), "_v%02d_j%02d", capture / g_subFrames,
                capture % g_subFrames);
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

    if (!g_cpuFrameMs.empty()) {
        std::vector<double> cpuSorted = g_cpuFrameMs;
        std::sort(cpuSorted.begin(), cpuSorted.end());
        printf("  CPU   median %.3f ms  p99 %.3f ms  max %.3f ms\n", medianOf(g_cpuFrameMs),
                percentileOf(cpuSorted, 0.99), cpuSorted.back());
    }

    if (g_gpuFrameMs.empty()) {
        std::cout << "frame time: no GPU samples (GPU timing unavailable)" << std::endl;
        return;
    }
    std::vector<double> sorted = g_gpuFrameMs;
    std::sort(sorted.begin(), sorted.end());

    printf("frame time over %zu measured frames from %d view(s):\n", g_gpuFrameMs.size(),
            g_viewCount);
    printf("  GPU   median %.3f ms  p99 %.3f ms  max %.3f ms\n", medianOf(g_gpuFrameMs),
            percentileOf(sorted, 0.99), sorted.back());
}

// Decodes the baked detail normal map as linear data. The map is not a color texture: applying
// an sRGB transfer function here would bend every normal towards +Z.
Texture* loadDetailNormalTexture(Engine* engine, char const* path) {
    if (engine == nullptr || path == nullptr || path[0] == '\0') {
        return nullptr;
    }
    std::ifstream in(path, std::ifstream::in | std::ios::binary);
    if (!in.is_open()) {
        std::cerr << "Could not open detail normal map '" << path << "'" << std::endl;
        return nullptr;
    }
    image::LinearImage const decoded =
            image::ImageDecoder::decode(in, path, image::ImageDecoder::ColorSpace::LINEAR);
    if (!decoded) {
        std::cerr << "Could not decode detail normal map '" << path << "'" << std::endl;
        return nullptr;
    }

    uint32_t const width = decoded.getWidth();
    uint32_t const height = decoded.getHeight();
    uint32_t const channels = std::max(1u, decoded.getChannels());
    auto* const pixels = new uint8_t[size_t(width) * height * 4];
    for (uint32_t y = 0; y < height; ++y) {
        float const* const row = decoded.getPixelRef(0, y);
        for (uint32_t x = 0; x < width; ++x) {
            for (uint32_t channel = 0; channel < 4; ++channel) {
                // Old RGB bakes have no lost-normal channel. Treat them as fully detailed so the
                // previous global roughness behaviour is preserved after upgrading.
                float value = 1.0f;
                if (channel < channels) {
                    value = row[x * channels + channel];
                } else if (channel < 3) {
                    value = row[x * channels + channels - 1];
                }
                pixels[(size_t(y) * width + x) * 4 + channel] =
                        uint8_t(std::clamp(std::lround(value * 255.0f), 0L, 255L));
            }
        }
    }

    Texture* const texture =
            Texture::Builder()
                    .width(width)
                    .height(height)
                    .levels(0xff)
                    .format(Texture::InternalFormat::RGBA8)
                    .usage(Texture::Usage::DEFAULT | Texture::Usage::GEN_MIPMAPPABLE)
                    .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(width) * height * 4,
                    Texture::Format::RGBA, Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    texture->generateMipmaps(*engine);
    return texture;
}

Texture* createAoMapTexture(Engine* engine, uint8_t const* values, uint32_t size) {
    if (engine == nullptr || values == nullptr || size == 0) {
        return nullptr;
    }
    auto* const pixels = new uint8_t[size_t(size) * size];
    std::memcpy(pixels, values, size_t(size) * size);
    Texture* const texture =
            Texture::Builder()
                    .width(size)
                    .height(size)
                    .levels(0xff)
                    .format(Texture::InternalFormat::R8)
                    .usage(Texture::Usage::DEFAULT | Texture::Usage::GEN_MIPMAPPABLE)
                    .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(size) * size, Texture::Format::R,
                    Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    texture->generateMipmaps(*engine);
    return texture;
}

// Uploads a linear RGBA8 image. The detail-normal bake outputs this layout; keeping it linear
// matters because an sRGB decode would bend every normal toward +Z.
Texture* createRgbaTexture(Engine* engine, uint8_t const* values, uint32_t size) {
    if (engine == nullptr || values == nullptr || size == 0) {
        return nullptr;
    }
    auto* const pixels = new uint8_t[size_t(size) * size * 4];
    std::memcpy(pixels, values, size_t(size) * size * 4);
    Texture* const texture =
            Texture::Builder()
                    .width(size)
                    .height(size)
                    .levels(0xff)
                    .format(Texture::InternalFormat::RGBA8)
                    .usage(Texture::Usage::DEFAULT | Texture::Usage::GEN_MIPMAPPABLE)
                    .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(size) * size * 4, Texture::Format::RGBA,
                    Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    texture->generateMipmaps(*engine);
    return texture;
}

Texture* loadAoMapTexture(Engine* engine, char const* path) {
    if (engine == nullptr || path == nullptr || path[0] == '\0') {
        return nullptr;
    }
    std::ifstream in(path, std::ifstream::in | std::ios::binary);
    if (!in.is_open()) {
        std::cerr << "Could not open AO map '" << path << "'" << std::endl;
        return nullptr;
    }
    image::LinearImage const decoded =
            image::ImageDecoder::decode(in, path, image::ImageDecoder::ColorSpace::LINEAR);
    if (!decoded) {
        std::cerr << "Could not decode AO map '" << path << "'" << std::endl;
        return nullptr;
    }
    uint32_t const width = decoded.getWidth();
    uint32_t const height = decoded.getHeight();
    if (width != height) {
        std::cerr << "AO map '" << path << "' must be square" << std::endl;
        return nullptr;
    }
    uint32_t const channels = std::max(1u, decoded.getChannels());
    auto* const pixels = new uint8_t[size_t(width) * height];
    for (uint32_t y = 0; y < height; ++y) {
        float const* const row = decoded.getPixelRef(0, y);
        for (uint32_t x = 0; x < width; ++x) {
            float const value = row[x * channels];
            pixels[size_t(y) * width + x] =
                    uint8_t(std::clamp(std::lround(value * 255.0f), 0L, 255L));
        }
    }
    Texture* const texture =
            Texture::Builder()
                    .width(width)
                    .height(height)
                    .levels(0xff)
                    .format(Texture::InternalFormat::R8)
                    .usage(Texture::Usage::DEFAULT | Texture::Usage::GEN_MIPMAPPABLE)
                    .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(width) * height, Texture::Format::R,
                    Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    texture->generateMipmaps(*engine);
    return texture;
}

// Loads a one-channel map. The height map is signed displacement, not color, so it stays linear
// for the same reason the detail normal map does.
Texture* loadHeightMapTexture(Engine* engine, char const* path) {
    if (engine == nullptr || path == nullptr || path[0] == '\0') {
        return nullptr;
    }
    std::ifstream in(path, std::ifstream::in | std::ios::binary);
    if (!in.is_open()) {
        std::cerr << "Could not open detail height map '" << path << "'" << std::endl;
        return nullptr;
    }
    image::LinearImage const decoded =
            image::ImageDecoder::decode(in, path, image::ImageDecoder::ColorSpace::LINEAR);
    if (!decoded) {
        std::cerr << "Could not decode detail height map '" << path << "'" << std::endl;
        return nullptr;
    }
    uint32_t const width = decoded.getWidth();
    uint32_t const height = decoded.getHeight();
    if (width != height) {
        std::cerr << "Detail height map '" << path << "' must be square" << std::endl;
        return nullptr;
    }
    uint32_t const channels = std::max(1u, decoded.getChannels());
    auto* const pixels = new uint8_t[size_t(width) * height];
    for (uint32_t y = 0; y < height; ++y) {
        float const* const row = decoded.getPixelRef(0, y);
        for (uint32_t x = 0; x < width; ++x) {
            float const value = row[x * channels];
            pixels[size_t(y) * width + x] =
                    uint8_t(std::clamp(std::lround(value * 255.0f), 0L, 255L));
        }
    }
    Texture* const texture =
            Texture::Builder()
                    .width(width)
                    .height(height)
                    .levels(0xff)
                    .format(Texture::InternalFormat::R8)
                    .usage(Texture::Usage::DEFAULT | Texture::Usage::GEN_MIPMAPPABLE)
                    .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(width) * height, Texture::Format::R,
                    Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    texture->generateMipmaps(*engine);
    return texture;
}

Texture* createNeutralNormalTexture(Engine* engine) {
    if (engine == nullptr) {
        return nullptr;
    }
    // Alpha 0 means "no lost normal detail": the roughness compensation slider stays a no-op
    // until a baked map supplies a real per-texel angle.
    auto* const pixels = new uint8_t[4]{ 128, 128, 255, 0 };
    Texture* const texture = Texture::Builder()
                                     .width(1)
                                     .height(1)
                                     .levels(1)
                                     .format(Texture::InternalFormat::RGBA8)
                                     .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, 4, Texture::Format::RGBA, Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) { delete[] static_cast<uint8_t*>(buffer); }));
    return texture;
}

Texture* createNeutralHeightTexture(Engine* engine) {
    uint8_t const neutral = 128;
    return createAoMapTexture(engine, &neutral, 1);
}

// mmgeo writes recommendedUvScale next to detail-height.png. Keeping it in a sidecar avoids
// inventing a second texture format just to carry one scalar.
float readParallaxScaleSidecar(std::string const& path) {
    std::ifstream in(path + ".txt");
    std::string line;
    while (std::getline(in, line)) {
        size_t const separator = line.find('=');
        if (separator != std::string::npos && line.substr(0, separator) == "recommendedUvScale") {
            return float(std::atof(line.c_str() + separator + 1));
        }
    }
    return 0.02f;
}

void applyShadingParameters(MaterialInstance* instance) {
    if (instance == nullptr || g_material == nullptr) {
        return;
    }
    if (g_material->hasParameter("roughness")) {
        instance->setParameter("roughness", g_roughness);
    }
    if (g_material->hasParameter("roughnessBoost")) {
        instance->setParameter("roughnessBoost", g_shadeCompensate ? g_roughnessBoost : 0.0f);
    }
    if (g_material->hasParameter("cavityStrength")) {
        instance->setParameter("cavityStrength", g_cavityStrength);
    }
    if (g_material->hasParameter("curvatureScale")) {
        instance->setParameter("curvatureScale", g_curvatureScale);
    }
    if (g_material->hasParameter("normalStrength")) {
        // The combined LOD material has its own conservative default; the standalone
        // aiDetailNormal material keeps the caller's --normal-strength.
        float const strength = g_material->hasParameter("roughnessBoost")
                                       ? (g_shadeCompensate ? g_compensateNormalStrength : 0.0f)
                                       : g_normalStrength;
        instance->setParameter("normalStrength", strength);
    }
    if (g_material->hasParameter("compensationStrength")) {
        // The combined material is always resident in the UI so the toggle can be instant. This
        // uniform is the gate: 0 reproduces the uncompensated LOD exactly.
        instance->setParameter("compensationStrength",
                g_shadeCompensate ? g_compensationStrength : 0.0f);
    }
    if (g_material->hasParameter("aoStrength")) {
        instance->setParameter("aoStrength", g_aoStrength);
    }
    if (g_material->hasParameter("bentNormalStrength")) {
        instance->setParameter("bentNormalStrength", g_bentNormalStrength);
    }
    if (g_detailNormalTexture != nullptr && g_material->hasParameter("normal")) {
        TextureSampler sampler;
        sampler.setMinFilter(TextureSampler::MinFilter::LINEAR_MIPMAP_LINEAR);
        sampler.setMagFilter(TextureSampler::MagFilter::LINEAR);
        sampler.setWrapModeS(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        sampler.setWrapModeT(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        instance->setParameter("normal", g_detailNormalTexture, sampler);
    }
    if (g_aoMapTexture != nullptr && g_material->hasParameter("aoMap")) {
        TextureSampler sampler;
        sampler.setMinFilter(TextureSampler::MinFilter::LINEAR_MIPMAP_LINEAR);
        sampler.setMagFilter(TextureSampler::MagFilter::LINEAR);
        sampler.setWrapModeS(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        sampler.setWrapModeT(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        instance->setParameter("aoMap", g_aoMapTexture, sampler);
    }
    if (g_detailHeightTexture != nullptr && g_material->hasParameter("heightMap")) {
        TextureSampler sampler;
        sampler.setMinFilter(TextureSampler::MinFilter::LINEAR_MIPMAP_LINEAR);
        sampler.setMagFilter(TextureSampler::MagFilter::LINEAR);
        sampler.setWrapModeS(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        sampler.setWrapModeT(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        instance->setParameter("heightMap", g_detailHeightTexture, sampler);
    }
    if (g_material->hasParameter("pomScale")) {
        instance->setParameter("pomScale", g_pomScale);
    }
    if (g_material->hasParameter("pomStrength")) {
        instance->setParameter("pomStrength", g_pomStrength);
    }
    if (g_material->hasParameter("pomLayers")) {
        instance->setParameter("pomLayers", float(g_pomLayers));
    }
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
        // In the interactive viewer the combined material is always resident: it is a superset
        // of the AO materials, and compensationStrength=0 leaves it visually neutral. That makes
        // the compensation checkbox a uniform update instead of a material rebuild.
        bool const interactiveCompensation =
                g_ui && (materialPath == nullptr || materialPath[0] == '\0');
        if (g_shadeCompensate || interactiveCompensation) {
            g_material = Material::Builder()
                                 .package(RESOURCES_AILODCOMPENSATED_DATA,
                                         RESOURCES_AILODCOMPENSATED_SIZE)
                                 .build(*engine);
        } else if (g_bakeAoMapSize > 0 || !g_aoMapPath.empty()) {
            g_material = Material::Builder()
                                 .package(RESOURCES_AIBAKEDAOMAP_DATA, RESOURCES_AIBAKEDAOMAP_SIZE)
                                 .build(*engine);
        } else if (g_bakeAo) {
            g_material = Material::Builder()
                                 .package(RESOURCES_AIBAKEDAO_DATA, RESOURCES_AIBAKEDAO_SIZE)
                                 .build(*engine);
        } else {
            g_material = Material::Builder()
                                 .package(RESOURCES_AIDEFAULTMAT_DATA, RESOURCES_AIDEFAULTMAT_SIZE)
                                 .build(*engine);
        }
    }

    bool const hasAoMap = g_material != nullptr && g_material->hasParameter("aoMap");
    bool const consumesVertexAo =
            g_material != nullptr && g_material->hasParameter("aoStrength") && !hasAoMap;
    bool const supportsCompensation =
            g_material != nullptr && g_material->hasParameter("compensationStrength");
    // The combined compensation material always reads vertex AO as a fallback for assets whose
    // UV layout cannot be baked into a map. Neutral vertex colors leave the map in control.
    // The combined material always samples the vertex-color R channel, even when its
    // compensationStrength gate is 0, so the attribute layout must be present whenever the
    // material is selected (explicitly or as the interactive default).
    g_vertexColors = consumesVertexAo || supportsCompensation;
    if (g_bakeAo && !g_vertexColors) {
        if (!hasAoMap) {
            std::cerr << "Baked AO needs a material with an aoStrength parameter (aiBakedAo); "
                         "the selected material does not consume vertex colors."
                      << std::endl;
        }
    }

    if (g_detailNormalTexture == nullptr) {
        g_detailNormalTexture = loadDetailNormalTexture(engine, g_detailNormalPath.c_str());
    }
    if (g_detailHeightTexture == nullptr && !g_detailHeightPath.empty()) {
        g_detailHeightTexture = loadHeightMapTexture(engine, g_detailHeightPath.c_str());
        if (g_detailHeightTexture != nullptr && g_pomScaleAuto) {
            g_pomScale = readParallaxScaleSidecar(g_detailHeightPath);
        }
    }
    if (g_aoMapTexture == nullptr && !g_aoMapPath.empty()) {
        g_aoMapTexture = loadAoMapTexture(engine, g_aoMapPath.c_str());
        g_aoMapHasData = g_aoMapTexture != nullptr;
    }
    if (g_material->hasParameter("normal") && g_detailNormalTexture == nullptr) {
        g_detailNormalTexture = createNeutralNormalTexture(engine);
    }
    if (g_material->hasParameter("aoMap") && g_aoMapTexture == nullptr) {
        uint8_t const white = 255;
        g_aoMapTexture = createAoMapTexture(engine, &white, 1);
        g_aoMapHasData = false;
    }
    if (g_material->hasParameter("heightMap") && g_detailHeightTexture == nullptr) {
        g_detailHeightTexture = createNeutralHeightTexture(engine);
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
    if (g_material->hasParameter("reflectance")) {
        g_materialInstance->setParameter("reflectance", 0.5f);
    }
    applyShadingParameters(g_materialInstance);
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

void destroyCompactLodBuffers(Engine* engine);
void updateShadowCasterFlags(Engine* engine);

void destroyLodRenderable(Engine* engine) {
    if (g_scene != nullptr && g_lodRenderable) {
        g_scene->remove(g_lodRenderable);
    }
    if (engine != nullptr) {
        if (g_lodRenderable) {
            engine->destroy(g_lodRenderable);
            utils::EntityManager::get().destroy(g_lodRenderable);
        }
        destroyCompactLodBuffers(engine);
    }
    g_lodRenderable = {};
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
        applyShadingParameters(instance);
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

struct LodCompactDrawGroup {
    uint32_t materialId = UINT32_MAX;
    uint32_t firstIndex = 0;
    uint32_t indexCount = 0;
};

std::vector<LodCompactDrawGroup> buildCompactDrawGroups(mm::LodGraphSelection const& selection,
        std::vector<uint32_t> const& indices, std::vector<uint32_t>* reordered) {
    size_t const triangleCount = indices.size() / 3;
    std::vector<uint32_t> materials;
    if (selection.materialIds.size() == triangleCount) {
        materials = selection.materialIds;
    } else {
        materials.assign(triangleCount, UINT32_MAX);
    }

    std::vector<uint32_t> ids;
    ids.reserve(materials.size());
    for (uint32_t id: materials) {
        if (std::find(ids.begin(), ids.end(), id) == ids.end()) {
            ids.push_back(id);
        }
    }
    std::vector<uint32_t> counts(ids.size(), 0);
    for (uint32_t id: materials) {
        size_t const group = size_t(std::find(ids.begin(), ids.end(), id) - ids.begin());
        counts[group] += 3;
    }
    std::vector<uint32_t> offsets(ids.size() + 1, 0);
    for (size_t i = 0; i < ids.size(); ++i) {
        offsets[i + 1] = offsets[i] + counts[i];
    }

    std::vector<uint32_t> cursor = offsets;
    reordered->resize(indices.size());
    for (size_t triangle = 0; triangle < triangleCount; ++triangle) {
        size_t const group =
                size_t(std::find(ids.begin(), ids.end(), materials[triangle]) - ids.begin());
        uint32_t const target = cursor[group];
        reordered->at(target + 0) = indices[triangle * 3 + 0];
        reordered->at(target + 1) = indices[triangle * 3 + 1];
        reordered->at(target + 2) = indices[triangle * 3 + 2];
        cursor[group] += 3;
    }

    std::vector<LodCompactDrawGroup> groups(ids.size());
    for (size_t i = 0; i < ids.size(); ++i) {
        groups[i].materialId = ids[i];
        groups[i].firstIndex = offsets[i];
        groups[i].indexCount = counts[i];
    }
    return groups;
}

// A cut is a set of DAG nodes, each with its own range in the flattened index buffer. Drawing
// them one by one costs a draw call per node even when the ranges are adjacent. Merge exactly
// adjacent ranges that share a material; this changes only the draw count, not the triangles.
std::vector<LodCompactDrawGroup> buildCoalescedDrawGroups(std::vector<uint32_t> const& nodes,
        size_t* mergedRanges) {
    std::vector<LodCompactDrawGroup> groups;
    groups.reserve(nodes.size());
    for (uint32_t const nodeId: nodes) {
        if (nodeId >= g_lodGraph.nodes.size()) {
            continue;
        }
        mm::LodGraphNode const& node = g_lodGraph.nodes[nodeId];
        if (node.indices.empty()) {
            continue;
        }
        groups.push_back(
                { node.materialId, g_lodNodeFirstIndex[nodeId], g_lodNodeIndexCount[nodeId] });
    }

    std::sort(groups.begin(), groups.end(),
            [](LodCompactDrawGroup const& lhs, LodCompactDrawGroup const& rhs) {
                return lhs.firstIndex < rhs.firstIndex;
            });

    size_t const sourceCount = groups.size();
    size_t write = 0;
    for (size_t read = 0; read < groups.size(); ++read) {
        if (write == 0) {
            groups[write++] = groups[read];
            continue;
        }
        LodCompactDrawGroup& previous = groups[write - 1];
        LodCompactDrawGroup const& current = groups[read];
        uint32_t const previousEnd = previous.firstIndex + previous.indexCount;
        if (previous.materialId == current.materialId && previousEnd == current.firstIndex) {
            previous.indexCount += current.indexCount;
        } else {
            groups[write++] = current;
        }
    }
    groups.resize(write);
    if (mergedRanges != nullptr) {
        *mergedRanges = sourceCount - groups.size();
    }
    return groups;
}

// Concatenate the index lists of the current cut, grouped by material. Unlike compacting
// vertices this keeps the global vertex buffer untouched: the upload is a few kilobytes of
// indices, paid only when the cut changes, and the renderer needs one draw per material.
std::vector<LodCompactDrawGroup> buildCutIndexGroups(std::vector<uint32_t> const& nodes,
        std::vector<uint32_t>* reordered) {
    struct Group {
        uint32_t materialId;
        std::vector<uint32_t> indices;
    };
    std::vector<Group> groups;

    for (uint32_t const nodeId: nodes) {
        if (nodeId >= g_lodGraph.nodes.size()) {
            continue;
        }
        mm::LodGraphNode const& node = g_lodGraph.nodes[nodeId];
        if (node.indices.empty()) {
            continue;
        }
        auto it = std::find_if(groups.begin(), groups.end(),
                [&node](Group const& group) { return group.materialId == node.materialId; });
        if (it == groups.end()) {
            groups.push_back({ node.materialId, {} });
            it = groups.end() - 1;
        }
        it->indices.insert(it->indices.end(), node.indices.begin(), node.indices.end());
    }

    size_t indexCount = 0;
    for (Group const& group: groups) {
        indexCount += group.indices.size();
    }
    reordered->clear();
    reordered->reserve(indexCount);

    std::vector<LodCompactDrawGroup> draws;
    draws.reserve(groups.size());
    for (Group const& group: groups) {
        LodCompactDrawGroup draw;
        draw.materialId = group.materialId;
        draw.firstIndex = uint32_t(reordered->size());
        draw.indexCount = uint32_t(group.indices.size());
        reordered->insert(reordered->end(), group.indices.begin(), group.indices.end());
        draws.push_back(draw);
    }
    return draws;
}

// UV-derived tangents keep mirrored charts consistent. The detail baker uses the same frame,
// so a tangent-space map lands on the correct side of every chart.
void ensureLodTangents() {
    if (!g_lodTangents.empty() || g_lodMesh.positions.empty()) {
        return;
    }
    mm::computeUvTangents(g_lodMesh, g_lodMesh.indices, &g_lodTangents, &g_lodTangentSigns);
    if (!g_lodTangents.empty()) {
        return;
    }

    g_lodTangents.resize(g_lodMesh.positions.size());
    g_lodTangentSigns.assign(g_lodMesh.positions.size(), 1.0f);
    for (size_t i = 0; i < g_lodTangents.size(); ++i) {
        float3 const normal =
                i < g_lodMesh.normals.size() ? g_lodMesh.normals[i] : float3{ 0.0f, 0.0f, 1.0f };
        float3 bitangent;
        mm::computeVertexFrame(normal, &g_lodTangents[i], &bitangent);
    }
}

// Restores the normals that came out of the hierarchy, then optionally welds duplicate-position
// shading normals. The original snapshot is kept so the UI can toggle the pass without
// rebuilding the DAG.
float effectiveShadeStrength() noexcept {
    return g_shadeAuto ? mm::recommendedShadingNormalStrength(g_lodMaxScreenError)
                       : g_shadeStrength;
}

void applyLodShadingNormals() {
    if (g_lodOriginalNormals.size() != g_lodMesh.normals.size()) {
        return;
    }
    g_lodMesh.normals = g_lodOriginalNormals;
    if (g_shadeCreaseDegrees <= 0.0f) {
        return;
    }
    float const strength = effectiveShadeStrength();
    mm::ShadingNormalOptions options;
    options.creaseAngleDegrees = g_shadeCreaseDegrees;
    options.strength = strength;
    mm::ShadingNormalResult result;
    mm::repairShadingNormals(&g_lodMesh, g_lodMesh.indices, options, &result);
    std::printf("shade: crease=%.1fdeg strength=%.2f%s duplicateVertices=%zu mergedClusters=%zu "
                "changedVertices=%zu maxAngle=%.2fdeg\n",
            g_shadeCreaseDegrees, strength, g_shadeAuto ? " (auto)" : "", result.duplicateVertices,
            result.mergedClusters, result.changedVertices, result.maxMergedAngleDegrees);
    std::fflush(stdout);
}

// Re-uploads the tangent frame after the shading normals changed. Positions and UVs are
// unchanged, but the tangent has to stay orthogonal to the new normal.
void uploadLodVertexData(Engine* engine) {
    if (engine == nullptr || g_lodVertexBuffer == nullptr || g_lodMesh.positions.empty()) {
        return;
    }
    size_t const vertexCount = g_lodMesh.positions.size();
    auto* const positions = new float3[vertexCount];
    auto* const tangents = new float4[vertexCount];
    auto* const uvs = new float2[vertexCount];
    uint8_t* colors = g_vertexColors ? new uint8_t[vertexCount * 4] : nullptr;
    g_lodTangents.clear();
    g_lodTangentSigns.clear();
    ensureLodTangents();
    for (size_t i = 0; i < vertexCount; ++i) {
        float3 const n = normalize(g_lodMesh.normals[i]);
        float3 const tangent = g_lodTangents[i];
        float3 const bitangent = cross(n, tangent) * g_lodTangentSigns[i];
        auto const q =
                filament::math::details::TMat33<float>::packTangentFrame({ tangent, bitangent, n });
        positions[i] = g_lodMesh.positions[i];
        tangents[i] = q.xyzw;
        uvs[i] = g_lodMesh.hasUVs() ? g_lodMesh.uvs[i] : float2{ 0.0f, 0.0f };
        if (colors != nullptr) {
            float const ao = g_lodAo.size() == vertexCount ? g_lodAo[i] : 1.0f;
            uint8_t const value = uint8_t(std::clamp(ao, 0.0f, 1.0f) * 255.0f + 0.5f);
            float bentX = 0.0f;
            float bentY = 0.0f;
            if (i < g_lodBentNormals.size()) {
                float3 const bent = g_lodBentNormals[i];
                float const length2 = dot(bent, bent);
                if (length2 > 1e-12f) {
                    float3 const unit = bent * (1.0f / std::sqrt(length2));
                    if (dot(unit, n) >= 0.0f) {
                        bentX = dot(unit, tangent);
                        bentY = dot(unit, bitangent);
                    }
                }
            }
            float const xy2 = bentX * bentX + bentY * bentY;
            if (xy2 > 1.0f) {
                float const scale = 1.0f / std::sqrt(xy2);
                bentX *= scale;
                bentY *= scale;
            }
            colors[i * 4 + 0] = value;
            colors[i * 4 + 1] =
                    uint8_t(std::clamp(bentX * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f + 0.5f);
            colors[i * 4 + 2] =
                    uint8_t(std::clamp(bentY * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f + 0.5f);
            float const compensation =
                    i < g_lodCompensationWeights.size() ? g_lodCompensationWeights[i] : 1.0f;
            colors[i * 4 + 3] = uint8_t(std::clamp(compensation, 0.0f, 1.0f) * 255.0f + 0.5f);
        }
    }
    g_lodVertexBuffer->setBufferAt(*engine, 0,
            VertexBuffer::BufferDescriptor(positions, vertexCount * sizeof(float3),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float3*>(buffer); }));
    g_lodVertexBuffer->setBufferAt(*engine, 1,
            VertexBuffer::BufferDescriptor(tangents, vertexCount * sizeof(float4),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float4*>(buffer); }));
    g_lodVertexBuffer->setBufferAt(*engine, 2,
            VertexBuffer::BufferDescriptor(uvs, vertexCount * sizeof(float2),
                    [](void* buffer, size_t, void*) { delete[] static_cast<float2*>(buffer); }));
    if (colors != nullptr) {
        g_lodVertexBuffer->setBufferAt(*engine, 3,
                VertexBuffer::BufferDescriptor(colors, vertexCount * 4,
                        [](void* buffer, size_t, void*) {
                            delete[] static_cast<uint8_t*>(buffer);
                        }));
    }
}

// MSAA is not a material term, but it is part of the measured LOD compensation ladder:
// it smooths silhouette coverage that no shading term can recover. Keep the control in one
// place so the CLI, the UI combo and the measured preset cannot disagree.
void applyMultiSampleAntiAliasing(View* view) {
    if (view == nullptr) {
        return;
    }
    View::MultiSampleAntiAliasingOptions options;
    options.enabled = g_msaaSamples > 1;
    options.sampleCount = uint8_t(std::clamp(g_msaaSamples, 0, 8));
    view->setMultiSampleAntiAliasingOptions(options);
}

// GTAO is view-level visibility, not a material term. It is complementary to the baked AO:
// the bake knows the source cavities but cannot resolve where the current cut actually is,
// while GTAO sees the depth buffer of the cut that is on screen. It only attenuates indirect
// light, so it needs the environment IBL (or another ambient source) to change the image.
void applyScreenSpaceAmbientOcclusion(View* view) {
    if (view == nullptr) {
        return;
    }
    View::AmbientOcclusionOptions options = view->getAmbientOcclusionOptions();
    options.enabled = g_ssao || g_ssct;
    if (!options.enabled) {
        view->setAmbientOcclusionOptions(options);
        return;
    }
    options.aoType = View::AmbientOcclusionOptions::AmbientOcclusionType::GTAO;
    options.radius = g_ssaoRadius > 0.0f ? g_ssaoRadius : std::max(0.1f * g_sceneDiagonal, 1e-4f);
    options.intensity = g_ssaoIntensity;
    options.power = g_ssaoPower;
    options.resolution = g_ssaoResolution < 0.75f ? 0.5f : 1.0f;
    options.quality = View::QualityLevel::HIGH;
    options.lowPassFilter = View::QualityLevel::HIGH;
    options.upsampling = View::QualityLevel::HIGH;
    options.bilateralThreshold = 0.05f;
    options.bentNormals = g_ssaoBentNormals;
    options.ssct.enabled = g_ssct;
    options.ssct.lightDirection = normalize(float3{ 0.6f, -1.0f, -0.8f });
    options.ssct.intensity = g_ssctIntensity;
    options.ssct.lightConeRad = g_ssctConeAngleRad;
    options.ssct.shadowDistance = g_ssctShadowDistance > 0.0f
                                          ? g_ssctShadowDistance
                                          : std::max(0.25f * g_sceneDiagonal, 1e-3f);
    options.ssct.contactDistanceMax = g_ssctContactDistanceMax > 0.0f
                                              ? g_ssctContactDistanceMax
                                              : std::max(0.5f * g_sceneDiagonal, 1e-3f);
    options.ssct.sampleCount = 8;
    options.ssct.rayCount = 1;
    switch (g_ssaoQuality) {
        default:
        case 0:
            options.gtao.sampleSliceCount = 4;
            options.gtao.sampleStepsPerSlice = 3;
            break;
        case 1:
            options.gtao.sampleSliceCount = 6;
            options.gtao.sampleStepsPerSlice = 3;
            break;
        case 2:
            options.gtao.sampleSliceCount = 8;
            options.gtao.sampleStepsPerSlice = 4;
            break;
        case 3:
            options.gtao.sampleSliceCount = 12;
            options.gtao.sampleStepsPerSlice = 6;
            break;
    }
    view->setAmbientOcclusionOptions(options);
}

VertexBuffer* createCompactLodVertexBuffer(Engine* engine,
        std::vector<uint32_t> const& globalVertexIds) {
    size_t const vertexCount = globalVertexIds.size();
    if (vertexCount == 0) {
        return nullptr;
    }
    auto* const positions = new float3[vertexCount];
    auto* const tangents = new float4[vertexCount];
    auto* const uvs = new float2[vertexCount];
    uint8_t* colors = g_vertexColors ? new uint8_t[vertexCount * 4] : nullptr;
    ensureLodTangents();
    for (size_t i = 0; i < vertexCount; ++i) {
        uint32_t const global = globalVertexIds[i];
        float3 const n = normalize(g_lodMesh.normals[global]);
        float3 const tangent = g_lodTangents[global];
        float3 const bitangent = cross(n, tangent) * g_lodTangentSigns[global];
        auto const q =
                filament::math::details::TMat33<float>::packTangentFrame({ tangent, bitangent, n });
        positions[i] = g_lodMesh.positions[global];
        tangents[i] = q.xyzw;
        uvs[i] = g_lodMesh.hasUVs() ? g_lodMesh.uvs[global] : float2{ 0.0f, 0.0f };
        if (colors != nullptr) {
            float const ao = global < g_lodAo.size() ? g_lodAo[global] : 1.0f;
            uint8_t const value = uint8_t(std::clamp(ao, 0.0f, 1.0f) * 255.0f + 0.5f);
            float bentX = 0.0f;
            float bentY = 0.0f;
            if (global < g_lodBentNormals.size()) {
                float3 const bent = g_lodBentNormals[global];
                float const length2 = dot(bent, bent);
                if (length2 > 1e-12f) {
                    float3 const unit = bent * (1.0f / std::sqrt(length2));
                    if (dot(unit, n) >= 0.0f) {
                        bentX = dot(unit, tangent);
                        bentY = dot(unit, bitangent);
                    }
                }
            }
            float const xy2 = bentX * bentX + bentY * bentY;
            if (xy2 > 1.0f) {
                float const scale = 1.0f / std::sqrt(xy2);
                bentX *= scale;
                bentY *= scale;
            }
            colors[i * 4 + 0] = value;
            colors[i * 4 + 1] =
                    uint8_t(std::clamp(bentX * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f + 0.5f);
            colors[i * 4 + 2] =
                    uint8_t(std::clamp(bentY * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f + 0.5f);
            float const compensation = global < g_lodCompensationWeights.size()
                                               ? g_lodCompensationWeights[global]
                                               : 1.0f;
            colors[i * 4 + 3] = uint8_t(std::clamp(compensation, 0.0f, 1.0f) * 255.0f + 0.5f);
        }
    }
    VertexBuffer::Builder builder =
            VertexBuffer::Builder()
                    .vertexCount(uint32_t(vertexCount))
                    .bufferCount(colors != nullptr ? 4 : 3)
                    .attribute(VertexAttribute::POSITION, 0, VertexBuffer::AttributeType::FLOAT3)
                    .attribute(VertexAttribute::TANGENTS, 1, VertexBuffer::AttributeType::FLOAT4)
                    .attribute(VertexAttribute::UV0, 2, VertexBuffer::AttributeType::FLOAT2);
    if (colors != nullptr) {
        builder.attribute(VertexAttribute::COLOR, 3, VertexBuffer::AttributeType::UBYTE4)
                .normalized(VertexAttribute::COLOR);
    }
    VertexBuffer* const buffer = builder.build(*engine);
    buffer->setBufferAt(*engine, 0,
            VertexBuffer::BufferDescriptor(positions, vertexCount * sizeof(float3),
                    [](void* data, size_t, void*) { delete[] static_cast<float3*>(data); }));
    buffer->setBufferAt(*engine, 1,
            VertexBuffer::BufferDescriptor(tangents, vertexCount * sizeof(float4),
                    [](void* data, size_t, void*) { delete[] static_cast<float4*>(data); }));
    buffer->setBufferAt(*engine, 2,
            VertexBuffer::BufferDescriptor(uvs, vertexCount * sizeof(float2),
                    [](void* data, size_t, void*) { delete[] static_cast<float2*>(data); }));
    if (colors != nullptr) {
        buffer->setBufferAt(*engine, 3,
                VertexBuffer::BufferDescriptor(colors, vertexCount * 4,
                        [](void* data, size_t, void*) { delete[] static_cast<uint8_t*>(data); }));
    }
    return buffer;
}

IndexBuffer* createLodIndexBuffer(Engine* engine, std::vector<uint32_t> const& indices,
        uint32_t vertexCount) {
    size_t const capacity = std::max<size_t>(indices.size(), 3);
    bool const wide = vertexCount > 65535;
    IndexBuffer* const buffer = IndexBuffer::Builder()
                                        .indexCount(uint32_t(capacity))
                                        .bufferType(wide ? IndexBuffer::IndexType::UINT
                                                         : IndexBuffer::IndexType::USHORT)
                                        .build(*engine);
    if (wide) {
        auto* const data = new uint32_t[capacity]();
        std::copy(indices.begin(), indices.end(), data);
        buffer->setBuffer(*engine, IndexBuffer::BufferDescriptor(data, capacity * sizeof(uint32_t),
                                           [](void* value, size_t, void*) {
                                               delete[] static_cast<uint32_t*>(value);
                                           }));
    } else {
        auto* const data = new uint16_t[capacity]();
        for (size_t i = 0; i < indices.size(); ++i) {
            data[i] = uint16_t(indices[i]);
        }
        buffer->setBuffer(*engine, IndexBuffer::BufferDescriptor(data, capacity * sizeof(uint16_t),
                                           [](void* value, size_t, void*) {
                                               delete[] static_cast<uint16_t*>(value);
                                           }));
    }
    return buffer;
}

void destroyCompactLodBuffers(Engine* engine) {
    if (engine != nullptr) {
        if (g_lodCompactVertexBuffer != nullptr) {
            engine->destroy(g_lodCompactVertexBuffer);
        }
        if (g_lodCompactIndexBuffer != nullptr) {
            engine->destroy(g_lodCompactIndexBuffer);
        }
    }
    g_lodCompactVertexBuffer = nullptr;
    g_lodCompactIndexBuffer = nullptr;
    g_lodCompactFirstIndex.clear();
    g_lodCompactIndexCount.clear();
    g_lodCompactMaterialIds.clear();
}

// Flatten every DAG node's index list into one static GPU buffer. A cut then only changes draw
// ranges; unlike the previous path it never rebuilds or re-uploads the index buffer.
void createLodNodeTable() {
    if (!g_lodNodeFirstIndex.empty() || g_lodGraph.nodes.empty()) {
        return;
    }
    if (g_lodGpuBuffer.nodes.empty()) {
        g_lodGpuBuffer = mm::flattenLodGraph(g_lodGraph);
    }
    g_lodNodeFirstIndex.resize(g_lodGpuBuffer.nodes.size());
    g_lodNodeIndexCount.resize(g_lodGpuBuffer.nodes.size());
    for (size_t i = 0; i < g_lodGpuBuffer.nodes.size(); ++i) {
        g_lodNodeFirstIndex[i] = g_lodGpuBuffer.nodes[i].indexOffset;
        g_lodNodeIndexCount[i] = g_lodGpuBuffer.nodes[i].indexCount;
    }
    if (g_compactCutIndices) {
        std::vector<uint32_t> const& nodes =
                g_showOriginal ? g_lodGraph.leaves : g_lodSelection.nodes;
        std::vector<uint32_t> materials;
        for (uint32_t const nodeId: nodes) {
            if (nodeId >= g_lodGraph.nodes.size()) {
                continue;
            }
            uint32_t const materialId = g_lodGraph.nodes[nodeId].materialId;
            if (std::find(materials.begin(), materials.end(), materialId) == materials.end()) {
                materials.push_back(materialId);
            }
        }
        g_lodPrimitiveCapacity = uint32_t(std::max<size_t>(materials.size(), 1));
    } else if (g_mergeDraws) {
        std::vector<uint32_t> const& nodes =
                g_showOriginal ? g_lodGraph.leaves : g_lodSelection.nodes;
        size_t mergedRanges = 0;
        g_lodPrimitiveCapacity = uint32_t(
                std::max<size_t>(buildCoalescedDrawGroups(nodes, &mergedRanges).size(), 1));
    } else {
        g_lodPrimitiveCapacity = uint32_t(
                std::max<size_t>({ g_lodGraph.leaves.size(), g_lodSelection.nodes.size(), 1 }));
    }
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

    if (g_lodIndexBuffer == nullptr) {
        g_lodIndexBuffer =
                createLodIndexBuffer(engine, g_lodGpuBuffer.indices, g_lodGraph.vertexCount);
        if (g_lodIndexBuffer == nullptr) {
            return;
        }
    }

    g_lodRenderable = utils::EntityManager::get().create();
    RenderableManager::Builder builder(g_lodPrimitiveCapacity);
    builder.boundingBox(g_lodBounds)
            .culling(false)
            .receiveShadows(true)
            .castShadows(g_shadows && !g_shadowProxy);
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
    updateShadowCasterFlags(engine);
}

bool shadowProxyCastsShadows() noexcept {
    return g_shadowProxy && g_shadows && g_shadowProxyRenderable && g_shadowProxyTriangles > 0;
}

void applyShadowBias(Engine* engine) {
    if (engine == nullptr || !g_lightEntity) {
        return;
    }
    LightManager& lcm = engine->getLightManager();
    LightManager::Instance const instance = lcm.getInstance(g_lightEntity);
    if (!instance) {
        return;
    }
    LightManager::ShadowOptions options = lcm.getShadowOptions(instance);
    options.constantBias = shadowProxyCastsShadows() ? g_shadowProxyConstantBias : 0.001f;
    options.normalBias = shadowProxyCastsShadows() ? g_shadowProxyNormalBias : 1.0f;
    lcm.setShadowOptions(instance, options);
}

void updateShadowCasterFlags(Engine* engine) {
    if (engine == nullptr) {
        return;
    }
    RenderableManager& rcm = engine->getRenderableManager();
    bool const proxyCasts = shadowProxyCastsShadows();
    if (g_lodRenderable) {
        RenderableManager::Instance const instance = rcm.getInstance(g_lodRenderable);
        if (instance) {
            rcm.setCastShadows(instance, g_shadows && !proxyCasts);
        }
    }
    if (g_shadowProxyRenderable) {
        RenderableManager::Instance const instance = rcm.getInstance(g_shadowProxyRenderable);
        if (instance) {
            rcm.setCastShadows(instance, proxyCasts);
        }
    }
}

// Rebuilds the shadow-only index range. The proxy shares the LOD vertex buffer: both the full
// source range and every generated vertex live there, so selecting a finer cut costs one index
// buffer, not a second copy of the asset. The material writes neither colour nor depth; only
// Filament's depth variant used by the shadow pass samples this geometry.
void refreshShadowProxyGeometry(Engine* engine) {
    if (engine == nullptr || g_scene == nullptr || g_lodVertexBuffer == nullptr) {
        return;
    }
    if (g_shadowProxyMaterial == nullptr) {
        g_shadowProxyMaterial =
                Material::Builder()
                        .package(RESOURCES_SHADOWPROXY_DATA, RESOURCES_SHADOWPROXY_SIZE)
                        .build(*engine);
        if (g_shadowProxyMaterial != nullptr) {
            g_shadowProxyMaterialInstance = g_shadowProxyMaterial->createInstance();
        }
    }
    if (g_shadowProxyMaterialInstance == nullptr) {
        std::cerr << "Shadow proxy material could not be created." << std::endl;
        return;
    }

    std::vector<uint32_t> indices;
    if (g_shadowProxyRatio >= 0.999f) {
        indices = g_lodMesh.indices;
        g_shadowProxySelection = {};
    } else {
        g_shadowProxySelection = mm::selectLodGraphAtRatio(g_lodGraph, g_lodCamera,
                std::clamp(g_shadowProxyRatio, 0.02f, 1.0f), 64.0f);
        indices = g_shadowProxySelection.indices;
    }
    if (indices.empty()) {
        std::cerr << "Shadow proxy selection is empty." << std::endl;
        return;
    }

    IndexBuffer* const newIndexBuffer =
            createLodIndexBuffer(engine, indices, uint32_t(g_lodMesh.positions.size()));
    if (newIndexBuffer == nullptr) {
        return;
    }

    RenderableManager& rcm = engine->getRenderableManager();
    if (!g_shadowProxyRenderable) {
        g_shadowProxyRenderable = utils::EntityManager::get().create();
        RenderableManager::Builder builder(1);
        builder.boundingBox(g_lodBounds)
                .culling(false)
                .receiveShadows(false)
                .castShadows(g_shadows)
                .material(0, g_shadowProxyMaterialInstance)
                .geometry(0, RenderableManager::PrimitiveType::TRIANGLES, g_lodVertexBuffer,
                        newIndexBuffer, 0, uint32_t(indices.size()));
        builder.build(*engine, g_shadowProxyRenderable);
        engine->getTransformManager().create(g_shadowProxyRenderable);
    } else {
        RenderableManager::Instance const instance = rcm.getInstance(g_shadowProxyRenderable);
        rcm.setGeometryAt(instance, 0, RenderableManager::PrimitiveType::TRIANGLES,
                g_lodVertexBuffer, newIndexBuffer, 0, uint32_t(indices.size()));
    }
    if (g_shadowProxyIndexBuffer != nullptr) {
        engine->destroy(g_shadowProxyIndexBuffer);
    }
    g_shadowProxyIndexBuffer = newIndexBuffer;
    g_shadowProxyTriangles = uint32_t(indices.size() / 3);

    if (!g_shadowProxyInScene) {
        g_scene->addEntity(g_shadowProxyRenderable);
        g_shadowProxyInScene = true;
    }
    updateShadowCasterFlags(engine);
    applyShadowBias(engine);
    std::printf("shadow proxy: triangles=%u ratio=%.2f%s\n", g_shadowProxyTriangles,
            g_shadowProxyRatio, g_shadows ? "" : " (shadows are disabled)");
    std::fflush(stdout);
}

void setShadowProxyEnabled(Engine* engine, bool enabled) {
    if (g_shadowProxy == enabled) {
        return;
    }
    g_shadowProxy = enabled;
    if (enabled) {
        refreshShadowProxyGeometry(engine);
    } else {
        if (g_scene != nullptr && g_shadowProxyRenderable && g_shadowProxyInScene) {
            g_scene->remove(g_shadowProxyRenderable);
            g_shadowProxyInScene = false;
        }
        updateShadowCasterFlags(engine);
        applyShadowBias(engine);
        std::printf("shadow proxy: disabled\n");
        std::fflush(stdout);
    }
}

void destroyShadowProxy(Engine* engine) {
    if (g_scene != nullptr && g_shadowProxyRenderable && g_shadowProxyInScene) {
        g_scene->remove(g_shadowProxyRenderable);
    }
    if (engine != nullptr) {
        if (g_shadowProxyRenderable) {
            engine->destroy(g_shadowProxyRenderable);
        }
        if (g_shadowProxyIndexBuffer != nullptr) {
            engine->destroy(g_shadowProxyIndexBuffer);
        }
        if (g_shadowProxyMaterialInstance != nullptr) {
            engine->destroy(g_shadowProxyMaterialInstance);
        }
        if (g_shadowProxyMaterial != nullptr) {
            engine->destroy(g_shadowProxyMaterial);
        }
    }
    g_shadowProxyRenderable = {};
    g_shadowProxyIndexBuffer = nullptr;
    g_shadowProxyMaterialInstance = nullptr;
    g_shadowProxyMaterial = nullptr;
    g_shadowProxyTriangles = 0;
    g_shadowProxyInScene = false;
    g_shadowProxySelection = {};
}

// Uploading only the generated vertices a cut uses trades a cut-time rebuild for a smaller
// resident vertex buffer. A production renderer would keep per-node ranges and compact on the
// GPU; doing it on the CPU here makes the memory saving and the visual result directly
// comparable with the full-buffer path.
void rebuildCompactLodGeometry(Engine* engine) {
    mm::LodGraphCompactOptions compactOptions;
    compactOptions.compactSourceVertices = true;
    mm::LodGraphCutGeometry const compacted =
            mm::compactLodSelection(g_lodGraph, g_lodSelection, compactOptions);
    if (compacted.vertexCount == 0 || compacted.indices.empty()) {
        return;
    }

    std::vector<uint32_t> reordered;
    std::vector<LodCompactDrawGroup> const groups =
            buildCompactDrawGroups(g_lodSelection, compacted.indices, &reordered);

    // Generated ids are renumbered into the compacted tail, so translating them back through
    // generatedSourceIds gives the attribute row in g_lodMesh that was appended at build time.
    std::vector<uint32_t> globalIds(compacted.vertexCount);
    for (uint32_t i = 0; i < compacted.sourceVertexCount; ++i) {
        globalIds[i] = compacted.sourceVertexIds.empty() ? i : compacted.sourceVertexIds[i];
    }
    for (size_t i = 0; i < compacted.generatedSourceIds.size(); ++i) {
        globalIds[compacted.sourceVertexCount + i] =
                g_lodGraph.sourceVertexCount() + compacted.generatedSourceIds[i];
    }

    VertexBuffer* const vertexBuffer = createCompactLodVertexBuffer(engine, globalIds);
    IndexBuffer* const indexBuffer =
            createLodIndexBuffer(engine, reordered, compacted.vertexCount);
    if (vertexBuffer == nullptr || indexBuffer == nullptr) {
        if (vertexBuffer != nullptr) {
            engine->destroy(vertexBuffer);
        }
        if (indexBuffer != nullptr) {
            engine->destroy(indexBuffer);
        }
        return;
    }

    if (groups.size() > g_lodPrimitiveCapacity) {
        destroyLodRenderable(engine);
        g_lodPrimitiveCapacity = uint32_t(groups.size());
        createLodRenderable(engine);
        if (!g_lodRenderable) {
            engine->destroy(indexBuffer);
            engine->destroy(vertexBuffer);
            return;
        }
    }
    g_lodDrawnTriangles = reordered.size() / 3;
    RenderableManager& rcm = engine->getRenderableManager();
    RenderableManager::Instance const instance = rcm.getInstance(g_lodRenderable);
    size_t const groupCount = std::min<size_t>(groups.size(), g_lodPrimitiveCapacity);
    for (uint32_t i = 0; i < g_lodPrimitiveCapacity; ++i) {
        if (i < groupCount) {
            rcm.setMaterialInstanceAt(instance, i, lodMaterialFor(groups[i].materialId));
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    vertexBuffer, indexBuffer, groups[i].firstIndex, groups[i].indexCount);
        } else {
            rcm.setMaterialInstanceAt(instance, i, g_materialInstance);
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    vertexBuffer, indexBuffer, 0, 0);
        }
    }

    destroyCompactLodBuffers(engine);
    g_lodCompactVertexBuffer = vertexBuffer;
    g_lodCompactIndexBuffer = indexBuffer;
    g_lodCompactFirstIndex.resize(groupCount);
    g_lodCompactIndexCount.resize(groupCount);
    g_lodCompactMaterialIds.resize(groupCount);
    for (size_t i = 0; i < groupCount; ++i) {
        g_lodCompactFirstIndex[i] = groups[i].firstIndex;
        g_lodCompactIndexCount[i] = groups[i].indexCount;
        g_lodCompactMaterialIds[i] = groups[i].materialId;
    }
    if (g_dag) {
        std::printf("dag: compactUpload vertices=%u indices=%zu groups=%zu\n",
                compacted.vertexCount, reordered.size(), groupCount);
    }
}

void rebuildCutIndexGeometry(Engine* engine) {
    std::vector<uint32_t> reordered;
    std::vector<LodCompactDrawGroup> const groups =
            buildCutIndexGroups(g_lodSelection.nodes, &reordered);
    IndexBuffer* const indexBuffer =
            createLodIndexBuffer(engine, reordered, g_lodGraph.vertexCount);
    if (indexBuffer == nullptr) {
        return;
    }

    if (groups.size() != g_lodPrimitiveCapacity) {
        destroyLodRenderable(engine);
        g_lodPrimitiveCapacity = uint32_t(std::max<size_t>(groups.size(), 1));
        createLodRenderable(engine);
        if (!g_lodRenderable || g_lodIndexBuffer == nullptr) {
            engine->destroy(indexBuffer);
            return;
        }
    }

    RenderableManager& rcm = engine->getRenderableManager();
    RenderableManager::Instance const instance = rcm.getInstance(g_lodRenderable);
    for (uint32_t i = 0; i < g_lodPrimitiveCapacity; ++i) {
        if (i < groups.size()) {
            rcm.setMaterialInstanceAt(instance, i, lodMaterialFor(groups[i].materialId));
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, indexBuffer, groups[i].firstIndex, groups[i].indexCount);
        } else {
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, indexBuffer, 0, 0);
        }
    }

    destroyCompactLodBuffers(engine);
    g_lodCompactIndexBuffer = indexBuffer;
    g_lodDrawnTriangles = reordered.size() / 3;
    g_lodCompactFirstIndex.resize(groups.size());
    g_lodCompactIndexCount.resize(groups.size());
    g_lodCompactMaterialIds.resize(groups.size());
    for (size_t i = 0; i < groups.size(); ++i) {
        g_lodCompactFirstIndex[i] = groups[i].firstIndex;
        g_lodCompactIndexCount[i] = groups[i].indexCount;
        g_lodCompactMaterialIds[i] = groups[i].materialId;
    }
    if (g_dag) {
        std::printf("dag: compactCutIndices indices=%zu drawGroups=%zu\n", reordered.size(),
                groups.size());
    }
}

void rebuildLodGeometry(Engine* engine) {
    if (engine == nullptr || g_materialInstance == nullptr || g_scene == nullptr) {
        return;
    }
    createLodRenderable(engine);
    if (!g_lodRenderable || g_lodIndexBuffer == nullptr) {
        return;
    }

    if (g_compactVertices && !g_showOriginal && !g_lodSelection.nodes.empty()) {
        rebuildCompactLodGeometry(engine);
        return;
    }
    if (g_compactCutIndices && !g_showOriginal && !g_lodSelection.nodes.empty()) {
        rebuildCutIndexGeometry(engine);
        return;
    }

    std::vector<uint32_t> const& nodes = g_showOriginal ? g_lodGraph.leaves : g_lodSelection.nodes;
    std::vector<LodCompactDrawGroup> coalesced;
    size_t mergedRanges = 0;
    if (g_mergeDraws) {
        coalesced = buildCoalescedDrawGroups(nodes, &mergedRanges);
    }
    size_t const drawGroupCount = g_mergeDraws ? coalesced.size() : nodes.size();
    size_t const capacity = std::max<size_t>(drawGroupCount, 1);
    if (capacity > g_lodPrimitiveCapacity ||
            (g_mergeDraws && !g_distanceLod && capacity != g_lodPrimitiveCapacity)) {
        // Retain the peak capacity as the camera moves. The static index buffer stays
        // resident even when a larger cut needs a new renderable.
        destroyLodRenderable(engine);
        g_lodPrimitiveCapacity = uint32_t(capacity);
        createLodRenderable(engine);
        if (!g_lodRenderable) {
            return;
        }
    }
    if (g_dag) {
        std::printf("dag: drawCalls cutNodes=%zu drawGroups=%zu mergedRanges=%zu\n", nodes.size(),
                drawGroupCount, mergedRanges);
    }
    // Each selected DAG node owns a prebuilt index range. Unused primitive slots are hidden with
    // a zero index count, so changing a cut performs no CPU index packing and no GPU upload.
    RenderableManager& rcm = engine->getRenderableManager();
    RenderableManager::Instance const instance = rcm.getInstance(g_lodRenderable);
    g_lodDrawnTriangles = 0;
    for (uint32_t i = 0; i < g_lodPrimitiveCapacity; ++i) {
        if (g_mergeDraws && i < coalesced.size()) {
            LodCompactDrawGroup const& group = coalesced[i];
            rcm.setMaterialInstanceAt(instance, i, lodMaterialFor(group.materialId));
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, g_lodIndexBuffer, group.firstIndex, group.indexCount);
            g_lodDrawnTriangles += group.indexCount / 3;
        } else if (!g_mergeDraws && i < nodes.size()) {
            uint32_t const nodeId = nodes[i];
            mm::LodGraphNode const& node = g_lodGraph.nodes[nodeId];
            rcm.setMaterialInstanceAt(instance, i, lodMaterialFor(node.materialId));
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, g_lodIndexBuffer, g_lodNodeFirstIndex[nodeId],
                    g_lodNodeIndexCount[nodeId]);
            g_lodDrawnTriangles += g_lodNodeIndexCount[nodeId] / 3;
        } else {
            rcm.setGeometryAt(instance, i, RenderableManager::PrimitiveType::TRIANGLES,
                    g_lodVertexBuffer, g_lodIndexBuffer, 0, 0);
        }
    }
    destroyCompactLodBuffers(engine);
}

// A cut can mix fine near nodes and coarse far nodes. A single global compensation strength
// cannot be right for both, so the combined material can read a per-vertex weight from colour
// alpha. The weight is the maximum over the selected nodes that reference the vertex, which
// keeps shared chart vertices conservative. With the option off every vertex stays at 1, so
// the material behaves exactly as before.
void updateLodCompensationWeights() {
    size_t const vertexCount = g_lodMesh.positions.size();
    g_lodCompensationWeights.assign(vertexCount, 1.0f);
    if (!g_shadeErrorDriven || g_showOriginal || g_lodSelection.nodes.empty()) {
        return;
    }
    std::fill(g_lodCompensationWeights.begin(), g_lodCompensationWeights.end(), 0.0f);
    for (size_t i = 0; i < g_lodSelection.nodes.size(); ++i) {
        uint32_t const nodeId = g_lodSelection.nodes[i];
        if (nodeId >= g_lodGraph.nodes.size()) {
            continue;
        }
        float const error = i < g_lodSelection.screenErrorPerNode.size()
                                    ? g_lodSelection.screenErrorPerNode[i]
                                    : g_lodMaxScreenError;
        float const weight = mm::recommendedShadingCompensationWeight(error);
        for (uint32_t const vertex: g_lodGraph.nodes[nodeId].indices) {
            if (vertex < vertexCount) {
                g_lodCompensationWeights[vertex] =
                        std::max(g_lodCompensationWeights[vertex], weight);
            }
        }
    }
    if (g_dag) {
        float minimum = 1.0f;
        float maximum = 0.0f;
        double sum = 0.0;
        size_t count = 0;
        for (uint32_t const vertex: g_lodSelection.indices) {
            if (vertex >= g_lodCompensationWeights.size()) {
                continue;
            }
            float const weight = g_lodCompensationWeights[vertex];
            minimum = std::min(minimum, weight);
            maximum = std::max(maximum, weight);
            sum += double(weight);
            ++count;
        }
        if (count > 0) {
            std::printf("shade: error-driven weight min=%.2f mean=%.2f max=%.2f "
                        "referencedVertices=%zu\n",
                    minimum, float(sum / double(count)), maximum, count);
            std::fflush(stdout);
        }
    }
}

bool updateLodSelection(Engine* engine, bool cameraUpdate = false) {
    if (g_lodGraph.nodes.empty()) {
        return false;
    }
    auto const start = std::chrono::steady_clock::now();
    mm::LodGraphSelection selection;
    bool changed = true;
    float const targetKeep = std::clamp(1.0f - g_lodSavings, 0.01f, 1.0f);
    mm::LodTierProfile const profile = mm::lodTierProfile(g_lodTier);
    float const ceiling = g_ignoreQualityCeiling ? std::numeric_limits<float>::infinity()
                                                 : profile.maxScreenErrorPx;
    if (g_distanceLod) {
        // Runtime path: one traversal of the DAG. Error is divided by the node's view depth,
        // so a fixed pixel threshold naturally yields fine geometry near and coarse far.
        bool selectedOnGpu = false;
        if (g_gpuCutActive && engine != nullptr) {
            mmbench::GpuCutResult gpuResult;
            std::string error;
            if (g_gpuCutSelector.select(*engine, g_lodCamera, g_lodScreenErrorPx, &gpuResult,
                        &error)) {
                std::sort(gpuResult.nodes.begin(), gpuResult.nodes.end());
                selection = mm::assembleLodSelection(g_lodGraph, g_lodCamera,
                        std::move(gpuResult.nodes), gpuResult.culledTriangles);
                g_gpuCutNodeCount = uint32_t(selection.nodes.size());
                g_gpuCutSelectedTriangles = gpuResult.selectedTriangles;
                g_gpuCutCulledTriangles = gpuResult.culledTriangles;
                g_gpuCutMs = gpuResult.wallMs;
                selectedOnGpu = true;

                if (!g_gpuCutVerified) {
                    mm::LodGraphSelection const cpu =
                            mm::selectLodGraph(g_lodGraph, g_lodCamera, g_lodScreenErrorPx);
                    std::vector<uint32_t> const& gpuNodes = selection.nodes;
                    std::vector<uint32_t> cpuNodes = cpu.nodes;
                    std::sort(cpuNodes.begin(), cpuNodes.end());
                    uint64_t mismatch = 0;
                    size_t gpuIndex = 0;
                    size_t cpuIndex = 0;
                    while (gpuIndex < gpuNodes.size() && cpuIndex < cpuNodes.size()) {
                        if (gpuNodes[gpuIndex] == cpuNodes[cpuIndex]) {
                            ++gpuIndex;
                            ++cpuIndex;
                        } else if (gpuNodes[gpuIndex] < cpuNodes[cpuIndex]) {
                            ++mismatch;
                            ++gpuIndex;
                        } else {
                            ++mismatch;
                            ++cpuIndex;
                        }
                    }
                    mismatch += gpuNodes.size() - gpuIndex;
                    mismatch += cpuNodes.size() - cpuIndex;
                    g_gpuCutNodeMismatch = mismatch;
                    g_gpuCutTriangleMismatch =
                            gpuResult.selectedTriangles > cpu.selectedTriangles
                                    ? gpuResult.selectedTriangles - cpu.selectedTriangles
                                    : cpu.selectedTriangles - gpuResult.selectedTriangles;
                    g_gpuCutVerified = true;
                    std::printf("gpu: cut nodes=%zu triangles=%llu gpuWall=%.3fms "
                                "cpuNodes=%zu cpuTriangles=%llu nodeMismatch=%llu "
                                "triangleMismatch=%llu\n",
                            selection.nodes.size(),
                            (unsigned long long) gpuResult.selectedTriangles, gpuResult.wallMs,
                            cpu.nodes.size(), (unsigned long long) cpu.selectedTriangles,
                            (unsigned long long) g_gpuCutNodeMismatch,
                            (unsigned long long) g_gpuCutTriangleMismatch);
                    std::fflush(stdout);
                }
            } else {
                if (g_gpuCutError != error) {
                    g_gpuCutError = error;
                    std::printf("gpu: cut disabled: %s\n", error.c_str());
                    std::fflush(stdout);
                }
                g_gpuCutActive = false;
            }
        }
        if (selectedOnGpu) {
            changed = !cameraUpdate || selection.nodes != g_lodSelection.nodes;
        } else if (cameraUpdate) {
            mm::selectLodGraphCut(g_lodGraph, g_lodCamera, g_lodScreenErrorPx, g_lodRuntimeCut);
            mm::LodGraphCut const& cut = g_lodRuntimeCut;
            changed = cut.nodes != g_lodSelection.nodes;
            if (changed && (g_ui || g_compactVertices || g_shadeErrorDriven)) {
                selection = mm::assembleLodSelection(g_lodGraph, g_lodCamera,
                        cut.nodes, cut.culledTriangles);
            } else {
                // Static draw ranges and compact-cut indices both consume node IDs directly.
                if (changed) {
                    selection.nodes = cut.nodes;
                    selection.nodesPerLevel = cut.nodesPerLevel;
                    selection.trianglesPerLevel = cut.trianglesPerLevel;
                }
                selection.baseTriangles = cut.baseTriangles;
                selection.selectedTriangles = cut.selectedTriangles;
                // Keep both the traversal scratch and the previous frame's error buffer alive.
                selection.screenErrorPerNode.swap(g_lodSelection.screenErrorPerNode);
                selection.screenErrorPerNode.assign(
                        cut.screenErrorPerNode.begin(), cut.screenErrorPerNode.end());
                selection.culledTriangles = cut.culledTriangles;
            }
        } else {
            selection = mm::selectLodGraph(g_lodGraph, g_lodCamera, g_lodScreenErrorPx);
        }
    } else {
        // Editor path: solve for the most detailed cut that fits a triangle budget. This is a
        // binary search over thresholds and is intentionally not the per-frame runtime path.
        selection = mm::selectLodGraphAtRatio(g_lodGraph, g_lodCamera, targetKeep, ceiling);
    }
    auto const end = std::chrono::steady_clock::now();
    g_lodSelectionMs = std::chrono::duration<double, std::milli>(end - start).count();
    if (changed) {
        g_lodSelection = std::move(selection);
        g_lodSelectedTriangles = uint32_t(g_lodSelection.selectedTriangles);
        if (!cameraUpdate || g_ui) {
            mm::LodGraphCompactOptions compactOptions;
            compactOptions.compactSourceVertices = true;
            auto const compactStart = std::chrono::steady_clock::now();
            mm::LodGraphCutGeometry const compacted =
                    mm::compactLodSelection(g_lodGraph, g_lodSelection, compactOptions);
            auto const compactEnd = std::chrono::steady_clock::now();
            g_lodCompactMs =
                    std::chrono::duration<double, std::milli>(compactEnd - compactStart).count();
            g_lodCutVertexCount = compacted.vertexCount;
            g_lodCutGeneratedVertices = uint32_t(compacted.generatedVertices.size());
            g_lodTopology = mm::measureTopology(g_lodMesh, g_lodSelection.indices);
        }
    } else {
        g_lodSelection.screenErrorPerNode = std::move(selection.screenErrorPerNode);
        g_lodSelection.culledTriangles = selection.culledTriangles;
    }
    g_lodMaxScreenError = 0.0f;
    for (float error: g_lodSelection.screenErrorPerNode) {
        g_lodMaxScreenError = std::max(g_lodMaxScreenError, error);
    }
    if (!cameraUpdate || g_shadeErrorDriven) {
        updateLodCompensationWeights();
    }
    return changed;
}

void printBuildProfile(char const* name, mm::SimplifyProfile const& profile) {
    std::printf("dag: %s profile attributeQem=%.3fs corner=%.3fs meshopt=%.3fs gate=%.3fs "
                "boundary=%.3fs lockMask=%.3fs (build %.3fs) accepted=%llu attempts=%llu "
                "rejectedTopology=%llu rejectedGeometry=%llu rejectedAttributes=%llu "
                "rejectedBoundary=%llu rejectedLocked=%llu\n",
            name, profile.attributeQemSeconds, profile.cornerSeconds, profile.meshoptSeconds,
            profile.candidateGateSeconds, profile.boundaryCheckSeconds, profile.lockedMaskSeconds,
            profile.lockedMaskBuildSeconds, (unsigned long long) profile.accepted,
            (unsigned long long) profile.attempts, (unsigned long long) profile.rejectedTopology,
            (unsigned long long) profile.rejectedGeometry,
            (unsigned long long) profile.rejectedAttributes,
            (unsigned long long) profile.rejectedBoundary,
            (unsigned long long) profile.rejectedLocked);
    std::printf("dag: %s corner setup=%.3fs evaluate=%.3fs topology=%.3fs target=%.3fs "
                "apply=%.3fs evaluations=%llu placementTests=%llu applied=%llu\n",
            name, profile.cornerSetupSeconds, profile.cornerEvaluateSeconds,
            profile.cornerEvaluateTopologySeconds, profile.cornerEvaluateTargetSeconds,
            profile.cornerApplySeconds, (unsigned long long) profile.cornerEvaluations,
            (unsigned long long) profile.cornerPlacementTests,
            (unsigned long long) profile.cornerApplied);
    std::printf("dag: %s candidate cleanup=%.3fs slivers=%.3fs errors=%.3fs topology=%.3fs "
                "weldedTopology=%.3fs\n",
            name, profile.candidateCleanupSeconds, profile.candidateSliverSeconds,
            profile.candidateErrorSeconds, profile.candidateTopologySeconds,
            profile.weldedTopologySeconds);
    std::printf("dag: %s extendedMesh=%.3fs copies=%llu\n", name, profile.extendedMeshSeconds,
            (unsigned long long) profile.extendedMeshCopies);
}

void reportLodStats() {
    std::printf("dag: build total=%.3fs clusterize=%.3fs leafSetup=%.3fs clusterChains=%.3fs "
                "groups=%.3fs (groupSimplify %.3fs)\n",
            g_lodGraphBuildStats.totalSeconds, g_lodGraphBuildStats.clusterizeSeconds,
            g_lodGraphBuildStats.leafSetupSeconds, g_lodGraphBuildStats.clusterChainSeconds,
            g_lodGraphBuildStats.groupBuildSeconds, g_lodGraphBuildStats.groupSimplifySeconds);
    std::printf("dag: build clusterCalls=%llu clusterAccepted=%llu clusterAttempts=%llu "
                "groupCandidates=%llu groupCalls=%llu groupAccepted=%llu "
                "groupAttempts=%llu seamLocked=%llu generated=%llu\n",
            (unsigned long long) g_lodGraphBuildStats.clusterSimplifyCalls,
            (unsigned long long) g_lodGraphBuildStats.clusterSimplifyAccepted,
            (unsigned long long) g_lodGraphBuildStats.clusterSimplifyAttempts,
            (unsigned long long) g_lodGraphBuildStats.groupCandidates,
            (unsigned long long) g_lodGraphBuildStats.groupSimplifyCalls,
            (unsigned long long) g_lodGraphBuildStats.groupSimplifyAccepted,
            (unsigned long long) g_lodGraphBuildStats.groupSimplifyAttempts,
            (unsigned long long) g_lodGraphBuildStats.seamLockedVertices,
            (unsigned long long) g_lodGraphBuildStats.generatedVertices);
    printBuildProfile("cluster", g_lodGraphBuildStats.clusterSimplify);
    printBuildProfile("group", g_lodGraphBuildStats.groupSimplify);

    double const ratio = g_lodBaseTriangles > 0
                                 ? double(g_lodSelectedTriangles) / double(g_lodBaseTriangles)
                                 : 0.0;
    std::printf("dag: nodes=%zu levels=%u leaves=%zu roots=%zu baseTriangles=%llu "
                "sourceVertices=%u generatedVertices=%zu\n",
            g_lodGraph.nodes.size(), g_lodGraph.levelCount, g_lodGraph.leaves.size(),
            g_lodGraph.roots.size(), (unsigned long long) g_lodGraph.baseTriangles,
            g_lodGraph.sourceVertexCount(), g_lodGraph.generatedVertices.size());
    std::printf("dag: selectedTriangles=%u ratio=%.4f worstScreenError=%.3fpx "
                "nonManifold=%llu duplicate=%llu flipped=%llu minQuality=%.4f selectionMs=%.3f "
                "compactMs=%.3f mode=%s\n",
            g_lodSelectedTriangles, ratio, g_lodMaxScreenError,
            (unsigned long long) g_lodTopology.nonManifoldEdges,
            (unsigned long long) g_lodTopology.duplicateTriangles,
            (unsigned long long) g_lodTopology.flippedTriangles, g_lodTopology.minTriangleQuality,
            g_lodSelectionMs, g_lodCompactMs, g_distanceLod ? "distance" : "savings");
    if (g_gpuCutActive) {
        std::printf("dag: gpuCut nodes=%u triangles=%llu culledTriangles=%llu wall=%.3fms "
                    "nodeMismatch=%llu triangleMismatch=%llu verified=%d\n",
                g_gpuCutNodeCount, (unsigned long long) g_gpuCutSelectedTriangles,
                (unsigned long long) g_gpuCutCulledTriangles, g_gpuCutMs,
                (unsigned long long) g_gpuCutNodeMismatch,
                (unsigned long long) g_gpuCutTriangleMismatch, g_gpuCutVerified ? 1 : 0);
    }
    std::printf("dag: drawCalls cutNodes=%zu compactGroups=%zu compactUpload=%s\n",
            g_lodSelection.nodes.size(), g_lodCompactIndexCount.size(),
            g_compactVertices ? "on" : "off");
    std::printf("dag: drawing=%s drawnTriangles=%llu\n",
            g_showOriginal ? "original" : "selectedCut",
            (unsigned long long) g_lodDrawnTriangles);
    std::printf("dag: cutVertices=%u of %u (generated %u of %zu, %.1f%% of global buffer)\n",
            g_lodCutVertexCount, g_lodGraph.vertexCount, g_lodCutGeneratedVertices,
            g_lodGraph.generatedVertices.size(),
            g_lodGraph.vertexCount > 0
                    ? 100.0 * double(g_lodCutVertexCount) / double(g_lodGraph.vertexCount)
                    : 0.0);
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
        mm::selectLodGraphCut(g_lodGraph, g_lodCamera,
                g_distanceLod ? g_lodScreenErrorPx : g_lodMaxScreenError, runtimeCut);
    }
    auto const cutEnd = std::chrono::steady_clock::now();
    double const averageMs = std::chrono::duration<double, std::milli>(cutEnd - cutStart).count() /
                             double(iterations);
    std::printf("dag: runtimeCut nodes=%zu triangles=%llu avg=%.4fms iterations=%d\n",
            runtimeCut.nodes.size(), (unsigned long long) runtimeCut.selectedTriangles, averageMs,
            iterations);
    std::fflush(stdout);

    // The two full-selection paths have different costs: distance-aware selection walks the DAG
    // once, while the editor's savings slider binary-searches thresholds and assembles a cut for
    // every probe. Timing both here keeps a regression in either path visible.
    auto const timeFullSelection = [&](char const* name, auto&& select) {
        constexpr int SELECTION_ITERATIONS = 5;
        uint64_t selectedTriangles = 0;
        auto const start = std::chrono::steady_clock::now();
        for (int i = 0; i < SELECTION_ITERATIONS; ++i) {
            mm::LodGraphSelection const selection = select();
            selectedTriangles += selection.selectedTriangles;
        }
        auto const end = std::chrono::steady_clock::now();
        double const ms = std::chrono::duration<double, std::milli>(end - start).count() /
                          double(SELECTION_ITERATIONS);
        std::printf("dag: selection %s avg=%.4fms iterations=%d avgTriangles=%llu\n", name, ms,
                SELECTION_ITERATIONS,
                (unsigned long long) (selectedTriangles / SELECTION_ITERATIONS));
    };
    float const targetKeep = std::clamp(1.0f - g_lodSavings, 0.01f, 1.0f);
    mm::LodTierProfile const profile = mm::lodTierProfile(g_lodTier);
    float const ceiling = g_ignoreQualityCeiling ? std::numeric_limits<float>::infinity()
                                                 : profile.maxScreenErrorPx;
    timeFullSelection("distance",
            [&] { return mm::selectLodGraph(g_lodGraph, g_lodCamera, g_lodScreenErrorPx); });
    timeFullSelection("savings", [&] {
        return mm::selectLodGraphAtRatio(g_lodGraph, g_lodCamera, targetKeep, ceiling);
    });
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

// Creates the texture a map-based material samples. The map can come from a file or from a
// runtime bake. A map material must never sample an unbound texture: Filament's fallback is
// black, which turns "no AO data" into a 50% darkening instead of a neutral LOD. Keeping the
// white 1x1 fallback here covers both the UI path and the plain headless path.
void ensureAoMapTexture(Engine* engine, mm::Mesh const* source) {
    bool const requested = g_bakeAoMapSize > 0 || !g_aoMapPath.empty();
    // A neutral 1x1 fallback is created eagerly for the interactive compensation material. It
    // must not block a later bake, hence the check is on data rather than on the texture pointer.
    if (!requested || g_aoMapHasData) {
        return;
    }
    if (g_bakeAoMapSize > 0 && source != nullptr) {
        mm::AmbientOcclusionMapOptions mapOptions;
        mapOptions.samples = g_aoSamples;
        mapOptions.size = g_bakeAoMapSize;
        mapOptions.radius = g_aoRadius;
        mm::AmbientOcclusionMapResult aoMap;
        if (mm::bakeAmbientOcclusionMap(*source, mapOptions, &aoMap)) {
            Texture* const previous = g_aoMapTexture;
            Texture* const baked = createAoMapTexture(engine, aoMap.values.data(), aoMap.size);
            if (baked != nullptr) {
                g_aoMapTexture = baked;
                g_aoMapHasData = true;
                if (previous != nullptr && engine != nullptr) {
                    engine->destroy(previous);
                }
            }
            std::printf("baked source AO map: %ux%u, %zu covered texels, %u samples, "
                        "radius %.5f%s, mean %.3f min %.3f, %.1f ms\n",
                    aoMap.size, aoMap.size, aoMap.coveredTexels, g_aoSamples, aoMap.radius,
                    g_aoRadius > 0.0f ? "" : " (auto)", aoMap.mean, aoMap.min, aoMap.bakeMs);
        } else {
            std::cerr << "Source AO map bake failed: it needs UVs in [0,1] and source normals. "
                         "The map stays neutral; shading compensation falls back to vertex AO, "
                         "or use --bake-ao explicitly."
                      << std::endl;
        }
    }
    if (g_aoMapTexture == nullptr) {
        uint8_t const white = 255;
        g_aoMapTexture = createAoMapTexture(engine, &white, 1);
        g_aoMapHasData = false;
    }
    applyShadingParameters(g_materialInstance);
}

// Bakes the high-poly surface response into the UV atlas of the current cut. The normal map is
// cut-dependent (it compares the source surface against the triangles actually selected), while
// the AO map is source-level and is reused. Both maps are optional: when the asset has no
// unique UV atlas, the material falls back to the neutral maps and vertex AO.
void applyLodCompensationMaps(Engine* engine) {
    if (!g_shadeCompensate || engine == nullptr || g_material == nullptr ||
            g_lodSelection.indices.empty()) {
        return;
    }

    Texture* previousNormalTexture = nullptr;
    if (g_compensateNormalStrength > 0.0f && g_detailNormalPath.empty() &&
            g_material->hasParameter("normal")) {
        mm::DetailBakeOptions options;
        options.size = g_compensateSize;
        mm::DetailBakeResult detail;
        if (mm::bakeDetailNormalMap(g_lodMesh, g_lodMesh, g_lodSelection.indices, options,
                    &detail)) {
            Texture* const baked = createRgbaTexture(engine, detail.rgba.data(), detail.size);
            if (baked != nullptr) {
                previousNormalTexture = g_detailNormalTexture;
                g_detailNormalTexture = baked;
            }
            std::printf("baked LOD compensation normal: %ux%u, %zu covered texels, "
                        "mean lost normal %.2f deg, max %.2f deg\n",
                    detail.size, detail.size, detail.coveredTexels, detail.meanAngleDegrees,
                    detail.maxAngleDegrees);
        } else {
            std::cerr << "LOD compensation normal bake skipped: the source and cut need "
                         "unique UVs in [0,1]. Shading stays on the LOD normals."
                      << std::endl;
        }
    }

    if (g_detailNormalTexture == nullptr && g_material->hasParameter("normal")) {
        g_detailNormalTexture = createNeutralNormalTexture(engine);
    }
    if (g_aoMapTexture == nullptr && g_material->hasParameter("aoMap")) {
        uint8_t const white = 255;
        g_aoMapTexture = createAoMapTexture(engine, &white, 1);
        g_aoMapHasData = false;
    }

    applyShadingParameters(g_materialInstance);
    for (MaterialInstance* instance: g_lodMaterialInstances) {
        applyShadingParameters(instance);
    }
    // The material instances now point at the new map; the old texture is no longer referenced.
    if (previousNormalTexture != nullptr && previousNormalTexture != g_detailNormalTexture) {
        engine->destroy(previousNormalTexture);
    }
    bool const normalActive = g_compensateNormalStrength > 0.0f && g_detailNormalTexture != nullptr;
    char const* aoState =
            g_aoMapHasData ? "map"
                           : (g_lodAo.size() == g_lodMesh.positions.size() ? "vertex" : "neutral");
    std::printf("shading compensation: normal=%s ao=%s roughnessBoost=%.2f\n",
            normalActive ? "baked/loaded" : "neutral", aoState, g_roughnessBoost);
    std::fflush(stdout);
}

bool bakeLodVertexAo();

void applyMeasuredShadingPreset(Engine* engine, View* view);

mm::ViewCamera readLodCamera(Camera const& camera, Viewport const& viewport) {
    mm::ViewCamera result;
    result.eye = float3(camera.getPosition());
    result.target = result.eye + camera.getForwardVector();
    result.up = camera.getUpVector();
    result.fovY = camera.getFieldOfViewInDegrees(Camera::Fov::VERTICAL) *
            (3.14159265358979323846f / 180.0f);
    result.screenWidth = viewport.width;
    result.screenHeight = viewport.height;
    result.near = float(camera.getNear());
    result.far = float(camera.getCullingFar());
    return result;
}

// Runtime A/B switch for the interactive viewer. The combined material is already resident, so
// this only changes a uniform plus the lazily baked inputs; no material or renderable rebuild is
// needed. Enabling attempts a texture-space AO bake first and falls back to vertex AO for assets
// whose UV layout cannot be baked (no UVs, tiled atlases, out-of-range coordinates).
void setLodCompensationEnabled(Engine* engine, bool enabled) {
    if (g_shadeCompensate == enabled) {
        return;
    }
    g_shadeCompensate = enabled;
    if (!enabled) {
        if (g_compensateBakeSizeAuto) {
            g_bakeAoMapSize = 0;
            g_compensateBakeSizeAuto = false;
        }
        applyShadingParameters(g_materialInstance);
        for (MaterialInstance* instance: g_lodMaterialInstances) {
            applyShadingParameters(instance);
        }
        std::printf("shading compensation: disabled\n");
        std::fflush(stdout);
        return;
    }

    if (g_bakeAoMapSize == 0 && g_aoMapPath.empty()) {
        g_bakeAoMapSize = g_compensateSize;
        g_compensateBakeSizeAuto = true;
    }
    ensureAoMapTexture(engine, &g_lodMesh);
    if (!g_aoMapHasData) {
        std::printf("shading compensation: texture AO unavailable, using vertex AO\n");
        bakeLodVertexAo();
    }
    uploadLodVertexData(engine);
    // The compact path owns a separate vertex buffer built from the current AO array. Refresh
    // it here; otherwise a cut uploaded before the toggle would keep neutral white colors.
    if (g_compactVertices && !g_showOriginal && !g_lodSelection.nodes.empty()) {
        rebuildCompactLodGeometry(engine);
    }
    applyLodCompensationMaps(engine);
    std::fflush(stdout);
}

// Builds a small directional SH environment. It is intentionally procedural: the bent-normal
// comparison must work without shipping a cubemap, and three SH bands are enough to show which
// side of the source mesh was open. A real game would replace this with its normal IBL.
void createEnvironmentIbl(Engine* engine, Scene* scene) {
    if (!g_ibl || g_indirectLight != nullptr || engine == nullptr || scene == nullptr) {
        return;
    }
    constexpr float kPi = 3.14159265358979323846f;
    constexpr uint32_t kThetaSamples = 32;
    constexpr uint32_t kPhiSamples = 64;
    float3 const up = normalize(float3{ 0.2f, 1.0f, 0.35f });
    float3 sh[9] = {};
    float const dTheta = kPi / float(kThetaSamples);
    float const dPhi = 2.0f * kPi / float(kPhiSamples);
    for (uint32_t thetaIndex = 0; thetaIndex < kThetaSamples; ++thetaIndex) {
        float const theta = (float(thetaIndex) + 0.5f) * dTheta;
        float const sinTheta = std::sin(theta);
        float const cosTheta = std::cos(theta);
        for (uint32_t phiIndex = 0; phiIndex < kPhiSamples; ++phiIndex) {
            float const phi = (float(phiIndex) + 0.5f) * dPhi;
            float3 const direction{ sinTheta * std::cos(phi), sinTheta * std::sin(phi), cosTheta };
            float const lobe = std::max(0.0f, dot(direction, up));
            float3 const radiance = float3{ 0.08f } + float3{ 0.92f, 0.97f, 1.0f } * lobe;
            float const solidAngle = sinTheta * dTheta * dPhi;
            float const basis[9] = {
                0.282095f,
                -0.488603f * direction.y,
                0.488603f * direction.z,
                -0.488603f * direction.x,
                1.092548f * direction.x * direction.y,
                -1.092548f * direction.y * direction.z,
                0.315392f * (3.0f * direction.z * direction.z - 1.0f),
                -1.092548f * direction.x * direction.z,
                0.546274f * (direction.x * direction.x - direction.y * direction.y),
            };
            for (size_t coefficient = 0; coefficient < 9; ++coefficient) {
                sh[coefficient] += radiance * (basis[coefficient] * solidAngle);
            }
        }
    }
    g_indirectLight =
            IndirectLight::Builder().radiance(3, sh).intensity(g_iblIntensity).build(*engine);
    scene->setIndirectLight(g_indirectLight);
}

// Vertex AO needs no UV atlas, so it is both the explicit --bake-ao path and the automatic
// fallback when a compensation material cannot bake a texture-space map (no UVs, tiled UVs,
// or UVs outside [0,1]). It is idempotent so the UI can call it after toggling compensation on.
bool bakeLodVertexAo() {
    size_t const vertexCount = g_lodMesh.positions.size();
    if (vertexCount == 0) {
        return false;
    }
    if (g_lodAo.size() == vertexCount) {
        return true;
    }
    mm::AmbientOcclusionOptions aoOptions;
    aoOptions.samples = g_aoSamples;
    aoOptions.radius = g_aoRadius;
    mm::AmbientOcclusionResult ao;
    if (!mm::bakeVertexAmbientOcclusion(g_lodMesh, g_lodMesh, aoOptions, &ao)) {
        std::cerr << "Source AO bake failed; LOD shading stays uncompensated." << std::endl;
        return false;
    }
    g_lodAo = ao.values;
    g_lodBentNormals = ao.bentNormals;
    std::printf("baked source AO: %zu vertices, %u samples, radius %.5f%s, mean %.3f "
                "min %.3f, bent %.1f/%.1f deg mean/max on %zu vertices, "
                "%zu welded position groups, %.1f ms\n",
            ao.bakedVertices, g_aoSamples, ao.radius, g_aoRadius > 0.0f ? "" : " (auto)", ao.mean,
            ao.min, ao.meanBendDegrees, ao.maxBendDegrees, ao.tiltedVertices, ao.weldedGroups,
            ao.bakeMs);
    std::fflush(stdout);
    return true;
}

void setupLodViewer(Engine* engine, View* view, Scene* scene) {
    g_lodTangents.clear();
    g_lodTangentSigns.clear();
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
    graphOptions.simplify.cornerSimplify = g_cornerSimplify;
    graphOptions.simplify.cornerSplitDivergentUv = g_cornerSplitUv;
    g_lodGraph = mm::buildLodGraph(g_lodMesh, graphOptions, &g_lodGraphBuildStats);
    mm::appendGeneratedVertices(&g_lodMesh, g_lodGraph.generatedVertices);
    g_lodGpuBuffer = {};
    g_gpuCutActive = false;
    g_gpuCutVerified = false;
    g_gpuCutNodeMismatch = 0;
    g_gpuCutTriangleMismatch = 0;
    if (g_gpuCut) {
        g_lodGpuBuffer = mm::flattenLodGraph(g_lodGraph);
        std::string error;
        if (g_gpuCutSelector.create(*engine, g_config.backend, g_lodGpuBuffer, &error)) {
            g_gpuCutActive = true;
            std::printf("gpu: cut initialized nodes=%zu backend=%s\n", g_lodGpuBuffer.nodes.size(),
                    g_config.backend == Engine::Backend::VULKAN ? "vulkan" : "opengl");
            std::fflush(stdout);
        } else {
            g_gpuCutError = error;
            std::printf("gpu: cut unavailable: %s\n", error.c_str());
            std::fflush(stdout);
        }
    }
    ensureAoMapTexture(engine, &g_lodMesh);
    bool const explicitVertexAo = g_bakeAo && g_bakeAoMapSize == 0 && g_aoMapPath.empty();
    bool const compensationFallback = g_shadeCompensate && !g_aoMapHasData;
    if (explicitVertexAo || compensationFallback) {
        if (compensationFallback && !explicitVertexAo) {
            std::printf("shading compensation: no usable AO map, falling back to vertex AO\n");
        }
        bakeLodVertexAo();
    }
    g_lodOriginalNormals = g_lodMesh.normals;
    g_lodBaseTriangles = uint32_t(g_lodMesh.triangleCount());

    math::float3 lo{};
    math::float3 hi{};
    mm::computeBounds(g_lodMesh, &lo, &hi);
    g_sceneDiagonal = length(hi - lo);
    g_lodBounds.center = (lo + hi) * 0.5f;
    g_lodBounds.halfExtent = (hi - lo) * 0.5f;
    // Mean curvature has units of 1/length. Multiplying by the mesh radius makes a feature
    // whose radius equals the whole asset saturate at 1, independent of asset scale.
    if (g_curvatureScaleAuto) {
        g_curvatureScale = std::max(0.5f * length(hi - lo), 1e-3f);
    }

    if (g_autoFrame) {
        float3 const center = (lo + hi) * 0.5f;
        float const radius = std::max(0.5f * length(hi - lo), 1e-3f);
        float const distance = radius / std::tan(22.5f * 3.14159265358979323846f / 180.0f) * 1.15f;
        g_target = center;
        g_eye = center + normalize(float3{ 0.8f, 0.55f, 1.8f }) * distance;
    }

    createLodMaterialInstances();

    size_t const vertexCount = g_lodMesh.positions.size();
    VertexBuffer::Builder vertexBuilder =
            VertexBuffer::Builder()
                    .vertexCount(uint32_t(vertexCount))
                    .bufferCount(g_vertexColors ? 4 : 3)
                    .attribute(VertexAttribute::POSITION, 0, VertexBuffer::AttributeType::FLOAT3)
                    .attribute(VertexAttribute::TANGENTS, 1, VertexBuffer::AttributeType::FLOAT4)
                    .attribute(VertexAttribute::UV0, 2, VertexBuffer::AttributeType::FLOAT2);
    if (g_vertexColors) {
        vertexBuilder.attribute(VertexAttribute::COLOR, 3, VertexBuffer::AttributeType::UBYTE4)
                .normalized(VertexAttribute::COLOR);
    }
    g_lodVertexBuffer = vertexBuilder.build(*engine);
    uploadLodVertexData(engine);

    Viewport const& vp = view->getViewport();
    g_screenHeightForJitter = int(vp.height);
    g_cameraEntity = utils::EntityManager::get().create();
    g_camera = engine->createCamera(g_cameraEntity);
    float const aspect = vp.height > 0 ? float(vp.width) / float(vp.height) : 1.0f;
    float const distance = length(g_eye - g_target);
    g_camera->setProjection(45.0, aspect, std::max(distance * 0.01, 1e-3), distance * 20.0);
    g_camera->lookAt(g_eye, g_target, { 0.0f, 1.0f, 0.0f });
    view->setCamera(g_camera);
    g_lodCamera = readLodCamera(*g_camera, vp);
    if (!g_distanceLod) {
        // Keep the fixed-budget reference camera used by the geometry comparisons.
        g_lodCamera.near = mm::ViewCamera{}.near;
        g_lodCamera.far = mm::ViewCamera{}.far;
    }
    writeCameraList(int(vp.width), int(vp.height));
    updateLodSelection(engine);
    bool presetApplied = false;
    if (g_autoShadingPreset) {
        applyMeasuredShadingPreset(engine, view);
        presetApplied = true;
    }
    if (!presetApplied && g_shadeErrorDriven) {
        uploadLodVertexData(engine);
    }
    if (!presetApplied && g_shadeCreaseDegrees > 0.0f) {
        applyLodShadingNormals();
        uploadLodVertexData(engine);
    }
    // The detail normal map has to see the repaired vertex normals: its tangent frame is built
    // from the same geometry that will be rendered.
    if (!presetApplied && g_shadeCompensate) {
        applyLodCompensationMaps(engine);
    }
    rebuildLodGeometry(engine);
    if (g_shadowProxy) {
        refreshShadowProxyGeometry(engine);
    }
    if (g_dag) {
        reportLodStats();
    }

    LightManager::ShadowOptions shadowOptions;
    if (g_shadowProxy) {
        shadowOptions.constantBias = g_shadowProxyConstantBias;
        shadowOptions.normalBias = g_shadowProxyNormalBias;
    }
    g_lightEntity = utils::EntityManager::get().create();
    LightManager::Builder(LightManager::Type::SUN)
            .color(Color::toLinear<ACCURATE>(sRGBColor{ 0.98f, 0.92f, 0.89f }))
            .intensity(g_sunIntensity)
            .direction({ 0.6f, -1.0f, -0.8f })
            .castShadows(g_shadows)
            .shadowOptions(shadowOptions)
            .build(*engine, g_lightEntity);
    scene->addEntity(g_lightEntity);

    view->setPostProcessingEnabled(false);
    if (g_taa) {
        view->setPostProcessingEnabled(true);
        View::TemporalAntiAliasingOptions options;
        options.enabled = true;
        options.feedback = 0.1f;
        view->setTemporalAntiAliasingOptions(options);
    }
    applyMultiSampleAntiAliasing(view);
    applyScreenSpaceAmbientOcclusion(view);
}

// Applies the measured shading ladder to the current cut. At extreme savings the surface terms
// are disabled because AO becomes blocky on large triangles and detail normals regress; MSAA
// plus seam-normal repair is the only repeatable gain. At 45%+ the vertex-AO preset is used.
void applyMeasuredShadingPreset(Engine* engine, View* view) {
    if (engine == nullptr) {
        return;
    }
    double const selectedRatio = g_lodBaseTriangles > 0 ? 100.0 * double(g_lodSelectedTriangles) /
                                                                  double(g_lodBaseTriangles)
                                                        : 0.0;
    bool const hasCompensation =
            g_material != nullptr && g_material->hasParameter("compensationStrength");
    float const retainedRatio = float(std::clamp(selectedRatio / 100.0, 0.0, 1.0));
    mm::ShadingCompensationPreset const preset =
            mm::recommendedShadingCompensationPreset(retainedRatio, hasCompensation);
    if (preset.useAmbientOcclusion) {
        setLodCompensationEnabled(engine, true);
        g_compensationStrength = 1.0f;
        g_aoStrength = preset.ambientOcclusionStrength;
        g_compensateNormalStrength = 0.0f;
        g_roughnessBoost = 0.0f;
        g_pomStrength = 0.0f;
        applyShadingParameters(g_materialInstance);
        for (MaterialInstance* instance: g_lodMaterialInstances) {
            applyShadingParameters(instance);
        }
    } else {
        setLodCompensationEnabled(engine, false);
    }
    if (preset.enableMsaa) {
        g_msaaSamples = preset.msaaSamples;
        applyMultiSampleAntiAliasing(view);
    }
    std::printf("shading preset: ratio=%.2f%% mode=%s compensation=%d msaa=%d\n", selectedRatio,
            preset.useAmbientOcclusion ? "ao+seam" : "msaa+seam", g_shadeCompensate ? 1 : 0,
            g_msaaSamples);
    std::fflush(stdout);
    g_shadeCreaseDegrees = preset.normalCreaseDegrees;
    g_shadeAuto = preset.autoNormalStrength;
    g_shadeStrength = preset.normalStrength;
    applyLodShadingNormals();
    uploadLodVertexData(engine);
}

void drawLodUi(Engine* engine, View* view) {
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
    if (g_material != nullptr && g_material->hasParameter("compensationStrength") &&
            !ImGui::GetIO().WantTextInput && ImGui::IsKeyPressed(ImGuiKey_C, false)) {
        setLodCompensationEnabled(engine, !g_shadeCompensate);
    }
    if (!ImGui::GetIO().WantTextInput && ImGui::IsKeyPressed(ImGuiKey_P, false)) {
        setShadowProxyEnabled(engine, !g_shadowProxy);
    }
    ImGui::SetNextWindowSize(ImVec2(360.0f, 340.0f), ImGuiCond_FirstUseEver);
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
    ImGui::BeginDisabled(!g_shadows);
    if (ImGui::Checkbox("High-poly shadow proxy  [P]", &g_shadowProxy)) {
        setShadowProxyEnabled(engine, g_shadowProxy);
    }
    ImGui::SameLine();
    if (g_shadows) {
        ImGui::TextDisabled("%s", g_shadowProxy ? "on" : "off");
    } else {
        ImGui::TextDisabled("shadows off");
    }
    if (g_shadowProxy) {
        float proxyRatio = g_shadowProxyRatio;
        ImGui::SliderFloat("Shadow proxy detail", &proxyRatio, 0.10f, 1.0f, "%.2f");
        g_shadowProxyRatio = proxyRatio;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            refreshShadowProxyGeometry(engine);
        }
        float constantBias = g_shadowProxyConstantBias;
        ImGui::SliderFloat("Shadow bias", &constantBias, 0.0f, 0.05f, "%.4f m");
        g_shadowProxyConstantBias = constantBias;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadowBias(engine);
        }
        float normalBias = g_shadowProxyNormalBias;
        ImGui::SliderFloat("Shadow normal bias", &normalBias, 0.0f, 8.0f, "%.2f");
        g_shadowProxyNormalBias = normalBias;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadowBias(engine);
        }
        ImGui::Text("Proxy: %u triangles (visible cut %u)", g_shadowProxyTriangles,
                g_lodSelectedTriangles);
        ImGui::TextDisabled("1.00 keeps the exact source mesh; lower values use a finer cut "
                            "than the visible LOD. The proxy casts shadows only: it writes no "
                            "colour or camera depth.");
    }
    ImGui::EndDisabled();
    rebuildGeometry |= ImGui::Checkbox("Show original", &g_showOriginal);
    rebuildGeometry |= ImGui::Checkbox("Material colours", &g_showMaterialColors);
    rebuildGeometry |= ImGui::Checkbox("Compact cut vertices", &g_compactVertices);
    int msaaIndex = g_msaaSamples >= 8 ? 3 : g_msaaSamples >= 4 ? 2 : g_msaaSamples >= 2 ? 1 : 0;
    char const* const msaaItems[] = { "Off", "2x", "4x", "8x" };
    if (ImGui::Combo("MSAA", &msaaIndex, msaaItems, 4)) {
        g_msaaSamples = msaaIndex == 3 ? 8 : msaaIndex == 2 ? 4 : msaaIndex == 1 ? 2 : 0;
        applyMultiSampleAntiAliasing(view);
    }
    ImGui::TextDisabled("Measured extreme-LOD winner: 4x MSAA; mobile may prefer 2x.");
    if (ImGui::Checkbox("Screen-space AO (GTAO)", &g_ssao)) {
        if (!g_ssao) {
            g_ssct = false;
        }
        applyScreenSpaceAmbientOcclusion(view);
    }
    ImGui::SameLine();
    ImGui::TextDisabled("%s", g_ssao ? "on" : "off");
    if (g_ssao) {
        float const maxRadius = std::max(0.01f, 0.5f * std::max(g_sceneDiagonal, 0.02f));
        float radius = g_ssaoRadius;
        if (ImGui::SliderFloat("SSAO radius", &radius, 0.0f, maxRadius, "%.4f")) {
            g_ssaoRadius = radius;
            applyScreenSpaceAmbientOcclusion(view);
        }
        ImGui::TextDisabled("0 = auto (10%% of the bounds diagonal).");
        float intensity = g_ssaoIntensity;
        if (ImGui::SliderFloat("SSAO intensity", &intensity, 0.0f, 2.0f, "%.2f")) {
            g_ssaoIntensity = intensity;
            applyScreenSpaceAmbientOcclusion(view);
        }
        float power = g_ssaoPower;
        if (ImGui::SliderFloat("SSAO power", &power, 0.1f, 4.0f, "%.2f")) {
            g_ssaoPower = power;
            applyScreenSpaceAmbientOcclusion(view);
        }
        char const* const qualityItems[] = { "Low", "Medium", "High", "Ultra" };
        if (ImGui::Combo("SSAO quality", &g_ssaoQuality, qualityItems, 4)) {
            applyScreenSpaceAmbientOcclusion(view);
        }
        int resolutionIndex = g_ssaoResolution < 0.75f ? 0 : 1;
        char const* const resolutionItems[] = { "Half", "Full" };
        if (ImGui::Combo("SSAO resolution", &resolutionIndex, resolutionItems, 2)) {
            g_ssaoResolution = resolutionIndex == 0 ? 0.5f : 1.0f;
            applyScreenSpaceAmbientOcclusion(view);
        }
        ImGui::TextDisabled("Half is the mobile default; Full is for static desktop comparison.");
        if (ImGui::Checkbox("SSAO bent normals", &g_ssaoBentNormals)) {
            applyScreenSpaceAmbientOcclusion(view);
        }
        if (ImGui::Checkbox("SSCT contact shadows", &g_ssct)) {
            g_ssao = g_ssao || g_ssct;
            applyScreenSpaceAmbientOcclusion(view);
        }
        if (g_ssct) {
            float intensity = g_ssctIntensity;
            if (ImGui::SliderFloat("SSCT intensity", &intensity, 0.0f, 2.0f, "%.2f")) {
                g_ssctIntensity = intensity;
                applyScreenSpaceAmbientOcclusion(view);
            }
            float const maxDistance = std::max(0.01f, 0.75f * std::max(g_sceneDiagonal, 0.02f));
            float distance = g_ssctShadowDistance;
            if (ImGui::SliderFloat("SSCT shadow distance", &distance, 0.0f, maxDistance, "%.3f")) {
                g_ssctShadowDistance = distance;
                applyScreenSpaceAmbientOcclusion(view);
            }
            ImGui::TextDisabled("0 = auto (25%% of the bounds diagonal).");
        }
        ImGui::TextUnformatted("Screen-space AO darkens indirect light only. Enable Environment "
                               "IBL or lower Sun intensity to see it. It complements baked AO: "
                               "it follows the current cut instead of the source surface.");
    }
    if (g_material != nullptr && g_material->hasParameter("compensationStrength")) {
        bool compensate = g_shadeCompensate;
        if (ImGui::Checkbox("Shading compensation (AO + detail)  [C]", &compensate)) {
            setLodCompensationEnabled(engine, compensate);
        }
        ImGui::SameLine();
        ImGui::TextDisabled("%s", g_shadeCompensate ? "on" : "off");
    }
    bool smoothShading = g_shadeCreaseDegrees > 0.0f;
    if (ImGui::Checkbox("Smooth seam normals", &smoothShading)) {
        g_shadeCreaseDegrees =
                smoothShading ? (g_shadeCreaseDegrees > 0.0f ? g_shadeCreaseDegrees : 10.0f) : 0.0f;
        if (smoothShading) {
            g_shadeAuto = true;
        }
        applyLodShadingNormals();
        uploadLodVertexData(engine);
        rebuildGeometry = true;
    }
    if (g_shadeCreaseDegrees > 0.0f) {
        float crease = g_shadeCreaseDegrees;
        ImGui::SliderFloat("Normal crease", &crease, 2.0f, 45.0f, "%.0f deg");
        g_shadeCreaseDegrees = crease;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyLodShadingNormals();
            uploadLodVertexData(engine);
            rebuildGeometry = true;
        }
        if (ImGui::Checkbox("Auto strength (screen error)", &g_shadeAuto)) {
            applyLodShadingNormals();
            uploadLodVertexData(engine);
            rebuildGeometry = true;
        }
        if (g_shadeAuto) {
            ImGui::Text("Compensation: %.2f (worst error %.2f px; capped at 0.50)",
                    effectiveShadeStrength(), g_lodMaxScreenError);
        } else {
            float strength = g_shadeStrength;
            ImGui::SliderFloat("Shading strength", &strength, 0.0f, 1.0f, "%.2f");
            g_shadeStrength = strength;
            if (ImGui::IsItemDeactivatedAfterEdit()) {
                applyLodShadingNormals();
                uploadLodVertexData(engine);
                rebuildGeometry = true;
            }
            if (ImGui::Button("Use measured optimum (0.50)")) {
                g_shadeStrength = 0.50f;
                applyLodShadingNormals();
                uploadLodVertexData(engine);
                rebuildGeometry = true;
            }
        }
        ImGui::TextUnformatted("Shading only: duplicate-position normals within this angle "
                               "are averaged. Auto fades in below 1 px and never exceeds 0.50, "
                               "because stronger repair flattens real normal variation.");
    }
    if (ImGui::Button("Use measured preset for this cut")) {
        applyMeasuredShadingPreset(engine, view);
        rebuildGeometry = true;
    }
    ImGui::SameLine();
    ImGui::TextDisabled("<45%%: 4x MSAA + seam normals; 45%%+: AO");
    bool autoPreset = g_autoShadingPreset;
    if (ImGui::Checkbox("Auto apply measured preset", &autoPreset)) {
        g_autoShadingPreset = autoPreset;
        if (g_autoShadingPreset) {
            applyMeasuredShadingPreset(engine, view);
            rebuildGeometry = true;
        }
    }
    ImGui::TextDisabled("Re-applies the measured ladder after every cut change; manual sliders "
                        "remain available as overrides.");
    if (g_shadeCompensate && g_material != nullptr && g_material->hasParameter("normal")) {
        bool const combined = g_material->hasParameter("roughnessBoost");
        float& targetStrength = combined ? g_compensateNormalStrength : g_normalStrength;
        float strength = targetStrength;
        ImGui::SliderFloat("Normal detail", &strength, 0.0f, 2.0f, "%.2f");
        targetStrength = strength;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            if (combined && strength > 0.0f) {
                applyLodCompensationMaps(engine);
            }
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
    }
    if (g_shadeCompensate && g_material != nullptr && g_material->hasParameter("roughnessBoost")) {
        float boost = g_roughnessBoost;
        ImGui::SliderFloat("Roughness from lost normals", &boost, 0.0f, 0.5f, "%.3f");
        g_roughnessBoost = boost;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        ImGui::TextDisabled("Uses the baked lost-normal angle in detail-normal.png alpha; "
                            "texels without lost detail keep the authored roughness.");
    }
    if (g_material != nullptr && g_material->hasParameter("compensationStrength")) {
        ImGui::Separator();
        ImGui::Text("LOD shading compensation: %s", g_shadeCompensate ? "on" : "off");
        ImGui::BeginDisabled(!g_shadeCompensate);
        float amount = g_compensationStrength;
        if (ImGui::SliderFloat("Compensation amount", &amount, 0.0f, 1.0f, "%.2f")) {
            g_compensationStrength = amount;
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        if (ImGui::Checkbox("Error-driven per cluster", &g_shadeErrorDriven)) {
            updateLodCompensationWeights();
            uploadLodVertexData(engine);
            rebuildGeometry = true;
        }
        ImGui::TextDisabled("Fade compensation out below 0.25 px and ramp to full at 1 px. "
                            "Near, fine clusters stay crisp; coarse clusters get the AO/detail.");
        if (ImGui::Button("Rebake maps for this cut") && g_shadeCompensate) {
            applyLodCompensationMaps(engine);
        }
        if (ImGui::Button("Use measured AO preset (45%+)")) {
            // This is the only compensation term with a repeatable positive result on the
            // 45-55% cuts. Keep the surface-detail terms neutral so a preset cannot silently
            // reintroduce the measured normal-map and roughness regressions.
            g_compensationStrength = 1.0f;
            g_aoStrength = 0.5f;
            g_compensateNormalStrength = 0.0f;
            g_roughnessBoost = 0.0f;
            g_pomStrength = 0.0f;
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        ImGui::EndDisabled();
        double const selectedRatio =
                g_lodBaseTriangles > 0
                        ? 100.0 * double(g_lodSelectedTriangles) / double(g_lodBaseTriangles)
                        : 0.0;
        if (selectedRatio < 45.0) {
            ImGui::TextUnformatted("Measured warning: at this extreme savings AO can paint "
                                   "blocky dark patches and detail normals regress. Prefer "
                                   "4x MSAA + seam normals 10deg/auto; enable AO on the 45%+ "
                                   "tiers or under full IBL.");
        }
        ImGui::TextUnformatted("Shading can restore cavities and micro-normal response. It cannot "
                               "restore silhouettes, thin geometry or displaced surfaces.");
    }
    if (g_material != nullptr && g_material->hasParameter("pomScale")) {
        float strength = g_pomStrength;
        ImGui::SliderFloat("Parallax strength", &strength, 0.0f, 2.0f, "%.2f");
        g_pomStrength = strength;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        int layers = g_pomLayers;
        ImGui::SliderInt("Parallax layers", &layers, 1, 32);
        g_pomLayers = layers;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        float scale = g_pomScale;
        ImGui::SliderFloat("Parallax scale", &scale, 0.0f, 0.20f, "%.4f");
        g_pomScale = scale;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            g_pomScaleAuto = false;
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        ImGui::TextUnformatted("Shading only: source displacement baked into the LOD UV "
                               "atlas and re-sampled with iterative parallax. It can recover "
                               "interior depth and self-occlusion, but not silhouette coverage.");
    }
    bool const hasVertexAo = g_material != nullptr && g_material->hasParameter("aoStrength") &&
                             !g_material->hasParameter("aoMap");
    if (hasVertexAo) {
        if (g_lodAo.empty()) {
            ImGui::TextUnformatted("Baked AO material is active, but no bake has run. Start "
                                   "with --bake-ao to sample the source mesh.");
        } else {
            float strength = g_aoStrength;
            ImGui::SliderFloat("Baked AO", &strength, 0.0f, 1.0f, "%.2f");
            g_aoStrength = strength;
            if (ImGui::IsItemDeactivatedAfterEdit()) {
                applyShadingParameters(g_materialInstance);
                for (MaterialInstance* instance: g_lodMaterialInstances) {
                    applyShadingParameters(instance);
                }
            }
            if (!g_lodBentNormals.empty() && g_material->hasParameter("bentNormalStrength")) {
                float bentStrength = g_bentNormalStrength;
                ImGui::SliderFloat("Bent normal", &bentStrength, 0.0f, 1.0f, "%.2f");
                g_bentNormalStrength = bentStrength;
                if (ImGui::IsItemDeactivatedAfterEdit()) {
                    applyShadingParameters(g_materialInstance);
                    for (MaterialInstance* instance: g_lodMaterialInstances) {
                        applyShadingParameters(instance);
                    }
                }
                ImGui::TextUnformatted("Directional visibility from the same source-mesh rays "
                                       "as AO. It needs IBL/SSAO to change the image; 0 is "
                                       "scalar-AO-only behaviour.");
            }
            ImGui::TextUnformatted("Shading only: source-mesh visibility baked onto LOD "
                                   "vertices. It restores contact darkening in cavities, but "
                                   "cannot recover silhouettes, thin features or displacement.");
        }
    }
    if (g_material != nullptr && g_material->hasParameter("aoMap")) {
        float strength = g_aoStrength;
        ImGui::SliderFloat("Baked AO map", &strength, 0.0f, 1.0f, "%.2f");
        g_aoStrength = strength;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        ImGui::TextUnformatted("Shading only: source-mesh visibility baked into the LOD UV "
                               "atlas. It keeps cavities finer than the vertex spacing, but "
                               "cannot recover silhouettes, thin features or displacement.");
    }
    if (g_material != nullptr && g_material->hasParameter("cavityStrength")) {
        float cavity = g_cavityStrength;
        ImGui::SliderFloat("Cavity shading", &cavity, 0.0f, 2.0f, "%.2f");
        g_cavityStrength = cavity;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        ImGui::TextUnformatted("Shading only: screen-space mean curvature darkens concave "
                               "regions. It adds the micro-shadowing a coarse mesh cannot "
                               "represent; it cannot recover silhouette coverage.");
    }
    if (ImGui::SliderFloat("Roughness", &g_roughness, 0.0f, 1.0f, "%.2f")) {
        applyShadingParameters(g_materialInstance);
        for (MaterialInstance* instance: g_lodMaterialInstances) {
            applyShadingParameters(instance);
        }
    }
    bool ibl = g_ibl;
    if (ImGui::Checkbox("Environment IBL (bent normals)", &ibl)) {
        g_ibl = ibl;
        if (g_ibl) {
            createEnvironmentIbl(engine, g_scene);
        } else if (g_indirectLight != nullptr) {
            if (g_scene != nullptr) {
                g_scene->setIndirectLight(nullptr);
            }
            engine->destroy(g_indirectLight);
            g_indirectLight = nullptr;
        }
    }
    ImGui::TextUnformatted("Bent normals and baked AO need indirect light to affect the image; "
                           "direct sunlight alone does not consume them.");
    if (g_indirectLight != nullptr) {
        float intensity = g_iblIntensity;
        if (ImGui::SliderFloat("IBL intensity", &intensity, 0.0f, 100000.0f, "%.0f")) {
            g_iblIntensity = intensity;
            g_indirectLight->setIntensity(intensity);
        }
    }
    float sunIntensity = g_sunIntensity;
    if (ImGui::SliderFloat("Sun intensity", &sunIntensity, 0.0f, 200000.0f, "%.0f")) {
        g_sunIntensity = sunIntensity;
        if (g_lightEntity) {
            LightManager& lightManager = engine->getLightManager();
            lightManager.setIntensity(lightManager.getInstance(g_lightEntity), sunIntensity);
        }
    }
    if (ImGui::Checkbox("Ignore tier ceiling", &g_ignoreQualityCeiling)) {
        selectionChanged = true;
        rebuildGeometry = true;
    }
    if (selectionChanged) {
        updateLodSelection(engine);
        bool presetApplied = false;
        if (g_autoShadingPreset && rebuildGeometry) {
            applyMeasuredShadingPreset(engine, view);
            presetApplied = true;
        }
        if (!presetApplied && rebuildGeometry && g_shadeAuto && g_shadeCreaseDegrees > 0.0f) {
            applyLodShadingNormals();
        }
        if (!presetApplied && rebuildGeometry &&
                (g_shadeErrorDriven || (g_shadeAuto && g_shadeCreaseDegrees > 0.0f))) {
            uploadLodVertexData(engine);
        }
        if (!presetApplied && rebuildGeometry && g_shadeCompensate) {
            applyLodCompensationMaps(engine);
        }
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
    ImGui::Text("vertices: %u source + %zu generated (global)", g_lodGraph.sourceVertexCount(),
            g_lodGraph.generatedVertices.size());
    ImGui::Text("cut needs: %u vertices (%u generated)", g_lodCutVertexCount,
            g_lodCutGeneratedVertices);
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
    createEnvironmentIbl(engine, scene);
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

    // The plain rendering path never builds a DAG, so there is no separate source mesh to bake
    // from. Bake the loaded asset itself; that is still the correct source-level AO for the
    // common "render this mesh with baked AO" use case. The DAG path below keeps the true
    // high-poly source and a runtime cut.
    if (g_bakeAoMapSize > 0 || !g_aoMapPath.empty()) {
        mm::Mesh aoSource;
        mm::Mesh const* source = nullptr;
        if (g_bakeAoMapSize > 0 && !g_config.positionalArgs.empty() &&
                loadLodMesh(g_config.positionalArgs.front().c_str_safe(), &aoSource)) {
            source = &aoSource;
        }
        ensureAoMapTexture(engine, source);
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

    if (!g_meshSet->getRenderables().empty()) {
        float3 lo{ std::numeric_limits<float>::max() };
        float3 hi{ std::numeric_limits<float>::lowest() };
        for (auto renderable: g_meshSet->getRenderables()) {
            auto instance = rcm.getInstance(renderable);
            if (!instance) {
                continue;
            }
            Box const& box = rcm.getAxisAlignedBoundingBox(instance);
            lo = min(lo, box.center - box.halfExtent);
            hi = max(hi, box.center + box.halfExtent);
        }
        if (hi.x >= lo.x) {
            g_sceneDiagonal = length(hi - lo);
            if (g_curvatureScaleAuto) {
                g_curvatureScale = std::max(0.5f * length(hi - lo), 1e-3f);
            }
        }
    }
    // The material instance was created before the mesh bounds were known; update the
    // curvature scale now that it has been derived from the asset.
    if (g_materialInstance != nullptr) {
        applyShadingParameters(g_materialInstance);
    }

    g_lightEntity = utils::EntityManager::get().create();
    LightManager::Builder(LightManager::Type::SUN)
            .color(Color::toLinear<ACCURATE>(sRGBColor{ 0.98f, 0.92f, 0.89f }))
            .intensity(g_sunIntensity)
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

    // The camera path is now final (auto-framing has run), so this list matches every capture.
    writeCameraList(int(vp.width), int(vp.height));

    view->setCamera(g_camera);
    view->setPostProcessingEnabled(false);
    applyScreenSpaceAmbientOcclusion(view);
}

void cleanup(Engine* engine, View*, Scene* scene) {
    if (engine != nullptr) {
        g_gpuCutSelector.destroy(*engine);
    }
    g_gpuCutActive = false;
    if (engine != nullptr && g_meshSet != nullptr) {
        for (auto renderable: g_meshSet->getRenderables()) {
            if (engine->getRenderableManager().getInstance(renderable)) {
                engine->destroy(renderable);
            }
        }
    }
    destroyLodRenderable(engine);
    destroyShadowProxy(engine);

    if (engine != nullptr) {
        if (g_lodIndexBuffer != nullptr) {
            engine->destroy(g_lodIndexBuffer);
            g_lodIndexBuffer = nullptr;
        }
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
        if (g_indirectLight != nullptr) {
            if (scene != nullptr) {
                scene->setIndirectLight(nullptr);
            }
            engine->destroy(g_indirectLight);
            g_indirectLight = nullptr;
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
        if (g_detailNormalTexture != nullptr) {
            engine->destroy(g_detailNormalTexture);
            g_detailNormalTexture = nullptr;
        }
        if (g_detailHeightTexture != nullptr) {
            engine->destroy(g_detailHeightTexture);
            g_detailHeightTexture = nullptr;
        }
        if (g_aoMapTexture != nullptr) {
            engine->destroy(g_aoMapTexture);
            g_aoMapTexture = nullptr;
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
    g_lodGpuBuffer = {};
    g_lodNodeFirstIndex.clear();
    g_lodNodeIndexCount.clear();
    g_lodPrimitiveCapacity = 0;
    g_scene = nullptr;
}

void preRender(Engine* engine, View* view, Scene*, Renderer* renderer) {
    // Without an IBL the swap chain has to be cleared explicitly, and the exposure has to be
    // pinned: both are what turns a lit scene into pixels, and both have to be identical across
    // runs for two screenshots to be comparable.
    renderer->setClearOptions({ .clearColor = { 0.0f, 0.0f, 0.0f, 1.0f }, .clear = true });
    bool const reposition = g_repositionCamera;
    if (g_camera != nullptr) {
        g_camera->setExposure(16.0f, 1.0f / 125.0f, 100.0f); // f/16, 1/125s, ISO 100
        if (reposition) {
            // The flag rather than a frame counter: the capture callback runs on the backend
            // thread and can land after this callback has already run for the frame, so a
            // counter reset would be incremented past zero before it was ever observed.
            g_camera->lookAt(eyeForView(g_currentView), targetForView(g_currentView),
                    { 0.0f, 1.0f, 0.0f });
            g_repositionCamera = false;
        }
    }
    if (!g_distanceLod || g_lodGraph.nodes.empty() || !view->hasCamera()) {
        return;
    }
    Viewport const& viewport = view->getViewport();
    if (viewport.width == 0 || viewport.height == 0) {
        return;
    }
    Camera& camera = view->getCamera();
    bool const viewportChanged = viewport.width != g_lodCamera.screenWidth ||
            viewport.height != g_lodCamera.screenHeight;
    if (&camera == g_camera && viewportChanged) {
        camera.setProjection(camera.getFieldOfViewInDegrees(Camera::Fov::VERTICAL),
                double(viewport.width) / viewport.height, camera.getNear(), camera.getCullingFar());
    }
    mm::ViewCamera const current = readLodCamera(camera, viewport);
    bool const cameraChanged = current.eye != g_lodCamera.eye ||
            current.target != g_lodCamera.target || current.up != g_lodCamera.up ||
            current.fovY != g_lodCamera.fovY || current.near != g_lodCamera.near ||
            current.far != g_lodCamera.far || viewportChanged;
    auto const start = std::chrono::steady_clock::now();
    bool cutChanged = false;
    if (cameraChanged) {
        g_lodCamera = current;
        cutChanged = updateLodSelection(engine, true);
        if (g_shadeErrorDriven && !g_showOriginal) {
            uploadLodVertexData(engine);
        }
        if (!g_showOriginal && (cutChanged || (g_shadeErrorDriven && g_compactVertices))) {
            rebuildLodGeometry(engine);
        }
    }
    if (g_dag && (reposition || cameraChanged)) {
        double const updateMs = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - start).count();
        std::printf("dag: cameraCut view=%d changed=%d nodes=%zu culledTriangles=%llu "
                    "drawnTriangles=%llu selectionMs=%.3f updateMs=%.3f\n",
                g_currentView, cutChanged, g_lodSelection.nodes.size(),
                (unsigned long long) g_lodSelection.culledTriangles,
                (unsigned long long) g_lodDrawnTriangles,
                cameraChanged ? g_lodSelectionMs : 0.0, updateMs);
    }
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
                g_lastFrameTime = {};
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
    auto const now = std::chrono::steady_clock::now();
    if (g_lastFrameTime != std::chrono::steady_clock::time_point{}) {
        double const frameMs =
                std::chrono::duration<double, std::milli>(now - g_lastFrameTime).count();
        if (!g_ui && g_viewFrame > g_warmup) {
            g_cpuFrameMs.push_back(frameMs);
        }
    }
    g_lastFrameTime = now;

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
        samples::Parameter::makeString("detail-normal", '\0',
                "Detail normal map baked with mmgeo --bake-normal", ""),
        samples::Parameter::makeFloat("normal-strength", '\0',
                "Strength of the baked LOD normal detail; 0 keeps the LOD normals", 1.0f),
        samples::Parameter::makeString("detail-height", '\0',
                "Height map baked with mmgeo --bake-height", ""),
        samples::Parameter::makeFloat("parallax-scale", '\0',
                "UV-space parallax scale; negative reads the mmgeo sidecar", -1.0f),
        samples::Parameter::makeInt("parallax-layers", '\0', "Parallax fixed-point iterations", 8,
                1, 32),
        samples::Parameter::makeFloat("parallax-strength", '\0',
                "Scales the baked displacement; negative auto-enables it only with --detail-height",
                -1.0f),
        samples::Parameter::makeBool("bake-ao", '\0',
                "Bake source-mesh ambient occlusion onto the LOD vertices", false),
        samples::Parameter::makeInt("ao-map-size", '\0',
                "Bake source AO into an NxN UV map; 0 disables it", 0, 0, 4096),
        samples::Parameter::makeString("ao-map", '\0',
                "Prebaked AO map (PNG) sampled in the LOD UV atlas", ""),
        samples::Parameter::makeInt("ao-samples", '\0',
                "Hemisphere rays per vertex or texel for --bake-ao/--ao-map-size", 32, 1, 256),
        samples::Parameter::makeFloat("ao-radius", '\0',
                "AO ray length in world units; 0 derives it from the mesh bounds", 0.0f),
        samples::Parameter::makeFloat("ao-strength", '\0',
                "Strength of the baked AO compensation, in [0,1]", 0.5f),
        samples::Parameter::makeFloat("bent-normal-strength", '\0',
                "Strength of the baked directional visibility; 0 keeps scalar AO only", 0.0f),
        samples::Parameter::makeBool("ibl", '\0',
                "Add a procedural SH environment so bent normals and AO are visible", false),
        samples::Parameter::makeFloat("ibl-intensity", '\0',
                "Scale of the procedural environment when --ibl is set", 30000.0f),
        samples::Parameter::makeFloat("sun-intensity", '\0',
                "Direct sunlight intensity; 0 leaves only indirect light", 110000.0f),
        samples::Parameter::makeFloat("roughness", '\0',
                "Material roughness override used for shading comparisons", 0.5f),
        samples::Parameter::makeBool("shade-compensate", '\0',
                "Use the combined high-poly AO + detail-normal LOD material", false),
        samples::Parameter::makeBool("shade-error-driven", '\0',
                "Weight AO/detail compensation per cluster by its screen-space error", false),
        samples::Parameter::makeInt("compensate-size", '\0',
                "Square size of the runtime compensation maps", 256, 64, 2048),
        samples::Parameter::makeFloat("compensation-strength", '\0',
                "Global blend of the AO/detail compensation terms, in [0,1]", 1.0f),
        samples::Parameter::makeFloat("compensate-normal", '\0',
                "Detail-normal strength of the combined material; negative auto-selects", -1.0f),
        samples::Parameter::makeFloat("roughness-boost", '\0',
                "Roughness added to compensate for lost normal variance, in [0,0.5]", 0.0f),
        samples::Parameter::makeFloat("shade-cavity", '\0',
                "Screen-space curvature cavity strength; 0 disables it", 0.0f),
        samples::Parameter::makeFloat("curvature-scale", '\0',
                "World-space scale for the cavity curvature; negative derives it from the mesh",
                -1.0f),
        samples::Parameter::makeFloat("shade-crease", '\0',
                "Weld duplicate-position shading normals below this angle; 0 disables it", 0.0f),
        samples::Parameter::makeFloat("shade-strength", '\0',
                "Blend toward the repaired seam normals, in [0,1]", 0.5f),
        samples::Parameter::makeBool("shade-auto", '\0',
                "Derive the seam-normal strength from the cut screen error", false),
        samples::Parameter::makeBool("auto-shading-preset", '\0',
                "Apply the measured MSAA/AO/seam-normal ladder whenever the cut changes", false),
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
        samples::Parameter::makeBool("shadow-proxy", '\0',
                "Let the source mesh cast shadows while the LOD renders (implies --dag)", false),
        samples::Parameter::makeFloat("shadow-proxy-ratio", '\0',
                "Triangle ratio of the shadow proxy cut; 1 keeps the exact source mesh", 1.0f, 0.1f,
                1.0f),
        samples::Parameter::makeFloat("shadow-proxy-bias", '\0',
                "Constant shadow bias in world units while the proxy is active", 0.010f, 0.0f,
                0.25f),
        samples::Parameter::makeFloat("shadow-proxy-normal-bias", '\0',
                "Normal shadow bias while the proxy is active", 3.0f, 0.0f, 8.0f),
        samples::Parameter::makeFloat("pan", 'P',
                "Total degrees of camera pan across the sequence; 0 keeps the camera still", 0.0f),
        samples::Parameter::makeFloat("translate", '\0',
                "Total lateral camera translation across the sequence, in world units; 0 keeps "
                "the eye fixed", 0.0f),
        samples::Parameter::makeInt("jitter", 'J',
                "Sub pixel frames per view; >1 renders each view that many times", 1, 1),
        samples::Parameter::makeInt("frames", '\0',
                "Temporal frames per view without sub pixel jitter; 0 keeps --jitter", 0, 0),
        samples::Parameter::makeString("camera-out", '\0',
                "Write the exact per-capture camera list for tools/mmdepth and mmtemporal", ""),
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
        samples::Parameter::makeBool("gpu-cut", '\0',
                "Run distance-aware DAG selection through the Filament backend compute queue",
                false),
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
        samples::Parameter::makeBool("no-merge-draws", '\0',
                "Draw every selected DAG node separately to compare draw-call cost", false),
        samples::Parameter::makeBool("compact-cut-indices", '\0',
                "Upload the current cut's indices once so each material is a single draw", false),
        samples::Parameter::makeBool("compact-vertices", '\0',
                "Upload only the generated vertices the current cut uses", false),
        samples::Parameter::makeInt("msaa", '\0',
                "MSAA sample count for edge A/B (0 disables, 4 is typical)", 0, 0, 8, 1),
        samples::Parameter::makeBool("taa", '\0',
                "Enable Filament temporal anti-aliasing (implies post-processing)", false),
        samples::Parameter::makeBool("ssao", '\0',
                "Enable GTAO screen-space ambient occlusion on the current cut", false),
        samples::Parameter::makeFloat("ssao-radius", '\0',
                "GTAO world-space radius; 0 derives it from the mesh bounds", 0.0f),
        samples::Parameter::makeFloat("ssao-intensity", '\0', "GTAO darkening strength", 1.0f),
        samples::Parameter::makeFloat("ssao-power", '\0', "GTAO contrast exponent", 1.0f),
        samples::Parameter::makeBool("ssao-bent-normals", '\0',
                "Also compute screen-space bent normals for specular AO", false),
        samples::Parameter::makeInt("ssao-quality", '\0',
                "GTAO quality: 0 low, 1 medium, 2 high, 3 ultra", 2, 0, 3),
        samples::Parameter::makeFloat("ssao-resolution", '\0', "GTAO buffer scale: 0.5 or 1.0",
                1.0f, 0.5f, 1.0f),
        samples::Parameter::makeBool("ssct", '\0',
                "Add SSCT directional contact shadows to the GTAO pass (implies --ssao)", false),
        samples::Parameter::makeFloat("ssct-intensity", '\0',
                "Strength of the screen-space contact shadows", 0.8f),
        samples::Parameter::makeFloat("ssct-shadow-distance", '\0',
                "World-space cone-trace length; 0 derives it from the mesh bounds", 0.0f),
        samples::Parameter::makeFloat("ssct-contact-distance-max", '\0',
                "Maximum world-space contact distance; 0 derives it from the mesh bounds", 0.0f),
        samples::Parameter::makeFloat("ssct-cone-angle", '\0', "Full cone angle in radians", 1.0f,
                0.0f, 1.5707964f),
        samples::Parameter::makeBool("corner-seam", '\0',
                "Generate attribute vertices so UV/normal seams can keep reducing", true),
        samples::Parameter::makeBool("corner-split-uv", '\0',
                "Keep divergent per-chart UVs in separate generated vertices (A/B only; "
                "0 averages them)",
                true),
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
    g_detailNormalPath = config.getString("detail-normal").c_str_safe();
    g_normalStrength = config.getFloat("normal-strength");
    g_detailHeightPath = config.getString("detail-height").c_str_safe();
    float const requestedParallaxScale = config.getFloat("parallax-scale", -1.0f);
    g_pomScaleAuto = requestedParallaxScale < 0.0f;
    g_pomScale = g_pomScaleAuto ? 0.02f : requestedParallaxScale;
    // Parallax needs a height map. Keep the loop disabled for assets that only use the AO and
    // normal compensation channels; an explicit --parallax-strength still enables it for tests.
    float const requestedParallaxStrength = config.getFloat("parallax-strength", -1.0f);
    g_pomStrength = requestedParallaxStrength >= 0.0f
                            ? std::clamp(requestedParallaxStrength, 0.0f, 2.0f)
                            : (g_detailHeightPath.empty() ? 0.0f : 1.0f);
    g_pomLayers = std::clamp(config.getInt("parallax-layers", 8), 1, 32);
    g_bakeAo = config.getBool("bake-ao");
    g_bakeAoMapSize = uint32_t(std::clamp(config.getInt("ao-map-size", 0), 0, 4096));
    g_aoMapPath = config.getString("ao-map").c_str_safe();
    g_aoSamples = uint32_t(std::clamp(config.getInt("ao-samples", 32), 1, 256));
    g_aoRadius = std::max(0.0f, config.getFloat("ao-radius"));
    g_aoStrength = std::clamp(config.getFloat("ao-strength", 0.5f), 0.0f, 1.0f);
    g_bentNormalStrength = std::clamp(config.getFloat("bent-normal-strength", 0.0f), 0.0f, 1.0f);
    g_ibl = config.getBool("ibl");
    g_iblIntensity = std::max(0.0f, config.getFloat("ibl-intensity", 30000.0f));
    g_sunIntensity = std::max(0.0f, config.getFloat("sun-intensity", 110000.0f));
    g_roughness = config.getFloat("roughness");
    g_shadeCompensate = config.getBool("shade-compensate");
    g_shadeErrorDriven = config.getBool("shade-error-driven");
    g_compensateSize = uint32_t(std::clamp(config.getInt("compensate-size", 256), 64, 2048));
    g_compensationStrength = std::clamp(config.getFloat("compensation-strength", 1.0f), 0.0f, 1.0f);
    float const requestedCompensateNormal = config.getFloat("compensate-normal", -1.0f);
    g_compensateNormalStrength = requestedCompensateNormal >= 0.0f
                                         ? std::clamp(requestedCompensateNormal, 0.0f, 2.0f)
                                         : (g_detailNormalPath.empty() ? 0.0f : 1.0f);
    g_roughnessBoost = std::clamp(config.getFloat("roughness-boost", 0.0f), 0.0f, 0.5f);
    if (g_shadeCompensate && g_bakeAoMapSize == 0 && g_aoMapPath.empty()) {
        // The combined material needs an AO map; bake one at the same resolution unless the
        // caller supplied an explicit map or requested a different size.
        g_bakeAoMapSize = g_compensateSize;
        g_compensateBakeSizeAuto = true;
    }
    g_cavityStrength = std::clamp(config.getFloat("shade-cavity"), 0.0f, 4.0f);
    float const requestedCurvatureScale = config.getFloat("curvature-scale", -1.0f);
    g_curvatureScaleAuto = requestedCurvatureScale < 0.0f;
    g_curvatureScale = g_curvatureScaleAuto ? 1.0f : requestedCurvatureScale;
    g_shadeCreaseDegrees = std::clamp(config.getFloat("shade-crease"), 0.0f, 45.0f);
    g_shadeStrength = std::clamp(config.getFloat("shade-strength"), 0.0f, 1.0f);
    g_shadeAuto = config.getBool("shade-auto");
    g_autoShadingPreset = config.getBool("auto-shading-preset");
    g_ui = config.getBool("ui");
    g_dag = config.getBool("dag");
    g_showOriginal = config.getBool("original");
    g_showMaterialColors = config.getBool("show-materials");
    g_autoFrame = config.getBool("auto-frame");
    g_ignoreQualityCeiling = config.getBool("ignore-ceiling");
    g_mergeDraws = !config.getBool("no-merge-draws");
    g_compactCutIndices = config.getBool("compact-cut-indices");
    g_compactVertices = config.getBool("compact-vertices");
    g_msaaSamples = std::max(0, config.getInt("msaa", 0));
    g_taa = config.getBool("taa");
    g_ssao = config.getBool("ssao");
    g_ssaoRadius = std::max(0.0f, config.getFloat("ssao-radius", 0.0f));
    g_ssaoIntensity = std::max(0.0f, config.getFloat("ssao-intensity", 1.0f));
    g_ssaoPower = std::max(0.1f, config.getFloat("ssao-power", 1.0f));
    g_ssaoBentNormals = config.getBool("ssao-bent-normals");
    g_ssaoQuality = std::clamp(config.getInt("ssao-quality", 2), 0, 3);
    g_ssaoResolution = config.getFloat("ssao-resolution", 1.0f) < 0.75f ? 0.5f : 1.0f;
    g_ssct = config.getBool("ssct");
    g_ssao = g_ssao || g_ssct;
    g_ssctIntensity = std::max(0.0f, config.getFloat("ssct-intensity", 0.8f));
    g_ssctShadowDistance = std::max(0.0f, config.getFloat("ssct-shadow-distance", 0.0f));
    g_ssctContactDistanceMax = std::max(0.0f, config.getFloat("ssct-contact-distance-max", 0.0f));
    g_ssctConeAngleRad = std::clamp(config.getFloat("ssct-cone-angle", 1.0f), 0.0f, 1.5707964f);
    g_cornerSimplify = config.getBool("corner-seam");
    g_cornerSplitUv = config.getBool("corner-split-uv");

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
    g_gpuCut = config.getBool("gpu-cut");
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
    g_shadowProxy = config.getBool("shadow-proxy");
    g_shadowProxyRatio = std::clamp(config.getFloat("shadow-proxy-ratio", 1.0f), 0.1f, 1.0f);
    g_shadowProxyConstantBias =
            std::clamp(config.getFloat("shadow-proxy-bias", 0.010f), 0.0f, 0.25f);
    g_shadowProxyNormalBias =
            std::clamp(config.getFloat("shadow-proxy-normal-bias", 3.0f), 0.0f, 8.0f);
    if (g_shadowProxy) {
        // The proxy needs the DAG path to have a source mesh and a separate visible cut.
        g_dag = true;
        if (!g_shadows) {
            std::cerr << "--shadow-proxy has no effect when shadows are disabled." << std::endl;
            g_shadowProxy = false;
        }
    }
    g_captureFrame = config.getInt("capture-frame", -1);
    g_jitter = std::max(1, config.getInt("jitter", 1));
    int const requestedFrames = config.getInt("frames", 0);
    g_subFrames = std::max({ g_jitter, requestedFrames });
    g_panDegrees = config.getFloat("pan", 0.0f);
    g_translateUnits = config.getFloat("translate", 0.0f);
    g_cameraOutPath = config.getString("camera-out", "").c_str_safe();
    g_totalCaptures = g_viewCount * g_subFrames;

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
