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

#ifndef TNT_MANYMESH_VISIBILITYBUFFER_H
#define TNT_MANYMESH_VISIBILITYBUFFER_H

#include <manymesh/GpuLod.h>
#include <manymesh/LodGraph.h>
#include <manymesh/Mesh.h>

#include <vector>

#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * A reference software visibility buffer: for every pixel, which selected cluster was
 * front-most and at what inverse depth.
 *
 * The GPU implementation would rasterize the same `(clusterId, depth)` pair into an R32_UINT +
 * depth target and defer material shading to a second pass. This CPU version exists so the
 * selection and the data layout can be validated without a device.
 */
struct VisibilityBuffer {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint32_t> clusterIds;  //!< UINT32_MAX for an uncovered pixel
    //! Triangle ordinal inside GpuLodBuffer::indices (index / 3), for deferred shading.
    std::vector<uint32_t> triangleIds;
    std::vector<uint32_t> materialIds;
    std::vector<uint32_t> submeshIds;
    std::vector<float> inverseDepth;
    uint32_t coveredPixels = 0;
};

VisibilityBuffer rasterizeVisibility(Mesh const& mesh, GpuLodBuffer const& buffer,
        LodGraphSelection const& selection, ViewCamera const& camera);

void writeVisibilityBufferPgm(VisibilityBuffer const& buffer, char const* path);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_VISIBILITYBUFFER_H
