# Current-source mmgeo provenance

The 2026-11-23 cluster-cut parameter and quality screens used the same current
`mmgeo` executable. Its parent Git revision alone is insufficient provenance
because the source worktree was dirty. This record archives the relevant
ManyMesh source delta and the hashes needed to identify the binary and scripts.

## Pinned inputs

- Parent revision: `2d417cacdeb545a13e6bfb7192310191e60670d6`.
- Source delta: [patch](current_mmgeo_source_patch_20261123.diff), SHA-256
  `fe20c1155af2c861764670397948776ca458902b8f71f1669ca0731c2dc7f6a3`.
- Reconstructed `mmgeo` binary: SHA-256
  `8820629cbd6ffb1d490c4a1b3e54926ba5a194ebbe7b8cbecc1ae17130122e4e`.
- `tools/mmgeo/src/main.cpp`: SHA-256
  `c044d8d026b32ccb335e99a8c9b0ef4e2ffc766e51455647f29f75bdcf6edea4`.
- The patch covers the changed ManyMesh headers, implementation files, test
  source, and `mmgeo` entry point. Individual source hashes and the parameter
  sweep/score script hashes are in the [provenance manifest](current_mmgeo_source_provenance_20261123.json).
- Build cache: CMake 3.31.6, Visual Studio 17 2022 generator, x64. The exact
  compiler version and original configure/build command were not archived.

The patch reverse-check passed against the current worktree. To reconstruct the
source in a separate checkout, start from the parent revision and apply the
patch:

```powershell
git checkout --detach 2d417cacdeb545a13e6bfb7192310191e60670d6
git apply tools/mmtrain/current_mmgeo_source_patch_20261123.diff
```

This reconstructs the recorded source delta, not a bit-identical build. The
compiler version and original configure/build command remain missing. Do not
describe this artifact as complete build reproducibility until those inputs are
recorded and the binary hash is reproduced from a clean build.

The relevant results are the [fixed-default eligibility audit](CURRENT_SOURCE_CLUSTERLOD_AUDIT_20261123.md),
[parameter-sweep screen](CURRENT_SOURCE_CLUSTERLOD_PARAMETER_SWEEP_20261123.md),
and [matched-face control screen](CURRENT_SOURCE_MATCHED_FACE_CONTROLS_20261123.md).
