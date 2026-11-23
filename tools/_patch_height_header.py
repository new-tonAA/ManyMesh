from pathlib import Path
p = Path('libs/manymesh/include/manymesh/DetailBake.h')
s = p.read_text(encoding='utf-8')
marker = '''/**
 * Bakes the difference between the source surface normal and the LOD surface normal into a
 * tangent-space normal map.'''
insert = '''struct DetailHeightOptions {
    //! Width and height of the square height map.
    uint32_t size = 512;

    //! Texels the source height field is grown across chart borders.
    uint32_t dilationTexels = 4;

    //! Longest displacement searched along the LOD normal, in world units. 0 derives 5% of the
    //! source bounds diagonal. A larger value can bridge a very coarse chord but also risks
    //! snapping to a different layer of the model.
    float maximumDistance = 0.0f;
};

struct DetailHeightResult {
    uint32_t size = 0;

    //! One byte per texel, row-major, with v increasing with the row index. 128 is the neutral
    //! (no displacement) value; lower values put the source surface behind the LOD, higher
    //! values put it in front.
    std::vector<uint8_t> values;

    //! Texels covered by the low-poly UV layout.
    size_t lodTexels = 0;

    //! Texels where a source surface point was found along the LOD normal.
    size_t coveredTexels = 0;

    //! Covered texels whose ray found no source surface within the search distance.
    size_t missedTexels = 0;

    //! Signed displacement of the source surface relative to the LOD along the LOD normal, in
    //! world units. Positive means the source surface is in front of the LOD.
    float minHeight = 0.0f;
    float maxHeight = 0.0f;
    float meanAbsHeight = 0.0f;

    //! Largest absolute displacement; the map normalizes to this range.
    float heightRange = 0.0f;

    //! Suggested UV-space parallax scale for a shader that treats 0.5 as neutral:
    //! uvOffset = (height - 0.5) * 2 * recommendedUvScale * viewTangent.xy / viewTangent.z.
    float recommendedUvScale = 0.0f;

    //! Wall time of BVH construction, rasterization and sampling, in milliseconds.
    double bakeMs = 0.0;
};

'''
assert marker in s
s = s.replace(marker, insert + marker, 1)
old = '''bool bakeDetailNormalMap(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& lodIndices, DetailBakeOptions const& options,
        DetailBakeResult* result);
'''
new = old + '''
/**
 * Bakes the signed displacement between the source surface and the LOD into the LOD's UV
 * layout.
 *
 * For every texel covered by the LOD, a ray is traced from the LOD surface along both
 * directions of the interpolated LOD normal, and the nearest source hit is stored. This is the
 * missing piece a tangent-space normal map cannot provide: a normal map changes shading, while
 * this map changes where the shading is sampled. It lets a fragment shader do iterative
 * parallax mapping and recover some of the surface displacement, self-occlusion and
 * high-frequency detail lost by a coarse chord.
 *
 * The source and LOD must share a UV parameterization and every LOD UV must lie in [0,1].
 * Returns false if either mesh lacks normals or UVs, if no texel is covered, or if no source
 * hit is found. Silhouette coverage still cannot be recovered by shading.
 */
bool bakeDetailHeightMap(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& lodIndices, DetailHeightOptions const& options,
        DetailHeightResult* result);
'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('DetailBake.h patched')
