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
 *  Deliberately draws no UI. The stock samples all render their ImGui panels, which then
 *  occupy most of the frame; comparing two such screenshots measures the overlay, not the
 *  model.
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

#include <filamentapp/AssetLoader.h>
#include <filamentapp/DesktopAssetLoader.h>
#include <filamentapp/FilamentApp2.h>
#include <filamentapp/MeshAssimp.h>

#include <filament/Camera.h>
#include <filament/Color.h>
#include <filament/Engine.h>
#include <filament/LightManager.h>
#include <filament/Material.h>
#include <filament/MaterialInstance.h>
#include <filament/RenderableManager.h>
#include <filament/Renderer.h>
#include <filament/Scene.h>
#include <filament/Skybox.h>
#include <filament/TransformManager.h>
#include <filament/View.h>
#include <filament/Viewport.h>

#include <utils/EntityManager.h>
#include <utils/Path.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>

using namespace filament;
using namespace filament::math;
using namespace image;
using namespace utils;

using filament::app::AssetLoader;
using filament::app::DisplayManager;

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

// Frame bookkeeping.
int g_frameCounter = 0;
bool g_captured = false;
std::map<uint32_t, Renderer::FrameInfo> g_frameInfo;
std::vector<double> g_gpuFrameMs;

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
    if (g_gpuFrameMs.empty()) {
        std::cout << "frame time: no samples (GPU timing unavailable)" << std::endl;
        return;
    }
    std::vector<double> sorted = g_gpuFrameMs;
    std::sort(sorted.begin(), sorted.end());

    printf("frame time over %zu measured frames:\n", g_gpuFrameMs.size());
    printf("  GPU   median %.3f ms  p99 %.3f ms  max %.3f ms\n",
            medianOf(g_gpuFrameMs), percentileOf(sorted, 0.99), sorted.back());
}

