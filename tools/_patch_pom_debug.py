from pathlib import Path
p=Path('samples/mm_bench.cpp')
s=p.read_text(encoding='utf-8')
old='''    if (g_material->hasParameter("heightMap") && g_detailHeightTexture == nullptr) {
        g_detailHeightTexture = createNeutralHeightTexture(engine);
    }

    g_materialInstance = g_material->createInstance();
'''
new='''    if (g_material->hasParameter("heightMap") && g_detailHeightTexture == nullptr) {
        g_detailHeightTexture = createNeutralHeightTexture(engine);
    }
    std::printf("parallax: path='%s' texture=%d scale=%.6f strength=%.3f layers=%d "
                "hasPom=%d hasHeight=%d\\n",
            g_detailHeightPath.c_str(), g_detailHeightTexture != nullptr ? 1 : 0,
            g_pomScale, g_pomStrength, g_pomLayers,
            g_material->hasParameter("pomScale") ? 1 : 0,
            g_material->hasParameter("heightMap") ? 1 : 0);
    std::fflush(stdout);

    g_materialInstance = g_material->createInstance();
'''
assert old in s
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('debug added')
