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

//! Software depth rasterizer for the temporal reconstruction experiments.
//
// Temporal reprojection with camera translation needs the view-space depth of the *rendered*
// coarse frame: a pixel's motion is only determined by its world position. Filament's public
// API reads back colour attachments, so the depth is produced here from the same mesh the
// renderer drew and the exact camera list the renderer used.
//
// `samples/mm_bench --camera-out <file>` writes that camera list. This tool reads it, so the
// two cannot drift apart. Output is a tiny binary format (top-down float32):
//
//   "MMDEPTH1\n"
//   "<width> <height>\n"
//   width * height little-endian float32, row major, top-down
//
// Depth is view-space z (the component along the camera forward vector), in world units.

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace {

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

Vec3 operator-(Vec3 a, Vec3 b) { return { a.x - b.x, a.y - b.y, a.z - b.z }; }
Vec3 operator+(Vec3 a, Vec3 b) { return { a.x + b.x, a.y + b.y, a.z + b.z }; }
Vec3 operator*(Vec3 a, float s) { return { a.x * s, a.y * s, a.z * s }; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) {
    return { a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x };
}
float length(Vec3 a) { return std::sqrt(dot(a, a)); }
Vec3 normalize(Vec3 a) {
    float const l = length(a);
    return l > 1e-12f ? a * (1.0f / l) : Vec3{};
}

struct Mesh {
    std::vector<Vec3> positions;
    std::vector<uint32_t> indices;
};

struct Camera {
    Vec3 eye;
    Vec3 target;
    float fovYDegrees = 45.0f;
    uint32_t width = 640;
    uint32_t height = 360;
};

struct CameraList {
    uint32_t views = 1;
    uint32_t jitter = 1;
    std::vector<Camera> cameras;
};

bool loadMesh(char const* path, Mesh* mesh) {
    Assimp::Importer importer;
    unsigned int const flags = aiProcess_Triangulate | aiProcess_JoinIdenticalVertices |
                               aiProcess_PreTransformVertices;
    aiScene const* scene = importer.ReadFile(path, flags);
    if (scene == nullptr || scene->mNumMeshes == 0) {
        std::fprintf(stderr, "Failed to load '%s': %s\n", path, importer.GetErrorString());
        return false;
    }
    for (unsigned int m = 0; m < scene->mNumMeshes; ++m) {
        aiMesh const* source = scene->mMeshes[m];
        uint32_t const offset = uint32_t(mesh->positions.size());
        mesh->positions.reserve(mesh->positions.size() + source->mNumVertices);
        for (unsigned int v = 0; v < source->mNumVertices; ++v) {
            aiVector3D const& p = source->mVertices[v];
            mesh->positions.push_back({ p.x, p.y, p.z });
        }
        for (unsigned int f = 0; f < source->mNumFaces; ++f) {
            aiFace const& face = source->mFaces[f];
            if (face.mNumIndices >= 3) {
                mesh->indices.push_back(offset + face.mIndices[0]);
                mesh->indices.push_back(offset + face.mIndices[1]);
                mesh->indices.push_back(offset + face.mIndices[2]);
            }
        }
    }
    return true;
}

bool loadCameras(char const* path, CameraList* list) {
    std::ifstream stream(path);
    if (!stream) {
        std::fprintf(stderr, "Failed to open camera list '%s'\n", path);
        return false;
    }
    std::string magic;
    if (!(stream >> magic) || magic != "manymesh-cameras") {
        std::fprintf(stderr, "'%s' is not a manymesh camera list\n", path);
        return false;
    }
    int version = 0;
    stream >> version;
    if (version != 1) {
        std::fprintf(stderr, "Unsupported camera list version %d\n", version);
        return false;
    }
    std::string key;
    uint32_t count = 0;
    while (stream >> key) {
        if (key == "views") {
            stream >> list->views;
        } else if (key == "jitter") {
            stream >> list->jitter;
        } else if (key == "count") {
            stream >> count;
            break;
        } else {
            std::fprintf(stderr, "Unknown camera list key '%s'\n", key.c_str());
            return false;
        }
    }
    list->cameras.reserve(count);
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t index = 0;
        Camera camera;
        stream >> index >> camera.eye.x >> camera.eye.y >> camera.eye.z >> camera.target.x >>
                camera.target.y >> camera.target.z >> camera.fovYDegrees >> camera.width >>
                camera.height;
        if (!stream) {
            std::fprintf(stderr, "Camera list ended after %u of %u entries\n", i, count);
            return false;
        }
        if (index != i) {
            std::fprintf(stderr, "Camera list entry %u has index %u\n", i, index);
            return false;
        }
        list->cameras.push_back(camera);
    }
    return !list->cameras.empty();
}

