from pathlib import Path
p = Path('libs/manymesh/src/DetailBake.cpp')
s = p.read_text(encoding='utf-8')
s = s.replace('''#include <algorithm>
#include <cmath>
''', '''#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
''', 1)

height_code = r'''
using HeightClock = std::chrono::steady_clock;

struct HeightBounds {
    math::float3 lo{ std::numeric_limits<float>::max() };
    math::float3 hi{ std::numeric_limits<float>::lowest() };

    void expand(math::float3 point) noexcept {
        lo = min(lo, point);
        hi = max(hi, point);
    }

    bool valid() const noexcept { return hi.x >= lo.x && hi.y >= lo.y && hi.z >= lo.z; }
};

struct HeightTriangle {
    math::float3 v0{};
    math::float3 v1{};
    math::float3 v2{};
    math::float3 centroid{};
    HeightBounds bounds;
};

struct HeightNode {
    HeightBounds bounds;
    uint32_t left = std::numeric_limits<uint32_t>::max();
    uint32_t right = std::numeric_limits<uint32_t>::max();
    uint32_t first = 0;
    uint32_t count = 0;
};

inline float heightSafeInverse(float value) noexcept {
    return 1.0f / (std::abs(value) < 1e-20f ? 1e-20f : value);
}

inline bool heightRayBounds(HeightBounds const& bounds, math::float3 const& origin,
        math::float3 const& inverseDirection, float maximumDistance) noexcept {
    float tMin = 0.0f;
    float tMax = maximumDistance;
    auto testAxis = [&](float originAxis, float inverse, float lo, float hi) {
        float const t0 = (lo - originAxis) * inverse;
        float const t1 = (hi - originAxis) * inverse;
        tMin = std::max(tMin, std::min(t0, t1));
        tMax = std::min(tMax, std::max(t0, t1));
    };
    testAxis(origin.x, inverseDirection.x, bounds.lo.x, bounds.hi.x);
    testAxis(origin.y, inverseDirection.y, bounds.lo.y, bounds.hi.y);
    testAxis(origin.z, inverseDirection.z, bounds.lo.z, bounds.hi.z);
    return tMax >= tMin;
}

inline bool heightRayTriangle(HeightTriangle const& triangle, math::float3 const& origin,
        math::float3 const& direction, float maximumDistance, float* distance) noexcept {
    constexpr float kEpsilon = 1e-9f;
    math::float3 const edge1 = triangle.v1 - triangle.v0;
    math::float3 const edge2 = triangle.v2 - triangle.v0;
    math::float3 const p = cross(direction, edge2);
    float const determinant = dot(edge1, p);
    if (std::abs(determinant) < kEpsilon) {
        return false;
    }
    float const inverseDeterminant = 1.0f / determinant;
    math::float3 const t = origin - triangle.v0;
    float const u = dot(t, p) * inverseDeterminant;
    if (u < -1e-6f || u > 1.0f + 1e-6f) {
        return false;
    }
    math::float3 const q = cross(t, edge1);
    float const v = dot(direction, q) * inverseDeterminant;
    if (v < -1e-6f || u + v > 1.0f + 1e-6f) {
        return false;
    }
    float const hitDistance = dot(edge2, q) * inverseDeterminant;
    if (hitDistance <= 1e-6f || hitDistance >= maximumDistance) {
        return false;
    }
    *distance = hitDistance;
    return true;
}

class HeightBvh {
public:
    bool build(Mesh const& source) {
        size_t const triangleCount = source.indices.size() / 3;
        if (triangleCount == 0) {
            return false;
        }
        mTriangles.resize(triangleCount);
        mOrder.resize(triangleCount);
        for (size_t t = 0; t < triangleCount; ++t) {
            mOrder[t] = uint32_t(t);
            math::float3 const p[3] = {
                source.positions[source.indices[t * 3 + 0]],
                source.positions[source.indices[t * 3 + 1]],
                source.positions[source.indices[t * 3 + 2]]
            };
            HeightTriangle& triangle = mTriangles[t];
            triangle.v0 = p[0];
            triangle.v1 = p[1];
            triangle.v2 = p[2];
            triangle.centroid = (p[0] + p[1] + p[2]) / 3.0f;
            triangle.bounds.expand(p[0]);
            triangle.bounds.expand(p[1]);
            triangle.bounds.expand(p[2]);
        }
        mNodes.reserve(triangleCount * 2);
        buildNode(0, uint32_t(triangleCount), 0);
        return !mNodes.empty();
    }

    bool nearest(math::float3 const& origin, math::float3 const& direction,
            float maximumDistance, float* distance) const {
        if (mNodes.empty()) {
            return false;
        }
        math::float3 const inverseDirection{ heightSafeInverse(direction.x),
            heightSafeInverse(direction.y), heightSafeInverse(direction.z) };
        uint32_t stack[64];
        uint32_t stackSize = 0;
        stack[stackSize++] = 0;
        float best = maximumDistance;
        bool hit = false;
        while (stackSize > 0) {
            HeightNode const& node = mNodes[stack[--stackSize]];
            if (!heightRayBounds(node.bounds, origin, inverseDirection, best)) {
                continue;
            }
            if (node.count > 0) {
                for (uint32_t i = 0; i < node.count; ++i) {
                    HeightTriangle const& triangle = mTriangles[mOrder[node.first + i]];
                    float candidate = 0.0f;
                    if (heightRayTriangle(triangle, origin, direction, best, &candidate)) {
                        best = candidate;
                        hit = true;
                    }
                }
            } else if (stackSize + 2 <= 64) {
                stack[stackSize++] = node.left;
                stack[stackSize++] = node.right;
            }
        }
        if (hit) {
            *distance = best;
        }
        return hit;
    }

private:
    uint32_t buildNode(uint32_t begin, uint32_t end, uint32_t depth) {
        uint32_t const nodeIndex = uint32_t(mNodes.size());
        mNodes.push_back({});
        HeightBounds bounds;
        for (uint32_t i = begin; i < end; ++i) {
            HeightTriangle const& triangle = mTriangles[mOrder[i]];
            bounds.expand(triangle.bounds.lo);
            bounds.expand(triangle.bounds.hi);
        }
        mNodes[nodeIndex].bounds = bounds;
        uint32_t const count = end - begin;
        if (count <= 8 || depth >= 28) {
            mNodes[nodeIndex].first = begin;
            mNodes[nodeIndex].count = count;
            return nodeIndex;
        }
        HeightBounds centroids;
        for (uint32_t i = begin; i < end; ++i) {
            centroids.expand(mTriangles[mOrder[i]].centroid);
        }
        math::float3 const extent = centroids.hi - centroids.lo;
        int axis = 0;
        if (extent.y > extent.x) {
            axis = 1;
        }
        if ((axis == 0 ? extent.x : extent.y) < extent.z) {
            axis = 2;
        }
        float const axisExtent = axis == 0 ? extent.x : (axis == 1 ? extent.y : extent.z);
        if (axisExtent < 1e-9f) {
            mNodes[nodeIndex].first = begin;
            mNodes[nodeIndex].count = count;
            return nodeIndex;
        }
        uint32_t const middle = begin + count / 2;
        auto const centroidAxis = [this, axis](uint32_t lhs, uint32_t rhs) {
            float const a = axis == 0 ? mTriangles[lhs].centroid.x
                                      : (axis == 1 ? mTriangles[lhs].centroid.y
                                                   : mTriangles[lhs].centroid.z);
            float const b = axis == 0 ? mTriangles[rhs].centroid.x
                                      : (axis == 1 ? mTriangles[rhs].centroid.y
                                                   : mTriangles[rhs].centroid.z);
            return a < b;
        };
        std::nth_element(mOrder.begin() + begin, mOrder.begin() + middle,
                mOrder.begin() + end, centroidAxis);
        uint32_t const left = buildNode(begin, middle, depth + 1);
        uint32_t const right = buildNode(middle, end, depth + 1);
        mNodes[nodeIndex].left = left;
        mNodes[nodeIndex].right = right;
        return nodeIndex;
    }

    std::vector<HeightTriangle> mTriangles;
    std::vector<uint32_t> mOrder;
    std::vector<HeightNode> mNodes;
};

struct HeightTarget {
    std::vector<math::float3> positions;
    std::vector<math::float3> normals;
    std::vector<uint8_t> covered;
    uint32_t size = 0;

    void reset(uint32_t texels) {
        size = texels;
        size_t const count = size_t(texels) * texels;
        positions.assign(count, math::float3{});
        normals.assign(count, math::float3{ 0.0f, 0.0f, 1.0f });
        covered.assign(count, 0);
    }
};

void rasterizeHeightSurface(Mesh const& mesh, std::vector<uint32_t> const& indices, uint32_t size,
        HeightTarget* target) {
    size_t const triangleCount = indices.size() / 3;
    for (size_t triangle = 0; triangle < triangleCount; ++triangle) {
        uint32_t const i0 = indices[triangle * 3 + 0];
        uint32_t const i1 = indices[triangle * 3 + 1];
        uint32_t const i2 = indices[triangle * 3 + 2];
        math::float2 const uv[3] = { mesh.uvs[i0], mesh.uvs[i1], mesh.uvs[i2] };
        math::float3 const p[3] = { mesh.positions[i0], mesh.positions[i1], mesh.positions[i2] };
        math::float3 const n[3] = { mesh.normals[i0], mesh.normals[i1], mesh.normals[i2] };
        detail::rasterizeUvTriangle(uv, size,
                [&](int x, int y, float w0, float w1, float w2) {
            size_t const texel = size_t(y) * size + size_t(x);
            target->positions[texel] = p[0] * w0 + p[1] * w1 + p[2] * w2;
            target->normals[texel] = normalizedOr(n[0] * w0 + n[1] * w1 + n[2] * w2,
                    math::float3{ 0.0f, 0.0f, 1.0f });
            target->covered[texel] = 1;
                });
    }
}

void dilateHeights(std::vector<uint8_t>* values, std::vector<uint8_t>* covered,
        uint32_t size, uint32_t passes) {
    if (passes == 0) {
        return;
    }
    std::vector<uint8_t> nextValues = *values;
    std::vector<uint8_t> nextCovered = *covered;
    for (uint32_t pass = 0; pass < passes; ++pass) {
        bool changed = false;
        for (int y = 0; y < int(size); ++y) {
            for (int x = 0; x < int(size); ++x) {
                size_t const texel = size_t(y) * size + size_t(x);
                if ((*covered)[texel]) {
                    continue;
                }
                int sum = 0;
                int count = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    int const ny = y + dy;
                    if (ny < 0 || ny >= int(size)) {
                        continue;
                    }
                    for (int dx = -1; dx <= 1; ++dx) {
                        int const nx = x + dx;
                        if (nx < 0 || nx >= int(size) || (dx == 0 && dy == 0)) {
                            continue;
                        }
                        size_t const neighbour = size_t(ny) * size + size_t(nx);
                        if ((*covered)[neighbour]) {
                            sum += (*values)[neighbour];
                            ++count;
                        }
                    }
                }
                if (count > 0) {
                    nextValues[texel] = uint8_t((sum + count / 2) / count);
                    nextCovered[texel] = 1;
                    changed = true;
                }
            }
        }
        values->swap(nextValues);
        covered->swap(nextCovered);
        if (!changed) {
            break;
        }
    }
}

'''
marker = '''} // anonymous namespace

bool bakeDetailNormalMap('''
assert marker in s
s = s.replace(marker, height_code + marker, 1)

