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

#include <manymesh/GeometryError.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <vector>

namespace filament {
namespace manymesh {

namespace {

//! Orthonormal camera frame plus the two constants every projection needs.
struct Basis {
    math::float3 right;
    math::float3 up;
    math::float3 forward;
    float tanHalfFovY = 1.0f;
    float aspect = 1.0f;
    float pixelsPerRadian = 1.0f;
};

bool makeBasis(ViewCamera const& camera, Basis* basis) {
    math::float3 const forward = camera.target - camera.eye;
    float const forwardLength = length(forward);
    if (!(forwardLength > 0.0f)) {
        return false;
    }
    basis->forward = forward / forwardLength;

    math::float3 const right = cross(basis->forward, camera.up);
    float const rightLength = length(right);
    if (!(rightLength > 0.0f)) {
        return false;
    }
    basis->right = right / rightLength;
    basis->up = cross(basis->right, basis->forward);

    float const tanHalfFovY = std::tan(camera.fovY * 0.5f);
    if (!(tanHalfFovY > 0.0f)) {
        return false;
    }
    basis->tanHalfFovY = tanHalfFovY;
    basis->aspect = float(camera.screenWidth) / float(std::max(camera.screenHeight, 1u));
    basis->pixelsPerRadian = float(camera.screenHeight) / (2.0f * tanHalfFovY);
    return true;
}

// A world space error at distance `depth` subtends roughly error/depth radians, which the
// vertical field of view maps onto pixelsPerRadian pixels.
float screenErrorAtDepth(float worldError, float depth, float pixelsPerRadian, float near) {
    float const distance = std::max(depth, near);
    return (worldError / distance) * pixelsPerRadian;
}

// Same, for a bounding sphere: the nearest point of the cluster is what decides how visible
// its error is, so the radius is taken off the depth. Erring on the pessimistic side means
// we never under-tessellate a cluster that is closer than its centre suggests.
float screenErrorForSphere(float worldError, Sphere const& sphere, ViewCamera const& camera,
        Basis const& basis) {
    float const depth = dot(sphere.center - camera.eye, basis.forward) - sphere.radius;
    return screenErrorAtDepth(worldError, depth, basis.pixelsPerRadian, camera.near);
}

struct ScreenVertex {
    float x = 0.0f;
    float y = 0.0f;
    float invZ = 0.0f;
    bool valid = false;
};

ScreenVertex project(math::float3 const& position, ViewCamera const& camera, Basis const& basis) {
    ScreenVertex out;

    math::float3 const d = position - camera.eye;
    float const depth = dot(d, basis.forward);
    if (!(depth >= camera.near)) {
        return out;
    }

    float const tanHalfFovX = basis.tanHalfFovY * basis.aspect;
    float const ndcX = (dot(d, basis.right) / depth) / tanHalfFovX;
    float const ndcY = (dot(d, basis.up) / depth) / basis.tanHalfFovY;

    out.x = (ndcX * 0.5f + 0.5f) * float(camera.screenWidth);
    out.y = (1.0f - (ndcY * 0.5f + 0.5f)) * float(camera.screenHeight);  // images grow downwards
    out.invZ = 1.0f / depth;
    out.valid = true;
    return out;
}

//! True when a cluster's bounding sphere lies entirely outside the view frustum.
bool sphereOutsideFrustum(Sphere const& sphere, ViewCamera const& camera, Basis const& basis) {
    math::float3 const d = sphere.center - camera.eye;
    float const depth = dot(d, basis.forward);
    if (depth + sphere.radius < camera.near) {
        return true;  // entirely behind the near plane
    }
    if (depth - sphere.radius > camera.far) {
        return true;  // entirely beyond the far plane
    }
    // The four side planes: a sphere is outside one when its centre is further off axis than
    // the plane at its depth, by more than its radius.
    float const halfHeight = depth * basis.tanHalfFovY;
    float const halfWidth = halfHeight * basis.aspect;
    if (std::abs(dot(d, basis.right)) - sphere.radius > halfWidth) {
        return true;
    }
    if (std::abs(dot(d, basis.up)) - sphere.radius > halfHeight) {
        return true;
    }
    return false;
}

float edgeFunction(float ax, float ay, float bx, float by, float px, float py) {
    return (px - ax) * (by - ay) - (py - ay) * (bx - ax);
}

} // anonymous namespace

float screenSpaceError(float worldError, math::float3 worldPosition, ViewCamera const& camera) noexcept {
    Basis basis;
    if (!makeBasis(camera, &basis)) {
        return 0.0f;
    }
    float const depth = dot(worldPosition - camera.eye, basis.forward);
    return screenErrorAtDepth(worldError, depth, basis.pixelsPerRadian, camera.near);
}

namespace {

//! level < 0 means "pick per view", anything else pins every cluster to that level.
Selection selectImpl(std::vector<Cluster> const& clusters, std::vector<ClusterLods> const& lods,
        ViewCamera const& camera, float thresholdPx, int forcedLevel) {
    Selection selection;

    size_t const count = std::min(clusters.size(), lods.size());
    selection.levelPerCluster.assign(count, 0);
    selection.worldErrorPerCluster.assign(count, 0.0f);
    selection.screenErrorPerCluster.assign(count, 0.0f);

    size_t maxLevels = 1;
    for (ClusterLods const& clusterLods : lods) {
        maxLevels = std::max(maxLevels, clusterLods.levels.size());
    }
    selection.clustersPerLevel.assign(maxLevels, 0);
    selection.trianglesPerLevel.assign(maxLevels, 0);
    selection.visiblePerCluster.assign(count, 1);

    Basis basis;
    bool const haveCamera = makeBasis(camera, &basis);

    for (size_t c = 0; c < count; ++c) {
        ClusterLods const& clusterLods = lods[c];
        if (clusterLods.levels.empty()) {
            continue;
        }

        // Counted before the cull test, so that `baseTriangles` stays the whole input and the
        // culled share is a share of the scene rather than of what is left after culling.
        uint64_t const clusterBaseTriangles = clusterLods.levels[0].triangleCount();
        selection.baseTriangles += clusterBaseTriangles;

        if (haveCamera && sphereOutsideFrustum(clusters[c].bounds, camera, basis)) {
            selection.visiblePerCluster[c] = 0;
            selection.culledTriangles += clusterBaseTriangles;
            continue;
        }

        size_t chosen = 0;
        if (forcedLevel >= 0) {
            chosen = std::min(size_t(forcedLevel), clusterLods.levels.size() - 1);
        } else if (haveCamera) {
            // Walk from the coarsest level down and take the first one that still fits the
            // pixel budget. When even full detail does not fit, full detail is what we keep:
            // there is nothing better available.
            for (size_t level = clusterLods.levels.size(); level-- > 1;) {
                float const screen = screenErrorForSphere(clusterLods.levels[level].worldError,
                        clusters[c].bounds, camera, basis);
                if (screen <= thresholdPx) {
                    chosen = level;
                    break;
                }
            }
        }

        LodLevel const& chosenLevel = clusterLods.levels[chosen];
        float const screen = haveCamera
                ? screenErrorForSphere(chosenLevel.worldError, clusters[c].bounds, camera, basis)
                : 0.0f;

        selection.levelPerCluster[c] = uint32_t(chosen);
        selection.worldErrorPerCluster[c] = chosenLevel.worldError;
        selection.screenErrorPerCluster[c] = screen;

        uint64_t const chosenTriangles = chosenLevel.triangleCount();
        selection.selectedTriangles += chosenTriangles;
        selection.clustersPerLevel[chosen] += 1;
        selection.trianglesPerLevel[chosen] += chosenTriangles;
    }

    return selection;
}

} // anonymous namespace

Selection selectClusters(std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, ViewCamera const& camera, float thresholdPx) {
    return selectImpl(clusters, lods, camera, thresholdPx, -1);
}

Selection selectClustersAtLevel(std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, ViewCamera const& camera, uint32_t level) {
    return selectImpl(clusters, lods, camera, 0.0f, int(level));
}

void writeErrorMap(Mesh const& mesh, std::vector<Cluster> const& clusters,
        std::vector<ClusterLods> const& lods, Selection const& selection,
        ViewCamera const& camera, float thresholdPx, char const* path) {
    uint32_t const width = camera.screenWidth;
    uint32_t const height = camera.screenHeight;
    if (width == 0 || height == 0 || path == nullptr) {
        return;
    }

    Basis basis;
    if (!makeBasis(camera, &basis)) {
        return;
    }

    size_t const pixelCount = size_t(width) * size_t(height);
    std::vector<float> invDepthBuffer(pixelCount, 0.0f);
    std::vector<float> errorBuffer(pixelCount, 0.0f);

    size_t const count = std::min(
            { clusters.size(), lods.size(), selection.levelPerCluster.size() });

    for (size_t c = 0; c < count; ++c) {
        if (c < selection.visiblePerCluster.size() && selection.visiblePerCluster[c] == 0) {
            continue;  // outside the frustum, so its error cannot be seen
        }
        uint32_t const level = selection.levelPerCluster[c];
        if (level >= lods[c].levels.size()) {
            continue;
        }

        // Normalize against the pixel budget so the image reads as "how much of the error
        // budget this region is spending": black is untouched geometry, white is at the limit.
        float const screenError = selection.screenErrorPerCluster[c];
        float const value = thresholdPx > 0.0f
                ? std::clamp(screenError / thresholdPx, 0.0f, 1.0f)
                : (screenError > 0.0f ? 1.0f : 0.0f);

        std::vector<uint32_t> const& indices = lods[c].levels[level].indices;

        for (size_t t = 0; t + 2 < indices.size(); t += 3) {
            ScreenVertex const v0 = project(mesh.positions[indices[t + 0]], camera, basis);
            ScreenVertex const v1 = project(mesh.positions[indices[t + 1]], camera, basis);
            ScreenVertex const v2 = project(mesh.positions[indices[t + 2]], camera, basis);
            // No near-plane clipping in this prototype: triangles crossing the near plane are
            // dropped rather than cut. Fine for a diagnostic image, not for production.
            if (!v0.valid || !v1.valid || !v2.valid) {
                continue;
            }

            float const area = edgeFunction(v0.x, v0.y, v1.x, v1.y, v2.x, v2.y);
            if (area == 0.0f) {
                continue;
            }
            float const invArea = 1.0f / area;

            int const minX = std::max(int(std::floor(std::min({ v0.x, v1.x, v2.x }))), 0);
            int const minY = std::max(int(std::floor(std::min({ v0.y, v1.y, v2.y }))), 0);
            int const maxX = std::min(int(std::ceil(std::max({ v0.x, v1.x, v2.x }))), int(width) - 1);
            int const maxY = std::min(int(std::ceil(std::max({ v0.y, v1.y, v2.y }))), int(height) - 1);

            for (int y = minY; y <= maxY; ++y) {
                for (int x = minX; x <= maxX; ++x) {
                    float const px = float(x) + 0.5f;
                    float const py = float(y) + 0.5f;

                    float const w0 = edgeFunction(v1.x, v1.y, v2.x, v2.y, px, py) * invArea;
                    float const w1 = edgeFunction(v2.x, v2.y, v0.x, v0.y, px, py) * invArea;
                    float const w2 = edgeFunction(v0.x, v0.y, v1.x, v1.y, px, py) * invArea;
                    if (w0 < 0.0f || w1 < 0.0f || w2 < 0.0f) {
                        continue;
                    }

                    float const invZ = w0 * v0.invZ + w1 * v1.invZ + w2 * v2.invZ;
                    size_t const pixel = size_t(y) * width + size_t(x);
                    if (invZ > invDepthBuffer[pixel]) {
                        invDepthBuffer[pixel] = invZ;
                        errorBuffer[pixel] = value;
                    }
                }
            }
        }
    }

    FILE* file = std::fopen(path, "wb");
    if (file == nullptr) {
        return;
    }

    std::fprintf(file, "P5\n%u %u\n255\n", width, height);
    std::vector<unsigned char> row(width);
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            float const v = errorBuffer[size_t(y) * width + size_t(x)];
            row[x] = (unsigned char)std::lround(std::clamp(v, 0.0f, 1.0f) * 255.0f);
        }
        std::fwrite(row.data(), 1, row.size(), file);
    }
    std::fclose(file);
}

} // namespace manymesh
} // namespace filament
