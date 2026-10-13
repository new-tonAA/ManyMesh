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

#include <manymesh/Mesh.h>

namespace filament {
namespace manymesh {

void computeBounds(Mesh const& mesh, math::float3* boundsMin, math::float3* boundsMax) noexcept {
    if (mesh.positions.empty()) {
        return;
    }
    math::float3 lo = mesh.positions[0];
    math::float3 hi = mesh.positions[0];
    for (math::float3 const& p : mesh.positions) {
        lo = min(lo, p);
        hi = max(hi, p);
    }
    *boundsMin = lo;
    *boundsMax = hi;
}

} // namespace manymesh
} // namespace filament