// Reads a compiled material from a file if one was given, otherwise falls back to the lit
// material baked into the sample resources so the harness has no external dependencies.
void createMaterial(Engine* engine, char const* materialPath) {
    if (materialPath == nullptr || materialPath[0] == '\0') {
        // No explicit material: keep what MeshAssimp built for the asset, which is the pairing
        // the geometry was loaded for.
        return;
    }
    {
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
            std::cerr << "Could not load material '" << materialPath << "', using the built-in one"
                      << std::endl;
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

void setup(Engine* engine, View* view, Scene* scene) {
    g_meshSet = std::make_unique<MeshAssimp>(*engine, g_assetLoader);
    createMaterial(engine, g_materialPath.c_str());

    for (auto const& fname : g_config.positionalArgs) {
        utils::Path const filename(fname.c_str_safe());
        g_meshSet->addFromFile(filename, g_meshMaterialInstances);
    }

    if (g_meshSet->getRenderables().empty()) {
        std::cerr << "No renderable geometry: the scene would be empty." << std::endl;
        return;
    }

    auto& rcm = engine->getRenderableManager();
    for (auto renderable : g_meshSet->getRenderables()) {
        auto instance = rcm.getInstance(renderable);
        if (!instance) {
            continue;
        }
        rcm.setCastShadows(instance, true);
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
            .castShadows(true)
            .build(*engine, g_lightEntity);
    scene->addEntity(g_lightEntity);

    // Own the camera instead of leaving the view on the app's manipulator. The manipulator
    // derives its projection from window events, which never arrive when rendering offscreen,
    // and the resulting view renders nothing at all.
    g_cameraEntity = utils::EntityManager::get().create();
    g_camera = engine->createCamera(g_cameraEntity);

    Viewport const& vp = view->getViewport();
    float const aspect = vp.height > 0 ? float(vp.width) / float(vp.height) : 1.0f;
    float const distance = length(g_eye - g_target);
    g_camera->setProjection(45.0, aspect, std::max(distance * 0.01, 1e-3), distance * 20.0);
    g_camera->lookAt(g_eye, g_target, { 0.0f, 1.0f, 0.0f });

    view->setCamera(g_camera);
    view->setPostProcessingEnabled(false);
}

void cleanup(Engine* engine, View*, Scene*) {
    for (auto renderable : g_meshSet->getRenderables()) {
        if (engine->getRenderableManager().getInstance(renderable)) {
            engine->destroy(renderable);
        }
    }
    for (auto const& material : g_meshMaterialInstances) {
        engine->destroy(material.second);
    }
    engine->destroy(g_skybox);
    engine->destroyCameraComponent(g_cameraEntity);
    utils::EntityManager::get().destroy(g_cameraEntity);
    engine->destroy(g_materialInstance);
    engine->destroy(g_material);
    engine->destroy(g_lightEntity);

    g_meshSet.reset();
    utils::EntityManager::get().destroy(g_lightEntity);
}

void preRender(Engine*, View* view, Scene*, Renderer* renderer) {
    // Near and far have to bracket the scene or the model gets clipped; deriving them from the
    // camera distance keeps the harness usable for assets of any scale.
    // Without an IBL the swap chain has to be cleared explicitly, and the exposure has to be
    // pinned: both are what turns a lit scene into pixels, and both have to be identical across
    // runs for two screenshots to be comparable.
    renderer->setClearOptions({ .clearColor = { 0.0f, 0.0f, 0.0f, 1.0f }, .clear = true });
    if (g_camera != nullptr) {
        g_camera->setExposure(16.0f, 1.0f / 125.0f, 100.0f);  // f/16, 1/125s, ISO 100
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

    backend::PixelBufferDescriptor buffer(pixels, vp.width * vp.height * 4,
            backend::PixelBufferDescriptor::PixelDataFormat::RGBA,
            backend::PixelBufferDescriptor::PixelDataType::UBYTE,
            [](void* buffer, size_t, void* user) {
                std::unique_ptr<CaptureState> const state(static_cast<CaptureState*>(user));
                Viewport const& v = state->view->getViewport();

                // RGBA, not RGB: the offscreen swap chain is an RGBA8 target and reading it
                // back as three channels yields an empty buffer.
                LinearImage const image(toLinearWithAlpha<uint8_t>(v.width, v.height, v.width * 4,
                        static_cast<uint8_t*>(buffer), [](uint8_t value) { return value; },
                        sRGBToLinear<float4>));

                utils::Path const out(state->path.c_str());
                std::ofstream stream(out, std::ios::binary | std::ios::trunc);
                ImageEncoder::encode(stream, ImageEncoder::Format::PNG, image, "",
                        state->path.c_str());

                std::cout << "wrote " << state->path << " (" << v.width << "x" << v.height << ")"
                          << std::endl;

                reportTiming();

                delete[] static_cast<uint8_t*>(buffer);
                if (g_filamentApp != nullptr) {
                    g_filamentApp->close();
                }
            },
            new CaptureState{ view, g_outPath });

    renderer->readPixels(uint32_t(vp.left), uint32_t(vp.bottom), vp.width, vp.height,
            std::move(buffer));
}

void collectFrameInfo(Renderer* renderer) {
    for (auto const& info : renderer->getFrameInfoHistory(renderer->getMaxFrameHistorySize())) {
        if (info.frameId != 0) {
            g_frameInfo.insert_or_assign(info.frameId, info);
        }
    }
}

void postRender(Engine*, View* view, Scene*, Renderer* renderer) {
    if (g_frameCounter >= g_warmup) {
        // The first frames after startup carry shader compilation and resource uploads, so
        // they are skipped; what is left is steady state.
        if (g_frameCounter > g_warmup) {
            collectFrameInfo(renderer);
        }
    }

    if (g_frameCounter >= g_warmup + g_measure && !g_captured) {
        g_captured = true;

        // Turn the collected history into per frame times, ignoring frames the driver did not
        // report on (INVALID/PENDING are negative).
        // Only the GPU duration is reported. The driver thread span is not meaningful here:
        // rendering to an offscreen swap chain never presents, so there is no frame pacing to
        // measure against and the begin/end timestamps are not comparable.
        for (auto const& [frameId, info] : g_frameInfo) {
            if (info.gpuFrameDuration > 0) {
                g_gpuFrameMs.push_back(double(info.gpuFrameDuration) / 1.0e6);
            }
        }

        captureScreenshot(nullptr, view, renderer);
    }

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

    auto filamentApp = samples::getBuilder(config, dm, loader)
                               .setup(setup)
                               .cleanup(cleanup)
                               .preRender(preRender)
                               .postRender(postRender)
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

    auto dm = samples::getDisplayManager(config);
    auto loader = samples::getAssetLoader(config);

    for (auto const& fname : config.positionalArgs) {
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
