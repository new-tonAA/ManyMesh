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

#ifndef TNT_MANYMESH_UVRASTERIZER_H
#define TNT_MANYMESH_UVRASTERIZER_H

#include <math/vec2.h>

#include <algorithm>
#include <cmath>

#include <stdint.h>

namespace filament {
namespace manymesh {
namespace detail {

inline math::float2 uvToPixel(math::float2 uv, uint32_t size) noexcept {
    return math::float2{ uv.x * float(size), uv.y * float(size) };
}

inline float cross2(math::float2 a, math::float2 b) noexcept { return a.x * b.y - a.y * b.x; }

// Rasterizes a UV triangle and calls `sink(x, y, w0, w1, w2)` for every covered texel center.
// Returns false for degenerate UV triangles. The barycentric order matches the three UVs.
template<typename Sink>
bool rasterizeUvTriangle(math::float2 const uv[3], uint32_t size, Sink&& sink) {
    math::float2 const a = uvToPixel(uv[0], size);
    math::float2 const b = uvToPixel(uv[1], size);
    math::float2 const c = uvToPixel(uv[2], size);

    float const area = cross2(b - a, c - a);
    if (std::abs(area) < 1e-8f) {
        return false;
    }
    float const inverseArea = 1.0f / area;

    int const minX = std::max(0, int(std::floor(std::min({ a.x, b.x, c.x }))));
    int const minY = std::max(0, int(std::floor(std::min({ a.y, b.y, c.y }))));
    int const maxX = std::min(int(size) - 1, int(std::ceil(std::max({ a.x, b.x, c.x }))));
    int const maxY = std::min(int(size) - 1, int(std::ceil(std::max({ a.y, b.y, c.y }))));
    if (minX > maxX || minY > maxY) {
        return false;
    }

    // A small negative epsilon lets a texel center that lands exactly on a shared UV edge belong
    // to both triangles, which avoids holes along chart borders.
    constexpr float kEpsilon = -1e-4f;
    for (int y = minY; y <= maxY; ++y) {
        float const py = float(y) + 0.5f;
        for (int x = minX; x <= maxX; ++x) {
            float const px = float(x) + 0.5f;
            math::float2 const p{ px, py };
            float const w0 = cross2(b - p, c - p) * inverseArea;
            float const w1 = cross2(c - p, a - p) * inverseArea;
            float const w2 = 1.0f - w0 - w1;
            if (w0 < kEpsilon || w1 < kEpsilon || w2 < kEpsilon) {
                continue;
            }
            sink(x, y, w0, w1, w2);
        }
    }
    return true;
}

} // namespace detail
} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_UVRASTERIZER_H
