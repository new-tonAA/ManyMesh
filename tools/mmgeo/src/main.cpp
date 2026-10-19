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

#include <manymesh/AmbientOcclusion.h>
#include <manymesh/Clusterizer.h>
#include <manymesh/DetailBake.h>
#include <manymesh/GeometryError.h>
#include <manymesh/GpuLod.h>
#include <manymesh/Grouper.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/ShadingNormals.h>
#include <manymesh/Simplifier.h>
#include <manymesh/Streaming.h>
#include <manymesh/VisibilityBuffer.h>

#include <math/vec3.h>

#include <image/LinearImage.h>
#include <imageio/ImageEncoder.h>

#include <utils/getopt.h>

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace math = filament::math;
using namespace filament::manymesh;

namespace {

struct Options {
    std::string input;
    std::string outDir = "out/mmgeo";

    bool clusterMode = true;
    bool dagMode = false;
    uint32_t levels = 5;
    float ratio = 0.7f;
    float targetError = 1e-2f;

    uint32_t dagGroupSize = 8;
    bool useTier = true;
    std::string tierName = "balanced";
    bool useTargetRatio = false;
    float targetTriangleRatio = 0.5f;
    bool writeDag = true;
    bool writeVisibility = false;
    bool attributeQem = true;
    bool cornerSeam = true;
    bool cornerSplitUv = true;
    uint32_t streamingPageBytes = 64 * 1024;

    uint32_t clusterVertices = 128;
    uint32_t clusterTriangles = 128;
    float coneWeight = 0.0f;
    bool splitCharts = true;
    uint32_t groupSize = 1;
    int errorLevel = -1;
    bool lockBorder = true;
    bool qualityDebug = false;
    bool qualityGate = true;
    uint32_t qualityAttempts = 4;
    float minTriangleQuality = 0.02f;
    float maxNormalErrorDegrees = 35.0f;
    float maxUvError = 0.10f;

    bool dumpObj = true;
    bool dumpPly = true;
    bool writeJson = true;

    //! 0 disables the detail bake; otherwise the square size of the tangent-space normal map.
    uint32_t bakeNormalSize = 0;
    //! 0 disables the displacement bake; otherwise the square size of the height map.
    uint32_t bakeHeightSize = 0;
    //! 0 disables the source-AO bake; otherwise hemisphere rays per exported LOD vertex.
    uint32_t bakeAoSamples = 0;
    //! 0 disables the source AO field; otherwise hemisphere rays per source vertex. The field is
    //! carried through simplification and serialized with the DAG, so every cut gets AO without
    //! a per-cut bake.
    uint32_t aoFieldSamples = 0;
    //! 0 disables the UV-space AO map; otherwise the square map size in texels.
    uint32_t bakeAoMapSize = 0;
    //! 0 derives the AO ray length from the source bounds.
    float aoRadius = 0.0f;
    //! Duplicate-position shading normals closer than this angle are averaged on export.
    float shadeCreaseDegrees = 0.0f;
    //! Blend factor for the seam-normal repair, in [0, 1].
    float shadeStrength = 1.0f;

    // ViewCamera. When absent, one is framed automatically around the mesh so that a selection
    // and an error map can always be produced.
    bool hasEye = false;
    math::float3 eye{};
    math::float3 lookAt{};
    float fovYDegrees = 45.0f;
    uint32_t screenHeight = 1080;
    uint32_t screenWidth = 1920;
    float thresholdPx = 1.0f;
};

void printUsage(char const* execName) {
    static const char* usage = R"(Usage: %s <input mesh> [options]

Geometry optimization layer: clusters a mesh, builds a per-cluster LOD chain, and reports
the geometric error each level introduces, both in world units and in screen space.

Input may be any format assimp reads (OBJ, PLY, FBX, Collada, ...).

Options:
  --out <dir>          output directory (default: out/mmgeo)
  --mode chain|cluster|dag global LOD chain, per-cluster LOD, or hierarchical DAG
                       (default: cluster)
  --levels N           number of LOD levels including the original (default: 5)
  --ratio F            fraction of triangles kept per level (default: 0.7)
  --target-error F     relative error ceiling for simplification (default: 0.01)
  --cluster-verts N    max vertices per cluster, <= 255 (default: 128)
  --cluster-tris N     max triangles per cluster, <= 512 (default: 128)
  --cone-weight F      0 = size driven clusters, 1 = favour cone culling (default: 0)
  --split-charts 0|1   keep clusters inside connected attribute charts (default: 1)
  --group-size N       clusters merged into one simplification unit (default: 1)
  --dag-group N        children merged into one DAG parent per level (default: 8)
  --tier maximum|balanced|aggressive
                       quality/saving tier for DAG selection (default: balanced)
  --target-ratio F     DAG selection: smallest cut that reaches this triangle ratio
                       (overrides --tier)
  --write-dag 0|1      write lod_graph.mmb and lod_graph.json (default: 1)
  --visibility 0|1     write a software visibility buffer for the DAG selection (default: 0)
  --attribute-qem 0|1  use position+normal+UV QEM for small units (default: 1)
  --corner-seam 0|1    weld attribute seams and generate chart corners so extreme LODs
                       can keep reducing without opening the surface (default: 1)
  --corner-split-uv 0|1
                       keep divergent per-chart UVs in separate generated vertices
                       (default: 1; 0 averages them for A/B only)
  --page-bytes N       streaming page size reported for lod_graph.mmb (default: 65536)
  --error-level K      pin every cluster to level K instead of selecting per view
                       (-1, the default, selects from the camera)
  --lock-border 0|1    per-cluster mode: never move cluster borders (default: 1)
  --quality-debug 0|1  print rejected simplification candidates and their metrics (default: 0)
  --quality-gate 0|1   retry/back off instead of emitting a broken or sliver-heavy LOD (default: 1)
  --quality-attempts N retries per unit when the gate rejects a candidate (default: 4)
  --min-quality F      minimum normalized triangle quality, 0..1 (default: 0.02)
  --max-normal-error F maximum normal deviation in degrees (default: 35)
  --max-uv-error F     maximum mean UV deviation (default: 0.10)
  --dump-obj 0|1       write the simplified meshes (default: 1)
  --dump-format f      obj or ply; ply is binary and loads far faster (default: ply)
  --bake-normal N      bake the normals lost by the selected LOD into an NxN tangent-space
                       normal map (detail-normal.png); 0 disables it (default: 0)
  --bake-height N      bake source-minus-LOD displacement in the shared UV layout into an NxN
                       height map (detail-height.png); 0 disables it (default: 0)
  --bake-ao N          bake source-mesh AO onto the exported LOD vertices with N rays
                       (PLY vertex colors; 0 disables it)
  --ao-field N         bake AO on the source vertices with N rays and carry it through the DAG
                       (generated vertices interpolate it; serialized in lod_graph.mmb)
  --bake-ao-map N      bake source AO into an NxN UV map (ao-map.png); needs UVs in [0,1]
  --ao-radius R        AO ray length in world units; 0 derives 10%% of the bounds diagonal
  --shade-crease DEG   average duplicate-position shading normals closer than DEG, without
                       changing the triangle count; 0 disables it (default: 0)
  --shade-strength F   blend toward the repaired seam normals, 0..1 (default: 1)
  --write-json 0|1     write clusters.json (default: 1)
  --eye x,y,z          camera position; omit to auto-frame the mesh
  --look-at x,y,z      camera target (default: mesh centre)
  --fov-y <deg>        vertical field of view in degrees (default: 45)
  --screen-height N    screen height in pixels for the error map (default: 1080)
  --threshold-px F     screen space error budget in pixels (default: 1.0)
  -h, --help           print this message
  -l, --license        print the licenses of the embedded libraries
)";
    printf(usage, execName);
}

void printLicense() {
    static const char* license[] = {
#include "licenses/licenses.inc"
        nullptr
    };
    for (const char** p = &license[0]; *p; ++p) {
        std::cout << *p++ << std::endl;
    }
}

std::string join(std::string const& dir, std::string const& name) {
    if (dir.empty()) {
        return name;
    }
    char const last = dir.back();
    return (last == '/' || last == '\\') ? dir + name : dir + '/' + name;
}

std::string jsonEscape(std::string const& text) {
    std::string result;
    result.reserve(text.size());
    for (char c: text) {
        if (c == '\\' || c == '"') {
            result.push_back('\\');
        }
        result.push_back(c);
    }
    return result;
}

bool parseVec3(char const* text, math::float3* out) {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    if (sscanf(text, "%f,%f,%f", &x, &y, &z) != 3) {
        return false;
    }
    *out = { x, y, z };
    return true;
}

bool parseTier(std::string const& name, LodTier* tier) {
    if (name == "maximum") {
        *tier = LodTier::MaximumQuality;
        return true;
    }
    if (name == "balanced") {
        *tier = LodTier::Balanced;
        return true;
    }
    if (name == "aggressive") {
        *tier = LodTier::Aggressive;
        return true;
    }
    return false;
}

