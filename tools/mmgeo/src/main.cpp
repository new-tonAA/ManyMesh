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
#include <manymesh/Grouper.h>
#include <manymesh/Mesh.h>
#include <manymesh/Simplifier.h>

#include <math/vec3.h>

#include <utils/getopt.h>

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace math = filament::math;
using namespace filament::manymesh;

namespace {

struct Options {
    std::string input;
    std::string outDir = "out/mmgeo";

    bool clusterMode = true;
    uint32_t levels = 5;
    float ratio = 0.7f;
    float targetError = 1e-2f;

    uint32_t clusterVertices = 128;
    uint32_t clusterTriangles = 128;
    float coneWeight = 0.0f;
    uint32_t groupSize = 1;
    bool lockBorder = true;

    bool dumpObj = true;
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
  --mode chain|cluster global LOD chain, or per-cluster LOD (default: cluster)
  --levels N           number of LOD levels including the original (default: 5)
  --ratio F            fraction of triangles kept per level (default: 0.7)
  --target-error F     relative error ceiling for simplification (default: 0.01)
  --cluster-verts N    max vertices per cluster, <= 255 (default: 128)
  --cluster-tris N     max triangles per cluster, <= 512 (default: 128)
  --cone-weight F      0 = size driven clusters, 1 = favour cone culling (default: 0)
  --group-size N       clusters merged into one simplification unit (default: 1)
  --lock-border 0|1    per-cluster mode: never move cluster borders (default: 1)
  --dump-obj 0|1       write the simplified meshes as OBJ (default: 1)
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

    mesh->positions.reserve(vertexCount);
    mesh->indices.reserve(triangleCount * 3);

    uint32_t vertexOffset = 0;
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        aiMesh const* source = scene->mMeshes[m];
        for (unsigned int v = 0; v < source->mNumVertices; ++v) {
            aiVector3D const& p = source->mVertices[v];
            mesh->positions.push_back({ p.x, p.y, p.z });
        }
        for (unsigned int f = 0; f < source->mNumFaces; ++f) {
            aiFace const& face = source->mFaces[f];
            for (unsigned int i = 0; i < face.mNumIndices && i < 3; ++i) {
                mesh->indices.push_back(vertexOffset + face.mIndices[i]);
            }
        }
        vertexOffset += source->mNumVertices;
    }

    return true;
}

void writeObj(Mesh const& mesh, std::vector<uint32_t> const& indices, char const* path) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }
    for (math::float3 const& p : mesh.positions) {
        file << "v " << p.x << ' ' << p.y << ' ' << p.z << '\n';
    }
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        file << "f " << (indices[i + 0] + 1) << ' ' << (indices[i + 1] + 1) << ' '
             << (indices[i + 2] + 1) << '\n';
    }
}

// Concatenates the given level of every cluster, clamped to the coarsest level each cluster
// actually has. Used to dump a "whole mesh at level N" OBJ in per-cluster mode.
std::vector<uint32_t> gatherLevel(std::vector<ClusterLods> const& lods, uint32_t level) {
    std::vector<uint32_t> result;
    for (ClusterLods const& clusterLods : lods) {
        if (clusterLods.levels.empty()) {
            continue;
        }
        uint32_t const clamped = std::min(level, uint32_t(clusterLods.levels.size() - 1));
        std::vector<uint32_t> const& indices = clusterLods.levels[clamped].indices;
        result.insert(result.end(), indices.begin(), indices.end());
    }
    return result;
}

std::vector<uint32_t> gatherSelection(std::vector<ClusterLods> const& lods,
        Selection const& selection) {
    std::vector<uint32_t> result;
    for (size_t c = 0; c < selection.levelPerCluster.size(); ++c) {
        uint32_t const level = selection.levelPerCluster[c];
        if (level >= lods[c].levels.size()) {
            continue;
        }
        std::vector<uint32_t> const& indices = lods[c].levels[level].indices;
        result.insert(result.end(), indices.begin(), indices.end());
    }
    return result;
}

void writeJson(Mesh const& mesh, ClusterSet const& clusters, std::vector<ClusterLods> const& lods,
        Options const& options, char const* path) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return;
    }

    file << "{\n";
    file << "  \"source\": \"" << options.input << "\",\n";
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
        { "group-size", utils::getopt::required_argument, 0, 'g' },
        { "lock-border", utils::getopt::required_argument, 0, 'b' },
        { "dump-obj", utils::getopt::required_argument, 0, 'd' },
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
                if (!options->clusterMode && strcmp(arg, "chain") != 0) {
                    std::cerr << "Unknown mode '" << arg << "', expected 'chain' or 'cluster'"
                              << std::endl;
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
            case 'g':
                options->groupSize = std::max(1u, uint32_t(atoi(arg)));
                break;
            case 'b':
                options->lockBorder = atoi(arg) != 0;
                break;
            case 'd':
                options->dumpObj = atoi(arg) != 0;
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

    if (!options.clusterMode) {
        // ------------------------------------------------------------------------------------
        // Global LOD chain: the classic "distance based LOD" baseline.
        // ------------------------------------------------------------------------------------
        SimplifyOptions simplifyOptions;
        simplifyOptions.levels = options.levels;
        simplifyOptions.ratio = options.ratio;
        simplifyOptions.targetError = options.targetError;

        std::vector<LodLevel> const levels = simplifyChain(mesh, simplifyOptions);
        printf("  simplified chain built (%.2fs)\n", elapsed());

        printChainStats(mesh, levels);

        if (options.dumpObj) {
            for (size_t l = 0; l < levels.size(); ++l) {
                std::string const path = join(options.outDir, "lod" + std::to_string(l) + ".obj");
                writeObj(mesh, levels[l].indices, path.c_str());
            }
            printf("  wrote %zu OBJ files to %s\n", levels.size(), options.outDir.c_str());
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
            std::vector<uint32_t> const indices = gatherLevel(lods, l);
            if (indices.empty()) {
                break;
            }
            std::string const path = join(options.outDir, "lod" + std::to_string(l) + ".obj");
            writeObj(mesh, indices, path.c_str());
        }
        printf("  wrote per-level OBJ files to %s\n", options.outDir.c_str());
    }

    ViewCamera const camera = makeCamera(options, mesh);
    Selection const selection =
            selectClusters(clusters.clusters, lods, camera, options.thresholdPx);
    printSelectionStats(selection, camera, options.thresholdPx);

    if (options.dumpObj) {
        std::vector<uint32_t> const indices = gatherSelection(lods, selection);
        std::string const selectedPath = join(options.outDir, "selected.obj");
        writeObj(mesh, indices, selectedPath.c_str());
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
