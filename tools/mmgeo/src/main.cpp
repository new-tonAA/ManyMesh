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

#include <manymesh/Clusterizer.h>
#include <manymesh/GeometryError.h>
#include <manymesh/GpuLod.h>
#include <manymesh/Grouper.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>
#include <manymesh/Simplifier.h>
#include <manymesh/Streaming.h>
#include <manymesh/VisibilityBuffer.h>

#include <math/vec3.h>

#include <utils/getopt.h>

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <chrono>
#include <algorithm>
#include <array>
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
    for (char c : text) {
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
    unsigned int const flags = aiProcess_Triangulate
            | aiProcess_JoinIdenticalVertices
            | aiProcess_PreTransformVertices;

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
        std::vector<uint32_t> const* submeshIds = nullptr) {
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
    file << "ply\nformat binary_little_endian 1.0\n";
    file << "element vertex " << vertices.size() << "\n";
    file << "property float x\nproperty float y\nproperty float z\n";
    if (hasNormals) {
        file << "property float nx\nproperty float ny\nproperty float nz\n";
    }
    if (hasUVs) {
        file << "property float s\nproperty float t\n";
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

    for (uint32_t vertex : vertices) {
        file.write(reinterpret_cast<char const*>(&mesh.positions[vertex].x), sizeof(float) * 3);
        if (hasNormals) {
            file.write(reinterpret_cast<char const*>(&mesh.normals[vertex].x), sizeof(float) * 3);
        }
        if (hasUVs) {
            file.write(reinterpret_cast<char const*>(&mesh.uvs[vertex].x), sizeof(float) * 2);
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
    for (math::float3 const& p : mesh.positions) {
        file << "v " << p.x << ' ' << p.y << ' ' << p.z << '\n';
    }
    bool const hasNormals = mesh.normals.size() == mesh.positions.size();
    bool const hasUVs = mesh.uvs.size() == mesh.positions.size();
    if (hasUVs) {
        for (math::float2 const& uv : mesh.uvs) {
            file << "vt " << uv.x << ' ' << uv.y << '\n';
        }
    }
    if (hasNormals) {
        for (math::float3 const& n : mesh.normals) {
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
            file << "f " << a << "//" << a << ' ' << b << "//" << b << ' ' << c << "//" << c << '\n';
        } else {
            file << "f " << a << ' ' << b << ' ' << c << '\n';
        }
    }

    if (hasMaterials) {
        std::ofstream mtl(std::string(path) + ".mtl");
        if (mtl) {
            std::set<uint32_t> unique(materialIds->begin(), materialIds->end());
            for (uint32_t material : unique) {
                mtl << "newmtl mm_material_" << material << "\n"
                    << "Kd 0.8 0.8 0.8\n"
                    << "Ks 0.0 0.0 0.0\n"
                    << "d 1.0\n"
                    << "illum 2\n\n";
            }
        }
    }
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
    destination->indices.insert(destination->indices.end(),
            source.indices.begin(), source.indices.end());
    destination->materialIds.insert(destination->materialIds.end(),
            source.materialIds.begin(), source.materialIds.end());
    destination->submeshIds.insert(destination->submeshIds.end(),
            source.submeshIds.begin(), source.submeshIds.end());
}

// Writes one mesh to the output directory, in whichever format was asked for.
void dumpMesh(Mesh const& mesh, GeometryOutput const& geometry, Options const& options,
        std::string const& stem) {
    std::string const path = join(options.outDir, stem + (options.dumpPly ? ".ply" : ".obj"));
    if (options.dumpPly) {
        writePly(mesh, geometry.indices, path.c_str(), &geometry.materialIds,
                &geometry.submeshIds);
    } else {
        writeObj(mesh, geometry.indices, path.c_str(), &geometry.materialIds,
                &geometry.submeshIds);
    }
}

// Concatenates the given level of every cluster, clamped to the coarsest level each cluster
// actually has. Used to dump a "whole mesh at level N" OBJ in per-cluster mode.
GeometryOutput gatherLevel(std::vector<ClusterLods> const& lods, uint32_t level) {
    GeometryOutput result;
    for (ClusterLods const& clusterLods : lods) {
        if (clusterLods.levels.empty()) {
            continue;
        }
        uint32_t const clamped = std::min(level, uint32_t(clusterLods.levels.size() - 1));
        appendOutput(&result, outputFromLevel(clusterLods.levels[clamped]));
    }
    return result;
}

GeometryOutput gatherSelection(std::vector<ClusterLods> const& lods,
        Selection const& selection) {
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
            ? double(selection.selectedTriangles)
                    / double(graph.baseTriangles - selection.culledTriangles)
            : 1.0;
    file << "{\n";
    file << "  \"source\": \"" << jsonEscape(options.input) << "\",\n";
    file << "  \"vertices\": " << mesh.vertexCount() << ",\n";
    file << "  \"triangles\": " << mesh.triangleCount() << ",\n";
    file << "  \"nodes\": " << graph.nodes.size() << ",\n";
    file << "  \"levels\": " << graph.levelCount << ",\n";
    file << "  \"clustersPerNode\": " << options.dagGroupSize << ",\n";
    file << "  \"ratio\": " << options.ratio << ",\n";
    file << "  \"attributeQem\": " << (options.attributeQem ? "true" : "false") << ",\n";
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
        file << "    {\"id\":" << n << ",\"level\":" << node.level
             << ",\"parent\":" << node.parent
             << ",\"children\":[";
        for (size_t i = 0; i < node.children.size(); ++i) {
            file << (i ? "," : "") << node.children[i];
        }
        file << "],\"tri\":" << node.triangleCount()
             << ",\"baseTri\":" << node.baseTriangles
             << ",\"selfError\":" << node.selfError
             << ",\"accumulatedError\":" << node.accumulatedError
             << ",\"material\":" << node.materialId
             << ",\"submesh\":" << node.submeshId
             << ",\"simplified\":" << (node.simplified ? "true" : "false")
             << ",\"bounds\":{\"center\":[" << node.bounds.center.x << ','
             << node.bounds.center.y << ',' << node.bounds.center.z
             << "],\"radius\":" << node.bounds.radius << "}"
             << ",\"boundaryEdges\":" << node.topology.boundaryEdges
             << ",\"nonManifoldEdges\":" << node.topology.nonManifoldEdges
             << ",\"duplicateTriangles\":" << node.topology.duplicateTriangles
             << ",\"degenerateTriangles\":" << node.topology.degenerateTriangles
             << ",\"minQuality\":" << node.topology.minTriangleQuality
             << ",\"normalErrorDeg\":"
             << node.attributes.maxNormalErrorRadians * 57.2957795f
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
        file << "],\"material\":" << cluster.materialId
             << ",\"submesh\":" << cluster.submeshId;
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
    for (ClusterLods const& clusterLods : lods) {
        maxLevels = std::max(maxLevels, clusterLods.levels.size());
        totalError += clusterLods.levels.size();
    }

    printf("\n");
    printf("  clusters: %zu   average levels per cluster: %.2f   coarsest level seen: %zu\n",
            clusters.clusters.size(),
            lods.empty() ? 0.0 : totalError / double(lods.size()), maxLevels);

    // The mean is weighted by triangles, because a unit's error only matters in proportion to
    // how much geometry carries it. Reporting the maximum alone is misleading: it is decided
    // by a single worst unit and swings wildly between configurations.
    printf("  %-6s %14s %14s %14s %14s\n",
            "level", "triangles", "units", "mean w.error", "max w.error");
    for (size_t l = 0; l < maxLevels; ++l) {
        uint64_t triangles = 0;
        size_t count = 0;
        float worst = 0.0f;
        double weightedError = 0.0;
        uint64_t weightedTriangles = 0;
        for (ClusterLods const& clusterLods : lods) {
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
        double const mean = weightedTriangles > 0
                ? weightedError / double(weightedTriangles)
                : 0.0;
        printf("  %-6zu %14llu %14zu %14.6f %14.6f\n", l, (unsigned long long)triangles, count,
                mean, worst);
    }
}

void printSelectionStats(Selection const& selection, ViewCamera const& camera, float thresholdPx) {
    printf("\n  camera: eye(%.3f, %.3f, %.3f) fovY(%.1f deg) screen(%u x %u) budget %.2f px\n",
            camera.eye.x, camera.eye.y, camera.eye.z,
            camera.fovY * 180.0f / 3.14159265358979323846f,
            camera.screenWidth, camera.screenHeight, thresholdPx);

    printf("  %-6s %14s %14s\n", "level", "clusters", "triangles");
    for (size_t l = 0; l < selection.clustersPerLevel.size(); ++l) {
        printf("  %-6zu %14u %14llu\n", l, selection.clustersPerLevel[l],
                (unsigned long long)selection.trianglesPerLevel[l]);
    }

    double const ratio = selection.baseTriangles > 0
            ? 100.0 * double(selection.selectedTriangles) / double(selection.baseTriangles)
            : 0.0;
    printf("  drawn: %llu of %llu triangles (%.1f%%)\n",
            (unsigned long long)selection.selectedTriangles,
            (unsigned long long)selection.baseTriangles, ratio);
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
    for (float error : selection.screenErrorPerNode) {
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
            camera.fovY * 180.0f / 3.14159265358979323846f,
            camera.screenWidth, camera.screenHeight, requestedError);
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
            (unsigned long long) selection.selectedTriangles,
            (unsigned long long) visibleBase, ratio, selection.nodes.size());
    printf("  frustum culled: %llu of %llu triangles (%.2f%%)\n",
            (unsigned long long) selection.culledTriangles,
            (unsigned long long) graph.baseTriangles,
            graph.baseTriangles > 0
                    ? 100.0 * double(selection.culledTriangles) / double(graph.baseTriangles)
                    : 0.0);
    printf("  worst selected screen error: %.4f px\n", maxScreenError(selection));
    TopologyStats const baseTopology = measureTopology(mesh, mesh.indices);
    printf("  base topology: boundary %llu, non-manifold %llu, duplicates %llu, "
           "degenerate %llu, flipped %llu, min quality %.4f\n",
            (unsigned long long) baseTopology.boundaryEdges,
            (unsigned long long) baseTopology.nonManifoldEdges,
            (unsigned long long) baseTopology.duplicateTriangles,
            (unsigned long long) baseTopology.degenerateTriangles,
            (unsigned long long) baseTopology.flippedTriangles,
            baseTopology.minTriangleQuality);
    TopologyStats const topology = measureTopology(mesh, selection.indices);
    printf("  selected topology: boundary %llu, non-manifold %llu, duplicates %llu, "
           "degenerate %llu, flipped %llu, min quality %.4f\n",
            (unsigned long long) topology.boundaryEdges,
            (unsigned long long) topology.nonManifoldEdges,
            (unsigned long long) topology.duplicateTriangles,
            (unsigned long long) topology.degenerateTriangles,
            (unsigned long long) topology.flippedTriangles,
            topology.minTriangleQuality);

    if (topology.boundaryEdges > baseTopology.boundaryEdges
            || topology.nonManifoldEdges > baseTopology.nonManifoldEdges) {
        // Diagnostics for cross-node seams: print the first few offending edges together with
        // the DAG nodes that own them.
        std::map<std::pair<uint32_t, uint32_t>, std::vector<uint32_t>> edgeNodes;
        std::map<std::pair<uint32_t, uint32_t>, uint32_t> edgeUse;
        std::map<std::pair<uint32_t, uint32_t>, uint32_t> baseEdgeUse;
        std::set<std::array<uint32_t, 3>> keptTriangles;
        for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
            uint32_t const v[3] = {
                mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2] };
            for (int e = 0; e < 3; ++e) {
                baseEdgeUse[{ std::min(v[e], v[(e + 1) % 3]),
                        std::max(v[e], v[(e + 1) % 3]) }] += 1;
            }
        }
        for (size_t i = 0; i + 2 < selection.indices.size(); i += 3) {
            uint32_t const v[3] = {
                selection.indices[i], selection.indices[i + 1], selection.indices[i + 2] };
            std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
            std::sort(key.begin(), key.end());
            keptTriangles.insert(key);
            for (int e = 0; e < 3; ++e) {
                std::pair<uint32_t, uint32_t> const edge = {
                    std::min(v[e], v[(e + 1) % 3]), std::max(v[e], v[(e + 1) % 3]) };
                edgeUse[edge] += 1;
            }
        }
        for (uint32_t nodeId : selection.nodes) {
            LodGraphNode const& node = graph.nodes[nodeId];
            for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                uint32_t const v[3] = {
                    node.indices[i], node.indices[i + 1], node.indices[i + 2] };
                std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
                std::sort(key.begin(), key.end());
                if (keptTriangles.count(key) == 0) {
                    continue;
                }
                for (int e = 0; e < 3; ++e) {
                    std::pair<uint32_t, uint32_t> const edge = {
                        std::min(v[e], v[(e + 1) % 3]), std::max(v[e], v[(e + 1) % 3]) };
                    auto& owners = edgeNodes[edge];
                    if (std::find(owners.begin(), owners.end(), nodeId) == owners.end()) {
                        owners.push_back(nodeId);
                    }
                }
            }
        }
        int printed = 0;
        for (auto const& [edge, count] : edgeUse) {
            bool const newBoundary = count == 1
                    && (baseEdgeUse.count(edge) == 0 || baseEdgeUse[edge] != 1);
            if ((newBoundary || count > 2) && printed < 12) {
                printf("  bad edge (%u,%u) use=%u nodes=", edge.first, edge.second, count);
                for (uint32_t owner : edgeNodes[edge]) {
                    printf("%u ", owner);
                }
                printf("\n");
                for (uint32_t owner : edgeNodes[edge]) {
                    LodGraphNode const& node = graph.nodes[owner];
                    for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                        uint32_t const v[3] = {
                            node.indices[i], node.indices[i + 1], node.indices[i + 2] };
                        std::array<uint32_t, 3> key = { v[0], v[1], v[2] };
                        std::sort(key.begin(), key.end());
                        if (keptTriangles.count(key) == 0) {
                            continue;
                        }
                        bool hasA = v[0] == edge.first || v[1] == edge.first || v[2] == edge.first;
                        bool hasB = v[0] == edge.second || v[1] == edge.second
                                || v[2] == edge.second;
                        if (hasA && hasB) {
                            printf("    node %u tri %u %u %u\n", owner, v[0], v[1], v[2]);
                        }
                    }
                }
                printf("    base use=%u leaves=", baseEdgeUse.count(edge) ? baseEdgeUse[edge] : 0u);
                for (uint32_t leaf : graph.leaves) {
                    LodGraphNode const& node = graph.nodes[leaf];
                    uint32_t use = 0;
                    for (size_t i = 0; i + 2 < node.indices.size(); i += 3) {
                        uint32_t const v[3] = {
                            node.indices[i], node.indices[i + 1], node.indices[i + 2] };
                        for (int e = 0; e < 3; ++e) {
                            std::pair<uint32_t, uint32_t> const pe = {
                                std::min(v[e], v[(e + 1) % 3]),
                                std::max(v[e], v[(e + 1) % 3]) };
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
        return false;  // the only short options here, -h and -l, are flags
    }
    if (strchr(arg + 2, '=') != nullptr) {
        return false;  // --name=value carries its own
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
        { "write-json", utils::getopt::required_argument, 0, 'j' },
        { "eye", utils::getopt::required_argument, 0, 'E' },
        { "look-at", utils::getopt::required_argument, 0, 'L' },
        { "fov-y", utils::getopt::required_argument, 0, 'f' },
        { "screen-height", utils::getopt::required_argument, 0, 's' },
        { "threshold-px", utils::getopt::required_argument, 0, 'p' },
        { 0, 0, 0, 0 }  // termination of the utils::getopt::option list
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
                lo.x, lo.y, lo.z, hi.x, hi.y, hi.z,
                hi.x - lo.x, hi.y - lo.y, hi.z - lo.z);
    }

    std::error_code errorCode;
    std::filesystem::create_directories(options.outDir, errorCode);
    if (errorCode) {
        std::cerr << "Could not create output directory '" << options.outDir << "': "
                  << errorCode.message() << std::endl;
        return 1;
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

        std::vector<LodLevel> const levels = simplifyChain(mesh, simplifyOptions);
        printf("  simplified chain built (%.2fs)\n", elapsed());

        printChainStats(mesh, levels);

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
        simplifyOptions.verbose = options.qualityDebug;
        simplifyOptions.qualityGate = options.qualityGate;
        simplifyOptions.qualityAttempts = options.qualityAttempts;
        simplifyOptions.minTriangleQuality = options.minTriangleQuality;
        simplifyOptions.maxNormalErrorDegrees = options.maxNormalErrorDegrees;
        simplifyOptions.maxUvError = options.maxUvError;
        simplifyOptions.attributeQem = options.attributeQem;

        LodGraphOptions graphOptions;
        graphOptions.clusterize.maxVertices = options.clusterVertices;
        graphOptions.clusterize.maxTriangles = options.clusterTriangles;
        graphOptions.clusterize.coneWeight = options.coneWeight;
        graphOptions.clusterize.splitCharts = options.splitCharts;
        graphOptions.clustersPerNode = options.dagGroupSize;
        graphOptions.levels = options.levels;
        graphOptions.ratio = options.ratio;
        graphOptions.simplify = simplifyOptions;

        LodGraph const graph = buildLodGraph(mesh, graphOptions);
        printf("  DAG built: %zu nodes, %u levels (%.2fs)\n", graph.nodes.size(),
                graph.levelCount, elapsed());
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
        LodGraphSelection const selection = options.useTargetRatio
                ? selectLodGraphAtRatio(graph, camera, options.targetTriangleRatio,
                        std::numeric_limits<float>::infinity())
                : selectLodGraphTier(graph, camera, tier);
        printDagStats(mesh, graph, selection, camera,
                options.useTargetRatio ? std::numeric_limits<float>::infinity()
                                       : profile.maxScreenErrorPx);

        if (options.dumpObj) {
            GeometryOutput const geometry = outputFromDagSelection(selection);
            std::string const selectedPath = join(options.outDir,
                    options.dumpPly ? "selected.ply" : "selected.obj");
            if (options.dumpPly) {
                writePly(mesh, geometry.indices, selectedPath.c_str(), &geometry.materialIds,
                        &geometry.submeshIds);
            } else {
                writeObj(mesh, geometry.indices, selectedPath.c_str(), &geometry.materialIds,
                        &geometry.submeshIds);
            }
            printf("  wrote %s\n", selectedPath.c_str());
        }

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
            writeDagJson(mesh, graph, selection, options, maxScreenError(selection),
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
            size_t const budget = std::max<size_t>(
                    size_t(options.streamingPageBytes) * 16, 1024u * 1024u);
            LodStreamingCache cache(&streaming, budget, options.streamingPageBytes);
            bool const prepared = cache.prepare(selection);
            LodStreamingCache::Stats const stats = cache.stats();
            printf("  streaming: %s, %zu pages, queue %s, resident %zu pages / %zu bytes, "
                   "hits %llu misses %llu evictions %llu\n",
                    streaming.fileBacked() ? "file-backed" : "memory-backed", pages.size(),
                    prepared ? "prepared" : "incomplete", stats.residentPages,
                    stats.residentBytes, (unsigned long long) stats.pageHits,
                    (unsigned long long) stats.pageMisses,
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
            VisibilityBuffer const visibility = rasterizeVisibility(mesh, gpu, selection, camera);
            std::string const visibilityPath = join(options.outDir, "visibility.pgm");
            writeVisibilityBufferPgm(visibility, visibilityPath.c_str());
            printf("  wrote %s (%u covered pixels, %zu indirect draws)\n",
                    visibilityPath.c_str(), visibility.coveredPixels, draws.size());
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
    Selection const selection = options.errorLevel >= 0
            ? selectClustersAtLevel(clusters.clusters, lods, camera, uint32_t(options.errorLevel))
            : selectClusters(clusters.clusters, lods, camera, options.thresholdPx);
    printSelectionStats(selection, camera, options.thresholdPx);

    if (options.dumpObj) {
        GeometryOutput const geometry = gatherSelection(lods, selection);
        std::string const selectedPath = join(options.outDir,
                options.dumpPly ? "selected.ply" : "selected.obj");
        if (options.dumpPly) {
            writePly(mesh, geometry.indices, selectedPath.c_str(), &geometry.materialIds,
                    &geometry.submeshIds);
        } else {
            writeObj(mesh, geometry.indices, selectedPath.c_str(), &geometry.materialIds,
                    &geometry.submeshIds);
        }
        printf("  wrote %s\n", selectedPath.c_str());
    }

    std::string const errorMapPath = join(options.outDir, "error_map.pgm");
    writeErrorMap(mesh, clusters.clusters, lods, selection, camera, options.thresholdPx,
            errorMapPath.c_str());
    printf("  wrote %s (screen space geometry error, white = at the pixel budget)\n",
            errorMapPath.c_str());

    printf("\n  total time: %.2fs\n", elapsed());
    return 0;
}