bool loadMesh(char const* path, Mesh* mesh) {
    Assimp::Importer importer;

    // Triangulate because every stage below assumes triangles; merge duplicate vertices so
    // that simplification is not blocked by artificial seams; bake node transforms so that
    // clusters, bounds and screen space error all live in one world space.
    unsigned int const flags = aiProcess_Triangulate | aiProcess_JoinIdenticalVertices |
                               aiProcess_PreTransformVertices;

    aiScene const* scene = importer.ReadFile(path, flags);
    if (scene == nullptr || scene->mNumMeshes == 0) {
        std::cerr << "Failed to load '" << path << "': " << importer.GetErrorString() << std::endl;
        return false;
    }

    size_t vertexCount = 0;
    size_t triangleCount = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        vertexCount += scene->mMeshes[m]->mNumVertices;
        triangleCount += scene->mMeshes[m]->mNumFaces;
    }

    bool hasNormals = true;
    bool hasUVs = true;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        hasNormals = hasNormals && scene->mMeshes[m]->HasNormals();
        hasUVs = hasUVs && scene->mMeshes[m]->HasTextureCoords(0);
    }

    mesh->positions.reserve(vertexCount);
    mesh->indices.reserve(triangleCount * 3);
    mesh->materialIds.reserve(triangleCount);
    mesh->submeshIds.reserve(triangleCount);
    if (hasNormals) {
        mesh->normals.reserve(vertexCount);
    }
    if (hasUVs) {
        mesh->uvs.reserve(vertexCount);
    }

    uint32_t vertexOffset = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        aiMesh const* source = scene->mMeshes[m];
        for (unsigned int v = 0; v < source->mNumVertices; ++v) {
            aiVector3D const& p = source->mVertices[v];
            mesh->positions.push_back({ p.x, p.y, p.z });
            if (hasNormals) {
                aiVector3D const& n = source->mNormals[v];
                mesh->normals.push_back({ n.x, n.y, n.z });
            }
            if (hasUVs) {
                aiVector3D const& uv = source->mTextureCoords[0][v];
                mesh->uvs.push_back({ uv.x, uv.y });
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

    return true;
}

// Writes the mesh as binary little-endian PLY, referencing only the vertices the triangles
// actually use.
//
// Binary matters for speed rather than size: assimp reads the seven million triangle scan in
// about five seconds, where the same geometry as OBJ text takes minutes of parsing, and a
// comparison run renders several levels of the same asset.
void writePly(Mesh const& mesh, std::vector<uint32_t> const& indices, char const* path,
        std::vector<uint32_t> const* materialIds = nullptr,
        std::vector<uint32_t> const* submeshIds = nullptr,
        std::vector<float> const* ambientOcclusion = nullptr,
        std::vector<math::float3> const* bentNormals = nullptr) {
    std::vector<int32_t> remap(mesh.positions.size(), -1);
    std::vector<uint32_t> vertices;
    std::vector<uint32_t> faces(indices.size());

    for (size_t i = 0; i < indices.size(); ++i) {
        uint32_t const global = indices[i];
        int32_t& local = remap[global];
        if (local < 0) {
            local = int32_t(vertices.size());
            vertices.push_back(global);
        }
        faces[i] = uint32_t(local);
    }

    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }

    size_t const faceCount = faces.size() / 3;
    bool const hasMaterials = materialIds != nullptr && materialIds->size() == faceCount;
    bool const hasSubmeshes = submeshIds != nullptr && submeshIds->size() == faceCount;
    bool const hasNormals = mesh.normals.size() == mesh.positions.size();
    bool const hasUVs = mesh.uvs.size() == mesh.positions.size();
    bool const hasAo = ambientOcclusion != nullptr &&
                       ambientOcclusion->size() == mesh.positions.size();
    bool const hasBentNormals = bentNormals != nullptr &&
                                bentNormals->size() == mesh.positions.size() && hasNormals &&
                                hasUVs;
    // The material consumes bent normals in tangent space, so the exported PLY has to use the
    // same UV frame a renderer derives from these UVs. computeUvTangents() is also what
    // mm_bench uploads, which keeps the offline and harness paths numerically identical.
    std::vector<math::float3> tangents;
    std::vector<float> tangentSigns;
    if (hasAo && hasBentNormals) {
        computeUvTangents(mesh, indices, &tangents, &tangentSigns);
    }
    file << "ply\nformat binary_little_endian 1.0\n";
    file << "element vertex " << vertices.size() << "\n";
    file << "property float x\nproperty float y\nproperty float z\n";
    if (hasNormals) {
        file << "property float nx\nproperty float ny\nproperty float nz\n";
    }
    if (hasUVs) {
        file << "property float s\nproperty float t\n";
    }
    if (hasAo) {
        file << "property uchar red\nproperty uchar green\nproperty uchar blue\n";
    }
    file << "element face " << faceCount << "\n";
    file << "property list uchar int vertex_indices\n";
    if (hasMaterials) {
        file << "property uint material_id\n";
    }
    if (hasSubmeshes) {
        file << "property uint submesh_id\n";
    }
    file << "end_header\n";

    for (uint32_t vertex: vertices) {
        file.write(reinterpret_cast<char const*>(&mesh.positions[vertex].x), sizeof(float) * 3);
        if (hasNormals) {
            file.write(reinterpret_cast<char const*>(&mesh.normals[vertex].x), sizeof(float) * 3);
        }
        if (hasUVs) {
            file.write(reinterpret_cast<char const*>(&mesh.uvs[vertex].x), sizeof(float) * 2);
        }
        if (hasAo) {
            float const value = std::clamp((*ambientOcclusion)[vertex], 0.0f, 1.0f);
            unsigned char const channel = static_cast<unsigned char>(
                    std::clamp(std::lround(value * 255.0f), 0L, 255L));
            unsigned char green = channel;
            unsigned char blue = channel;
            if (hasBentNormals && vertex < tangents.size()) {
                math::float3 n = mesh.normals[vertex];
                float const n2 = dot(n, n);
                n = n2 > 1e-20f ? n * (1.0f / std::sqrt(n2)) : math::float3{ 0.0f, 0.0f, 1.0f };
                math::float3 const t = tangents[vertex];
                math::float3 const b = cross(n, t) * tangentSigns[vertex];
                math::float3 bent = (*bentNormals)[vertex];
                float const b2 = dot(bent, bent);
                if (b2 > 1e-20f) {
                    bent = bent * (1.0f / std::sqrt(b2));
                    float bentX = 0.0f;
                    float bentY = 0.0f;
                    if (dot(bent, n) >= 0.0f) {
                        bentX = dot(bent, t);
                        bentY = dot(bent, b);
                    }
                    float const xy2 = bentX * bentX + bentY * bentY;
                    if (xy2 > 1.0f) {
                        float const scale = 1.0f / std::sqrt(xy2);
                        bentX *= scale;
                        bentY *= scale;
                    }
                    green = static_cast<unsigned char>(std::clamp(
                            std::lround((bentX * 0.5f + 0.5f) * 255.0f), 0L, 255L));
                    blue = static_cast<unsigned char>(std::clamp(
                            std::lround((bentY * 0.5f + 0.5f) * 255.0f), 0L, 255L));
                }
            }
            file.write(reinterpret_cast<char const*>(&channel), 1);
            file.write(reinterpret_cast<char const*>(&green), 1);
            file.write(reinterpret_cast<char const*>(&blue), 1);
        }
    }
    for (size_t face = 0; face < faceCount; ++face) {
        unsigned char const count = 3;
        file.write(reinterpret_cast<char const*>(&count), 1);
        file.write(reinterpret_cast<char const*>(&faces[face * 3]), sizeof(uint32_t) * 3);
        if (hasMaterials) {
            file.write(reinterpret_cast<char const*>(&(*materialIds)[face]), sizeof(uint32_t));
        }
        if (hasSubmeshes) {
            file.write(reinterpret_cast<char const*>(&(*submeshIds)[face]), sizeof(uint32_t));
        }
    }
}

void writeObj(Mesh const& mesh, std::vector<uint32_t> const& indices, char const* path,
        std::vector<uint32_t> const* materialIds = nullptr,
        std::vector<uint32_t> const* submeshIds = nullptr) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }
    for (math::float3 const& p: mesh.positions) {
        file << "v " << p.x << ' ' << p.y << ' ' << p.z << '\n';
    }
    bool const hasNormals = mesh.normals.size() == mesh.positions.size();
    bool const hasUVs = mesh.uvs.size() == mesh.positions.size();
    if (hasUVs) {
        for (math::float2 const& uv: mesh.uvs) {
            file << "vt " << uv.x << ' ' << uv.y << '\n';
        }
    }
    if (hasNormals) {
        for (math::float3 const& n: mesh.normals) {
            file << "vn " << n.x << ' ' << n.y << ' ' << n.z << '\n';
        }
    }
    bool const hasMaterials = materialIds != nullptr && materialIds->size() == indices.size() / 3;
    bool const hasSubmeshes = submeshIds != nullptr && submeshIds->size() == indices.size() / 3;
    if (hasMaterials) {
        std::string const mtlName = std::filesystem::path(path).filename().string() + ".mtl";
        file << "mtllib " << mtlName << '\n';
    }
    uint32_t currentMaterial = UINT32_MAX;
    uint32_t currentSubmesh = UINT32_MAX;
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        size_t const triangle = i / 3;
        if (hasMaterials && (*materialIds)[triangle] != currentMaterial) {
            currentMaterial = (*materialIds)[triangle];
            file << "usemtl mm_material_" << currentMaterial << '\n';
        }
        if (hasSubmeshes && (*submeshIds)[triangle] != currentSubmesh) {
            currentSubmesh = (*submeshIds)[triangle];
            file << "g mm_submesh_" << currentSubmesh << '\n';
        }
        uint32_t const a = indices[i + 0] + 1;
        uint32_t const b = indices[i + 1] + 1;
        uint32_t const c = indices[i + 2] + 1;
        if (hasUVs && hasNormals) {
            file << "f " << a << '/' << a << '/' << a << ' ' << b << '/' << b << '/' << b << ' '
                 << c << '/' << c << '/' << c << '\n';
        } else if (hasUVs) {
            file << "f " << a << '/' << a << ' ' << b << '/' << b << ' ' << c << '/' << c << '\n';
        } else if (hasNormals) {
            file << "f " << a << "//" << a << ' ' << b << "//" << b << ' ' << c << "//" << c
                 << '\n';
        } else {
            file << "f " << a << ' ' << b << ' ' << c << '\n';
        }
    }

    if (hasMaterials) {
        std::ofstream mtl(std::string(path) + ".mtl");
        if (mtl) {
            std::set<uint32_t> unique(materialIds->begin(), materialIds->end());
            for (uint32_t material: unique) {
                mtl << "newmtl mm_material_" << material << "\n"
                    << "Kd 0.8 0.8 0.8\n"
                    << "Ks 0.0 0.0 0.0\n"
                    << "d 1.0\n"
                    << "illum 2\n\n";
            }
        }
    }
}

bool writeDetailNormalPng(DetailBakeResult const& bake, char const* path) {
    // RGBA, not RGB: alpha carries the normalized lost-normal angle used for per-texel specular
    // roughness compensation. Dropping it here would silently turn that term back into a global
    // roughness boost after a bake/reload round trip.
    image::LinearImage image(bake.size, bake.size, 4);
    for (uint32_t y = 0; y < bake.size; ++y) {
        float* const row = image.getPixelRef(0, y);
        for (uint32_t x = 0; x < bake.size; ++x) {
            uint8_t const* const pixel = &bake.rgba[(size_t(y) * bake.size + x) * 4];
            row[x * 4 + 0] = float(pixel[0]) / 255.0f;
            row[x * 4 + 1] = float(pixel[1]) / 255.0f;
            row[x * 4 + 2] = float(pixel[2]) / 255.0f;
            row[x * 4 + 3] = float(pixel[3]) / 255.0f;
        }
    }
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return false;
    }
    return image::ImageEncoder::encode(file, image::ImageEncoder::Format::PNG_LINEAR, image, "",
            path);
}

bool writeAoMapPng(AmbientOcclusionMapResult const& bake, char const* path) {
    image::LinearImage image(bake.size, bake.size, 3);
    for (uint32_t y = 0; y < bake.size; ++y) {
        float* const row = image.getPixelRef(0, y);
        for (uint32_t x = 0; x < bake.size; ++x) {
            float const value = float(bake.values[size_t(y) * bake.size + x]) / 255.0f;
            row[x * 3 + 0] = value;
            row[x * 3 + 1] = value;
            row[x * 3 + 2] = value;
        }
    }
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return false;
    }
    return image::ImageEncoder::encode(file, image::ImageEncoder::Format::PNG_LINEAR, image, "",
            path);
}

