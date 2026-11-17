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
#include <manymesh/Quality.h>

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

using namespace filament::manymesh;

namespace {
Mesh captureGrid() {
    Mesh mesh;
    constexpr uint32_t N = 8;
    for (uint32_t y = 0; y <= N; ++y) {
        for (uint32_t x = 0; x <= N; ++x) {
            mesh.positions.push_back({ float(x), float(y),
                    0.1f * std::sin(float(x)) * std::cos(float(y)) });
        }
    }
    for (uint32_t y = 0; y < N; ++y) {
        for (uint32_t x = 0; x < N; ++x) {
            uint32_t const a = y * (N + 1) + x;
            mesh.indices.insert(mesh.indices.end(), { a, a + 1, a + N + 2,
                    a, a + N + 2, a + N + 1 });
        }
    }
    return mesh;
}
} // namespace

TEST(CornerCapture, DoesNotChangeSimplificationAndExportsApplicableCandidates) {
    Mesh const mesh = captureGrid();
    CornerSimplifyOptions options;
    options.targetIndexCount = mesh.indices.size() / 2;
    std::vector<uint32_t> baseline, observed;
    std::vector<GeneratedVertex> baselineVertices, observedVertices;
    float baselineError = 0.0f, observedError = 0.0f;
    bool const result = simplifyWithCornerAttributes(mesh, mesh.indices, options,
            &baseline, &baselineVertices, &baselineError);
    CornerCandidateCapture capture;
    capture.maxCandidates = 24;
    options.candidateCapture = &capture;
    EXPECT_EQ(result, simplifyWithCornerAttributes(mesh, mesh.indices, options,
            &observed, &observedVertices, &observedError));
    EXPECT_EQ(baseline, observed);
    EXPECT_EQ(baselineVertices, observedVertices);
    EXPECT_FLOAT_EQ(baselineError, observedError);
    ASSERT_FALSE(capture.candidates.empty());
    EXPECT_LE(capture.candidates.size(), capture.maxCandidates);
    EXPECT_GE(capture.legalCandidates, capture.candidates.size());
    ASSERT_EQ(capture.initialTriangles.size(), mesh.indices.size() / 3);
    for (auto const& candidate: capture.candidates) {
        ASSERT_LT(candidate.remove, capture.initialPositions.size());
        ASSERT_LT(candidate.keep, capture.initialPositions.size());
        EXPECT_TRUE(std::isfinite(candidate.priority));
        Mesh changed;
        changed.positions = capture.initialPositions;
        changed.positions[candidate.keep] = candidate.targetPosition;
        size_t deleted = 0;
        for (size_t t = 0; t < capture.initialTriangles.size(); ++t) {
            auto triangle = capture.initialTriangles[t];
            bool affected = false;
            for (uint32_t& vertex: triangle) {
                affected |= vertex == candidate.remove || vertex == candidate.keep;
                if (vertex == candidate.remove) { vertex = candidate.keep; }
            }
            EXPECT_EQ(affected, std::binary_search(candidate.affectedTriangles.begin(),
                    candidate.affectedTriangles.end(), uint32_t(t)));
            if (triangle[0] == triangle[1] || triangle[1] == triangle[2] ||
                    triangle[2] == triangle[0]) {
                ++deleted;
                continue;
            }
            changed.indices.insert(changed.indices.end(), triangle.begin(), triangle.end());
        }
        EXPECT_GT(deleted, 0u);
        auto const topology = measureWeldedTopology(changed, changed.indices);
        EXPECT_EQ(topology.nonManifoldEdges, 0u);
        EXPECT_EQ(topology.duplicateTriangles, 0u);
        EXPECT_EQ(topology.degenerateTriangles, 0u);
        EXPECT_EQ(topology.boundaryEdges, measureWeldedTopology(mesh, mesh.indices).boundaryEdges);
    }
}

TEST(CornerCapture, CapAndEarlyReturnResetOldObservations) {
    Mesh const mesh = captureGrid();
    CornerCandidateCapture capture;
    capture.maxCandidates = 0;
    CornerSimplifyOptions options;
    options.targetIndexCount = mesh.indices.size() / 2;
    options.candidateCapture = &capture;
    std::vector<uint32_t> output;
    std::vector<GeneratedVertex> generated;
    simplifyWithCornerAttributes(mesh, mesh.indices, options, &output, &generated);
    EXPECT_TRUE(capture.candidates.empty());
    EXPECT_GT(capture.legalCandidates, 0u);
    EXPECT_FALSE(capture.initialPositions.empty());
    options.targetIndexCount = mesh.indices.size();
    simplifyWithCornerAttributes(mesh, mesh.indices, options, &output, &generated);
    EXPECT_TRUE(capture.initialPositions.empty());
    EXPECT_TRUE(capture.initialTriangles.empty());
    EXPECT_TRUE(capture.candidates.empty());
    EXPECT_EQ(capture.legalCandidates, 0u);
}
