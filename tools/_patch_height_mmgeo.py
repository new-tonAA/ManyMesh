from pathlib import Path
p = Path('tools/mmgeo/src/main.cpp')
s = p.read_text(encoding='utf-8')

old = '''    //! 0 disables the detail bake; otherwise the square size of the tangent-space normal map.
    uint32_t bakeNormalSize = 0;
'''
new = old + '''    //! 0 disables the displacement bake; otherwise the square size of the height map.
    uint32_t bakeHeightSize = 0;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''  --bake-normal N      bake the normals lost by the selected LOD into an NxN tangent-space
                       normal map (detail-normal.png); 0 disables it (default: 0)
'''
new = old + '''  --bake-height N      bake the displacement between the source and the selected LOD into an
                       NxN height map (detail-height.png); 0 disables it (default: 0)
'''
assert old in s
s = s.replace(old, new, 1)

marker = '''// Source AO in the source UV layout. This is a material-level asset: it is shared by every LOD
'''
write_fn = r'''bool writeDetailHeightPng(DetailHeightResult const& bake, char const* path) {
    image::LinearImage image(bake.size, bake.size, 3);
    for (uint32_t y = 0; y < bake.size; ++y) {
        float* const row = image.getPixelRef(0, y);
        for (uint32_t x = 0; x < bake.size; ++x) {
            float const value = float(bake.values[size_t(y) * bake.size + x]) / 255.0f;
            row[x * 3 + 0] = value;
            row[x * 3 + 1] = value;
            row[x * 3 + 2] = value;
        }
    }
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        std::cerr << "Could not open '" << path << "' for writing" << std::endl;
        return false;
    }
    return image::ImageEncoder::encode(file, image::ImageEncoder::Format::PNG_LINEAR, image, "",
            path);
}

'''
assert marker in s
s = s.replace(marker, write_fn + marker, 1)

marker = '''struct GeometryOutput {
'''
bake_fn = r'''// Bakes the source displacement into the selected LOD's UV layout. The map is signed around
// 0.5, so a material can sample it with iterative parallax mapping without a second scale map.
void bakeDetailHeight(Mesh const& source, Mesh const& lod,
        std::vector<uint32_t> const& indices, Options const& options) {
    if (options.bakeHeightSize == 0) {
        return;
    }
    DetailHeightOptions bakeOptions;
    bakeOptions.size = options.bakeHeightSize;
    DetailHeightResult bake;
    if (!bakeDetailHeightMap(source, lod, indices, bakeOptions, &bake)) {
        std::cerr << "  detail height bake skipped: both meshes need normals and UVs, every "
                     "LOD UV must lie in [0,1], and the LOD must overlap the source surface"
                  << std::endl;
        return;
    }
    std::string const path = join(options.outDir, "detail-height.png");
    if (!writeDetailHeightPng(bake, path.c_str())) {
        std::cerr << "  could not write '" << path << "'" << std::endl;
        return;
    }
    std::string const sidecarPath = path + ".txt";
    std::ofstream sidecar(sidecarPath, std::ios::trunc);
    if (sidecar) {
        sidecar << "heightRange=" << bake.heightRange << "\n"
                << "recommendedUvScale=" << bake.recommendedUvScale << "\n";
    }
    printf("  baked %s (%ux%u, %zu covered texels, %zu misses, signed height %.5f..%.5f, "
           "mean |h| %.5f, range %.5f, recommended parallax scale %.5f, %.1f ms)\n",
            path.c_str(), bake.size, bake.size, bake.coveredTexels, bake.missedTexels,
            bake.minHeight, bake.maxHeight, bake.meanAbsHeight, bake.heightRange,
            bake.recommendedUvScale, bake.bakeMs);
}

'''
assert marker in s
s = s.replace(marker, bake_fn + marker, 1)

old = '''        { "bake-normal", utils::getopt::required_argument, 0, 'B' },
'''
new = old + '''        { "bake-height", utils::getopt::required_argument, 0, 'Y' },
'''
assert old in s
s = s.replace(old, new, 1)

old = '''            case 'B':
                options->bakeNormalSize = uint32_t(std::max(0, atoi(arg)));
                break;
'''
new = old + '''            case 'Y':
                options->bakeHeightSize = uint32_t(std::max(0, atoi(arg)));
                break;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''        bakeDetailNormal(mesh, dagMesh, outputFromDagSelection(selection).indices, options);
'''
new = old + '''        bakeDetailHeight(mesh, dagMesh, outputFromDagSelection(selection).indices, options);
'''
assert old in s
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('mmgeo patched')