bool writeDetailHeightPng(DetailHeightResult const& bake, char const* path) {
    image::LinearImage image(bake.size, bake.size, 3);
    for (uint32_t y = 0; y < bake.size; ++y) {
        float* const row = image.getPixelRef(0, y);
        for (uint32_t x = 0; x < bake.size; ++x) {
            float const value = float(bake.values[size_t(y) * bake.size + x]) / 255.0f;
            row[x * 3 + 0] = value;
            row[x * 3 + 1] = value;
            row[x * 3 + 2] = value;
        }
    }
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return false;
    }
    return image::ImageEncoder::encode(file, image::ImageEncoder::Format::PNG_LINEAR, image, "",
            path);
}

// Source AO in the source UV layout. This is a material-level asset: it is shared by every LOD
// cut that keeps the parameterization, so it is baked once rather than per exported level.
void bakeAoMap(Mesh const& source, Options const& options) {
    if (options.bakeAoMapSize == 0) {
        return;
    }
    AmbientOcclusionMapOptions bakeOptions;
    bakeOptions.samples = options.bakeAoSamples > 0 ? options.bakeAoSamples : 32;
    bakeOptions.size = options.bakeAoMapSize;
    bakeOptions.radius = options.aoRadius;
    AmbientOcclusionMapResult bake;
    if (!bakeAmbientOcclusionMap(source, bakeOptions, &bake)) {
        std::cerr << "  AO map bake skipped: it needs source normals and UVs in [0,1]"
                  << std::endl;
        return;
    }
    std::string const path = join(options.outDir, "ao-map.png");
    if (!writeAoMapPng(bake, path.c_str())) {
        std::cerr << "  could not write '" << path << "'" << std::endl;
        return;
    }
    printf("  baked %s (%ux%u, %zu covered texels, %.3f mean, %u samples, radius %.5f%s, "
           "%.1f ms)\n",
            path.c_str(), bake.size, bake.size, bake.coveredTexels, bake.mean,
            bakeOptions.samples, bake.radius, options.aoRadius > 0.0f ? "" : " (auto)",
            bake.bakeMs);
}

// Bakes the high-poly normal field into the low-poly UV layout. The map holds only the detail
// the LOD lost: its neutral value is (0, 0, 1), so the LOD's own vertex normals still carry the
// large-scale shape.
void bakeDetailNormal(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& indices, Options const& options) {
    if (options.bakeNormalSize == 0) {
        return;
    }
    DetailBakeOptions bakeOptions;
    bakeOptions.size = options.bakeNormalSize;
    DetailBakeResult bake;
    if (!bakeDetailNormalMap(source, lod, indices, bakeOptions, &bake)) {
        std::cerr << "  detail normal bake skipped: both meshes need normals and UVs, and every "
                     "LOD UV must lie in [0,1] (a tiled layout needs an unwrapped atlas first)"
                  << std::endl;
        return;
    }
    std::string const path = join(options.outDir, "detail-normal.png");
    if (!writeDetailNormalPng(bake, path.c_str())) {
        std::cerr << "  could not write '" << path << "'" << std::endl;
        return;
    }
    printf("  baked %s (%ux%u, %.1f%% of UV space covered, lost normal detail: mean %.2f deg, "
           "max %.2f deg, %zu UV-mismatch texels kept neutral)\n",
            path.c_str(), bake.size, bake.size,
            100.0 * double(bake.coveredTexels) / double(bake.lodTexels),
            bake.meanAngleDegrees, bake.maxAngleDegrees, bake.mismatchedTexels);
}

// Bakes the source displacement into the selected LOD's UV layout. The map is signed around
// 0.5, so a material can sample it with iterative parallax mapping without a second scale map.
void bakeDetailHeight(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& indices, Options const& options) {
    if (options.bakeHeightSize == 0) {
        return;
    }
    DetailHeightOptions bakeOptions;
    bakeOptions.size = options.bakeHeightSize;
    DetailHeightResult bake;
    if (!bakeDetailHeightMap(source, lod, indices, bakeOptions, &bake)) {
        std::cerr << "  detail height bake skipped: both meshes need normals and UVs, every "
                     "LOD UV must lie in [0,1], and the LOD must overlap the source surface"
                  << std::endl;
        return;
    }
    std::string const path = join(options.outDir, "detail-height.png");
    if (!writeDetailHeightPng(bake, path.c_str())) {
        std::cerr << "  could not write '" << path << "'" << std::endl;
        return;
    }
    std::string const sidecarPath = path + ".txt";
    std::ofstream sidecar(sidecarPath, std::ios::trunc);
    if (sidecar) {
        sidecar << "heightRange=" << bake.heightRange << "\n"
                << "recommendedUvScale=" << bake.recommendedUvScale << "\n";
    }
    printf("  baked %s (%ux%u, %zu covered texels, %zu misses, signed height %.5f..%.5f, "
           "mean |h| %.5f, range %.5f, recommended parallax scale %.5f, %.1f ms)\n",
            path.c_str(), bake.size, bake.size, bake.coveredTexels, bake.missedTexels,
            bake.minHeight, bake.maxHeight, bake.meanAbsHeight, bake.heightRange,
            bake.recommendedUvScale, bake.bakeMs);
}

struct GeometryOutput {
    std::vector<uint32_t> indices;
    std::vector<uint32_t> materialIds;
    std::vector<uint32_t> submeshIds;
};

GeometryOutput outputFromLevel(LodLevel const& level) {
    GeometryOutput result;
    result.indices = level.indices;
    size_t const triangles = result.indices.size() / 3;
    if (level.materialIds.size() == triangles) {
        result.materialIds = level.materialIds;
    } else {
        result.materialIds.assign(triangles, level.materialId);
    }
    if (level.submeshIds.size() == triangles) {
        result.submeshIds = level.submeshIds;
    } else {
        result.submeshIds.assign(triangles, level.submeshId);
    }
    return result;
}

void appendOutput(GeometryOutput* destination, GeometryOutput const& source) {
    destination->indices.insert(destination->indices.end(), source.indices.begin(),
            source.indices.end());
    destination->materialIds.insert(destination->materialIds.end(), source.materialIds.begin(),
            source.materialIds.end());
    destination->submeshIds.insert(destination->submeshIds.end(), source.submeshIds.begin(),
            source.submeshIds.end());
}

void writeGeometry(Mesh const& mesh, GeometryOutput const& geometry, char const* path,
        Options const& options, std::vector<float> const* ambientOcclusion = nullptr,
        std::vector<math::float3> const* bentNormals = nullptr) {
    Mesh shaded;
    Mesh const* output = &mesh;
    if (options.shadeCreaseDegrees > 0.0f) {
        shaded = mesh;
        ShadingNormalOptions shading;
        shading.creaseAngleDegrees = options.shadeCreaseDegrees;
        shading.strength = options.shadeStrength;
        ShadingNormalResult result;
        repairShadingNormals(&shaded, geometry.indices, shading, &result);
        printf("  shade normals: crease %.1f deg, strength %.2f, %zu duplicate vertices, "
               "%zu merged clusters, %zu changed vertices, max %.2f deg\n",
                options.shadeCreaseDegrees, options.shadeStrength, result.duplicateVertices,
                result.mergedClusters,
                result.changedVertices, result.maxMergedAngleDegrees);
        output = &shaded;
    }
    if (options.dumpPly) {
        if (ambientOcclusion == nullptr && output->hasAO()) {
            ambientOcclusion = &output->ao;
        }
        writePly(*output, geometry.indices, path, &geometry.materialIds, &geometry.submeshIds,
                ambientOcclusion, bentNormals);
    } else {
        writeObj(*output, geometry.indices, path, &geometry.materialIds, &geometry.submeshIds);
    }
}

// Writes one mesh to the output directory, in whichever format was asked for.
void dumpMesh(Mesh const& mesh, GeometryOutput const& geometry, Options const& options,
        std::string const& stem, std::vector<float> const* ambientOcclusion = nullptr) {
    std::string const path = join(options.outDir, stem + (options.dumpPly ? ".ply" : ".obj"));
    writeGeometry(mesh, geometry, path.c_str(), options, ambientOcclusion);
}

// Concatenates the given level of every cluster, clamped to the coarsest level each cluster
// actually has. Used to dump a "whole mesh at level N" OBJ in per-cluster mode.
GeometryOutput gatherLevel(std::vector<ClusterLods> const& lods, uint32_t level) {
    GeometryOutput result;
    for (ClusterLods const& clusterLods: lods) {
        if (clusterLods.levels.empty()) {
            continue;
        }
        uint32_t const clamped = std::min(level, uint32_t(clusterLods.levels.size() - 1));
        appendOutput(&result, outputFromLevel(clusterLods.levels[clamped]));
    }
    return result;
}

GeometryOutput gatherSelection(std::vector<ClusterLods> const& lods, Selection const& selection) {
    GeometryOutput result;
    for (size_t c = 0; c < selection.levelPerCluster.size(); ++c) {
        // Clusters the frustum rejects keep their default level, which is full detail. Writing
        // those out would put the whole off screen scene into the mesh at level 0, and the
        // renderer would then pay to transform geometry that a real one would have thrown away
        // before it ever reached a level of detail decision.
        if (c < selection.visiblePerCluster.size() && selection.visiblePerCluster[c] == 0) {
            continue;
        }
        uint32_t const level = selection.levelPerCluster[c];
        if (level >= lods[c].levels.size()) {
            continue;
        }
        appendOutput(&result, outputFromLevel(lods[c].levels[level]));
    }
    return result;
}

GeometryOutput outputFromDagSelection(LodGraphSelection const& selection) {
    GeometryOutput result;
    result.indices = selection.indices;
    size_t const triangles = result.indices.size() / 3;
    result.materialIds = selection.materialIds.size() == triangles
                                 ? selection.materialIds
                                 : std::vector<uint32_t>(triangles, UINT32_MAX);
    result.submeshIds = selection.submeshIds.size() == triangles
                                ? selection.submeshIds
                                : std::vector<uint32_t>(triangles, UINT32_MAX);
    return result;
}