std::string depthPath(std::string const& dir, uint32_t capture, uint32_t views, uint32_t jitter) {
    char name[64];
    if (jitter > 1) {
        std::snprintf(name, sizeof(name), "depth_v%02u_j%02u.depth", capture / jitter,
                capture % jitter);
    } else {
        std::snprintf(name, sizeof(name), "depth_v%02u.depth", capture);
    }
    (void) views;
    return dir + "/" + name;
}

void rasterize(Mesh const& mesh, Camera const& camera, std::vector<float>* depth) {
    uint32_t const width = camera.width;
    uint32_t const height = camera.height;
    depth->assign(size_t(width) * height, 0.0f);

    Vec3 const forward = normalize(camera.target - camera.eye);
    Vec3 const right = normalize(cross(forward, Vec3{ 0.0f, 1.0f, 0.0f }));
    Vec3 const up = cross(right, forward);
    float const tanHalf = std::tan(camera.fovYDegrees * 0.5f * 3.14159265358979323846f / 180.0f);
    float const focal = (float(height) * 0.5f) / std::max(tanHalf, 1e-6f);
    float const halfWidth = float(width) * 0.5f;
    float const halfHeight = float(height) * 0.5f;

    std::vector<float> sx(mesh.positions.size());
    std::vector<float> sy(mesh.positions.size());
    std::vector<float> invZ(mesh.positions.size());
    std::vector<bool> valid(mesh.positions.size());

    for (size_t i = 0; i < mesh.positions.size(); ++i) {
        Vec3 const delta = mesh.positions[i] - camera.eye;
        float const z = dot(delta, forward);
        valid[i] = z > 1e-5f;
        if (!valid[i]) {
            continue;
        }
        float const inv = 1.0f / z;
        invZ[i] = inv;
        sx[i] = halfWidth + dot(delta, right) * inv * focal;
        sy[i] = halfHeight - dot(delta, up) * inv * focal;
    }

    for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
        uint32_t const ia = mesh.indices[t + 0];
        uint32_t const ib = mesh.indices[t + 1];
        uint32_t const ic = mesh.indices[t + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() ||
                ic >= mesh.positions.size()) {
            continue;
        }
        if (!valid[ia] || !valid[ib] || !valid[ic]) {
            continue;
        }
        float const ax = sx[ia];
        float const ay = sy[ia];
        float const bx = sx[ib];
        float const by = sy[ib];
        float const cx = sx[ic];
        float const cy = sy[ic];
        float const area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
        if (std::fabs(area) < 1e-10f) {
            continue;
        }
        float const minX = std::max(0.0f, std::floor(std::min({ ax, bx, cx })));
        float const maxX = std::min(float(width - 1), std::ceil(std::max({ ax, bx, cx })));
        float const minY = std::max(0.0f, std::floor(std::min({ ay, by, cy })));
        float const maxY = std::min(float(height - 1), std::ceil(std::max({ ay, by, cy })));
        if (minX > maxX || minY > maxY) {
            continue;
        }
        float const inverseArea = 1.0f / area;
        int const x0 = int(minX);
        int const x1 = int(maxX);
        int const y0 = int(minY);
        int const y1 = int(maxY);
        for (int y = y0; y <= y1; ++y) {
            float const py = float(y) + 0.5f;
            for (int x = x0; x <= x1; ++x) {
                float const px = float(x) + 0.5f;
                float const w0 = ((cx - bx) * (py - by) - (cy - by) * (px - bx)) * inverseArea;
                float const w1 = ((ax - cx) * (py - cy) - (ay - cy) * (px - cx)) * inverseArea;
                float const w2 = 1.0f - w0 - w1;
                if (w0 < 0.0f || w1 < 0.0f || w2 < 0.0f) {
                    continue;
                }
                float const z = w0 * invZ[ia] + w1 * invZ[ib] + w2 * invZ[ic];
                float& target = (*depth)[size_t(y) * width + size_t(x)];
                if (z > target) {
                    target = z;
                }
            }
        }
    }

    for (float& value : *depth) {
        value = value > 0.0f ? 1.0f / value : 0.0f;
    }
}

