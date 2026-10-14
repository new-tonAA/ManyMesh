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

#ifndef TNT_MANYMESH_GEOMETRYERROR_H
#define TNT_MANYMESH_GEOMETRYERROR_H

#include <manymesh/Cluster.h>
#include <manymesh/Mesh.h>
#include <manymesh/Simplifier.h>

#include <math/vec3.h>

#include <vector>

#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * A minimal pinhole camera. Deliberately not a filament::Camera: this stage is offline and
 * must not depend on a renderer, but the quantities match what the runtime would provide.
 */
struct ViewCamera {
    math::float3 eye{0.0f, 0.0f, 1.0f};
    math::float3 target{0.0f, 0.0f, 0.0f};
    math::float3 up{0.0f, 1.0f, 0.0f};

    float fovY = 0.7853982f;  //!< vertical field of view, radians

    uint32_t screenWidth = 1920;
    uint32_t screenHeight = 1080;

    float near = 0.01f;
    float far = 1000.0f;
};

/**
 * How many pixels of screen space a world-space error of `worldError` spans when seen from
 * `camera` at `worldPosition`.
 *
 * A world error `e` at distance `d` subtends roughly `e/d` radians, and the vertical field of
 * view `fovY` is mapped onto `screenHeight` pixels, hence
 *
 *     pixels = (e / d) * screenHeight / (2 * tan(fovY / 2))
 *
 * This is the classic "screen space error" used to decide whether a piece of geometry is
 * detailed enough for the view it is being seen from — and it is the quantity ManyMesh
 * intends to hand to the reconstruction network.
 */
float screenSpaceError(float worldError, math::float3 worldPosition, ViewCamera const& camera) noexcept;

/**
 * The result of picking a level for every cluster of one view.
 */
struct Selection {
    std::vector<uint32_t> levelPerCluster;

    //! Error committed by the chosen level, in world units and in pixels, per cluster.
    std::vector<float> worldErrorPerCluster;
    std::vector<float> screenErrorPerCluster;

    //! Triangles that would actually be drawn, versus the full detail count.
    uint64_t selectedTriangles = 0;
    uint64_t baseTriangles = 0;

    //! Clusters whose bounding sphere is entirely outside the view frustum. A renderer would
    //! reject these before any level of detail mattered, and a scene is mostly made of them,
    //! so they are counted apart from everything else.
    std::vector<uint8_t> visiblePerCluster;
    uint64_t culledTriangles = 0;

    //! How many clusters ended up on each level.
    std::vector<uint32_t> clustersPerLevel;

    //! How many triangles each level contributes to the drawn total.
    std::vector<uint64_t> trianglesPerLevel;
};

/**
 * Picks, for each cluster, the coarsest level whose screen space error stays under
 * `thresholdPx`. A cluster whose full-detail level already exceeds the threshold keeps level
 * 0: there is nothing coarser that could make it better.
 */
Selection selectClusters(std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, ViewCamera const& camera, float thresholdPx);

/**
 * Same, but with every cluster pinned to one level.
 *
 * A view dependent selection gives every camera its own geometry, which is right for rendering
 * and awkward for producing training data: each view would need its own mesh loaded. Pinning
 * the level decouples the two - one mesh serves every view, and only the projected error map
 * changes with the camera. Pass `level < 0` for the normal selection.
 */
Selection selectClustersAtLevel(std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, ViewCamera const& camera, uint32_t level);

/**
 * Software-rasterizes the per-cluster screen space error of a selection into a binary PPM.
 *
 * This is the offline prototype of the "Geometry Error Map" that ManyMesh wants to feed to
 * the neural reconstruction stage: bright pixels are regions where the chosen geometry is
 * far from the original, dark pixels are regions that survived simplification intact.
 * Pixels covered by more than one cluster keep the one closest to the camera.
 */
void writeErrorMap(Mesh const& mesh, std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, Selection const& selection,
        ViewCamera const& camera, float thresholdPx, char const* path);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_GEOMETRYERROR_H