void writeDagJson(Mesh const& mesh, LodGraph const& graph, LodGraphSelection const& selection,
        Options const& options, float maxScreenError, char const* path) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }
    double const ratio = graph.baseTriangles > selection.culledTriangles
                                 ? double(selection.selectedTriangles) /
                                           double(graph.baseTriangles - selection.culledTriangles)
                                 : 1.0;
    file << "{\n";
    file << "  \"source\": \"" << jsonEscape(options.input) << "\",\n";
    file << "  \"vertices\": " << mesh.vertexCount() << ",\n";
    file << "  \"generatedVertices\": " << graph.generatedVertices.size() << ",\n";
    file << "  \"sourceVertices\": " << graph.sourceVertexCount() << ",\n";
    file << "  \"triangles\": " << mesh.triangleCount() << ",\n";
    file << "  \"nodes\": " << graph.nodes.size() << ",\n";
    file << "  \"levels\": " << graph.levelCount << ",\n";
    file << "  \"clustersPerNode\": " << options.dagGroupSize << ",\n";
    file << "  \"ratio\": " << options.ratio << ",\n";
    file << "  \"attributeQem\": " << (options.attributeQem ? "true" : "false") << ",\n";
    file << "  \"cornerSeam\": " << (options.cornerSeam ? "true" : "false") << ",\n";
    file << "  \"cornerSplitUv\": " << (options.cornerSplitUv ? "true" : "false") << ",\n";
    file << "  \"tier\": \"" << jsonEscape(options.tierName) << "\",\n";
    file << "  \"targetRatio\": " << options.targetTriangleRatio << ",\n";
    file << "  \"selectedTriangles\": " << selection.selectedTriangles << ",\n";
    file << "  \"baseTriangles\": " << selection.baseTriangles << ",\n";
    file << "  \"culledTriangles\": " << selection.culledTriangles << ",\n";
    file << "  \"visibleRatio\": " << ratio << ",\n";
    file << "  \"maxScreenErrorPx\": " << maxScreenError << ",\n";
    file << "  \"roots\": [";
    for (size_t i = 0; i < graph.roots.size(); ++i) {
        file << (i ? "," : "") << graph.roots[i];
    }
    file << "],\n  \"leaves\": [";
    for (size_t i = 0; i < graph.leaves.size(); ++i) {
        file << (i ? "," : "") << graph.leaves[i];
    }
    file << "],\n  \"selectedNodes\": [";
    for (size_t i = 0; i < selection.nodes.size(); ++i) {
        file << (i ? "," : "") << selection.nodes[i];
    }
    file << "],\n  \"dag\": [\n";
    for (size_t n = 0; n < graph.nodes.size(); ++n) {
        LodGraphNode const& node = graph.nodes[n];
        file << "    {\"id\":" << n << ",\"level\":" << node.level << ",\"parent\":" << node.parent
             << ",\"children\":[";
        for (size_t i = 0; i < node.children.size(); ++i) {
            file << (i ? "," : "") << node.children[i];
        }
        file << "],\"tri\":" << node.triangleCount() << ",\"baseTri\":" << node.baseTriangles
             << ",\"selfError\":" << node.selfError
             << ",\"accumulatedError\":" << node.accumulatedError
             << ",\"material\":" << node.materialId << ",\"submesh\":" << node.submeshId
             << ",\"simplified\":" << (node.simplified ? "true" : "false")
             << ",\"bounds\":{\"center\":[" << node.bounds.center.x << ',' << node.bounds.center.y
             << ',' << node.bounds.center.z << "],\"radius\":" << node.bounds.radius << "}"
             << ",\"boundaryEdges\":" << node.topology.boundaryEdges
             << ",\"nonManifoldEdges\":" << node.topology.nonManifoldEdges
             << ",\"duplicateTriangles\":" << node.topology.duplicateTriangles
             << ",\"degenerateTriangles\":" << node.topology.degenerateTriangles
             << ",\"minQuality\":" << node.topology.minTriangleQuality
             << ",\"normalErrorDeg\":" << node.attributes.maxNormalErrorRadians * 57.2957795f
             << ",\"uvError\":" << node.attributes.maxUvError << "}";
        file << (n + 1 == graph.nodes.size() ? "\n" : ",\n");
    }
    file << "  ]\n}\n";
}

void writeJson(Mesh const& mesh, ClusterSet const& clusters, std::vector<ClusterLods> const& lods,
        Options const& options, char const* path) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }

    file << "{\n";
    file << "  \"source\": \"" << jsonEscape(options.input) << "\",\n";
    file << "  \"vertices\": " << mesh.vertexCount() << ",\n";
    file << "  \"triangles\": " << mesh.triangleCount() << ",\n";
    file << "  \"clusterMaxVertices\": " << clusters.maxVertices << ",\n";
    file << "  \"clusterMaxTriangles\": " << clusters.maxTriangles << ",\n";
    file << "  \"levels\": " << options.levels << ",\n";
    file << "  \"ratio\": " << options.ratio << ",\n";
    file << "  \"lockBorder\": " << (options.lockBorder ? "true" : "false") << ",\n";
    file << "  \"clusters\": [\n";

    for (size_t c = 0; c < clusters.clusters.size(); ++c) {
        Cluster const& cluster = clusters.clusters[c];
        ClusterLods const& clusterLods = lods[c];

        file << "    {\"c\":[" << cluster.bounds.center.x << ',' << cluster.bounds.center.y << ','
             << cluster.bounds.center.z << "],\"r\":" << cluster.bounds.radius;
        file << ",\"ca\":[" << cluster.cone.axis.x << ',' << cluster.cone.axis.y << ','
             << cluster.cone.axis.z << "],\"cc\":" << cluster.cone.cutoff;

        // Per level: triangle count and the world space error that level introduces.
        // Two parallel arrays keep the file compact, which matters at seven million triangles.
        file << ",\"tri\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].triangleCount();
        }
        file << "],\"err\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].worldError;
        }
        file << "],\"boundaryEdges\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].topology.boundaryEdges;
        }
        file << "],\"nonManifoldEdges\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].topology.nonManifoldEdges;
        }
        file << "],\"minQuality\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].topology.minTriangleQuality;
        }
        file << "],\"normalErrorDeg\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "")
                 << clusterLods.levels[l].attributes.maxNormalErrorRadians * 57.2957795f;
        }
        file << "],\"uvError\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].attributes.maxUvError;
        }
        file << "],\"meanNormalErrorDeg\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "")
                 << clusterLods.levels[l].attributes.meanNormalErrorRadians * 57.2957795f;
        }
        file << "],\"meanUvError\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << clusterLods.levels[l].attributes.meanUvError;
        }
        file << "],\"simplified\":[";
        for (size_t l = 0; l < clusterLods.levels.size(); ++l) {
            file << (l ? "," : "") << (clusterLods.levels[l].simplified ? 1 : 0);
        }
        file << "],\"material\":" << cluster.materialId << ",\"submesh\":" << cluster.submeshId;
        file << "]}";
        file << (c + 1 == clusters.clusters.size() ? "\n" : ",\n");
    }

    file << "  ]\n}\n";
}

void printChainStats(Mesh const& mesh, std::vector<LodLevel> const& levels) {
    printf("\n");
    printf("  %-6s %12s %14s %14s\n", "level", "triangles", "rel. error", "world error");
    for (size_t l = 0; l < levels.size(); ++l) {
        printf("  %-6zu %12zu %13.4f%% %14.6f\n", l, levels[l].triangleCount(),
                levels[l].relativeError * 100.0f, levels[l].worldError);
    }
    if (levels.size() > 1 && levels[0].triangleCount() > 0) {
        printf("  reduction: %.1f%% of the original triangle count remains at the coarsest level\n",
                100.0 * double(levels.back().triangleCount()) / double(levels[0].triangleCount()));
    }
}

void printClusterStats(ClusterSet const& clusters, std::vector<ClusterLods> const& lods) {
    size_t maxLevels = 0;
    double totalError = 0.0;
    for (ClusterLods const& clusterLods: lods) {
        maxLevels = std::max(maxLevels, clusterLods.levels.size());
        totalError += clusterLods.levels.size();
    }

    printf("\n");
    printf("  clusters: %zu   average levels per cluster: %.2f   coarsest level seen: %zu\n",
            clusters.clusters.size(), lods.empty() ? 0.0 : totalError / double(lods.size()),
            maxLevels);

    // The mean is weighted by triangles, because a unit's error only matters in proportion to
    // how much geometry carries it. Reporting the maximum alone is misleading: it is decided
    // by a single worst unit and swings wildly between configurations.
    printf("  %-6s %14s %14s %14s %14s\n", "level", "triangles", "units", "mean w.error",
            "max w.error");
    for (size_t l = 0; l < maxLevels; ++l) {
        uint64_t triangles = 0;
        size_t count = 0;
        float worst = 0.0f;
        double weightedError = 0.0;
        uint64_t weightedTriangles = 0;
        for (ClusterLods const& clusterLods: lods) {
            if (l < clusterLods.levels.size()) {
                LodLevel const& level = clusterLods.levels[l];
                uint64_t const tris = level.triangleCount();
                triangles += tris;
                worst = std::max(worst, level.worldError);
                weightedError += double(level.worldError) * double(tris);
                weightedTriangles += tris;
                count += 1;
            }
        }
        double const mean = weightedTriangles > 0 ? weightedError / double(weightedTriangles) : 0.0;
        printf("  %-6zu %14llu %14zu %14.6f %14.6f\n", l, (unsigned long long) triangles, count,
                mean, worst);
    }
}

void printSelectionStats(Selection const& selection, ViewCamera const& camera, float thresholdPx) {
    printf("\n  camera: eye(%.3f, %.3f, %.3f) fovY(%.1f deg) screen(%u x %u) budget %.2f px\n",
            camera.eye.x, camera.eye.y, camera.eye.z,
            camera.fovY * 180.0f / 3.14159265358979323846f, camera.screenWidth, camera.screenHeight,
            thresholdPx);

    printf("  %-6s %14s %14s\n", "level", "clusters", "triangles");
    for (size_t l = 0; l < selection.clustersPerLevel.size(); ++l) {
        printf("  %-6zu %14u %14llu\n", l, selection.clustersPerLevel[l],
                (unsigned long long) selection.trianglesPerLevel[l]);
    }

    double const ratio = selection.baseTriangles > 0 ? 100.0 * double(selection.selectedTriangles) /
                                                               double(selection.baseTriangles)
                                                     : 0.0;
    printf("  drawn: %llu of %llu triangles (%.1f%%)\n",
            (unsigned long long) selection.selectedTriangles,
            (unsigned long long) selection.baseTriangles, ratio);
    if (selection.culledTriangles > 0) {
        uint64_t const visible = selection.baseTriangles - selection.culledTriangles;
        printf("  culled by the frustum: %llu of %llu triangles (%.1f%%)\n",
                (unsigned long long) selection.culledTriangles,
                (unsigned long long) selection.baseTriangles,
                100.0 * double(selection.culledTriangles) / double(selection.baseTriangles));
        printf("  drawn of what survives culling: %.1f%%\n",
                100.0 * double(selection.selectedTriangles) / double(visible));
    }
}

float maxScreenError(LodGraphSelection const& selection) {
    float result = 0.0f;
    for (float error: selection.screenErrorPerNode) {
        result = std::max(result, error);
    }
    return result;
}

