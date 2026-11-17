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

#include <manymesh/CornerSimplifier.h>

#include <assimp/Importer.hpp>
#include <assimp/postprocess.h>
#include <assimp/scene.h>

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <vector>

using namespace filament::manymesh;

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: mm_capture_candidates input-mesh output-json\n";
        return EXIT_FAILURE;
    }
    Assimp::Importer importer;
    auto const* scene = importer.ReadFile(argv[1], aiProcess_Triangulate |
            aiProcess_JoinIdenticalVertices | aiProcess_PreTransformVertices);
    if (!scene || !scene->mNumMeshes) {
        std::cerr << importer.GetErrorString() << '\n';
        return EXIT_FAILURE;
    }
    // Each imported submesh is captured separately: do not silently collapse across materials.
    std::ofstream out(argv[2]);
    if (!out) { return EXIT_FAILURE; }
    out << std::setprecision(17) << "{\"version\":1,\"scope\":\"initial legal Corner placements; "
            "geometry only; not global quality gate\",\"units\":[";
    for (unsigned m = 0; m < scene->mNumMeshes; ++m) {
        auto const* source = scene->mMeshes[m];
        Mesh mesh;
        for (unsigned v = 0; v < source->mNumVertices; ++v) {
            auto const& p = source->mVertices[v];
            mesh.positions.push_back({ p.x, p.y, p.z });
            if (source->HasNormals()) {
                auto const& n = source->mNormals[v];
                mesh.normals.push_back({ n.x, n.y, n.z });
            }
            if (source->HasTextureCoords(0)) {
                auto const& uv = source->mTextureCoords[0][v];
                mesh.uvs.push_back({ uv.x, uv.y });
            }
        }
        for (unsigned f = 0; f < source->mNumFaces; ++f) {
            auto const& face = source->mFaces[f];
            if (face.mNumIndices != 3) {
                std::cerr << "nontriangle primitive\n";
                return EXIT_FAILURE;
            }
            mesh.indices.insert(mesh.indices.end(), face.mIndices, face.mIndices + 3);
        }
        CornerCandidateCapture capture;
        // Capture all initially legal directed edges; never claim an insertion-order prefix is
        // representative. Bound input complexity rather than silently truncating candidates.
        if (mesh.triangleCount() > 100000) {
            std::cerr << "research capture limit: 100000 triangles per submesh\n";
            return EXIT_FAILURE;
        }
        capture.maxCandidates = std::numeric_limits<size_t>::max();
        CornerSimplifyOptions options;
        options.targetIndexCount = mesh.indices.size() > 3 ? mesh.indices.size() - 3 : 0;
        options.candidateCapture = &capture;
        std::vector<uint32_t> indices;
        std::vector<GeneratedVertex> generated;
        simplifyWithCornerAttributes(mesh, mesh.indices, options, &indices, &generated);
        if (m) { out << ','; }
        out << "{\"material\":" << source->mMaterialIndex << ",\"positions\":[";
        for (size_t v = 0; v < capture.initialPositions.size(); ++v) {
            auto const& p = capture.initialPositions[v];
            if (v) { out << ','; }
            out << '[' << p.x << ',' << p.y << ',' << p.z << ']';
        }
        out << "],\"triangles\":[";
        for (size_t t = 0; t < capture.initialTriangles.size(); ++t) {
            auto const& triangle = capture.initialTriangles[t];
            if (t) { out << ','; }
            out << '[' << triangle[0] << ',' << triangle[1] << ',' << triangle[2] << ']';
        }
        out << "],\"legalCandidates\":" << capture.legalCandidates << ",\"candidates\":[";
        for (size_t i = 0; i < capture.candidates.size(); ++i) {
            auto const& c = capture.candidates[i];
            if (i) { out << ','; }
            out << "{\"remove\":" << c.remove << ",\"keep\":" << c.keep << ",\"target\":["
                << c.targetPosition.x << ',' << c.targetPosition.y << ',' << c.targetPosition.z
                << "],\"priority\":" << c.priority << ",\"affected\":[";
            for (size_t t = 0; t < c.affectedTriangles.size(); ++t) {
                if (t) { out << ','; }
                out << c.affectedTriangles[t];
            }
            out << "]}";
        }
        out << "]}";
        std::cerr << "unit " << m << ": " << mesh.triangleCount() << " triangles, "
                  << capture.candidates.size() << " legal candidates\n";
    }
    out << "]}\n";
    return out.good() ? EXIT_SUCCESS : EXIT_FAILURE;
}