bool writeDepth(std::string const& path, std::vector<float> const& depth, uint32_t width,
        uint32_t height) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream) {
        std::fprintf(stderr, "Failed to open '%s' for writing\n", path.c_str());
        return false;
    }
    stream << "MMDEPTH1\n" << width << ' ' << height << '\n';
    stream.write(reinterpret_cast<char const*>(depth.data()),
            std::streamsize(depth.size() * sizeof(float)));
    return bool(stream);
}

void usage(char const* program) {
    std::fprintf(stderr,
            "Usage: %s <mesh> --cameras <file> --out <dir> [options]\n\n"
            "Rasterizes view-space depth for every camera in a manymesh camera list, which\n"
            "samples/mm_bench writes with --camera-out. The output names match the render\n"
            "names, so depth_vNN_jMM.depth belongs to lr_vNN_jMM.png.\n\n"
            "Options:\n"
            "  --out <dir>       output directory (required)\n"
            "  --cameras <file>  camera list written by mm_bench --camera-out (required)\n"
            "  --quiet           do not print per-frame progress\n",
            program);
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        usage(argv[0]);
        return 1;
    }
    char const* meshPath = argv[1];
    std::string cameraPath;
    std::string outDir;
    bool quiet = false;
    for (int i = 2; i < argc; ++i) {
        std::string const arg = argv[i];
        if (arg == "--cameras" && i + 1 < argc) {
            cameraPath = argv[++i];
        } else if (arg == "--out" && i + 1 < argc) {
            outDir = argv[++i];
        } else if (arg == "--quiet") {
            quiet = true;
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0]);
            return 0;
        } else {
            std::fprintf(stderr, "Unknown option '%s'\n", arg.c_str());
            usage(argv[0]);
            return 1;
        }
    }
    if (cameraPath.empty() || outDir.empty()) {
        usage(argv[0]);
        return 1;
    }

    Mesh mesh;
    if (!loadMesh(meshPath, &mesh)) {
        return 1;
    }
    CameraList cameras;
    if (!loadCameras(cameraPath.c_str(), &cameras)) {
        return 1;
    }
    std::printf("mmdepth: %zu vertices, %zu triangles, %zu cameras\n", mesh.positions.size(),
            mesh.indices.size() / 3, cameras.cameras.size());

    std::vector<float> depth;
    for (size_t i = 0; i < cameras.cameras.size(); ++i) {
        Camera const& camera = cameras.cameras[i];
        rasterize(mesh, camera, &depth);
        std::string const path = depthPath(outDir, uint32_t(i), cameras.views, cameras.jitter);
        if (!writeDepth(path, depth, camera.width, camera.height)) {
            return 1;
        }
        if (!quiet) {
            std::printf("  wrote %s (%ux%u)\n", path.c_str(), camera.width, camera.height);
            std::fflush(stdout);
        }
    }
    return 0;
}