void printDagStats(Mesh const& mesh, LodGraph const& graph, LodGraphSelection const& selection,
        ViewCamera const& camera, float requestedError) {
    printf("\n");
    printf("  DAG: %zu nodes, %zu levels, %zu roots, %zu leaves, %llu base triangles\n",
            graph.nodes.size(), graph.levelCount, graph.roots.size(), graph.leaves.size(),
            (unsigned long long) graph.baseTriangles);
    printf("  camera: eye(%.3f, %.3f, %.3f) fovY(%.1f deg) screen(%u x %u) budget %.2f px\n",
            camera.eye.x, camera.eye.y, camera.eye.z,
            camera.fovY * 180.0f / 3.14159265358979323846f, camera.screenWidth, camera.screenHeight,
            requestedError);
    printf("  %-6s %14s %14s\n", "level", "nodes", "triangles");
    for (size_t l = 0; l < selection.nodesPerLevel.size(); ++l) {
        printf("  %-6zu %14u %14llu\n", l, selection.nodesPerLevel[l],
                (unsigned long long) selection.trianglesPerLevel[l]);
    }
    uint64_t const visibleBase = graph.baseTriangles > selection.culledTriangles
                                         ? graph.baseTriangles - selection.culledTriangles
                                         : graph.baseTriangles;
    double const ratio = visibleBase > 0
                                 ? 100.0 * double(selection.selectedTriangles) / double(visibleBase)
                                 : 100.0;
    printf("  drawn: %llu of %llu visible triangles (%.2f%%) in %zu nodes\n",
            (unsigned long long) selection.selectedTriangles, (unsigned long long) visibleBase,
            ratio, selection.nodes.size());
    printf("  frustum culled: %llu of %llu triangles (%.2f%%)\n",
            (unsigned long long) selection.culledTriangles,
            (unsigned long long) graph.baseTriangles,
            graph.baseTriangles > 0
                    ? 100.0 * double(selection.culledTriangles) / double(graph.baseTriangles)
                    : 0.0);
    printf("  worst selected screen error: %.4f px\n", maxScreenError(selection));
    TopologyStats const baseTopology = measureWeldedTopology(mesh, mesh.indices);
    printf("  base topology: boundary %llu, non-manifold %llu, duplicates %llu, "
           "degenerate %llu, flipped %llu, min quality %.4f\n",
            (unsigned long long) baseTopology.boundaryEdges,
            (unsigned long long) baseTopology.nonManifoldEdges,
            (unsigned long long) baseTopology.duplicateTriangles,
            (unsigned long long) baseTopology.degenerateTriangles,
            (unsigned long long) baseTopology.flippedTriangles, baseTopology.minTriangleQuality);
    TopologyStats const topology = measureWeldedTopology(mesh, selection.indices);
    printf("  selected topology: boundary %llu, non-manifold %llu, duplicates %llu, "
           "degenerate %llu, flipped %llu, min quality %.4f\n",
            (unsigned long long) topology.boundaryEdges,
            (unsigned long long) topology.nonManifoldEdges,
            (unsigned long long) topology.duplicateTriangles,
            (unsigned long long) topology.degenerateTriangles,
            (unsigned long long) topology.flippedTriangles, topology.minTriangleQuality);

    if (topology.boundaryEdges > baseTopology.boundaryEdges ||
            topology.nonManifoldEdges > baseTopology.nonManifoldEdges) {
        // Diagnostics for cross-node seams: print the first few offending edges together with
        // the DAG nodes that own them.
        std::map<std::pair<uint32_t, uint32_t>, std::vector<uint32_t>> edgeNodes;
        std::map<std::pair<uint32_t, uint32_t>, uint32_t> edgeUse;
        std::map<std::pair<uint32_t, uint32_t>, uint32_t> baseEdgeUse;
        std::set<std::array<uint32_t, 3>> keptTriangles;
        for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
            uint32_t const v[3] = { mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2] };
            for (int e = 0; e < 3; ++e) {
                baseEdgeUse[{ std::min(v[e], v[(e + 1) % 3]), std::max(v[e], v[(e + 1) % 3]) }] +=
                        1;
            }
        }
        for (size_t i = 0; i + 2 < selection.indices.size(); i += 3) {
            uint32_t const v[3] = { selection.indices[i], selection.indices[i + 1],
                selection.indices[i + 2] };
            std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
            std::sort(key.begin(), key.end());
            keptTriangles.insert(key);
            for (int e = 0; e < 3; ++e) {
                std::pair<uint32_t, uint32_t> const edge = { std::min(v[e], v[(e + 1) % 3]),
                    std::max(v[e], v[(e + 1) % 3]) };
                edgeUse[edge] += 1;
            }
        }
        for (uint32_t nodeId: selection.nodes) {
            LodGraphNode const& node = graph.nodes[nodeId];
            for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                uint32_t const v[3] = { node.indices[i], node.indices[i + 1], node.indices[i + 2] };
                std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
                std::sort(key.begin(), key.end());
                if (keptTriangles.count(key) == 0) {
                    continue;
                }
                for (int e = 0; e < 3; ++e) {
                    std::pair<uint32_t, uint32_t> const edge = { std::min(v[e], v[(e + 1) % 3]),
                        std::max(v[e], v[(e + 1) % 3]) };
                    auto& owners = edgeNodes[edge];
                    if (std::find(owners.begin(), owners.end(), nodeId) == owners.end()) {
                        owners.push_back(nodeId);
                    }
                }
            }
        }
        int printed = 0;
        for (auto const& [edge, count]: edgeUse) {
            bool const newBoundary =
                    count == 1 && (baseEdgeUse.count(edge) == 0 || baseEdgeUse[edge] != 1);
            if ((newBoundary || count > 2) && printed < 12) {
                printf("  bad edge (%u,%u) use=%u nodes=", edge.first, edge.second, count);
                for (uint32_t owner: edgeNodes[edge]) {
                    printf("%u ", owner);
                }
                printf("\n");
                for (uint32_t owner: edgeNodes[edge]) {
                    LodGraphNode const& node = graph.nodes[owner];
                    for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                        uint32_t const v[3] = { node.indices[i], node.indices[i + 1],
                            node.indices[i + 2] };
                        std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
                        std::sort(key.begin(), key.end());
                        if (keptTriangles.count(key) == 0) {
                            continue;
                        }
                        bool hasA = v[0] == edge.first || v[1] == edge.first || v[2] == edge.first;
                        bool hasB =
                                v[0] == edge.second || v[1] == edge.second || v[2] == edge.second;
                        if (hasA && hasB) {
                            printf("    node %u tri %u %u %u\n", owner, v[0], v[1], v[2]);
                        }
                    }
                }
                printf("    base use=%u leaves=", baseEdgeUse.count(edge) ? baseEdgeUse[edge] : 0u);
                for (uint32_t leaf: graph.leaves) {
                    LodGraphNode const& node = graph.nodes[leaf];
                    uint32_t use = 0;
                    for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                        uint32_t const v[3] = { node.indices[i], node.indices[i + 1],
                            node.indices[i + 2] };
                        for (int e = 0; e < 3; ++e) {
                            std::pair<uint32_t, uint32_t> const pe = {
                                std::min(v[e], v[(e + 1) % 3]), std::max(v[e], v[(e + 1) % 3])
                            };
                            use += pe == edge ? 1u : 0u;
                        }
                    }
                    if (use != 0) {
                        printf("%u(use=%u) ", leaf, use);
                    }
                }
                printf("\n");
                printed += 1;
            }
        }
    }
}

ViewCamera makeCamera(Options const& options, Mesh const& mesh) {
    ViewCamera camera;
    camera.fovY = options.fovYDegrees * 3.14159265358979323846f / 180.0f;
    camera.screenHeight = options.screenHeight;
    // Keep the same pixel density when the height changes, so that a threshold in pixels
    // means the same thing regardless of the requested resolution.
    camera.screenWidth = options.screenHeight * 16 / 9;

    if (options.hasEye) {
        camera.eye = options.eye;
        camera.target = options.lookAt;
        // Near and far still have to bracket the scene. Leaving the defaults would put the far
        // plane at 1000 units, which silently culls anything further away - whole scenes.
        math::float3 lo{};
        math::float3 hi{};
        computeBounds(mesh, &lo, &hi);
        float const radius = length(hi - lo) * 0.5f;
        float const distance = length(camera.eye - camera.target);
        camera.near = std::max(distance * 0.001f, 1e-3f);
        camera.far = distance + radius * 4.0f + 1.0f;
        return camera;
    }

    // Auto-frame by fitting the bounding *box* to the field of view. Fitting the bounding
    // sphere instead would use the box diagonal, which for anything elongated — a scan of a
    // dragon, say — parks the camera far enough that the model occupies a corner of the frame.
    math::float3 lo{};
    math::float3 hi{};
    computeBounds(mesh, &lo, &hi);
    math::float3 const center = (lo + hi) * 0.5f;
    math::float3 const extent = hi - lo;

    float const tanHalfFovY = std::max(std::tan(camera.fovY * 0.5f), 1e-4f);
    float const aspect = float(camera.screenWidth) / float(std::max(camera.screenHeight, 1u));
    float const distanceForHeight = (extent.y * 0.5f) / tanHalfFovY;
    float const distanceForWidth = (extent.x * 0.5f) / (tanHalfFovY * aspect);
    // Step back past the near face of the box as well, so nothing ends up behind the camera.
    float const distance = std::max(distanceForHeight, distanceForWidth) * 1.05f + extent.z * 0.5f;

    camera.target = center;
    camera.eye = center + math::float3{ 0.0f, 0.0f, std::max(distance, 1e-3f) };
    camera.near = std::max(distance * 0.01f, 1e-4f);
    camera.far = distance + extent.z + length(extent);
    return camera;
}

//! Does the option named by this argument require a value?
bool optionRequiresValue(char const* arg, utils::getopt::option const* table) {
    if (arg[0] != '-' || arg[1] == '\0') {
        return false;
    }
    if (arg[1] != '-') {
        return false; // the only short options here, -h and -l, are flags
    }
    if (strchr(arg + 2, '=') != nullptr) {
        return false; // --name=value carries its own
    }
    std::string const name(arg + 2);
    for (utils::getopt::option const* option = table; option->name != nullptr; ++option) {
        if (name == option->name) {
            return option->has_arg == utils::getopt::required_argument;
        }
    }
    return false;
}

/**
 * The getopt bundled with this repository stops at the first non-option argument instead of
 * permuting the command line the way glibc does. Left alone, `mmgeo mesh.ply --out dir` would
 * quietly parse no options at all and write to the default directory, which is exactly the
 * order people write commands in. Moving the positional argument to the end of argv first
 * makes its position irrelevant.
 */
