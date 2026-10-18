# ManyMesh

> **面向移动端的几何复杂度压缩与神经重建协同实时渲染方案**
> Perceptual geometry compression and temporal reconstruction for real-time rendering.

像 **MegaLights 通过采样解决光源数量爆炸**一样，ManyMesh 通过**几何压缩 + 神经重建**解决
模型面数爆炸：用类似 Nanite 的自适应几何压缩减少模型处理开销，再用轻量神经网络超分
恢复因几何简化造成的视觉损失，从而使普通移动设备能够实时渲染高复杂度 3D 资产。

> 把不可承受的计算复杂度转化为可控制的近似误差，再用重建技术补偿。

- 📄 **完整方案、实验设计与里程碑路线图：[MANYMESH.md](MANYMESH.md)**
- 🧱 **渲染底座**：[Google Filament](https://github.com/google/filament) —— 本仓库为其完整源码快照
  （上游提交 `4bcb2e4e5aa2fdba45b0db73dcb92f5dbfc38752`），详见 [MANYMESH.md §9.1](MANYMESH.md#91-仓库形态)

## 当前实现状态

- **已跑通**：属性感知 QEM、UV/法线成对 seam collapse、带质量门的层次化 cluster DAG、
  CPU 运行时 cut、编辑器节省比例滑杆/质量档位、近细远粗开关、分页流式缓存、
  WinHTTP Range 下载，以及独立 Vulkan compute cut + indirect draw + visibility buffer 原型。
- **已做视觉回归**：dragon / sphere / monkey / torus / cloth / shapes 六模型同机位对比；
  monkey 50% 为 40.99 dB / 0.99349，torus 48.78% 为 40.56 dB / 0.99655，未发现新增穿孔。
- **性能**：cloth DAG（74,976 三角形）构建从 37.02s 降到 1.93s，节点与三角形输出逐位不变；
  588 节点 monkey DAG 的运行时 CPU cut 约 0.003 ms/次。
- **尚未完成**：Filament 公共 API/后端内的常驻 compute + indirect 渲染路径、Android/iOS
  平台 HTTP transport、三份以上同位置 seam 副本、跨 UV chart 的生成顶点/属性插值，以及
  移动端真机功耗与帧时验证。这里不会用放松质量门来换取更低面数。

> ⚠️ **构建前请注意**：本仓库的 Windows 构建流程与上游默认方式不同（Filament 不支持 MSYS2
> 环境），并含一处 MSVC 编译修补。请先阅读
> [MANYMESH.md §9 开发环境与构建](MANYMESH.md#9-开发环境与构建当前状态)。

---

# Filament

[![Android Build Status](https://github.com/google/filament/actions/workflows/status-android.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-android.yml)
[![iOS Build Status](https://github.com/google/filament/actions/workflows/status-ios.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-ios.yml)
[![Linux Build Status](https://github.com/google/filament/actions/workflows/status-linux.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-linux.yml)
[![macOS Build Status](https://github.com/google/filament/actions/workflows/status-macos.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-macos.yml)
[![Windows Build Status](https://github.com/google/filament/actions/workflows/status-windows.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-windows.yml)
[![Web Build Status](https://github.com/google/filament/actions/workflows/status-web.yml/badge.svg)](https://github.com/google/filament/actions/workflows/status-web.yml)

Filament is a real-time physically based rendering engine for Android, iOS, Linux, macOS, Windows,
and WASM. It is designed to be as small as possible and as efficient as possible on Android.

## Download

[Download Filament releases](https://github.com/google/filament/releases) to access stable builds.
Filament release archives contains host-side tools that are required to generate assets.

Make sure you always use tools from the same release as the runtime library. This is particularly
important for `matc` (material compiler).

If you'd rather build Filament yourself, please refer to our [build manual](/BUILDING.md).

### Android

Android projects can simply declare Filament libraries as Maven dependencies:

```gradle
repositories {
    // ...
    mavenCentral()
}

dependencies {
    implementation 'com.google.android.filament:filament-android:1.77.3'
}
```

Here are all the libraries available in the group `com.google.android.filament`:

| Artifact      | Description   |
| ------------- | ------------- |
| [![filament-android](https://img.shields.io/maven-central/v/com.google.android.filament/filament-android?label=filament-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-android)  | The Filament rendering engine itself. |
| [![filament-android-debug](https://img.shields.io/maven-central/v/com.google.android.filament/filament-android-debug?label=filament-android-debug&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-android-debug)  | Debug version of `filament-android`. |
| [![gltfio-android](https://img.shields.io/maven-central/v/com.google.android.filament/gltfio-android?label=gltfio-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/gltfio-android) | A glTF 2.0 loader for Filament, depends on `filament-android`. |
| [![filament-utils-android](https://img.shields.io/maven-central/v/com.google.android.filament/filament-utils-android?label=filament-utils-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filament-utils-android) | KTX loading, Kotlin math, and camera utilities, depends on `gltfio-android`. |
| [![filamat-android](https://img.shields.io/maven-central/v/com.google.android.filament/filamat-android?label=filamat-android&color=green)](https://mvnrepository.com/artifact/com.google.android.filament/filamat-android) | A runtime material builder/compiler. This library is large but contains a full shader compiler/validator/optimizer and supports both OpenGL and Vulkan. |

### iOS

iOS projects can use CocoaPods to install the latest release:

```shell
pod 'Filament', '~> 1.77.3'
```

## Documentation

- [Filament](https://google.github.io/filament/Filament.html), an in-depth explanation of
  real-time physically based rendering, the graphics capabilities and implementation of Filament.
  This document explains the math and reasoning behind most of our decisions. This document is a
  good introduction to PBR for graphics programmers.
- [Materials](https://google.github.io/filament/Materials.html), the full reference
  documentation for our material system. This document explains our different material models, how
  to use the material compiler `matc` and how to write custom materials.
- [Material Properties](https://google.github.io/filament/notes/material_properties.html), a reference
  sheet for the standard material model.

## Examples

![Night scene](docs/images/samples/example_bistro1.jpg)
![Night scene](docs/images/samples/example_bistro2.jpg)
![Materials](docs/images/samples/example_materials1.jpg)
![Materials](docs/images/samples/example_materials2.jpg)
![Helmet](docs/images/samples/example_helmet.jpg)
![Screen-space refraction](docs/images/samples/example_ssr.jpg)

## Features

### APIs

- Native C++ API for Android, iOS, Linux, macOS and Windows
- Java/JNI API for Android
- JavaScript API

### Backends

- OpenGL 4.1+ for Linux, macOS and Windows
- OpenGL ES 3.0+ for Android and iOS
- Metal for macOS and iOS
- Vulkan 1.0 for Android, Linux, macOS, and Windows
- WebGPU for Android, Linux, macOS, and Windows
- WebGL 2.0 for all browsers supporting it

### Rendering

- Clustered forward renderer
- Cook-Torrance microfacet specular BRDF
- Lambertian diffuse BRDF
- Custom lighting/surface shading
- HDR/linear lighting
- Metallic workflow
- Clear coat
- Anisotropic lighting
- Approximated translucent (subsurface) materials
- Cloth/fabric/sheen shading
- Normal mapping & ambient occlusion mapping
- Image-based lighting
- Physically-based camera (shutter speed, sensitivity and aperture)
- Physical light units
- Point lights, spot lights, and directional light
- Specular anti-aliasing
- Point, spot, and directional light shadows
- Cascaded shadows
- EVSM, PCSS, DPCF, or PCF shadows
- Colored penumbra
- Transparent shadows
- Contact shadows
- Screen-space ambient occlusion
- Screen-space reflections
- Screen-space refraction
- Global fog
- Dynamic resolution (with support for AMD FidelityFX FSR)

### Post processing

- HDR bloom
- Depth of field bokeh
- Multiple tone mappers: GT7, PBR Neutral, AgX, generic (customizable), ACES, filmic, etc.
- Color and tone management: luminance scaling, gamut mapping
- Color grading: exposure, night adaptation, white balance, channel mixer,
  shadows/mid-tones/highlights, ASC CDL, contrast, saturation, etc.
- TAA, FXAA, MSAA
- Screen-space lens flares

### glTF 2.0

- Encodings
  - [x] Embeded
  - [x] Binary

- Primitive Types
  - [x] Points
  - [x] Lines
  - [ ] Line Loop
  - [x] Line Strip
  - [x] Triangles
  - [x] Triangle Strip
  - [ ] Triangle Fan

- Animation
  - [x] Transform animation
  - [x] Linear interpolation
  - [x] Morph animation
    - [x] Sparse accessor
  - [x] Skin animation
  - [x] Joint animation

- Extensions
  - [x] KHR_draco_mesh_compression
  - [x] KHR_lights_punctual
  - [x] KHR_materials_clearcoat
  - [x] KHR_materials_dispersion
  - [x] KHR_materials_emissive_strength
  - [x] KHR_materials_ior
  - [x] KHR_materials_pbrSpecularGlossiness
  - [x] KHR_materials_sheen
  - [x] KHR_materials_specular
  - [x] KHR_materials_transmission
  - [x] KHR_materials_unlit
  - [x] KHR_materials_variants
  - [x] KHR_materials_volume
  - [x] KHR_mesh_quantization
  - [x] KHR_texture_basisu
  - [x] KHR_texture_transform
  - [x] EXT_meshopt_compression

## Rendering with Filament

### Native Linux, macOS and Windows

You must create an `Engine`, a `Renderer` and a `SwapChain`. The `SwapChain` is created from a
native window pointer (an `NSView` on macOS or a `HWND` on Windows for instance):

```c++
Engine* engine = Engine::create();
SwapChain* swapChain = engine->createSwapChain(nativeWindow);
Renderer* renderer = engine->createRenderer();
```

To render a frame you must then create a `View`, a `Scene` and a `Camera`:

```c++
Camera* camera = engine->createCamera(EntityManager::get().create());
View* view = engine->createView();
Scene* scene = engine->createScene();

view->setCamera(camera);
view->setScene(scene);
```

Renderables are added to the scene:

```c++
Entity renderable = EntityManager::get().create();
// build a quad
RenderableManager::Builder(1)
        .boundingBox({{ -1, -1, -1 }, { 1, 1, 1 }})
        .material(0, materialInstance)
        .geometry(0, RenderableManager::PrimitiveType::TRIANGLES, vertexBuffer, indexBuffer, 0, 6)
        .culling(false)
        .build(*engine, renderable);
scene->addEntity(renderable);
```

The material instance is obtained from a material, itself loaded from a binary blob generated
by `matc`:

```c++
Material* material = Material::Builder()
        .package((void*) BAKED_MATERIAL_PACKAGE, sizeof(BAKED_MATERIAL_PACKAGE))
        .build(*engine);
MaterialInstance* materialInstance = material->createInstance();
```

To learn more about materials and `matc`, please refer to the
[materials documentation](https://google.github.io/filament/Materials.html).

To render, simply pass the `View` to the `Renderer`:

```c++
// beginFrame() returns false if we need to skip a frame
if (renderer->beginFrame(swapChain)) {
    // for each View
    renderer->render(view);
    renderer->endFrame();
}
```

For complete examples of Linux, macOS and Windows Filament applications, look at the source files
in the `samples/` directory. These samples are all based on `libs/filamentapp/` which contains the
code that creates a native window with SDL2 and initializes the Filament engine, renderer and views.

For more information on how to prepare environment maps for image-based lighting please refer to
[BUILDING.md](/BUILDING.md#running-the-native-samples).

### Android

See `android/samples` for examples of how to use Filament on Android.

You must always first initialize Filament by calling `Filament.init()`.

Rendering with Filament on Android is similar to rendering from native code (the APIs are largely
the same across languages). You can render into a `Surface` by passing a `Surface` to the
`createSwapChain` method. This allows you to render to a `SurfaceTexture`, a `TextureView` or
a `SurfaceView`. To make things easier we provide an Android specific API called `UiHelper` in the
package `com.google.android.filament.android`. All you need to do is set a render callback on the
helper and attach your `SurfaceView` or `TextureView` to it. You are still responsible for
creating the swap chain in the `onNativeWindowChanged()` callback.

### iOS

Filament is supported on iOS 11.0 and above. See `ios/samples` for examples of using Filament on
iOS.

Filament on iOS is largely the same as native rendering with C++. A `CAEAGLLayer` or `CAMetalLayer`
is passed to the `createSwapChain` method. Filament for iOS supports both Metal (preferred) and
OpenGL ES.

## Assets

To get started you can use the textures and environment maps found respectively in
`third_party/textures` and `third_party/environments`. These assets are under CC0 license. Please
refer to their respective `URL.txt` files to know more about the original authors.

Environments must be pre-processed using
[`cmgen`](/BUILDING.md#running-the-native-samples) or
using the `libiblprefilter` library.

## How to make contributions

Please read and follow the steps in [CONTRIBUTING.md](/CONTRIBUTING.md). Make sure you are
familiar with the [code style](/CODE_STYLE.md). For reporting vulnerabilities, please consult
our [Security Policy](/SECURITY.md).

## Directory structure

This repository not only contains the core Filament engine, but also its supporting libraries
and tools.

- `android`:                  Android libraries and projects
  - `filamat-android`:        Filament material generation library (AAR) for Android
  - `filament-android`:       Filament library (AAR) for Android
  - `filament-utils-android`: Extra utilities (KTX loader, math types, etc.)
  - `gltfio-android`:         Filament glTF loading library (AAR) for Android
  - `samples`:                Android-specific Filament samples
- `art`:                      Source for various artworks (logos, PDF manuals, etc.)
- `assets`:                   3D assets to use with sample applications
- `build`:                    CMake build scripts
- `docs`:                     Documentation
  - `math`:                   Mathematica notebooks used to explore BRDFs, equations, etc.
- `filament`:                 Filament rendering engine (minimal dependencies)
  - `backend`:                Rendering backends/drivers (Vulkan, Metal, OpenGL/ES)
- `ide`:                      Configuration files for IDEs (CLion, etc.)
- `ios`:                      Sample projects for iOS
- `libs`:                     Libraries
  - `bluegl`:                 OpenGL bindings for macOS, Linux and Windows
  - `bluevk`:                 Vulkan bindings for macOS, Linux, Windows and Android
  - `camutils`:               Camera manipulation utilities
  - `filabridge`:             Library shared by the Filament engine and host tools
  - `filaflat`:               Serialization/deserialization library used for materials
  - `filagui`:                Helper library for [Dear ImGui](https://github.com/ocornut/imgui)
  - `filamat`:                Material generation library
  - `filamentapp`:            SDL2 skeleton to build sample apps
  - `filameshio`:             Tiny filamesh parsing library (see also `tools/filamesh`)
  - `geometry`:               Mesh-related utilities
  - `gltfio`:                 Loader for glTF 2.0
  - `ibl`:                    IBL generation tools
  - `image`:                  Image filtering and simple transforms
  - `imageio`:                Image file reading / writing, only intended for internal use
  - `matdbg`:                 DebugServer for inspecting shaders at run-time (debug builds only)
  - `math`:                   Math library
  - `mathio`:                 Math types support for output streams
  - `utils`:                  Utility library (threads, memory, data structures, etc.)
  - `viewer`:                 glTF viewer library (requires gltfio)
- `samples`:                  Sample desktop applications
- `shaders`:                  Shaders used by `filamat` and `matc`
- `third_party`:              External libraries and assets
  - `environments`:           Environment maps under CC0 license that can be used with `cmgen`
  - `models`:                 Models under permissive licenses
  - `textures`:               Textures under CC0 license
- `tools`:                    Host tools
  - `cmgen`:                  Image-based lighting asset generator
  - `filamesh`:               Mesh converter
  - `glslminifier`:           Minifies GLSL source code
  - `matc`:                   Material compiler
  - `matedit`:                Material editor for compiled materials
  - `matinfo`                 Displays information about materials compiled with `matc`
  - `mipgen`                  Generates a series of miplevels from a source image
  - `normal-blending`:        Tool to blend normal maps
  - `resgen`                  Aggregates binary blobs into embeddable resources
  - `roughness-prefilter`:    Pre-filters a roughness map from a normal map to reduce aliasing
  - `specular-color`:         Computes the specular color of conductors based on spectral data
- `web`:                      JavaScript bindings, documentation, and samples

## License

Please see [LICENSE](/LICENSE).

## Disclaimer

This is not an officially supported Google product.
