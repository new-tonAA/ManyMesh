from pathlib import Path
p = Path('samples/mm_bench.cpp')
s = p.read_text(encoding='utf-8')

def rep(old, new, count=1):
    global s
    assert old in s, old[:120]
    s = s.replace(old, new, count)

rep('''Texture* g_detailNormalTexture = nullptr;
Texture* g_aoMapTexture = nullptr;
''', '''Texture* g_detailNormalTexture = nullptr;
Texture* g_detailHeightTexture = nullptr;
Texture* g_aoMapTexture = nullptr;
''')

rep('''std::string g_detailNormalPath;
float g_normalStrength = 1.0f;
''', '''std::string g_detailNormalPath;
float g_normalStrength = 1.0f;
std::string g_detailHeightPath;
//! UV-space parallax scale. Negative means "read the sidecar written by mmgeo"; 0 disables it.
float g_parallaxScale = 0.02f;
bool g_parallaxScaleAuto = true;
float g_parallaxStrength = 1.0f;
int g_parallaxLayers = 8;
''')

marker = '''}

void applyShadingParameters(MaterialInstance* instance) {
'''
helper = r'''}

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
    image::LinearImage const decoded = image::ImageDecoder::decode(in, path,
            image::ImageDecoder::ColorSpace::LINEAR);
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
    Texture* const texture = Texture::Builder()
                                     .width(width)
                                     .height(height)
                                     .levels(0xff)
                                     .format(Texture::InternalFormat::R8)
                                     .usage(Texture::Usage::DEFAULT |
                                             Texture::Usage::GEN_MIPMAPPABLE)
                                     .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, size_t(width) * height,
                    Texture::Format::R, Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) {
                        delete[] static_cast<uint8_t*>(buffer);
                    }));
    texture->generateMipmaps(*engine);
    return texture;
}

Texture* createNeutralNormalTexture(Engine* engine) {
    if (engine == nullptr) {
        return nullptr;
    }
    auto* const pixels = new uint8_t[3]{ 128, 128, 255 };
    Texture* const texture = Texture::Builder()
                                     .width(1)
                                     .height(1)
                                     .levels(1)
                                     .format(Texture::InternalFormat::RGB8)
                                     .build(*engine);
    texture->setImage(*engine, 0,
            Texture::PixelBufferDescriptor(pixels, 3, Texture::Format::RGB,
                    Texture::Type::UBYTE,
                    [](void* buffer, size_t, void*) {
                        delete[] static_cast<uint8_t*>(buffer);
                    }));
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
        if (separator != std::string::npos &&
                line.substr(0, separator) == "recommendedUvScale") {
            return float(std::atof(line.c_str() + separator + 1));
        }
    }
    return 0.02f;
}

void applyShadingParameters(MaterialInstance* instance) {
'''
assert marker in s
s = s.replace(marker, helper, 1)

rep('''    if (g_aoMapTexture != nullptr && g_material->hasParameter("aoMap")) {
        TextureSampler sampler;
        sampler.setMinFilter(TextureSampler::MinFilter::LINEAR_MIPMAP_LINEAR);
        sampler.setMagFilter(TextureSampler::MagFilter::LINEAR);
        sampler.setWrapModeS(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        sampler.setWrapModeT(TextureSampler::WrapMode::CLAMP_TO_EDGE);
        instance->setParameter("aoMap", g_aoMapTexture, sampler);
    }
}
''', '''    if (g_aoMapTexture != nullptr && g_material->hasParameter("aoMap")) {
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
    if (g_material->hasParameter("parallaxScale")) {
        instance->setParameter("parallaxScale", g_parallaxScale);
    }
    if (g_material->hasParameter("parallaxStrength")) {
        instance->setParameter("parallaxStrength", g_parallaxStrength);
    }
    if (g_material->hasParameter("parallaxLayers")) {
        instance->setParameter("parallaxLayers", float(g_parallaxLayers));
    }
}
''')