void rotatePositionalToEnd(int argc, char** argv, utils::getopt::option const* table) {
    bool previousTakesValue = false;
    for (int i = 1; i < argc; ++i) {
        char const* const arg = argv[i];
        if (previousTakesValue) {
            previousTakesValue = false;
            continue;
        }
        if (arg[0] == '-' && arg[1] != '\0') {
            previousTakesValue = optionRequiresValue(arg, table);
            continue;
        }

        char* const positional = argv[i];
        for (int j = i; j + 1 < argc; ++j) {
            argv[j] = argv[j + 1];
        }
        argv[argc - 1] = positional;
        return;
    }
}

int handleArguments(int argc, char* argv[], Options* options) {
    static constexpr const char* OPTSTR = "hl";
    static const utils::getopt::option OPTIONS[] = {
        { "help", utils::getopt::no_argument, 0, 'h' },
        { "license", utils::getopt::no_argument, 0, 'l' },
        { "out", utils::getopt::required_argument, 0, 'o' },
        { "mode", utils::getopt::required_argument, 0, 'm' },
        { "levels", utils::getopt::required_argument, 0, 'n' },
        { "ratio", utils::getopt::required_argument, 0, 'r' },
        { "target-error", utils::getopt::required_argument, 0, 'e' },
        { "cluster-verts", utils::getopt::required_argument, 0, 'v' },
        { "cluster-tris", utils::getopt::required_argument, 0, 't' },
        { "cone-weight", utils::getopt::required_argument, 0, 'w' },
        { "split-charts", utils::getopt::required_argument, 0, 'c' },
        { "group-size", utils::getopt::required_argument, 0, 'g' },
        { "dag-group", utils::getopt::required_argument, 0, 'D' },
        { "tier", utils::getopt::required_argument, 0, 'T' },
        { "target-ratio", utils::getopt::required_argument, 0, 'R' },
        { "write-dag", utils::getopt::required_argument, 0, 'J' },
        { "visibility", utils::getopt::required_argument, 0, 'V' },
        { "attribute-qem", utils::getopt::required_argument, 0, 'a' },
        { "corner-seam", utils::getopt::required_argument, 0, 'C' },
        { "corner-split-uv", utils::getopt::required_argument, 0, 'X' },
        { "page-bytes", utils::getopt::required_argument, 0, 'P' },
        { "error-level", utils::getopt::required_argument, 0, 'K' },
        { "lock-border", utils::getopt::required_argument, 0, 'b' },
        { "quality-debug", utils::getopt::required_argument, 0, 'Q' },
        { "quality-gate", utils::getopt::required_argument, 0, 'G' },
        { "quality-attempts", utils::getopt::required_argument, 0, 'A' },
        { "min-quality", utils::getopt::required_argument, 0, 'q' },
        { "max-normal-error", utils::getopt::required_argument, 0, 'N' },
        { "max-uv-error", utils::getopt::required_argument, 0, 'U' },
        { "dump-obj", utils::getopt::required_argument, 0, 'd' },
        { "dump-format", utils::getopt::required_argument, 0, 'F' },
        { "bake-normal", utils::getopt::required_argument, 0, 'B' },
        { "bake-height", utils::getopt::required_argument, 0, 'Y' },
        { "bake-ao", utils::getopt::required_argument, 0, 'O' },
        { "ao-field", utils::getopt::required_argument, 0, 'Z' },
        { "bake-ao-map", utils::getopt::required_argument, 0, 'M' },
        { "ao-radius", utils::getopt::required_argument, 0, 'W' },
        { "shade-crease", utils::getopt::required_argument, 0, 'H' },
        { "shade-strength", utils::getopt::required_argument, 0, 'S' },
        { "write-json", utils::getopt::required_argument, 0, 'j' },
        { "eye", utils::getopt::required_argument, 0, 'E' },
        { "look-at", utils::getopt::required_argument, 0, 'L' },
        { "fov-y", utils::getopt::required_argument, 0, 'f' },
        { "screen-height", utils::getopt::required_argument, 0, 's' },
        { "threshold-px", utils::getopt::required_argument, 0, 'p' },
        { 0, 0, 0, 0 } // termination of the utils::getopt::option list
    };

    rotatePositionalToEnd(argc, argv, OPTIONS);

    int opt;
    int optionIndex = 0;
    while ((opt = utils::getopt::getopt_long(argc, argv, OPTSTR, OPTIONS, &optionIndex)) >= 0) {
        char const* arg = utils::getopt::optarg;
        switch (opt) {
            case '?':
                std::cerr << "Unknown option. Run with --help for the list." << std::endl;
                return -1;
            case 'h':
                printUsage(argv[0]);
                exit(0);
            case 'l':
                printLicense();
                exit(0);
            case 'o':
                options->outDir = arg;
                break;
            case 'm':
                options->clusterMode = (strcmp(arg, "cluster") == 0);
                options->dagMode = (strcmp(arg, "dag") == 0);
                if (!options->clusterMode && !options->dagMode && strcmp(arg, "chain") != 0) {
                    std::cerr << "Unknown mode '" << arg
                              << "', expected 'chain', 'cluster' or 'dag'" << std::endl;
                    return -1;
                }
                break;
            case 'n':
                options->levels = std::max(1u, uint32_t(atoi(arg)));
                break;
            case 'r':
                options->ratio = float(atof(arg));
                break;
            case 'e':
                options->targetError = float(atof(arg));
                break;
            case 'v':
                options->clusterVertices = uint32_t(atoi(arg));
                break;
            case 't':
                options->clusterTriangles = uint32_t(atoi(arg));
                break;
            case 'w':
                options->coneWeight = float(atof(arg));
                break;
            case 'c':
                options->splitCharts = atoi(arg) != 0;
                break;
            case 'g':
                options->groupSize = std::max(1u, uint32_t(atoi(arg)));
                break;
            case 'D':
                options->dagGroupSize = std::max(2u, uint32_t(atoi(arg)));
                break;
            case 'T':
                options->tierName = arg;
                options->useTier = true;
                options->useTargetRatio = false;
                break;
            case 'R':
                options->targetTriangleRatio = std::clamp(float(atof(arg)), 0.0f, 1.0f);
                options->useTargetRatio = true;
                options->useTier = false;
                break;
            case 'J':
                options->writeDag = atoi(arg) != 0;
                break;
            case 'V':
                options->writeVisibility = atoi(arg) != 0;
                break;
            case 'a':
                options->attributeQem = atoi(arg) != 0;
                break;
            case 'C':
                options->cornerSeam = atoi(arg) != 0;
                break;
            case 'X':
                options->cornerSplitUv = atoi(arg) != 0;
                break;
            case 'P':
                options->streamingPageBytes = std::max(1u, uint32_t(atoi(arg)));
                break;
            case 'K':
                options->errorLevel = atoi(arg);
                break;
            case 'b':
                options->lockBorder = atoi(arg) != 0;
                break;
            case 'Q':
                options->qualityDebug = atoi(arg) != 0;
                break;
            case 'G':
                options->qualityGate = atoi(arg) != 0;
                break;
            case 'A':
                options->qualityAttempts = std::max(1u, uint32_t(atoi(arg)));
                break;
            case 'q':
                options->minTriangleQuality = std::max(0.0f, float(atof(arg)));
                break;
            case 'N':
                options->maxNormalErrorDegrees = std::max(0.0f, float(atof(arg)));
                break;
            case 'U':
                options->maxUvError = std::max(0.0f, float(atof(arg)));
                break;
            case 'd':
                options->dumpObj = atoi(arg) != 0;
                break;
            case 'F':
                options->dumpPly = (strcmp(arg, "ply") == 0);
                if (!options->dumpPly && strcmp(arg, "obj") != 0) {
                    std::cerr << "Unknown dump format '" << arg << "', expected 'obj' or 'ply'"
                              << std::endl;
                    return -1;
                }
                break;
            case 'B':
                options->bakeNormalSize = uint32_t(std::max(0, atoi(arg)));
                break;
            case 'Y':
                options->bakeHeightSize = uint32_t(std::max(0, atoi(arg)));
                break;
            case 'O':
                options->bakeAoSamples = uint32_t(std::clamp(atoi(arg), 0, 4096));
                break;
            case 'Z':
                options->aoFieldSamples = uint32_t(std::clamp(atoi(arg), 0, 4096));
                break;
            case 'M':
                options->bakeAoMapSize = uint32_t(std::clamp(atoi(arg), 0, 4096));
                break;
            case 'W':
                options->aoRadius = std::max(0.0f, float(atof(arg)));
                break;
            case 'H':
                options->shadeCreaseDegrees =
                        std::clamp(float(atof(arg)), 0.0f, 45.0f);
                break;
            case 'S':
                options->shadeStrength = std::clamp(float(atof(arg)), 0.0f, 1.0f);
                break;
            case 'j':
                options->writeJson = atoi(arg) != 0;
                break;
            case 'E':
                if (!parseVec3(arg, &options->eye)) {
                    std::cerr << "Could not parse --eye '" << arg << "', expected x,y,z"
                              << std::endl;
                    return -1;
                }
                options->hasEye = true;
                break;
            case 'L':
                if (!parseVec3(arg, &options->lookAt)) {
                    std::cerr << "Could not parse --look-at '" << arg << "', expected x,y,z"
                              << std::endl;
                    return -1;
                }
                break;
            case 'f':
                options->fovYDegrees = float(atof(arg));
                break;
            case 's':
                options->screenHeight = uint32_t(atoi(arg));
                break;
            case 'p':
                options->thresholdPx = float(atof(arg));
                break;
        }
    }

    return utils::getopt::optind;
}

} // anonymous namespace