public_code = r'''
bool bakeDetailHeightMap(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& lodIndices, DetailHeightOptions const& options,
        DetailHeightResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    if (!source.hasNormals() || !lod.hasNormals() || !source.hasUVs() || !lod.hasUVs() ||
            lodIndices.empty() || lodIndices.size() % 3 != 0 || options.size < 2 ||
            source.indices.empty()) {
        return false;
    }
    for (uint32_t index: lodIndices) {
        if (index >= lod.positions.size()) {
            return false;
        }
        math::float2 const uv = lod.uvs[index];
        if (uv.x < -1e-3f || uv.x > 1.0f + 1e-3f || uv.y < -1e-3f || uv.y > 1.0f + 1e-3f) {
            return false;
        }
    }

    auto const start = HeightClock::now();
    HeightBvh bvh;
    if (!bvh.build(source)) {
        return false;
    }

    math::float3 boundsMin{ std::numeric_limits<float>::max() };
    math::float3 boundsMax{ std::numeric_limits<float>::lowest() };
    for (math::float3 const& position: source.positions) {
        boundsMin = min(boundsMin, position);
        boundsMax = max(boundsMax, position);
    }
    float const diagonal = length(boundsMax - boundsMin);
    if (diagonal <= 0.0f) {
        return false;
    }
    float const maximumDistance = options.maximumDistance > 0.0f
            ? options.maximumDistance : 0.05f * diagonal;
    float const bias = std::max(1e-6f, diagonal * 1e-5f);

    uint32_t const size = options.size;
    HeightTarget target;
    target.reset(size);
    rasterizeHeightSurface(lod, lodIndices, size, &target);

    std::vector<float> heights(size_t(size) * size, 0.0f);
    std::vector<uint8_t> hit(size_t(size) * size, 0);
    size_t lodTexels = 0;
    size_t coveredTexels = 0;
    size_t missedTexels = 0;
    float minHeight = std::numeric_limits<float>::max();
    float maxHeight = std::numeric_limits<float>::lowest();
    double absHeightSum = 0.0;

    for (size_t texel = 0; texel < size_t(size) * size; ++texel) {
        if (!target.covered[texel]) {
            continue;
        }
        ++lodTexels;
        math::float3 const position = target.positions[texel];
        math::float3 const normal = target.normals[texel];
        float positive = 0.0f;
        float negative = 0.0f;
        bool const hasPositive = bvh.nearest(position + normal * bias, normal,
                maximumDistance, &positive);
        bool const hasNegative = bvh.nearest(position - normal * bias, -normal,
                maximumDistance, &negative);
        if (!hasPositive && !hasNegative) {
            ++missedTexels;
            continue;
        }
        float height = 0.0f;
        if (hasPositive && hasNegative) {
            height = positive <= negative ? positive : -negative;
        } else if (hasPositive) {
            height = positive;
        } else {
            height = -negative;
        }
        heights[texel] = height;
        hit[texel] = 1;
        ++coveredTexels;
        minHeight = std::min(minHeight, height);
        maxHeight = std::max(maxHeight, height);
        absHeightSum += double(std::abs(height));
    }

    if (coveredTexels == 0) {
        return false;
    }
    float const heightRange = std::max(std::abs(minHeight), std::abs(maxHeight));
    std::vector<uint8_t> values(size_t(size) * size, 128);
    if (heightRange > 1e-8f) {
        float const scale = 127.5f / heightRange;
        for (size_t texel = 0; texel < size_t(size) * size; ++texel) {
            if (hit[texel]) {
                float const encoded = 127.5f + heights[texel] * scale;
                values[texel] = uint8_t(std::clamp(std::lround(encoded), 0L, 255L));
            }
        }
    }
    dilateHeights(&values, &hit, size, options.dilationTexels);

    double worldArea = 0.0;
    double uvArea = 0.0;
    for (size_t triangle = 0; triangle + 2 < lodIndices.size(); triangle += 3) {
        uint32_t const i0 = lodIndices[triangle + 0];
        uint32_t const i1 = lodIndices[triangle + 1];
        uint32_t const i2 = lodIndices[triangle + 2];
        math::float3 const e1 = lod.positions[i1] - lod.positions[i0];
        math::float3 const e2 = lod.positions[i2] - lod.positions[i0];
        math::float2 const d1 = lod.uvs[i1] - lod.uvs[i0];
        math::float2 const d2 = lod.uvs[i2] - lod.uvs[i0];
        worldArea += 0.5 * double(length(cross(e1, e2)));
        uvArea += 0.5 * double(std::abs(d1.x * d2.y - d2.x * d1.y));
    }
    float const worldPerUv = uvArea > 1e-12 ? float(std::sqrt(worldArea / uvArea)) : 0.0f;

    result->size = size;
    result->values = std::move(values);
    result->lodTexels = lodTexels;
    result->coveredTexels = coveredTexels;
    result->missedTexels = missedTexels;
    result->minHeight = minHeight;
    result->maxHeight = maxHeight;
    result->meanAbsHeight = float(absHeightSum / double(coveredTexels));
    result->heightRange = heightRange;
    result->recommendedUvScale = worldPerUv > 1e-6f ? heightRange / worldPerUv : 0.02f;
    result->bakeMs = std::chrono::duration<double, std::milli>(HeightClock::now() - start).count();
    return true;
}

'''
marker2 = '''} // namespace manymesh
} // namespace filament'''
assert marker2 in s
s = s.replace(marker2, public_code + marker2, 1)
p.write_text(s, encoding='utf-8')
print('DetailBake.cpp patched')