rep('''    if (g_detailNormalTexture == nullptr) {
        g_detailNormalTexture = loadDetailNormalTexture(engine, g_detailNormalPath.c_str());
    }
    if (g_aoMapTexture == nullptr && !g_aoMapPath.empty()) {
        g_aoMapTexture = loadAoMapTexture(engine, g_aoMapPath.c_str());
    }

    g_materialInstance = g_material->createInstance();
''', '''    if (g_detailNormalTexture == nullptr) {
        g_detailNormalTexture = loadDetailNormalTexture(engine, g_detailNormalPath.c_str());
    }
    if (g_detailHeightTexture == nullptr && !g_detailHeightPath.empty()) {
        g_detailHeightTexture = loadHeightMapTexture(engine, g_detailHeightPath.c_str());
        if (g_detailHeightTexture != nullptr && g_parallaxScaleAuto) {
            g_parallaxScale = readParallaxScaleSidecar(g_detailHeightPath);
        }
    }
    if (g_aoMapTexture == nullptr && !g_aoMapPath.empty()) {
        g_aoMapTexture = loadAoMapTexture(engine, g_aoMapPath.c_str());
    }
    if (g_material->hasParameter("normal") && g_detailNormalTexture == nullptr) {
        g_detailNormalTexture = createNeutralNormalTexture(engine);
    }
    if (g_material->hasParameter("heightMap") && g_detailHeightTexture == nullptr) {
        g_detailHeightTexture = createNeutralHeightTexture(engine);
    }

    g_materialInstance = g_material->createInstance();
''')

rep('''    bool const hasVertexAo = g_material != nullptr && g_material->hasParameter("aoStrength") &&
''', '''    if (g_material != nullptr && g_material->hasParameter("parallaxScale")) {
        float strength = g_parallaxStrength;
        ImGui::SliderFloat("Parallax strength", &strength, 0.0f, 2.0f, "%.2f");
        g_parallaxStrength = strength;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        int layers = g_parallaxLayers;
        ImGui::SliderInt("Parallax layers", &layers, 1, 32);
        g_parallaxLayers = layers;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            applyShadingParameters(g_materialInstance);
            for (MaterialInstance* instance: g_lodMaterialInstances) {
                applyShadingParameters(instance);
            }
        }
        float scale = g_parallaxScale;
        ImGui::SliderFloat("Parallax scale", &scale, 0.0f, 0.20f, "%.4f");
        g_parallaxScale = scale;
        if (ImGui::IsItemDeactivatedAfterEdit()) {
            g_parallaxScaleAuto = false;
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
''')

rep('''        samples::Parameter::makeString("detail-normal", '\\0',
                "Detail normal map baked with mmgeo --bake-normal", ""),
        samples::Parameter::makeFloat("normal-strength", '\\0',
                "Strength of the baked LOD normal detail; 0 keeps the LOD normals", 1.0f),
''', '''        samples::Parameter::makeString("detail-normal", '\\0',
                "Detail normal map baked with mmgeo --bake-normal", ""),
        samples::Parameter::makeFloat("normal-strength", '\\0',
                "Strength of the baked LOD normal detail; 0 keeps the LOD normals", 1.0f),
        samples::Parameter::makeString("detail-height", '\\0',
                "Height map baked with mmgeo --bake-height", ""),
        samples::Parameter::makeFloat("parallax-scale", '\\0',
                "UV-space parallax scale; negative reads the mmgeo sidecar", -1.0f),
        samples::Parameter::makeInt("parallax-layers", '\\0',
                "Parallax fixed-point iterations", 8, 1, 32),
        samples::Parameter::makeFloat("parallax-strength", '\\0',
                "Scales the baked displacement; 0 keeps the LOD surface", 1.0f),
''')

rep('''    g_detailNormalPath = config.getString("detail-normal").c_str_safe();
    g_normalStrength = config.getFloat("normal-strength");
''', '''    g_detailNormalPath = config.getString("detail-normal").c_str_safe();
    g_normalStrength = config.getFloat("normal-strength");
    g_detailHeightPath = config.getString("detail-height").c_str_safe();
    float const requestedParallaxScale = config.getFloat("parallax-scale", -1.0f);
    g_parallaxScaleAuto = requestedParallaxScale < 0.0f;
    g_parallaxScale = g_parallaxScaleAuto ? 0.02f : requestedParallaxScale;
    g_parallaxStrength = std::clamp(config.getFloat("parallax-strength", 1.0f), 0.0f, 2.0f);
    g_parallaxLayers = std::clamp(config.getInt("parallax-layers", 8), 1, 32);
''')

rep('''        if (g_detailNormalTexture != nullptr) {
            engine->destroy(g_detailNormalTexture);
            g_detailNormalTexture = nullptr;
        }
''', '''        if (g_detailNormalTexture != nullptr) {
            engine->destroy(g_detailNormalTexture);
            g_detailNormalTexture = nullptr;
        }
        if (g_detailHeightTexture != nullptr) {
            engine->destroy(g_detailHeightTexture);
            g_detailHeightTexture = nullptr;
        }
''')

p.write_text(s, encoding='utf-8')
print('mm_bench patched')