int main(int argc, char* argv[]) {
    Options options;

    int const optionIndex = handleArguments(argc, argv, &options);
    if (optionIndex < 0) {
        return 1;
    }

    if (argc - optionIndex < 1) {
        printUsage(argv[0]);
        return 1;
    }
    options.input = argv[optionIndex];

    using clock = std::chrono::steady_clock;
    auto const start = clock::now();
    auto elapsed = [&start]() {
        return std::chrono::duration<double>(clock::now() - start).count();
    };

    printf("ManyMesh geometry optimization layer\n");
    printf("  input: %s\n", options.input.c_str());

    Mesh mesh;
    if (!loadMesh(options.input.c_str(), &mesh)) {
        return 1;
    }
    printf("  loaded: %zu vertices, %zu triangles (%.2fs)\n", mesh.vertexCount(),
            mesh.triangleCount(), elapsed());

    {
        math::float3 lo{};
        math::float3 hi{};
        computeBounds(mesh, &lo, &hi);
        printf("  bounds: (%.2f, %.2f, %.2f) .. (%.2f, %.2f, %.2f)   extent (%.2f, %.2f, %.2f)\n",
                lo.x, lo.y, lo.z, hi.x, hi.y, hi.z, hi.x - lo.x, hi.y - lo.y, hi.z - lo.z);
    }

    std::error_code errorCode;
    std::filesystem::create_directories(options.outDir, errorCode);
    if (errorCode) {
        std::cerr << "Could not create output directory '" << options.outDir
                  << "': " << errorCode.message() << std::endl;
        return 1;
    }
    // The source UV atlas does not depend on the cut, so bake it once before any LOD work.
    bakeAoMap(mesh, options);

    if (options.aoFieldSamples > 0) {
        AmbientOcclusionOptions aoOptions;
        aoOptions.samples = options.aoFieldSamples;
        aoOptions.radius = options.aoRadius;
        AmbientOcclusionResult ao;
        if (!bakeVertexAmbientOcclusion(mesh, mesh, aoOptions, &ao)) {
            std::cerr << "  source AO field bake failed" << std::endl;
        } else {
            mesh.ao = std::move(ao.values);
            printf("  source AO field: %zu vertices, %u samples, radius %.5f%s, mean %.3f, "
                   "min %.3f, %.1f ms\n",
                    ao.bakedVertices, options.aoFieldSamples, ao.radius,
                    options.aoRadius > 0.0f ? "" : " (auto)", ao.mean, ao.min, ao.bakeMs);
        }
    }

    if (!options.clusterMode && !options.dagMode) {
        // ------------------------------------------------------------------------------------
        // Global LOD chain: the classic "distance based LOD" baseline.
        // ------------------------------------------------------------------------------------
        SimplifyOptions simplifyOptions;
        simplifyOptions.levels = options.levels;
        simplifyOptions.ratio = options.ratio;
        simplifyOptions.targetError = options.targetError;
        simplifyOptions.verbose = options.qualityDebug;
        simplifyOptions.qualityGate = options.qualityGate;
        simplifyOptions.qualityAttempts = options.qualityAttempts;
        simplifyOptions.minTriangleQuality = options.minTriangleQuality;
        simplifyOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
        simplifyOptions.maxUvError = options.maxUvError;
        simplifyOptions.attributeQem = options.attributeQem;
        simplifyOptions.cornerSplitDivergentUv = options.cornerSplitUv;

        std::vector<LodLevel> const levels = simplifyChain(mesh, simplifyOptions);
        printf("  simplified chain built (%.2fs)\n", elapsed());

        printChainStats(mesh, levels);
        if (options.bakeNormalSize > 0 || options.bakeHeightSize > 0) {
            std::cerr << "  detail maps are baked for one selected cluster/DAG cut; chain mode "
                         "has no single selected LOD, so --bake-normal/--bake-height were "
                         "ignored" << std::endl;
        }

        if (options.dumpObj) {
            for (size_t l = 0; l < levels.size(); ++l) {
                dumpMesh(mesh, outputFromLevel(levels[l]), options, "lod" + std::to_string(l));
            }
            printf("  wrote %zu mesh files to %s\n", levels.size(), options.outDir.c_str());
        }

        printf("\n  total time: %.2fs\n", elapsed());
        return 0;
    }

    if (options.dagMode) {
        // ------------------------------------------------------------------------------------
        // Hierarchical cluster DAG: build leaf clusters, merge connected neighbours level by
        // level, and select a non-overlapping cut for the requested saving tier.
        // ------------------------------------------------------------------------------------
        SimplifyOptions simplifyOptions;
        simplifyOptions.lockBorder = options.lockBorder;
        simplifyOptions.targetError = options.targetError;
        simplifyOptions.verbose = options.qualityDebug;
        simplifyOptions.qualityGate = options.qualityGate;
        simplifyOptions.qualityAttempts = options.qualityAttempts;
        simplifyOptions.minTriangleQuality = options.minTriangleQuality;
        simplifyOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
        simplifyOptions.maxUvError = options.maxUvError;
        simplifyOptions.attributeQem = options.attributeQem;
        simplifyOptions.cornerSimplify = options.cornerSeam;
        simplifyOptions.cornerSplitDivergentUv = options.cornerSplitUv;

        LodGraphOptions graphOptions;
        graphOptions.clusterize.maxVertices = options.clusterVertices;
        graphOptions.clusterize.maxTriangles = options.clusterTriangles;
        graphOptions.clusterize.coneWeight = options.coneWeight;
        graphOptions.clusterize.splitCharts = options.splitCharts;
        graphOptions.clustersPerNode = options.dagGroupSize;
        graphOptions.levels = options.levels;
        graphOptions.ratio = options.ratio;
        graphOptions.simplify = simplifyOptions;

        LodGraphBuildStats buildStats;
        LodGraph const graph = buildLodGraph(mesh, graphOptions, &buildStats);
        Mesh dagMesh = mesh;
        appendGeneratedVertices(&dagMesh, graph.generatedVertices);
        printf("  DAG built: %zu nodes, %u levels (%.2fs)\n", graph.nodes.size(), graph.levelCount,
                elapsed());
        printf("  vertices: %u source + %zu generated = %u total\n", graph.sourceVertexCount(),
                graph.generatedVertices.size(), graph.vertexCount);
        if (!graph.generatedVertices.empty()) {
            float minAO = 1.0f;
            float maxAO = 0.0f;
            float sumAO = 0.0f;
            for (GeneratedVertex const& vertex: graph.generatedVertices) {
                minAO = std::min(minAO, vertex.ao);
                maxAO = std::max(maxAO, vertex.ao);
                sumAO += vertex.ao;
            }
            printf("  generated AO: %.3f .. %.3f (%.3f mean)%s\n", minAO, maxAO,
                    sumAO / float(graph.generatedVertices.size()),
                    options.aoFieldSamples > 0
                            ? ""
                            : " [no source AO field; all vertices unoccluded]");
        }
        printf("  build phases: clusterize %.3fs, leaf setup %.3fs, cluster chains %.3fs, "
               "groups %.3fs (simplify %.3fs)\n",
                buildStats.clusterizeSeconds, buildStats.leafSetupSeconds,
                buildStats.clusterChainSeconds, buildStats.groupBuildSeconds,
                buildStats.groupSimplifySeconds);
        printf("  simplify calls: cluster %llu accepted %llu attempts %llu; "
               "group %llu accepted %llu attempts %llu; seam-locked vertex uses %llu\n",
                (unsigned long long) buildStats.clusterSimplifyCalls,
                (unsigned long long) buildStats.clusterSimplifyAccepted,
                (unsigned long long) buildStats.clusterSimplifyAttempts,
                (unsigned long long) buildStats.groupSimplifyCalls,
                (unsigned long long) buildStats.groupSimplifyAccepted,
                (unsigned long long) buildStats.groupSimplifyAttempts,
                (unsigned long long) buildStats.seamLockedVertices);
        auto const printSimplifyProfile = [](char const* name, SimplifyProfile const& profile) {
            printf("  %s simplify profile: attribute-qem %.3fs, corner %.3fs, meshopt %.3fs, "
                   "gate %.3fs, "
                   "boundary %.3fs, lock-mask %.3fs (build %.3fs) | calls %llu attempts %llu, "
                   "attribute candidates %llu, corner candidates %llu, meshopt candidates %llu, "
                   "accepted %llu, rejected: topology %llu geometry %llu attributes %llu "
                   "boundary %llu locked %llu none %llu\n",
                    name, profile.attributeQemSeconds, profile.cornerSeconds,
                    profile.meshoptSeconds, profile.candidateGateSeconds,
                    profile.boundaryCheckSeconds, profile.lockedMaskSeconds,
                    profile.lockedMaskBuildSeconds, (unsigned long long) profile.calls,
                    (unsigned long long) profile.attempts,
                    (unsigned long long) profile.attributeCandidates,
                    (unsigned long long) profile.cornerCandidates,
                    (unsigned long long) profile.meshoptCandidates,
                    (unsigned long long) profile.accepted,
                    (unsigned long long) profile.rejectedTopology,
                    (unsigned long long) profile.rejectedGeometry,
                    (unsigned long long) profile.rejectedAttributes,
                    (unsigned long long) profile.rejectedBoundary,
                    (unsigned long long) profile.rejectedLocked,
                    (unsigned long long) profile.rejectedNotSimplified);
            printf("  %s gate detail: cleanup %.3fs, sliver %.3fs, topology %.3fs, "
                   "welded-topology %.3fs, error %.3fs\n",
                    name, profile.candidateCleanupSeconds, profile.candidateSliverSeconds,
                    profile.candidateTopologySeconds, profile.weldedTopologySeconds,
                    profile.candidateErrorSeconds);
            printf("  %s extended-mesh: %.3fs, copies %llu\n", name,
                    profile.extendedMeshSeconds,
                    (unsigned long long) profile.extendedMeshCopies);
            double const microsecondsPerEvaluation =
                    profile.cornerEvaluations != 0 ? profile.cornerEvaluateSeconds * 1e6 /
                                                             double(profile.cornerEvaluations)
                                                   : 0.0;
            printf("  %s corner detail: setup %.3fs, evaluate %.3fs (%.0f evals, %.2f us/eval), "
                   "topology %.3fs, target %.3fs (%llu placements), apply %.3fs (%llu applied)\n",
                    name, profile.cornerSetupSeconds, profile.cornerEvaluateSeconds,
                    double(profile.cornerEvaluations), microsecondsPerEvaluation,
                    profile.cornerEvaluateTopologySeconds, profile.cornerEvaluateTargetSeconds,
                    (unsigned long long) profile.cornerPlacementTests, profile.cornerApplySeconds,
                    (unsigned long long) profile.cornerApplied);
            printf("  %s corner topology: neighbor %.3fs, triangles %.3fs, local-triangles "
                   "%.3fs, local-edges %.3fs\n",
                    name, profile.cornerTopologyNeighborSeconds,
                    profile.cornerTopologyTriangleSeconds,
                    profile.cornerTopologyLocalTriangleSeconds,
                    profile.cornerTopologyLocalEdgeSeconds);
        };
        printSimplifyProfile("cluster", buildStats.clusterSimplify);
        printSimplifyProfile("group", buildStats.groupSimplify);
        if (graph.nodes.empty()) {
            std::cerr << "The DAG is empty; nothing to select." << std::endl;
            return 1;
        }

        LodTier tier = LodTier::Balanced;
        if (!parseTier(options.tierName, &tier)) {
            std::cerr << "Unknown tier '" << options.tierName
                      << "', expected 'maximum', 'balanced' or 'aggressive'" << std::endl;
            return 1;
        }
        LodTierProfile const profile = lodTierProfile(tier);
        ViewCamera const camera = makeCamera(options, mesh);
        LodGraphSelection const selection =
                options.useTargetRatio
                        ? selectLodGraphAtRatio(graph, camera, options.targetTriangleRatio,
                                  std::numeric_limits<float>::infinity())
                        : selectLodGraphTier(graph, camera, tier);
        LodGraphCompactOptions compactOptions;
        compactOptions.compactSourceVertices = true;
        LodGraphCutGeometry const compacted = compactLodSelection(graph, selection, compactOptions);
        printf("  cut vertices: %u of %u source + %zu of %zu generated = %u total "
               "(%.1f%% of the %u-vertex global buffer, %zu KiB generated tail)\n",
                compacted.sourceVertexCount, graph.sourceVertexCount(),
                compacted.generatedVertices.size(), graph.generatedVertices.size(),
                compacted.vertexCount,
                graph.vertexCount > 0
                        ? 100.0 * double(compacted.vertexCount) / double(graph.vertexCount)
                        : 0.0,
                graph.vertexCount, compacted.generatedVertices.size() * 8u * sizeof(float) / 1024u);
        printDagStats(dagMesh, graph, selection, camera,
                options.useTargetRatio ? std::numeric_limits<float>::infinity()
                                       : profile.maxScreenErrorPx);

        if (options.dumpObj) {
            GeometryOutput const geometry = outputFromDagSelection(selection);
            std::vector<float> aoValues;
            std::vector<math::float3> bentValues;
            if (options.bakeAoSamples > 0) {
                AmbientOcclusionOptions aoOptions;
                aoOptions.samples = options.bakeAoSamples;
                aoOptions.radius = options.aoRadius;
                AmbientOcclusionResult ao;
                if (bakeVertexAmbientOcclusion(mesh, dagMesh, aoOptions, &ao)) {
                    aoValues = ao.values;
                    bentValues = ao.bentNormals;
                    printf("  baked source AO: %zu vertices, %u samples, radius %.5f%s, "
                           "mean %.3f, min %.3f, bent %.1f/%.1f deg, %.1f ms\n",
                            ao.bakedVertices, options.bakeAoSamples, ao.radius,
                            options.aoRadius > 0.0f ? "" : " (auto)", ao.mean, ao.min,
                            ao.meanBendDegrees, ao.maxBendDegrees, ao.bakeMs);
                    if (!options.dumpPly) {
                        std::cerr << "  AO vertex colors are written to PLY only; use "
                                     "--dump-format ply to keep them" << std::endl;
                    }
                } else {
                    std::cerr << "  source AO bake failed" << std::endl;
                }
            }
            std::string const selectedPath =
                    join(options.outDir, options.dumpPly ? "selected.ply" : "selected.obj");
            writeGeometry(dagMesh, geometry, selectedPath.c_str(), options,
                    aoValues.empty() ? nullptr : &aoValues,
                    bentValues.empty() ? nullptr : &bentValues);
            printf("  wrote %s\n", selectedPath.c_str());
        }

        bakeDetailNormal(mesh, dagMesh, outputFromDagSelection(selection).indices, options);
        bakeDetailHeight(mesh, dagMesh, outputFromDagSelection(selection).indices, options);

        std::vector<uint8_t> const blob = serializeLodGraph(graph);
        std::string const dagPath = join(options.outDir, "lod_graph.mmb");
        if (options.writeDag) {
            if (!writeLodGraphFile(graph, dagPath.c_str())) {
                std::cerr << "Could not write '" << dagPath << "'" << std::endl;
                return 1;
            }
            printf("  wrote %s (%.2f MiB)\n", dagPath.c_str(),
                    double(blob.size()) / (1024.0 * 1024.0));
        }
        if (options.writeJson) {
            std::string const jsonPath = join(options.outDir, "lod_graph.json");
            writeDagJson(dagMesh, graph, selection, options, maxScreenError(selection),
                    jsonPath.c_str());
            printf("  wrote %s\n", jsonPath.c_str());
        }

        auto reportStreaming = [&](StreamingLodGraph const& streaming) {
            if (!streaming.valid()) {
                printf("  streaming: graph could not be opened\n");
                return;
            }
            std::vector<LodStreamingPage> const pages =
                    streaming.planPages(options.streamingPageBytes);
            size_t const budget =
                    std::max<size_t>(size_t(options.streamingPageBytes) * 16, 1024u * 1024u);
            LodStreamingCache cache(&streaming, budget, options.streamingPageBytes);
            bool const prepared = cache.prepare(selection);
            LodStreamingCache::Stats const stats = cache.stats();
            printf("  streaming: %s, %zu pages, queue %s, resident %zu pages / %zu bytes, "
                   "hits %llu misses %llu evictions %llu\n",
                    streaming.fileBacked() ? "file-backed" : "memory-backed", pages.size(),
                    prepared ? "prepared" : "incomplete", stats.residentPages, stats.residentBytes,
                    (unsigned long long) stats.pageHits, (unsigned long long) stats.pageMisses,
                    (unsigned long long) stats.evictions);
        };
        if (options.writeDag) {
            StreamingLodGraph const streaming(dagPath);
            reportStreaming(streaming);
        } else {
            StreamingLodGraph const streaming(blob);
            reportStreaming(streaming);
        }

        if (options.writeVisibility) {
            GpuLodBuffer const gpu = flattenLodGraph(graph);
            std::vector<GpuDrawIndexedIndirectCommand> const draws =
                    buildIndirectDraws(gpu, selection);
            VisibilityBuffer const visibility =
                    rasterizeVisibility(dagMesh, gpu, selection, camera);
            std::string const visibilityPath = join(options.outDir, "visibility.pgm");
            writeVisibilityBufferPgm(visibility, visibilityPath.c_str());
            printf("  wrote %s (%u covered pixels, %zu indirect draws)\n", visibilityPath.c_str(),
                    visibility.coveredPixels, draws.size());
        }

        printf("\n  total time: %.2fs\n", elapsed());
        return 0;
    }

    // ----------------------------------------------------------------------------------------
    // Per-cluster pipeline: clusterize, simplify each cluster independently, then pick a
    // level per cluster for the requested view.
    // ----------------------------------------------------------------------------------------
    ClusterizeOptions clusterizeOptions;
    clusterizeOptions.maxVertices = options.clusterVertices;
    clusterizeOptions.maxTriangles = options.clusterTriangles;
    clusterizeOptions.coneWeight = options.coneWeight;
    clusterizeOptions.splitCharts = options.splitCharts;

    ClusterSet clusters = clusterize(mesh, clusterizeOptions);
    printf("  clustered: %zu clusters (%.2fs)\n", clusters.clusters.size(), elapsed());

    if (options.groupSize > 1) {
        // Merging neighbours before simplifying is what lets the border lock only apply to
        // the group's outer boundary, so the members' shared edges become collapsible.
        GroupOptions groupOptions;
        groupOptions.clustersPerGroup = options.groupSize;
        clusters = groupClusters(clusters, groupOptions);
        printf("  grouped:   %zu simplification units of up to %u clusters\n",
                clusters.clusters.size(), options.groupSize);
    }

    SimplifyOptions simplifyOptions;
    simplifyOptions.levels = options.levels;
    simplifyOptions.ratio = options.ratio;
    simplifyOptions.targetError = options.targetError;
    simplifyOptions.lockBorder = options.lockBorder;
    simplifyOptions.verbose = options.qualityDebug;
    simplifyOptions.qualityGate = options.qualityGate;
    simplifyOptions.qualityAttempts = options.qualityAttempts;
    simplifyOptions.minTriangleQuality = options.minTriangleQuality;
    simplifyOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
    simplifyOptions.maxUvError = options.maxUvError;
    simplifyOptions.attributeQem = options.attributeQem;
    simplifyOptions.cornerSplitDivergentUv = options.cornerSplitUv;

    std::vector<ClusterLods> const lods = simplifyClusters(mesh, clusters, simplifyOptions);
    printf("  per-cluster LOD built (%.2fs)\n", elapsed());

    printClusterStats(clusters, lods);

    if (options.writeJson) {
        std::string const jsonPath = join(options.outDir, "clusters.json");
        writeJson(mesh, clusters, lods, options, jsonPath.c_str());
        printf("  wrote %s\n", jsonPath.c_str());
    }

    if (options.dumpObj) {
        for (uint32_t l = 0; l < options.levels; ++l) {
            GeometryOutput const geometry = gatherLevel(lods, l);
            if (geometry.indices.empty()) {
                break;
            }
            dumpMesh(mesh, geometry, options, "lod" + std::to_string(l));
        }
        printf("  wrote per-level mesh files to %s\n", options.outDir.c_str());
    }

    ViewCamera const camera = makeCamera(options, mesh);
    Selection const selection =
            options.errorLevel >= 0
                    ? selectClustersAtLevel(clusters.clusters, lods, camera,
                              uint32_t(options.errorLevel))
                    : selectClusters(clusters.clusters, lods, camera, options.thresholdPx);
    printSelectionStats(selection, camera, options.thresholdPx);

    if (options.dumpObj) {
        GeometryOutput const geometry = gatherSelection(lods, selection);
        std::vector<float> aoValues;
        std::vector<math::float3> bentValues;
        if (options.bakeAoSamples > 0) {
            AmbientOcclusionOptions aoOptions;
            aoOptions.samples = options.bakeAoSamples;
            aoOptions.radius = options.aoRadius;
            AmbientOcclusionResult ao;
            if (bakeVertexAmbientOcclusion(mesh, mesh, aoOptions, &ao)) {
                aoValues = ao.values;
                bentValues = ao.bentNormals;
                printf("  baked source AO: %zu vertices, %u samples, radius %.5f%s, mean %.3f, "
                       "min %.3f, bent %.1f/%.1f deg, %.1f ms\n",
                        ao.bakedVertices, options.bakeAoSamples, ao.radius,
                        options.aoRadius > 0.0f ? "" : " (auto)", ao.mean, ao.min,
                        ao.meanBendDegrees, ao.maxBendDegrees, ao.bakeMs);
            } else {
                std::cerr << "  source AO bake failed" << std::endl;
            }
        }
        std::string const selectedPath =
                join(options.outDir, options.dumpPly ? "selected.ply" : "selected.obj");
        writeGeometry(mesh, geometry, selectedPath.c_str(), options,
                aoValues.empty() ? nullptr : &aoValues,
                bentValues.empty() ? nullptr : &bentValues);
        printf("  wrote %s\n", selectedPath.c_str());
    }

    GeometryOutput const detailGeometry = gatherSelection(lods, selection);
    bakeDetailNormal(mesh, mesh, detailGeometry.indices, options);
    bakeDetailHeight(mesh, mesh, detailGeometry.indices, options);

    std::string const errorMapPath = join(options.outDir, "error_map.pgm");
    writeErrorMap(mesh, clusters.clusters, lods, selection, camera, options.thresholdPx,
            errorMapPath.c_str());
    printf("  wrote %s (screen space geometry error, white = at the pixel budget)\n",
            errorMapPath.c_str());

    printf("\n  total time: %.2fs\n", elapsed());
    return 0;
}
